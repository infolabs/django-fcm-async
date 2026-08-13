# -*- coding: utf-8 -*-
from django.core.management.base import BaseCommand, CommandError

from ...models import (FIREBASE_APP, PushNotification, is_invalid_token_error, is_transient_error, mask_token,
                       warmup_credentials)
from ...settings import get_send_system_notification


class Command(BaseCommand):
    help = 'Отправляет тестовое push-уведомление на указанные токены и печатает ответ FCM по каждому токену'

    def add_arguments(self, parser):
        parser.add_argument(
            'tokens',
            nargs='+',
            help='Токены устройств',
        )
        parser.add_argument(
            '-t', '--title',
            default='Тестовое уведомление',
            help='Заголовок уведомления',
        )
        parser.add_argument(
            '-m', '--text',
            default='Проверка доставки push-уведомлений',
            help='Текст уведомления. Ссылка в теге <a href="..."> при системном уведомлении '
                 'уходит отдельным значением data, иначе остаётся в тексте',
        )
        parser.add_argument(
            '-d', '--dry-run',
            action='store_true',
            help='Проверить сообщение на стороне FCM без доставки на устройства',
        )
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument(
            '-s', '--system',
            dest='system_notification',
            action='store_true',
            default=None,
            help='Отправить с системным уведомлением независимо от SEND_SYSTEM_NOTIFICATION',
        )
        mode.add_argument(
            '-D', '--data-only',
            dest='system_notification',
            action='store_false',
            default=None,
            help='Отправить только data-сообщение независимо от SEND_SYSTEM_NOTIFICATION',
        )

    def handle(self, *args, **options):
        if not FIREBASE_APP:
            raise CommandError('Firebase не настроен, проверьте FIREBASE_KEY_PATH')

        tokens = options['tokens']
        system_notification = options['system_notification']
        if system_notification is None:
            system_notification = get_send_system_notification()

        notification = PushNotification(to='\n'.join(tokens), title=options['title'], text=options['text'])
        title, body, url = notification.get_payload(notification.notification_message(), system_notification)

        self.stdout.write('Проект: {}'.format(FIREBASE_APP.project_id))
        self.stdout.write('Уведомление показывает: {}'.format(
            'операционная система' if system_notification else 'мобильное приложение'))
        self.stdout.write('Заголовок: {}'.format(title))
        self.stdout.write('Текст: {}'.format(body))
        if system_notification:
            self.stdout.write('Ссылка перехода: {}'.format(url or 'нет'))
        self.stdout.write('Размер заголовка и текста: {} байт'.format(len((title + body).encode('utf-8'))))
        if options['dry_run']:
            self.stdout.write('Режим проверки, уведомления на устройства не доставляются')

        warmup_credentials()
        batch_response = notification.send_firebase(notification.notification_message(), tokens,
                                                    dry_run=options['dry_run'],
                                                    system_notification=system_notification)

        for token, response in zip(tokens, batch_response.responses):
            if response.success:
                self.stdout.write(self.style.SUCCESS('{}: принято, message_id={}'.format(
                    mask_token(token), response.message_id)))
                continue
            exception = response.exception
            notes = []
            if is_invalid_token_error(exception):
                notes.append('токен недействителен и будет удалён при обычной отправке')
            if is_transient_error(exception):
                notes.append('временная ошибка, отправка будет повторена')
            self.stdout.write(self.style.ERROR('{}: {} ({}){}'.format(
                mask_token(token), exception, type(exception).__name__,
                ', ' + '; '.join(notes) if notes else '')))

        self.stdout.write('Принято {} из {} токенов'.format(
            batch_response.success_count, len(tokens)))
