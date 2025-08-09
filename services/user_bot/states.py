"""
FSM состояния для UserBot
Все состояния конечного автомата в одном месте
"""

from aiogram.fsm.state import State, StatesGroup


class BotSettingsStates(StatesGroup):
    """Состояния настроек бота"""
    # Welcome settings
    waiting_for_welcome_message = State()
    waiting_for_welcome_button = State()
    waiting_for_confirmation_message = State()
    
    # Goodbye settings
    waiting_for_goodbye_message = State()
    waiting_for_goodbye_button_text = State()
    waiting_for_goodbye_button_url = State()


class FunnelStates(StatesGroup):
    """Состояния воронки продаж"""
    # Message creation/editing
    waiting_for_message_text = State()
    waiting_for_message_delay = State()
    waiting_for_media_upload = State()
    waiting_for_media_file = State()
    
    # Message editing
    waiting_for_edit_text = State()
    waiting_for_edit_delay = State()
    
    # Button management
    waiting_for_button_text = State()
    waiting_for_button_url = State()
    waiting_for_edit_button_text = State()
    waiting_for_edit_button_url = State()


class AISettingsStates(StatesGroup):
    """Состояния настроек ИИ ассистента"""
    waiting_for_api_token = State()      # for API token (step 1)
    waiting_for_bot_id = State()         # for bot_id (step 2)
    waiting_for_assistant_id = State()   # Keep for compatibility
    waiting_for_daily_limit = State()
    in_ai_conversation = State()
