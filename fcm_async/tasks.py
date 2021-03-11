import datetime

from celery import shared_task

from django.utils.timezone import now

from fcm_async.models import PushNotification


@shared_task(name='cleanup_push_notifications')
def cleanup_push_notifications(days=90):
    """
    Очистка пуш уведомлений.
    :param days: По умолчанию очищаются уведомления дата которых старше 90 дней.
    :return: словарь из количества уведомлений подготовленных для очистки и результат выполнения удачно или неудачно.
    """
    res = {
        "count": 0,
        "success": False
    }
    cutoff_date = now() - datetime.timedelta(days)
    count = PushNotification.objects.filter(created__lt=cutoff_date).count()
    res["count"] += count

    try:
        PushNotification.objects.only('id').filter(created__lt=cutoff_date).delete()
    except Exception:
        pass
    else:
        res["success"] = True

    return res
