# -*- coding: utf-8 -*-

from django.apps import AppConfig
from django.utils.translation import ugettext_lazy as _


class FCMAsyncConfig(AppConfig):
    name = 'fcm_async'
    verbose_name = _("Firebase Cloud Messaging Async")
