"""
Обработчики команд администратора
✅ ПОЛНАЯ ИНТЕГРАЦИЯ: Управление ИИ агентами в админ панели
✅ СОХРАНЕНО: Вся существующая логика (статистика, настройки, подписки)
✅ ДОБАВЛЕНО: Полноценное управление OpenAI агентами
✅ ДОБАВЛЕНО: Управление лимитами сообщений через MessageLimitManager
✅ АРХИТЕКТУРА: AdminHandler использует AIHandler методы через делегирование
✅ ИСПРАВЛЕНО: Конфликт callback_data для кнопки завершения диалога с ИИ
✅ ОБНОВЛЕНО: Поддержка каналов И групп для проверки подписки
✅ ДОБАВЛЕНО: Проверки доступа владельца через access_control
✅ ОБНОВЛЕНО: Токены всегда показываются (даже без ИИ агентов)
✅ ИСПРАВЛЕНО: Использование TokenManager для актуальных данных о токенах
"""

import structlog
from datetime import datetime
from aiogram import Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardRemove

from config import Emoji
from ..keyboards import AdminKeyboards
from ..formatters import MessageFormatter
from ..states import ChannelStates, AISettingsStates

logger = structlog.get_logger()


def register_admin_handlers(dp: Dispatcher, **kwargs):
    """Регистрация обработчиков администратора"""
    
    db = kwargs['db']
    bot_config = kwargs['bot_config']
    funnel_manager = kwargs['funnel_manager']
    user_bot = kwargs.get('user_bot')
    access_control = kwargs.get('access_control')  # ✅ НОВОЕ
    
    try:
        # Создаем экземпляр обработчика с полной конфигурацией
        handler = AdminHandler(db, bot_config, funnel_manager, user_bot, access_control)  # ✅ НОВОЕ
        
        # ===== ОСНОВНЫЕ АДМИНСКИЕ КОМАНДЫ =====
        dp.message.register(handler.cmd_start, CommandStart())
        
        # ===== НАВИГАЦИОННЫЕ CALLBACK =====
        dp.callback_query.register(handler.cb_admin_main, F.data == "admin_main")
        dp.callback_query.register(handler.cb_admin_settings, F.data == "admin_settings")
        dp.callback_query.register(handler.cb_admin_funnel, F.data == "admin_funnel")
        dp.callback_query.register(handler.cb_admin_stats, F.data == "admin_stats")
        dp.callback_query.register(handler.cb_admin_tokens, F.data == "admin_tokens")
        
        # ===== ✅ НОВОЕ: ПОЛНОЕ УПРАВЛЕНИЕ ИИ АГЕНТАМИ =====
        dp.callback_query.register(handler.cb_admin_ai, F.data == "admin_ai")
        dp.callback_query.register(handler.cb_ai_management, F.data == "ai_management")
        dp.callback_query.register(handler.cb_create_openai_agent, F.data == "create_openai_agent")
        dp.callback_query.register(handler.cb_configure_openai_agent, F.data == "configure_openai_agent")
        dp.callback_query.register(handler.cb_test_openai_agent, F.data == "test_openai_agent")
        dp.callback_query.register(handler.cb_delete_openai_agent, F.data == "delete_openai_agent")
        dp.callback_query.register(handler.cb_confirm_delete_agent, F.data == "openai_confirm_delete")
        dp.callback_query.register(handler.cb_edit_agent_name, F.data == "openai_edit_name")
        dp.callback_query.register(handler.cb_edit_agent_prompt, F.data == "openai_edit_prompt")
        # ✅ ИСПРАВЛЕНО: Новый callback_data для админского завершения диалога
        dp.callback_query.register(handler.cb_admin_ai_exit_conversation, F.data == "admin_ai_exit_conversation")
        
        # ===== ✅ НОВОЕ: ОБРАБОТЧИКИ ЛИМИТОВ СООБЩЕНИЙ =====
        dp.callback_query.register(handler.cb_ai_message_limit, F.data == "ai_message_limit")
        dp.callback_query.register(handler.cb_ai_set_message_limit, F.data == "ai_set_message_limit")
        dp.callback_query.register(handler.cb_ai_disable_message_limit, F.data == "ai_disable_message_limit")
        
        # ===== ✅ НОВОЕ: FSM ОБРАБОТЧИКИ ДЛЯ ИИ =====
        dp.message.register(
            handler.handle_openai_name_input,
            AISettingsStates.admin_waiting_for_openai_name
        )
        dp.message.register(
            handler.handle_openai_role_input,
            AISettingsStates.admin_waiting_for_openai_role
        )
        dp.message.register(
            handler.handle_agent_name_edit,
            AISettingsStates.admin_editing_agent_name
        )
        dp.message.register(
            handler.handle_agent_prompt_edit,
            AISettingsStates.admin_editing_agent_prompt
        )
        dp.message.register(
            handler.handle_admin_ai_conversation,
            AISettingsStates.admin_in_ai_conversation
        )
        
        # ===== ✅ НОВОЕ: FSM ОБРАБОТЧИК ДЛЯ ВВОДА ЛИМИТА =====
        dp.message.register(
            handler.handle_message_limit_input,
            AISettingsStates.waiting_for_message_limit
        )
        
        # ===== НАСТРОЙКИ ПОДПИСКИ =====
        dp.callback_query.register(handler.cb_subscription_settings, F.data == "admin_subscription")
        dp.callback_query.register(handler.cb_toggle_subscription, F.data == "toggle_subscription")
        dp.callback_query.register(handler.cb_set_subscription_channel, F.data == "set_subscription_channel")
        dp.callback_query.register(handler.cb_edit_subscription_message, F.data == "edit_subscription_message")
        
        # FSM обработчик для пересланного сообщения канала
        dp.message.register(
            handler.handle_forwarded_channel, 
            ChannelStates.waiting_for_subscription_channel
        )
        
        # Debug handler
        dp.message.register(handler.debug_owner_message, F.text == "test")
        
        logger.info("✅ Admin handlers registered successfully with AI integration, message limits, access control and TokenManager integration", 
                   bot_id=bot_config['bot_id'], 
                   owner_id=bot_config['owner_user_id'],
                   ai_handlers_count=9,
                   message_limit_handlers=4,
                   total_handlers=23,
                   access_control_enabled=bool(access_control),
                   token_manager_direct=True)
        
    except Exception as e:
        logger.error("💥 Failed to register admin handlers", 
                    bot_id=kwargs.get('bot_config', {}).get('bot_id', 'unknown'),
                    error=str(e), exc_info=True)
        raise


class AdminHandler:
    """Класс обработчиков администратора с полной интеграцией ИИ и лимитов сообщений"""
    
    def __init__(self, db, bot_config: dict, funnel_manager, user_bot, access_control=None):
        self.db = db
        self.bot_config = bot_config
        self.bot_id = bot_config['bot_id']
        self.owner_user_id = bot_config['owner_user_id']
        self.bot_username = bot_config['bot_username']
        self.funnel_manager = funnel_manager
        self.formatter = MessageFormatter()
        self.user_bot = user_bot
        self.access_control = access_control  # ✅ НОВОЕ
        
        # Кэшируем только статичные данные
        self.stats = bot_config.get('stats', {})
        
        # ✅ НОВОЕ: Инициализация AI helper
        self._ai_handler = None
        
        # ✅ НОВОЕ: Инициализация MessageLimitManager
        self._message_limit_manager = None
    
    async def _get_ai_handler(self):
        """Ленивая инициализация AI handler"""
        if self._ai_handler is None:
            try:
                from .ai_handlers import AIHandler
                self._ai_handler = AIHandler(
                    db=self.db,
                    bot_config=self.bot_config,
                    user_bot=self.user_bot
                )
                logger.debug("✅ AI handler initialized", bot_id=self.bot_id)
            except Exception as e:
                logger.error("💥 Failed to initialize AI handler", error=str(e))
                return None
        return self._ai_handler
    
    async def _get_message_limit_manager(self):
        """Ленивая инициализация MessageLimitManager"""
        if self._message_limit_manager is None:
            try:
                from .ai_message_limits import MessageLimitManager
                self._message_limit_manager = MessageLimitManager(
                    db=self.db,
                    bot_config=self.bot_config
                )
                logger.debug("✅ MessageLimitManager initialized", bot_id=self.bot_id)
            except Exception as e:
                logger.error("💥 Failed to initialize MessageLimitManager", error=str(e))
                return None
        return self._message_limit_manager
    
    async def _create_openai_handler(self):
        """Создание экземпляра OpenAIHandler"""
        try:
            from .ai_openai_handler import OpenAIHandler
            
            openai_handler = OpenAIHandler(
                db=self.db,
                bot_config=self.bot_config,
                ai_assistant=None,
                user_bot=self.user_bot
            )
            
            logger.debug("✅ OpenAIHandler created for admin", bot_id=self.bot_id)
            return openai_handler
            
        except Exception as e:
            logger.error("💥 Failed to create OpenAIHandler", error=str(e))
            return None
    
    async def _safe_edit_message(self, callback: CallbackQuery, text: str, reply_markup=None, parse_mode="HTML"):
        """Безопасное редактирование сообщения с проверкой типа"""
        try:
            # Проверяем, есть ли текст в сообщении
            if callback.message.text:
                await callback.message.edit_text(
                    text=text, 
                    reply_markup=reply_markup, 
                    parse_mode=parse_mode
                )
            elif callback.message.caption is not None:
                # Сообщение содержит медиа с подписью
                await callback.message.edit_caption(
                    caption=text, 
                    reply_markup=reply_markup, 
                    parse_mode=parse_mode
                )
            else:
                # Сообщение содержит медиа без подписи или другой тип
                # Удаляем старое и отправляем новое
                await callback.message.delete()
                await callback.bot.send_message(
                    chat_id=callback.message.chat.id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
        except Exception as e:
            logger.warning(f"Failed to edit message safely, using fallback: {e}")
            try:
                # Fallback: удаляем старое и отправляем новое
                await callback.message.delete()
                await callback.bot.send_message(
                    chat_id=callback.message.chat.id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
            except Exception as fallback_error:
                logger.error(f"Fallback message edit also failed: {fallback_error}")
                # Последний fallback: просто отправляем новое сообщение
                await callback.bot.send_message(
                    chat_id=callback.message.chat.id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
    
    async def _get_fresh_config(self) -> dict:
        """Получение свежей конфигурации из БД"""
        try:
            fresh_config = await self.db.get_bot_full_config(self.bot_id, fresh=True)
            
            if fresh_config:
                logger.debug("✅ Fresh config loaded", 
                           bot_id=self.bot_id,
                           subscription_enabled=fresh_config.get('subscription_check_enabled', False))
                return fresh_config
            else:
                logger.warning("❌ Failed to load fresh config, using cached", bot_id=self.bot_id)
                return self.bot_config
                
        except Exception as e:
            logger.error("❌ Error loading fresh config", bot_id=self.bot_id, error=str(e))
            return self.bot_config
    
    async def _get_fresh_ai_config(self) -> dict:
        """Получение свежей конфигурации ИИ агента"""
        try:
            ai_config = await self.db.get_ai_config(self.bot_id)
            return ai_config or {}
        except Exception as e:
            logger.error("💥 Failed to get fresh AI config", error=str(e))
            return {}
    
    def _format_number(self, number: int) -> str:
        """Форматирование чисел с пробелами (22 500)"""
        return f"{number:,}".replace(",", " ")
    
    def _format_percentage(self, used: int, limit: int) -> str:
        """Форматирование процента использования"""
        if limit <= 0:
            return "0%"
        percentage = (used / limit) * 100
        return f"{percentage:.1f}%"
    
    async def _get_token_stats(self) -> dict:
        """✅ ИСПРАВЛЕНО: Получение статистики токенов OpenAI через TokenManager (всегда актуальные данные)"""
        try:
            # ✅ ИСПРАВЛЕНО: Используем TokenManager напрямую
            from database.managers.token_manager import TokenManager
            token_balance = await TokenManager.get_user_token_balance(self.owner_user_id)
            
            logger.debug("💰 Token balance retrieved via TokenManager", 
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
            logger.error("💥 Failed to get token stats via TokenManager", 
                        user_id=self.owner_user_id,
                        error=str(e),
                        error_type=type(e).__name__)
            
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
    
    async def _get_subscription_enabled(self) -> bool:
        """Получение статуса подписки (может использовать кэш)"""
        try:
            config = await self._get_fresh_config()
            enabled = config.get('subscription_check_enabled', False)
            
            logger.debug("🔍 Subscription status checked", 
                        bot_id=self.bot_id,
                        enabled=enabled)
            
            return enabled
            
        except Exception as e:
            logger.error("❌ Failed to get subscription status", bot_id=self.bot_id, error=str(e))
            return False

    async def _get_subscription_enabled_fresh(self) -> bool:
        """✅ АГРЕССИВНОЕ получение статуса подписки"""
        try:
            enabled, _ = await self.db.get_subscription_status_no_cache(self.bot_id)
            
            logger.debug("🔥 AGGRESSIVE subscription status checked", 
                        bot_id=self.bot_id,
                        enabled=enabled)
            return enabled
            
        except Exception as e:
            logger.error("❌ Failed to get aggressive subscription status", bot_id=self.bot_id, error=str(e))
            return False
    
    async def _get_subscription_channel_info(self) -> dict:
        """Получение информации о канале (может использовать кэш)"""
        try:
            config = await self._get_fresh_config()
            
            return {
                'channel_id': config.get('subscription_channel_id'),
                'channel_username': config.get('subscription_channel_username'),
                'deny_message': config.get('subscription_deny_message', 'Для доступа к ИИ агенту необходимо подписаться на наш канал.')
            }
            
        except Exception as e:
            logger.error("❌ Failed to get channel info", bot_id=self.bot_id, error=str(e))
            return {
                'channel_id': None,
                'channel_username': None,
                'deny_message': 'Для доступа к ИИ агенту необходимо подписаться на наш канал.'
            }

    async def _get_subscription_channel_info_fresh(self) -> dict:
        """✅ АГРЕССИВНОЕ получение информации о канале"""
        try:
            _, channel_info = await self.db.get_subscription_status_no_cache(self.bot_id)
            
            logger.debug("🔥 AGGRESSIVE channel info retrieved", 
                        bot_id=self.bot_id,
                        has_channel=bool(channel_info.get('channel_id')))
            return channel_info
            
        except Exception as e:
            logger.error("❌ Failed to get aggressive channel info", bot_id=self.bot_id, error=str(e))
            return {
                'channel_id': None,
                'channel_username': None,
                'deny_message': 'Для доступа к ИИ агенту необходимо подписаться на наш канал.'
            }
    
    async def _get_content_agent_info(self) -> tuple[str, bool]:
        """Получение информации о контент-агенте"""
        has_content_agent = False
        content_agent_status = "❌ Не создан"
        
        try:
            agent_info = await self.db.get_content_agent(self.bot_id)
            
            if agent_info and not agent_info.get('deleted_at'):
                has_content_agent = True
                agent_name = agent_info.get('agent_name', 'Контент-агент')
                
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
        """Проверка наличия ИИ агента"""
        has_agent = bool(config.get('ai_assistant_id'))
        logger.debug("AI agent check", 
                    bot_id=self.bot_id,
                    has_agent=has_agent,
                    ai_assistant_id_exists=bool(config.get('ai_assistant_id')))
        return has_agent
    
    def _get_ai_agent_info(self, config: dict) -> tuple[str, str]:
        """Получение информации об ИИ агенте"""
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
    
    async def _get_ai_agent_info_fresh(self) -> tuple[str, str, dict]:
        """✅ НОВОЕ: Получение СВЕЖЕЙ информации об ИИ агенте"""
        try:
            fresh_ai_config = await self._get_fresh_ai_config()
            
            if not fresh_ai_config or not fresh_ai_config.get('enabled') or not fresh_ai_config.get('agent_id'):
                return "❌ Не создан", "none", {}
            
            agent_type = fresh_ai_config.get('type', 'unknown')
            agent_settings = fresh_ai_config.get('settings', {})
            
            if agent_type == 'openai':
                agent_name = agent_settings.get('agent_name', 'OpenAI агент')
                creation_method = agent_settings.get('creation_method', 'unknown')
                
                if creation_method == 'real_openai_api':
                    status = f"✅ {agent_name} (OpenAI)"
                elif creation_method == 'fallback_stub':
                    status = f"⚠️ {agent_name} (тестовый)"
                else:
                    status = f"✅ {agent_name} (OpenAI)"
                
                return status, "openai", fresh_ai_config
            else:
                return f"⚠️ {agent_type}", agent_type, fresh_ai_config
                
        except Exception as e:
            logger.error("💥 Failed to get fresh AI agent info", error=str(e))
            return "❌ Ошибка загрузки", "error", {}
    
    async def _get_admin_welcome_text(self) -> str:
        """✅ ОБНОВЛЕНО: Генерация приветственного текста с ВСЕГДА показываемыми токенами"""
        config = await self._get_fresh_config()
        
        total_sent = (self.stats.get('welcome_sent', 0) + 
                     self.stats.get('goodbye_sent', 0) + 
                     self.stats.get('confirmation_sent', 0))
        
        # ✅ НОВОЕ: Получаем статистику массовых рассылок
        try:
            broadcast_stats = await self.db.get_mass_broadcast_stats(self.bot_id, days=30)
            broadcasts_sent = broadcast_stats.get('deliveries', {}).get('successful', 0)
        except Exception as e:
            logger.warning("Failed to get broadcast stats", bot_id=self.bot_id, error=str(e))
            broadcasts_sent = 0
        
        has_welcome = bool(config.get('welcome_message'))
        has_welcome_button = bool(config.get('welcome_button_text'))
        has_confirmation = bool(config.get('confirmation_message'))
        has_goodbye = bool(config.get('goodbye_message'))
        has_goodbye_button = bool(config.get('goodbye_button_text') and config.get('goodbye_button_url'))
        
        ai_status, ai_type = self._get_ai_agent_info(config)
        # ✅ ИСПРАВЛЕНО: TokenManager всегда возвращает актуальные данные
        token_stats = await self._get_token_stats()
        content_agent_status, has_content_agent = await self._get_content_agent_info()
        
        # ✅ ИСПРАВЛЕНО: Используем FRESH методы вместо кэшированных
        subscription_enabled = await self._get_subscription_enabled_fresh()
        subscription_status = "🟢 Включена" if subscription_enabled else "🔴 Выключена"
        
        # ✅ ИЗМЕНЕНО: Формируем секцию токенов ВСЕГДА (убрано условие)
        used_formatted = self._format_number(token_stats['total_used'])
        limit_formatted = self._format_number(token_stats['limit'])
        percentage = self._format_percentage(token_stats['total_used'], token_stats['limit'])
        
        if token_stats['percentage_used'] >= 90:
            token_emoji = "🔴"
        elif token_stats['percentage_used'] >= 70:
            token_emoji = "🟡"
        else:
            token_emoji = "💰"
        
        token_section = f"\n{token_emoji} <b>Токены OpenAI:</b> {used_formatted} / {limit_formatted} ({percentage})"
            
        base_text = f"""
{Emoji.ROBOT} <b>Админ-панель @{self.bot_username or 'bot'}</b>

{Emoji.SUCCESS} <b>Статус:</b> Активен
{Emoji.MESSAGE} <b>Сообщений отправлено:</b> {total_sent}
{Emoji.BUTTON} <b>Кнопок нажато:</b> {self.stats.get('button_clicks', 0)}
{Emoji.FUNNEL} <b>Воронок запущено:</b> {self.stats.get('funnel_starts', 0)}
📨 <b>Рассылок отправлено:</b> {broadcasts_sent}{token_section}

{Emoji.INFO} <b>Настройки:</b>
- Приветствие: {'✅' if has_welcome else '❌'}
- Кнопка приветствия: {'✅' if has_welcome_button else '❌'}
- Подтверждение: {'✅' if has_confirmation else '❌'}
- Прощание: {'✅' if has_goodbye else '❌'}
- Кнопка прощания: {'✅' if has_goodbye_button else '❌'}

🤖 <b>ИИ Агент:</b> {ai_status}
📝 <b>Контент-агент:</b> {content_agent_status}
🔒 <b>Подписка:</b> {subscription_status}

Выберите раздел для настройки:
"""
        
        return base_text
    
    # ===== ОСНОВНЫЕ АДМИНСКИЕ ОБРАБОТЧИКИ =====
    
    async def cmd_start(self, message: Message, state: FSMContext):
        """Команда /start с динамическими данными"""
        # ✅ НОВОЕ: Проверка доступа владельца
        if self.access_control:
            has_access, status = await self.access_control['check_owner_access']()
            if not has_access:
                await self.access_control['send_access_denied'](message, status)
                return
        
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
            
            admin_text = await self._get_admin_welcome_text()
            # ✅ ИСПРАВЛЕНО: TokenManager всегда возвращает актуальные данные
            token_stats = await self._get_token_stats()
            # ✅ ИЗМЕНЕНО: Всегда показываем кнопку токенов
            keyboard = AdminKeyboards.main_menu(has_openai_bots=True)
            
            await message.answer(
                admin_text,
                reply_markup=keyboard
            )
            
            logger.info("✅ Owner accessed admin panel", 
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
        """Главное меню админки"""
        # ✅ НОВОЕ: Проверка доступа владельца
        if self.access_control:
            has_access, status = await self.access_control['check_owner_access']()
            if not has_access:
                await self.access_control['send_access_denied'](callback, status)
                return
        
        await callback.answer()
        await state.clear()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        admin_text = await self._get_admin_welcome_text()
        # ✅ ИСПРАВЛЕНО: TokenManager всегда возвращает актуальные данные
        token_stats = await self._get_token_stats()
        # ✅ ИЗМЕНЕНО: Всегда показываем кнопку токенов
        keyboard = AdminKeyboards.main_menu(has_openai_bots=True)
        
        await self._safe_edit_message(
            callback,
            admin_text,
            reply_markup=keyboard
        )
        
        logger.debug("✅ Admin main menu refreshed", 
                    bot_id=self.bot_id,
                    has_openai_bots=token_stats['has_openai_bots'])
    
    async def cb_admin_settings(self, callback: CallbackQuery):
        """Настройки сообщений"""
        # ✅ НОВОЕ: Проверка доступа владельца
        if self.access_control:
            has_access, status = await self.access_control['check_owner_access']()
            if not has_access:
                await self.access_control['send_access_denied'](callback, status)
                return
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        config = await self._get_fresh_config()
        
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
        
        await self._safe_edit_message(
            callback,
            text,
            reply_markup=AdminKeyboards.settings_menu()
        )
        
        logger.debug("✅ Admin settings displayed", 
                   bot_id=self.bot_id,
                   welcome_configured=bool(config.get('welcome_message')),
                   welcome_button_configured=bool(config.get('welcome_button_text')))
    
    async def cb_admin_funnel(self, callback: CallbackQuery):
        """Воронка продаж"""
        # ✅ НОВОЕ: Проверка доступа владельца
        if self.access_control:
            has_access, status = await self.access_control['check_owner_access']()
            if not has_access:
                await self.access_control['send_access_denied'](callback, status)
                return
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        from .funnel_handlers import show_funnel_main_menu
        await show_funnel_main_menu(callback, self.bot_id, self.bot_username, self.funnel_manager)
    
    # ===== ✅ НОВОЕ: ПОЛНОЕ УПРАВЛЕНИЕ ИИ АГЕНТАМИ =====
    
    async def cb_admin_ai(self, callback: CallbackQuery):
        """✅ ОБНОВЛЕНО: Главное меню управления ИИ агентом с лимитами"""
        # ✅ НОВОЕ: Проверка доступа владельца
        if self.access_control:
            has_access, status = await self.access_control['check_owner_access']()
            if not has_access:
                await self.access_control['send_access_denied'](callback, status)
                return
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        # Получаем свежую информацию об агенте
        ai_status, ai_type, ai_config = await self._get_ai_agent_info_fresh()
        # ✅ ИСПРАВЛЕНО: TokenManager всегда возвращает актуальные данные
        token_stats = await self._get_token_stats()
        
        text = f"""
🤖 <b>Управление ИИ Агентом</b>

<b>Текущий статус:</b> {ai_status}

<b>Доступные действия:</b>
"""
        
        # Формируем клавиатуру в зависимости от статуса агента
        keyboard_buttons = []
        
        if ai_type == "none":
            # Агента нет - показываем создание
            text += """
• Создать нового OpenAI агента
• Настроить параметры агента
• Настроить ограничения доступа

<b>Начать настройку ИИ агента?</b>"""
            
            keyboard_buttons = [
                [InlineKeyboardButton(text="➕ Создать OpenAI агента", callback_data="create_openai_agent")],
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_main")]
            ]
        else:
            # ✅ НОВОЕ: Получаем информацию о лимитах
            try:
                current_limit = await self.db.get_daily_message_limit(self.bot_id)
                limit_info = ""
                if current_limit > 0:
                    limit_info = f"\n<b>Лимит сообщений:</b> {current_limit} в день"
            except:
                limit_info = ""
            
            # Агент есть - показываем управление
            agent_settings = ai_config.get('settings', {})
            agent_name = agent_settings.get('agent_name', 'ИИ Агент')
            
            text += f"""
• Настроить параметры агента
• Протестировать работу агента
• Изменить роль и инструкции
• Управлять лимитами сообщений
• Удалить агента

<b>Агент:</b> {agent_name}{limit_info}"""
            
            # Информация о токенах для OpenAI агентов
            if ai_type == "openai":
                used_formatted = self._format_number(token_stats['total_used'])
                limit_formatted = self._format_number(token_stats['limit'])
                percentage = self._format_percentage(token_stats['total_used'], token_stats['limit'])
                text += f"\n<b>Токены:</b> {used_formatted} / {limit_formatted} ({percentage})"
            
            keyboard_buttons = [
                [InlineKeyboardButton(text="🧪 Протестировать агента", callback_data="test_openai_agent")],
                [InlineKeyboardButton(text="📚 База знаний", callback_data="openai_upload_files")],
                [InlineKeyboardButton(text="⚙️ Настроить агента", callback_data="configure_openai_agent")],
                [InlineKeyboardButton(text="📊 Лимит сообщений", callback_data="ai_message_limit")],  # ✅ НОВОЕ
                [InlineKeyboardButton(text="🗑️ Удалить агента", callback_data="delete_openai_agent")],
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_main")]
            ]
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        await self._safe_edit_message(callback, text, reply_markup=keyboard)
        
        logger.info("✅ AI management menu displayed", 
                   bot_id=self.bot_id,
                   ai_type=ai_type,
                   ai_status=ai_status)
    
    async def cb_ai_management(self, callback: CallbackQuery):
        """Альтернативный вход в управление ИИ (совместимость)"""
        await self.cb_admin_ai(callback)
    
    async def cb_create_openai_agent(self, callback: CallbackQuery, state: FSMContext):
        """Создание нового OpenAI агента"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Проверяем что агента еще нет
            ai_config = await self._get_fresh_ai_config()
            if ai_config and ai_config.get('enabled'):
                await callback.answer("❌ ИИ агент уже существует. Удалите старого для создания нового.", show_alert=True)
                return
            
            await state.set_state(AISettingsStates.admin_waiting_for_openai_name)
            
            text = """
➕ <b>Создание OpenAI агента</b>

<b>Шаг 1 из 2:</b> Введите имя для вашего ИИ агента

<b>Примеры имен:</b>
• Консультант по продажам
• Помощник по SEO
• Эксперт по недвижимости
• Бизнес-аналитик
• Техподдержка

<b>Введите имя агента:</b>
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отменить", callback_data="admin_ai")]
            ])
            
            await self._safe_edit_message(callback, text, reply_markup=keyboard)
            
            logger.info("✅ OpenAI agent creation started", bot_id=self.bot_id)
            
        except Exception as e:
            logger.error("💥 Error starting OpenAI agent creation", error=str(e))
            await callback.answer("❌ Ошибка при запуске создания агента", show_alert=True)
    
    async def cb_configure_openai_agent(self, callback: CallbackQuery):
        """Настройка существующего OpenAI агента"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            ai_status, ai_type, ai_config = await self._get_ai_agent_info_fresh()
            
            if ai_type == "none":
                await callback.answer("❌ Сначала создайте ИИ агента", show_alert=True)
                return
            
            agent_settings = ai_config.get('settings', {})
            agent_name = agent_settings.get('agent_name', 'ИИ Агент')
            agent_prompt = agent_settings.get('system_prompt', 'Не настроен')
            daily_limit = agent_settings.get('daily_limit', 'Без ограничений')
            
            # Ограничиваем длину промпта для отображения
            prompt_preview = agent_prompt[:100] + "..." if len(agent_prompt) > 100 else agent_prompt
            
            text = f"""
⚙️ <b>Настройка ИИ агента</b>

<b>Текущие параметры:</b>

<b>Имя:</b> {agent_name}
<b>Роль:</b> {prompt_preview}
<b>Лимит сообщений:</b> {daily_limit if daily_limit != 'Без ограничений' else 'Нет ограничений'}

<b>Что можно изменить:</b>
"""
            
            keyboard_buttons = [
                [InlineKeyboardButton(text="✏️ Изменить имя", callback_data="openai_edit_name")],
                [InlineKeyboardButton(text="🎭 Изменить роль", callback_data="openai_edit_prompt")],
                [InlineKeyboardButton(text="📊 Настроить лимиты", callback_data="openai_set_limits")],
                [InlineKeyboardButton(text="🔙 Назад к ИИ", callback_data="admin_ai")]
            ]
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
            
            await self._safe_edit_message(callback, text, reply_markup=keyboard)
            
            logger.info("✅ AI agent configuration menu displayed", bot_id=self.bot_id)
            
        except Exception as e:
            logger.error("💥 Error showing AI configuration", error=str(e))
            await callback.answer("❌ Ошибка при загрузке настроек агента", show_alert=True)
    
    async def cb_test_openai_agent(self, callback: CallbackQuery, state: FSMContext):
        """Тестирование OpenAI агента"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            ai_status, ai_type, ai_config = await self._get_ai_agent_info_fresh()
            
            if ai_type == "none":
                await callback.answer("❌ Сначала создайте ИИ агента", show_alert=True)
                return
            
            # Проверяем токены для OpenAI агентов
            if ai_type == "openai":
                token_stats = await self._get_token_stats()
                if token_stats['remaining'] <= 0:
                    await callback.answer("❌ Закончились токены OpenAI", show_alert=True)
                    return
            
            await state.set_state(AISettingsStates.admin_in_ai_conversation)
            await state.update_data(
                agent_type=ai_type,
                agent_id=ai_config.get('agent_id'),
                is_admin_test=True
            )
            
            agent_settings = ai_config.get('settings', {})
            agent_name = agent_settings.get('agent_name', 'ИИ Агент')
            
            text = f"""
🧪 <b>Тестирование {agent_name}</b>

Вы находитесь в режиме тестирования ИИ агента. 

<b>Возможности:</b>
• Задавать любые вопросы агенту
• Проверять качество ответов
• Тестировать понимание инструкций

<b>Напишите ваш тестовый вопрос:</b>

<i>Для выхода используйте кнопку ниже или команды /exit, /stop</i>
"""
            
            # ✅ ИСПРАВЛЕНО: Используем admin-специфичный callback_data
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚪 Завершить тестирование", callback_data="admin_ai_exit_conversation")]
            ])
            
            await self._safe_edit_message(callback, text, reply_markup=keyboard)
            
            logger.info("✅ AI agent testing started", bot_id=self.bot_id)
            
        except Exception as e:
            logger.error("💥 Error starting AI testing", error=str(e))
            await callback.answer("❌ Ошибка при запуске тестирования", show_alert=True)
    
    async def cb_delete_openai_agent(self, callback: CallbackQuery):
        """Подтверждение удаления OpenAI агента"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            ai_status, ai_type, ai_config = await self._get_ai_agent_info_fresh()
            
            if ai_type == "none":
                await callback.answer("❌ ИИ агент не найден", show_alert=True)
                return
            
            agent_settings = ai_config.get('settings', {})
            agent_name = agent_settings.get('agent_name', 'ИИ Агент')
            
            text = f"""
🗑️ <b>Удаление ИИ агента</b>

<b>Вы уверены что хотите удалить агента?</b>

<b>Агент:</b> {agent_name}
<b>Тип:</b> {ai_type.upper()}

<b>⚠️ ВНИМАНИЕ:</b>
• Все настройки агента будут потеряны
• Пользователи потеряют доступ к ИИ
• Действие необратимо

<b>Подтвердите удаление:</b>
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🗑️ Да, удалить", callback_data="openai_confirm_delete")],
                [InlineKeyboardButton(text="❌ Отменить", callback_data="admin_ai")]
            ])
            
            await self._safe_edit_message(callback, text, reply_markup=keyboard)
            
            logger.info("✅ AI agent deletion confirmation displayed", bot_id=self.bot_id)
            
        except Exception as e:
            logger.error("💥 Error showing deletion confirmation", error=str(e))
            await callback.answer("❌ Ошибка при загрузке", show_alert=True)
    
    async def cb_confirm_delete_agent(self, callback: CallbackQuery):
        """Подтверждение удаления агента - делегируем в OpenAI handler"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            openai_handler = await self._create_openai_handler()
            if not openai_handler:
                await callback.answer("❌ Ошибка создания обработчика", show_alert=True)
                return
            
            is_owner_check = lambda user_id: self._is_owner(user_id)
            await openai_handler.handle_confirm_delete(callback, is_owner_check)
            
            logger.info("✅ AI agent deletion delegated to OpenAI handler", bot_id=self.bot_id)
            
        except Exception as e:
            logger.error("💥 Error in agent deletion", error=str(e))
            await callback.answer("❌ Ошибка при удалении агента", show_alert=True)
    
    async def cb_edit_agent_name(self, callback: CallbackQuery, state: FSMContext):
        """Редактирование имени агента"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            ai_status, ai_type, ai_config = await self._get_ai_agent_info_fresh()
            
            if ai_type == "none":
                await callback.answer("❌ ИИ агент не найден", show_alert=True)
                return
            
            agent_settings = ai_config.get('settings', {})
            current_name = agent_settings.get('agent_name', 'ИИ Агент')
            
            await state.set_state(AISettingsStates.admin_editing_agent_name)
            
            text = f"""
✏️ <b>Изменение имени агента</b>

<b>Текущее имя:</b> {current_name}

<b>Введите новое имя для агента:</b>

<b>Хорошие примеры:</b>
• Консультант по продажам
• Помощник по SEO  
• Эксперт по недвижимости
• Техподдержка

<i>Введите новое имя:</i>
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отменить", callback_data="configure_openai_agent")]
            ])
            
            await self._safe_edit_message(callback, text, reply_markup=keyboard)
            
            logger.info("✅ Agent name editing started", bot_id=self.bot_id)
            
        except Exception as e:
            logger.error("💥 Error starting name editing", error=str(e))
            await callback.answer("❌ Ошибка при запуске редактирования", show_alert=True)
    
    async def cb_edit_agent_prompt(self, callback: CallbackQuery, state: FSMContext):
        """Редактирование промпта агента"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            ai_status, ai_type, ai_config = await self._get_ai_agent_info_fresh()
            
            if ai_type == "none":
                await callback.answer("❌ ИИ агент не найден", show_alert=True)
                return
            
            agent_settings = ai_config.get('settings', {})
            current_prompt = agent_settings.get('system_prompt', 'Не настроен')
            
            await state.set_state(AISettingsStates.admin_editing_agent_prompt)
            
            # Показываем первые 300 символов промпта
            prompt_preview = current_prompt[:300] + "..." if len(current_prompt) > 300 else current_prompt
            
            text = f"""
🎭 <b>Изменение роли агента</b>

<b>Текущая роль:</b>
<code>{prompt_preview}</code>

<b>Введите новую роль и инструкции для агента:</b>

<b>Советы для хорошего промпта:</b>
• Четко опишите роль агента
• Укажите как он должен отвечать
• Добавьте специфику вашего бизнеса
• Определите стиль общения

<i>Введите новую роль:</i>
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отменить", callback_data="configure_openai_agent")]
            ])
            
            await self._safe_edit_message(callback, text, reply_markup=keyboard)
            
            logger.info("✅ Agent prompt editing started", bot_id=self.bot_id)
            
        except Exception as e:
            logger.error("💥 Error starting prompt editing", error=str(e))
            await callback.answer("❌ Ошибка при запуске редактирования", show_alert=True)
    
    async def cb_admin_ai_exit_conversation(self, callback: CallbackQuery, state: FSMContext):
        """✅ ОБНОВЛЕНО: Завершение диалога с ИИ - всегда возвращать в admin_ai"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            await state.clear()
            
            text = """
🚪 <b>Тестирование завершено</b>

Диалог с ИИ агентом закончен.

<b>Что дальше:</b>
• Если агент работает хорошо - он готов к использованию
• Если нужно изменить поведение - настройте роль
• Для дополнительной настройки используйте меню конфигурации

<b>Возвращаемся к управлению ИИ</b>
"""
            
            # ✅ ИЗМЕНЕНО: Убираем кнопку "Главное меню", оставляем только возврат к ИИ
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🤖 Управление ИИ", callback_data="admin_ai")]
            ])
            
            await self._safe_edit_message(callback, text, reply_markup=keyboard)
            
            logger.info("✅ AI testing conversation ended", bot_id=self.bot_id)
            
        except Exception as e:
            logger.error("💥 Error ending AI conversation", error=str(e))
            await callback.answer("❌ Ошибка при завершении диалога", show_alert=True)
    
    # ===== ✅ НОВОЕ: ОБРАБОТЧИКИ ЛИМИТОВ СООБЩЕНИЙ =====
    
    async def cb_ai_message_limit(self, callback: CallbackQuery):
        """Настройки лимита сообщений"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            limit_manager = await self._get_message_limit_manager()
            if not limit_manager:
                await callback.answer("❌ Ошибка инициализации", show_alert=True)
                return
            
            await limit_manager.handle_message_limit_settings(callback)
            
        except Exception as e:
            logger.error("💥 Error in message limit settings", error=str(e))
            await callback.answer("❌ Ошибка при загрузке настроек", show_alert=True)
    
    async def cb_ai_set_message_limit(self, callback: CallbackQuery, state: FSMContext):
        """Установка лимита сообщений"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            limit_manager = await self._get_message_limit_manager()
            if not limit_manager:
                await callback.answer("❌ Ошибка инициализации", show_alert=True)
                return
            
            await limit_manager.handle_set_message_limit(callback, state)
            
        except Exception as e:
            logger.error("💥 Error setting message limit", error=str(e))
            await callback.answer("❌ Ошибка при установке лимита", show_alert=True)
    
    async def cb_ai_disable_message_limit(self, callback: CallbackQuery):
        """Отключение лимита сообщений"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            limit_manager = await self._get_message_limit_manager()
            if not limit_manager:
                await callback.answer("❌ Ошибка инициализации", show_alert=True)
                return
            
            await limit_manager.handle_disable_message_limit(callback)
            
        except Exception as e:
            logger.error("💥 Error disabling message limit", error=str(e))
            await callback.answer("❌ Ошибка при отключении лимита", show_alert=True)
    
    async def handle_message_limit_input(self, message: Message, state: FSMContext):
        """Обработка ввода лимита сообщений"""
        if not self._is_owner(message.from_user.id):
            await message.answer("❌ Доступ запрещен")
            return
        
        try:
            limit_manager = await self._get_message_limit_manager()
            if not limit_manager:
                await message.answer("❌ Ошибка инициализации")
                return
            
            is_owner_check = lambda user_id: self._is_owner(user_id)
            await limit_manager.handle_message_limit_input(message, state, is_owner_check)
            
        except Exception as e:
            logger.error("💥 Error handling message limit input", error=str(e))
            await message.answer("❌ Произошла ошибка")
    
    # ===== ✅ НОВОЕ: FSM ОБРАБОТЧИКИ ДЛЯ ИИ =====
    
    async def handle_openai_name_input(self, message: Message, state: FSMContext):
        """Обработка ввода имени OpenAI агента"""
        if not self._is_owner(message.from_user.id):
            await message.answer("❌ Доступ запрещен")
            return
        
        try:
            openai_handler = await self._create_openai_handler()
            if not openai_handler:
                await message.answer("❌ Ошибка создания обработчика")
                return
            
            is_owner_check = lambda user_id: self._is_owner(user_id)
            await openai_handler.handle_name_input(message, state, is_owner_check)
            
            logger.info("✅ OpenAI name input handled", bot_id=self.bot_id)
            
        except Exception as e:
            logger.error("💥 Error handling name input", error=str(e))
            await message.answer("❌ Ошибка при обработке имени")
    
    async def handle_openai_role_input(self, message: Message, state: FSMContext):
        """Обработка ввода роли OpenAI агента"""
        if not self._is_owner(message.from_user.id):
            await message.answer("❌ Доступ запрещен")
            return
        
        try:
            openai_handler = await self._create_openai_handler()
            if not openai_handler:
                await message.answer("❌ Ошибка создания обработчика")
                return
            
            is_owner_check = lambda user_id: self._is_owner(user_id)
            await openai_handler.handle_role_input(message, state, is_owner_check)
            
            logger.info("✅ OpenAI role input handled", bot_id=self.bot_id)
            
        except Exception as e:
            logger.error("💥 Error handling role input", error=str(e))
            await message.answer("❌ Ошибка при обработке роли")
    
    async def handle_agent_name_edit(self, message: Message, state: FSMContext):
        """Обработка редактирования имени агента"""
        if not self._is_owner(message.from_user.id):
            await message.answer("❌ Доступ запрещен")
            return
        
        try:
            openai_handler = await self._create_openai_handler()
            if not openai_handler:
                await message.answer("❌ Ошибка создания обработчика")
                return
            
            is_owner_check = lambda user_id: self._is_owner(user_id)
            await openai_handler.handle_name_edit_input(message, state, is_owner_check)
            
            logger.info("✅ Agent name edit handled", bot_id=self.bot_id)
            
        except Exception as e:
            logger.error("💥 Error handling name edit", error=str(e))
            await message.answer("❌ Ошибка при редактировании имени")
    
    async def handle_agent_prompt_edit(self, message: Message, state: FSMContext):
        """Обработка редактирования промпта агента"""
        if not self._is_owner(message.from_user.id):
            await message.answer("❌ Доступ запрещен")
            return
        
        try:
            openai_handler = await self._create_openai_handler()
            if not openai_handler:
                await message.answer("❌ Ошибка создания обработчика")
                return
            
            is_owner_check = lambda user_id: self._is_owner(user_id)
            await openai_handler.handle_prompt_edit_input(message, state, is_owner_check)
            
            logger.info("✅ Agent prompt edit handled", bot_id=self.bot_id)
            
        except Exception as e:
            logger.error("💥 Error handling prompt edit", error=str(e))
            await message.answer("❌ Ошибка при редактировании промпта")
    
    async def handle_admin_ai_conversation(self, message: Message, state: FSMContext):
        """Обработка тестирования ИИ агента"""
        if not self._is_owner(message.from_user.id):
            await message.answer("❌ Доступ запрещен")
            return
        
        try:
            # Проверяем команды выхода
            if message.text in ['/exit', '/stop', '/cancel']:
                await state.clear()
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🤖 Управление ИИ", callback_data="admin_ai")],
                    [InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_main")]
                ])
                
                await message.answer("🚪 Тестирование ИИ завершено", reply_markup=keyboard)
                return
            
            # Делегируем в AI handler
            ai_handler = await self._get_ai_handler()
            if not ai_handler:
                await message.answer("❌ Ошибка инициализации ИИ")
                return
            
            await ai_handler.handle_admin_ai_conversation(message, state)
            
            logger.info("✅ Admin AI conversation handled", bot_id=self.bot_id)
            
        except Exception as e:
            logger.error("💥 Error in admin AI conversation", error=str(e))
            await message.answer("❌ Ошибка при общении с ИИ")
    
    # ===== СТАТИСТИКА И ТОКЕНЫ =====
    
    async def cb_admin_stats(self, callback: CallbackQuery):
        """Статистика бота"""
        # ✅ НОВОЕ: Проверка доступа владельца
        if self.access_control:
            has_access, status = await self.access_control['check_owner_access']()
            if not has_access:
                await self.access_control['send_access_denied'](callback, status)
                return
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        await self._show_bot_stats(callback)
    
    async def cb_admin_tokens(self, callback: CallbackQuery):
        """Детальная статистика токенов OpenAI"""
        # ✅ НОВОЕ: Проверка доступа владельца
        if self.access_control:
            has_access, status = await self.access_control['check_owner_access']()
            if not has_access:
                await self.access_control['send_access_denied'](callback, status)
                return
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        await self._show_token_stats(callback)
    
    # ===== НАСТРОЙКИ ПОДПИСКИ =====
    
    async def cb_subscription_settings(self, callback: CallbackQuery):
        """✅ ИСПРАВЛЕНО: Упрощенные настройки подписки с fresh data"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        # ✅ СТАТИЧНЫЙ ТЕКСТ (никогда не меняется)
        text = """
🔒 <b>Ограничение доступа к ИИ</b>

<b>Как работает:</b>
• Пользователь жмет "🤖 Позвать ИИ"
• Система проверяет подписку на канал
• Если не подписан - просит подписаться
• Если подписан - запускает ИИ

<b>Настройка:</b>
1. Настройте канал для проверки
2. Включите/выключите проверку
3. При необходимости измените сообщение

<i>Используйте кнопки ниже для управления</i>
"""
        
        # ✅ ИСПРАВЛЕНО: Используем FRESH данные для кнопок
        keyboard = await self._get_subscription_keyboard(force_fresh=True)
        
        await self._safe_edit_message(callback, text, reply_markup=keyboard)
        
        logger.debug("✅ Subscription settings displayed with fresh data", bot_id=self.bot_id)
    
    async def _get_subscription_keyboard(self, force_fresh: bool = False):
        """✅ ИСПРАВЛЕНО: Генерация клавиатуры с опцией fresh data"""
        
        # ✅ Получаем свежие данные при необходимости
        if force_fresh:
            enabled = await self._get_subscription_enabled_fresh()
            channel_info = await self._get_subscription_channel_info_fresh()
        else:
            enabled = await self._get_subscription_enabled()
            channel_info = await self._get_subscription_channel_info()
        
        # Формируем кнопку переключения
        if enabled:
            toggle_button = InlineKeyboardButton(
                text="🔴 Выключить проверку", 
                callback_data="toggle_subscription"
            )
        else:
            toggle_button = InlineKeyboardButton(
                text="🟢 Включить проверку", 
                callback_data="toggle_subscription"
            )
        
        # Кнопка настройки канала (с индикатором состояния)
        if channel_info['channel_id']:
            channel_button_text = "📺 Канал настроен ✅"
        else:
            channel_button_text = "📺 Настроить канал"
        
        channel_button = InlineKeyboardButton(
            text=channel_button_text,
            callback_data="set_subscription_channel"
        )
        
        keyboard_buttons = [
            [toggle_button],
            [channel_button],
            [InlineKeyboardButton(text="✏️ Изменить сообщение", callback_data="edit_subscription_message")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_main")]
        ]
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    async def cb_toggle_subscription(self, callback: CallbackQuery):
        """✅ АГРЕССИВНОЕ переключение подписки с проверкой"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Получаем текущее состояние агрессивным методом
            current_enabled = await self._get_subscription_enabled_fresh()
            new_enabled = not current_enabled
            
            logger.info("🔄 AGGRESSIVE toggle subscription", 
                       bot_id=self.bot_id,
                       current_enabled=current_enabled,
                       new_enabled=new_enabled)
            
            # Обновляем в БД
            result = await self.db.update_subscription_settings(
                self.bot_id,
                enabled=new_enabled
            )
            
            if isinstance(result, dict) and not result.get('success', True):
                await callback.answer("❌ Ошибка при изменении настроек", show_alert=True)
                return
            
            # ✅ КРИТИЧНО: Проверяем что изменение прошло успешно
            verification_success = await self.db.verify_update_success(self.bot_id, new_enabled)
            
            if not verification_success:
                logger.error("💥 Update verification FAILED", 
                            bot_id=self.bot_id,
                            expected=new_enabled)
                await callback.answer("❌ Изменения не сохранились, попробуйте еще раз", show_alert=True)
                return
            
            # Уведомляем пользователя об успехе
            status = "включена" if new_enabled else "выключена"
            await callback.answer(f"✅ Проверка подписки {status}")
            
            logger.info("✅ AGGRESSIVE subscription toggle SUCCESS", 
                       bot_id=self.bot_id,
                       enabled=new_enabled,
                       verified=True)
            
            # Обновляем интерфейс с гарантированно свежими данными
            try:
                new_keyboard = await self._get_subscription_keyboard(force_fresh=True)
                await callback.message.edit_reply_markup(reply_markup=new_keyboard)
                
            except Exception as update_error:
                error_message = str(update_error).lower()
                
                if "message is not modified" in error_message:
                    # Fallback: полное обновление с уникальным контентом
                    from datetime import datetime
                    update_time = datetime.now().strftime("%H:%M:%S")
                    
                    status_indicator = "🟢 Включена" if new_enabled else "🔴 Выключена"
                    
                    text = f"""
🔒 <b>Ограничение доступа к ИИ</b>

<b>Как работает:</b>
• Пользователь жмет "🤖 Позвать ИИ"
• Система проверяет подписку на канал
• Если не подписан - просит подписаться
• Если подписан - запускает ИИ

<b>Настройка:</b>
1. Настройте канал для проверки
2. Включите/выключите проверку
3. При необходимости измените сообщение

<b>Текущий статус:</b> {status_indicator} ✅

<i>Обновлено: {update_time}</i>
"""
                    
                    await self._safe_edit_message(callback, text, reply_markup=new_keyboard)
                else:
                    raise update_error
            
        except Exception as e:
            logger.error("❌ AGGRESSIVE toggle subscription FAILED", 
                        bot_id=self.bot_id,
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            await callback.answer("❌ Ошибка при изменении настроек", show_alert=True)
    
    async def cb_set_subscription_channel(self, callback: CallbackQuery, state: FSMContext):
        """✅ ОБНОВЛЕНО: Настройка канала/группы для проверки подписки"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        await state.set_state(ChannelStates.waiting_for_subscription_channel)
        
        text = """
📺 <b>Настройка канала/группы для проверки</b>

<b>Способы настройки:</b>

<b>1️⃣ Публичный канал/группа:</b>
- Перешлите любое сообщение из канала/группы
- Система автоматически определит все данные

<b>2️⃣ Приватный канал/группа:</b>
- Перешлите сообщение из чата (появится подсказка)
- ИЛИ отправьте ID канала/группы вручную

<b>🔍 Как узнать ID приватного чата:</b>
- Добавьте @userinfobot в канал/группу
- Напишите /id в чате
- Скопируйте ID (начинается с минуса)

<b>Требования:</b>
- Бот должен быть администратором чата
- Для каналов: права на управление каналом
- Для групп: права на просмотр участников

<i>Ожидаю пересланное сообщение или ID...</i>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="admin_subscription")]
        ])
        
        await self._safe_edit_message(callback, text, reply_markup=keyboard)
        
        logger.info("✅ Waiting for forwarded channel/group message", 
                   bot_id=self.bot_id,
                   user_id=callback.from_user.id)
    
    async def handle_forwarded_channel(self, message: Message, state: FSMContext):
        """✅ ОБНОВЛЕНО: Обработка пересланного сообщения из канала/группы + ручной ввод ID"""
        try:
            user_id = message.from_user.id
            
            if not self._is_owner(user_id):
                await message.answer("❌ Доступ запрещен")
                await state.clear()
                return
            
            # ✅ СПОСОБ 1: Проверяем forward_from_chat (публичные каналы/группы)
            if message.forward_from_chat:
                await self._handle_public_chat_forward(message, state)
                return
            
            # ✅ СПОСОБ 2: Проверяем признаки пересланного сообщения
            if message.forward_date or message.forward_sender_name or message.forward_signature:
                await self._handle_private_chat_forward(message, state)
                return
            
            # ✅ СПОСОБ 3: Ручной ввод ID (если ничего не определилось)
            if message.text and (message.text.startswith('-') or message.text.isdigit()):
                await self._handle_manual_chat_id_input(message, state)
                return
            
            # ❌ Не удалось определить
            await message.answer("""
❌ <b>Не удалось определить чат!</b>

<b>Способы настройки:</b>

<b>1️⃣ Публичный канал/группа:</b>
Перешлите любое сообщение из канала/группы

<b>2️⃣ Приватный канал/группа:</b>
Отправьте ID канала/группы вручную

<b>🔍 Как узнать ID приватного чата:</b>
- Добавьте бота @userinfobot в канал/группу
- Напишите /id в чате
- Скопируйте ID (начинается с минуса)
- Отправьте этот ID сюда

<b>Примеры:</b> 
• Канал: -1001234567890
• Группа: -1001234567890
""")
            
        except Exception as e:
            logger.error("❌ Failed to handle forwarded channel", 
                        bot_id=self.bot_id,
                        error=str(e),
                        exc_info=True)
            await message.answer("❌ Ошибка при обработке")
            await state.clear()
    
    async def _handle_public_chat_forward(self, message: Message, state: FSMContext):
        """Обработка публичного канала/группы"""
        try:
            chat = message.forward_from_chat
            
            if chat.type not in ["channel", "group", "supergroup"]:
                await message.answer(f"❌ Неподдерживаемый тип: {chat.type}")
                return
            
            await self._save_chat_config(chat.id, chat.title, chat.username, chat.type, state, message)
            
        except Exception as e:
            logger.error("❌ Failed to handle public chat forward", error=str(e))
            await message.answer("❌ Ошибка при обработке публичного чата")

    async def _handle_private_chat_forward(self, message: Message, state: FSMContext):
        """Обработка приватного канала/группы (forward_from_chat скрыт)"""
        await message.answer("""
⚠️ <b>Обнаружено пересланное сообщение из приватного чата</b>

Telegram скрывает информацию о приватных каналах/группах из соображений безопасности.

<b>Отправьте ID канала/группы вручную:</b>
- Добавьте @userinfobot в канал/группу
- Напишите /id в чате  
- Скопируйте ID (например: -1001234567890)
- Отправьте ID сюда

<i>Ожидаю ID канала/группы...</i>
""")

    async def _handle_manual_chat_id_input(self, message: Message, state: FSMContext):
        """Обработка ручного ввода ID канала/группы"""
        try:
            chat_id = int(message.text)
            
            if chat_id > 0:
                await message.answer("❌ ID канала/группы должен быть отрицательным (начинаться с минуса)")
                return
            
            # Проверяем доступность чата
            try:
                chat_info = await message.bot.get_chat(chat_id)
                
                if chat_info.type not in ["channel", "group", "supergroup"]:
                    await message.answer(f"❌ Неподдерживаемый тип чата: {chat_info.type}")
                    return
                
                # Проверяем права бота
                bot_member = await message.bot.get_chat_member(chat_id, message.bot.id)
                if bot_member.status not in ["administrator", "creator"]:
                    chat_type = "канала" if chat_info.type == "channel" else "группы"
                    await message.answer(f"""
❌ <b>Бот не является администратором {chat_type}!</b>

<b>Что нужно сделать:</b>
1. Добавьте бота в {chat_type.replace('а', 'у')}
2. Дайте ему права администратора
3. Попробуйте снова
""")
                    return
                
                await self._save_chat_config(
                    chat_info.id, 
                    chat_info.title, 
                    chat_info.username,
                    chat_info.type, 
                    state,
                    message
                )
                
            except Exception as e:
                error_msg = str(e).lower()
                if "chat not found" in error_msg:
                    await message.answer("❌ Канал/группа не найден. Убедитесь что бот добавлен в чат.")
                elif "not enough rights" in error_msg:
                    await message.answer("❌ У бота нет прав в канале/группе. Дайте права администратора.")
                else:
                    await message.answer(f"❌ Ошибка доступа: {e}")
                
        except ValueError:
            await message.answer("❌ Неверный формат ID. Пример: -1001234567890")

    async def _save_chat_config(self, chat_id: int, chat_title: str, chat_username: str, chat_type: str, state: FSMContext, message: Message):
        """Сохранение конфигурации чата"""
        try:
            # Сохраняем в БД
            result = await self.db.update_subscription_settings(
                self.bot_id,
                channel_id=chat_id,
                channel_username=chat_username
            )
            
            if isinstance(result, dict) and not result.get('success', True):
                await message.answer("❌ Ошибка при сохранении")
                await state.clear()
                return
            
            # Определяем тип для отображения
            chat_type_names = {
                "channel": "канал",
                "group": "группа", 
                "supergroup": "супергруппа"
            }
            chat_type_display = chat_type_names.get(chat_type, chat_type)
            
            success_text = f"""
✅ <b>{chat_type_display.capitalize()} настроен!</b>

<b>Название:</b> {chat_title}
<b>Тип:</b> {chat_type_display}
<b>ID:</b> <code>{chat_id}</code>
{f'<b>Username:</b> @{chat_username}' if chat_username else '<b>Username:</b> Приватный чат'}

<b>Теперь пользователи должны подписаться на этот {chat_type_display} для доступа к ИИ.</b>
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Включить проверку", callback_data="toggle_subscription")],
                [InlineKeyboardButton(text="⚙️ Настройки", callback_data="admin_subscription")],
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_main")]
            ])
            
            await message.answer(success_text, reply_markup=keyboard)
            await state.clear()
            
            logger.info("✅ Subscription chat configured successfully", 
                       bot_id=self.bot_id,
                       chat_id=chat_id,
                       chat_title=chat_title,
                       chat_type=chat_type,
                       chat_username=chat_username)
                       
        except Exception as e:
            logger.error("❌ Failed to save chat config", error=str(e))
            await message.answer("❌ Ошибка при сохранении конфигурации")
            await state.clear()
    
    async def cb_edit_subscription_message(self, callback: CallbackQuery, state: FSMContext):
        """Редактирование сообщения для неподписанных (заглушка)"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        await callback.answer("🚧 Редактирование сообщения будет добавлено в следующем обновлении", show_alert=True)
    
    # ===== МЕТОДЫ ОТОБРАЖЕНИЯ СТАТИСТИКИ =====
    
    async def _show_bot_stats(self, callback: CallbackQuery):
        """Показать статистику бота"""
        try:
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
            
            await self._safe_edit_message(callback, text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error("Failed to show bot stats", bot_id=self.bot_id, error=str(e))
            await callback.answer("Ошибка при загрузке статистики", show_alert=True)
    
    async def _show_token_stats(self, callback: CallbackQuery):
        """✅ ОБНОВЛЕНО: Показать детальную статистику токенов OpenAI (ВСЕГДА)"""
        try:
            logger.info("📊 Loading token statistics", 
                       user_id=self.owner_user_id,
                       bot_id=self.bot_id)
            
            # ✅ ИСПРАВЛЕНО: TokenManager всегда возвращает актуальные данные
            token_stats = await self._get_token_stats()
            
            logger.debug("💰 Token stats loaded", 
                        has_openai_bots=token_stats['has_openai_bots'],
                        total_used=token_stats['total_used'],
                        bots_count=token_stats['bots_count'])
            
            # ✅ ИЗМЕНЕНО: Убрано условие, всегда показываем детальную статистику
            used_formatted = self._format_number(token_stats['total_used'])
            limit_formatted = self._format_number(token_stats['limit'])
            remaining_formatted = self._format_number(token_stats['remaining'])
            input_formatted = self._format_number(token_stats['input_tokens'])
            output_formatted = self._format_number(token_stats['output_tokens'])
            percentage = self._format_percentage(token_stats['total_used'], token_stats['limit'])
            
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
            
            # ✅ НОВОЕ: Специальный текст если агентов нет
            agents_info = ""
            if not token_stats['has_openai_bots']:
                agents_info = f"\n\n💡 <b>Совет:</b>\nСоздайте ИИ агента в разделе \"🤖 ИИ Агент\" чтобы начать использовать токены"
            
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
⏰ <b>Последнее использование:</b> {last_usage_text}{agents_info}

{Emoji.INFO} <b>Что такое токены?</b>
• Токены - это единицы измерения для OpenAI API
• ~1 токен ≈ 0.75 слова в русском языке
• Входящие: ваши сообщения к ИИ
• Исходящие: ответы ИИ вам

{Emoji.ROCKET} <b>Пополнение токенов:</b>
Обратитесь к администратору для увеличения лимита
"""
            
            keyboard_buttons = [
                [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_tokens")],
                # ✅ ИЗМЕНЕНО: Всегда показываем кнопку пополнения (убрано условие)
                [InlineKeyboardButton(text="💳 Запросить пополнение", callback_data="request_token_topup")],
                [InlineKeyboardButton(text=f"{Emoji.BACK} Главное меню", callback_data="admin_main")]
            ]
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
            
            await self._safe_edit_message(callback, text, reply_markup=keyboard)
            
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
    
    # ===== DEBUG МЕТОДЫ =====
    
    async def debug_owner_message(self, message: Message):
        """Debug метод"""
        user_id = message.from_user.id
        is_owner = self._is_owner(user_id)
        
        config = await self._get_fresh_config()
        ai_status, ai_type = self._get_ai_agent_info(config)
        # ✅ ИСПРАВЛЕНО: TokenManager всегда возвращает актуальные данные
        token_stats = await self._get_token_stats()
        content_agent_status, has_content_agent = await self._get_content_agent_info()
        
        # ✅ ИСПРАВЛЕНО: Проверяем настройки подписки с fresh data
        subscription_enabled = await self._get_subscription_enabled_fresh()
        channel_info = await self._get_subscription_channel_info_fresh()
        
        # ✅ НОВОЕ: Проверяем статистику рассылок
        try:
            broadcast_stats = await self.db.get_mass_broadcast_stats(self.bot_id, days=30)
            broadcasts_sent = broadcast_stats.get('deliveries', {}).get('successful', 0)
        except:
            broadcasts_sent = 0
        
        # ✅ НОВОЕ: Проверяем лимиты сообщений
        try:
            current_limit = await self.db.get_daily_message_limit(self.bot_id)
        except:
            current_limit = 0
        
        from datetime import datetime
        current_time = datetime.now().strftime("%H:%M:%S.%f")
        
        await message.answer(
            f"🔍 <b>Debug Info ({current_time}):</b>\n"
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
            f"Has Agent: {has_content_agent}\n\n"
            f"🔒 <b>Subscription Settings (FRESH):</b>\n"
            f"Enabled: {subscription_enabled} ({'🟢' if subscription_enabled else '🔴'})\n"
            f"Channel ID: {channel_info['channel_id']}\n"
            f"Channel Username: {channel_info['channel_username']}\n"
            f"Has Channel: {bool(channel_info['channel_id'])}\n\n"
            f"📨 <b>Broadcast Stats:</b>\n"
            f"Broadcasts Sent: {broadcasts_sent}\n\n"
            f"📊 <b>Message Limits:</b>\n"
            f"Daily Limit: {current_limit} ({'✅ Enabled' if current_limit > 0 else '❌ Disabled'})\n\n"
            f"🤖 <b>AI Handler Status:</b>\n"
            f"AI Handler Initialized: {self._ai_handler is not None}\n"
            f"Message Limit Manager Initialized: {self._message_limit_manager is not None}\n"
            f"Access Control Enabled: {self.access_control is not None}"
        )


# ===== ФУНКЦИЯ ДЛЯ ВНЕШНЕГО ИСПОЛЬЗОВАНИЯ =====

async def show_mass_broadcast_main_menu(callback: CallbackQuery, bot_id: str, bot_username: str, db):
    """
    Функция для внешнего показа меню массовых рассылок 
    (для использования из других обработчиков)
    """
    try:
        # Получаем статистику
        stats = await db.get_mass_broadcast_stats(bot_id, days=30)
        
        text = f"""
📨 <b>Массовые рассылки @{bot_username}</b>

📊 <b>Статистика за 30 дней:</b>
   Отправлено рассылок: {stats.get('total_broadcasts', 0)}
   Мгновенных: {stats.get('by_type', {}).get('instant', 0)}
   Запланированных: {stats.get('by_type', {}).get('scheduled', 0)}
   
📈 <b>Доставка:</b>
   Успешно доставлено: {stats.get('deliveries', {}).get('successful', 0)}
   Ошибок доставки: {stats.get('deliveries', {}).get('failed', 0)}
   Процент успеха: {stats.get('deliveries', {}).get('success_rate', 0)}%

Выберите тип рассылки:
"""
        
        # Безопасное редактирование сообщения
        try:
            if callback.message.text:
                await callback.message.edit_text(
                    text=text, 
                    reply_markup=AdminKeyboards.mass_broadcast_main_menu(),
                    parse_mode="HTML"
                )
            elif callback.message.caption is not None:
                await callback.message.edit_caption(
                    caption=text, 
                    reply_markup=AdminKeyboards.mass_broadcast_main_menu(),
                    parse_mode="HTML"
                )
            else:
                await callback.message.delete()
                await callback.bot.send_message(
                    chat_id=callback.message.chat.id,
                    text=text,
                    reply_markup=AdminKeyboards.mass_broadcast_main_menu(),
                    parse_mode="HTML"
                )
        except Exception as e:
            logger.warning(f"Failed to edit message safely, using fallback: {e}")
            try:
                await callback.message.delete()
                await callback.bot.send_message(
                    chat_id=callback.message.chat.id,
                    text=text,
                    reply_markup=AdminKeyboards.mass_broadcast_main_menu(),
                    parse_mode="HTML"
                )
            except Exception as fallback_error:
                logger.error(f"Fallback message edit also failed: {fallback_error}")
                await callback.bot.send_message(
                    chat_id=callback.message.chat.id,
                    text=text,
                    reply_markup=AdminKeyboards.mass_broadcast_main_menu(),
                    parse_mode="HTML"
                )
        
        logger.info("✅ Mass broadcast menu displayed successfully", bot_id=bot_id)
        
    except Exception as e:
        logger.error("💥 Failed to show mass broadcast menu", 
                    bot_id=bot_id, error=str(e), exc_info=True)
        await callback.answer("❌ Ошибка при загрузке меню рассылок", show_alert=True)
