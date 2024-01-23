# -*- coding: utf-8 -*-
# based on https://github.com/ui/django-post_office/blob/master/post_office/models.py

import re
from collections import namedtuple

try:
    from post_office.compat import smart_text
except ImportError:
    from django.utils.encoding import smart_str as smart_text

import datetime
import firebase_admin
from firebase_admin import credentials, messaging

from django.db import models
from django.utils.encoding import python_2_unicode_compatible
from django.utils.translation import ugettext_lazy as _
from django.template.backends.django import DjangoTemplates
from django.template import Context

from .settings import context_field_class, get_log_level, get_template_engine, get_firebase_key_path


PRIORITY = namedtuple('PRIORITY', 'low medium high now')._make(range(4))
STATUS = namedtuple('STATUS', 'sent failed queued')._make(range(3))

FIREBASE_KEY_PATH = get_firebase_key_path()
FIREBASE_CREDENTIALS = credentials.Certificate(FIREBASE_KEY_PATH) if FIREBASE_KEY_PATH else None
FIREBASE_APP = firebase_admin.initialize_app(FIREBASE_CREDENTIALS) if FIREBASE_CREDENTIALS else None

NON_ANCHOR_TAGS_RE = re.compile(r'(<[^aA/].*?>|</[^aA].*?>)')


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
        return NON_ANCHOR_TAGS_RE.sub(r'', text)

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

    def send_firebase(self, msg):
        firebase_message = messaging.MulticastMessage(
            tokens=self.to.splitlines(),
            apns=messaging.APNSConfig(
                headers={'apns-priority': '5', 'apns-push-type': 'background'},
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(content_available=True),
                ),
            ),
            android=messaging.AndroidConfig(
                ttl=datetime.timedelta(seconds=3600),
                priority='normal',
            ),
            data={'title': msg['title'], 'body': msg['text']}
        )
        messaging.send_multicast(firebase_message)

    def dispatch(self, log_level=None, commit=True):
        """
        Sends email and log the result.
        """
        if not FIREBASE_APP:
            return STATUS.failed
        try:
            self.send_firebase(self.notification_message())
            status = STATUS.sent
            message = ''
            exception_type = ''
        except Exception as e:
            status = STATUS.failed
            message = str(e)
            exception_type = type(e).__name__

            # If run in a bulk sending mode, reraise and let the outer
            # layer handle the exception
            if not commit:
                raise

        if commit:
            self.status = status
            self.save(update_fields=['status'])

            if log_level is None:
                log_level = get_log_level()

            # If log level is 0, log nothing, 1 logs only sending failures
            # and 2 means log both successes and failures
            if log_level == 1:
                if status == STATUS.failed:
                    self.logs.create(status=status, message=message,
                                     exception_type=exception_type)
            elif log_level == 2:
                self.logs.create(status=status, message=message,
                                 exception_type=exception_type)

        return status

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
