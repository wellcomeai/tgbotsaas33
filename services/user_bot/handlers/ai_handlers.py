"""
Обработчики ИИ ассистента с поддержкой OpenAI Responses API
✅ ОБНОВЛЕНО: Переход с Assistants API на Responses API
✅ СОХРАНЕНО: Полная токеновая система и управление лимитами
✅ СОХРАНЕНО: Поддержка ChatForYou и ProTalk
✅ ДОБАВЛЕНО: Автоматическое управление контекстом через Responses API
✅ ДОБАВЛЕНО: Встроенные инструменты OpenAI (web_search, code_interpreter, etc.)
✅ НОВОЕ: UI для управления инструментами Responses API
✅ НОВОЕ: Система лимитов сообщений в день
✅ ИСПРАВЛЕНО: Использование новой архитектуры DatabaseManager для синхронизации данных
✅ УПРОЩЕНО: Кнопка "Позвать ИИ" всегда доступна если агент настроен
✅ РЕФАКТОРИНГ: Разбито на модульную структуру
"""

import structlog
from aiogram import Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

# Импорты новых модулей
from .ai_token_manager import TokenManager
from .ai_message_limits import MessageLimitManager
from .ai_openai_handler import OpenAIHandler
from .ai_chatforyou_handler import ChatForYouHandler
from .ai_conversation import ConversationHandler
from ..states import AISettingsStates

logger = structlog.get_logger()


def register_ai_handlers(dp: Dispatcher, **kwargs):
    """Регистрация обработчиков ИИ с поддержкой Responses API"""
    
    logger.info("🔧 Registering AI handlers with Responses API support")
    
    db = kwargs['db']
    bot_config = kwargs['bot_config']
    ai_assistant = kwargs.get('ai_assistant')
    user_bot = kwargs.get('user_bot')
    
    logger.info("📋 Handler registration parameters", 
               bot_id=bot_config.get('bot_id', 'unknown'),
               has_db=bool(db),
               has_ai_assistant=bool(ai_assistant),
               has_user_bot=bool(user_bot))
    
    try:
        # Создаем основной обработчик
        handler = AIHandler(db, bot_config, ai_assistant, user_bot)
        
        # Callback обработчики (главные меню)
        dp.callback_query.register(handler.cb_admin_ai, F.data == "admin_ai")
        dp.callback_query.register(handler.cb_ai_action, F.data.startswith("ai_"))
        
        # Обработчики для выбора типа агента
        dp.callback_query.register(handler.cb_select_agent_type, F.data.startswith("agent_type_"))
        
        # OpenAI обработчики
        dp.callback_query.register(handler.cb_openai_action, F.data.startswith("openai_"))
        dp.callback_query.register(handler.cb_openai_tools_settings, F.data == "openai_tools_settings")
        dp.callback_query.register(handler.cb_openai_toggle_web_search, F.data == "openai_toggle_web_search")
        dp.callback_query.register(handler.cb_openai_toggle_code_interpreter, F.data == "openai_toggle_code_interpreter")
        dp.callback_query.register(handler.cb_openai_toggle_file_search, F.data == "openai_toggle_file_search")
        dp.callback_query.register(handler.cb_openai_upload_files, F.data == "openai_upload_files")
        dp.callback_query.register(handler.cb_openai_clear_context, F.data == "openai_clear_context")
        dp.callback_query.register(handler.cb_sync_agent_data, F.data == "sync_agent_data")
        
        # Обработчики подтверждения удаления
        dp.callback_query.register(handler.cb_ai_confirm_delete, F.data == "ai_confirm_delete")
        dp.callback_query.register(handler.cb_openai_confirm_delete, F.data == "openai_confirm_delete")
        
        # Токеновые обработчики
        dp.callback_query.register(handler.cb_request_token_topup, F.data == "request_token_topup")
        
        # Обработчики лимитов сообщений
        dp.callback_query.register(handler.cb_message_limit_settings, F.data == "ai_message_limit")
        dp.callback_query.register(handler.cb_set_message_limit, F.data == "ai_set_message_limit")
        dp.callback_query.register(handler.cb_disable_message_limit, F.data == "ai_disable_message_limit")
        
        # Обработчик inline кнопки завершения диалога
        dp.callback_query.register(handler.cb_exit_conversation, F.data == "ai_exit_conversation")
        
        # Обработчики ввода для ChatForYou
        dp.message.register(
            handler.handle_api_token_input,
            AISettingsStates.waiting_for_api_token
        )
        dp.message.register(
            handler.handle_bot_id_input,
            AISettingsStates.waiting_for_bot_id
        )
        dp.message.register(
            handler.handle_ai_assistant_id_input,
            AISettingsStates.waiting_for_assistant_id
        )
        dp.message.register(
            handler.handle_ai_daily_limit_input,
            AISettingsStates.waiting_for_daily_limit
        )
        
        # Обработчик ввода лимита сообщений
        dp.message.register(
            handler.handle_message_limit_input,
            AISettingsStates.waiting_for_message_limit
        )
        
        # Обработчики для OpenAI агента
        dp.message.register(
            handler.handle_openai_name_input,
            AISettingsStates.waiting_for_openai_name
        )
        dp.message.register(
            handler.handle_openai_role_input,
            AISettingsStates.waiting_for_openai_role
        )
        
        # Обработчики диалога
        dp.message.register(
            handler.handle_ai_conversation,
            AISettingsStates.in_ai_conversation
        )
        
        # Обработчики кнопок
        dp.message.register(
            handler.handle_ai_button_click,
            F.text == "🤖 Позвать ИИ"
        )
        
        dp.message.register(
            handler.handle_ai_exit,
            F.text == "🚪 Завершить диалог с ИИ"
        )
        
        logger.info("✅ AI handlers with Responses API support registered successfully", 
                   bot_id=bot_config['bot_id'],
                   handlers_count=24)
        
    except Exception as e:
        logger.error("💥 Failed to register AI handlers", 
                    bot_id=kwargs.get('bot_config', {}).get('bot_id', 'unknown'),
                    error=str(e),
                    error_type=type(e).__name__,
                    exc_info=True)
        raise


class AIHandler:
    """✅ РЕФАКТОРИНГ: Основной обработчик ИИ - координирует работу всех модулей"""
    
    def __init__(self, db, bot_config: dict, ai_assistant, user_bot):
        logger.info("🔧 Initializing AIHandler with modular structure", 
                   bot_id=bot_config.get('bot_id', 'unknown'))
        
        self.db = db
        self.bot_config = bot_config
        self.bot_id = bot_config['bot_id']
        self.owner_user_id = bot_config['owner_user_id']
        self.ai_assistant = ai_assistant
        self.user_bot = user_bot
        
        # Получаем настройки ИИ из конфигурации
        self.bot_username = bot_config['bot_username']
        self.ai_assistant_id = bot_config.get('ai_assistant_id')
        self.ai_assistant_settings = bot_config.get('ai_assistant_settings', {})
        
        # ✅ НОВОЕ: Инициализируем модули
        self.token_manager = TokenManager(db, bot_config)
        self.message_limit_manager = MessageLimitManager(db, bot_config)
        self.openai_handler = OpenAIHandler(db, bot_config, ai_assistant, user_bot)
        self.chatforyou_handler = ChatForYouHandler(db, bot_config, ai_assistant, user_bot)
        self.conversation_handler = ConversationHandler(
            db, bot_config, ai_assistant, user_bot,
            self.token_manager, self.message_limit_manager
        )
        
        logger.info("✅ AIHandler initialized with modular structure", 
                   bot_id=self.bot_id,
                   bot_username=self.bot_username,
                   owner_user_id=self.owner_user_id,
                   ai_assistant_id_exists=bool(self.ai_assistant_id),
                   modules_initialized=5)

    # ===== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ =====
    
    def _is_owner(self, user_id: int) -> bool:
        """Проверка владельца"""
        return user_id == self.owner_user_id
    
    def _get_agent_type(self) -> str:
        """Получение типа агента"""
        return self.ai_assistant_settings.get('agent_type', 'none')
    
    def _has_ai_agent(self) -> bool:
        """Проверка наличия ИИ агента"""
        return bool(self.ai_assistant_id)
    
    # ===== ДЕЛЕГИРОВАНИЕ К МОДУЛЯМ =====
    
    # Токеновые методы -> TokenManager
    async def cb_request_token_topup(self, callback: CallbackQuery):
        await self.token_manager.handle_request_token_topup(callback)
    
    # Лимиты сообщений -> MessageLimitManager
    async def cb_message_limit_settings(self, callback: CallbackQuery):
        await self.message_limit_manager.handle_message_limit_settings(callback)
    
    async def cb_set_message_limit(self, callback: CallbackQuery, state: FSMContext):
        await self.message_limit_manager.handle_set_message_limit(callback, state)
    
    async def cb_disable_message_limit(self, callback: CallbackQuery):
        await self.message_limit_manager.handle_disable_message_limit(callback)
    
    async def handle_message_limit_input(self, message: Message, state: FSMContext):
        await self.message_limit_manager.handle_message_limit_input(message, state, self._is_owner)
    
    # OpenAI методы -> OpenAIHandler
    async def cb_openai_action(self, callback: CallbackQuery, state: FSMContext):
        await self.openai_handler.handle_openai_action(callback, state, self._is_owner)
    
    async def cb_openai_tools_settings(self, callback: CallbackQuery):
        await self.openai_handler.handle_tools_settings(callback, self._is_owner)
    
    async def cb_openai_toggle_web_search(self, callback: CallbackQuery):
        await self.openai_handler.handle_toggle_web_search(callback, self._is_owner)
    
    async def cb_openai_toggle_code_interpreter(self, callback: CallbackQuery):
        await self.openai_handler.handle_toggle_code_interpreter(callback, self._is_owner)
    
    async def cb_openai_toggle_file_search(self, callback: CallbackQuery):
        await self.openai_handler.handle_toggle_file_search(callback, self._is_owner)
    
    async def cb_openai_upload_files(self, callback: CallbackQuery):
        await self.openai_handler.handle_upload_files(callback, self._is_owner)
    
    async def cb_openai_clear_context(self, callback: CallbackQuery):
        await self.openai_handler.handle_clear_context(callback, self._is_owner)
    
    async def cb_sync_agent_data(self, callback: CallbackQuery):
        await self.openai_handler.handle_sync_agent_data(callback, self._is_owner)
    
    async def cb_openai_confirm_delete(self, callback: CallbackQuery):
        await self.openai_handler.handle_confirm_delete(callback, self._is_owner)
    
    async def handle_openai_name_input(self, message: Message, state: FSMContext):
        await self.openai_handler.handle_name_input(message, state, self._is_owner)
    
    async def handle_openai_role_input(self, message: Message, state: FSMContext):
        await self.openai_handler.handle_role_input(message, state, self._is_owner)
    
    # ChatForYou методы -> ChatForYouHandler
    async def cb_ai_action(self, callback: CallbackQuery, state: FSMContext):
        await self.chatforyou_handler.handle_ai_action(callback, state, self._is_owner)
    
    async def cb_ai_confirm_delete(self, callback: CallbackQuery):
        await self.chatforyou_handler.handle_confirm_delete(callback, self._is_owner)
    
    async def handle_api_token_input(self, message: Message, state: FSMContext):
        await self.chatforyou_handler.handle_api_token_input(message, state, self._is_owner)
    
    async def handle_bot_id_input(self, message: Message, state: FSMContext):
        await self.chatforyou_handler.handle_bot_id_input(message, state, self._is_owner)
    
    async def handle_ai_assistant_id_input(self, message: Message, state: FSMContext):
        await self.chatforyou_handler.handle_ai_assistant_id_input(message, state, self._is_owner)
    
    async def handle_ai_daily_limit_input(self, message: Message, state: FSMContext):
        await self.chatforyou_handler.handle_ai_daily_limit_input(message, state, self._is_owner)
    
    # Диалоги -> ConversationHandler
    async def handle_ai_button_click(self, message: Message, state: FSMContext):
        await self.conversation_handler.handle_ai_button_click(message, state, self._has_ai_agent, self._get_agent_type)
    
    async def handle_ai_conversation(self, message: Message, state: FSMContext):
        await self.conversation_handler.handle_ai_conversation(message, state, self._is_owner, self._get_agent_type)
    
    async def handle_ai_exit(self, message: Message, state: FSMContext):
        await self.conversation_handler.handle_ai_exit(message, state)
    
    async def cb_exit_conversation(self, callback: CallbackQuery, state: FSMContext):
        await self.conversation_handler.handle_exit_conversation(callback, state)
    
    # ===== ОСНОВНЫЕ МЕНЮ (ОСТАЮТСЯ В ГЛАВНОМ ФАЙЛЕ) =====
    
    async def cb_admin_ai(self, callback: CallbackQuery):
        """Главное меню настроек ИИ"""
        logger.info("🎛️ Admin AI menu accessed", 
                   user_id=callback.from_user.id,
                   bot_id=self.bot_id)
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        agent_type = self._get_agent_type()
        
        # Если тип агента не выбран - показываем меню выбора
        if agent_type == 'none':
            await self._show_agent_type_selection(callback)
            return
        
        # Показываем настройки конкретного типа агента
        if agent_type == 'chatforyou':
            await self.chatforyou_handler.show_settings(callback, self._has_ai_agent)
        elif agent_type == 'openai':
            await self.openai_handler.show_settings(callback, self._has_ai_agent)
        else:
            await self._show_agent_type_selection(callback)
    
    async def cb_select_agent_type(self, callback: CallbackQuery):
        """Обработка выбора типа агента"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        agent_type = callback.data.replace("agent_type_", "")
        
        try:
            # Очищаем старую конфигурацию при смене типа
            await self.db.clear_ai_configuration(self.bot_id)
            
            # Устанавливаем новый тип агента
            ai_settings = {'agent_type': agent_type}
            
            await self.db.update_ai_assistant(
                self.bot_id,
                settings=ai_settings
            )
            
            # Обновляем локальные настройки
            self.ai_assistant_settings = ai_settings
            self.ai_assistant_id = None
            
            # Переходим к настройкам выбранного типа
            if agent_type == 'chatforyou':
                await self.chatforyou_handler.show_settings(callback, False)
            elif agent_type == 'openai':
                await self.openai_handler.show_settings(callback, False)
                
        except Exception as e:
            logger.error("💥 Failed to set agent type", error=str(e))
            await callback.answer("Ошибка при сохранении типа агента", show_alert=True)
    
    async def _show_agent_type_selection(self, callback: CallbackQuery):
        """Показ меню выбора типа агента"""
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        
        text = f"""
🤖 <b>ИИ Агент @{self.bot_username}</b>

Выберите тип ИИ агента для вашего бота:

🌐 <b>Подключить с платформы</b>
- ChatForYou (api.chatforyou.ru)
- ProTalk (api.pro-talk.ru)
- Требует API токен

🎨 <b>Создать своего агента</b>
- На базе OpenAI GPT-4o (Responses API)
- Настройка роли и инструкций
- Автоматическое управление контекстом
- Встроенные инструменты (веб-поиск, код, файлы)

<b>Что выберете?</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Подключить с платформы", callback_data="agent_type_chatforyou")],
            [InlineKeyboardButton(text="🎨 Создать своего агента", callback_data="agent_type_openai")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
