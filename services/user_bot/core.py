"""
Основной класс UserBot после рефакторинга
Управление жизненным циклом бота и координация всех компонентов
✅ ОБЪЕДИНЁННЫЙ ПОДХОД: Вся ИИ логика в ai_handlers.py
✅ ЧИСТАЯ АРХИТЕКТУРА: Админ + ИИ в одном месте, события канала отдельно
✅ ДОБАВЛЕНО: Регистрация обработчиков лимитов сообщений
✅ ДОБАВЛЕНО: Контроль доступа владельца бота
✅ ДОБАВЛЕНО: Установка команд бота при старте
"""

import asyncio
import re
from datetime import datetime
from typing import Optional, Dict, Any, TYPE_CHECKING
import structlog
from services.notifications import get_notification_service
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from utils.access_control import check_user_access
from database.managers.user_manager import UserManager

from config import settings
from database import db as database

from .handlers import (
    register_admin_handlers,
    register_settings_handlers,
    register_ai_handlers,
    register_funnel_handlers,
    register_channel_handlers,
    register_content_handlers,
    register_mass_broadcast_handlers,
    register_message_limit_handlers  # ✅ НОВОЕ: Обработчики лимитов сообщений
)
from .formatters import MessageFormatter

if TYPE_CHECKING:
    from services.bot_manager import BotManager

logger = structlog.get_logger()


class UserBot:
    """Основной класс пользовательского бота"""
    
    def __init__(self, config: dict, bot_manager: 'BotManager'):
        """
        Инициализация бота
        
        Args:
            config: Конфигурация бота из БД
            bot_manager: Менеджер ботов
        """
        self.config = config
        self.bot_manager = bot_manager
        self.bot_id = config['bot_id']
        self.token = config['token']
        self.bot_username = config['bot_username']
        self.owner_user_id = config['user_id']
        
        # Debug: Log owner info
        logger.info("UserBot initialized", 
                   bot_id=self.bot_id, 
                   bot_username=self.bot_username,
                   owner_user_id=self.owner_user_id)
        
        # Bot instances
        self.bot: Optional[Bot] = None
        self.dp: Optional[Dispatcher] = None
        self.polling_task: Optional[asyncio.Task] = None
        
        # Status tracking
        self.is_running = False
        self.last_activity: Optional[datetime] = None
        self.error_count = 0
        
        # Message configuration
        self.welcome_message = config.get('welcome_message')
        self.welcome_button_text = config.get('welcome_button_text')
        self.confirmation_message = config.get('confirmation_message')
        self.goodbye_message = config.get('goodbye_message')
        self.goodbye_button_text = config.get('goodbye_button_text')
        self.goodbye_button_url = config.get('goodbye_button_url')
        
        # AI Assistant configuration
        self.ai_assistant_id = config.get('ai_assistant_id')
        self.ai_assistant_settings = config.get('ai_assistant_settings', {})
        
        # Extended statistics
        self.stats = {
            'welcome_sent': 0,
            'welcome_blocked': 0,
            'welcome_buttons_sent': 0,
            'confirmation_sent': 0,
            'confirmation_blocked': 0,
            'goodbye_sent': 0,
            'goodbye_blocked': 0,
            'goodbye_buttons_sent': 0,
            'button_clicks': 0,
            'funnel_starts': 0,
            'total_attempts': 0,
            'join_requests_processed': 0,
            'admin_adds_processed': 0,
            'user_chat_id_available': 0,
            'user_chat_id_missing': 0,
            'admin_sessions': 0
        }
    
    async def check_owner_access(self) -> tuple[bool, dict]:
        """✅ НОВЫЙ: Проверить доступ владельца бота"""
        try:
            return await check_user_access(self.owner_user_id, "user_bot_functions")
        except Exception as e:
            logger.error("Failed to check owner access", 
                        bot_id=self.bot_id, 
                        owner_user_id=self.owner_user_id, 
                        error=str(e))
            return False, {'status': 'error', 'error': str(e)}

    async def send_owner_access_denied(self, message_or_callback, status: dict):
        """✅ НОВЫЙ: Отправить сообщение о блокировке бота"""
        from config import settings, Emoji
        
        if status.get('trial_expired'):
            text = f"""
{Emoji.WARNING} <b>Пробный период владельца бота завершен!</b>

У владельца этого бота (@{self.bot_username}) закончился 3-дневный пробный период Bot Factory.

💎 <b>Что нужно сделать:</b>
- Владелец должен перейти в главный бот Factory
- Оформить подписку AI ADMIN за {settings.robokassa_payment_amount}₽
- После оплаты этот бот заработает автоматически

⏳ <b>Бот будет недоступен до продления подписки владельца.</b>

👤 <b>Сообщите владельцу о необходимости оплаты!</b>
"""
        elif status.get('status') == 'expired':
            text = f"""
{Emoji.WARNING} <b>Подписка владельца бота истекла!</b>

У владельца этого бота (@{self.bot_username}) истекла подписка Bot Factory.

💎 <b>Что нужно сделать:</b>
- Владелец должен продлить подписку AI ADMIN
- Стоимость: {settings.robokassa_payment_amount}₽ за 30 дней
- После оплаты все функции восстановятся

⏳ <b>Бот временно заблокирован до оплаты.</b>

👤 <b>Обратитесь к владельцу для продления подписки!</b>
"""
        else:
            text = f"""
{Emoji.ERROR} <b>Бот временно недоступен</b>

Владелец бота должен обратиться в техническую поддержку.

⏳ Попробуйте позже.
"""
        
        try:
            if hasattr(message_or_callback, 'message'):
                # Callback query
                await message_or_callback.message.answer(text)
            else:
                # Regular message  
                await message_or_callback.answer(text)
                
            logger.info("Access denied message sent to user", 
                       bot_id=self.bot_id,
                       user_id=getattr(message_or_callback, 'from_user', {}).get('id'),
                       reason=status.get('status'))
                       
        except Exception as e:
            logger.error("Failed to send access denied message", 
                        bot_id=self.bot_id, 
                        error=str(e))
    
    def has_ai_agent(self) -> bool:
        """Проверка наличия настроенного ИИ агента"""
        return bool(self.ai_assistant_id)
    
    async def start(self):
        """Запуск бота"""
        try:
            logger.info("Starting user bot with UNIFIED AI APPROACH", 
                       bot_id=self.bot_id, 
                       bot_username=self.bot_username,
                       owner_user_id=self.owner_user_id)
            
            # Создаем экземпляр бота
            self.bot = Bot(
                token=self.token,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML)
            )
            
            # Проверяем токен
            bot_info = await self.bot.get_me()
            if bot_info.username != self.bot_username:
                raise ValueError(f"Bot username mismatch: expected {self.bot_username}, got {bot_info.username}")
            
            logger.info("Bot token verified", 
                       bot_id=self.bot_id, 
                       verified_username=bot_info.username)
            
            # ✅ НОВОЕ: Устанавливаем команды бота
            await self.bot.set_my_commands([
                BotCommand(command="start", description="Начать работу")
            ])
            
            logger.info("Bot commands set", bot_id=self.bot_id)
            
            # Создаем диспетчер с FSM storage
            self.dp = Dispatcher(storage=MemoryStorage())
            
            # ✅ КРИТИЧНО: Регистрируем обработчики с объединенным подходом ИИ
            self._setup_handlers()
            
            # Инициализируем воронку
            await self._initialize_funnel()
            
            # Запускаем polling
            self.polling_task = asyncio.create_task(self._start_polling())
            self.is_running = True
            self.last_activity = datetime.now()
            
            logger.info(
                "✅ User bot started with UNIFIED AI APPROACH", 
                bot_id=self.bot_id,
                bot_username=self.bot_username,
                owner_user_id=self.owner_user_id,
                has_welcome_button=bool(self.welcome_button_text),
                has_confirmation=bool(self.confirmation_message),
                has_goodbye_button=bool(self.goodbye_button_text),
                has_ai_agent=self.has_ai_agent(),
                ai_unified=True,
                channel_events_only=True,
                message_limits_enabled=True,  # ✅ НОВОЕ
                owner_access_control_enabled=True,  # ✅ НОВОЕ
                bot_commands_set=True  # ✅ НОВОЕ
            )
            
        except Exception as e:
            logger.error(
                "Failed to start user bot", 
                bot_id=self.bot_id,
                error=str(e),
                exc_info=True
            )
            await self._cleanup()
            raise
    
    async def stop(self):
        """Остановка бота"""
        logger.info("Stopping user bot", bot_id=self.bot_id)
        
        self.is_running = False
        
        # Отменяем задачу polling
        if self.polling_task:
            self.polling_task.cancel()
            try:
                await self.polling_task
            except asyncio.CancelledError:
                pass
        
        # Очистка
        await self._cleanup()
        
        logger.info("User bot stopped", bot_id=self.bot_id)
    
    async def _cleanup(self):
        """Очистка ресурсов бота с правильной очисткой роутеров"""
        # Очищаем роутеры из диспетчера
        if self.dp:
            try:
                # Останавливаем диспетчер если запущен
                if hasattr(self.dp, '_running') and getattr(self.dp, '_running', False):
                    await self.dp.stop_polling()
                
                # Очищаем роутеры для предотвращения ошибки "Router is already attached"
                if hasattr(self.dp, '_routers'):
                    for router in self.dp._routers:
                        if hasattr(router, 'parent_router'):
                            router.parent_router = None
                    self.dp._routers.clear()
                    
                logger.info("Dispatcher routers cleared", bot_id=self.bot_id)
            except Exception as e:
                logger.warning("Error clearing dispatcher routers", bot_id=self.bot_id, error=str(e))
        
        if self.bot:
            try:
                await self.bot.session.close()
            except Exception as e:
                logger.error("Error closing bot session", bot_id=self.bot_id, error=str(e))
        
        self.bot = None
        self.dp = None
        self.polling_task = None
    
    async def _initialize_funnel(self):
        """Инициализация воронки для бота"""
        try:
            from services.funnel_manager import funnel_manager
            success = await funnel_manager.initialize_bot_funnel(self.bot_id)
            logger.info("Funnel initialization", bot_id=self.bot_id, success=success)
        except Exception as e:
            logger.error("Failed to initialize funnel", bot_id=self.bot_id, error=str(e))
    
    def _setup_handlers(self):
        """✅ ОБНОВЛЕНО: Setup handlers with OWNER ACCESS CONTROL + UNIFIED AI APPROACH + MESSAGE LIMITS"""
        logger.info("🎯 Setting up handlers with OWNER ACCESS CONTROL + UNIFIED AI APPROACH + MESSAGE LIMITS", bot_id=self.bot_id)
        
        try:
            # Импортируем менеджеры
            from services.funnel_manager import funnel_manager
            from services.ai_assistant import ai_client
            
            # Передаем полную конфигурацию бота
            bot_config = {
                'bot': self.bot,
                'bot_id': self.bot_id,
                'bot_username': self.bot_username,
                'owner_user_id': self.owner_user_id,
                'welcome_message': self.welcome_message,
                'welcome_button_text': self.welcome_button_text,
                'confirmation_message': self.confirmation_message,
                'goodbye_message': self.goodbye_message,
                'goodbye_button_text': self.goodbye_button_text,
                'goodbye_button_url': self.goodbye_button_url,
                'ai_assistant_id': self.ai_assistant_id,
                'ai_assistant_settings': self.ai_assistant_settings,
                'stats': self.stats,
                'bot_manager': self.bot_manager
            }
            
            # ✅ НОВОЕ: Функции проверки доступа владельца
            access_control = {
                'check_owner_access': self.check_owner_access,
                'send_access_denied': self.send_owner_access_denied
            }
            
            # Подготавливаем зависимости для обработчиков
            deps = {
                'db': database,
                'bot_config': bot_config,
                'funnel_manager': funnel_manager,
                'ai_assistant': ai_client if self.has_ai_agent() else None,
                'formatter': MessageFormatter(),
                'user_bot': self,
                'access_control': access_control  # ✅ НОВОЕ: Передаем контроль доступа
            }
            
            # ===== ✅ ОБЪЕДИНЁННЫЙ ПОРЯДОК РЕГИСТРАЦИИ С КОНТРОЛЕМ ДОСТУПА =====
            
            # 🏆 1. АДМИН ОБРАБОТЧИКИ - ВЫСШИЙ ПРИОРИТЕТ (С КОНТРОЛЕМ ДОСТУПА)
            logger.info("1️⃣ Registering ADMIN handlers with OWNER ACCESS CONTROL (HIGHEST PRIORITY)", bot_id=self.bot_id)
            register_admin_handlers(self.dp, **deps)
            
            # 🤖 2. ВСЯ ИИ ЛОГИКА - АДМИН + ПОЛЬЗОВАТЕЛИ (ОБЪЕДИНЕНО!) (С КОНТРОЛЕМ ДОСТУПА)
            logger.info("2️⃣ Registering UNIFIED AI handlers with OWNER ACCESS CONTROL (ADMIN + USERS IN ONE)", bot_id=self.bot_id)
            register_ai_handlers(self.dp, **deps)
            
            # 📊 3. ЛИМИТЫ СООБЩЕНИЙ (С КОНТРОЛЕМ ДОСТУПА)
            logger.info("3️⃣ Registering MESSAGE LIMIT handlers with OWNER ACCESS CONTROL", bot_id=self.bot_id)
            register_message_limit_handlers(self.dp, **deps)
            
            # 📝 4. КОНТЕНТ ОБРАБОТЧИКИ (С КОНТРОЛЕМ ДОСТУПА)
            logger.info("4️⃣ Registering content handlers with OWNER ACCESS CONTROL", bot_id=self.bot_id)
            register_content_handlers(self.dp, **deps)
            
            # ⚙️ 5. НАСТРОЙКИ ОБРАБОТЧИКИ (С КОНТРОЛЕМ ДОСТУПА)
            logger.info("5️⃣ Registering settings handlers with OWNER ACCESS CONTROL", bot_id=self.bot_id)
            register_settings_handlers(self.dp, **deps)
            
            # 📊 6. ВОРОНКА ОБРАБОТЧИКИ (С КОНТРОЛЕМ ДОСТУПА)
            logger.info("6️⃣ Registering funnel handlers with OWNER ACCESS CONTROL", bot_id=self.bot_id)
            register_funnel_handlers(self.dp, **deps)
            
            # 📨 7. МАССОВЫЕ РАССЫЛКИ (С КОНТРОЛЕМ ДОСТУПА)
            logger.info("7️⃣ Registering mass broadcast handlers with OWNER ACCESS CONTROL", bot_id=self.bot_id)
            register_mass_broadcast_handlers(self.dp, **deps)
            
            # 🎪 8. СОБЫТИЯ КАНАЛА - ТОЛЬКО СОБЫТИЯ (БЕЗ ИИ ЛОГИКИ!) (С КОНТРОЛЕМ ДОСТУПА)
            logger.info("8️⃣ Registering channel handlers with OWNER ACCESS CONTROL (EVENTS ONLY - NO AI LOGIC)", bot_id=self.bot_id)
            register_channel_handlers(self.dp, **deps)
            
            logger.info("✅ ALL HANDLERS REGISTERED WITH OWNER ACCESS CONTROL + UNIFIED AI APPROACH + MESSAGE LIMITS!", 
                       bot_id=self.bot_id,
                       owner_user_id=self.owner_user_id,
                       total_handlers=8,
                       access_control_enabled=True,  # ✅ НОВОЕ
                       admin_first=True,
                       ai_unified_second=True,
                       message_limits_third=True,
                       channel_events_last=True,
                       architecture="UNIFIED_AI_WITH_ACCESS_CONTROL")
            
        except Exception as e:
            logger.error("💥 CRITICAL: Failed to setup unified handlers with owner access control", 
                        bot_id=self.bot_id, 
                        owner_user_id=self.owner_user_id,
                        error=str(e), 
                        exc_info=True)
            raise
    
    async def _start_polling(self):
        """Запуск polling с обработкой ошибок"""
        retry_count = 0
        max_retries = 5
        
        while self.is_running and retry_count < max_retries:
            try:
                logger.info("Starting polling", bot_id=self.bot_id)
                await self.dp.start_polling(
                    self.bot, 
                    handle_signals=False,
                    allowed_updates=["message", "chat_member", "chat_join_request", "callback_query"]
                )
                break
                
            except asyncio.CancelledError:
                break
                
            except Exception as e:
                retry_count += 1
                self.error_count += 1
                
                logger.error(
                    "Polling error", 
                    bot_id=self.bot_id,
                    error=str(e),
                    retry_count=retry_count
                )
                
                if retry_count < max_retries:
                    await asyncio.sleep(min(retry_count * 5, 30))
                else:
                    logger.error("Max retries exceeded", bot_id=self.bot_id)
                    self.is_running = False
                    await database.update_bot_status(self.bot_id, "error", False)
    
    # =====================================================
    # КЛЮЧЕВЫЕ МЕТОДЫ ДЛЯ РАБОТЫ С ЗАДЕРЖКАМИ И СООБЩЕНИЯМИ
    # =====================================================
    
    def _parse_delay(self, delay_text: str) -> Optional[float]:
        """
        Парсинг текста задержки в часы
        
        Поддерживаемые форматы:
        - "5m", "30min", "45 minutes" -> в часы
        - "2h", "3 hours" -> часы
        - "1d", "2 days" -> в часы (24h = 1d)
        - "1w", "2 weeks" -> в часы (168h = 1w)
        - Просто число -> интерпретируется как часы
        
        Args:
            delay_text: Текст с описанием задержки
            
        Returns:
            float: Количество часов или None если не удалось распарсить
        """
        if not delay_text:
            return None
        
        delay_text = delay_text.strip().lower()
        
        # Регулярные выражения для разных форматов
        patterns = [
            # Минуты: 5m, 30min, 45 minutes
            (r'(\d+(?:\.\d+)?)\s*(?:m|min|minutes?)', lambda x: float(x) / 60),
            # Часы: 2h, 3 hours
            (r'(\d+(?:\.\d+)?)\s*(?:h|hours?)', lambda x: float(x)),
            # Дни: 1d, 2 days
            (r'(\d+(?:\.\d+)?)\s*(?:d|days?)', lambda x: float(x) * 24),
            # Недели: 1w, 2 weeks
            (r'(\d+(?:\.\d+)?)\s*(?:w|weeks?)', lambda x: float(x) * 168),
            # Просто число (интерпретируется как часы)
            (r'^(\d+(?:\.\d+)?)$', lambda x: float(x))
        ]
        
        for pattern, converter in patterns:
            match = re.match(pattern, delay_text)
            if match:
                try:
                    value = match.group(1)
                    hours = converter(value)
                    # Ограничиваем разумными пределами
                    if 0 <= hours <= 8760:  # Максимум год
                        return hours
                except (ValueError, IndexError):
                    continue
        
        logger.warning("Could not parse delay", delay_text=delay_text, bot_id=self.bot_id)
        return None
    
    def _format_delay(self, hours: float) -> str:
        """
        Форматирование часов задержки в читаемый текст
        
        Args:
            hours: Количество часов
            
        Returns:
            str: Читаемое представление задержки
        """
        if hours <= 0:
            return "немедленно"
        
        # Если меньше часа - показываем в минутах
        if hours < 1:
            minutes = int(hours * 60)
            if minutes == 1:
                return "1 минута"
            elif minutes < 5:
                return f"{minutes} минуты"
            else:
                return f"{minutes} минут"
        
        # Если меньше суток - показываем в часах
        elif hours < 24:
            if hours == 1:
                return "1 час"
            elif hours < 5:
                return f"{int(hours)} часа"
            else:
                return f"{int(hours)} часов"
        
        # Если меньше недели - показываем в днях
        elif hours < 168:  # 7 * 24
            days = int(hours / 24)
            if days == 1:
                return "1 день"
            elif days < 5:
                return f"{days} дня"
            else:
                return f"{days} дней"
        
        # Если больше недели - показываем в неделях
        else:
            weeks = int(hours / 168)
            if weeks == 1:
                return "1 неделя"
            elif weeks < 5:
                return f"{weeks} недели"
            else:
                return f"{weeks} недель"
    
    def _format_message(self, template: str, user) -> str:
        """
        Форматирование шаблона сообщения с переменными пользователя
        
        Поддерживаемые переменные:
        - {first_name} - имя пользователя
        - {last_name} - фамилия пользователя
        - {full_name} - полное имя
        - {username} - username пользователя (с @)
        - {user_id} - ID пользователя
        - {mention} - упоминание пользователя
        
        Args:
            template: Шаблон сообщения с переменными
            user: Объект пользователя из Telegram
            
        Returns:
            str: Отформатированное сообщение
        """
        if not template:
            return ""
        
        try:
            # Получаем данные пользователя
            first_name = getattr(user, 'first_name', '') or ''
            last_name = getattr(user, 'last_name', '') or ''
            username = getattr(user, 'username', '') or ''
            user_id = getattr(user, 'id', 0)
            
            # Формируем переменные для замены
            variables = {
                'first_name': first_name,
                'last_name': last_name,
                'full_name': f"{first_name} {last_name}".strip() or first_name,
                'username': f"@{username}" if username else '',
                'user_id': str(user_id),
                'mention': f'<a href="tg://user?id={user_id}">{first_name}</a>' if first_name else f"User {user_id}"
            }
            
            # Заменяем переменные в шаблоне
            formatted_message = template
            for var_name, var_value in variables.items():
                # Поддерживаем разные форматы: {var}, {{var}}, $var
                formatted_message = formatted_message.replace(f"{{{var_name}}}", var_value)
                formatted_message = formatted_message.replace(f"{{{{{var_name}}}}}", var_value)
                formatted_message = formatted_message.replace(f"${var_name}", var_value)
            
            return formatted_message
            
        except Exception as e:
            logger.error("Error formatting message", 
                        template=template, 
                        user_id=getattr(user, 'id', None),
                        error=str(e),
                        bot_id=self.bot_id)
            return template  # Возвращаем оригинальный шаблон в случае ошибки
    
    # =====================================================
    # МЕТОДЫ ДЛЯ ОБНОВЛЕНИЯ КОНФИГУРАЦИИ
    # =====================================================
    
    async def update_welcome_settings(self, **kwargs):
        """Обновление настроек приветствия"""
        if 'welcome_message' in kwargs:
            self.welcome_message = kwargs['welcome_message']
        if 'welcome_button_text' in kwargs:
            self.welcome_button_text = kwargs['welcome_button_text']
        if 'confirmation_message' in kwargs:
            self.confirmation_message = kwargs['confirmation_message']
        
        logger.info("Welcome settings updated in UserBot", bot_id=self.bot_id)
    
    async def update_goodbye_settings(self, **kwargs):
        """Обновление настроек прощания"""
        if 'goodbye_message' in kwargs:
            self.goodbye_message = kwargs['goodbye_message']
        if 'goodbye_button_text' in kwargs:
            self.goodbye_button_text = kwargs['goodbye_button_text']
        if 'goodbye_button_url' in kwargs:
            self.goodbye_button_url = kwargs['goodbye_button_url']
        
        logger.info("Goodbye settings updated in UserBot", bot_id=self.bot_id)
    
    async def update_ai_settings(self, **kwargs):
        """Обновление настроек ИИ"""
        if 'ai_assistant_id' in kwargs:
            self.ai_assistant_id = kwargs['ai_assistant_id']
        if 'ai_assistant_settings' in kwargs:
            self.ai_assistant_settings = kwargs['ai_assistant_settings']
        
        logger.info("AI settings updated in UserBot", bot_id=self.bot_id)
    
    # =====================================================
    # PUBLIC API МЕТОДЫ
    # =====================================================
    
    def get_message_stats(self) -> dict:
        """Получить статистику сообщений"""
        return {
            **self.stats,
            'success_rate': self._get_success_rate(),
            'blocked_rate': self._get_blocked_rate()
        }
    
    def get_detailed_stats(self) -> dict:
        """Получить детальную статистику"""
        return {
            **self.get_message_stats(),
            'bot_info': {
                'bot_id': self.bot_id,
                'bot_username': self.bot_username,
                'owner_user_id': self.owner_user_id,
                'is_running': self.is_running,
                'error_count': self.error_count,
                'last_activity': self.last_activity.isoformat() if self.last_activity else None
            },
            'config': {
                'has_welcome_message': bool(self.welcome_message),
                'has_welcome_button': bool(self.welcome_button_text),
                'has_confirmation_message': bool(self.confirmation_message),
                'has_goodbye_message': bool(self.goodbye_message),
                'has_goodbye_button': bool(self.goodbye_button_text and self.goodbye_button_url),
                'has_ai_agent': self.has_ai_agent()
            }
        }
    
    def update_config(self, new_config: dict):
        """Обновление конфигурации бота"""
        self.config = new_config
        self.welcome_message = new_config.get('welcome_message')
        self.welcome_button_text = new_config.get('welcome_button_text')
        self.confirmation_message = new_config.get('confirmation_message')
        self.goodbye_message = new_config.get('goodbye_message')
        self.goodbye_button_text = new_config.get('goodbye_button_text')
        self.goodbye_button_url = new_config.get('goodbye_button_url')
        
        # AI settings
        self.ai_assistant_id = new_config.get('ai_assistant_id')
        self.ai_assistant_settings = new_config.get('ai_assistant_settings', {})
        
        logger.info("Bot config updated", bot_id=self.bot_id)
    
    # =====================================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # =====================================================
    
    def _get_success_rate(self) -> float:
        """Вычисление процента успеха"""
        if self.stats['total_attempts'] == 0:
            return 0.0
        
        successful = (self.stats['welcome_sent'] + 
                     self.stats['goodbye_sent'] + 
                     self.stats['confirmation_sent'])
        return (successful / self.stats['total_attempts']) * 100
    
    def _get_blocked_rate(self) -> float:
        """Вычисление процента блокировок"""
        if self.stats['total_attempts'] == 0:
            return 0.0
        
        blocked = (self.stats['welcome_blocked'] + 
                  self.stats['goodbye_blocked'] + 
                  self.stats.get('confirmation_blocked', 0))
        return (blocked / self.stats['total_attempts']) * 100
