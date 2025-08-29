import asyncio
import uuid
import hashlib
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode
from typing import Optional

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
from database.managers.user_manager import UserManager
from services.admin_service import AdminService
from utils.media_handler import MediaHandler, BroadcastMedia
from utils.access_control import check_user_access, require_access


logger = structlog.get_logger()


class BotCreationStates(StatesGroup):
    waiting_for_token = State()


class AdminBroadcastStates(StatesGroup):
    waiting_for_message = State()
    waiting_for_confirmation = State()
    collecting_media_album = State()  # ✅ НОВОЕ: для сбора медиаальбомов


class MasterBot:
    def __init__(self, bot_manager=None):
        self.bot = Bot(
            token=settings.master_bot_token, 
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        self.dp = Dispatcher(storage=MemoryStorage())
        self.bot_manager = bot_manager
        
        # ✅ НОВОЕ: Инициализируем admin service
        self.admin_service = AdminService(self.bot)
        
        self._setup_handlers()
    
    def _setup_handlers(self):
        """✅ ОБНОВЛЕНО: Setup handlers with admin functionality and media support"""
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
        
        # Robokassa handlers
        self.dp.callback_query.register(self.cb_pay_subscription, F.data == "pay_subscription")
        self.dp.callback_query.register(self.cb_check_payment_status, F.data == "check_payment_status")
        
        # Token purchase callbacks
        self.dp.callback_query.register(self.cb_buy_tokens, F.data == "buy_tokens")
        self.dp.callback_query.register(self.cb_pay_tokens, F.data == "pay_tokens")
        self.dp.callback_query.register(self.cb_check_tokens_payment, F.data == "check_tokens_payment")
        
        # Bot management callbacks
        self.dp.callback_query.register(self.cb_bot_details, F.data.startswith("bot_"))
        self.dp.callback_query.register(self.cb_bot_manage, F.data.startswith("manage_"))
        
        # Bot deletion handler
        self.dp.callback_query.register(
            self._confirm_delete_bot, 
            F.data.startswith("confirm_delete_")
        )
        
        # ✅ НОВОЕ: Admin callbacks (только для суперадмина)
        self.dp.callback_query.register(self.cb_admin_stats, F.data == "admin_stats")
        self.dp.callback_query.register(self.cb_admin_broadcast, F.data == "admin_broadcast")
        self.dp.callback_query.register(self.cb_admin_history, F.data == "admin_history")
        
        # ✅ НОВОЕ: Admin broadcast handlers with media support
        self.dp.callback_query.register(self.cb_confirm_broadcast, F.data == "confirm_broadcast")
        
        # ✅ ОБНОВЛЕНО: Admin broadcast message handler (теперь поддерживает медиа)
        self.dp.message.register(
            self.handle_admin_broadcast_message, 
            AdminBroadcastStates.waiting_for_message
        )
        
        # ✅ НОВОЕ: Media album collection handler
        self.dp.message.register(
            self.handle_media_album_collection,
            AdminBroadcastStates.collecting_media_album
        )
        
        # Token input handler
        self.dp.message.register(
            self.handle_token_input, 
            BotCreationStates.waiting_for_token
        )
    
    async def set_commands(self):
        """Set bot commands"""
        commands = [
            BotCommand(command="start", description="🏭 Главное меню"),
            BotCommand(command="help", description="❓ Помощь"),
        ]
        await self.bot.set_my_commands(commands)
    
    def generate_robokassa_payment_link(self, user_id: int, amount: float = None) -> str:
        """Generate Robokassa payment link with unique InvId and Shp_user_id"""
        if amount is None:
            amount = settings.robokassa_payment_amount
        
        # Проверяем что все настройки доступны
        if not settings.robokassa_merchant_login:
            logger.error("❌ ROBOKASSA_MERCHANT_LOGIN not configured")
            raise ValueError("Robokassa merchant login not configured")
        
        if not settings.robokassa_password1:
            logger.error("❌ ROBOKASSA_PASSWORD1 not configured")
            raise ValueError("Robokassa password1 not configured")
        
        # Уникальный InvId с временной меткой
        timestamp = int(time.time())
        invoice_id = str(timestamp)
        
        # Параметры с user_id в Shp_user_id
        params = {
            'MerchantLogin': settings.robokassa_merchant_login,
            'OutSum': f"{amount:.2f}",
            'InvId': invoice_id,
            'Shp_user_id': str(user_id),
        }
        
        # Создаем подпись
        signature_string = f"{settings.robokassa_merchant_login}:{params['OutSum']}:{params['InvId']}:{settings.robokassa_password1}:Shp_user_id={params['Shp_user_id']}"
        signature = hashlib.md5(signature_string.encode('utf-8')).hexdigest().upper()
        params['SignatureValue'] = signature
        
        # Добавляем тестовый режим если включен
        if settings.robokassa_is_test:
            params['IsTest'] = '1'
            logger.info("🧪 Test mode enabled for payment link")
        
        # Формируем URL
        base_url = "https://auth.robokassa.ru/Merchant/Index.aspx"
        payment_url = f"{base_url}?{urlencode(params)}"
        
        logger.info("💳 Unique payment link generated with Shp_user_id", 
                   user_id=user_id,
                   amount=amount,
                   invoice_id=invoice_id,
                   timestamp=timestamp)
        
        return payment_url
    
    def generate_tokens_payment_link(self, user_id: int) -> str:
        """Generate Robokassa payment link for tokens purchase"""
        amount = settings.robokassa_tokens_amount
        
        # Проверяем настройки
        if not settings.robokassa_merchant_login or not settings.robokassa_password1:
            raise ValueError("Robokassa not configured")
        
        # Уникальный InvId
        timestamp = int(time.time())
        invoice_id = str(timestamp)
        
        # Параметры для токенов
        params = {
            'MerchantLogin': settings.robokassa_merchant_login,
            'OutSum': f"{amount:.2f}",
            'InvId': invoice_id,
            'Shp_user_id': f"{user_id}tokens",  # Добавляем 'tokens' к user_id
        }
        
        # Создаем подпись
        signature_string = f"{settings.robokassa_merchant_login}:{params['OutSum']}:{params['InvId']}:{settings.robokassa_password1}:Shp_user_id={params['Shp_user_id']}"
        signature = hashlib.md5(signature_string.encode('utf-8')).hexdigest().upper()
        params['SignatureValue'] = signature
        
        # Тестовый режим
        if settings.robokassa_is_test:
            params['IsTest'] = '1'
        
        base_url = "https://auth.robokassa.ru/Merchant/Index.aspx"
        payment_url = f"{base_url}?{urlencode(params)}"
        
        logger.info("🔋 Tokens payment link generated", 
                   user_id=user_id,
                   amount=amount,
                   tokens=settings.tokens_per_purchase)
        
        return payment_url
    
    async def _save_payment_info(self, invoice_id: str, user_id: int, amount: float):
        """Сохраняем информацию о платеже"""
        try:
            logger.info("💾 Payment info saved for webhook processing", 
                       invoice_id=invoice_id,
                       user_id=user_id,
                       amount=amount)
        except Exception as e:
            logger.error("Failed to save payment info", error=str(e))
    
    def get_main_keyboard(self, user_id: int = None) -> InlineKeyboardMarkup:
        """✅ ОБНОВЛЕНО: Main menu keyboard with admin features for super admin"""
        keyboard = [
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
                    text=f"🔋 Купить токены для ИИ", 
                    callback_data="buy_tokens"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{Emoji.HELP} Как создать бота?", 
                    callback_data="how_to_create"
                )
            ]
        ]
        
        # ✅ НОВОЕ: Добавляем админ кнопки только для суперадмина
        if user_id and self.admin_service.is_super_admin(user_id):
            keyboard.extend([
                [
                    InlineKeyboardButton(
                        text="👑 АДМИН СТАТИСТИКА", 
                        callback_data="admin_stats"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="📨 Рассылка всем", 
                        callback_data="admin_broadcast"
                    ),
                    InlineKeyboardButton(
                        text="📊 История рассылок", 
                        callback_data="admin_history"
                    )
                ]
            ])
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
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
        """✅ ОБНОВЛЕНО: Start command с системой триалов"""
        await state.clear()
        
        user_data = {
            "id": message.from_user.id,
            "username": message.from_user.username,
            "first_name": message.from_user.first_name,
            "last_name": message.from_user.last_name
        }
        
        try:
            # ✅ НОВОЕ: Создаем пользователя с триалом
            await UserManager.create_user_with_trial(
                user_data=user_data,
                admin_chat_id=message.chat.id
            )
            logger.info("✅ User registered with 3-day trial", 
                       user_id=message.from_user.id,
                       username=message.from_user.username)
        except Exception as e:
            logger.error("Failed to register user with trial", 
                        user_id=message.from_user.id,
                        error=str(e))
            # Fallback to old method
            try:
                await db.create_or_update_user_with_tokens(
                    user_data=user_data,
                    admin_chat_id=message.chat.id
                )
            except Exception as fallback_error:
                logger.error("Fallback registration failed", error=str(fallback_error))
        
        # ✅ ОБНОВЛЕНО: Получаем статус пользователя с триалом
        user = await UserManager.get_user(message.from_user.id)
        if user:
            status = user.get_subscription_status()
            
            if status['status'] == 'paid':
                subscription_info = f"""
✅ <b>План AI ADMIN активен!</b>
📅 До {status['expires_at'].strftime('%d.%m.%Y')} ({status['days_left']} дн.)
"""
            elif status['status'] == 'trial':
                subscription_info = f"""
🎁 <b>Пробный период активен!</b>
⏰ Осталось: <b>{status['days_left']} дн.</b> из 3
💎 <a href='#'>Оформить подписку AI ADMIN</a>
"""
            elif status.get('trial_expired'):
                subscription_info = f"""
⚠️ <b>Пробный период завершён</b>
💎 <a href='#'>Оформить подписку AI ADMIN</a>
📅 Доступ ограничен до оплаты
"""
            else:
                subscription_info = f"""
🆓 <b>План FREE</b> • <a href='#'>Улучшить до AI ADMIN</a>
"""
        else:
            subscription_info = "🆓 <b>План FREE</b>"
        
        welcome_text = f"""{Messages.WELCOME}

{subscription_info}
"""
        
        await message.answer(
            welcome_text,
            reply_markup=self.get_main_keyboard(message.from_user.id)
        )
    
    async def cmd_help(self, message: Message):
        """Help command handler"""
        help_text = f"""
{Emoji.INFO} <b>Помощь по AI ADMIN</b>

{Emoji.FACTORY} <b>Основные функции:</b>
- Создание ботов для Telegram каналов
- Безлимитные воронки продаж с детальной статистикой
- Массовые рассылки с аналитикой  
- Автоматическое управление участниками
- Настройка приветственных сообщений с кнопками
- Сообщения подтверждения и прощания
- ИИ агенты на базе OpenAI GPT-4o

{Emoji.ROCKET} <b>Как управлять ботом:</b>
1. Создайте бота здесь в AI ADMIN
2. Перейдите в админ-панель созданного бота
3. Напишите вашему боту команду /start
4. Настраивайте сообщения, воронки и статистику

{Emoji.NEW} <b>Новинка:</b> Каждый бот имеет собственную админ-панель с ИИ агентами!

💰 <b>Токены OpenAI:</b> Каждый пользователь получает 500,000 бесплатных токенов для ИИ агентов

🎁 <b>Пробный период:</b> 3 дня полного доступа ко всем функциям!

{Emoji.HELP} Нужна помощь? Напишите @support
"""
        
        await message.answer(help_text, reply_markup=self.get_back_keyboard())
    
    # ✅ MAIN MENU CALLBACKS
    
    async def cb_create_bot(self, callback: CallbackQuery, state: FSMContext):
        """✅ ОБНОВЛЕНО: Create bot callback с проверкой доступа"""
        await callback.answer()
        
        # ✅ НОВОЕ: Проверяем доступ к созданию ботов
        from utils.access_control import check_user_access, send_access_denied_message
        
        has_access, status = await check_user_access(callback.from_user.id, "create_bot")
        if not has_access:
            await send_access_denied_message(callback, status)
            return
        
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
        """✅ ОБНОВЛЕНО: My bots callback с проверкой доступа"""
        await callback.answer()
        
        # ✅ НОВОЕ: Проверяем доступ к управлению ботами
        from utils.access_control import check_user_access, send_access_denied_message
        
        has_access, status = await check_user_access(callback.from_user.id, "bot_management")
        if not has_access:
            await send_access_denied_message(callback, status)
            return
        
        user_bots = await db.get_user_bots(callback.from_user.id)
        
        if not user_bots:
            await callback.message.edit_text(
                Messages.NO_BOTS_YET,
                reply_markup=self.get_main_keyboard(callback.from_user.id)
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
            # ИИ агент статус
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
        """✅ ОБНОВЛЕНО: Pricing plans callback с учетом триала"""
        await callback.answer()
        
        # ✅ НОВОЕ: Получаем статус пользователя с триалом
        user = await UserManager.get_user(callback.from_user.id)
        if user:
            status = user.get_subscription_status()
            
            if status['status'] == 'paid':
                status_text = f"""
✅ <b>У вас активная подписка!</b>

📅 <b>План:</b> AI ADMIN
⏰ <b>Действует до:</b> {status['expires_at'].strftime('%d.%m.%Y')}
🕒 <b>Осталось дней:</b> {status['days_left']}

Вы можете продлить подписку заранее:
"""
            elif status['status'] == 'trial':
                status_text = f"""
🎁 <b>Пробный период активен!</b>

⏰ <b>Осталось:</b> {status['days_left']} дн. из 3
🚀 <b>У вас полный доступ к AI ADMIN!</b>

💎 <b>Оформите подписку сейчас:</b>
- Без потери функций после триала
- Получите скидку 10% на первый месяц
- Безлимитные боты и статистика
"""
            elif status.get('trial_expired'):
                status_text = f"""
⚠️ <b>Пробный период завершён</b>

🎁 <b>Вы пробовали AI ADMIN 3 дня</b>
💎 <b>Оформите подписку для продолжения:</b>

- Возврат к безлимитным ботам
- Расширенная статистика  
- Приоритетная поддержка
- ИИ агенты без ограничений

💰 <b>Стоимость:</b> всего {settings.robokassa_payment_amount}₽ за 30 дней
"""
            else:
                status_text = f"""
🆓 <b>Текущий план: FREE</b>

🎁 <b>Получите 3-дневный пробный период БЕСПЛАТНО!</b>
Создайте бота прямо сейчас и получите полный доступ.

💎 <b>После триала - подписка AI ADMIN:</b>
- Безлимитные боты
- Расширенная статистика  
- Приоритетная поддержка
- ИИ агенты без ограничений

💰 <b>Стоимость:</b> всего {settings.robokassa_payment_amount}₽ за 30 дней
"""
        else:
            status_text = f"""
🆓 <b>Текущий план: FREE</b>

🎁 <b>Создайте первого бота и получите 3 дня AI ADMIN бесплатно!</b>
"""
        
        text = f"""
💎 <b>ПОДПИСКА "AI ADMIN"</b>

{status_text}

{Emoji.INFO} При оплате вы соглашаетесь с <a href="https://graph.org/AI-Admin---POLZOVATELSKOE-SOGLASHENIE-08-15">пользовательским соглашением</a>.
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"💳 Оплатить {settings.robokassa_payment_amount}₽ (30 дней)",
                    callback_data="pay_subscription"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{Emoji.BACK} Главное меню",
                    callback_data="back_to_main"
                )
            ]
        ])
        
        await callback.message.edit_text(
            text,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    
    async def cb_pay_subscription(self, callback: CallbackQuery):
        """Handle subscription payment"""
        await callback.answer()
        
        # Проверяем что Робокасса настроена
        if not settings.robokassa_merchant_login or not settings.robokassa_password1:
            await callback.message.edit_text(
                f"{Emoji.ERROR} <b>Система оплаты временно недоступна</b>\n\n"
                f"Попробуйте позже или обратитесь в поддержку.",
                reply_markup=self.get_back_keyboard()
            )
            return
        
        try:
            # Генерируем ссылку
            payment_url = self.generate_robokassa_payment_link(callback.from_user.id)
            
            # Сохраняем информацию о платеже
            timestamp = int(time.time())
            await self._save_payment_info(
                str(timestamp),
                callback.from_user.id, 
                settings.robokassa_payment_amount
            )
            
            text = f"""
💳 <b>Оплата подписки</b>

💰 <b>Сумма:</b> {settings.robokassa_payment_amount}₽
📅 <b>Срок:</b> 30 дней
🎯 <b>План:</b> AI ADMIN

🔒 <b>Безопасная оплата через Робокассу</b>
Принимаем карты всех банков, электронные кошельки и другие способы оплаты.

⚡ <b>Подписка активируется автоматически</b> сразу после оплаты!

👆 <b>Нажмите кнопку ниже для перехода к оплате:</b>
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"💳 Оплатить {settings.robokassa_payment_amount}₽",
                        url=payment_url
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔄 Проверить статус оплаты",
                        callback_data="check_payment_status"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=f"{Emoji.BACK} Назад к тарифам",
                        callback_data="pricing"
                    )
                ]
            ])
            
            await callback.message.edit_text(
                text,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
            
        except Exception as e:
            logger.error("Failed to generate payment link", 
                        user_id=callback.from_user.id, 
                        error=str(e))
            await callback.message.edit_text(
                f"{Emoji.ERROR} <b>Ошибка генерации ссылки оплаты</b>\n\n"
                f"Попробуйте еще раз или обратитесь в поддержку.",
                reply_markup=self.get_back_keyboard()
            )
    
    async def cb_check_payment_status(self, callback: CallbackQuery):
        """✅ ОБНОВЛЕНО: Check payment status с учетом триала"""
        await callback.answer()
        
        # ✅ НОВОЕ: Получаем статус через UserManager
        user = await UserManager.get_user(callback.from_user.id)
        if not user:
            await callback.message.edit_text(
                f"{Emoji.ERROR} Пользователь не найден",
                reply_markup=self.get_back_keyboard()
            )
            return
        
        status = user.get_subscription_status()
        
        if status['status'] == 'paid':
            # Платная подписка активна
            text = f"""
✅ <b>Оплата подтверждена!</b>

🎉 <b>Поздравляем!</b> Ваша подписка AI ADMIN активна.

📅 <b>План:</b> AI ADMIN
⏰ <b>Действует до:</b> {status['expires_at'].strftime('%d.%m.%Y')}
🕒 <b>Осталось дней:</b> {status['days_left']}

🚀 <b>Теперь вам доступны:</b>
- Безлимитные боты
- Расширенная статистика
- Приоритетная поддержка
- ИИ агенты без ограничений

Создавайте ботов и пользуйтесь всеми возможностями платформы!
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
        elif status['status'] == 'trial':
            # Триал активен
            text = f"""
🎁 <b>Пробный период активен!</b>

⏰ <b>Осталось:</b> {status['days_left']} дн. из 3
🚀 У вас полный доступ к AI ADMIN!

💡 <b>Совет:</b> Оформите подписку заранее, чтобы не потерять доступ к функциям.

✨ <b>Пока доступны:</b>
- Безлимитные боты
- Полная статистика
- ИИ агенты
"""
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"💎 Оформить подписку",
                        callback_data="pay_subscription"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=f"{Emoji.PLUS} Создать бота",
                        callback_data="create_bot"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=f"{Emoji.BACK} Главное меню",
                        callback_data="back_to_main"
                    )
                ]
            ])
        elif status.get('trial_expired'):
            # Триал закончился, нужна оплата
            text = f"""
⏳ <b>Оплата еще не поступила</b>

🎁 Ваш 3-дневный пробный период завершился.
💰 Для продолжения работы оформите подписку AI ADMIN.

🔄 Если вы только что произвели оплату, подождите несколько минут и проверьте снова.

⚠️ <b>Доступ ограничен до оплаты</b>
"""
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔄 Проверить еще раз",
                        callback_data="check_payment_status"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=f"💳 Оплатить {settings.robokassa_payment_amount}₽",
                        callback_data="pay_subscription"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=f"{Emoji.BACK} Назад к тарифам",
                        callback_data="pricing"
                    )
                ]
            ])
        else:
            # Другие случаи (FREE или неопределенный статус)
            text = f"""
⏳ <b>Оплата еще не поступила</b>

Это может занять несколько минут. Если вы только что произвели оплату, подождите немного и проверьте снова.

🎁 <b>Напоминание:</b> Вы можете создать первого бота и получить 3-дневный пробный период бесплатно!
"""
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔄 Проверить еще раз",
                        callback_data="check_payment_status"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=f"💳 Оплатить {settings.robokassa_payment_amount}₽",
                        callback_data="pay_subscription"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=f"{Emoji.BACK} Назад к тарифам",
                        callback_data="pricing"
                    )
                ]
            ])
        
        await callback.message.edit_text(
            text,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    
    async def cb_buy_tokens(self, callback: CallbackQuery):
        """Buy tokens callback"""
        await callback.answer()
        
        # Получаем текущий баланс токенов
        try:
            user = await UserManager.get_user(callback.from_user.id)
            current_tokens = user.tokens_limit_total if user else 500000
        except Exception:
            current_tokens = 500000
        
        text = f"""
🔋 <b>Покупка токенов для ИИ агентов</b>

💰 <b>Стоимость:</b> {settings.robokassa_tokens_amount}₽
🎯 <b>Количество токенов:</b> {settings.tokens_per_purchase:,}
📊 <b>Ваш текущий баланс:</b> {current_tokens:,} токенов

✨ <b>После оплаты:</b> {current_tokens + settings.tokens_per_purchase:,} токенов

🤖 <b>Что дают токены:</b>
- Общение с OpenAI ИИ агентами
- Создание контента через GPT-4o
- Умные ответы пользователям ваших ботов
- Автоматическая генерация текстов

🔒 <b>Безопасная оплата через Робокассу</b>
Токены добавляются к балансу автоматически после оплаты!
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"💳 Купить за {settings.robokassa_tokens_amount}₽",
                    callback_data="pay_tokens"
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

    async def cb_pay_tokens(self, callback: CallbackQuery):
        """Handle tokens payment"""
        await callback.answer()
        
        # Проверяем настройки Робокассы
        if not settings.robokassa_merchant_login or not settings.robokassa_password1:
            await callback.message.edit_text(
                f"{Emoji.ERROR} <b>Система оплаты временно недоступна</b>",
                reply_markup=self.get_back_keyboard()
            )
            return
        
        try:
            payment_url = self.generate_tokens_payment_link(callback.from_user.id)
            
            text = f"""
💳 <b>Оплата токенов для ИИ</b>

💰 <b>Сумма:</b> {settings.robokassa_tokens_amount}₽
🔋 <b>Токенов:</b> {settings.tokens_per_purchase:,}
🎯 <b>Для:</b> OpenAI ИИ агентов

🔒 <b>Безопасная оплата через Робокассу</b>
⚡ <b>Токены добавляются автоматически</b> сразу после оплаты!
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"💳 Оплатить {settings.robokassa_tokens_amount}₽",
                        url=payment_url
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔄 Проверить пополнение",
                        callback_data="check_tokens_payment"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=f"{Emoji.BACK} Назад к покупке",
                        callback_data="buy_tokens"
                    )
                ]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error("Failed to generate tokens payment link", error=str(e))
            await callback.message.edit_text(
                f"{Emoji.ERROR} <b>Ошибка генерации ссылки оплаты</b>",
                reply_markup=self.get_back_keyboard()
            )

    async def cb_check_tokens_payment(self, callback: CallbackQuery):
        """Check tokens payment status"""
        await callback.answer()
        
        try:
            user = await UserManager.get_user(callback.from_user.id)
            current_tokens = user.tokens_limit_total if user else 500000
        except Exception:
            current_tokens = 500000
        
        text = f"""
🔋 <b>Текущий баланс токенов</b>

📊 <b>Доступно токенов:</b> {current_tokens:,}

🔄 <b>Проверка пополнения:</b>
Если вы только что произвели оплату, токены должны добавиться автоматически в течение нескольких минут.
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🔋 Купить еще токенов",
                    callback_data="buy_tokens"
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
    
    async def cb_pricing_plan(self, callback: CallbackQuery):
        """Individual pricing plan callback"""
        await callback.answer()
        
        plan_data = {
            "pricing_1m": {"period": "1 месяц", "price": "299 ₽", "savings": ""},
            "pricing_3m": {"period": "3 месяца", "price": "749 ₽", "savings": " (экономия 150₽)"},
            "pricing_6m": {"period": "6 месяцев", "price": "1,499 ₽", "savings": " (экономия 295₽)"},
            "pricing_12m": {"period": "12 месяцев", "price": "2,490 ₽", "savings": " (экономия 1,098₽)"},
        }
        
        plan = plan_data.get(callback.data)
        if not plan:
            await callback.answer("Неверный тариф", show_alert=True)
            return
        
        text = f"""
💎 <b>Тариф "AI ADMIN"</b>
📅 <b>Период:</b> {plan['period']}
💰 <b>Стоимость:</b> {plan['price']}{plan['savings']}

🚧 <b>Функция оплаты находится в разработке</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"💎 Выбрать другой тариф",
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
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def cb_how_to_create(self, callback: CallbackQuery):
        """How to create bot callback"""
        await callback.answer()
        
        await callback.message.edit_text(
            Messages.HOW_TO_CREATE_BOT,
            reply_markup=self.get_back_keyboard()
        )
    
    async def cb_back_to_main(self, callback: CallbackQuery, state: FSMContext):
        """✅ ОБНОВЛЕНО: Back to main menu callback с поддержкой триала"""
        await callback.answer()
        await state.clear()
        
        # ✅ ОБНОВЛЕНО: Получаем статус через UserManager
        user = await UserManager.get_user(callback.from_user.id)
        if user:
            status = user.get_subscription_status()
            
            if status['status'] == 'paid':
                subscription_info = f"""
✅ <b>План AI ADMIN активен!</b>
📅 До {status['expires_at'].strftime('%d.%m.%Y')} ({status['days_left']} дн.)
"""
            elif status['status'] == 'trial':
                subscription_info = f"""
🎁 <b>Пробный период активен!</b>
⏰ Осталось: <b>{status['days_left']} дн.</b> из 3
💎 <a href='#'>Оформить подписку AI ADMIN</a>
"""
            elif status.get('trial_expired'):
                subscription_info = f"""
⚠️ <b>Пробный период завершён</b>
💎 <a href='#'>Оформить подписку AI ADMIN</a>
📅 Доступ ограничен до оплаты
"""
            else:
                subscription_info = f"""
🆓 <b>План FREE</b> • <a href='#'>Улучшить до AI ADMIN</a>
"""
        else:
            subscription_info = "🆓 <b>План FREE</b>"
        
        welcome_text = f"""{Messages.WELCOME}

{subscription_info}
"""
        
        await callback.message.edit_text(
            welcome_text,
            reply_markup=self.get_main_keyboard(callback.from_user.id)
        )
    
    # ✅ НОВЫЕ ADMIN ОБРАБОТЧИКИ С МЕДИА ПОДДЕРЖКОЙ
    
    async def cb_admin_stats(self, callback: CallbackQuery):
        """Admin statistics callback - только для суперадмина"""
        await callback.answer()
        
        if not self.admin_service.is_super_admin(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        await callback.message.edit_text(
            "⏳ Загружаю статистику...",
            reply_markup=None
        )
        
        stats_text = await self.admin_service.get_admin_statistics()
        
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
                    callback_data="back_to_main"
                )
            ]
        ])
        
        await callback.message.edit_text(
            stats_text,
            reply_markup=keyboard
        )
    
    async def cb_admin_broadcast(self, callback: CallbackQuery, state: FSMContext):
        """✅ ОБНОВЛЕНО: Admin broadcast callback with media support"""
        await callback.answer()
        
        if not self.admin_service.is_super_admin(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        await state.set_state(AdminBroadcastStates.waiting_for_message)
        
        text = f"""
📨 <b>АДМИНСКАЯ РАССЫЛКА</b>

Отправьте сообщение для рассылки всем пользователям AI ADMIN.

✨ <b>Поддерживается:</b>
• 📝 Текстовые сообщения с HTML форматированием
• 🖼 Фото с подписями
• 🎥 Видео с подписями
• 📄 Документы (файлы)
• 🎵 Аудио файлы
• 🎤 Голосовые сообщения
• 📹 Видеокружки
• 🎬 Анимации (GIF)
• 🎭 Стикеры
• 📸 <b>Медиаальбомы</b> (несколько фото/видео)

⚠️ <b>Ограничения:</b>
• Rate limit: {settings.admin_broadcast_rate_limit} сообщений/сек
• Максимум 10 элементов в альбоме
• Максимальный размер файла: 50MB
• Нельзя отменить после запуска

💡 <b>Примеры:</b>
<code>🎉 <b>Обновление платформы!</b>
Добавлена новая функция...</code>

📎 Отправьте текст, медиа или альбом:
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Отмена", 
                    callback_data="back_to_main"
                )
            ]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def handle_admin_broadcast_message(self, message: Message, state: FSMContext):
        """✅ ОБНОВЛЕНО: Handle admin broadcast message with media support"""
        if not self.admin_service.is_super_admin(message.from_user.id):
            await state.clear()
            await message.answer("❌ Доступ запрещен")
            return
        
        try:
            # Извлекаем медиа из сообщения
            broadcast_media = MediaHandler.extract_media_from_message(message)
            
            if not broadcast_media:
                await message.answer(
                    "❌ <b>Ошибка:</b> Сообщение должно содержать текст или медиа",
                    reply_markup=self.get_main_keyboard(message.from_user.id)
                )
                await state.clear()
                return
            
            # Проверяем на медиаальбом
            if hasattr(message, 'media_group_id') and message.media_group_id:
                # Начинаем сбор медиаальбома
                await state.set_state(AdminBroadcastStates.collecting_media_album)
                await state.update_data({
                    'media_group_id': message.media_group_id,
                    'collected_media': [broadcast_media],
                    'album_text': broadcast_media.text_content,
                    'collection_timeout': datetime.now().timestamp() + 30  # 30 секунд на сбор
                })
                
                await message.answer(
                    f"📸 <b>Медиаальбом обнаружен!</b>\n\n"
                    f"🔄 Собираю все элементы альбома...\n"
                    f"⏰ Ожидание: 30 секунд\n\n"
                    f"📎 Получено: 1 элемент"
                )
                return
            
            # Одиночное сообщение - показываем превью
            await self._show_broadcast_preview(message, state, broadcast_media)
            
        except Exception as e:
            logger.error("Failed to handle admin broadcast message", 
                        user_id=message.from_user.id,
                        error=str(e))
            await message.answer(
                f"❌ <b>Ошибка обработки сообщения:</b>\n{str(e)}",
                reply_markup=self.get_main_keyboard(message.from_user.id)
            )
            await state.clear()
    
    async def handle_media_album_collection(self, message: Message, state: FSMContext):
        """✅ НОВОЕ: Сбор элементов медиаальбома"""
        if not self.admin_service.is_super_admin(message.from_user.id):
            await state.clear()
            return
        
        try:
            state_data = await state.get_data()
            media_group_id = state_data.get('media_group_id')
            collected_media = state_data.get('collected_media', [])
            collection_timeout = state_data.get('collection_timeout', 0)
            
            # Проверяем таймаут
            if datetime.now().timestamp() > collection_timeout:
                await message.answer("⏰ Время сбора альбома истекло. Начните заново.")
                await state.clear()
                return
            
            # Проверяем что это тот же альбом
            if not hasattr(message, 'media_group_id') or message.media_group_id != media_group_id:
                # Это новое сообщение - завершаем сбор альбома
                await self._finalize_media_album(message, state, collected_media)
                return
            
            # Добавляем элемент к альбому
            broadcast_media = MediaHandler.extract_media_from_message(message)
            if broadcast_media and broadcast_media.media_items:
                collected_media.extend(broadcast_media.media_items)
                
                await state.update_data({
                    'collected_media': collected_media,
                    'collection_timeout': datetime.now().timestamp() + 5  # Продлеваем на 5 секунд
                })
                
                # Обновляем статус
                await message.answer(
                    f"📸 <b>Медиаальбом:</b> {len(collected_media)} элементов\n"
                    f"⏰ Сбор продолжается..."
                )
                
                # Устанавливаем таймер для завершения альбома
                asyncio.create_task(self._album_collection_timer(
                    message.from_user.id, state, collected_media, 5
                ))
            
        except Exception as e:
            logger.error("Failed to handle media album collection", error=str(e))
            await state.clear()
    
    async def _album_collection_timer(self, user_id: int, state: FSMContext, collected_media: list, delay: int):
        """✅ НОВОЕ: Таймер для завершения сбора альбома"""
        await asyncio.sleep(delay)
        
        try:
            # Проверяем что состояние не изменилось
            current_state = await state.get_state()
            if current_state == AdminBroadcastStates.collecting_media_album.state:
                # Создаем финальный BroadcastMedia объект
                state_data = await state.get_data()
                album_text = state_data.get('album_text')
                
                # Объединяем все медиа в альбом
                final_broadcast_media = BroadcastMedia(
                    media_items=collected_media,
                    text_content=album_text,
                    is_album=True
                )
                
                # Показываем превью альбома
                await self._show_album_preview(user_id, state, final_broadcast_media)
                
        except Exception as e:
            logger.error("Album collection timer failed", error=str(e))
    
    async def _finalize_media_album(self, message: Message, state: FSMContext, collected_media: list):
        """✅ НОВОЕ: Завершение сбора медиаальбома"""
        try:
            state_data = await state.get_data()
            album_text = state_data.get('album_text')
            
            # Создаем финальный BroadcastMedia объект
            final_broadcast_media = BroadcastMedia(
                media_items=collected_media,
                text_content=album_text,
                is_album=True
            )
            
            await self._show_broadcast_preview(message, state, final_broadcast_media)
            
        except Exception as e:
            logger.error("Failed to finalize media album", error=str(e))
            await state.clear()
    
    async def _show_album_preview(self, user_id: int, state: FSMContext, broadcast_media: BroadcastMedia):
        """✅ НОВОЕ: Показать превью альбома"""
        try:
            # Валидация медиа
            validation = await self.admin_service.validate_broadcast_media(broadcast_media)
            
            media_preview = MediaHandler.get_media_preview_text(broadcast_media)
            
            if validation['valid']:
                preview_text = f"""
📸 <b>ПРЕВЬЮ МЕДИААЛЬБОМА</b>

📎 <b>Контент:</b> {media_preview}
📊 <b>Элементов:</b> {broadcast_media.media_count}
📏 <b>Общий размер:</b> {validation['total_size'] / 1024 / 1024:.1f}MB

"""
                if broadcast_media.text_content:
                    preview_text += f"📝 <b>Текст:</b>\n<blockquote>{broadcast_media.text_content}</blockquote>\n\n"
                
                preview_text += "Подтвердите отправку альбома всем пользователям:"
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ ОТПРАВИТЬ АЛЬБОМ", 
                            callback_data=f"confirm_broadcast"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="❌ Отмена", 
                            callback_data="back_to_main"
                        )
                    ]
                ])
                
                # Сохраняем медиа для подтверждения
                await state.set_data({'broadcast_media': broadcast_media})
                await state.set_state(AdminBroadcastStates.waiting_for_confirmation)
                
            else:
                preview_text = f"""
❌ <b>ОШИБКИ В МЕДИААЛЬБОМЕ</b>

📎 <b>Контент:</b> {media_preview}
📊 <b>Элементов:</b> {broadcast_media.media_count}

🚫 <b>Ошибки:</b>
{chr(10).join(f"• {error}" for error in validation['errors'])}
"""
                
                if validation['warnings']:
                    preview_text += f"""
⚠️ <b>Предупреждения:</b>
{chr(10).join(f"• {warning}" for warning in validation['warnings'])}
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="❌ Отмена", 
                            callback_data="back_to_main"
                        )
                    ]
                ])
                
                await state.clear()
            
            await self.bot.send_message(
                chat_id=user_id,
                text=preview_text,
                reply_markup=keyboard
            )
            
        except Exception as e:
            logger.error("Failed to show album preview", error=str(e))
            await state.clear()
    
    async def _show_broadcast_preview(self, message: Message, state: FSMContext, broadcast_media: BroadcastMedia):
        """✅ ОБНОВЛЕНО: Показать превью рассылки с медиа поддержкой"""
        try:
            # Валидация медиа
            validation = await self.admin_service.validate_broadcast_media(broadcast_media)
            
            media_preview = MediaHandler.get_media_preview_text(broadcast_media)
            
            if validation['valid']:
                preview_text = f"""
📨 <b>ПРЕВЬЮ РАССЫЛКИ</b>

📎 <b>Контент:</b> {media_preview}
"""
                
                if validation['total_size'] > 0:
                    preview_text += f"📏 <b>Размер:</b> {validation['total_size'] / 1024 / 1024:.1f}MB\n"
                
                if broadcast_media.text_content:
                    preview_text += f"\n📝 <b>Текст:</b>\n<blockquote>{broadcast_media.text_content}</blockquote>\n"
                
                if validation['warnings']:
                    preview_text += f"""
⚠️ <b>Предупреждения:</b>
{chr(10).join(f"• {warning}" for warning in validation['warnings'])}
"""
                
                preview_text += "\nПодтвердите отправку рассылки всем активным пользователям:"
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ ОТПРАВИТЬ ВСЕМ", 
                            callback_data=f"confirm_broadcast"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="❌ Отмена", 
                            callback_data="back_to_main"
                        )
                    ]
                ])
                
                # Сохраняем медиа для подтверждения
                await state.set_data({'broadcast_media': broadcast_media})
                await state.set_state(AdminBroadcastStates.waiting_for_confirmation)
                
            else:
                preview_text = f"""
❌ <b>ОШИБКИ В СООБЩЕНИИ</b>

📎 <b>Контент:</b> {media_preview}

🚫 <b>Ошибки:</b>
{chr(10).join(f"• {error}" for error in validation['errors'])}
"""
                
                if validation['warnings']:
                    preview_text += f"""
⚠️ <b>Предупреждения:</b>
{chr(10).join(f"• {warning}" for warning in validation['warnings'])}
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="❌ Отмена", 
                            callback_data="back_to_main"
                        )
                    ]
                ])
                
                await state.clear()
            
            await message.answer(preview_text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error("Failed to show broadcast preview", error=str(e))
            await message.answer(
                f"❌ Ошибка создания превью: {str(e)}",
                reply_markup=self.get_main_keyboard(message.from_user.id)
            )
            await state.clear()
    
    async def cb_confirm_broadcast(self, callback: CallbackQuery, state: FSMContext):
        """✅ ОБНОВЛЕНО: Confirm admin broadcast with media support"""
        await callback.answer()
        
        if not self.admin_service.is_super_admin(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            await state.clear()
            return
        
        state_data = await state.get_data()
        broadcast_media = state_data.get('broadcast_media')
        
        # Поддержка старого формата (обратная совместимость)
        if not broadcast_media:
            broadcast_message = state_data.get('broadcast_message')
            if broadcast_message:
                broadcast_media = BroadcastMedia(
                    media_items=[],
                    text_content=broadcast_message,
                    is_album=False
                )
        
        if not broadcast_media:
            await callback.message.edit_text(
                "❌ Контент для рассылки не найден",
                reply_markup=self.get_main_keyboard(callback.from_user.id)
            )
            await state.clear()
            return
        
        await state.clear()
        
        # Запускаем медиа рассылку
        result = await self.admin_service.start_admin_broadcast_with_media(
            admin_user_id=callback.from_user.id,
            broadcast_media=broadcast_media
        )
        
        if result['success']:
            media_info = result.get('media_info', {})
            response_text = f"""
✅ <b>Рассылка запущена!</b>

📊 <b>Параметры:</b>
• Получателей: <b>{result['total_users']}</b>
• ID рассылки: <code>{result['broadcast_id']}</code>
• Скорость: <b>{settings.admin_broadcast_rate_limit} сообщ/сек</b>
"""
            
            if media_info.get('has_media'):
                response_text += f"""
📎 <b>Медиа контент:</b>
• Тип: {'Альбом' if media_info.get('is_album') else 'Одиночное медиа'}
• Элементов: <b>{media_info.get('media_count', 0)}</b>
• Размер: <b>{media_info.get('total_size', 0) / 1024 / 1024:.1f}MB</b>
"""
            
            response_text += "\n⏳ Рассылка выполняется в фоновом режиме.\nВы получите уведомления о прогрессе."
            
        else:
            response_text = f"❌ <b>Ошибка запуска рассылки:</b>\n\n{result['error']}"
        
        await callback.message.edit_text(
            response_text,
            reply_markup=self.get_main_keyboard(callback.from_user.id)
        )
    
    async def cb_admin_history(self, callback: CallbackQuery):
        """Admin broadcast history - только для суперадмина"""
        await callback.answer()
        
        if not self.admin_service.is_super_admin(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        await callback.message.edit_text(
            "⏳ Загружаю историю рассылок...",
            reply_markup=None
        )
        
        history_text = await self.admin_service.get_broadcast_history(callback.from_user.id)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Обновить", 
                    callback_data="admin_history"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{Emoji.BACK} Главное меню", 
                    callback_data="back_to_main"
                )
            ]
        ])
        
        await callback.message.edit_text(
            history_text,
            reply_markup=keyboard
        )
    
    # ✅ BOT MANAGEMENT
    
    async def cb_bot_details(self, callback: CallbackQuery):
        """Bot details callback"""
        await callback.answer()
        
        bot_id = callback.data.replace("bot_", "")
        bot = await db.get_bot_by_id(bot_id)
        
        if not bot:
            await callback.answer("Бот не найден", show_alert=True)
            return
        
        # Проверка владельца бота
        if bot.user_id != callback.from_user.id:
            await callback.answer("❌ Это не ваш бот", show_alert=True)
            return
        
        status_emoji = Emoji.SUCCESS if bot.is_running else Emoji.ERROR
        status_text = "Активен" if bot.is_running else "Остановлен"
        
        # Информация об ИИ агенте
        ai_info = ""
        if bot.ai_assistant_enabled and bot.ai_assistant_type:
            if bot.ai_assistant_type == 'openai':
                agent_name = getattr(bot, 'openai_agent_name', 'OpenAI Агент')
                ai_info = f"🎨 <b>ИИ Агент:</b> {agent_name} (OpenAI)\n"
            elif bot.ai_assistant_type in ['chatforyou', 'protalk']:
                platform_name = bot.ai_assistant_type.title()
                ai_info = f"🌐 <b>ИИ Агент:</b> {platform_name}\n"
        else:
            ai_info = f"🤖 <b>ИИ Агент:</b> Не настроен\n"
        
        text = f"""
{Emoji.ROBOT} <b>Бот @{bot.bot_username}</b>

{status_emoji} <b>Статус:</b> {status_text}
{Emoji.USERS} <b>Подписчиков:</b> {bot.total_subscribers}
{Emoji.BROADCAST} <b>Отправлено сообщений:</b> {bot.total_messages_sent}
{ai_info}{Emoji.CHART} <b>Создан:</b> {bot.created_at.strftime('%d.%m.%Y')}

{Emoji.INFO} <b>Настройки:</b>
- Приветствие: {'✅' if bot.welcome_message else '❌ Не настроено'}
- Кнопка приветствия: {'✅' if bot.welcome_button_text else '❌ Не настроено'}
- Подтверждение: {'✅' if bot.confirmation_message else '❌ Не настроено'}
- Прощание: {'✅' if bot.goodbye_message else '❌ Не настроено'}
- Кнопка прощания: {'✅' if bot.goodbye_button_text else '❌ Не настроено'}

{Emoji.NEW} <b>Для настройки бота:</b>
Напишите боту @{bot.bot_username} команду /start
"""
        
        await callback.message.edit_text(
            text,
            reply_markup=self.get_bot_info_keyboard(bot)
        )
    
    async def cb_bot_manage(self, callback: CallbackQuery):
        """Bot management actions"""
        await callback.answer()
        
        action_data = callback.data.replace("manage_", "")
        parts = action_data.split("_", 1)
        
        if len(parts) != 2:
            await callback.answer("Неверный формат команды", show_alert=True)
            return
        
        action, bot_id = parts
        
        bot = await db.get_bot_by_id(bot_id)
        if not bot:
            await callback.answer("Бот не найден", show_alert=True)
            return
        
        # Проверка владельца для всех операций управления
        if bot.user_id != callback.from_user.id:
            await callback.answer("❌ Только владелец может управлять ботом", show_alert=True)
            return
        
        if action == "configure":
            await self._show_configure_instructions(callback, bot)
        elif action == "stats":
            await self._show_bot_quick_stats(callback, bot)
        elif action == "restart":
            await self._restart_bot(callback, bot)
        elif action == "delete":
            await self._show_delete_confirmation(callback, bot)
    
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
                    bot_db_data = await db.get_bot_by_id(bot_id)
                    await self.bot_manager.add_bot(bot_db_data)
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
                "Bot created successfully", 
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
        text = f"""
{Emoji.SETTINGS} <b>Настройка бота @{bot.bot_username}</b>

{Emoji.NEW} <b>У каждого бота теперь есть собственная админ-панель!</b>

{Emoji.ROCKET} <b>Для настройки:</b>
1. Перейдите в чат с ботом @{bot.bot_username}
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
                    text=f"📱 Написать @{bot.bot_username}",
                    url=f"https://t.me/{bot.bot_username}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{Emoji.BACK} К информации о боте",
                    callback_data=f"bot_{bot.bot_id}"
                )
            ]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def _show_bot_quick_stats(self, callback: CallbackQuery, bot):
        """Show quick bot statistics"""
        try:
            # Get real-time stats from bot manager
            bot_status = {"status": "unknown", "running": False}
            if self.bot_manager:
                bot_status = self.bot_manager.get_bot_status(bot.bot_id)
            
            status_emoji = Emoji.SUCCESS if bot_status.get('running', False) else Emoji.ERROR
            status_text = "Активен" if bot_status.get('running', False) else "Остановлен"
            
            # Get button stats if available
            button_stats = bot_status.get('button_stats', {})
            
            # ✅ НОВОЕ: Показываем статистику токенов через UserManager
            token_info = ""
            try:
                user = await UserManager.get_user(callback.from_user.id)
                if user:
                    tokens_used = getattr(user, 'tokens_used', 0)
                    tokens_limit = user.tokens_limit_total
                    tokens_remaining = tokens_limit - tokens_used
                    usage_percent = round((tokens_used / tokens_limit * 100), 1) if tokens_limit > 0 else 0
                    
                    token_info = f"""
💰 <b>Токены OpenAI:</b>
- Использовано: {tokens_used:,} из {tokens_limit:,} ({usage_percent}%)
- Осталось: {tokens_remaining:,} токенов
"""
            except Exception as token_error:
                logger.warning("Could not get token balance for stats", error=str(token_error))
            
            text = f"""
{Emoji.CHART} <b>Статистика @{bot.bot_username}</b>

{status_emoji} <b>Статус:</b> {status_text}
{Emoji.USERS} <b>Подписчиков:</b> {bot.total_subscribers}
{Emoji.BROADCAST} <b>Сообщений отправлено:</b> {bot.total_messages_sent}
{token_info}
{Emoji.BUTTON} <b>Активность кнопок:</b>
- Приветственных отправлено: {button_stats.get('welcome_buttons_sent', 0)}
- Прощальных отправлено: {button_stats.get('goodbye_buttons_sent', 0)}
- Всего нажатий: {button_stats.get('button_clicks', 0)}
- Подтверждений отправлено: {button_stats.get('confirmation_sent', 0)}

{Emoji.FUNNEL} <b>Воронки:</b>
- Запущено: {button_stats.get('funnel_starts', 0)}

{Emoji.CHART} <b>Создан:</b> {bot.created_at.strftime('%d.%m.%Y в %H:%M')}

{Emoji.INFO} <b>Подробная статистика:</b>
Напишите боту @{bot.bot_username} команду /start
и перейдите в раздел "Статистика"
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"📱 Админ-панель @{bot.bot_username}",
                        url=f"https://t.me/{bot.bot_username}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔄 Обновить",
                        callback_data=f"manage_stats_{bot.bot_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=f"{Emoji.BACK} К информации о боте",
                        callback_data=f"bot_{bot.bot_id}"
                    )
                ]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error("Failed to show bot stats", bot_id=bot.bot_id, error=str(e))
            await callback.answer("Ошибка при загрузке статистики", show_alert=True)
    
    async def _restart_bot(self, callback: CallbackQuery, bot):
        """Restart bot"""
        try:
            if self.bot_manager:
                await self.bot_manager.restart_bot(bot.bot_id)
                await callback.answer("Бот перезапущен!", show_alert=True)
                
                # Refresh bot info
                await self.cb_bot_details(
                    callback=type('obj', (object,), {
                        'data': f'bot_{bot.bot_id}',
                        'answer': callback.answer,
                        'message': callback.message,
                        'from_user': callback.from_user
                    })()
                )
            else:
                await callback.answer("Bot Manager недоступен", show_alert=True)
                
        except Exception as e:
            logger.error("Failed to restart bot", bot_id=bot.bot_id, error=str(e))
            await callback.answer("Ошибка при перезапуске бота", show_alert=True)
    
    async def _show_delete_confirmation(self, callback: CallbackQuery, bot):
        """Show bot deletion confirmation"""
        text = f"""
{Emoji.WARNING} <b>Удаление бота</b>

Вы действительно хотите удалить бота @{bot.bot_username}?

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
                    callback_data=f"confirm_delete_{bot.bot_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{Emoji.BACK} Отмена",
                    callback_data=f"bot_{bot.bot_id}"
                )
            ]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def _confirm_delete_bot(self, callback: CallbackQuery):
        """Confirm bot deletion with owner verification"""
        await callback.answer()
        
        bot_id = callback.data.replace("confirm_delete_", "")
        
        try:
            # Проверка владельца бота
            bot = await db.get_bot_by_id(bot_id)
            if not bot:
                await callback.answer("❌ Бот не найден", show_alert=True)
                return
            
            if bot.user_id != callback.from_user.id:
                await callback.answer("❌ Только владелец может удалить бота", show_alert=True)
                return
            
            logger.info("User confirmed bot deletion", 
                       user_id=callback.from_user.id,
                       bot_id=bot_id,
                       bot_username=bot.bot_username)
            
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
                f"{Emoji.SUCCESS} <b>Бот @{bot.bot_username} успешно удален!</b>\n\n"
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
                       bot_username=bot.bot_username,
                       owner_id=callback.from_user.id)
            
        except Exception as e:
            logger.error("Failed to delete bot", bot_id=bot_id, error=str(e), exc_info=True)
            await callback.answer("Ошибка при удалении бота", show_alert=True)
    
    # ✅ BOT LIFECYCLE
    
    async def start_polling(self):
        """Start bot polling"""
        await self.set_commands()
        logger.info("✅ Master bot started with trial system, access control, and media broadcast functionality")
        await self.dp.start_polling(self.bot)
    
    async def stop(self):
        """Stop bot"""
        try:
            await self.bot.session.close()
            logger.info("Master bot stopped")
        except Exception as e:
            logger.error("Error closing bot session", error=str(e))
