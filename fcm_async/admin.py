# -*- coding: utf-8 -*-
# based on https://github.com/ui/django-post_office/blob/master/post_office/admin.py

from __future__ import unicode_literals

from django.contrib import admin

from .models import Log, PushNotification, STATUS


def get_message_preview(instance):
    return (u'{0}...'.format(instance.message[:25]) if len(instance.message) > 25
            else instance.message)


get_message_preview.short_description = 'Message'


class LogInline(admin.StackedInline):
    model = Log
    extra = 0


def requeue(modeladmin, request, queryset):
    """An admin action to requeue notifications."""
    queryset.update(status=STATUS.queued)


class NotificationAdmin(admin.ModelAdmin):
    list_display = ('id', 'title_display', 'template',
                    'status', 'last_updated')
    search_fields = ['to', 'title']
    date_hierarchy = 'last_updated'
    inlines = [LogInline]
    list_filter = ['status', 'template__language', 'template__name']
    actions = [requeue]

    def get_queryset(self, request):
        return super(NotificationAdmin, self).get_queryset(request).select_related('template')

    def title_display(self, instance):
        if instance.template and instance.template.subject:
            return instance.template.subject
        elif instance.title:
            return instance.title
        else:
            return u'%s: %s' % (instance._meta.verbose_name, instance.id)

    title_display.short_description = 'Title'
    title_display.admin_order_field = 'Title'


class LogAdmin(admin.ModelAdmin):
    list_display = ('date', 'notification', 'status', get_message_preview)


admin.site.register(PushNotification, NotificationAdmin)
admin.site.register(Log, LogAdmin)
