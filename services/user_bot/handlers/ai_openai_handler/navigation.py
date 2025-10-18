"""
Navigation Mixin для OpenAI Handler
Содержит логику навигации между меню и критичные обработчики переходов
"""

import structlog
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

logger = structlog.get_logger()


class NavigationMixin:
    """Миксин для навигации между меню"""

    # ===== КРИТИЧНЫЕ ОБРАБОТЧИКИ НАВИГАЦИИ =====
    
    async def handle_admin_panel(self, callback: CallbackQuery, state: FSMContext):
        """✅ НОВЫЙ: Возврат в главную админ панель"""
        logger.info("🏠 Returning to admin panel", 
                   user_id=callback.from_user.id,
                   bot_id=self.bot_id)
        
        await state.clear()
        
        text = f"""
🔧 <b>Админ панель бота @{self.bot_username}</b>

Управление вашим ботом:
"""
        
        # Импортируем клавиатуру админ панели
        try:
            from ..keyboards import AdminKeyboards
            keyboard = AdminKeyboards.main_menu()
        except Exception as e:
            logger.error("💥 Error importing AdminKeyboards", error=str(e))
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🤖 Настройки ИИ", callback_data="admin_ai")],
                [InlineKeyboardButton(text="⚙️ Настройки бота", callback_data="admin_settings")],
                [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")]
            ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def handle_exit_conversation(self, callback: CallbackQuery, state: FSMContext):
        """✅ НОВЫЙ: Завершение диалога с ИИ - переход в главное меню"""
        logger.info("🚪 Exiting AI conversation", 
                   user_id=callback.from_user.id,
                   bot_id=self.bot_id)
        
        await state.clear()
        
        # ✅ ИСПРАВЛЕНО: Возвращаемся в главное меню вместо настроек ИИ
        await self.handle_admin_ai(callback, state)
    
    async def handle_admin_ai(self, callback: CallbackQuery, state: FSMContext):
        """✅ НОВЫЙ: Переход к настройкам ИИ"""
        logger.info("🤖 Going to AI settings", 
                   user_id=callback.from_user.id,
                   bot_id=self.bot_id)
        
        await state.clear()
        
        # Проверяем наличие агента и показываем соответствующий интерфейс
        await self._sync_with_db_state()
        
        agent_type = self.ai_assistant_settings.get('agent_type', 'none')
        has_agent = bool(self.ai_assistant_id) and agent_type == 'openai'
        
        await self.show_settings(callback, has_ai_agent=has_agent)
    
    async def handle_admin_main(self, callback: CallbackQuery, state: FSMContext):
        """✅ НОВЫЙ: Возврат в главное меню"""
        logger.info("🏠 Returning to main menu", 
                   user_id=callback.from_user.id,
                   bot_id=self.bot_id)
        
        await state.clear()
        
        text = f"""
🤖 <b>Бот @{self.bot_username}</b>

Главное меню управления ботом.
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔧 Админ панель", callback_data="admin_panel")],
            [InlineKeyboardButton(text="🤖 Настройки ИИ", callback_data="admin_ai")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
