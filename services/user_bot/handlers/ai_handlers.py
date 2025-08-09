"""
Обработчики ИИ ассистента с поддержкой OpenAI Assistants, улучшенным UX и детальным логированием
ПОЛНАЯ РЕАЛИЗАЦИЯ со всей оригинальной логикой + улучшения
"""

import structlog
import time
from datetime import datetime
from aiogram import Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext

from config import Emoji
from ..states import AISettingsStates
from ..keyboards import AIKeyboards

logger = structlog.get_logger()


def register_ai_handlers(dp: Dispatcher, **kwargs):
    """Регистрация обработчиков ИИ с логированием"""
    
    logger.info("🔧 Registering AI handlers")
    
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
        handler = AIHandler(db, bot_config, ai_assistant, user_bot)
        
        # Callback обработчики
        dp.callback_query.register(handler.cb_admin_ai, F.data == "admin_ai")
        dp.callback_query.register(handler.cb_ai_action, F.data.startswith("ai_"))
        
        # Новые обработчики для выбора типа агента
        dp.callback_query.register(handler.cb_select_agent_type, F.data.startswith("agent_type_"))
        dp.callback_query.register(handler.cb_openai_action, F.data.startswith("openai_"))
        
        # Обработчики ввода для ChatForYou (существующие)
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
        
        # Новые обработчики для OpenAI агента
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
        
        logger.info("✅ AI handlers with OpenAI support registered successfully", 
                   bot_id=bot_config['bot_id'],
                   handlers_count=11)
        
    except Exception as e:
        logger.error("💥 Failed to register AI handlers", 
                    bot_id=kwargs.get('bot_config', {}).get('bot_id', 'unknown'),
                    error=str(e),
                    error_type=type(e).__name__,
                    exc_info=True)
        raise


class AIHandler:
    """Обработчик ИИ ассистента с поддержкой ChatForYou и OpenAI с полным логированием"""
    
    def __init__(self, db, bot_config: dict, ai_assistant, user_bot):
        logger.info("🔧 Initializing AIHandler", 
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
        self.ai_assistant_enabled = bot_config.get('ai_assistant_enabled', False)
        self.ai_assistant_settings = bot_config.get('ai_assistant_settings', {})
        
        logger.info("✅ AIHandler initialized", 
                   bot_id=self.bot_id,
                   bot_username=self.bot_username,
                   owner_user_id=self.owner_user_id,
                   ai_enabled=self.ai_assistant_enabled,
                   ai_assistant_id_exists=bool(self.ai_assistant_id),
                   settings_keys=list(self.ai_assistant_settings.keys()))
    
    def _is_owner(self, user_id: int) -> bool:
        """Проверка владельца с логированием"""
        is_owner = user_id == self.owner_user_id
        logger.debug("🔍 Owner check", 
                    user_id=user_id,
                    owner_user_id=self.owner_user_id,
                    is_owner=is_owner)
        return is_owner
    
    def _get_agent_type(self) -> str:
        """Получение типа агента с логированием"""
        agent_type = self.ai_assistant_settings.get('agent_type', 'none')
        logger.debug("🔍 Agent type check", 
                    bot_id=self.bot_id,
                    agent_type=agent_type)
        return agent_type
    
    def _should_show_ai_button(self, user_id: int) -> bool:
        """Проверка показывать ли кнопку ИИ с логированием"""
        show_button = True  # Пока всегда показываем
        logger.debug("🔍 AI button visibility check", 
                    user_id=user_id,
                    should_show=show_button)
        return show_button
    
    async def _cancel_and_show_ai(self, message: Message, state: FSMContext):
        """Отмена и показ настроек ИИ с логированием"""
        logger.info("❌ Cancelling AI operation", 
                   user_id=message.from_user.id,
                   bot_id=self.bot_id)
        
        await state.clear()
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
        ])
        await message.answer("Настройка отменена", reply_markup=keyboard)
    
    async def _safe_update_user_bot(self, **kwargs):
        """Безопасное обновление настроек UserBot с логированием"""
        logger.info("🔄 Attempting UserBot update", 
                   bot_id=self.bot_id,
                   update_keys=list(kwargs.keys()))
        
        try:
            if self.user_bot and hasattr(self.user_bot, 'update_ai_settings'):
                await self.user_bot.update_ai_settings(**kwargs)
                logger.info("✅ UserBot update successful")
            else:
                logger.warning("⚠️ UserBot doesn't have update_ai_settings method", 
                             bot_id=self.bot_id,
                             has_user_bot=bool(self.user_bot),
                             has_method=hasattr(self.user_bot, 'update_ai_settings') if self.user_bot else False)
        except Exception as e:
            logger.error("💥 Failed to update UserBot settings", 
                        bot_id=self.bot_id,
                        error=str(e),
                        error_type=type(e).__name__)
    
    async def _safe_update_bot_manager(self, **kwargs):
        """Безопасное обновление через bot_manager с логированием"""
        logger.info("🔄 Attempting BotManager update", 
                   bot_id=self.bot_id,
                   update_keys=list(kwargs.keys()))
        
        try:
            bot_manager = self.bot_config.get('bot_manager')
            if bot_manager and hasattr(bot_manager, 'update_bot_config'):
                await bot_manager.update_bot_config(self.bot_id, **kwargs)
                logger.info("✅ BotManager update successful")
            else:
                logger.warning("⚠️ BotManager doesn't have update_bot_config method", 
                             bot_id=self.bot_id,
                             has_bot_manager=bool(bot_manager),
                             has_method=hasattr(bot_manager, 'update_bot_config') if bot_manager else False)
        except Exception as e:
            logger.error("💥 Failed to update BotManager config", 
                        bot_id=self.bot_id,
                        error=str(e),
                        error_type=type(e).__name__)
    
    async def cb_admin_ai(self, callback: CallbackQuery):
        """Главное меню настроек ИИ с логированием"""
        logger.info("🎛️ Admin AI menu accessed", 
                   user_id=callback.from_user.id,
                   bot_id=self.bot_id)
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            logger.warning("🚫 Unauthorized access attempt", 
                          user_id=callback.from_user.id,
                          owner_user_id=self.owner_user_id)
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        agent_type = self._get_agent_type()
        
        logger.info("📊 Current AI state", 
                   agent_type=agent_type,
                   ai_enabled=self.ai_assistant_enabled,
                   ai_assistant_id_exists=bool(self.ai_assistant_id))
        
        # Если тип агента не выбран - показываем меню выбора
        if agent_type == 'none':
            logger.info("📋 Showing agent type selection")
            await self._show_agent_type_selection(callback)
            return
        
        # Показываем настройки конкретного типа агента
        if agent_type == 'chatforyou':
            logger.info("📋 Showing ChatForYou settings")
            await self._show_chatforyou_settings(callback)
        elif agent_type == 'openai':
            logger.info("📋 Showing OpenAI settings")
            await self._show_openai_settings(callback)
        else:
            logger.warning("❓ Unknown agent type, falling back to selection", 
                          agent_type=agent_type)
            await self._show_agent_type_selection(callback)
    
    async def _show_agent_type_selection(self, callback: CallbackQuery):
        """Показ меню выбора типа агента с логированием"""
        logger.info("📋 Displaying agent type selection menu", 
                   bot_id=self.bot_id)
        
        text = f"""
🤖 <b>ИИ Агент @{self.bot_username}</b>

Выберите тип ИИ агента для вашего бота:

🌐 <b>Подключить с платформы</b>
- ChatForYou (api.chatforyou.ru)
- ProTalk (api.pro-talk.ru)
- Требует API токен

🎨 <b>Создать своего агента</b>
- На базе OpenAI GPT-4o-mini
- Настройка роли и инструкций
- Работает через наш токен

<b>Что выберете?</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Подключить с платформы", callback_data="agent_type_chatforyou")],
            [InlineKeyboardButton(text="🎨 Создать своего агента", callback_data="agent_type_openai")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def _show_chatforyou_settings(self, callback: CallbackQuery):
        """Показ настроек ChatForYou с логированием"""
        logger.info("📋 Displaying ChatForYou settings", 
                   bot_id=self.bot_id,
                   ai_enabled=self.ai_assistant_enabled)
        
        ai_status = "включен" if self.ai_assistant_enabled else "выключен"
        
        # Проверяем статус конфигурации
        platform = self.ai_assistant_settings.get('detected_platform')
        config_status = "не настроен"
        platform_info = ""
        
        logger.info("🔍 ChatForYou configuration check", 
                   platform=platform,
                   has_assistant_id=bool(self.ai_assistant_id),
                   chatforyou_bot_id=self.ai_assistant_settings.get('chatforyou_bot_id'))
        
        if self.ai_assistant_id:
            if platform == 'chatforyou':
                bot_id_value = self.ai_assistant_settings.get('chatforyou_bot_id')
                if bot_id_value:
                    config_status = f"API: {self.ai_assistant_id[:10]}... | ID: {bot_id_value}"
                else:
                    config_status = f"API: {self.ai_assistant_id[:10]}... | ID: не задан"
            else:
                config_status = f"API: {self.ai_assistant_id[:10]}..."
            
            if platform:
                platform_names = {
                    'chatforyou': 'ChatForYou',
                    'protalk': 'ProTalk'
                }
                platform_display = platform_names.get(platform, platform)
                platform_info = f"\n🌐 Платформа: {platform_display}"
        
        text = f"""
🌐 <b>ИИ Агент с платформы</b>

<b>Текущие настройки:</b>
🤖 Статус: {ai_status}
🔑 Конфигурация: {config_status}{platform_info}

<b>Поддерживаемые платформы:</b>
- ChatForYou (требует API токен + ID сотрудника)
- ProTalk (требует только API токен)

<b>Настройка происходит в 2 шага:</b>
1️⃣ Ввод API токена
2️⃣ Ввод ID сотрудника (только для ChatForYou)
"""
        
        # Проверяем полную конфигурацию
        is_configured = False
        if self.ai_assistant_id:
            if platform == 'chatforyou':
                is_configured = bool(self.ai_assistant_settings.get('chatforyou_bot_id'))
            else:
                is_configured = True
        
        logger.info("📊 Configuration status", 
                   is_configured=is_configured,
                   platform=platform)
        
        keyboard = AIKeyboards.chatforyou_settings_menu(
            self.ai_assistant_enabled,
            is_configured,
            platform
        )
        
        # Добавляем кнопку смены типа агента
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="🔄 Сменить тип агента", callback_data="ai_change_type")
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def _show_openai_settings(self, callback: CallbackQuery):
        """Показ настроек OpenAI агента с логированием"""
        logger.info("📋 Displaying OpenAI settings", 
                   bot_id=self.bot_id,
                   ai_enabled=self.ai_assistant_enabled)
        
        agent_status = "включен" if self.ai_assistant_enabled else "выключен"
        
        # Получаем информацию об OpenAI агенте
        local_agent_id = self.ai_assistant_settings.get('local_agent_id')
        openai_assistant_id = self.ai_assistant_settings.get('openai_assistant_id')
        agent_name = self.ai_assistant_settings.get('agent_name')
        creation_method = self.ai_assistant_settings.get('creation_method', 'unknown')
        
        logger.info("🔍 OpenAI agent info", 
                   local_agent_id=local_agent_id,
                   openai_assistant_id=openai_assistant_id,
                   agent_name=agent_name,
                   creation_method=creation_method)
        
        agent_info = "не создан"
        agent_details = ""
        
        if local_agent_id:
            try:
                agent_info = f"ID: {local_agent_id}"
                if agent_name:
                    agent_info = f"{agent_name} (ID: {local_agent_id})"
                
                if openai_assistant_id:
                    agent_details = f"\n🆔 OpenAI ID: {openai_assistant_id[:15]}..."
                
                if creation_method == 'fallback_stub':
                    agent_details += "\n⚠️ Режим: Тестовый (OpenAI недоступен)"
                elif creation_method == 'real_openai_api':
                    agent_details += "\n✅ Режим: Реальный OpenAI"
                elif creation_method == 'chat_api_fallback':
                    agent_details += "\n🔄 Режим: Chat API (Fallback)"
                    
            except Exception as e:
                logger.error("💥 Failed to get OpenAI agent info", 
                           error=str(e),
                           error_type=type(e).__name__)
        
        text = f"""
🎨 <b>Собственный ИИ Агент</b>

<b>Текущие настройки:</b>
🤖 Статус: {agent_status}
🎯 Агент: {agent_info}{agent_details}
🧠 Модель: GPT-4o-mini
⚡ Лимиты: без ограничений

<b>Преимущества собственного агента:</b>
- Полная настройка роли и поведения
- Быстрые ответы через OpenAI API
- Без дополнительных токенов
- Стабильная работа 24/7

<b>Управление агентом:</b>
"""
        
        # Создаем клавиатуру для OpenAI агента
        keyboard = AIKeyboards.openai_settings_menu(
            self.ai_assistant_enabled,
            bool(local_agent_id)
        )
        
        # Добавляем кнопку смены типа агента
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="🔄 Сменить тип агента", callback_data="ai_change_type")
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def cb_select_agent_type(self, callback: CallbackQuery):
        """Обработка выбора типа агента с логированием"""
        logger.info("🎯 Agent type selection", 
                   user_id=callback.from_user.id,
                   callback_data=callback.data)
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            logger.warning("🚫 Unauthorized agent type selection", 
                          user_id=callback.from_user.id)
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        agent_type = callback.data.replace("agent_type_", "")
        
        logger.info("🔄 Changing agent type", 
                   bot_id=self.bot_id,
                   new_agent_type=agent_type,
                   old_agent_type=self._get_agent_type())
        
        try:
            # Обновляем тип агента в настройках
            ai_settings = self.ai_assistant_settings.copy()
            ai_settings['agent_type'] = agent_type
            
            logger.info("💾 Updating agent type in database")
            await self.db.update_ai_assistant(
                self.bot_id,
                settings=ai_settings
            )
            
            # Обновляем локальные настройки
            self.ai_assistant_settings = ai_settings
            
            logger.info("✅ Agent type updated successfully", 
                       bot_id=self.bot_id,
                       agent_type=agent_type)
            
            # Безопасное обновление UserBot
            await self._safe_update_user_bot(ai_assistant_settings=ai_settings)
            
            # Безопасное обновление bot_manager
            await self._safe_update_bot_manager(ai_assistant_settings=ai_settings)
            
            # Переходим к настройкам выбранного типа
            if agent_type == 'chatforyou':
                await self._show_chatforyou_settings(callback)
            elif agent_type == 'openai':
                await self._show_openai_settings(callback)
                
        except Exception as e:
            logger.error("💥 Failed to set agent type", 
                        bot_id=self.bot_id,
                        agent_type=agent_type,
                        error=str(e),
                        error_type=type(e).__name__)
            await callback.answer("Ошибка при сохранении типа агента", show_alert=True)
    
    async def cb_ai_action(self, callback: CallbackQuery, state: FSMContext):
        """Обработка действий для ChatForYou с логированием"""
        logger.info("🎯 AI action callback", 
                   user_id=callback.from_user.id,
                   callback_data=callback.data)
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            logger.warning("🚫 Unauthorized AI action", 
                          user_id=callback.from_user.id)
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        action = callback.data.replace("ai_", "")
        
        logger.info("🔄 Processing AI action", 
                   action=action,
                   bot_id=self.bot_id)
        
        if action == "toggle":
            await self._toggle_ai_assistant(callback)
        elif action == "set_id":
            await self._set_assistant_id(callback, state)
        elif action == "test":
            await self._test_ai_assistant(callback, state)
        elif action == "change_type":
            await self._change_agent_type(callback)
    
    async def cb_openai_action(self, callback: CallbackQuery, state: FSMContext):
        """Обработка действий для OpenAI агента с логированием"""
        logger.info("🎯 OpenAI action callback", 
                   user_id=callback.from_user.id,
                   callback_data=callback.data)
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            logger.warning("🚫 Unauthorized OpenAI action", 
                          user_id=callback.from_user.id)
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        action = callback.data.replace("openai_", "")
        
        logger.info("🔄 Processing OpenAI action", 
                   action=action,
                   bot_id=self.bot_id)
        
        if action == "toggle":
            await self._toggle_openai_assistant(callback)
        elif action == "create":
            await self._create_openai_agent(callback, state)
        elif action == "edit":
            await self._edit_openai_agent(callback, state)
        elif action == "delete":
            await self._delete_openai_agent(callback)
        elif action == "test":
            await self._test_openai_assistant(callback, state)
    
    async def _toggle_ai_assistant(self, callback: CallbackQuery):
        """Переключение ИИ ассистента (ChatForYou) с логированием"""
        logger.info("🔄 Toggling ChatForYou AI assistant", 
                   current_status=self.ai_assistant_enabled,
                   bot_id=self.bot_id)
        
        try:
            new_status = not self.ai_assistant_enabled
            
            ai_settings = self.ai_assistant_settings.copy()
            
            logger.info("💾 Updating ChatForYou assistant status in database")
            await self.db.update_ai_assistant(
                self.bot_id,
                enabled=new_status,
                settings=ai_settings
            )
            
            self.ai_assistant_enabled = new_status
            
            # Безопасное обновление
            await self._safe_update_user_bot(ai_assistant_enabled=new_status)
            await self._safe_update_bot_manager(
                ai_assistant_enabled=new_status,
                ai_assistant_settings=ai_settings
            )
            
            status_text = "включен" if new_status else "выключен"
            logger.info("✅ ChatForYou AI assistant toggled", 
                       new_status=new_status,
                       status_text=status_text)
            
            await callback.answer(f"ИИ агент {status_text}!", show_alert=True)
            await self._show_chatforyou_settings(callback)
            
        except Exception as e:
            logger.error("💥 Failed to toggle ChatForYou AI assistant", 
                        error=str(e),
                        error_type=type(e).__name__)
            await callback.answer("Ошибка при изменении настроек", show_alert=True)
    
    async def _toggle_openai_assistant(self, callback: CallbackQuery):
        """Переключение OpenAI ассистента с логированием"""
        logger.info("🔄 Toggling OpenAI assistant", 
                   current_status=self.ai_assistant_enabled,
                   bot_id=self.bot_id)
        
        try:
            new_status = not self.ai_assistant_enabled
            
            ai_settings = self.ai_assistant_settings.copy()
            
            logger.info("💾 Updating OpenAI assistant status in database")
            await self.db.update_ai_assistant(
                self.bot_id,
                enabled=new_status,
                settings=ai_settings
            )
            
            self.ai_assistant_enabled = new_status
            
            # Безопасное обновление
            await self._safe_update_user_bot(ai_assistant_enabled=new_status)
            await self._safe_update_bot_manager(
                ai_assistant_enabled=new_status,
                ai_assistant_settings=ai_settings
            )
            
            status_text = "включен" if new_status else "выключен"
            logger.info("✅ OpenAI assistant toggled", 
                       new_status=new_status,
                       status_text=status_text)
            
            await callback.answer(f"OpenAI агент {status_text}!", show_alert=True)
            await self._show_openai_settings(callback)
            
        except Exception as e:
            logger.error("💥 Failed to toggle OpenAI assistant", 
                        error=str(e),
                        error_type=type(e).__name__)
            await callback.answer("Ошибка при изменении настроек", show_alert=True)
    
    async def _set_assistant_id(self, callback: CallbackQuery, state: FSMContext):
        """Настройка ID ассистента (ChatForYou) с логированием"""
        logger.info("🔧 Setting ChatForYou assistant ID", 
                   bot_id=self.bot_id)
        
        await state.set_state(AISettingsStates.waiting_for_api_token)
        
        text = f"""
🔑 <b>Шаг 1/2: API токен</b>

Введите API токен от ChatForYou или ProTalk.

<b>Поддерживаемые платформы:</b>
- ChatForYou (api.chatforyou.ru)
- ProTalk (api.pro-talk.ru)

Система автоматически определит платформу по токену.

<b>Пример токена:</b> <code>your_api_token_here</code>

<b>Отправьте API токен:</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="admin_ai")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def _test_ai_assistant(self, callback: CallbackQuery, state: FSMContext):
        """Тестирование ИИ ассистента (ChatForYou) с логированием"""
        logger.info("🧪 Starting ChatForYou AI assistant test", 
                   bot_id=self.bot_id,
                   has_assistant_id=bool(self.ai_assistant_id))
        
        if not self.ai_assistant_id:
            logger.warning("❌ No assistant ID for testing")
            await callback.answer("❌ Сначала настройте API токен", show_alert=True)
            return
        
        platform = self.ai_assistant_settings.get('detected_platform')
        if not platform:
            logger.warning("❌ No platform detected for testing")
            await callback.answer("❌ Платформа не определена. Перенастройте токен.", show_alert=True)
            return
        
        if platform == 'chatforyou' and not self.ai_assistant_settings.get('chatforyou_bot_id'):
            logger.warning("❌ ChatForYou requires bot ID")
            await callback.answer("❌ Для ChatForYou требуется ID сотрудника", show_alert=True)
            return
        
        logger.info("✅ Starting test mode", 
                   platform=platform,
                   chatforyou_bot_id=self.ai_assistant_settings.get('chatforyou_bot_id'))
        
        await state.set_state(AISettingsStates.in_ai_conversation)
        await state.update_data(is_test_mode=True, agent_type='chatforyou')
        
        platform_names = {
            'chatforyou': 'ChatForYou',
            'protalk': 'ProTalk'
        }
        platform_display = platform_names.get(platform, platform)
        
        bot_id_info = ""
        if platform == 'chatforyou':
            bot_id_info = f"\n<b>ID сотрудника:</b> {self.ai_assistant_settings.get('chatforyou_bot_id')}"
        
        text = f"""
🧪 <b>Тестирование ИИ агента (ChatForYou)</b>

<b>API Token:</b> {self.ai_assistant_id[:15]}...
<b>Платформа:</b> {platform_display}{bot_id_info}

Отправьте любое сообщение для тестирования ИИ агента. 

<b>Напишите ваш вопрос:</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚪 Выйти из тестирования", callback_data="admin_ai")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def _test_openai_assistant(self, callback: CallbackQuery, state: FSMContext):
        """Тестирование OpenAI ассистента с логированием"""
        logger.info("🧪 Starting OpenAI assistant test", 
                   bot_id=self.bot_id)
        
        local_agent_id = self.ai_assistant_settings.get('local_agent_id')
        if not local_agent_id:
            logger.warning("❌ No OpenAI agent created for testing")
            await callback.answer("❌ Сначала создайте OpenAI агента", show_alert=True)
            return
        
        logger.info("✅ Starting OpenAI test mode", 
                   local_agent_id=local_agent_id)
        
        await state.set_state(AISettingsStates.in_ai_conversation)
        await state.update_data(is_test_mode=True, agent_type='openai')
        
        text = f"""
🧪 <b>Тестирование OpenAI агента</b>

<b>Агент ID:</b> {local_agent_id}
<b>Модель:</b> GPT-4o-mini
<b>Режим:</b> Тестирование

Отправьте любое сообщение для тестирования OpenAI агента.

<b>Напишите ваш вопрос:</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚪 Выйти из тестирования", callback_data="admin_ai")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def _change_agent_type(self, callback: CallbackQuery):
        """Смена типа агента с логированием"""
        logger.info("🔄 Agent type change request", 
                   bot_id=self.bot_id,
                   current_type=self._get_agent_type())
        
        text = """
🔄 <b>Смена типа ИИ агента</b>

⚠️ <b>Внимание!</b> При смене типа агента:
- Текущая конфигурация будет сброшена
- Все настройки придется настроить заново
- Диалоги пользователей завершатся

Вы уверены, что хотите сменить тип агента?
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, сменить", callback_data="ai_confirm_change_type")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_ai")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def _create_openai_agent(self, callback: CallbackQuery, state: FSMContext):
        """Начало создания OpenAI агента с логированием"""
        logger.info("🎨 Starting OpenAI agent creation flow", 
                   user_id=callback.from_user.id,
                   bot_id=self.bot_id)
        
        await state.set_state(AISettingsStates.waiting_for_openai_name)
        
        text = f"""
🎨 <b>Создание собственного ИИ агента</b>

<b>Шаг 1/2: Имя агента</b>

Придумайте имя для вашего ИИ агента. Оно будет отображаться пользователям при общении.

<b>Примеры хороших имен:</b>
- Консультант Мария
- Помощник Алекс
- Эксперт по продажам
- Тренер по фитнесу

<b>Введите имя агента:</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_ai")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def handle_openai_name_input(self, message: Message, state: FSMContext):
        """Обработка ввода имени OpenAI агента с логированием"""
        logger.info("📝 OpenAI agent name input", 
                   user_id=message.from_user.id,
                   input_text=message.text,
                   bot_id=self.bot_id)
        
        if not self._is_owner(message.from_user.id):
            logger.warning("🚫 Unauthorized name input", user_id=message.from_user.id)
            return
        
        if message.text == "/cancel":
            await self._cancel_and_show_ai(message, state)
            return
        
        agent_name = message.text.strip()
        
        logger.info("🔍 Validating agent name", 
                   agent_name=agent_name,
                   name_length=len(agent_name))
        
        if len(agent_name) < 2:
            logger.warning("❌ Agent name too short", 
                          name_length=len(agent_name))
            await message.answer("❌ Имя агента должно быть не менее 2 символов. Попробуйте еще раз:")
            return
        
        if len(agent_name) > 100:
            logger.warning("❌ Agent name too long", 
                          name_length=len(agent_name))
            await message.answer("❌ Имя агента слишком длинное (максимум 100 символов). Попробуйте еще раз:")
            return
        
        # Сохраняем имя в состоянии
        await state.update_data(agent_name=agent_name)
        await state.set_state(AISettingsStates.waiting_for_openai_role)
        
        logger.info("✅ Agent name accepted, moving to role input", 
                   agent_name=agent_name)
        
        text = f"""
✅ <b>Имя сохранено:</b> {agent_name}

<b>Шаг 2/2: Роль и инструкции</b>

Опишите роль вашего агента и то, как он должен отвечать пользователям. Это очень важно для качества ответов!

<b>Примеры хороших ролей:</b>
- "Ты эксперт по фитнесу. Отвечай дружелюбно, давай практичные советы по тренировкам и питанию."
- "Ты консультант по продажам. Помогай клиентам выбрать подходящий товар, отвечай профессионально."
- "Ты психолог-консультант. Выслушивай внимательно и давай поддерживающие советы."

<b>Введите роль и инструкции:</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_ai")]
        ])
        
        await message.answer(text, reply_markup=keyboard)
    
    async def handle_openai_role_input(self, message: Message, state: FSMContext):
        """Обработка ввода роли OpenAI агента с улучшенным UX и логированием"""
        logger.info("📝 OpenAI agent role input", 
                   user_id=message.from_user.id,
                   input_length=len(message.text),
                   bot_id=self.bot_id)
        
        if not self._is_owner(message.from_user.id):
            logger.warning("🚫 Unauthorized role input", user_id=message.from_user.id)
            return
        
        if message.text == "/cancel":
            await self._cancel_and_show_ai(message, state)
            return
        
        agent_role = message.text.strip()
        
        logger.info("🔍 Validating agent role", 
                   role_length=len(agent_role))
        
        if len(agent_role) < 10:
            logger.warning("❌ Agent role too short", 
                          role_length=len(agent_role))
            await message.answer("❌ Описание роли слишком короткое (минимум 10 символов). Попробуйте еще раз:")
            return
        
        if len(agent_role) > 1000:
            logger.warning("❌ Agent role too long", 
                          role_length=len(agent_role))
            await message.answer("❌ Описание роли слишком длинное (максимум 1000 символов). Попробуйте еще раз:")
            return
        
        try:
            # Получаем данные из состояния
            data = await state.get_data()
            agent_name = data.get('agent_name')
            
            logger.info("📊 Agent creation data", 
                       agent_name=agent_name,
                       agent_role=agent_role)
            
            if not agent_name:
                logger.error("❌ Agent name lost from state")
                await message.answer("❌ Ошибка: имя агента потеряно. Начните заново.")
                await state.clear()
                return
            
            # ✨ УЛУЧШЕННЫЙ UX: Показываем прогресс пользователю
            progress_message = await message.answer("🔄 Создаю агента в OpenAI...")
            
            logger.info("🚀 Calling _create_agent_in_openai")
            success, response_data = await self._create_agent_in_openai(agent_name, agent_role)
            
            logger.info("📊 Agent creation result", 
                       success=success,
                       response_keys=list(response_data.keys()) if response_data else None)
            
            if success:
                creation_method = response_data.get('creation_method', 'unknown')
                duration = response_data.get('total_duration', 'unknown')
                
                success_message = f"🎉 <b>Агент успешно создан!</b>\n\n"
                success_message += f"<b>Имя:</b> {agent_name}\n"
                success_message += f"<b>Роль:</b> {agent_role[:100]}{'...' if len(agent_role) > 100 else ''}\n"
                
                if creation_method == 'real_openai_api':
                    success_message += f"\n✅ <b>Создан в OpenAI</b> за {duration}\n"
                elif creation_method == 'fallback_stub':
                    success_message += f"\n⚠️ <b>Тестовый режим</b> (OpenAI недоступен)\n"
                elif creation_method == 'chat_api_fallback':
                    success_message += f"\n🔄 <b>Создан через Chat API</b> (Assistants API временно недоступен)\n"
                
                success_message += f"\nТеперь можете протестировать работу агента!"
                
                await progress_message.edit_text(
                    success_message,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🧪 Тестировать", callback_data="openai_test")],
                        [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
                    ])
                )
            else:
                error_msg = response_data.get('error', 'Неизвестная ошибка')
                
                # ✨ УЛУЧШЕННЫЙ UX: Анализируем тип ошибки и даем понятное объяснение
                if "500" in error_msg or "server_error" in error_msg:
                    user_friendly_error = """
❌ <b>Временная проблема с OpenAI</b>

Серверы OpenAI сейчас перегружены. Это частая ситуация.

<b>Что делать:</b>
• Попробуйте через 2-3 минуты
• Или создайте агента позже
• Проблема решится автоматически

<b>Это НЕ ошибка вашего бота!</b>
"""
                elif "429" in error_msg or "rate" in error_msg:
                    user_friendly_error = """
❌ <b>Превышен лимит запросов</b>

OpenAI ограничивает количество запросов в минуту.

<b>Что делать:</b>
• Подождите 1-2 минуты
• Попробуйте создать агента снова
• Это временное ограничение
"""
                elif "401" in error_msg or "unauthorized" in error_msg:
                    user_friendly_error = """
❌ <b>Проблема с API ключом</b>

Возможно API ключ OpenAI неактивен.

<b>Обратитесь к администратору</b>
"""
                else:
                    user_friendly_error = f"""
❌ <b>Ошибка при создании агента</b>

{error_msg}

<b>Попробуйте еще раз через несколько минут</b>
"""
                
                logger.error("❌ Agent creation failed", error=error_msg)
                
                await progress_message.edit_text(
                    user_friendly_error,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="openai_create")],
                        [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
                    ])
                )
            
            await state.clear()
            
        except Exception as e:
            logger.error("💥 Failed to create OpenAI agent", 
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            await message.answer(
                "❌ Произошла ошибка при создании агента. Попробуйте еще раз.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
                ])
            )
            await state.clear()
    
    async def _create_agent_in_openai(self, name: str, role: str) -> tuple[bool, dict]:
        """
        Создание агента в OpenAI с детальным логированием
        
        Returns:
            tuple: (success: bool, response_data: dict)
        """
        
        # 🔍 ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ - НАЧАЛО
        logger.info("🎬 Starting OpenAI agent creation process", 
                   bot_id=self.bot_id,
                   owner_user_id=self.owner_user_id,
                   agent_name=name,
                   agent_role=role,
                   name_length=len(name),
                   role_length=len(role))
        
        overall_start_time = time.time()
        
        try:
            # Попытка импорта OpenAI сервиса
            logger.info("📦 Attempting to import OpenAI service...")
            
            try:
                from services.openai_assistant import openai_client
                from services.openai_assistant.models import OpenAICreateAgentRequest
                
                logger.info("✅ OpenAI service imported successfully", 
                           client_type=type(openai_client).__name__,
                           client_available=hasattr(openai_client, 'create_assistant'))
                
                # Проверка доступности клиента
                if hasattr(openai_client, 'is_available'):
                    is_available = openai_client.is_available()
                    logger.info("🔧 OpenAI client availability check", 
                               is_available=is_available)
                    
                    if not is_available:
                        logger.warning("⚠️ OpenAI client reports not available")
                
                # Создание запроса
                logger.info("📋 Creating OpenAI agent request...")
                
                system_prompt = f"Ты - {role}. Твое имя {name}. Отвечай полезно и дружелюбно."
                
                request = OpenAICreateAgentRequest(
                    bot_id=self.bot_id,
                    agent_name=name,
                    agent_role=role,
                    system_prompt=system_prompt
                )
                
                logger.info("✅ Request object created", 
                           request_bot_id=request.bot_id,
                           request_agent_name=request.agent_name,
                           request_model=request.model,
                           request_temperature=request.temperature,
                           request_max_tokens=request.max_tokens,
                           system_prompt_length=len(system_prompt))
                
                # Валидация запроса
                logger.info("🔍 Validating request...")
                
                is_valid, error_msg = openai_client.validate_create_request(request)
                
                logger.info("📊 Request validation result", 
                           is_valid=is_valid,
                           error_message=error_msg if not is_valid else None)
                
                if not is_valid:
                    logger.error("❌ OpenAI request validation failed", 
                               validation_error=error_msg,
                               request_data=request.__dict__)
                    return False, {"error": error_msg}
                
                logger.info("✅ Request validation passed")
                
                # Конвертация в агента
                logger.info("🔄 Converting request to agent...")
                agent = request.to_agent()
                
                logger.info("✅ Agent object created", 
                           agent_id=agent.id,
                           agent_bot_id=agent.bot_id,
                           agent_name=agent.agent_name,
                           agent_model=agent.model,
                           agent_active=agent.is_active)
                
                # Основной вызов создания ассистента
                logger.info("🚀 Calling OpenAI assistant creation...")
                
                creation_start_time = time.time()
                
                response = await openai_client.create_assistant(agent)
                
                creation_duration = time.time() - creation_start_time
                
                logger.info("📡 OpenAI assistant creation call completed", 
                           duration=f"{creation_duration:.2f}s",
                           response_success=response.success,
                           response_message=response.message if response.success else None,
                           response_error=response.error if not response.success else None,
                           assistant_id=response.assistant_id if response.success else None)
                
                if response.success:
                    # ✅ УСПЕШНОЕ СОЗДАНИЕ
                    logger.info("🎉 OpenAI assistant created successfully")
                    
                    # Подготовка настроек для сохранения
                    logger.info("💾 Preparing settings for database save...")
                    
                    ai_settings = self.ai_assistant_settings.copy()
                    
                    settings_update = {
                        'agent_type': 'openai',
                        'local_agent_id': f"openai_{int(datetime.now().timestamp())}",
                        'openai_assistant_id': response.assistant_id,
                        'agent_name': name,
                        'agent_role': role,
                        'created_at': datetime.now().isoformat(),
                        'creation_method': 'real_openai_api',
                        'model_used': agent.model,
                        'system_prompt': system_prompt
                    }
                    
                    ai_settings.update(settings_update)
                    
                    logger.info("📊 Settings prepared for update", 
                               settings_keys=list(settings_update.keys()),
                               local_agent_id=settings_update['local_agent_id'],
                               openai_assistant_id=settings_update['openai_assistant_id'])
                    
                    # Сохранение в БД
                    logger.info("💾 Saving to database...")
                    
                    try:
                        await self.db.update_ai_assistant(
                            self.bot_id,
                            settings=ai_settings
                        )
                        
                        logger.info("✅ Database update successful")
                        
                    except Exception as db_error:
                        logger.error("💥 Database update failed", 
                                   error=str(db_error),
                                   error_type=type(db_error).__name__)
                        # Не прерываем процесс, агент создан в OpenAI
                    
                    # Обновление локальных настроек
                    logger.info("🔄 Updating local settings...")
                    self.ai_assistant_settings = ai_settings
                    
                    # Безопасное обновление других компонентов
                    logger.info("🔄 Updating other components...")
                    
                    try:
                        await self._safe_update_user_bot(ai_assistant_settings=ai_settings)
                        logger.info("✅ UserBot updated")
                    except Exception as update_error:
                        logger.error("⚠️ UserBot update failed", error=str(update_error))
                    
                    try:
                        await self._safe_update_bot_manager(ai_assistant_settings=ai_settings)
                        logger.info("✅ BotManager updated")
                    except Exception as update_error:
                        logger.error("⚠️ BotManager update failed", error=str(update_error))
                    
                    total_duration = time.time() - overall_start_time
                    
                    logger.info("🏁 OpenAI agent creation process completed successfully", 
                               bot_id=self.bot_id,
                               agent_name=name,
                               assistant_id=response.assistant_id,
                               total_duration=f"{total_duration:.2f}s",
                               creation_duration=f"{creation_duration:.2f}s")
                    
                    return True, {
                        "assistant_id": response.assistant_id,
                        "message": response.message,
                        "local_agent_id": settings_update['local_agent_id'],
                        "creation_method": "real_openai_api",
                        "creation_duration": creation_duration,
                        "total_duration": total_duration
                    }
                    
                else:
                    # ❌ ОШИБКА СОЗДАНИЯ
                    logger.error("💥 OpenAI assistant creation failed", 
                               bot_id=self.bot_id,
                               agent_name=name,
                               error=response.error,
                               duration=f"{creation_duration:.2f}s")
                    
                    return False, {"error": response.error}
                    
            except ImportError as import_error:
                # 📦 FALLBACK ПРИ ОТСУТСТВИИ OPENAI СЕРВИСА
                logger.warning("📦 OpenAI service not available, using fallback", 
                              import_error=str(import_error),
                              fallback_mode="stub_creation")
                
                # Создание заглушки
                ai_settings = self.ai_assistant_settings.copy()
                
                stub_settings = {
                    'agent_type': 'openai',
                    'local_agent_id': f"stub_{int(datetime.now().timestamp())}",
                    'agent_name': name,
                    'agent_role': role,
                    'created_at': datetime.now().isoformat(),
                    'status': 'stub_created',
                    'creation_method': 'fallback_stub',
                    'reason': 'openai_service_not_available',
                    'import_error': str(import_error)
                }
                
                ai_settings.update(stub_settings)
                
                logger.info("💾 Saving stub configuration...", 
                           stub_id=stub_settings['local_agent_id'])
                
                try:
                    await self.db.update_ai_assistant(self.bot_id, settings=ai_settings)
                    self.ai_assistant_settings = ai_settings
                    
                    total_duration = time.time() - overall_start_time
                    
                    logger.info("✅ Stub agent created successfully", 
                               bot_id=self.bot_id, 
                               agent_name=name,
                               local_agent_id=stub_settings['local_agent_id'],
                               total_duration=f"{total_duration:.2f}s")
                    
                    return True, {
                        "message": "Агент создан (тестовый режим - OpenAI сервис недоступен)",
                        "local_agent_id": stub_settings['local_agent_id'],
                        "creation_method": "fallback_stub",
                        "total_duration": total_duration
                    }
                    
                except Exception as db_error:
                    logger.error("💥 Failed to save stub configuration", 
                               error=str(db_error),
                               error_type=type(db_error).__name__)
                    return False, {"error": f"Fallback creation failed: {str(db_error)}"}
                
        except Exception as e:
            # 🚨 ОБЩАЯ ОБРАБОТКА ОШИБОК
            total_duration = time.time() - overall_start_time
            
            logger.error("💥 Exception in _create_agent_in_openai", 
                        bot_id=self.bot_id,
                        agent_name=name,
                        exception_type=type(e).__name__,
                        exception_message=str(e),
                        total_duration=f"{total_duration:.2f}s",
                        full_exception=repr(e),
                        exc_info=True)
            
            return False, {"error": f"Внутренняя ошибка: {str(e)}"}
    
    # ============ ОБРАБОТЧИКИ ВВОДА CHATFORYOU ============
    
    async def handle_api_token_input(self, message: Message, state: FSMContext):
        """Обработка ввода API токена (существующая логика) с логированием"""
        logger.info("📝 ChatForYou API token input", 
                   user_id=message.from_user.id,
                   input_length=len(message.text),
                   bot_id=self.bot_id)
        
        if not self._is_owner(message.from_user.id):
            logger.warning("🚫 Unauthorized token input", user_id=message.from_user.id)
            return
        
        if message.text == "/cancel":
            await self._cancel_and_show_ai(message, state)
            return
        
        api_token = message.text.strip()
        
        logger.info("🔍 Processing API token", 
                   token_length=len(api_token),
                   token_prefix=api_token[:12] + "..." if len(api_token) > 12 else api_token)
        
        try:
            await message.answer("🔍 Определяем платформу...")
            
            logger.info("📡 Calling platform detection")
            success, platform, error_msg = await self.db.detect_and_validate_ai_platform(api_token)
            
            logger.info("📊 Platform detection result", 
                       success=success,
                       platform=platform,
                       error=error_msg if not success else None)
            
            if not success:
                logger.warning("❌ Platform detection failed", error=error_msg)
                await message.answer(
                    f"❌ {error_msg}\n\n"
                    f"Проверьте токен и попробуйте еще раз:"
                )
                return
            
            await state.update_data(api_token=api_token, platform=platform)
            
            if platform == 'chatforyou':
                logger.info("🔧 ChatForYou detected, requesting bot ID")
                await state.set_state(AISettingsStates.waiting_for_bot_id)
                
                text = f"""
✅ <b>Токен сохранен для платформы ChatForYou!</b>

🆔 <b>Шаг 2/2: ID сотрудника</b>

Для завершения настройки ChatForYou введите ваш ID сотрудника.

<b>Пример:</b> <code>21472</code>

<b>Важно:</b> ID должен быть числом, активным в системе ChatForYou.

<b>Отправьте ID сотрудника:</b>
"""
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Отмена", callback_data="admin_ai")]
                ])
                
                await message.answer(text, reply_markup=keyboard)
                
            else:
                # ProTalk готов к использованию
                logger.info("🔧 ProTalk detected, saving configuration")
                ai_settings = self.ai_assistant_settings.copy()
                ai_settings.update({
                    'detected_platform': platform,
                    'platform_detected_at': datetime.now().isoformat(),
                    'platform_validation': 'completed'
                })
                
                logger.info("💾 Saving ProTalk configuration to database")
                await self.db.update_ai_assistant_with_platform(
                    self.bot_id,
                    api_token=api_token,
                    bot_id_value=None,
                    settings=ai_settings,
                    platform=platform
                )
                
                # Обновляем настройки
                self.ai_assistant_id = api_token
                self.ai_assistant_settings = ai_settings
                
                # Безопасное обновление
                await self._safe_update_user_bot(
                    ai_assistant_id=api_token,
                    ai_assistant_settings=ai_settings
                )
                await self._safe_update_bot_manager(
                    ai_assistant_id=api_token,
                    ai_assistant_settings=ai_settings
                )
                
                success_text = f"""
✅ <b>ProTalk настроен и готов!</b>

<b>API Token:</b> <code>{api_token[:15]}...</code>
<b>Платформа:</b> ProTalk
<b>Статус:</b> ✅ Готов к работе

🔥 Теперь можете протестировать работу ИИ агента!
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🧪 Тестировать ИИ", callback_data="ai_test")],
                    [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
                ])
                
                logger.info("✅ ProTalk configuration completed successfully")
                await message.answer(success_text, reply_markup=keyboard)
                await state.clear()
                
        except Exception as e:
            logger.error("💥 Failed to process API token", 
                        error=str(e),
                        error_type=type(e).__name__)
            await message.answer("❌ Ошибка при обработке токена")
            await state.clear()
    
    async def handle_bot_id_input(self, message: Message, state: FSMContext):
        """Обработка ввода ID сотрудника для ChatForYou с логированием"""
        logger.info("📝 ChatForYou bot ID input", 
                   user_id=message.from_user.id,
                   input_text=message.text,
                   bot_id=self.bot_id)
        
        if not self._is_owner(message.from_user.id):
            logger.warning("🚫 Unauthorized bot ID input", user_id=message.from_user.id)
            return
        
        if message.text == "/cancel":
            await self._cancel_and_show_ai(message, state)
            return
        
        bot_id_value = message.text.strip()
        
        logger.info("🔍 Validating bot ID", 
                   bot_id_value=bot_id_value)
        
        try:
            int(bot_id_value)
        except ValueError:
            logger.warning("❌ Invalid bot ID format", 
                          bot_id_value=bot_id_value)
            await message.answer(
                f"❌ <b>ID сотрудника должен быть числом!</b>\n\n"
                f"Вы ввели: {bot_id_value}\n"
                f"Пример правильного ID: <code>21472</code>\n\n"
                f"Попробуйте еще раз:"
            )
            return
        
        bot_id_value = int(bot_id_value)
        
        logger.info("✅ Bot ID validation passed", 
                   bot_id_value=bot_id_value)
        
        try:
            data = await state.get_data()
            api_token = data.get('api_token')
            platform = data.get('platform')
            
            logger.info("📊 ChatForYou configuration data", 
                       has_api_token=bool(api_token),
                       platform=platform,
                       bot_id_value=bot_id_value)
            
            if not api_token or platform != 'chatforyou':
                logger.error("❌ Missing state data for ChatForYou")
                await message.answer("❌ Ошибка: данные первого шага потеряны. Начните заново.")
                await state.clear()
                return
            
            await message.answer("🔍 Проверяем соединение с ChatForYou...")
            
            logger.info("📡 Validating ChatForYou configuration")
            success, verified_platform, error_msg = await self.db.detect_and_validate_ai_platform(
                api_token, 
                test_bot_id=bot_id_value
            )
            
            logger.info("📊 ChatForYou validation result", 
                       success=success,
                       verified_platform=verified_platform,
                       error=error_msg if not success else None)
            
            if not success:
                logger.warning("❌ ChatForYou validation failed", error=error_msg)
                await message.answer(
                    f"❌ <b>Ошибка подключения к ChatForYou</b>\n\n"
                    f"{error_msg}\n\n"
                    f"Проверьте данные и попробуйте еще раз:"
                )
                return
            
            # Сохраняем конфигурацию
            logger.info("💾 Saving ChatForYou configuration")
            ai_settings = self.ai_assistant_settings.copy()
            ai_settings.update({
                'detected_platform': platform,
                'chatforyou_bot_id': bot_id_value,
                'platform_detected_at': datetime.now().isoformat(),
                'bot_id_verified': True,
                'bot_id_verified_at': datetime.now().isoformat(),
                'platform_validation': 'completed',
                'validation_method': 'real_api_test'
            })
            
            await self.db.update_ai_assistant_with_platform(
                self.bot_id,
                api_token=api_token,
                bot_id_value=bot_id_value,
                settings=ai_settings,
                platform=platform
            )
            
            # Обновляем настройки
            self.ai_assistant_id = api_token
            self.ai_assistant_settings = ai_settings
            
            # Безопасное обновление
            await self._safe_update_user_bot(
                ai_assistant_id=api_token,
                ai_assistant_settings=ai_settings
            )
            await self._safe_update_bot_manager(
                ai_assistant_id=api_token,
                ai_assistant_settings=ai_settings
            )
            
            success_text = f"""
🎉 <b>ChatForYou полностью настроен и протестирован!</b>

<b>API Token:</b> <code>{api_token[:15]}...</code>
<b>ID сотрудника:</b> {bot_id_value}
<b>Платформа:</b> ChatForYou
<b>Статус:</b> ✅ Проверено реальным API запросом

Теперь ИИ агент готов к работе с пользователями!
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🧪 Тестировать ИИ", callback_data="ai_test")],
                [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
            ])
            
            logger.info("✅ ChatForYou configuration completed successfully")
            await message.answer(success_text, reply_markup=keyboard)
            await state.clear()
            
        except Exception as e:
            logger.error("💥 Failed to validate ChatForYou configuration", 
                        error=str(e),
                        error_type=type(e).__name__)
            await message.answer("❌ Ошибка при проверке конфигурации ChatForYou")
            await state.clear()
    
    # Совместимость
    async def handle_ai_assistant_id_input(self, message: Message, state: FSMContext):
        """Обработчик для совместимости с логированием"""
        logger.info("📝 AI assistant ID input (compatibility)", 
                   user_id=message.from_user.id)
        await self.handle_api_token_input(message, state)
    
    async def handle_ai_daily_limit_input(self, message: Message, state: FSMContext):
        """Обработка ввода дневного лимита с логированием"""
        logger.info("📝 Daily limit input", 
                   user_id=message.from_user.id,
                   input_text=message.text)
        
        if not self._is_owner(message.from_user.id):
            logger.warning("🚫 Unauthorized daily limit input", user_id=message.from_user.id)
            return
        
        # Пока не используется для OpenAI, но может быть добавлено в будущем
        logger.info("ℹ️ Daily limit feature not implemented for current agent types")
        pass
    
    # ============ ОБЩИЕ ОБРАБОТЧИКИ ============
    
    async def handle_ai_conversation(self, message: Message, state: FSMContext):
        """Обработка диалога с ИИ (для обоих типов агентов) с логированием"""
        logger.info("💬 AI conversation message", 
                   user_id=message.from_user.id,
                   message_length=len(message.text),
                   bot_id=self.bot_id)
        
        try:
            data = await state.get_data()
            is_test_mode = data.get('is_test_mode', False)
            agent_type = data.get('agent_type', self._get_agent_type())
            user_id = message.from_user.id
            
            logger.info("📊 Conversation context", 
                       is_test_mode=is_test_mode,
                       agent_type=agent_type,
                       user_id=user_id)
            
            # В тестовом режиме только владелец может тестировать
            if is_test_mode and not self._is_owner(user_id):
                logger.warning("🚫 Unauthorized test conversation", user_id=user_id)
                return
            
            # Отправляем typing
            await message.bot.send_chat_action(message.chat.id, "typing")
            
            ai_response = None
            
            if agent_type == 'chatforyou':
                logger.info("🌐 Processing ChatForYou conversation")
                ai_response = await self._handle_chatforyou_conversation(message, data)
            elif agent_type == 'openai':
                logger.info("🎨 Processing OpenAI conversation")
                ai_response = await self._handle_openai_conversation(message, data)
            else:
                logger.warning("❓ Unknown agent type for conversation", agent_type=agent_type)
            
            if ai_response:
                keyboard = None
                if is_test_mode:
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🚪 Выйти из тестирования", callback_data="admin_ai")]
                    ])
                else:
                    keyboard = AIKeyboards.conversation_menu()
                
                logger.info("✅ AI response received and sent", 
                           response_length=len(ai_response),
                           has_keyboard=bool(keyboard))
                
                await message.answer(ai_response, reply_markup=keyboard)
            else:
                logger.error("❌ No AI response received")
                await message.answer(
                    "❌ Извините, ИИ агент временно недоступен. Попробуйте позже.",
                    reply_markup=ReplyKeyboardRemove()
                )
                await state.clear()
                
        except Exception as e:
            logger.error("💥 Error in AI conversation", 
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            await message.answer(
                "❌ Произошла ошибка при обращении к ИИ агенту.",
                reply_markup=ReplyKeyboardRemove()
            )
            await state.clear()
    
    async def _handle_chatforyou_conversation(self, message: Message, data: dict) -> str:
        """Обработка диалога с ChatForYou с логированием"""
        logger.info("🌐 ChatForYou conversation processing", 
                   user_id=message.from_user.id,
                   message_length=len(message.text))
        
        try:
            platform = self.ai_assistant_settings.get('detected_platform')
            if not platform:
                logger.error("❌ No platform detected for ChatForYou")
                return None
            
            bot_id_value = None
            if platform == 'chatforyou':
                bot_id_value = self.ai_assistant_settings.get('chatforyou_bot_id')
                if not bot_id_value:
                    logger.error("❌ No bot ID for ChatForYou")
                    return None
            
            logger.info("📊 ChatForYou conversation parameters", 
                       platform=platform,
                       bot_id_value=bot_id_value,
                       has_context_info=self.ai_assistant_settings.get('context_info', True))
            
            context = {}
            if self.ai_assistant_settings.get('context_info', True):
                context = {
                    "user_name": message.from_user.first_name or "Пользователь",
                    "username": message.from_user.username,
                    "is_test": data.get('is_test_mode', False)
                }
                
                logger.info("📝 Conversation context prepared", context=context)
            
            try:
                from services.ai_assistant import ai_client
                
                logger.info("📡 Sending message to ChatForYou AI service")
                
                ai_response = await ai_client.send_message(
                    api_token=self.ai_assistant_id,
                    message=message.text,
                    user_id=message.from_user.id,
                    bot_id=bot_id_value,
                    platform=platform,
                    context=context
                )
                
                logger.info("✅ ChatForYou response received", 
                           response_length=len(ai_response) if ai_response else 0)
                
                return ai_response
                
            except ImportError:
                logger.warning("📦 AI assistant service not available")
                return "🤖 ИИ сервис временно недоступен."
            
        except Exception as e:
            logger.error("💥 Error in ChatForYou conversation", 
                        error=str(e),
                        error_type=type(e).__name__)
            return None
    
    async def _handle_openai_conversation(self, message: Message, data: dict) -> str:
        """Обработка диалога с OpenAI агентом с логированием"""
        logger.info("🎨 OpenAI conversation processing", 
                   user_id=message.from_user.id,
                   message_length=len(message.text))
        
        try:
            # Пытаемся использовать OpenAI сервис
            try:
                from services.openai_assistant import openai_client
                from services.openai_assistant.models import OpenAIConversationContext
                
                openai_assistant_id = self.ai_assistant_settings.get('openai_assistant_id')
                if not openai_assistant_id:
                    logger.error("❌ No OpenAI assistant ID")
                    return "❌ OpenAI агент не настроен."
                
                logger.info("📊 OpenAI conversation parameters", 
                           openai_assistant_id=openai_assistant_id,
                           is_test_mode=data.get('is_test_mode', False))
                
                # Создаем контекст
                context = OpenAIConversationContext(
                    user_id=message.from_user.id,
                    user_name=message.from_user.first_name or "Пользователь",
                    username=message.from_user.username,
                    bot_id=self.bot_id,
                    chat_id=message.chat.id,
                    is_admin=data.get('is_test_mode', False)
                )
                
                logger.info("📝 OpenAI context prepared", 
                           user_name=context.user_name,
                           is_admin=context.is_admin)
                
                # Отправляем сообщение
                logger.info("📡 Sending message to OpenAI service")
                
                response = await openai_client.send_message(
                    assistant_id=openai_assistant_id,
                    message=message.text,
                    user_id=message.from_user.id,
                    context=context
                )
                
                logger.info("✅ OpenAI response received", 
                           response_length=len(response) if response else 0)
                
                return response or "❌ Не удалось получить ответ от OpenAI."
                
            except ImportError:
                # Fallback для случая когда OpenAI сервис недоступен
                logger.warning("📦 OpenAI service not available, using fallback")
                agent_name = self.ai_assistant_settings.get('agent_name', 'ИИ Агент')
                return f"🤖 {agent_name}: Получил ваше сообщение '{message.text}'. Это тестовый ответ, так как OpenAI сервис еще не подключен."
            
        except Exception as e:
            logger.error("💥 Error in OpenAI conversation", 
                        error=str(e),
                        error_type=type(e).__name__)
            return None
    
    async def handle_ai_button_click(self, message: Message, state: FSMContext):
        """Обработка нажатия кнопки вызова ИИ с логированием"""
        logger.info("🤖 AI button clicked", 
                   user_id=message.from_user.id,
                   bot_id=self.bot_id)
        
        try:
            user = message.from_user
            agent_type = self._get_agent_type()
            
            logger.info("📊 AI button click context", 
                       agent_type=agent_type,
                       ai_enabled=self.ai_assistant_enabled)
            
            # Проверяем что ИИ включен и настроен
            if not self.ai_assistant_enabled or agent_type == 'none':
                logger.warning("❌ AI agent not available for user")
                await message.answer(
                    "❌ ИИ агент временно недоступен.",
                    reply_markup=ReplyKeyboardRemove()
                )
                return
            
            # Переводим в режим общения с ИИ
            await state.set_state(AISettingsStates.in_ai_conversation)
            await state.update_data(agent_type=agent_type)
            
            agent_name = "ИИ агентом"
            if agent_type == 'openai':
                # Получаем имя OpenAI агента
                local_agent_id = self.ai_assistant_settings.get('local_agent_id')
                if local_agent_id:
                    saved_name = self.ai_assistant_settings.get('agent_name')
                    if saved_name:
                        agent_name = f"агентом {saved_name}"
                    else:
                        agent_name = "собственным ИИ агентом"
            
            logger.info("✅ Starting AI conversation", 
                       agent_name=agent_name,
                       agent_type=agent_type)
            
            welcome_text = f"""
🤖 <b>Добро пожаловать в чат с {agent_name}!</b>

Задавайте любые вопросы, я постараюсь помочь.

<b>Напишите ваш вопрос:</b>
"""
            
            await message.answer(welcome_text, reply_markup=AIKeyboards.conversation_menu())
            
        except Exception as e:
            logger.error("💥 Error handling AI button click", 
                        bot_id=self.bot_id,
                        error=str(e),
                        error_type=type(e).__name__)
            await message.answer(
                "❌ Произошла ошибка при запуске ИИ агента.",
                reply_markup=ReplyKeyboardRemove()
            )
    
    async def handle_ai_exit(self, message: Message, state: FSMContext):
        """Обработка выхода из диалога с ИИ с логированием"""
        logger.info("🚪 AI conversation exit", 
                   user_id=message.from_user.id,
                   bot_id=self.bot_id)
        
        if message.text == "🚪 Завершить диалог с ИИ":
            await message.answer(
                "👋 Диалог с ИИ агентом завершен. Спасибо за общение!",
                reply_markup=ReplyKeyboardRemove()
            )
            await state.clear()
            
            logger.info("✅ AI conversation ended successfully")
    
    # ============ ЗАГЛУШКИ ДЛЯ БУДУЩИХ OPENAI МЕТОДОВ ============
    
    async def _edit_openai_agent(self, callback: CallbackQuery, state: FSMContext):
        """Редактирование OpenAI агента с логированием"""
        logger.info("✏️ Edit OpenAI agent request", 
                   bot_id=self.bot_id,
                   user_id=callback.from_user.id)
        await callback.answer("🚧 Функция в разработке", show_alert=True)
    
    async def _delete_openai_agent(self, callback: CallbackQuery):
        """Удаление OpenAI агента с логированием"""
        logger.info("🗑️ Delete OpenAI agent request", 
                   bot_id=self.bot_id,
                   user_id=callback.from_user.id)
        await callback.answer("🚧 Функция в разработке", show_alert=True)
