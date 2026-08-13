# -*- coding: utf-8 -*-
# based on https://github.com/ui/django-post_office/blob/master/post_office/models.py

import re
from collections import namedtuple

try:
    from post_office.compat import smart_text
except ImportError:
    from django.utils.encoding import smart_str as smart_text

import datetime
import html
import logging
import firebase_admin
from firebase_admin import credentials, exceptions, messaging
from google.auth.transport.requests import Request as GoogleAuthRequest
from six import python_2_unicode_compatible

from django.db import models
from django.utils.html import strip_tags
from django.utils.timezone import now
from django.utils.translation import ugettext_lazy as _
from django.template.backends.django import DjangoTemplates
from django.template import Context

from .settings import (context_field_class, get_android_channel_id, get_firebase_key_path,
                       get_invalid_token_handler, get_log_level, get_max_body_length, get_max_retries,
                       get_max_title_length, get_retry_interval, get_send_system_notification,
                       get_template_engine, get_ttl)


logger = logging.getLogger(__name__)

PRIORITY = namedtuple('PRIORITY', 'low medium high now')._make(range(4))
STATUS = namedtuple('STATUS', 'sent failed queued')._make(range(3))

FIREBASE_KEY_PATH = get_firebase_key_path()
FIREBASE_CREDENTIALS = credentials.Certificate(FIREBASE_KEY_PATH) if FIREBASE_KEY_PATH else None
FIREBASE_APP = firebase_admin.initialize_app(FIREBASE_CREDENTIALS) if FIREBASE_CREDENTIALS else None

NON_ANCHOR_TAGS_RE = re.compile(r'(<[^aA/].*?>|</[^aA].*?>)')
# Значение атрибута может быть в двойных кавычках, в одинарных или вовсе без них
FIRST_ANCHOR_HREF_RE = re.compile(r'<a\s[^>]*?href=(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))', re.IGNORECASE)
DANGLING_TAG_RE = re.compile(r'<[^>]*$')
# Теги, разделяющие строки и абзацы. Их нужно заменять переносом, а не просто вырезать,
# иначе соседние строки склеиваются в одно слово
LINE_BREAK_TAGS_RE = re.compile(
    r'</?(?:br|p|div|li|ul|ol|tr|table|h[1-6]|blockquote|section|article|hr)\b[^>]*>',
    re.IGNORECASE)

# Лимит размера сообщения на стороне FCM и APNs. С системным уведомлением заголовок и текст
# попадают в payload дважды: в блок notification (alert) и в data, поэтому бюджет делится
# между копиями.
MAX_PAYLOAD_BYTES = 4096
PAYLOAD_OVERHEAD_BYTES = 512
PAYLOAD_COPIES = 2
# Минимум, который должен остаться заголовку и тексту после вычета адреса перехода
MIN_TEXT_BUDGET_BYTES = 512

ELLIPSIS = '...'

# Ограничения записи в Log: `message` — TEXT, `exception_type` — varchar(255)
MAX_LOGGED_TOKEN_ERRORS = 50
MAX_LOG_MESSAGE_LENGTH = 16000
MAX_EXCEPTION_TYPE_LENGTH = 255

# Ошибки, при которых имеет смысл повторить отправку позже.
TRANSIENT_ERROR_CODES = frozenset([
    exceptions.UNAVAILABLE,
    exceptions.INTERNAL,
    exceptions.DEADLINE_EXCEEDED,
    exceptions.RESOURCE_EXHAUSTED,
    exceptions.ABORTED,
    exceptions.UNKNOWN,
])

# Ошибки подготовки сообщения, повторять которые бессмысленно.
PERMANENT_EXCEPTIONS = (ValueError, TypeError, KeyError, AttributeError)


DeliveryResult = namedtuple('DeliveryResult',
                            'status message exception_type transient invalid_tokens success_count failure_count')


class PushDeliveryError(Exception):
    """
    Ошибка доставки уведомления. Поднимается в режиме массовой отправки, где решение
    о статусе принимает вызывающий код.
    """
    def __init__(self, message, transient=False):
        super(PushDeliveryError, self).__init__(message)
        self.transient = transient


def is_transient_error(exception):
    if isinstance(exception, exceptions.FirebaseError):
        return exception.code in TRANSIENT_ERROR_CODES
    return not isinstance(exception, PERMANENT_EXCEPTIONS)


def is_invalid_token_error(exception):
    return isinstance(exception, (messaging.UnregisteredError, messaging.SenderIdMismatchError))


def mask_token(token):
    """
    Токен — это учётные данные устройства, в логи пишем только опознавательный префикс.
    """
    return '{}...'.format(token[:10]) if len(token) > 10 else token


def handle_invalid_tokens(tokens):
    """
    Передаёт отвергнутые FCM токены обработчику проекта, чтобы тот удалил их у получателей.
    """
    if not tokens:
        return
    handler = get_invalid_token_handler()
    if handler is None:
        return
    try:
        handler(tokens)
    except Exception:
        logger.exception('Invalid token handler has failed for %d tokens', len(tokens))


def warmup_credentials():
    """
    Обновляет токен доступа до старта потоков отправки. Иначе каждый поток обнаруживает
    просроченные учётные данные и запускает свой refresh, а `firebase_admin` не перехватывает
    `RefreshError` внутри отправки и роняет всю пачку сообщений целиком.
    """
    if not FIREBASE_APP:
        return
    try:
        credential = FIREBASE_APP.credential.get_credential()
        if not credential.valid:
            credential.refresh(GoogleAuthRequest())
    except Exception:
        logger.exception('Failed to warm up firebase credentials')


def extract_url(text):
    """
    Достаёт адрес перехода из первой ссылки текста. Ссылки переживают `render_and_clean`
    (`NON_ANCHOR_TAGS_RE` их не вырезает) именно ради этого: в самом уведомлении разметки
    быть не может, а мобильному приложению нужен адрес, чтобы открыть нужный экран.
    """
    match = FIRST_ANCHOR_HREF_RE.search(text or '')
    if not match:
        return ''
    url = next(group for group in match.groups() if group is not None)
    return html.unescape(url).strip()


def break_lines(text):
    """
    Ставит перенос строки на место тегов, разделяющих строки и абзацы, — до того, как теги
    будут вырезаны.
    """
    return LINE_BREAK_TAGS_RE.sub('\n', text or '')


def normalize_whitespace(text, keep_line_breaks=True):
    """
    Сворачивает пробелы внутри строк и убирает пустые строки. Переносы сохраняются: текст
    уведомления обычно состоит из нескольких строк, и в сплошном виде читается плохо.
    """
    lines = [' '.join(line.split()) for line in (text or '').splitlines()]
    lines = [line for line in lines if line]
    return ('\n' if keep_line_breaks else ' ').join(lines)


def truncate_by_chars(text, max_length):
    if len(text) <= max_length:
        return text
    return text[:max(max_length - len(ELLIPSIS), 0)].rstrip() + ELLIPSIS


def truncate_by_bytes(text, max_bytes):
    encoded = text.encode('utf-8')
    if len(encoded) <= max_bytes:
        return text
    limit = max(max_bytes - len(ELLIPSIS), 0)
    return encoded[:limit].decode('utf-8', 'ignore').rstrip() + ELLIPSIS


@python_2_unicode_compatible
class PushNotification(models.Model):
    """
    A model to hold notification information.
    """
    PRIORITY_CHOICES = [(PRIORITY.low, _("low")), (PRIORITY.medium, _("medium")),
                        (PRIORITY.high, _("high")), (PRIORITY.now, _("now"))]
    STATUS_CHOICES = [(STATUS.sent, _("sent")), (STATUS.failed, _("failed")),
                      (STATUS.queued, _("queued"))]

    to = models.TextField(_("Notification To"))
    title = models.CharField(_("Title"), max_length=989, blank=True)
    text = models.TextField(_("Text"), blank=True)
    status = models.PositiveSmallIntegerField(_("Status"), choices=STATUS_CHOICES,
                                              db_index=True, blank=True, null=True)
    priority = models.PositiveSmallIntegerField(_("Priority"), choices=PRIORITY_CHOICES, blank=True, null=True)
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    last_updated = models.DateTimeField(db_index=True, auto_now=True)
    scheduled_time = models.DateTimeField(_('The scheduled sending time'), blank=True, null=True, db_index=True)
    number_of_retries = models.PositiveIntegerField(_("Number of retries"), null=True, blank=True)
    template = models.ForeignKey('post_office.EmailTemplate', blank=True, null=True,
                                 verbose_name=_('Template'), on_delete=models.CASCADE)
    context = context_field_class(_('Context'), blank=True, null=True)

    class Meta:
        app_label = 'fcm_async'
        verbose_name = _('Push notification')
        verbose_name_plural = _('Push notifications')

    def __init__(self, *args, **kwargs):
        super(PushNotification, self).__init__(*args, **kwargs)
        self._cached_notification_message = None

    def __str__(self):
        if self.template and self.template.subject:
            return self.template.subject
        elif self.title:
            return self.title
        else:
            return u'%s: %s' % (self._meta.verbose_name, self.id)

    def notification_message(self):
        """
        Returns dict for sending.
        """
        if self._cached_notification_message:
            return self._cached_notification_message

        return self.prepare_notification_message()

    def render_and_clean(self, engine, template_code, context_dict):
        context = Context(context_dict, autoescape=False)
        template = engine.from_string(template_code)
        text = template.template.render(context)
        return NON_ANCHOR_TAGS_RE.sub(r'', break_lines(text))

    def prepare_notification_message(self):
        """
        Returns a django dict
        """
        if self.template is not None:
            engine = get_template_engine()
            if isinstance(engine, DjangoTemplates):
                title = self.render_and_clean(engine, self.template.subject, self.context)
                content = self.template.html_content if self.template.html_content else self.template.content
                text = self.render_and_clean(engine, content, self.context)
            else:
                title = engine.from_string(self.template.subject).render(self.context)
                text = engine.from_string(self.template.content).render(self.context)
        else:
            title = smart_text(self.title)
            text = self.text

        msg = {'title': title, 'text': text}

        self._cached_notification_message = msg
        return msg

    def get_tokens(self):
        return [token.strip() for token in self.to.splitlines() if token.strip()]

    def get_payload(self, msg, system_notification=None):
        """
        Готовит заголовок, текст и адрес перехода. Шаблоны уведомлений общие с email, поэтому
        текст может содержать разметку и не влезать в лимит размера сообщения FCM.

        Если уведомление показывает операционная система, разметка из текста убирается, а адрес
        первой ссылки уезжает в отдельное значение: кликабельную ссылку в системном уведомлении
        показать нельзя, переход по нажатию выполняет приложение. Если уведомление рисует
        приложение, текст отдаётся со ссылками как есть — приложение разбирает их само.
        """
        if system_notification is None:
            system_notification = get_send_system_notification()

        # Заголовок остаётся в одну строку, его перенос показывают не все оболочки
        title = normalize_whitespace(html.unescape(strip_tags(msg['title'] or '')),
                                     keep_line_breaks=False)

        if system_notification:
            url = extract_url(msg['text'])
            body = normalize_whitespace(html.unescape(strip_tags(break_lines(msg['text']))))
            copies = PAYLOAD_COPIES
        else:
            url = ''
            body = normalize_whitespace(break_lines(msg['text']))
            copies = 1

        title = truncate_by_chars(title, get_max_title_length())
        body = truncate_by_chars(body, get_max_body_length())

        # Адрес попадает в payload один раз и обрезке не подлежит, иначе переход сломается,
        # поэтому его размер вычитается из бюджета до деления между копиями заголовка и текста.
        budget = MAX_PAYLOAD_BYTES - PAYLOAD_OVERHEAD_BYTES - len(url.encode('utf-8'))
        if budget < MIN_TEXT_BUDGET_BYTES:
            # Уведомление без перехода лучше, чем сообщение, которое FCM отвергнет целиком
            url = ''
            budget = MAX_PAYLOAD_BYTES - PAYLOAD_OVERHEAD_BYTES
        budget //= copies
        title = truncate_by_bytes(title, budget // 4)
        body = truncate_by_bytes(body, budget - len(title.encode('utf-8')))

        if not system_notification:
            # Обрезка могла разорвать тег, его хвост убираем, чтобы не ломать разбор разметки
            body = DANGLING_TAG_RE.sub('', body)

        return title, body, url

    def send_firebase(self, msg, tokens=None, dry_run=False, system_notification=None):
        """
        Отправляет уведомление всем токенам получателя и возвращает `messaging.BatchResponse`.

        В зависимости от `SEND_SYSTEM_NOTIFICATION` собирается один из двух вариантов сообщения:

        * с блоком `notification` — уведомление показывает операционная система, доставка
          надёжнее, но приложение получает те же данные и рисует своё уведомление вторым;
        * без него — приходит только `data`, уведомление целиком на стороне приложения, зато
          ОС притормаживает такие сообщения, особенно на iOS.
        """
        if tokens is None:
            tokens = self.get_tokens()
        if system_notification is None:
            system_notification = get_send_system_notification()
        title, body, url = self.get_payload(msg, system_notification)

        data = {'title': title, 'body': body}
        if url:
            data['url'] = url

        if system_notification:
            notification = messaging.Notification(title=title, body=body)
            apns = messaging.APNSConfig(
                headers={'apns-priority': '10', 'apns-push-type': 'alert'},
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(
                        alert=messaging.ApsAlert(title=title, body=body),
                        sound='default',
                        mutable_content=True,
                    ),
                ),
            )
            android_notification = messaging.AndroidNotification(
                title=title,
                body=body,
                # Начиная с Android 8 звук и всплытие определяет канал уведомлений, а эти
                # два поля учитываются только на более старых версиях
                default_sound=True,
                priority='high',
                channel_id=get_android_channel_id(),
            )
        else:
            notification = None
            # Фоновая доставка на iOS допускает только приоритет 5, с приоритетом 10 APNs
            # отвергает сообщение без alert
            apns = messaging.APNSConfig(
                headers={'apns-priority': '5', 'apns-push-type': 'background'},
                payload=messaging.APNSPayload(aps=messaging.Aps(content_available=True)),
            )
            android_notification = None

        firebase_message = messaging.MulticastMessage(
            tokens=tokens,
            notification=notification,
            apns=apns,
            android=messaging.AndroidConfig(
                ttl=datetime.timedelta(seconds=get_ttl()),
                # Высокий приоритет и для data-сообщения: иначе Android откладывает доставку
                # до выхода устройства из Doze
                priority='high',
                notification=android_notification,
            ),
            data=data,
        )
        return messaging.send_each_for_multicast(firebase_message, dry_run=dry_run)

    def deliver(self):
        """
        Отправляет уведомление и возвращает `DeliveryResult`. Не обращается к базе данных,
        поэтому может вызываться из потоков массовой отправки.
        """
        if not FIREBASE_APP:
            return DeliveryResult(STATUS.failed, 'Firebase application is not configured',
                                  'ImproperlyConfigured', False, [], 0, 0)

        tokens = self.get_tokens()
        if not tokens:
            return DeliveryResult(STATUS.failed, 'Recipient tokens list is empty', 'ValueError', False, [], 0, 0)

        try:
            batch_response = self.send_firebase(self.notification_message(), tokens)
        except Exception as e:
            return DeliveryResult(STATUS.failed, str(e), type(e).__name__, is_transient_error(e),
                                  [], 0, len(tokens))

        return self.process_batch_response(tokens, batch_response)

    def process_batch_response(self, tokens, batch_response):
        """
        Разбирает ответ FCM. Ошибки отдельных токенов не поднимают исключение, поэтому без
        разбора ответа недоставка выглядит как успешная отправка.
        """
        messages, exception_types, invalid_tokens = [], [], []
        transient = False

        for token, response in zip(tokens, batch_response.responses):
            if response.success:
                continue
            exception = response.exception
            messages.append('{}: {}'.format(mask_token(token), exception))
            exception_types.append(type(exception).__name__)
            if is_invalid_token_error(exception):
                invalid_tokens.append(token)
            if is_transient_error(exception):
                transient = True

        success_count = batch_response.success_count
        failure_count = batch_response.failure_count
        status = STATUS.sent if success_count else STATUS.failed

        if failure_count:
            message = '{} of {} tokens failed: {}'.format(
                failure_count, len(tokens), '; '.join(messages[:MAX_LOGGED_TOKEN_ERRORS]))
            message = truncate_by_chars(message, MAX_LOG_MESSAGE_LENGTH)
        else:
            message = ''

        exception_type = truncate_by_chars(', '.join(sorted(set(exception_types))), MAX_EXCEPTION_TYPE_LENGTH)

        return DeliveryResult(status, message, exception_type, transient,
                              invalid_tokens, success_count, failure_count)

    def should_retry(self, result):
        return (result.status == STATUS.failed and result.transient
                and (self.number_of_retries or 0) < get_max_retries())

    def dispatch(self, log_level=None, commit=True):
        """
        Sends notification and log the result.
        """
        if not FIREBASE_APP:
            return STATUS.failed

        result = self.deliver()
        handle_invalid_tokens(result.invalid_tokens)

        # If run in a bulk sending mode, reraise and let the outer
        # layer handle the failure
        if not commit:
            if result.status == STATUS.failed:
                raise PushDeliveryError(result.message or 'Push notification delivery failed',
                                        transient=result.transient)
            return result.status

        update_fields = ['status', 'last_updated']
        if self.should_retry(result):
            self.status = STATUS.queued
            self.number_of_retries = (self.number_of_retries or 0) + 1
            self.scheduled_time = now() + get_retry_interval()
            update_fields += ['number_of_retries', 'scheduled_time']
        else:
            self.status = result.status
        self.save(update_fields=update_fields)

        if log_level is None:
            log_level = get_log_level()

        # If log level is 0, log nothing, 1 logs only sending failures
        # and 2 means log both successes and failures
        if log_level == 1:
            if result.status == STATUS.failed:
                self.logs.create(status=result.status, message=result.message,
                                 exception_type=result.exception_type)
        elif log_level == 2:
            self.logs.create(status=result.status, message=result.message,
                             exception_type=result.exception_type)

        return result.status

    def save(self, *args, **kwargs):
        self.full_clean()
        return super(PushNotification, self).save(*args, **kwargs)


@python_2_unicode_compatible
class Log(models.Model):
    """
    A model to record sending email sending activities.
    """

    STATUS_CHOICES = [(STATUS.sent, _("sent")), (STATUS.failed, _("failed"))]

    notification = models.ForeignKey(PushNotification, editable=False, related_name='logs',
                                     verbose_name=_('Push notification'), on_delete=models.CASCADE)
    date = models.DateTimeField(auto_now_add=True)
    status = models.PositiveSmallIntegerField(_('Status'), choices=STATUS_CHOICES)
    exception_type = models.CharField(_('Exception type'), max_length=255, blank=True)
    message = models.TextField(_('Message'))

    class Meta:
        app_label = 'fcm_async'
        verbose_name = _("Log")
        verbose_name_plural = _("Logs")

    def __str__(self):
        ret = 'date'
        try:
            from post_office.compat import text_type
            ret = text_type(self.date)
        except ImportError:
            ret = str(self.date)

        return ret
