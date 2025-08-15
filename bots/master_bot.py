import asyncio
import uuid
from datetime import datetime
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


logger = structlog.get_logger()


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
        self._setup_handlers()
    
    def _setup_handlers(self):
        """✅ ИСПРАВЛЕНО: Setup simplified handlers with proper deletion handler"""
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
        """✅ ОБНОВЛЕНО: Start command handler с инициализацией токенового лимита"""
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
        
        await message.answer(
            Messages.WELCOME,
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
        """Pricing plans callback"""
        await callback.answer()
        
        text = f"""
💎 <b>ТАРИФ "AI ADMIN"</b>

<b>Стоимость подписки:</b>
• 📅 <b>1 месяц</b> — 299 ₽
• 📅 <b>3 месяца</b> — 749 ₽ <i>(экономия 150₽)</i>
• 📅 <b>6 месяцев</b> — 1,499 ₽ <i>(экономия 295₽)</i>
• 📅 <b>12 месяцев</b> — 2,490 ₽ <i>(экономия 1,098₽)</i>

{Emoji.INFO} При оплате вы соглашаетесь с <a href="https://graph.org/AI-Admin---POLZOVATELSKOE-SOGLASHENIE-08-15">пользовательским соглашением</a>.

Выберите срок действия тарифа:
"""
        
        await callback.message.edit_text(
            text,
            reply_markup=self.get_pricing_keyboard(),
            disable_web_page_preview=True
        )
    
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

{Emoji.INFO} При оплате вы соглашаетесь с <a href="https://graph.org/AI-Admin---POLZOVATELSKOE-SOGLASHENIE-08-15">пользовательским соглашением</a>.

🚧 <b>Функция оплаты находится в разработке</b>
Скоро здесь появится возможность оплаты!

Вернитесь к выбору тарифа или в главное меню:
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
        
        await callback.message.edit_text(
            text,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    
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
        """Bot details callback"""
        await callback.answer()
        
        bot_id = callback.data.replace("bot_", "")
        bot = await db.get_bot_by_id(bot_id)
        
        if not bot:
            await callback.answer("Бот не найден", show_alert=True)
            return
        
        # ✅ ДОБАВЛЕНО: Проверка владельца бота
        if bot.user_id != callback.from_user.id:
            await callback.answer("❌ Это не ваш бот", show_alert=True)
            return
        
        status_emoji = Emoji.SUCCESS if bot.is_running else Emoji.ERROR
        status_text = "Активен" if bot.is_running else "Остановлен"
        
        # ✅ НОВОЕ: Показываем информацию об ИИ агенте
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
        
        # Get extended bot info
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
        
        # ✅ ДОБАВЛЕНО: Проверка владельца для всех операций управления
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
            
            # ✅ НОВОЕ: Показываем статистику токенов OpenAI
            token_info = ""
            try:
                # Пытаемся получить информацию о токенах пользователя
                user_token_balance = await db.get_user_token_balance(callback.from_user.id)
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
        """✅ ИСПРАВЛЕНО: Show bot deletion confirmation without temporary handler registration"""
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
        """✅ ИСПРАВЛЕНО: Confirm bot deletion with owner verification"""
        await callback.answer()
        
        bot_id = callback.data.replace("confirm_delete_", "")
        
        try:
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверка владельца бота
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
        logger.info("✅ Master bot started with token limit initialization")
        await self.dp.start_polling(self.bot)
    
    async def stop(self):
        """Stop bot"""
        try:
            await self.bot.session.close()
            logger.info("Master bot stopped")
        except Exception as e:
            logger.error("Error closing bot session", error=str(e))
