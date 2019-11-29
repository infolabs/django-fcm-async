# -*- coding: utf-8 -*-
# Generated by Django 1.9.8 on 2019-11-29 13:14
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion
import jsonfield.fields


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('post_office', '0007_auto_20170731_1342'),
    ]

    operations = [
        migrations.CreateModel(
            name='Log',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateTimeField(auto_now_add=True)),
                ('status', models.PositiveSmallIntegerField(choices=[(0, 'sent'), (1, 'failed')], verbose_name='Status')),
                ('exception_type', models.CharField(blank=True, max_length=255, verbose_name='Exception type')),
                ('message', models.TextField(verbose_name='Message')),
            ],
            options={
                'verbose_name': 'Log',
                'verbose_name_plural': 'Logs',
            },
        ),
        migrations.CreateModel(
            name='PushNotification',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('to', models.TextField(verbose_name='Notification To')),
                ('title', models.CharField(blank=True, max_length=989, verbose_name='Title')),
                ('text', models.TextField(blank=True, verbose_name='Text')),
                ('status', models.PositiveSmallIntegerField(blank=True, choices=[(0, 'sent'), (1, 'failed'), (2, 'queued')], db_index=True, null=True, verbose_name='Status')),
                ('priority', models.PositiveSmallIntegerField(blank=True, choices=[(0, 'low'), (1, 'medium'), (2, 'high'), (3, 'now')], null=True, verbose_name='Priority')),
                ('created', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('last_updated', models.DateTimeField(auto_now=True, db_index=True)),
                ('scheduled_time', models.DateTimeField(blank=True, db_index=True, null=True, verbose_name='The scheduled sending time')),
                ('context', jsonfield.fields.JSONField(blank=True, null=True, verbose_name='Context')),
                ('template', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='post_office.EmailTemplate', verbose_name='Template')),
            ],
            options={
                'verbose_name': 'Push notification',
                'verbose_name_plural': 'Push notifications',
            },
        ),
        migrations.AddField(
            model_name='log',
            name='notification',
            field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name='logs', to='fcm_async.PushNotification', verbose_name='Push notification'),
        ),
    ]