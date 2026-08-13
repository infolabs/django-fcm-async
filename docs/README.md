# Документация пакета `fcm_async` (django-fcm-async)

**Актуализация:** 2026-08-12

## Правила ведения

1. **Дата** — в начале каждого `docs/*.md`: `**Актуализация:** YYYY-MM-DD`; обновлять при существенных правках.
2. **Ссылки** — от каталога `docs/` на корень пакета: `../fcm_async/...`.
3. **Соответствие коду** — описывать поведение по текущему репозиторию.

## Оглавление

| Документ | Содержание |
|----------|------------|
| [push_notifications.md](push_notifications.md) | Механизм отправки, формат сообщения FCM, статусы и повторы |
| [settings.md](settings.md) | Настройка `FCM_ASYNC` и `FIREBASE_KEY_PATH` |
| [management_commands.md](management_commands.md) | `send_queued_notifications`, `send_test_push`, `cleanup_notifications` |
| [troubleshooting.md](troubleshooting.md) | Диагностика недоставки уведомлений |
