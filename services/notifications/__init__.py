"""
Пакет уведомлений для системы ботов
Содержит сервисы для отправки различных типов уведомлений
"""

# ✅ СУЩЕСТВУЮЩИЕ импорты токен-уведомлений
from .token_notifications import (
    TokenNotificationService,
    get_notification_service,
    send_token_exhausted_notification,
    send_token_warning_notification
)

# ✅ НОВЫЕ импорты платежных уведомлений
try:
    from .payment_notifier import payment_notifier, PaymentNotificationService
    PAYMENT_NOTIFICATIONS_AVAILABLE = True
except ImportError:
    payment_notifier = None
    PaymentNotificationService = None
    PAYMENT_NOTIFICATIONS_AVAILABLE = False

__all__ = [
    # Существующие токен-уведомления
    'TokenNotificationService',
    'get_notification_service', 
    'send_token_exhausted_notification',
    'send_token_warning_notification',
    
    # Новые платежные уведомления
    'payment_notifier',
    'PaymentNotificationService',
    'PAYMENT_NOTIFICATIONS_AVAILABLE'
]
