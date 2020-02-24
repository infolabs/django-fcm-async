# -*- coding: utf-8 -*-
# based on https://github.com/ui/django-post_office/blob/master/post_office/logutils.py
import logging

try:
    from post_office.compat import dictConfig
except ImportError:
    from logging.config import dictConfig


# Taken from https://github.com/nvie/rq/blob/master/rq/logutils.py
def setup_loghandlers(level=None):
    # Setup logging for fcm_async if not already configured
    logger = logging.getLogger('fcm_async')
    if not logger.handlers:
        dictConfig({
            "version": 1,
            "disable_existing_loggers": False,

            "formatters": {
                "fcm_async": {
                    "format": "[%(levelname)s]%(asctime)s PID %(process)d: %(message)s",
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                },
            },

            "handlers": {
                "fcm_async": {
                    "level": "DEBUG",
                    "class": "logging.StreamHandler",
                    "formatter": "fcm_async"
                },
            },

            "loggers": {
                "fcm_async": {
                    "handlers": ["fcm_async"],
                    "level": level or "DEBUG"
                }
            }
        })
    return logger
