# -*- coding: utf-8 -*-
# based on https://github.com/ui/django-post_office/blob/master/post_office/management/commands/cleanup_mail.py

import datetime

from django.core.management.base import BaseCommand
from django.utils.timezone import now

from ...models import PushNotification


class Command(BaseCommand):
    help = 'Place deferred messages back in the queue.'

    def add_arguments(self, parser):
        parser.add_argument('-d', '--days',
                            type=int, default=90,
                            help="Cleanup notifications older than this many days, defaults to 90.")

    def handle(self, verbosity, days, **options):
        # Delete notifications and their related logs and queued created before X days

        cutoff_date = now() - datetime.timedelta(days)
        count = PushNotification.objects.filter(created__lt=cutoff_date).count()
        PushNotification.objects.only('id').filter(created__lt=cutoff_date).delete()
        self.stdout.write("Deleted {0} notifications created before {1} ".format(count, cutoff_date))
