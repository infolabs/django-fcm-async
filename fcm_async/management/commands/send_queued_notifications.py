# -*- coding: utf-8 -*-
# based on https://github.com/ui/django-post_office/blob/master/post_office/management/commands/send_queued_mail.py

import tempfile
import sys

from post_office.lockfile import FileLock, FileLocked

from django.core.management.base import BaseCommand
from django.db import connection
from django.db.models import Q
from django.utils.timezone import now

from ...push import send_queued
from ...models import PushNotification, STATUS
from ...logutils import setup_loghandlers


logger = setup_loghandlers()
default_lockfile = tempfile.gettempdir() + "/fcm_async"


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            '-p', '--processes',
            type=int,
            default=1,
            help='Number of processes used to send notifications',
        )
        parser.add_argument(
            '-L', '--lockfile',
            default=default_lockfile,
            help='Absolute path of lockfile to acquire',
        )
        parser.add_argument(
            '-l', '--log-level',
            type=int,
            help='"0" to log nothing, "1" to only log errors',
        )

    def handle(self, *args, **options):
        logger.info('Acquiring lock for sending queued notifications at %s.lock' %
                    options['lockfile'])
        try:
            with FileLock(options['lockfile']):

                while 1:
                    try:
                        send_queued(options['processes'],
                                    options.get('log_level'))
                    except Exception as e:
                        logger.error(e, exc_info=sys.exc_info(),
                                     extra={'status_code': 500})
                        raise

                    # Close DB connection to avoid multiprocessing errors
                    connection.close()

                    if not PushNotification.objects.filter(status=STATUS.queued) \
                            .filter(Q(scheduled_time__lte=now()) | Q(scheduled_time=None)).exists():
                        break
        except FileLocked:
            logger.info('Failed to acquire lock, terminating now.')
