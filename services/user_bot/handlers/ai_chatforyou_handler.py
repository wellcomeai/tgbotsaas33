"""
Обработчик ChatForYou и ProTalk агентов
Управляет подключением к внешним платформам ИИ
Поддерживает автоматическое определение платформы по токену
"""

import structlog
from datetime import datetime
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from ..states import AISettingsStates
from ..keyboards import AIKeyboards

logger = structlog.get_logger()


class ChatForYouHandler:
    """Обработчик внешних ИИ платформ (ChatForYou, ProTalk)"""
    
    def __init__(self, db, bot_config: dict, ai_assistant, user_bot):
        self.db = db
        self.bot_config = bot_config
        self.bot_id = bot_config['bot_id']
        self.owner_user_id = bot_config['owner_user_id']
        self.bot_username = bot_config['bot_username']
        self.ai_assistant = ai_assistant
        self.user_bot = user_bot
        
        # Хранимые ссылки на основной обработчик (будут обновляться)
        self._ai_assistant_id = bot_config.get('ai_assistant_id')
        self._ai_assistant_settings = bot_config.get('ai_assistant_settings', {})
        
        logger.info("🌐 ChatForYouHandler initialized", 
                   bot_id=self.bot_id,
                   has_external_agent=bool(self._ai_assistant_id))

    # ===== СВОЙСТВА ДЛЯ ДОСТУПА К АКТУАЛЬНЫМ ДАННЫМ =====
    
    @property
    def ai_assistant_id(self):
        """Получение актуального ID агента (API токена)"""
        return self._ai_assistant_id
    
    @ai_assistant_id.setter
    def ai_assistant_id(self, value):
        """Установка ID агента"""
        self._ai_assistant_id = value
    
    @property 
    def ai_assistant_settings(self):
        """Получение актуальных настроек агента"""
        return self._ai_assistant_settings
    
    @ai_assistant_settings.setter
    def ai_assistant_settings(self, value):
        """Установка настроек агента"""
        self._ai_assistant_settings = value

    # ===== ОСНОВНЫЕ МЕТОДЫ УПРАВЛЕНИЯ =====
    
    async def handle_ai_action(self, callback: CallbackQuery, state: FSMContext, is_owner_check):
        """Обработка действий для ChatForYou агента"""
        logger.info("🎯 ChatForYou action callback", 
                   user_id=callback.from_user.id,
                   callback_data=callback.data)
        
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        action = callback.data.replace("ai_", "")
        
        logger.info("🔄 Processing ChatForYou action", 
                   action=action,
                   bot_id=self.bot_id)
        
        if action == "set_id":
            await self._set_assistant_id(callback, state)
        elif action == "test":
            await self._test_ai_assistant(callback, state)
        elif action == "change_type":
            await self._change_agent_type(callback)
        elif action == "confirm_change_type":
            await self._confirm_change_agent_type(callback)
        elif action == "delete":
            await self._delete_chatforyou_agent(callback)

    async def show_settings(self, callback: CallbackQuery, has_ai_agent: bool):
        """Показ настроек ChatForYou агента"""
        logger.info("📋 Displaying ChatForYou settings", 
                   bot_id=self.bot_id,
                   has_ai_agent=has_ai_agent)
        
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
        
        keyboard = AIKeyboards.chatforyou_settings_menu(is_configured, platform)
        
        # Добавляем кнопку смены типа агента
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="🔄 Сменить тип агента", callback_data="ai_change_type")
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)

    # ===== НАСТРОЙКА API ТОКЕНА =====
    
    async def _set_assistant_id(self, callback: CallbackQuery, state: FSMContext):
        """Настройка ID ассистента (ChatForYou)"""
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

    async def handle_api_token_input(self, message: Message, state: FSMContext, is_owner_check):
        """Обработка ввода API токена"""
        logger.info("📝 ChatForYou API token input", 
                   user_id=message.from_user.id,
                   input_length=len(message.text),
                   bot_id=self.bot_id)
        
        if not is_owner_check(message.from_user.id):
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
                await self._save_protalk_configuration(api_token, platform, message, state)
                
        except Exception as e:
            logger.error("💥 Failed to process API token", 
                        error=str(e),
                        error_type=type(e).__name__)
            await message.answer("❌ Ошибка при обработке токена")
            await state.clear()

    async def _save_protalk_configuration(self, api_token: str, platform: str, message: Message, state: FSMContext):
        """Сохранение конфигурации ProTalk"""
        logger.info("💾 Saving ProTalk configuration")
        
        try:
            ai_settings = self.ai_assistant_settings.copy()
            ai_settings.update({
                'agent_type': 'chatforyou',
                'detected_platform': platform,
                'platform_detected_at': datetime.now().isoformat(),
                'platform_validation': 'completed'
            })
            
            logger.info("💾 Saving ProTalk configuration to database")
            await self.db.save_external_ai_config(
                bot_id=self.bot_id,
                api_token=api_token,
                bot_id_value=None,
                platform=platform,
                settings=ai_settings
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
            logger.error("💥 Failed to save ProTalk configuration", error=str(e))
            await message.answer("❌ Ошибка при сохранении конфигурации ProTalk")
            await state.clear()

    # ===== НАСТРОЙКА BOT ID ДЛЯ CHATFORYOU =====
    
    async def handle_bot_id_input(self, message: Message, state: FSMContext, is_owner_check):
        """Обработка ввода ID сотрудника для ChatForYou"""
        logger.info("📝 ChatForYou bot ID input", 
                   user_id=message.from_user.id,
                   input_text=message.text,
                   bot_id=self.bot_id)
        
        if not is_owner_check(message.from_user.id):
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
            
            # Сохраняем конфигурацию ChatForYou
            await self._save_chatforyou_configuration(api_token, platform, bot_id_value, message, state)
            
        except Exception as e:
            logger.error("💥 Failed to validate ChatForYou configuration", 
                        error=str(e),
                        error_type=type(e).__name__)
            await message.answer("❌ Ошибка при проверке конфигурации ChatForYou")
            await state.clear()

    async def _save_chatforyou_configuration(self, api_token: str, platform: str, bot_id_value: int, message: Message, state: FSMContext):
        """Сохранение конфигурации ChatForYou"""
        logger.info("💾 Saving ChatForYou configuration")
        
        try:
            ai_settings = self.ai_assistant_settings.copy()
            ai_settings.update({
                'agent_type': 'chatforyou',
                'detected_platform': platform,
                'chatforyou_bot_id': bot_id_value,
                'platform_detected_at': datetime.now().isoformat(),
                'bot_id_verified': True,
                'bot_id_verified_at': datetime.now().isoformat(),
                'platform_validation': 'completed',
                'validation_method': 'real_api_test'
            })
            
            await self.db.save_external_ai_config(
                bot_id=self.bot_id,
                api_token=api_token,
                bot_id_value=str(bot_id_value),
                platform=platform,
                settings=ai_settings
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
            logger.error("💥 Failed to save ChatForYou configuration", error=str(e))
            await message.answer("❌ Ошибка при сохранении конфигурации ChatForYou")
            await state.clear()

    # ===== ТЕСТИРОВАНИЕ =====
    
    async def _test_ai_assistant(self, callback: CallbackQuery, state: FSMContext):
        """Тестирование ИИ ассистента (ChatForYou)"""
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
            [InlineKeyboardButton(text="🚪 Завершить диалог", callback_data="ai_exit_conversation")],
            [InlineKeyboardButton(text="🔧 К настройкам", callback_data="admin_ai")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)

    # ===== ДИАЛОГ С CHATFORYOU =====
    
    async def handle_chatforyou_conversation(self, message: Message, data: dict) -> str:
        """Обработка диалога с ChatForYou"""
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

    # ===== СМЕНА ТИПА АГЕНТА =====
    
    async def _change_agent_type(self, callback: CallbackQuery):
        """Смена типа агента"""
        logger.info("🔄 Agent type change request", 
                   bot_id=self.bot_id,
                   current_type=self.ai_assistant_settings.get('agent_type', 'none'))
        
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

    async def _confirm_change_agent_type(self, callback: CallbackQuery):
        """Подтверждение смены типа агента с полной очисткой конфигурации"""
        logger.info("🔄 Confirming agent type change", 
                   bot_id=self.bot_id,
                   current_type=self.ai_assistant_settings.get('agent_type', 'none'),
                   user_id=callback.from_user.id)
        
        try:
            # 1. Показываем прогресс
            await callback.message.edit_text("🔄 Очищаем конфигурацию агента...")
            
            # 2. Полная очистка конфигурации в БД
            logger.info("🗑️ Clearing AI configuration in database")
            await self.db.clear_ai_configuration(self.bot_id)
            
            # 3. Очищаем кеш бота для гарантии
            logger.info("🧹 Clearing bot cache")
            await self.db.expire_bot_cache(self.bot_id)
            
            # 4. Очищаем локальные настройки
            logger.info("🧹 Clearing local settings")
            self.ai_assistant_id = None
            self.ai_assistant_settings = {'agent_type': 'none'}
            
            # 5. Безопасное обновление других компонентов
            logger.info("🔄 Updating other components")
            try:
                await self._safe_update_user_bot(
                    ai_assistant_id=None,
                    ai_assistant_settings=self.ai_assistant_settings
                )
                logger.info("✅ UserBot updated after type change")
            except Exception as update_error:
                logger.error("⚠️ UserBot update failed after type change", error=str(update_error))
            
            try:
                await self._safe_update_bot_manager(
                    ai_assistant_id=None,
                    ai_assistant_settings=self.ai_assistant_settings
                )
                logger.info("✅ BotManager updated after type change")
            except Exception as update_error:
                logger.error("⚠️ BotManager update failed after type change", error=str(update_error))
            
            # 6. Возвращаемся к выбору типа агента
            logger.info("📋 Redirecting to agent type selection after cleanup")
            
            await callback.message.edit_text(
                "✅ Конфигурация очищена. Переходим к выбору типа агента...",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🤖 К выбору агента", callback_data="admin_ai")]
                ])
            )
            
            logger.info("✅ Agent type change completed successfully", 
                       bot_id=self.bot_id)
            
        except Exception as e:
            logger.error("💥 Failed to change agent type", 
                        bot_id=self.bot_id,
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            
            await callback.message.edit_text(
                "❌ Ошибка при смене типа агента. Попробуйте позже.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
                ])
            )

    # ===== УДАЛЕНИЕ АГЕНТА =====
    
    async def _delete_chatforyou_agent(self, callback: CallbackQuery):
        """Удаление ChatForYou агента"""
        logger.info("🗑️ Deleting ChatForYou agent", 
                   bot_id=self.bot_id)
        
        text = """
🗑️ <b>Удаление ИИ агента</b>

⚠️ <b>Внимание!</b> При удалении агента:
- Конфигурация будет полностью очищена
- Пользователи не смогут обращаться к ИИ
- Все настройки агента будут потеряны

Вы уверены, что хотите удалить агента?
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data="ai_confirm_delete")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_ai")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)

    async def handle_confirm_delete(self, callback: CallbackQuery, is_owner_check):
        """Подтверждение удаления ChatForYou агента"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            logger.info("🗑️ Confirming ChatForYou agent deletion", 
                       bot_id=self.bot_id)
            
            await callback.message.edit_text("🔄 Удаляем агента...")
            
            # Очищаем конфигурацию
            await self.db.clear_ai_configuration(self.bot_id)
            await self.db.expire_bot_cache(self.bot_id)
            
            # Очищаем локальные настройки
            self.ai_assistant_id = None
            self.ai_assistant_settings = {'agent_type': 'none'}
            
            # Обновляем другие компоненты
            await self._safe_update_user_bot(
                ai_assistant_id=None,
                ai_assistant_settings=self.ai_assistant_settings
            )
            await self._safe_update_bot_manager(
                ai_assistant_id=None,
                ai_assistant_settings=self.ai_assistant_settings
            )
            
            await callback.message.edit_text(
                "✅ ИИ агент удален успешно.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🤖 Настроить заново", callback_data="admin_ai")]
                ])
            )
            
            logger.info("✅ ChatForYou agent deleted successfully")
            
        except Exception as e:
            logger.error("💥 Error deleting ChatForYou agent", 
                        error=str(e),
                        error_type=type(e).__name__)
            await callback.answer("Ошибка при удалении агента", show_alert=True)

    # ===== ОБРАБОТЧИКИ ДЛЯ СОВМЕСТИМОСТИ =====
    
    async def handle_ai_assistant_id_input(self, message: Message, state: FSMContext, is_owner_check):
        """Обработчик для совместимости"""
        logger.info("📝 AI assistant ID input (compatibility)", 
                   user_id=message.from_user.id)
        await self.handle_api_token_input(message, state, is_owner_check)

    async def handle_ai_daily_limit_input(self, message: Message, state: FSMContext, is_owner_check):
        """Обработка ввода дневного лимита"""
        logger.info("📝 Daily limit input", 
                   user_id=message.from_user.id,
                   input_text=message.text)
        
        if not is_owner_check(message.from_user.id):
            logger.warning("🚫 Unauthorized daily limit input", user_id=message.from_user.id)
            return
        
        # Пока не используется для ChatForYou, но может быть добавлено в будущем
        logger.info("ℹ️ Daily limit feature not implemented for ChatForYou agent types")
        pass

    # ===== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ =====
    
    async def _cancel_and_show_ai(self, message: Message, state: FSMContext):
        """Отмена и показ настроек ИИ"""
        logger.info("❌ Cancelling ChatForYou operation", 
                   user_id=message.from_user.id,
                   bot_id=self.bot_id)
        
        await state.clear()
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
        ])
        await message.answer("Настройка отменена", reply_markup=keyboard)
    
    async def _safe_update_user_bot(self, **kwargs):
        """Безопасное обновление настроек UserBot"""
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
        """Безопасное обновление через bot_manager"""
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
