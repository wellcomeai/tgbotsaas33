"""
Payment Services Package
Сервисы для работы с платежами и подписками Robokassa
"""

try:
    from .robokassa_service import robokassa_service, RobokassaService
    ROBOKASSA_AVAILABLE = True
except ImportError:
    robokassa_service = None
    RobokassaService = None
    ROBOKASSA_AVAILABLE = False

try:
    from .subscription_manager import subscription_manager, SubscriptionManager
    SUBSCRIPTION_MANAGER_AVAILABLE = True
except ImportError:
    subscription_manager = None
    SubscriptionManager = None
    SUBSCRIPTION_MANAGER_AVAILABLE = False

__all__ = [
    'robokassa_service',
    'RobokassaService',
    'ROBOKASSA_AVAILABLE',
    
    'subscription_manager',
    'SubscriptionManager', 
    'SUBSCRIPTION_MANAGER_AVAILABLE'
]
