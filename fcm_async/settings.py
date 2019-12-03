# -*- coding: utf-8 -*-
# based on https://github.com/ui/django-post_office/blob/master/post_office/settings.py

from post_office.compat import import_attribute

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


CONTEXT_FIELD_CLASS = get_config().get('CONTEXT_FIELD_CLASS', 'jsonfield.JSONField')
context_field_class = import_attribute(CONTEXT_FIELD_CLASS)
