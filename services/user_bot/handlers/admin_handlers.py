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
        dp.callback_query.register(handler.cb_admin_tokens, F.data == "admin_tokens")  # ✅ НОВОЕ: детальная статистика токенов
        
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
        self.bot_config = bot_config  # Сохраняем для базовой информации
        self.bot_id = bot_config['bot_id']
        self.owner_user_id = bot_config['owner_user_id']
        self.bot_username = bot_config['bot_username']
        self.funnel_manager = funnel_manager
        self.formatter = MessageFormatter()
        self.user_bot = user_bot  # Сохраняем ссылку на UserBot
        
        # ✅ ИСПРАВЛЕНО: НЕ кэшируем настройки, будем получать их динамически
        # self.welcome_message = bot_config.get('welcome_message')  # УДАЛЕНО
        # self.welcome_button_text = bot_config.get('welcome_button_text')  # УДАЛЕНО
        # ... остальные настройки тоже не кэшируем
        
        # Кэшируем только статичные данные
        self.stats = bot_config.get('stats', {})
    
    async def _get_fresh_config(self) -> dict:
        """✅ НОВЫЙ: Получение свежей конфигурации из БД"""
        try:
            fresh_config = await self.db.get_bot_full_config(self.bot_id, fresh=True)
            
            if fresh_config:
                logger.debug("✅ Fresh config loaded", 
                           bot_id=self.bot_id,
                           has_welcome=bool(fresh_config.get('welcome_message')),
                           has_welcome_button=bool(fresh_config.get('welcome_button_text')))
                return fresh_config
            else:
                logger.warning("❌ Failed to load fresh config, using cached", bot_id=self.bot_id)
                return self.bot_config
                
        except Exception as e:
            logger.error("❌ Error loading fresh config", bot_id=self.bot_id, error=str(e))
            return self.bot_config
    
    def _format_number(self, number: int) -> str:
        """✅ НОВОЕ: Форматирование чисел с пробелами (22 500)"""
        return f"{number:,}".replace(",", " ")
    
    def _format_percentage(self, used: int, limit: int) -> str:
        """✅ НОВОЕ: Форматирование процента использования"""
        if limit <= 0:
            return "0%"
        percentage = (used / limit) * 100
        return f"{percentage:.1f}%"
    
    async def _get_token_stats(self) -> dict:
        """✅ НОВОЕ: Получение статистики токенов OpenAI"""
        try:
            # Получаем детальный баланс токенов
            token_balance = await self.db.get_user_token_balance(self.owner_user_id)
            
            logger.debug("💰 Token balance retrieved", 
                        user_id=self.owner_user_id,
                        total_used=token_balance.get('total_used', 0),
                        limit=token_balance.get('limit', 0),
                        bots_count=token_balance.get('bots_count', 0))
            
            return {
                'has_openai_bots': token_balance.get('bots_count', 0) > 0,
                'total_used': token_balance.get('total_used', 0),
                'input_tokens': token_balance.get('input_tokens', 0),
                'output_tokens': token_balance.get('output_tokens', 0),
                'limit': token_balance.get('limit', 500000),
                'remaining': token_balance.get('remaining', 500000),
                'percentage_used': token_balance.get('percentage_used', 0.0),
                'bots_count': token_balance.get('bots_count', 0),
                'last_usage_at': token_balance.get('last_usage_at')
            }
            
        except Exception as e:
            logger.error("💥 Failed to get token stats", 
                        user_id=self.owner_user_id,
                        error=str(e),
                        error_type=type(e).__name__)
            
            # Возвращаем пустую статистику в случае ошибки
            return {
                'has_openai_bots': False,
                'total_used': 0,
                'input_tokens': 0,
                'output_tokens': 0,
                'limit': 500000,
                'remaining': 500000,
                'percentage_used': 0.0,
                'bots_count': 0,
                'last_usage_at': None
            }
    
    async def _get_content_agent_info(self) -> tuple[str, bool]:
        """✅ НОВОЕ: Получение информации о контент-агенте"""
        has_content_agent = False
        content_agent_status = "❌ Не создан"
        
        try:
            # Проверяем наличие контент-агента через базу данных
            agent_info = await self.db.get_content_agent(self.bot_id)
            
            if agent_info and not agent_info.get('deleted_at'):
                has_content_agent = True
                agent_name = agent_info.get('agent_name', 'Контент-агент')
                
                # Проверяем настройку OpenAI ID
                if agent_info.get('openai_agent_id'):
                    content_agent_status = f"✅ {agent_name}"
                else:
                    content_agent_status = f"⚠️ {agent_name} (не настроен)"
                    
                logger.debug("📝 Content agent found", 
                           bot_id=self.bot_id,
                           agent_name=agent_name,
                           has_openai_id=bool(agent_info.get('openai_agent_id')))
            else:
                logger.debug("📝 No content agent found", bot_id=self.bot_id)
                
        except Exception as e:
            logger.warning("📝 Failed to check content agent", 
                         bot_id=self.bot_id,
                         error=str(e))
            content_agent_status = "❌ Ошибка загрузки"
        
        return content_agent_status, has_content_agent
    
    def _is_owner(self, user_id: int) -> bool:
        """Проверка является ли пользователь владельцем"""
        is_owner = user_id == self.owner_user_id
        logger.debug("Owner check", 
                    bot_id=self.bot_id,
                    user_id=user_id, 
                    owner_user_id=self.owner_user_id, 
                    is_owner=is_owner)
        return is_owner
    
    def _has_ai_agent(self, config: dict) -> bool:
        """НОВОЕ: Проверка наличия ИИ агента (упрощенная логика)"""
        has_agent = bool(config.get('ai_assistant_id'))
        logger.debug("AI agent check", 
                    bot_id=self.bot_id,
                    has_agent=has_agent,
                    ai_assistant_id_exists=bool(config.get('ai_assistant_id')))
        return has_agent
    
    def _get_ai_agent_info(self, config: dict) -> tuple[str, str]:
        """НОВОЕ: Получение информации об ИИ агенте"""
        if not self._has_ai_agent(config):
            return "❌ Не создан", "none"
        
        ai_settings = config.get('ai_assistant_settings', {})
        agent_type = ai_settings.get('agent_type', 'unknown')
        
        if agent_type == 'chatforyou':
            platform = ai_settings.get('detected_platform', 'unknown')
            if platform == 'chatforyou':
                bot_id_configured = bool(ai_settings.get('chatforyou_bot_id'))
                if bot_id_configured:
                    return "✅ ChatForYou настроен", "chatforyou"
                else:
                    return "⚠️ ChatForYou (неполная настройка)", "chatforyou_partial"
            elif platform == 'protalk':
                return "✅ ProTalk настроен", "protalk"
            else:
                return "⚠️ Платформа неизвестна", "unknown_platform"
        
        elif agent_type == 'openai':
            agent_name = ai_settings.get('agent_name', 'OpenAI агент')
            creation_method = ai_settings.get('creation_method', 'unknown')
            
            if creation_method == 'real_openai_api':
                return f"✅ {agent_name} (OpenAI)", "openai"
            elif creation_method == 'fallback_stub':
                return f"⚠️ {agent_name} (тестовый)", "openai_stub"
            else:
                return f"✅ {agent_name} (OpenAI)", "openai"
        
        else:
            return "⚠️ Неизвестный тип", "unknown"
    
    async def _get_admin_welcome_text(self) -> str:
        """✅ ОБНОВЛЕНО: Генерация приветственного текста с токеновой статистикой и контент-агентом"""
        # ✅ КРИТИЧНО: Получаем свежие данные из БД
        config = await self._get_fresh_config()
        
        # Используем self.stats напрямую из переданной конфигурации
        total_sent = (self.stats.get('welcome_sent', 0) + 
                     self.stats.get('goodbye_sent', 0) + 
                     self.stats.get('confirmation_sent', 0))
        
        # ✅ ИСПРАВЛЕНО: Проверяем настройки из свежего config, а не из self
        has_welcome = bool(config.get('welcome_message'))
        has_welcome_button = bool(config.get('welcome_button_text'))
        has_confirmation = bool(config.get('confirmation_message'))
        has_goodbye = bool(config.get('goodbye_message'))
        has_goodbye_button = bool(config.get('goodbye_button_text') and config.get('goodbye_button_url'))
        
        # ✅ ИЗМЕНЕНО: Получаем информацию об ИИ агенте (упрощенная логика)
        ai_status, ai_type = self._get_ai_agent_info(config)
        
        # ✅ НОВОЕ: Получаем статистику токенов
        token_stats = await self._get_token_stats()
        
        # ✅ НОВОЕ: Получаем информацию о контент-агенте
        content_agent_status, has_content_agent = await self._get_content_agent_info()
        
        # ✅ НОВОЕ: Формируем секцию токенов
        token_section = ""
        if token_stats['has_openai_bots']:
            used_formatted = self._format_number(token_stats['total_used'])
            limit_formatted = self._format_number(token_stats['limit'])
            percentage = self._format_percentage(token_stats['total_used'], token_stats['limit'])
            
            # Определяем эмоджи в зависимости от процента использования
            if token_stats['percentage_used'] >= 90:
                token_emoji = "🔴"  # Критично
            elif token_stats['percentage_used'] >= 70:
                token_emoji = "🟡"  # Предупреждение
            else:
                token_emoji = "💰"  # Нормально
            
            token_section = f"\n{token_emoji} <b>Токены OpenAI:</b> {used_formatted} / {limit_formatted} ({percentage})"
            
        base_text = f"""
{Emoji.ROBOT} <b>Админ-панель @{self.bot_username or 'bot'}</b>

{Emoji.SUCCESS} <b>Статус:</b> Активен
{Emoji.MESSAGE} <b>Сообщений отправлено:</b> {total_sent}
{Emoji.BUTTON} <b>Кнопок нажато:</b> {self.stats.get('button_clicks', 0)}
{Emoji.FUNNEL} <b>Воронок запущено:</b> {self.stats.get('funnel_starts', 0)}{token_section}

{Emoji.INFO} <b>Настройки:</b>
- Приветствие: {'✅' if has_welcome else '❌'}
- Кнопка приветствия: {'✅' if has_welcome_button else '❌'}
- Подтверждение: {'✅' if has_confirmation else '❌'}
- Прощание: {'✅' if has_goodbye else '❌'}
- Кнопка прощания: {'✅' if has_goodbye_button else '❌'}

🤖 <b>ИИ Агент:</b> {ai_status}
📝 <b>Контент-агент:</b> {content_agent_status}

Выберите раздел для настройки:
"""
        
        return base_text
    
    async def cmd_start(self, message: Message, state: FSMContext):
        """✅ ОБНОВЛЕНО: Команда /start с динамическими данными"""
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
            
            # ✅ ИСПРАВЛЕНО: Owner access - показываем админ панель со свежими данными
            admin_text = await self._get_admin_welcome_text()
            
            # ✅ НОВОЕ: Определяем клавиатуру в зависимости от наличия OpenAI ботов
            token_stats = await self._get_token_stats()
            keyboard = AdminKeyboards.main_menu(has_openai_bots=token_stats['has_openai_bots'])
            
            await message.answer(
                admin_text,
                reply_markup=keyboard
            )
            
            logger.info("✅ Owner accessed admin panel with fresh data", 
                       bot_id=self.bot_id, 
                       owner_user_id=user_id,
                       bot_username=self.bot_username,
                       has_openai_bots=token_stats['has_openai_bots'])
                       
        except Exception as e:
            logger.error("Error in cmd_start", bot_id=self.bot_id, error=str(e), exc_info=True)
            await message.answer(
                "❌ Ошибка при загрузке админ панели. Проверьте логи.",
                reply_markup=ReplyKeyboardRemove()
            )
    
    async def cb_admin_main(self, callback: CallbackQuery, state: FSMContext):
        """✅ ОБНОВЛЕНО: Главное меню админки с динамическими данными"""
        await callback.answer()
        await state.clear()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        # ✅ ИСПРАВЛЕНО: Получаем свежие данные для главного меню
        admin_text = await self._get_admin_welcome_text()
        
        # ✅ НОВОЕ: Определяем клавиатуру в зависимости от наличия OpenAI ботов
        token_stats = await self._get_token_stats()
        keyboard = AdminKeyboards.main_menu(has_openai_bots=token_stats['has_openai_bots'])
        
        await callback.message.edit_text(
            admin_text,
            reply_markup=keyboard
        )
        
        logger.debug("✅ Admin main menu refreshed with fresh data", 
                    bot_id=self.bot_id,
                    has_openai_bots=token_stats['has_openai_bots'])
    
    async def cb_admin_settings(self, callback: CallbackQuery):
        """✅ ОБНОВЛЕНО: Настройки сообщений с динамическими данными"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        # ✅ КРИТИЧНО: Получаем свежие данные из БД
        config = await self._get_fresh_config()
        
        # ✅ ИСПРАВЛЕНО: Используем свежие данные из config
        welcome_status = "✅ Настроено" if config.get('welcome_message') else "❌ Не настроено"
        welcome_button_status = "✅ Настроено" if config.get('welcome_button_text') else "❌ Не настроено"
        confirmation_status = "✅ Настроено" if config.get('confirmation_message') else "❌ Не настроено"
        goodbye_status = "✅ Настроено" if config.get('goodbye_message') else "❌ Не настроено"
        goodbye_button_status = "✅ Настроено" if (config.get('goodbye_button_text') and config.get('goodbye_button_url')) else "❌ Не настроено"
        
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
        
        logger.debug("✅ Admin settings displayed with fresh data", 
                   bot_id=self.bot_id,
                   welcome_configured=bool(config.get('welcome_message')),
                   welcome_button_configured=bool(config.get('welcome_button_text')))
    
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
    
    async def cb_admin_tokens(self, callback: CallbackQuery):
        """✅ НОВОЕ: Детальная статистика токенов OpenAI"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        await self._show_token_stats(callback)
    
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
    
    async def _show_token_stats(self, callback: CallbackQuery):
        """✅ НОВОЕ: Показать детальную статистику токенов OpenAI"""
        try:
            logger.info("📊 Loading token statistics", 
                       user_id=self.owner_user_id,
                       bot_id=self.bot_id)
            
            # Получаем детальную статистику токенов
            token_stats = await self._get_token_stats()
            
            logger.debug("💰 Token stats loaded", 
                        has_openai_bots=token_stats['has_openai_bots'],
                        total_used=token_stats['total_used'],
                        bots_count=token_stats['bots_count'])
            
            if not token_stats['has_openai_bots']:
                text = f"""
💰 <b>Токены OpenAI</b>

❌ <b>OpenAI агенты не найдены</b>

У вас нет активных OpenAI агентов, поэтому токены не используются.

<b>Чтобы начать использовать токены:</b>
1. Создайте OpenAI агента в разделе "🤖 ИИ Агент"
2. Система автоматически выдаст вам стартовый пакет из 500,000 токенов
3. После этого здесь появится детальная статистика

{Emoji.INFO} <i>Токены нужны только для собственных OpenAI агентов</i>
"""
            else:
                # Форматируем числа и проценты
                used_formatted = self._format_number(token_stats['total_used'])
                limit_formatted = self._format_number(token_stats['limit'])
                remaining_formatted = self._format_number(token_stats['remaining'])
                input_formatted = self._format_number(token_stats['input_tokens'])
                output_formatted = self._format_number(token_stats['output_tokens'])
                percentage = self._format_percentage(token_stats['total_used'], token_stats['limit'])
                
                # Определяем статус и эмоджи
                if token_stats['percentage_used'] >= 90:
                    status_emoji = "🔴"
                    status_text = "Критично! Нужно пополнить"
                elif token_stats['percentage_used'] >= 70:
                    status_emoji = "🟡"
                    status_text = "Предупреждение"
                elif token_stats['percentage_used'] >= 50:
                    status_emoji = "🟠"
                    status_text = "Половина использована"
                else:
                    status_emoji = "🟢"
                    status_text = "В норме"
                
                # Форматируем дату последнего использования
                last_usage_text = "Не использовались"
                if token_stats['last_usage_at']:
                    try:
                        from datetime import datetime
                        if isinstance(token_stats['last_usage_at'], str):
                            last_usage = datetime.fromisoformat(token_stats['last_usage_at'].replace('Z', '+00:00'))
                        else:
                            last_usage = token_stats['last_usage_at']
                        last_usage_text = last_usage.strftime("%d.%m.%Y %H:%M")
                    except:
                        last_usage_text = "Недавно"
                
                text = f"""
💰 <b>Токены OpenAI</b>

{status_emoji} <b>Статус:</b> {status_text}

📊 <b>Использование:</b>
   Потрачено: {used_formatted} / {limit_formatted} ({percentage})
   Осталось: {remaining_formatted}

📈 <b>Детализация:</b>
   Входящие токены: {input_formatted}
   Исходящие токены: {output_formatted}
   
🤖 <b>OpenAI ботов:</b> {token_stats['bots_count']}
⏰ <b>Последнее использование:</b> {last_usage_text}

{Emoji.INFO} <b>Что такое токены?</b>
• Токены - это единицы измерения для OpenAI API
• ~1 токен ≈ 0.75 слова в русском языке
• Входящие: ваши сообщения к ИИ
• Исходящие: ответы ИИ вам

{Emoji.ROCKET} <b>Пополнение токенов:</b>
Обратитесь к администратору для увеличения лимита
"""
            
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            
            # Создаем клавиатуру
            keyboard_buttons = [
                [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_tokens")]
            ]
            
            # Добавляем кнопку пополнения только если есть OpenAI боты
            if token_stats['has_openai_bots']:
                keyboard_buttons.append([
                    InlineKeyboardButton(text="💳 Запросить пополнение", callback_data="request_token_topup")
                ])
            
            keyboard_buttons.append([
                InlineKeyboardButton(text=f"{Emoji.BACK} Главное меню", callback_data="admin_main")
            ])
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
            logger.info("✅ Token statistics displayed successfully", 
                       user_id=self.owner_user_id,
                       total_used=token_stats['total_used'],
                       percentage_used=token_stats['percentage_used'])
            
        except Exception as e:
            logger.error("💥 Failed to show token stats", 
                        bot_id=self.bot_id,
                        user_id=self.owner_user_id,
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            await callback.answer("Ошибка при загрузке статистики токенов", show_alert=True)
    
    async def debug_owner_message(self, message: Message):
        """✅ ОБНОВЛЕНО: Debug метод с проверкой свежих данных, токенов и контент-агента"""
        user_id = message.from_user.id
        is_owner = self._is_owner(user_id)
        
        # ✅ Добавляем отладку свежих данных
        config = await self._get_fresh_config()
        ai_status, ai_type = self._get_ai_agent_info(config)
        
        # ✅ НОВОЕ: Добавляем отладку токенов
        token_stats = await self._get_token_stats()
        
        # ✅ НОВОЕ: Добавляем отладку контент-агента
        content_agent_status, has_content_agent = await self._get_content_agent_info()
        
        await message.answer(
            f"🔍 <b>Debug Info:</b>\n"
            f"User ID: {user_id}\n"
            f"Owner ID: {self.owner_user_id}\n"
            f"Is Owner: {is_owner}\n"
            f"Bot ID: {self.bot_id}\n"
            f"Bot Username: {self.bot_username}\n\n"
            f"🔄 <b>Fresh Config Check:</b>\n"
            f"Welcome Message: {'✅' if config.get('welcome_message') else '❌'}\n"
            f"Welcome Button: {'✅' if config.get('welcome_button_text') else '❌'}\n"
            f"Confirmation: {'✅' if config.get('confirmation_message') else '❌'}\n"
            f"AI Agent: {ai_status}\n"
            f"AI Type: {ai_type}\n\n"
            f"💰 <b>Token Stats:</b>\n"
            f"Has OpenAI Bots: {token_stats['has_openai_bots']}\n"
            f"Tokens Used: {self._format_number(token_stats['total_used'])}\n"
            f"Tokens Limit: {self._format_number(token_stats['limit'])}\n"
            f"Usage %: {self._format_percentage(token_stats['total_used'], token_stats['limit'])}\n"
            f"Bots Count: {token_stats['bots_count']}\n\n"
            f"📝 <b>Content Agent:</b>\n"
            f"Status: {content_agent_status}\n"
            f"Has Agent: {has_content_agent}"
        )
