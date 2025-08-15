"""
Обработчики для UserBot
Экспорт функций регистрации всех обработчиков
"""

from .admin_handlers import register_admin_handlers
from .settings_handlers import register_settings_handlers
from .ai_handlers import register_ai_handlers
from .funnel_handlers import register_funnel_handlers
from .channel_handlers import register_channel_handlers
from .content_handlers import register_content_handlers
__all__ = [
    'register_admin_handlers',
    'register_settings_handlers', 
    'register_ai_handlers',
    'register_funnel_handlers',
    'register_channel_handlers',
    'register_content_handlers'
]
