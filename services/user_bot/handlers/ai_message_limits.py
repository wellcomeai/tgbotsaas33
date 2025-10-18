"""
Менеджер лимитов сообщений для ИИ агентов
Управляет дневными лимитами сообщений пользователей
Применяется ко всем типам агентов (OpenAI, ChatForYou, ProTalk)
"""

import structlog
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from ..states import AISettingsStates

logger = structlog.get_logger()


class MessageLimitManager:
    """Менеджер дневных лимитов сообщений"""
    
    def __init__(self, db, bot_config: dict):
        self.db = db
        self.bot_config = bot_config
        self.bot_id = bot_config['bot_id']
        self.owner_user_id = bot_config['owner_user_id']
        self.bot_username = bot_config['bot_username']
        
        # Хранимые ссылки на настройки агента (будут обновляться)
        self._ai_assistant_settings = bot_config.get('ai_assistant_settings', {})
        
        logger.info("📊 MessageLimitManager initialized", 
                   bot_id=self.bot_id,
                   owner_user_id=self.owner_user_id)

    # ===== СВОЙСТВА ДЛЯ ДОСТУПА К АКТУАЛЬНЫМ ДАННЫМ =====
    
    @property 
    def ai_assistant_settings(self):
        """Получение актуальных настроек агента"""
        return self._ai_assistant_settings
    
    @ai_assistant_settings.setter
    def ai_assistant_settings(self, value):
        """Установка настроек агента"""
        self._ai_assistant_settings = value

    # ===== ОСНОВНЫЕ МЕТОДЫ ПРОВЕРКИ ЛИМИТОВ =====
    
    async def check_daily_message_limit(self, user_id: int) -> tuple[bool, str]:
        """Проверка дневного лимита сообщений"""
        try:
            logger.info("📊 Checking daily message limit", 
                       user_id=user_id,
                       bot_id=self.bot_id)
            
            can_send, used_today, daily_limit = await self.db.check_daily_message_limit(
                self.bot_id, user_id
            )
            
            logger.info("📊 Daily message limit check result", 
                       user_id=user_id,
                       can_send=can_send,
                       used_today=used_today,
                       daily_limit=daily_limit)
            
            if not can_send:
                error_message = f"""
📊 <b>Дневной лимит сообщений исчерпан</b>

Использовано: {used_today} / {daily_limit} сообщений

Лимит обновится в 00:00 МСК.
Попробуйте снова завтра!

💡 <i>Лимит установлен администратором бота</i>
"""
                return False, error_message
            
            return True, ""
            
        except Exception as e:
            logger.error("💥 Error checking daily message limit", 
                        user_id=user_id,
                        error=str(e),
                        error_type=type(e).__name__)
            return True, ""  # В случае ошибки разрешаем отправку

    async def increment_daily_message_usage(self, user_id: int) -> bool:
        """Увеличение счетчика использованных сообщений"""
        try:
            logger.info("📈 Incrementing daily message usage", 
                       user_id=user_id,
                       bot_id=self.bot_id)
            
            success = await self.db.increment_daily_message_usage(self.bot_id, user_id)
            
            if success:
                logger.info("✅ Daily message usage incremented successfully")
            else:
                logger.error("❌ Failed to increment daily message usage")
            
            return success
            
        except Exception as e:
            logger.error("💥 Error incrementing daily message usage", 
                        user_id=user_id,
                        error=str(e),
                        error_type=type(e).__name__)
            return False

    # ===== УПРАВЛЕНИЕ НАСТРОЙКАМИ ЛИМИТОВ =====
    
    async def handle_message_limit_settings(self, callback: CallbackQuery):
        """Настройка лимита сообщений"""
        await callback.answer()
        
        if callback.from_user.id != self.owner_user_id:
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            logger.info("📊 Showing message limit settings", 
                       user_id=callback.from_user.id,
                       bot_id=self.bot_id)
            
            # Получаем текущий лимит
            current_limit = await self.db.get_daily_message_limit(self.bot_id)
            
            limit_text = "не установлен" if current_limit == 0 else f"{current_limit} сообщений"
            
            text = f"""
📊 <b>Лимит сообщений в день</b>

<b>Текущий лимит:</b> {limit_text}

Этот лимит применяется ко всем пользователям бота. После достижения лимита пользователь не сможет отправлять сообщения ИИ агенту до 00:00 МСК следующего дня.

<b>Как это работает:</b>
- Считаются только сообщения пользователей к ИИ
- Лимит сбрасывается каждый день в 00:00 МСК
- При достижении лимита показывается уведомление

<b>Что делать:</b>
"""
            
            keyboard_buttons = []
            
            if current_limit > 0:
                keyboard_buttons.extend([
                    [InlineKeyboardButton(text="📝 Изменить лимит", callback_data="ai_set_message_limit")],
                    [InlineKeyboardButton(text="🚫 Отключить лимит", callback_data="ai_disable_message_limit")]
                ])
            else:
                keyboard_buttons.append([InlineKeyboardButton(text="✅ Установить лимит", callback_data="ai_set_message_limit")])
            
            keyboard_buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_ai")])
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
            logger.info("✅ Message limit settings displayed", 
                       current_limit=current_limit)
            
        except Exception as e:
            logger.error("💥 Error showing message limit settings", 
                        error=str(e),
                        error_type=type(e).__name__)
            await callback.answer("Ошибка при загрузке настроек", show_alert=True)

    async def handle_set_message_limit(self, callback: CallbackQuery, state: FSMContext):
        """Установка лимита сообщений"""
        await callback.answer()
        
        if callback.from_user.id != self.owner_user_id:
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        logger.info("📝 Setting message limit", 
                   user_id=callback.from_user.id,
                   bot_id=self.bot_id)
        
        await state.set_state(AISettingsStates.waiting_for_message_limit)
        
        text = """
📊 <b>Установка лимита сообщений</b>

Введите количество сообщений, которое пользователь может отправить ИИ агенту в день.

<b>Примеры:</b>
- 10 - для небольшого лимита
- 50 - для среднего использования  
- 100 - для активного использования
- 0 - отключить лимит

<b>Введите число:</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="ai_message_limit")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)

    async def handle_disable_message_limit(self, callback: CallbackQuery):
        """Отключение лимита сообщений"""
        await callback.answer()
        
        if callback.from_user.id != self.owner_user_id:
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            logger.info("🚫 Disabling message limit", 
                       user_id=callback.from_user.id,
                       bot_id=self.bot_id)
            
            success = await self.db.set_daily_message_limit(self.bot_id, 0)
            
            if success:
                # ✅ НОВОЕ: Очищаем логи использования при отключении лимитов
                from database.managers.message_manager import MessageManager
                clear_success = await MessageManager.clear_bot_usage_logs(self.bot_id)
                
                if clear_success:
                    await callback.answer("✅ Лимит отключен, счетчики сброшены")
                    logger.info("✅ Message limit disabled and logs cleared")
                else:
                    await callback.answer("✅ Лимит отключен")
                    logger.warning("⚠️ Message limit disabled but logs not cleared")
                
                # Возвращаемся к настройкам лимита
                await self.handle_message_limit_settings(callback)
            else:
                await callback.answer("❌ Ошибка при отключении лимита", show_alert=True)
                logger.error("❌ Failed to disable message limit")
                
        except Exception as e:
            logger.error("💥 Error disabling message limit", 
                        error=str(e),
                        error_type=type(e).__name__)
            await callback.answer("❌ Ошибка при отключении лимита", show_alert=True)

    async def handle_message_limit_input(self, message: Message, state: FSMContext, is_owner_check):
        """Обработка ввода лимита сообщений"""
        if not is_owner_check(message.from_user.id):
            return
        
        logger.info("📝 Processing message limit input", 
                   user_id=message.from_user.id,
                   input_text=message.text,
                   bot_id=self.bot_id)
        
        if message.text == "/cancel":
            await self._cancel_and_show_ai(message, state)
            return
        
        try:
            limit = int(message.text.strip())
            
            if limit < 0:
                await message.answer("❌ Лимит не может быть отрицательным. Введите число от 0:")
                return
            
            if limit > 10000:
                await message.answer("❌ Слишком большой лимит (максимум 10000). Введите меньшее число:")
                return
            
            logger.info("✅ Valid message limit input", 
                       limit=limit,
                       user_id=message.from_user.id)
            
            # Сохраняем лимит
            success = await self.db.set_daily_message_limit(self.bot_id, limit)
            
            if success:
                if limit == 0:
                    result_text = "✅ Лимит сообщений отключен, счетчики сброшены"
                    
                    # ✅ НОВОЕ: Очищаем логи при установке лимита = 0
                    from database.managers.message_manager import MessageManager
                    await MessageManager.clear_bot_usage_logs(self.bot_id)
                else:
                    result_text = f"✅ Лимит установлен: {limit} сообщений в день"
                
                # ✅ ИЗМЕНЕНО: Обновленные кнопки возврата
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📊 К настройкам лимита", callback_data="ai_message_limit")],
                    [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
                ])
                
                await message.answer(result_text, reply_markup=keyboard)
                
                # Обновляем локальные настройки
                agent_type = self.ai_assistant_settings.get('agent_type', 'none')
                if agent_type == 'openai':
                    if 'openai_settings' not in self.ai_assistant_settings:
                        self.ai_assistant_settings['openai_settings'] = {}
                    self.ai_assistant_settings['openai_settings']['daily_message_limit'] = limit
                elif agent_type in ['chatforyou', 'protalk']:
                    if 'external_settings' not in self.ai_assistant_settings:
                        self.ai_assistant_settings['external_settings'] = {}
                    self.ai_assistant_settings['external_settings']['daily_message_limit'] = limit
                
                logger.info("✅ Message limit set successfully", 
                           limit=limit,
                           bot_id=self.bot_id)
            else:
                await message.answer("❌ Ошибка при сохранении лимита. Попробуйте еще раз.")
                logger.error("❌ Failed to save message limit")
            
            await state.clear()
            
        except ValueError:
            await message.answer("❌ Введите корректное число. Например: 50")
            logger.warning("❌ Invalid number format for message limit", input_text=message.text)
        except Exception as e:
            logger.error("💥 Error handling message limit input", 
                        error=str(e),
                        error_type=type(e).__name__)
            await message.answer("❌ Произошла ошибка. Попробуйте еще раз.")
            await state.clear()

    # ===== СТАТИСТИКА И МОНИТОРИНГ =====
    
    async def get_message_usage_stats(self, user_id: int = None) -> dict:
        """Получение статистики использования сообщений"""
        try:
            logger.info("📈 Getting message usage statistics", 
                       user_id=user_id,
                       bot_id=self.bot_id)
            
            if user_id:
                # Статистика для конкретного пользователя
                stats = await self.db.get_user_daily_message_stats(self.bot_id, user_id)
            else:
                # Общая статистика по боту
                stats = await self.db.get_bot_daily_message_stats(self.bot_id)
            
            logger.info("✅ Message usage statistics retrieved", 
                       stats_keys=list(stats.keys()) if stats else None)
            
            return stats
            
        except Exception as e:
            logger.error("💥 Error getting message usage statistics", 
                        error=str(e),
                        error_type=type(e).__name__)
            return {}

    async def reset_daily_limits(self) -> bool:
        """Сброс дневных лимитов (вызывается в 00:00 МСК)"""
        try:
            logger.info("🔄 Resetting daily message limits", 
                       bot_id=self.bot_id)
            
            success = await self.db.reset_daily_message_limits(self.bot_id)
            
            if success:
                logger.info("✅ Daily message limits reset successfully")
            else:
                logger.error("❌ Failed to reset daily message limits")
            
            return success
            
        except Exception as e:
            logger.error("💥 Error resetting daily message limits", 
                        error=str(e),
                        error_type=type(e).__name__)
            return False

    # ===== УВЕДОМЛЕНИЯ И ПРЕДУПРЕЖДЕНИЯ =====
    
    async def check_limit_warnings(self, user_id: int) -> bool:
        """Проверка необходимости отправки предупреждений о приближении к лимиту"""
        try:
            logger.info("⚠️ Checking for limit warnings", 
                       user_id=user_id,
                       bot_id=self.bot_id)
            
            # Получаем текущее использование
            can_send, used_today, daily_limit = await self.db.check_daily_message_limit(
                self.bot_id, user_id
            )
            
            if daily_limit > 0:
                usage_percentage = (used_today / daily_limit) * 100
                
                # Предупреждаем при достижении 80% лимита
                if usage_percentage >= 80 and usage_percentage < 100:
                    logger.info("⚠️ User approaching message limit", 
                               user_id=user_id,
                               usage_percentage=usage_percentage)
                    
                    # Здесь можно добавить отправку уведомления пользователю
                    # Пока просто логируем
                    return True
            
            return False
            
        except Exception as e:
            logger.error("💥 Error checking limit warnings", 
                        user_id=user_id,
                        error=str(e),
                        error_type=type(e).__name__)
            return False

    async def send_limit_warning(self, user_id: int, message: Message) -> bool:
        """Отправка предупреждения о приближении к лимиту"""
        try:
            logger.info("📢 Sending limit warning", 
                       user_id=user_id,
                       bot_id=self.bot_id)
            
            # Получаем текущую статистику
            can_send, used_today, daily_limit = await self.db.check_daily_message_limit(
                self.bot_id, user_id
            )
            
            if daily_limit > 0:
                remaining = daily_limit - used_today
                
                warning_text = f"""
⚠️ <b>Предупреждение о лимите сообщений</b>

Использовано: {used_today} / {daily_limit} сообщений
Осталось: {remaining} сообщений

💡 <i>Лимит обновится в 00:00 МСК</i>
"""
                
                await message.answer(warning_text)
                
                logger.info("✅ Limit warning sent successfully")
                return True
            
            return False
            
        except Exception as e:
            logger.error("💥 Error sending limit warning", 
                        user_id=user_id,
                        error=str(e),
                        error_type=type(e).__name__)
            return False

    # ===== АДМИНИСТРАТИВНЫЕ ФУНКЦИИ =====
    
    async def override_user_limit(self, user_id: int, new_limit: int) -> bool:
        """Переопределение лимита для конкретного пользователя"""
        try:
            logger.info("🔧 Overriding user message limit", 
                       user_id=user_id,
                       new_limit=new_limit,
                       bot_id=self.bot_id)
            
            success = await self.db.set_user_daily_message_limit(self.bot_id, user_id, new_limit)
            
            if success:
                logger.info("✅ User message limit overridden successfully")
            else:
                logger.error("❌ Failed to override user message limit")
            
            return success
            
        except Exception as e:
            logger.error("💥 Error overriding user message limit", 
                        user_id=user_id,
                        error=str(e),
                        error_type=type(e).__name__)
            return False

    async def get_top_users_by_usage(self, limit: int = 10) -> list:
        """Получение топ пользователей по использованию сообщений"""
        try:
            logger.info("📊 Getting top users by message usage", 
                       limit=limit,
                       bot_id=self.bot_id)
            
            top_users = await self.db.get_top_users_by_message_usage(self.bot_id, limit)
            
            logger.info("✅ Top users by usage retrieved", 
                       users_count=len(top_users) if top_users else 0)
            
            return top_users
            
        except Exception as e:
            logger.error("💥 Error getting top users by usage", 
                        error=str(e),
                        error_type=type(e).__name__)
            return []

    # ===== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ =====
    
    async def _cancel_and_show_ai(self, message: Message, state: FSMContext):
        """Отмена и показ настроек ИИ"""
        logger.info("❌ Cancelling message limit operation", 
                   user_id=message.from_user.id,
                   bot_id=self.bot_id)
        
        await state.clear()
        # ✅ ИЗМЕНЕНО: Обновленный callback_data
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
        ])
        await message.answer("Настройка отменена", reply_markup=keyboard)

    def format_limit_display(self, limit: int) -> str:
        """Форматирование отображения лимита"""
        if limit == 0:
            return "не установлен"
        elif limit == 1:
            return "1 сообщение"
        elif limit < 5:
            return f"{limit} сообщения"
        else:
            return f"{limit} сообщений"

    def get_limit_recommendation(self, user_count: int) -> dict:
        """Получение рекомендаций по лимитам на основе количества пользователей"""
        if user_count <= 10:
            return {
                "recommended_limit": 100,
                "description": "Для небольшой аудитории можно установить высокий лимит"
            }
        elif user_count <= 100:
            return {
                "recommended_limit": 50,
                "description": "Для средней аудитории рекомендуется умеренный лимит"
            }
        else:
            return {
                "recommended_limit": 20,
                "description": "Для большой аудитории рекомендуется консервативный лимит"
            }

    # ===== ИНТЕГРАЦИЯ С ДРУГИМИ МОДУЛЯМИ =====
    
    async def sync_with_agent_settings(self, agent_type: str, agent_settings: dict):
        """Синхронизация настроек лимитов с настройками агента"""
        try:
            logger.info("🔄 Syncing message limits with agent settings", 
                       agent_type=agent_type,
                       bot_id=self.bot_id)
            
            # Обновляем локальные настройки
            self.ai_assistant_settings = agent_settings
            
            # Получаем лимит из настроек агента
            current_db_limit = await self.db.get_daily_message_limit(self.bot_id)
            
            settings_limit = None
            if agent_type == 'openai':
                settings_limit = agent_settings.get('openai_settings', {}).get('daily_message_limit')
            elif agent_type in ['chatforyou', 'protalk']:
                settings_limit = agent_settings.get('external_settings', {}).get('daily_message_limit')
            
            # Синхронизируем если есть различия
            if settings_limit is not None and settings_limit != current_db_limit:
                await self.db.set_daily_message_limit(self.bot_id, settings_limit)
                logger.info("✅ Message limit synced from agent settings", 
                           new_limit=settings_limit)
            
        except Exception as e:
            logger.error("💥 Error syncing message limits", 
                        error=str(e),
                        error_type=type(e).__name__)

    async def update_references(self, ai_assistant_settings):
        """Обновление ссылок на настройки агента"""
        logger.info("🔄 Updating message limit manager references", 
                   bot_id=self.bot_id)
        
        self.ai_assistant_settings = ai_assistant_settings
        
        # Проверяем соответствие лимитов в БД и настройках
        try:
            agent_type = ai_assistant_settings.get('agent_type', 'none')
            if agent_type != 'none':
                await self.sync_with_agent_settings(agent_type, ai_assistant_settings)
        except Exception as e:
            logger.error("⚠️ Failed to sync limits during reference update", error=str(e))


def register_message_limit_handlers(dp, **kwargs):
    """Регистрация обработчиков лимитов сообщений"""
    from aiogram.filters import StateFilter
    from aiogram import F
    
    message_limit_manager = MessageLimitManager(
        db=kwargs['db'],
        bot_config=kwargs['bot_config']
    )
    
    owner_user_id = kwargs['bot_config']['owner_user_id']
    
    # Админские обработчики лимитов
    dp.callback_query.register(
        message_limit_manager.handle_message_limit_settings,
        F.data == "ai_message_limit",
        F.from_user.id == owner_user_id
    )
    
    dp.callback_query.register(
        message_limit_manager.handle_set_message_limit,
        F.data == "ai_set_message_limit", 
        F.from_user.id == owner_user_id
    )
    
    dp.callback_query.register(
        message_limit_manager.handle_disable_message_limit,
        F.data == "ai_disable_message_limit",
        F.from_user.id == owner_user_id
    )
    
    from ..states import AISettingsStates
    
    is_owner_check = lambda user_id: user_id == owner_user_id
    
    dp.message.register(
        lambda msg, state: message_limit_manager.handle_message_limit_input(msg, state, is_owner_check),
        StateFilter(AISettingsStates.waiting_for_message_limit),
        F.from_user.id == owner_user_id
    )
