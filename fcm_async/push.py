# -*- coding: utf-8 -*-
# based on https://github.com/ui/django-post_office/blob/master/post_office/mail.py

from multiprocessing import Pool
from multiprocessing.dummy import Pool as ThreadPool
from post_office.models import EmailTemplate
from post_office.utils import get_email_template, split_emails, parse_priority

from django.db.models import F, Q, Value
from django.db.models.functions import Coalesce
from django.db import connection as db_connection
from django.template import Context, Template
from django.utils.timezone import now

from .models import (PushNotification, Log, PRIORITY, STATUS, FIREBASE_APP, DeliveryResult,
                     handle_invalid_tokens, is_transient_error, warmup_credentials)
from .settings import (get_batch_size, get_log_level, get_retry_interval, get_sending_order,
                       get_threads_per_process)
from .logutils import setup_loghandlers


logger = setup_loghandlers("INFO")


def create(recipients, title='', text='', context=None, scheduled_time=None, template=None,
           priority=None, render_on_delivery=False, commit=True):
    """
    Creates an notification from supplied keyword arguments. If template is
    specified, notification title and content will be rendered during delivery.
    """
    priority = parse_priority(priority)
    status = None if priority == PRIORITY.now else STATUS.queued

    if context is None:
        context = ''

    # If notification is to be rendered during delivery, save all necessary
    # information
    if render_on_delivery:
        notification = PushNotification(
            to=recipients,
            scheduled_time=scheduled_time,
            priority=priority,
            status=status,
            context=context,
            template=template,
        )

    else:
        if template:
            title = template.subject
            text = template.content

        _context = Context(context or {})
        title = Template(title).render(_context)
        text = Template(text).render(_context)

        notification = PushNotification(
            to=recipients,
            title=title,
            text=text,
            scheduled_time=scheduled_time,
            priority=priority,
            status=status,
        )

    if commit:
        notification.save()

    return notification


def send(recipients, template=None, context=None, title='',
         text='', scheduled_time=None,
         priority=None, render_on_delivery=False,
         log_level=None, commit=True, language=''):

    if not FIREBASE_APP:
        return None

    if not recipients:
        return None

    recipients = '\n'.join(recipients)
    priority = parse_priority(priority)

    if log_level is None:
        log_level = get_log_level()

    if not commit:
        if priority == PRIORITY.now:
            raise ValueError("send_many() can't be used with priority = 'now'")

    if template:
        if title:
            raise ValueError('You can\'t specify both "template" and "title" arguments')
        if text:
            raise ValueError('You can\'t specify both "template" and "text" arguments')
        # template can be an EmailTemplate instance or name
        if isinstance(template, EmailTemplate):
            template = template
            # If language is specified, ensure template uses the right language
            if language:
                if template.language != language:
                    template = template.translated_templates.get(language=language)
        else:
            template = get_email_template(template, language)

    notification = create(recipients, title, text, context, scheduled_time,
                          template, priority, render_on_delivery, commit=commit)

    if priority == PRIORITY.now:
        notification.dispatch(log_level=log_level)

    return notification


def send_many(kwargs_list):
    """
    Similar to push.send(), but this function accepts a list of kwargs.
    Internally, it uses Django's bulk_create command for efficiency reasons.
    Currently send_many() can't be used to send notifications with priority = 'now'.
    """
    if not FIREBASE_APP:
        return None

    notifications = []
    for kwargs in kwargs_list:
        notifications.append(send(commit=False, **kwargs))
    PushNotification.objects.bulk_create(notifications)


def get_queued():
    """
    Returns a list of notifications that should be sent:
     - Status is queued
     - Has scheduled_time lower than the current time or None
    """
    return PushNotification.objects.filter(status=STATUS.queued) \
        .select_related('template') \
        .filter(Q(scheduled_time__lte=now()) | Q(scheduled_time=None)) \
        .order_by(*get_sending_order())[:get_batch_size()]


def send_queued(processes=1, log_level=None):
    """
    Sends out all queued notifications that have scheduled_time less than now or None
    """
    if not FIREBASE_APP:
        return None

    queued_notifications = get_queued()
    total_sent, total_failed = 0, 0
    total_notifications = len(queued_notifications)

    logger.info('Started sending %s notifications with %s processes.' %
                (total_notifications, processes))

    if log_level is None:
        log_level = get_log_level()

    if queued_notifications:

        # Don't use more processes than number of notifications
        if total_notifications < processes:
            processes = total_notifications

        if processes == 1:
            total_sent, total_failed = _send_bulk(queued_notifications,
                                                  uses_multiprocessing=False,
                                                  log_level=log_level)
        else:
            notification_lists = split_emails(queued_notifications, processes)

            pool = Pool(processes)
            results = pool.map(_send_bulk, notification_lists)
            pool.terminate()

            total_sent = sum([result[0] for result in results])
            total_failed = sum([result[1] for result in results])
    message = '%s notifications attempted, %s sent, %s failed' % (
        total_notifications,
        total_sent,
        total_failed
    )
    logger.info(message)
    return (total_sent, total_failed)


def _send_bulk(notifications, uses_multiprocessing=True, log_level=None):
    # Multiprocessing does not play well with database connection
    # Fix: Close connections on forking process
    # https://groups.google.com/forum/#!topic/django-users/eCAIY9DAfG0
    if uses_multiprocessing:
        db_connection.close()

    if log_level is None:
        log_level = get_log_level()

    results = []  # This is a list of two tuples (notification, DeliveryResult)
    prepared_notifications = []
    notification_count = len(notifications)

    logger.info('Process started, sending %s notifications' % notification_count)

    def send(notification):
        result = notification.deliver()
        if result.status == STATUS.sent:
            logger.debug('Successfully sent notification #%d' % notification.id)
        else:
            logger.debug('Failed to send notification #%d: %s' % (notification.id, result.message))
        results.append((notification, result))

    # Prepare notifications before we send these to threads for sending
    # So we don't need to access the DB from within threads
    for notification in notifications:
        # Sometimes this can fail, for example when trying to render
        # notification from a faulty Django template
        try:
            notification.prepare_notification_message()
        except Exception as e:
            results.append((notification, DeliveryResult(STATUS.failed, str(e), type(e).__name__,
                                                         is_transient_error(e), [], 0, 0)))
        else:
            prepared_notifications.append(notification)

    if prepared_notifications:
        # Обновляем токен доступа до старта потоков, иначе одновременный refresh в каждом
        # потоке роняет отправку целиком
        warmup_credentials()

        number_of_threads = min(get_threads_per_process(), len(prepared_notifications))
        pool = ThreadPool(number_of_threads)

        pool.map(send, prepared_notifications)
        pool.close()
        pool.join()

    sent_ids, failed_ids, retry_ids, invalid_tokens = [], [], [], []
    for notification, result in results:
        invalid_tokens.extend(result.invalid_tokens)
        if result.status == STATUS.sent:
            sent_ids.append(notification.id)
        elif notification.should_retry(result):
            retry_ids.append(notification.id)
        else:
            failed_ids.append(notification.id)

    # Update statuses of sent and failed notifications
    PushNotification.objects.filter(id__in=sent_ids).update(status=STATUS.sent, last_updated=now())
    PushNotification.objects.filter(id__in=failed_ids).update(status=STATUS.failed, last_updated=now())

    # Временные ошибки FCM возвращаем в очередь, иначе уведомление теряется навсегда
    if retry_ids:
        PushNotification.objects.filter(id__in=retry_ids).update(
            status=STATUS.queued,
            scheduled_time=now() + get_retry_interval(),
            number_of_retries=Coalesce(F('number_of_retries'), Value(0)) + Value(1),
            last_updated=now()
        )

    handle_invalid_tokens(invalid_tokens)

    # If log level is 0, log nothing, 1 logs only sending failures
    # and 2 means log both successes and failures
    logs = []
    for notification, result in results:
        if result.status == STATUS.failed:
            if log_level >= 1:
                logs.append(Log(notification=notification, status=STATUS.failed, message=result.message,
                                exception_type=result.exception_type))
        elif log_level == 2:
            logs.append(Log(notification=notification, status=STATUS.sent, message=result.message,
                            exception_type=result.exception_type))

    if logs:
        Log.objects.bulk_create(logs)

    logger.info(
        'Process finished, %s attempted, %s sent, %s failed, %s requeued' % (
            notification_count, len(sent_ids), len(failed_ids), len(retry_ids)
        )
    )

    return len(sent_ids), len(failed_ids) + len(retry_ids)
