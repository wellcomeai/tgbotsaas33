import asyncio
import uuid
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse, parse_qs

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, 
    InlineKeyboardButton, BotCommand
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import structlog

from config import settings, Emoji, Messages
from database import db
from services.payments.robokassa_service import robokassa_service
from services.payments.subscription_manager import subscription_manager


logger = structlog.get_logger()


def row_to_dict(row):
    """✅ НОВОЕ: Convert database Row object to dict safely"""
    if row is None:
        return None
    
    if hasattr(row, '_asdict'):  # namedtuple
        return row._asdict()
    elif hasattr(row, '_mapping'):  # SQLAlchemy Row
        return dict(row._mapping)
    elif hasattr(row, 'keys'):  # Row with keys() method
        return {key: row[key] for key in row.keys()}
    elif isinstance(row, dict):  # Already a dict
        return row
    else:
        # Fallback - try to convert to dict
        try:
            return dict(row)
        except:
            logger.error("Failed to convert row to dict", row_type=type(row).__name__)
            return None


class BotCreationStates(StatesGroup):
    waiting_for_token = State()


class MasterBot:
    def __init__(self, bot_manager=None):
        self.bot = Bot(
            token=settings.master_bot_token, 
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        self.dp = Dispatcher(storage=MemoryStorage())
        self.bot_manager = bot_manager
        
        # ✅ НОВОЕ: Инициализируем платежные сервисы
        self.robokassa_service = robokassa_service
        self.subscription_manager = subscription_manager
        
        self._setup_handlers()
        
        logger.info("MasterBot initialized with payment integration",
                   robokassa_test_mode=settings.robokassa_test_mode)
    
    def _setup_handlers(self):
        """✅ ОБНОВЛЕНО: Setup handlers with payment callbacks"""
        # Basic commands
        self.dp.message.register(self.cmd_start, CommandStart())
        self.dp.message.register(self.cmd_help, Command("help"))
        
        # Main menu callbacks
        self.dp.callback_query.register(self.cb_create_bot, F.data == "create_bot")
        self.dp.callback_query.register(self.cb_my_bots, F.data == "my_bots")
        self.dp.callback_query.register(self.cb_pricing, F.data == "pricing")
        self.dp.callback_query.register(self.cb_how_to_create, F.data == "how_to_create")
        self.dp.callback_query.register(self.cb_back_to_main, F.data == "back_to_main")
        
        # Pricing callbacks
        self.dp.callback_query.register(self.cb_pricing_plan, F.data.startswith("pricing_"))
        
        # ✅ НОВОЕ: Добавляем обработчики платежей
        self.dp.callback_query.register(
            self.cb_check_payment, 
            F.data.startswith("check_payment_")
        )
        
        # Bot management callbacks
        self.dp.callback_query.register(self.cb_bot_details, F.data.startswith("bot_"))
        self.dp.callback_query.register(self.cb_bot_manage, F.data.startswith("manage_"))
        
        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Постоянная регистрация обработчика удаления
        self.dp.callback_query.register(
            self._confirm_delete_bot, 
            F.data.startswith("confirm_delete_")
        )
        
        # Token input handler
        self.dp.message.register(
            self.handle_token_input, 
            BotCreationStates.waiting_for_token
        )
        
        logger.info("Payment handlers registered successfully")
    
    async def set_commands(self):
        """Set bot commands"""
        commands = [
            BotCommand(command="start", description="🏭 Главное меню"),
            BotCommand(command="help", description="❓ Помощь"),
        ]
        await self.bot.set_my_commands(commands)
    
    def get_main_keyboard(self) -> InlineKeyboardMarkup:
        """Main menu keyboard"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{Emoji.PLUS} Создать бота", 
                    callback_data="create_bot"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{Emoji.LIST} Мои боты", 
                    callback_data="my_bots"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"💎 Оплатить тариф", 
                    callback_data="pricing"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{Emoji.HELP} Как создать бота?", 
                    callback_data="how_to_create"
                )
            ]
        ])
    
    def get_pricing_keyboard(self) -> InlineKeyboardMarkup:
        """Pricing plans keyboard"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📅 1 месяц — 299 ₽",
                    callback_data="pricing_1m"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📅 3 месяца — 749 ₽ (экономия 150₽)",
                    callback_data="pricing_3m"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📅 6 месяцев — 1,499 ₽ (экономия 295₽)",
                    callback_data="pricing_6m"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📅 12 месяцев — 2,490 ₽ (экономия 1,098₽)",
                    callback_data="pricing_12m"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{Emoji.BACK} Назад", 
                    callback_data="back_to_main"
                )
            ]
        ])
    
    def get_back_keyboard(self) -> InlineKeyboardMarkup:
        """Back to main menu keyboard"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{Emoji.BACK} Назад", 
                    callback_data="back_to_main"
                )
            ]
        ])
    
    def get_bot_info_keyboard(self, bot) -> InlineKeyboardMarkup:
        """Bot info keyboard with link to bot's admin panel"""
        keyboard = [
            [
                InlineKeyboardButton(
                    text=f"{Emoji.SETTINGS} Настроить бота",
                    callback_data=f"manage_configure_{bot.bot_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{Emoji.CHART} Краткая статистика", 
                    callback_data=f"manage_stats_{bot.bot_id}"
                )
            ]
        ]
        
        # Add restart button if bot has errors
        if not bot.is_running:
            keyboard.append([
                InlineKeyboardButton(
                    text=f"{Emoji.RESTART} Перезапустить бота",
                    callback_data=f"manage_restart_{bot.bot_id}"
                )
            ])
        
        keyboard.extend([
            [
                InlineKeyboardButton(
                    text=f"{Emoji.DELETE} Удалить бота",
                    callback_data=f"manage_delete_{bot.bot_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{Emoji.BACK} К списку ботов", 
                    callback_data="my_bots"
                )
            ]
        ])
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    # ✅ BASIC COMMAND HANDLERS
    
    async def cmd_start(self, message: Message, state: FSMContext):
        """✅ ОБНОВЛЕНО: Start command с проверкой подписки"""
        await state.clear()
        
        # Save user to database WITH token limit initialization
        user_data = {
            "id": message.from_user.id,
            "username": message.from_user.username,
            "first_name": message.from_user.first_name,
            "last_name": message.from_user.last_name
        }
        
        try:
            # ✅ НОВОЕ: Создаем пользователя с токеновым лимитом
            await db.create_or_update_user_with_tokens(
                user_data=user_data,
                admin_chat_id=message.chat.id  # ← Для уведомлений о токенах
            )
            logger.info("✅ User registered with token limit", 
                       user_id=message.from_user.id,
                       admin_chat_id=message.chat.id,
                       username=message.from_user.username)
        except Exception as e:
            logger.error("💥 Failed to register user with tokens", 
                        user_id=message.from_user.id,
                        error=str(e),
                        error_type=type(e).__name__)
            # Fallback к старому методу если новый не работает
            try:
                await db.create_or_update_user(user_data)
                logger.info("⚠️ Fallback: User registered without token limit")
            except Exception as fallback_error:
                logger.error("💥 Fallback registration also failed", error=str(fallback_error))
        
        # ✅ НОВОЕ: Проверяем и показываем статус подписки
        try:
            limits = await self.subscription_manager.check_user_limits(message.from_user.id)
            limits = row_to_dict(limits) if limits else {}
            
            if limits.get('is_pro'):
                # Пользователь имеет Pro подписку
                subscription_info = f"""

💎 <b>У вас активна Pro подписка!</b>
📅 Действует до: {limits.get('subscription_end').strftime('%d.%m.%Y') if limits.get('subscription_end') else 'Неизвестно'}
✅ Безлимитные возможности активированы
"""
            else:
                # Бесплатный план
                subscription_info = f"""

📋 <b>Текущий план:</b> Бесплатный
🤖 Лимит ботов: {limits.get('max_bots', 5)}
👥 Лимит подписчиков: {limits.get('max_subscribers', 100)} на бота

💎 Обновитесь до Pro для снятия лимитов!
"""
            
            welcome_message = Messages.WELCOME + subscription_info
            
        except Exception as e:
            logger.error("Failed to check subscription in start command", error=str(e))
            welcome_message = Messages.WELCOME
        
        await message.answer(
            welcome_message,
            reply_markup=self.get_main_keyboard()
        )
    
    async def cmd_help(self, message: Message):
        """Help command handler"""
        help_text = f"""
{Emoji.INFO} <b>Помощь по Bot Factory</b>

{Emoji.FACTORY} <b>Основные функции:</b>
- Создание ботов для Telegram каналов
- Безлимитные воронки продаж с детальной статистикой
- Массовые рассылки с аналитикой  
- Автоматическое управление участниками
- Настройка приветственных сообщений с кнопками
- Сообщения подтверждения и прощания
- ИИ агенты на базе OpenAI GPT-4o

{Emoji.ROCKET} <b>Как управлять ботом:</b>
1. Создайте бота здесь в Bot Factory
2. Перейдите в админ-панель созданного бота
3. Напишите вашему боту команду /start
4. Настраивайте сообщения, воронки и статистику

{Emoji.NEW} <b>Новинка:</b> Каждый бот имеет собственную админ-панель с ИИ агентами!

💰 <b>Токены OpenAI:</b> Каждый пользователь получает 500,000 бесплатных токенов для ИИ агентов

{Emoji.HELP} Нужна помощь? Напишите @support
"""
        
        await message.answer(help_text, reply_markup=self.get_back_keyboard())
    
    # ✅ MAIN MENU CALLBACKS
    
    async def cb_create_bot(self, callback: CallbackQuery, state: FSMContext):
        """Create bot callback"""
        await callback.answer()
        
        # Check user's bot limit
        user_bots = await db.get_user_bots(callback.from_user.id)
        if len(user_bots) >= settings.max_bots_per_user:
            await callback.message.edit_text(
                f"{Emoji.WARNING} <b>Лимит ботов превышен</b>\n\n"
                f"На бесплатном тарифе можно создать до {settings.max_bots_per_user} ботов.\n"
                f"Обновитесь до Pro для снятия лимитов!",
                reply_markup=self.get_back_keyboard()
            )
            return
        
        await state.set_state(BotCreationStates.waiting_for_token)
        
        text = f"""
{Emoji.ROBOT} <b>Создание нового бота</b>

{Messages.HOW_TO_CREATE_BOT}

💰 <b>Бонус:</b> При первом запуске вы получили 500,000 токенов для ИИ агентов OpenAI!

{Emoji.ROCKET} <b>Отправьте токен бота:</b>
"""
        
        await callback.message.edit_text(
            text,
            reply_markup=self.get_back_keyboard()
        )
    
    async def cb_my_bots(self, callback: CallbackQuery):
        """My bots callback"""
        await callback.answer()
        
        user_bots = await db.get_user_bots(callback.from_user.id)
        
        if not user_bots:
            await callback.message.edit_text(
                Messages.NO_BOTS_YET,
                reply_markup=self.get_main_keyboard()
            )
            return
        
        # Create bots list
        text = f"{Emoji.LIST} <b>Ваши боты ({len(user_bots)}):</b>\n\n"
        
        keyboard = []
        for bot in user_bots:
            status_emoji = Emoji.SUCCESS if bot.is_running else Emoji.ERROR
            text += f"{status_emoji} <b>@{bot.bot_username}</b>\n"
            text += f"   Статус: {'Активен' if bot.is_running else 'Остановлен'}\n"
            text += f"   Подписчиков: {bot.total_subscribers}\n"
            
            # Show configuration status
            config_status = []
            if bot.welcome_message:
                config_status.append("👋")
            if bot.welcome_button_text:
                config_status.append("🔘")
            if bot.goodbye_message:
                config_status.append("👋💫")
            # ✅ НОВОЕ: Показываем статус ИИ агента
            if bot.ai_assistant_enabled and bot.ai_assistant_type:
                if bot.ai_assistant_type == 'openai':
                    config_status.append("🎨")
                else:
                    config_status.append("🌐")
            
            if config_status:
                text += f"   Настроено: {' '.join(config_status)}\n"
            else:
                text += f"   {Emoji.WARNING} Требует настройки\n"
            
            text += "\n"
            
            keyboard.append([
                InlineKeyboardButton(
                    text=f"🔧 @{bot.bot_username}",
                    callback_data=f"bot_{bot.bot_id}"
                )
            ])
        
        keyboard.append([
            InlineKeyboardButton(
                text=f"{Emoji.PLUS} Создать нового",
                callback_data="create_bot"
            )
        ])
        keyboard.append([
            InlineKeyboardButton(
                text=f"{Emoji.BACK} Главное меню",
                callback_data="back_to_main"
            )
        ])
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
    
    async def cb_pricing(self, callback: CallbackQuery):
        """✅ ОБНОВЛЕНО: Pricing plans callback с проверкой подписки"""
        await callback.answer()
        
        # Проверяем текущую подписку пользователя
        current_subscription_raw = await self.subscription_manager.get_active_subscription(
            callback.from_user.id
        )
        current_subscription = row_to_dict(current_subscription_raw) if current_subscription_raw else None
        
        if current_subscription:
            # У пользователя уже есть активная подписка
            end_date = current_subscription.get('end_date')
            plan_name = current_subscription.get('plan_name')
            
            text = f"""
💎 <b>У вас уже есть активная подписка!</b>

📦 <b>Текущий тариф:</b> {plan_name}
📅 <b>Действует до:</b> {end_date.strftime('%d.%m.%Y') if end_date else 'Неизвестно'}

✅ <b>Доступные Pro функции:</b>
• Безлимитные боты
• Безлимитные подписчики  
• Расширенные воронки продаж
• Приоритетная поддержка

💡 <b>Подписка продлится автоматически при новой оплате</b>
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="💎 Продлить подписку",
                        callback_data="pricing_extend"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=f"{Emoji.BACK} Главное меню",
                        callback_data="back_to_main"
                    )
                ]
            ])
            
        else:
            # Обычное меню тарифов для пользователей без подписки
            text = f"""
💎 <b>ТАРИФ "AI ADMIN"</b>

🚀 <b>Что дает Pro подписка:</b>
• Безлимитное количество ботов
• Безлимитные подписчики для каждого бота
• Расширенные воронки продаж (безлимит сообщений)
• Приоритетная техподдержка
• Все будущие обновления

<b>💰 Стоимость подписки:</b>
• 📅 <b>1 месяц</b> — 299 ₽
• 📅 <b>3 месяца</b> — 749 ₽ <i>(экономия 150₽)</i>
• 📅 <b>6 месяцев</b> — 1,499 ₽ <i>(экономия 295₽)</i>  
• 📅 <b>12 месяцев</b> — 2,490 ₽ <i>(экономия 1,098₽)</i>

{Emoji.INFO} При оплате вы соглашаетесь с <a href="https://graph.org/AI-Admin---POLZOVATELSKOE-SOGLASHENIE-08-15">пользовательским соглашением</a>.

Выберите срок действия тарифа:
"""
            
            keyboard = self.get_pricing_keyboard()
        
        await callback.message.edit_text(
            text,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    
    async def cb_pricing_plan(self, callback: CallbackQuery):
        """✅ ИСПРАВЛЕНО: Правильная обработка результатов БД"""
        await callback.answer()
        
        logger.info("🔥 ===== ROBOKASSA DEBUG START =====")
        logger.info("📋 Callback data received", 
                   callback_data=callback.data,
                   user_id=callback.from_user.id,
                   username=callback.from_user.username)
        
        # Если это продление подписки
        if callback.data == "pricing_extend":
            logger.info("🔄 Extend subscription request")
            await self._show_extend_subscription_options(callback)
            return
        
        plan_id = callback.data.replace("pricing_", "")
        logger.info("📦 Plan ID extracted", plan_id=plan_id)
        
        # Проверяем валидность плана
        logger.info("🔍 Checking plan validity...")
        if not hasattr(settings, 'subscription_plans'):
            logger.error("❌ settings.subscription_plans NOT FOUND!")
            await callback.answer("❌ Ошибка конфигурации планов", show_alert=True)
            return
        
        plan = settings.subscription_plans.get(plan_id)
        if not plan:
            available_plans = list(settings.subscription_plans.keys())
            logger.error("❌ Invalid plan_id", 
                        plan_id=plan_id, 
                        available_plans=available_plans)
            await callback.answer("❌ Неверный тарифный план", show_alert=True)
            return
        
        logger.info("✅ Plan found", 
                   plan_id=plan_id,
                   plan_title=plan.get('title'),
                   plan_price=plan.get('price'),
                   plan_duration=plan.get('duration_days'))
        
        # Проверяем Robokassa сервис
        logger.info("🔍 Checking Robokassa service...")
        if not self.robokassa_service:
            logger.error("❌ robokassa_service is None!")
            await callback.answer("❌ Сервис платежей недоступен", show_alert=True)
            return
        
        # Логируем конфигурацию Robokassa
        logger.info("⚙️ Robokassa configuration",
                   merchant_login=self.robokassa_service.merchant_login,
                   test_mode=self.robokassa_service.test_mode,
                   has_password1=bool(self.robokassa_service.password1),
                   has_password2=bool(self.robokassa_service.password2),
                   password1_length=len(self.robokassa_service.password1) if self.robokassa_service.password1 else 0,
                   password2_length=len(self.robokassa_service.password2) if self.robokassa_service.password2 else 0)
        
        try:
            logger.info("💳 Starting payment URL generation...")
            logger.info("📊 Input parameters",
                       plan_id=plan_id,
                       user_id=callback.from_user.id,
                       user_email=None,
                       plan_price=plan.get('price'))
            
            # ✅ ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА ПЛАНА
            price = plan.get('price', 0)
            if not isinstance(price, (int, float)) or price <= 0:
                logger.error("❌ Invalid plan price", 
                            plan_id=plan_id, 
                            price=price, 
                            price_type=type(price).__name__)
                await callback.answer("❌ Ошибка в цене плана", show_alert=True)
                return
            
            logger.info("💰 Price validation passed", price=price, price_type=type(price).__name__)
            
            # ✅ ТЕСТИРУЕМ ГЕНЕРАЦИЮ ПОДПИСИ ОТДЕЛЬНО
            try:
                logger.info("🔐 Testing signature generation...")
                test_result = self.robokassa_service.test_signature_generation({
                    'MerchantLogin': self.robokassa_service.merchant_login,
                    'OutSum': f"{price:.2f}".replace(',', '.'),
                    'InvId': f'test_{int(datetime.now().timestamp())}',
                    'Shp_user_id': str(callback.from_user.id),
                    'Shp_plan_id': plan_id,
                    'Shp_bot_factory': '1'
                })
                
                if test_result.get('success'):
                    logger.info("✅ Signature test PASSED", 
                               signature=test_result.get('signature'),
                               signature_length=test_result.get('signature_length'))
                else:
                    logger.error("❌ Signature test FAILED", 
                                error=test_result.get('error'))
                    await callback.answer("❌ Ошибка тестирования подписи", show_alert=True)
                    return
                    
            except Exception as sig_error:
                logger.error("💥 Signature test exception", 
                            error=str(sig_error),
                            error_type=type(sig_error).__name__)
                await callback.answer("❌ Ошибка тестирования подписи", show_alert=True)
                return
            
            # ✅ ОСНОВНАЯ ГЕНЕРАЦИЯ URL
            logger.info("🚀 Generating actual payment URL...")
            payment_url, order_id = self.robokassa_service.generate_payment_url(
                plan_id=plan_id,
                user_id=callback.from_user.id,
                user_email=None  # Email опционален
            )
            
            logger.info("✅ Payment URL generated successfully!",
                       order_id=order_id,
                       url_length=len(payment_url),
                       url_preview=payment_url[:150] + "..." if len(payment_url) > 150 else payment_url)
            
            # ✅ АНАЛИЗИРУЕМ СОЗДАННУЮ ССЫЛКУ
            parsed_url = urlparse(payment_url)
            url_params = parse_qs(parsed_url.query)
            
            logger.info("🔍 URL Analysis",
                       scheme=parsed_url.scheme,
                       netloc=parsed_url.netloc,
                       path=parsed_url.path,
                       query_length=len(parsed_url.query),
                       params_count=len(url_params))
            
            # Логируем ключевые параметры (БЕЗ паролей!)
            safe_params = {}
            for key, value in url_params.items():
                if 'password' not in key.lower() and 'signature' not in key.lower():
                    safe_params[key] = value[0] if isinstance(value, list) and value else value
                else:
                    safe_params[key] = f"[MASKED_{len(str(value))}]"
            
            logger.info("📋 URL Parameters", params=safe_params)
            
            # Проверяем обязательные параметры
            required_params = ['MerchantLogin', 'OutSum', 'InvId', 'SignatureValue']
            missing_params = []
            for param in required_params:
                if param not in url_params:
                    missing_params.append(param)
            
            if missing_params:
                logger.error("❌ Missing required parameters", missing=missing_params)
                await callback.answer("❌ Ошибка параметров платежа", show_alert=True)
                return
            
            logger.info("✅ All required parameters present")
            
            # ✅ ИСПРАВЛЕНО: СОЗДАЕМ ЗАПИСЬ О ПЛАТЕЖЕ с безопасной обработкой результата
            logger.info("💾 Creating payment record...")
            payment_record_data = {
                'user_id': callback.from_user.id,
                'order_id': order_id,
                'amount': float(plan['price']),
                'currency': 'RUB',
                'status': 'pending',
                'payment_method': 'robokassa_web',
                'description': plan['description']
            }
            
            logger.info("📝 Payment record data", payment_data=payment_record_data)
            
            try:
                payment_record_raw = await db.create_payment_record(payment_record_data)
                payment_record = row_to_dict(payment_record_raw) if payment_record_raw else None
                
                if payment_record:
                    logger.info("✅ Payment record created", 
                               payment_id=payment_record.get('id'),
                               order_id=order_id)
                else:
                    logger.error("❌ Failed to create payment record")
                    await callback.answer("❌ Ошибка создания записи платежа", show_alert=True)
                    return
                    
            except Exception as db_error:
                logger.error("💥 Database error creating payment record",
                            error=str(db_error),
                            error_type=type(db_error).__name__)
                await callback.answer("❌ Ошибка базы данных", show_alert=True)
                return
            
            # ✅ ФОРМИРУЕМ ОТВЕТНОЕ СООБЩЕНИЕ
            logger.info("📝 Preparing response message...")
            
            text = f"""
💳 <b>Оплата подписки</b>

📦 <b>Тариф:</b> {plan['title']}
💰 <b>Стоимость:</b> {plan['price']} ₽
⏱ <b>Срок:</b> {plan['duration_days']} дней

🔒 <b>Безопасная оплата через Robokassa</b>
Принимаем карты всех банков

🎯 <b>После оплаты получите:</b>
• Мгновенную активацию Pro функций
• Безлимитные возможности Bot Factory
• Приоритетную поддержку

💡 <b>Нажмите кнопку ниже для перехода к оплате</b>
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="💳 Оплатить",
                        url=payment_url
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔄 Проверить оплату",
                        callback_data=f"check_payment_{order_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="💎 Выбрать другой тариф",
                        callback_data="pricing"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=f"{Emoji.BACK} Главное меню",
                        callback_data="back_to_main"
                    )
                ]
            ])
            
            logger.info("📤 Sending response to user...")
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
            logger.info("🎉 SUCCESS! Payment flow completed successfully",
                       user_id=callback.from_user.id,
                       plan_id=plan_id,
                       order_id=order_id,
                       amount=plan['price'],
                       url_length=len(payment_url))
            
            logger.info("🔥 ===== ROBOKASSA DEBUG END =====")
            
        except Exception as e:
            logger.error("💥 CRITICAL ERROR in payment URL generation",
                        error=str(e),
                        error_type=type(e).__name__,
                        user_id=callback.from_user.id,
                        plan_id=plan_id,
                        exc_info=True)
            
            # Дополнительная диагностика
            logger.error("🔍 Error context",
                        robokassa_service_exists=self.robokassa_service is not None,
                        plan_exists=plan is not None,
                        plan_price=plan.get('price') if plan else None)
            
            await callback.answer("❌ Произошла ошибка. Попробуйте позже.", show_alert=True)
            
            logger.info("🔥 ===== ROBOKASSA DEBUG END (WITH ERROR) =====")
    
    async def debug_robokassa_manually(self, user_id: int = 123456, plan_id: str = "1m"):
        """
        ✅ РУЧНАЯ ДИАГНОСТИКА ROBOKASSA
        Вызовите этот метод в консоли для тестирования
        """
        logger.info("🧪 ===== MANUAL ROBOKASSA DEBUG =====")
        
        try:
            # Проверка сервиса
            if not self.robokassa_service:
                logger.error("❌ robokassa_service is None")
                return False
            
            # Проверка health check
            health = self.robokassa_service.health_check()
            logger.info("🏥 Health check result", health=health)
            
            # Проверка планов
            plan_validation = self.robokassa_service.validate_plan_prices()
            logger.info("📋 Plan validation", validation=plan_validation)
            
            # Тест генерации URL
            logger.info("🚀 Testing URL generation...")
            payment_url, order_id = self.robokassa_service.generate_payment_url(
                plan_id=plan_id,
                user_id=user_id
            )
            
            logger.info("✅ Manual test SUCCESSFUL",
                       order_id=order_id,
                       url=payment_url[:200] + "...")
            
            # Сохраняем URL в файл для проверки
            with open("/tmp/robokassa_test_url.txt", "w") as f:
                f.write(f"Order ID: {order_id}\n")
                f.write(f"URL: {payment_url}\n")
            
            logger.info("💾 URL saved to /tmp/robokassa_test_url.txt")
            
            return True
            
        except Exception as e:
            logger.error("💥 Manual test FAILED",
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            return False
    
    def check_robokassa_config(self):
        """Быстрая проверка конфигурации Robokassa"""
        logger.info("🔧 ===== ROBOKASSA CONFIG CHECK =====")
        
        # Проверка сервиса
        logger.info("Service check",
                   service_exists=self.robokassa_service is not None)
        
        if not self.robokassa_service:
            logger.error("❌ Robokassa service not initialized")
            return False
        
        # Проверка настроек
        service_info = self.robokassa_service.get_service_info()
        logger.info("🔍 Service info", info=service_info)
        
        # Проверка переменных окружения
        import os
        env_vars = {
            'ROBOKASSA_MERCHANT_LOGIN': os.getenv('ROBOKASSA_MERCHANT_LOGIN'),
            'ROBOKASSA_TEST_MODE': os.getenv('ROBOKASSA_TEST_MODE'),
            'ROBOKASSA_PASSWORD1': bool(os.getenv('ROBOKASSA_PASSWORD1')),
            'ROBOKASSA_PASSWORD2': bool(os.getenv('ROBOKASSA_PASSWORD2'))
        }
        logger.info("🌍 Environment variables", env_vars=env_vars)
        
        # Проверка планов
        logger.info("📋 Subscription plans",
                   plans_exist=hasattr(settings, 'subscription_plans'),
                   plans_count=len(settings.subscription_plans) if hasattr(settings, 'subscription_plans') else 0)
        
        if hasattr(settings, 'subscription_plans'):
            for plan_id, plan_data in settings.subscription_plans.items():
                logger.info(f"📦 Plan {plan_id}",
                           title=plan_data.get('title'),
                           price=plan_data.get('price'),
                           duration=plan_data.get('duration_days'))
        
        logger.info("🔧 ===== CONFIG CHECK COMPLETE =====")
        return True
    
    async def cb_check_payment(self, callback: CallbackQuery):
        """✅ ИСПРАВЛЕНО: Проверка статуса оплаты с безопасной обработкой БД"""
        await callback.answer()
        
        # Извлекаем order_id из callback_data
        if not callback.data.startswith("check_payment_"):
            return
        
        order_id = callback.data.replace("check_payment_", "")
        
        try:
            # Проверяем подписку в БД
            subscription_raw = await db.get_subscription_by_order_id(order_id)
            subscription = row_to_dict(subscription_raw) if subscription_raw else None
            
            if subscription and subscription.get('status') == 'active':
                # Оплата прошла успешно
                end_date = subscription.get('end_date')
                plan_name = subscription.get('plan_name')
                
                text = f"""
🎉 <b>Оплата успешно обработана!</b>

💎 <b>Тариф:</b> {plan_name}
📅 <b>Действует до:</b> {end_date.strftime('%d.%m.%Y') if end_date else 'Неизвестно'}

✅ <b>Pro функции активированы:</b>
• Безлимитные боты
• Безлимитные подписчики
• Расширенные воронки продаж
• Приоритетная поддержка

🚀 <b>Начните создавать ботов без ограничений!</b>
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=f"{Emoji.PLUS} Создать бота",
                            callback_data="create_bot"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text=f"{Emoji.LIST} Мои боты",
                            callback_data="my_bots"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text=f"{Emoji.BACK} Главное меню",
                            callback_data="back_to_main"
                        )
                    ]
                ])
                
                await callback.message.edit_text(text, reply_markup=keyboard)
                
            else:
                # Оплата еще не обработана
                text = f"""
⏳ <b>Ожидание оплаты</b>

💳 Ваш платеж еще обрабатывается.

⏱ <b>Обычно это занимает:</b>
• 1-3 минуты для карт
• До 10 минут для других способов

🔄 <b>Что делать:</b>
• Подождите несколько минут
• Нажмите "Проверить оплату" снова
• Если долго не приходит - обратитесь в поддержку

💡 Мы автоматически активируем Pro функции сразу после получения платежа.
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🔄 Проверить снова",
                            callback_data=f"check_payment_{order_id}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="💬 Поддержка",
                            url="https://t.me/support"  # Замените на вашу поддержку
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text=f"{Emoji.BACK} Главное меню",
                            callback_data="back_to_main"
                        )
                    ]
                ])
                
                await callback.message.edit_text(text, reply_markup=keyboard)
                
        except Exception as e:
            logger.error("Failed to check payment status",
                        error=str(e),
                        order_id=order_id,
                        user_id=callback.from_user.id)
            
            await callback.answer("❌ Ошибка проверки платежа", show_alert=True)
    
    async def _show_extend_subscription_options(self, callback: CallbackQuery):
        """✅ НОВЫЙ: Показать опции продления подписки"""
        text = f"""
💎 <b>Продление подписки AI ADMIN</b>

💡 <b>При продлении:</b>
• Новый период добавится к текущему
• Скидки действуют как для новых клиентов
• Не теряете оставшееся время

<b>💰 Выберите период продления:</b>
• 📅 <b>1 месяц</b> — 299 ₽
• 📅 <b>3 месяца</b> — 749 ₽ <i>(экономия 150₽)</i>
• 📅 <b>6 месяцев</b> — 1,499 ₽ <i>(экономия 295₽)</i>
• 📅 <b>12 месяцев</b> — 2,490 ₽ <i>(экономия 1,098₽)</i>

Выберите срок продления:
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📅 1 месяц — 299 ₽",
                    callback_data="pricing_1m"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📅 3 месяца — 749 ₽ (экономия 150₽)",
                    callback_data="pricing_3m"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📅 6 месяцев — 1,499 ₽ (экономия 295₽)",
                    callback_data="pricing_6m"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📅 12 месяцев — 2,490 ₽ (экономия 1,098₽)",
                    callback_data="pricing_12m"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{Emoji.BACK} Назад",
                    callback_data="pricing"
                )
            ]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def cb_how_to_create(self, callback: CallbackQuery):
        """How to create bot callback"""
        await callback.answer()
        
        await callback.message.edit_text(
            Messages.HOW_TO_CREATE_BOT,
            reply_markup=self.get_back_keyboard()
        )
    
    async def cb_back_to_main(self, callback: CallbackQuery, state: FSMContext):
        """Back to main menu callback"""
        await callback.answer()
        await state.clear()
        
        await callback.message.edit_text(
            Messages.WELCOME,
            reply_markup=self.get_main_keyboard()
        )
    
    # ✅ BOT MANAGEMENT
    
    async def cb_bot_details(self, callback: CallbackQuery):
        """✅ ИСПРАВЛЕНО: Bot details callback с безопасной обработкой БД"""
        await callback.answer()
        
        bot_id = callback.data.replace("bot_", "")
        bot_raw = await db.get_bot_by_id(bot_id)
        bot = row_to_dict(bot_raw) if bot_raw else None
        
        if not bot:
            await callback.answer("Бот не найден", show_alert=True)
            return
        
        # ✅ ДОБАВЛЕНО: Проверка владельца бота
        if bot.get('user_id') != callback.from_user.id:
            await callback.answer("❌ Это не ваш бот", show_alert=True)
            return
        
        status_emoji = Emoji.SUCCESS if bot.get('is_running') else Emoji.ERROR
        status_text = "Активен" if bot.get('is_running') else "Остановлен"
        
        # ✅ НОВОЕ: Показываем информацию об ИИ агенте
        ai_info = ""
        if bot.get('ai_assistant_enabled') and bot.get('ai_assistant_type'):
            if bot.get('ai_assistant_type') == 'openai':
                agent_name = bot.get('openai_agent_name', 'OpenAI Агент')
                ai_info = f"🎨 <b>ИИ Агент:</b> {agent_name} (OpenAI)\n"
            elif bot.get('ai_assistant_type') in ['chatforyou', 'protalk']:
                platform_name = bot.get('ai_assistant_type').title()
                ai_info = f"🌐 <b>ИИ Агент:</b> {platform_name}\n"
        else:
            ai_info = f"🤖 <b>ИИ Агент:</b> Не настроен\n"
        
        # Get extended bot info
        created_at = bot.get('created_at', datetime.now())
        created_at_str = created_at.strftime('%d.%m.%Y') if hasattr(created_at, 'strftime') else str(created_at)
        
        text = f"""
{Emoji.ROBOT} <b>Бот @{bot.get('bot_username', 'unknown')}</b>

{status_emoji} <b>Статус:</b> {status_text}
{Emoji.USERS} <b>Подписчиков:</b> {bot.get('total_subscribers', 0)}
{Emoji.BROADCAST} <b>Отправлено сообщений:</b> {bot.get('total_messages_sent', 0)}
{ai_info}{Emoji.CHART} <b>Создан:</b> {created_at_str}

{Emoji.INFO} <b>Настройки:</b>
- Приветствие: {'✅' if bot.get('welcome_message') else '❌ Не настроено'}
- Кнопка приветствия: {'✅' if bot.get('welcome_button_text') else '❌ Не настроено'}
- Подтверждение: {'✅' if bot.get('confirmation_message') else '❌ Не настроено'}
- Прощание: {'✅' if bot.get('goodbye_message') else '❌ Не настроено'}
- Кнопка прощания: {'✅' if bot.get('goodbye_button_text') else '❌ Не настроено'}

{Emoji.NEW} <b>Для настройки бота:</b>
Напишите боту @{bot.get('bot_username', 'unknown')} команду /start
"""
        
        # Создаем объект-подобие для обратной совместимости
        bot_obj = type('Bot', (), bot)()
        
        await callback.message.edit_text(
            text,
            reply_markup=self.get_bot_info_keyboard(bot_obj)
        )
    
    async def cb_bot_manage(self, callback: CallbackQuery):
        """✅ ИСПРАВЛЕНО: Bot management actions с безопасной обработкой БД"""
        await callback.answer()
        
        action_data = callback.data.replace("manage_", "")
        parts = action_data.split("_", 1)
        
        if len(parts) != 2:
            await callback.answer("Неверный формат команды", show_alert=True)
            return
        
        action, bot_id = parts
        
        bot_raw = await db.get_bot_by_id(bot_id)
        bot = row_to_dict(bot_raw) if bot_raw else None
        
        if not bot:
            await callback.answer("Бот не найден", show_alert=True)
            return
        
        # ✅ ДОБАВЛЕНО: Проверка владельца для всех операций управления
        if bot.get('user_id') != callback.from_user.id:
            await callback.answer("❌ Только владелец может управлять ботом", show_alert=True)
            return
        
        # Создаем объект-подобие для обратной совместимости
        bot_obj = type('Bot', (), bot)()
        
        if action == "configure":
            await self._show_configure_instructions(callback, bot_obj)
        elif action == "stats":
            await self._show_bot_quick_stats(callback, bot_obj)
        elif action == "restart":
            await self._restart_bot(callback, bot_obj)
        elif action == "delete":
            await self._show_delete_confirmation(callback, bot_obj)
    
    # ✅ BOT TOKEN INPUT
    
    async def handle_token_input(self, message: Message, state: FSMContext):
        """Handle bot token input"""
        token = message.text.strip()
        
        # Basic token validation
        if not self._validate_token(token):
            await message.answer(
                f"{Emoji.ERROR} <b>Неверный формат токена!</b>\n\n"
                f"Токен должен выглядеть как:\n"
                f"<code>123456789:ABCdefGHIjklMNOpqrSTUvwxYZ</code>\n\n"
                f"Попробуйте еще раз:"
            )
            return
        
        # Try to create bot
        try:
            bot_info = await self._verify_token(token)
            if not bot_info:
                await message.answer(
                    f"{Emoji.ERROR} <b>Токен недействителен!</b>\n\n"
                    f"Проверьте токен и попробуйте еще раз:"
                )
                return
            
            # Create bot in database
            bot_id = str(uuid.uuid4())
            bot_data = {
                "bot_id": bot_id,
                "user_id": message.from_user.id,
                "token": token,
                "bot_username": bot_info.username,
                "bot_name": bot_info.first_name,
                "status": "active",
                "is_running": True
            }
            
            await db.create_user_bot(bot_data)
            
            # Add bot to bot manager if available
            if self.bot_manager:
                try:
                    bot_db_data_raw = await db.get_bot_by_id(bot_id)
                    bot_db_data = row_to_dict(bot_db_data_raw) if bot_db_data_raw else None
                    if bot_db_data:
                        # Создаем объект-подобие для обратной совместимости
                        bot_obj = type('Bot', (), bot_db_data)()
                        await self.bot_manager.add_bot(bot_obj)
                        logger.info("Bot added to manager", bot_id=bot_id)
                except Exception as e:
                    logger.error("Failed to add bot to manager", bot_id=bot_id, error=str(e))
            
            await state.clear()
            
            success_text = f"""
{Emoji.SUCCESS} <b>Бот успешно создан!</b>

{Emoji.ROBOT} <b>@{bot_info.username}</b>
{Emoji.INFO} Имя: {bot_info.first_name}

💰 <b>Ваш токеновый баланс OpenAI:</b> 500,000 токенов

{Emoji.ROCKET} <b>Что дальше?</b>
1. Добавьте бота в свой канал как администратора
2. Дайте права на управление участниками
3. Перейдите к настройке бота

{Emoji.NEW} <b>Для настройки бота:</b>
Напишите боту @{bot_info.username} команду <code>/start</code>

🎨 <b>Доступны ИИ агенты:</b>
- Собственные OpenAI агенты (включены в токены)
- Подключение внешних платформ

{Emoji.FIRE} Бот уже работает и готов к использованию!
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"📱 Написать @{bot_info.username}",
                        url=f"https://t.me/{bot_info.username}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=f"🔧 Информация о боте",
                        callback_data=f"bot_{bot_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=f"{Emoji.LIST} Все мои боты",
                        callback_data="my_bots"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=f"{Emoji.BACK} Главное меню",
                        callback_data="back_to_main"
                    )
                ]
            ])
            
            await message.answer(success_text, reply_markup=keyboard)
            
            logger.info(
                "Bot created successfully with user having token limit", 
                user_id=message.from_user.id,
                bot_username=bot_info.username,
                bot_id=bot_id
            )
            
        except Exception as e:
            logger.error("Failed to create bot", error=str(e))
            await message.answer(
                f"{Emoji.ERROR} <b>Ошибка при создании бота!</b>\n\n"
                f"Попробуйте позже или обратитесь в поддержку.",
                reply_markup=self.get_back_keyboard()
            )
    
    def _validate_token(self, token: str) -> bool:
        """Validate token format"""
        import re
        pattern = r'^\d+:[A-Za-z0-9_-]+$'
        return bool(re.match(pattern, token))
    
    async def _verify_token(self, token: str):
        """Verify token with Telegram"""
        try:
            temp_bot = Bot(token=token)
            bot_info = await temp_bot.get_me()
            await temp_bot.session.close()
            return bot_info
        except Exception as e:
            logger.error("Token verification failed", error=str(e))
            return None
    
    # ✅ BOT MANAGEMENT ACTIONS
    
    async def _show_configure_instructions(self, callback: CallbackQuery, bot):
        """Show configuration instructions"""
        bot_username = getattr(bot, 'bot_username', 'unknown')
        
        text = f"""
{Emoji.SETTINGS} <b>Настройка бота @{bot_username}</b>

{Emoji.NEW} <b>У каждого бота теперь есть собственная админ-панель!</b>

{Emoji.ROCKET} <b>Для настройки:</b>
1. Перейдите в чат с ботом @{bot_username}
2. Отправьте команду <code>/start</code>
3. Получите доступ к полной админ-панели

{Emoji.INFO} <b>В админ-панели бота доступно:</b>
- Настройка приветственных сообщений и кнопок
- Настройка прощальных сообщений с кнопками
- Создание и управление воронкой продаж
- Детальная статистика и аналитика
- Управление медиа-контентом
- Настройка кнопок для сообщений
- 🎨 <b>ИИ агенты OpenAI</b> (используют ваши 500,000 токенов)
- 🌐 <b>Подключение внешних ИИ платформ</b>

{Emoji.FIRE} <b>Преимущества:</b>
- Удобный интерфейс для каждого бота
- Быстрый доступ к настройкам
- Реальная статистика в реальном времени
- Мощные ИИ агенты для пользователей
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"📱 Написать @{bot_username}",
                    url=f"https://t.me/{bot_username}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{Emoji.BACK} К информации о боте",
                    callback_data=f"bot_{getattr(bot, 'bot_id', 'unknown')}"
                )
            ]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def _show_bot_quick_stats(self, callback: CallbackQuery, bot):
        """✅ ИСПРАВЛЕНО: Show quick bot statistics с безопасной обработкой БД"""
        try:
            bot_id = getattr(bot, 'bot_id', None)
            bot_username = getattr(bot, 'bot_username', 'unknown')
            
            # Get real-time stats from bot manager
            bot_status = {"status": "unknown", "running": False}
            if self.bot_manager and bot_id:
                bot_status = self.bot_manager.get_bot_status(bot_id)
            
            status_emoji = Emoji.SUCCESS if bot_status.get('running', False) else Emoji.ERROR
            status_text = "Активен" if bot_status.get('running', False) else "Остановлен"
            
            # Get button stats if available
            button_stats = bot_status.get('button_stats', {})
            
            # ✅ ИСПРАВЛЕНО: Показываем статистику токенов OpenAI с безопасной обработкой
            token_info = ""
            try:
                # Пытаемся получить информацию о токенах пользователя
                user_token_balance_raw = await db.get_user_token_balance(callback.from_user.id)
                user_token_balance = row_to_dict(user_token_balance_raw) if user_token_balance_raw else None
                
                if user_token_balance:
                    tokens_used = user_token_balance.get('total_used', 0)
                    tokens_limit = user_token_balance.get('limit', 500000)
                    tokens_remaining = tokens_limit - tokens_used
                    usage_percent = round((tokens_used / tokens_limit * 100), 1) if tokens_limit > 0 else 0
                    
                    token_info = f"""
💰 <b>Токены OpenAI:</b>
- Использовано: {tokens_used:,} из {tokens_limit:,} ({usage_percent}%)
- Осталось: {tokens_remaining:,} токенов
"""
            except Exception as token_error:
                logger.warning("Could not get token balance for stats", error=str(token_error))
            
            # Безопасное получение атрибутов бота
            total_subscribers = getattr(bot, 'total_subscribers', 0)
            total_messages_sent = getattr(bot, 'total_messages_sent', 0)
            created_at = getattr(bot, 'created_at', datetime.now())
            created_at_str = created_at.strftime('%d.%m.%Y в %H:%M') if hasattr(created_at, 'strftime') else str(created_at)
            
            text = f"""
{Emoji.CHART} <b>Статистика @{bot_username}</b>

{status_emoji} <b>Статус:</b> {status_text}
{Emoji.USERS} <b>Подписчиков:</b> {total_subscribers}
{Emoji.BROADCAST} <b>Сообщений отправлено:</b> {total_messages_sent}
{token_info}
{Emoji.BUTTON} <b>Активность кнопок:</b>
- Приветственных отправлено: {button_stats.get('welcome_buttons_sent', 0)}
- Прощальных отправлено: {button_stats.get('goodbye_buttons_sent', 0)}
- Всего нажатий: {button_stats.get('button_clicks', 0)}
- Подтверждений отправлено: {button_stats.get('confirmation_sent', 0)}

{Emoji.FUNNEL} <b>Воронки:</b>
- Запущено: {button_stats.get('funnel_starts', 0)}

{Emoji.CHART} <b>Создан:</b> {created_at_str}

{Emoji.INFO} <b>Подробная статистика:</b>
Напишите боту @{bot_username} команду /start
и перейдите в раздел "Статистика"
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"📱 Админ-панель @{bot_username}",
                        url=f"https://t.me/{bot_username}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔄 Обновить",
                        callback_data=f"manage_stats_{bot_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=f"{Emoji.BACK} К информации о боте",
                        callback_data=f"bot_{bot_id}"
                    )
                ]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error("Failed to show bot stats", bot_id=getattr(bot, 'bot_id', 'unknown'), error=str(e))
            await callback.answer("Ошибка при загрузке статистики", show_alert=True)
    
    async def _restart_bot(self, callback: CallbackQuery, bot):
        """Restart bot"""
        try:
            bot_id = getattr(bot, 'bot_id', None)
            if self.bot_manager and bot_id:
                await self.bot_manager.restart_bot(bot_id)
                await callback.answer("Бот перезапущен!", show_alert=True)
                
                # Refresh bot info
                await self.cb_bot_details(
                    callback=type('obj', (object,), {
                        'data': f'bot_{bot_id}',
                        'answer': callback.answer,
                        'message': callback.message,
                        'from_user': callback.from_user
                    })()
                )
            else:
                await callback.answer("Bot Manager недоступен", show_alert=True)
                
        except Exception as e:
            logger.error("Failed to restart bot", bot_id=getattr(bot, 'bot_id', 'unknown'), error=str(e))
            await callback.answer("Ошибка при перезапуске бота", show_alert=True)
    
    async def _show_delete_confirmation(self, callback: CallbackQuery, bot):
        """✅ ИСПРАВЛЕНО: Show bot deletion confirmation without temporary handler registration"""
        bot_username = getattr(bot, 'bot_username', 'unknown')
        bot_id = getattr(bot, 'bot_id', 'unknown')
        
        text = f"""
{Emoji.WARNING} <b>Удаление бота</b>

Вы действительно хотите удалить бота @{bot_username}?

{Emoji.INFO} <b>Это действие:</b>
- Удалит бота из системы
- Остановит все его функции
- Удалит всю статистику и настройки
- Удалит настройки ИИ агентов
- <b>НЕЛЬЗЯ ОТМЕНИТЬ!</b>

💰 <b>Важно:</b> Ваши токены OpenAI (500,000) останутся доступны для других ботов.

{Emoji.WARNING} <b>Примечание:</b> Сам бот в Telegram останется, но перестанет работать.
Вы можете повторно добавить его позже с тем же токеном.
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{Emoji.DELETE} Да, удалить бота",
                    callback_data=f"confirm_delete_{bot_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{Emoji.BACK} Отмена",
                    callback_data=f"bot_{bot_id}"
                )
            ]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def _confirm_delete_bot(self, callback: CallbackQuery):
        """✅ ИСПРАВЛЕНО: Confirm bot deletion with owner verification и безопасной обработкой БД"""
        await callback.answer()
        
        bot_id = callback.data.replace("confirm_delete_", "")
        
        try:
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверка владельца бота
            bot_raw = await db.get_bot_by_id(bot_id)
            bot = row_to_dict(bot_raw) if bot_raw else None
            
            if not bot:
                await callback.answer("❌ Бот не найден", show_alert=True)
                return
            
            if bot.get('user_id') != callback.from_user.id:
                await callback.answer("❌ Только владелец может удалить бота", show_alert=True)
                return
            
            bot_username = bot.get('bot_username', 'unknown')
            
            logger.info("User confirmed bot deletion", 
                       user_id=callback.from_user.id,
                       bot_id=bot_id,
                       bot_username=bot_username)
            
            # Remove from bot manager
            if self.bot_manager:
                try:
                    await self.bot_manager.remove_bot(bot_id)
                    logger.info("Bot removed from manager", bot_id=bot_id)
                except Exception as e:
                    logger.error("Failed to remove bot from manager", bot_id=bot_id, error=str(e))
            
            # Delete from database
            await db.delete_user_bot(bot_id)
            
            await callback.message.edit_text(
                f"{Emoji.SUCCESS} <b>Бот @{bot_username} успешно удален!</b>\n\n"
                f"Бот остановлен и удален из системы.\n"
                f"Все настройки и статистика также удалены.\n\n"
                f"💰 <b>Ваши токены OpenAI сохранены</b> и доступны для других ботов.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=f"{Emoji.LIST} Мои боты",
                            callback_data="my_bots"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text=f"{Emoji.BACK} Главное меню",
                            callback_data="back_to_main"
                        )
                    ]
                ])
            )
            
            logger.info("Bot deleted successfully", 
                       bot_id=bot_id,
                       bot_username=bot_username,
                       owner_id=callback.from_user.id)
            
        except Exception as e:
            logger.error("Failed to delete bot", bot_id=bot_id, error=str(e), exc_info=True)
            await callback.answer("Ошибка при удалении бота", show_alert=True)
    
    # ✅ BOT LIFECYCLE
    
    async def start_polling(self):
        """Start bot polling"""
        await self.set_commands()
        logger.info("✅ Master bot started with payment integration")
        await self.dp.start_polling(self.bot)
    
    async def stop(self):
        """Stop bot"""
        try:
            await self.bot.session.close()
            logger.info("Master bot stopped")
        except Exception as e:
            logger.error("Error closing bot session", error=str(e))


# В конце файла добавить логирование
logger.info("🎉 MasterBot with Robokassa integration and safe DB handling loaded successfully")
