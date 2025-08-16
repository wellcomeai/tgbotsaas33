# services/__init__.py - ОБНОВЛЕННЫЙ с интеграцией платежей

# ✅ СУЩЕСТВУЮЩИЕ сервисы
from .bot_manager import BotManager
from .user_bot import UserBot
from .funnel_manager import funnel_manager
from .message_scheduler import MessageScheduler
from .ai_assistant import ai_client, AIAssistantClient, AIAssistantError

# ✅ СУЩЕСТВУЮЩИЕ: Безопасный импорт content_agent_service
try:
    from .content_agent import content_agent_service, ContentAgentService
    CONTENT_AGENT_AVAILABLE = True
except ImportError as e:
    content_agent_service = None
    ContentAgentService = None
    CONTENT_AGENT_AVAILABLE = False
    
    # Логируем предупреждение если структлог доступен
    try:
        import structlog
        logger = structlog.get_logger()
        logger.warning("ContentAgentService not available", error=str(e))
    except ImportError:
        pass  # Структлог тоже может быть недоступен

# ✅ НОВЫЕ: Платежные сервисы
try:
    from .payments import (
        robokassa_service, 
        RobokassaService,
        subscription_manager, 
        SubscriptionManager,
        ROBOKASSA_AVAILABLE,
        SUBSCRIPTION_MANAGER_AVAILABLE
    )
    PAYMENTS_AVAILABLE = True
except ImportError as e:
    robokassa_service = None
    RobokassaService = None
    subscription_manager = None
    SubscriptionManager = None
    ROBOKASSA_AVAILABLE = False
    SUBSCRIPTION_MANAGER_AVAILABLE = False
    PAYMENTS_AVAILABLE = False
    
    try:
        import structlog
        logger = structlog.get_logger()
        logger.warning("Payment services not available", error=str(e))
    except ImportError:
        pass

# ✅ НОВЫЕ: Уведомления (обновленные с платежными)
try:
    from .notifications import (
        # Существующие токен-уведомления
        TokenNotificationService,
        get_notification_service,
        send_token_exhausted_notification,
        send_token_warning_notification,
        
        # Новые платежные уведомления
        payment_notifier,
        PaymentNotificationService,
        PAYMENT_NOTIFICATIONS_AVAILABLE
    )
    NOTIFICATIONS_AVAILABLE = True
except ImportError as e:
    # Fallback к старым импортам если новых нет
    try:
        from .notifications import (
            TokenNotificationService,
            get_notification_service,
            send_token_exhausted_notification,
            send_token_warning_notification
        )
        payment_notifier = None
        PaymentNotificationService = None
        PAYMENT_NOTIFICATIONS_AVAILABLE = False
        NOTIFICATIONS_AVAILABLE = True
    except ImportError:
        TokenNotificationService = None
        get_notification_service = None
        send_token_exhausted_notification = None
        send_token_warning_notification = None
        payment_notifier = None
        PaymentNotificationService = None
        PAYMENT_NOTIFICATIONS_AVAILABLE = False
        NOTIFICATIONS_AVAILABLE = False

# ✅ НОВЫЕ: Планировщики (обновленные с подписками)
try:
    from .scheduler import (
        # Существующий планировщик
        message_limit_scheduler,
        MessageLimitResetScheduler,
        MESSAGE_LIMIT_SCHEDULER_AVAILABLE,
        
        # Новый планировщик
        subscription_checker,
        SubscriptionChecker, 
        SUBSCRIPTION_CHECKER_AVAILABLE
    )
    SCHEDULER_AVAILABLE = True
except ImportError as e:
    # Fallback к старым планировщикам если новых нет
    try:
        from .scheduler.message_limit_reset import message_limit_scheduler, MessageLimitResetScheduler
        MESSAGE_LIMIT_SCHEDULER_AVAILABLE = True
    except ImportError:
        message_limit_scheduler = None
        MessageLimitResetScheduler = None
        MESSAGE_LIMIT_SCHEDULER_AVAILABLE = False
    
    subscription_checker = None
    SubscriptionChecker = None
    SUBSCRIPTION_CHECKER_AVAILABLE = False
    SCHEDULER_AVAILABLE = MESSAGE_LIMIT_SCHEDULER_AVAILABLE

__all__ = [
    # Основные существующие сервисы
    "BotManager", 
    "UserBot", 
    "funnel_manager", 
    "MessageScheduler",
    "ai_client",
    "AIAssistantClient", 
    "AIAssistantError",
    
    # Content Agent (если доступен)
    "content_agent_service",
    "ContentAgentService", 
    "CONTENT_AGENT_AVAILABLE",
    
    # ✅ НОВЫЕ: Платежные сервисы
    "robokassa_service",
    "RobokassaService",
    "subscription_manager", 
    "SubscriptionManager",
    "ROBOKASSA_AVAILABLE",
    "SUBSCRIPTION_MANAGER_AVAILABLE",
    "PAYMENTS_AVAILABLE",
    
    # ✅ ОБНОВЛЕННЫЕ: Уведомления
    "TokenNotificationService",
    "get_notification_service",
    "send_token_exhausted_notification", 
    "send_token_warning_notification",
    "payment_notifier",
    "PaymentNotificationService",
    "PAYMENT_NOTIFICATIONS_AVAILABLE",
    "NOTIFICATIONS_AVAILABLE",
    
    # ✅ ОБНОВЛЕННЫЕ: Планировщики
    "message_limit_scheduler",
    "MessageLimitResetScheduler",
    "MESSAGE_LIMIT_SCHEDULER_AVAILABLE",
    "subscription_checker",
    "SubscriptionChecker",
    "SUBSCRIPTION_CHECKER_AVAILABLE", 
    "SCHEDULER_AVAILABLE"
]
