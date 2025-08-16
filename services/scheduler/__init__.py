"""
Scheduler Services Package
Планировщики и фоновые задачи для Bot Factory
"""

# ✅ СУЩЕСТВУЮЩИЙ планировщик сброса лимитов сообщений
try:
    from .message_limit_reset import message_limit_scheduler, MessageLimitResetScheduler
    MESSAGE_LIMIT_SCHEDULER_AVAILABLE = True
except ImportError:
    message_limit_scheduler = None
    MessageLimitResetScheduler = None
    MESSAGE_LIMIT_SCHEDULER_AVAILABLE = False

# ✅ НОВЫЙ планировщик проверки подписок
try:
    from .subscription_checker import subscription_checker, SubscriptionChecker
    SUBSCRIPTION_CHECKER_AVAILABLE = True
except ImportError:
    subscription_checker = None
    SubscriptionChecker = None
    SUBSCRIPTION_CHECKER_AVAILABLE = False

__all__ = [
    # Существующий планировщик
    'message_limit_scheduler',
    'MessageLimitResetScheduler',
    'MESSAGE_LIMIT_SCHEDULER_AVAILABLE',
    
    # Новый планировщик
    'subscription_checker', 
    'SubscriptionChecker',
    'SUBSCRIPTION_CHECKER_AVAILABLE'
]
