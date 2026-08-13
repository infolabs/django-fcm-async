# -*- coding: utf-8 -*-
# based on https://github.com/ui/django-post_office/blob/master/post_office/settings.py


import datetime

try:
    from post_office.compat import import_attribute
except ImportError:
    from django.utils.module_loading import import_string as import_attribute

from django.conf import settings
from django.template import engines as template_engines


def get_config():
    """
    Returns FCM Async's configuration in dictionary format. e.g:
    FCM_ASYNC = {
        'BATCH_SIZE': 1000
    }
    """
    return getattr(settings, 'FCM_ASYNC', {})


def get_batch_size():
    return get_config().get('BATCH_SIZE', 100)


def get_threads_per_process():
    return get_config().get('THREADS_PER_PROCESS', 5)


def get_default_priority():
    return get_config().get('DEFAULT_PRIORITY', 'medium')


def get_log_level():
    return get_config().get('LOG_LEVEL', 2)


def get_sending_order():
    return get_config().get('SENDING_ORDER', ['-priority'])


def get_template_engine():
    using = get_config().get('TEMPLATE_ENGINE', 'django')
    return template_engines[using]


def get_firebase_key_path():
    return getattr(settings, 'FIREBASE_KEY_PATH', None)


def get_ttl():
    """
    Время жизни сообщения на стороне FCM в секундах.
    """
    return get_config().get('TTL', 3600)


def get_max_retries():
    """
    Количество повторных попыток отправки при временных ошибках FCM.
    """
    return get_config().get('MAX_RETRIES', 3)


def get_retry_interval():
    return get_config().get('RETRY_INTERVAL', datetime.timedelta(minutes=15))


def get_send_system_notification():
    """
    Показывать ли уведомление силами операционной системы. Если выключено, отправляется
    data-сообщение, и уведомление рисует мобильное приложение.
    """
    return get_config().get('SEND_SYSTEM_NOTIFICATION', True)


def get_android_channel_id():
    """
    Канал уведомлений Android. Начиная с Android 8 звук, вибрация и всплытие задаются каналом,
    а не сообщением, поэтому уведомление нужно отправлять в канал, который создало приложение.
    """
    return get_config().get('ANDROID_CHANNEL_ID', None)


def get_max_title_length():
    return get_config().get('MAX_TITLE_LENGTH', 200)


def get_max_body_length():
    return get_config().get('MAX_BODY_LENGTH', 1000)


def get_invalid_token_handler():
    """
    Обработчик токенов, отвергнутых FCM как несуществующие. Вызывается со списком токенов.
    Задаётся строкой с путём до функции, т.к. пакет не знает о моделях проекта.
    """
    handler = get_config().get('INVALID_TOKEN_HANDLER', None)
    if handler is None:
        return None
    if isinstance(handler, str):
        return import_attribute(handler)
    return handler


CONTEXT_FIELD_CLASS = get_config().get('CONTEXT_FIELD_CLASS', 'jsonfield.JSONField')
context_field_class = import_attribute(CONTEXT_FIELD_CLASS)
