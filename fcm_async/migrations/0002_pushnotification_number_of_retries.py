# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('fcm_async', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='pushnotification',
            name='number_of_retries',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='Number of retries'),
        ),
    ]
