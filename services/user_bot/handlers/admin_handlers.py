"""
Обработчики команд администратора
"""

import structlog
from aiogram import Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardRemove

from config import Emoji
from ..keyboards import AdminKeyboards
from ..formatters import MessageFormatter

logger = structlog.get_logger()


def register_admin_handlers(dp: Dispatcher, **kwargs):
    """Регистрация обработчиков администратора"""
    
    db = kwargs['db']
    bot_config = kwargs['bot_config']  # ИЗМЕНЕНО: получаем полную конфигурацию
    funnel_manager = kwargs['funnel_manager']
    user_bot = kwargs.get('user_bot')  # Получаем ссылку на UserBot
    
    try:
        # Создаем экземпляр обработчика с полной конфигурацией
        handler = AdminHandler(db, bot_config, funnel_manager, user_bot)
        
        # Регистрируем команды
        dp.message.register(handler.cmd_start, CommandStart())
        
        # Регистрируем callback-обработчики
        dp.callback_query.register(handler.cb_admin_main, F.data == "admin_main")
        dp.callback_query.register(handler.cb_admin_settings, F.data == "admin_settings")
        dp.callback_query.register(handler.cb_admin_funnel, F.data == "admin_funnel")
        dp.callback_query.register(handler.cb_admin_stats, F.data == "admin_stats")
        
        # Debug handler
        dp.message.register(handler.debug_owner_message, F.text == "test")
        
        logger.info("Admin handlers registered successfully", 
                   bot_id=bot_config['bot_id'], 
                   owner_id=bot_config['owner_user_id'])
        
    except Exception as e:
        logger.error("Failed to register admin handlers", 
                    bot_id=kwargs.get('bot_config', {}).get('bot_id', 'unknown'),
                    error=str(e), exc_info=True)
        raise


class AdminHandler:
    """Класс обработчиков администратора"""
    
    def __init__(self, db, bot_config: dict, funnel_manager, user_bot):
        self.db = db
        self.bot_config = bot_config
        self.bot_id = bot_config['bot_id']
        self.owner_user_id = bot_config['owner_user_id']
        self.bot_username = bot_config['bot_username']
        self.funnel_manager = funnel_manager
        self.formatter = MessageFormatter()
        self.user_bot = user_bot  # Сохраняем ссылку на UserBot
        
        # Получаем все настройки из конфигурации
        self.welcome_message = bot_config.get('welcome_message')
        self.welcome_button_text = bot_config.get('welcome_button_text')
        self.confirmation_message = bot_config.get('confirmation_message')
        self.goodbye_message = bot_config.get('goodbye_message')
        self.goodbye_button_text = bot_config.get('goodbye_button_text')
        self.goodbye_button_url = bot_config.get('goodbye_button_url')
        self.ai_assistant_id = bot_config.get('ai_assistant_id')
        self.ai_assistant_enabled = bot_config.get('ai_assistant_enabled', False)
        self.ai_assistant_settings = bot_config.get('ai_assistant_settings', {})
        self.stats = bot_config.get('stats', {})
    
    # УДАЛЯЕМ метод _load_config() - он больше не нужен
    
    def _is_owner(self, user_id: int) -> bool:
        """Проверка является ли пользователь владельцем"""
        is_owner = user_id == self.owner_user_id
        logger.debug("Owner check", 
                    bot_id=self.bot_id,
                    user_id=user_id, 
                    owner_user_id=self.owner_user_id, 
                    is_owner=is_owner)
        return is_owner
    
    def _get_admin_welcome_text(self) -> str:
        """Генерация приветственного текста админки"""
        # Используем self.stats напрямую из переданной конфигурации
        total_sent = (self.stats.get('welcome_sent', 0) + 
                     self.stats.get('goodbye_sent', 0) + 
                     self.stats.get('confirmation_sent', 0))
        
        # Проверяем настройки из self, а не из bot_config
        has_welcome = bool(self.welcome_message)
        has_welcome_button = bool(self.welcome_button_text)
        has_confirmation = bool(self.confirmation_message)
        has_goodbye = bool(self.goodbye_message)
        has_goodbye_button = bool(self.goodbye_button_text and self.goodbye_button_url)
        
        # Проверяем ИИ
        ai_enabled = self.ai_assistant_enabled
        ai_configured = bool(self.ai_assistant_id)
        
        return f"""
{Emoji.ROBOT} <b>Админ-панель @{self.bot_username or 'bot'}</b>

{Emoji.SUCCESS} <b>Статус:</b> Активен
{Emoji.MESSAGE} <b>Сообщений отправлено:</b> {total_sent}
{Emoji.BUTTON} <b>Кнопок нажато:</b> {self.stats.get('button_clicks', 0)}
{Emoji.FUNNEL} <b>Воронок запущено:</b> {self.stats.get('funnel_starts', 0)}

{Emoji.INFO} <b>Настройки:</b>
- Приветствие: {'✅' if has_welcome else '❌'}
- Кнопка приветствия: {'✅' if has_welcome_button else '❌'}
- Подтверждение: {'✅' if has_confirmation else '❌'}
- Прощание: {'✅' if has_goodbye else '❌'}
- Кнопка прощания: {'✅' if has_goodbye_button else '❌'}

🤖 <b>ИИ Агент:</b>
- Статус: {'✅ Включен' if ai_enabled else '❌ Выключен'}
- Настройка: {'✅ Готов' if ai_configured else '❌ Не настроен'}

Выберите раздел для настройки:
"""
    
    async def cmd_start(self, message: Message, state: FSMContext):
        """Команда /start - админ панель для владельца"""
        try:
            await state.clear()
            
            user_id = message.from_user.id
            
            if not self._is_owner(user_id):
                logger.debug("Non-owner user accessed /start", 
                            bot_id=self.bot_id, 
                            user_id=user_id,
                            username=message.from_user.username)
                
                await message.answer(
                    f"👋 Это служебный бот канала.\n"
                    f"Для получения информации используйте основной канал.",
                    reply_markup=ReplyKeyboardRemove()
                )
                return
            
            # Owner access - show admin panel
            await message.answer(
                self._get_admin_welcome_text(),
                reply_markup=AdminKeyboards.main_menu()
            )
            
            logger.info("Owner accessed admin panel", 
                       bot_id=self.bot_id, 
                       owner_user_id=user_id,
                       bot_username=self.bot_username)
                       
        except Exception as e:
            logger.error("Error in cmd_start", bot_id=self.bot_id, error=str(e), exc_info=True)
            await message.answer(
                "❌ Ошибка при загрузке админ панели. Проверьте логи.",
                reply_markup=ReplyKeyboardRemove()
            )
    
    async def cb_admin_main(self, callback: CallbackQuery, state: FSMContext):
        """Главное меню админки"""
        await callback.answer()
        await state.clear()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        await callback.message.edit_text(
            self._get_admin_welcome_text(),
            reply_markup=AdminKeyboards.main_menu()
        )
    
    async def cb_admin_settings(self, callback: CallbackQuery):
        """Настройки сообщений"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        welcome_status = "✅ Настроено" if self.welcome_message else "❌ Не настроено"
        welcome_button_status = "✅ Настроено" if self.welcome_button_text else "❌ Не настроено"
        confirmation_status = "✅ Настроено" if self.confirmation_message else "❌ Не настроено"
        goodbye_status = "✅ Настроено" if self.goodbye_message else "❌ Не настроено"
        goodbye_button_status = "✅ Настроено" if self.goodbye_button_text else "❌ Не настроено"
        
        text = f"""
{Emoji.SETTINGS} <b>Настройки @{self.bot_username or 'bot'}</b>

{Emoji.INFO} <b>Приветствие:</b>
   Сообщение: {welcome_status}
   Кнопка: {welcome_button_status}
   Подтверждение: {confirmation_status}

{Emoji.INFO} <b>Прощание:</b>
   Сообщение: {goodbye_status}
   Кнопка: {goodbye_button_status}

{Emoji.ROCKET} <b>Как работает:</b>
1. Новый участник → Приветствие + кнопка
2. Нажатие кнопки → Подтверждение + запуск воронки 
3. Выход участника → Прощание + кнопка с ссылкой
"""
        
        await callback.message.edit_text(
            text,
            reply_markup=AdminKeyboards.settings_menu()
        )
    
    async def cb_admin_funnel(self, callback: CallbackQuery):
        """Воронка продаж"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        # Перенаправляем в обработчик воронки
        from .funnel_handlers import show_funnel_main_menu
        await show_funnel_main_menu(callback, self.bot_id, self.bot_username, self.funnel_manager)
    
    async def cb_admin_stats(self, callback: CallbackQuery):
        """Статистика бота"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        await self._show_bot_stats(callback)
    
    async def _show_bot_stats(self, callback: CallbackQuery):
        """Показать статистику бота"""
        try:
            # Получаем статистику из БД
            stats = await self.db.get_bot_statistics(self.bot_id)
            
            text = f"""
{Emoji.CHART} <b>Статистика @{self.bot_username or 'bot'}</b>

{Emoji.ROBOT} <b>Статус бота:</b>
   Активен

{Emoji.USERS} <b>Сообщения:</b>
   Приветствий: {stats.get('welcome_sent', 0)}
   Подтверждений: {stats.get('confirmation_sent', 0)}
   Прощаний: {stats.get('goodbye_sent', 0)}
   
{Emoji.BUTTON} <b>Кнопки:</b>
   Отправлено приветственных: {stats.get('welcome_buttons_sent', 0)}
   Отправлено прощальных: {stats.get('goodbye_buttons_sent', 0)}
   Нажатий: {stats.get('button_clicks', 0)}
   
{Emoji.FUNNEL} <b>Воронки:</b>
   Запущено: {stats.get('funnel_starts', 0)}
   
{Emoji.FIRE} <b>Активность:</b>
   Заявок на вступление: {stats.get('join_requests_processed', 0)}
   Админских добавлений: {stats.get('admin_adds_processed', 0)}

{Emoji.INFO} <i>Подробная аналитика в разработке</i>
"""
            
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔄 Обновить",
                        callback_data="admin_stats"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=f"{Emoji.BACK} Главное меню",
                        callback_data="admin_main"
                    )
                ]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error("Failed to show bot stats", bot_id=self.bot_id, error=str(e))
            await callback.answer("Ошибка при загрузке статистики", show_alert=True)
    
    async def debug_owner_message(self, message: Message):
        """Debug метод для проверки владельца"""
        user_id = message.from_user.id
        is_owner = self._is_owner(user_id)
        
        await message.answer(
            f"🔍 <b>Debug Info:</b>\n"
            f"User ID: {user_id}\n"
            f"Owner ID: {self.owner_user_id}\n"
            f"Is Owner: {is_owner}\n"
            f"Bot ID: {self.bot_id}\n"
            f"Bot Username: {self.bot_username}"
        )
