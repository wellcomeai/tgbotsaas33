"""
Обработчики событий канала
"""

import asyncio
import structlog
from datetime import datetime
from aiogram import Dispatcher, F, Bot
from aiogram.types import (
    ChatMemberUpdated, ChatJoinRequest, Message,
    ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.filters import IS_MEMBER, IS_NOT_MEMBER, ChatMemberUpdatedFilter
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext

from config import Emoji
from ..states import AISettingsStates
from ..keyboards import UserKeyboards, AIKeyboards
from ..formatters import MessageFormatter

logger = structlog.get_logger()


def register_channel_handlers(dp: Dispatcher, **kwargs):
    """Регистрация обработчиков событий канала"""
    
    db = kwargs['db']
    bot_config = kwargs['bot_config']  # ИЗМЕНЕНО: получаем полную конфигурацию
    funnel_manager = kwargs['funnel_manager']
    ai_assistant = kwargs.get('ai_assistant')
    user_bot = kwargs.get('user_bot')  # Получаем ссылку на UserBot
    
    try:
        handler = ChannelHandler(db, bot_config, funnel_manager, ai_assistant, user_bot)
        
        # Обработчики событий канала
        dp.chat_join_request.register(handler.handle_join_request_extended)
        
        dp.chat_member.register(
            handler.handle_chat_member_join,
            ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER)
        )
        
        dp.chat_member.register(
            handler.handle_chat_member_leave,
            ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER)
        )
        
        # ✅ ИСПРАВЛЕНО: Динамическая регистрация с проверкой текста кнопки приветствия
        welcome_button_text = bot_config.get('welcome_button_text')
        if welcome_button_text:
            dp.message.register(
                handler.handle_welcome_button_click,
                F.text == welcome_button_text  # ✅ Проверяем конкретный текст кнопки
            )
            logger.info("Welcome button handler registered", 
                       bot_id=bot_config['bot_id'], 
                       button_text=welcome_button_text)
        
        # Обработчик кнопки ИИ (без изменений)
        dp.message.register(
            handler.handle_ai_button_click,
            F.text == "🤖 Позвать ИИ"
        )
        
        logger.info("Channel handlers registered successfully", 
                   bot_id=bot_config['bot_id'])
        
    except Exception as e:
        logger.error("Failed to register channel handlers", 
                    bot_id=kwargs.get('bot_config', {}).get('bot_id', 'unknown'),
                    error=str(e), exc_info=True)
        raise


class ChannelHandler:
    """Обработчик событий канала"""
    
    def __init__(self, db, bot_config: dict, funnel_manager, ai_assistant, user_bot):
        self.db = db
        self.bot_config = bot_config
        self.bot_id = bot_config['bot_id']
        self.owner_user_id = bot_config['owner_user_id']
        self.funnel_manager = funnel_manager
        self.ai_assistant = ai_assistant
        self.formatter = MessageFormatter()
        self.user_bot = user_bot  # Сохраняем ссылку на UserBot
        
        # Получаем настройки из конфигурации
        self.bot = bot_config.get('bot')  # Экземпляр бота
        self.welcome_message = bot_config.get('welcome_message')
        self.welcome_button_text = bot_config.get('welcome_button_text')
        self.confirmation_message = bot_config.get('confirmation_message')
        self.goodbye_message = bot_config.get('goodbye_message')
        self.goodbye_button_text = bot_config.get('goodbye_button_text')
        self.goodbye_button_url = bot_config.get('goodbye_button_url')
        self.ai_assistant_id = bot_config.get('ai_assistant_id')
        self.ai_assistant_enabled = bot_config.get('ai_assistant_enabled', False)
        self.ai_assistant_settings = bot_config.get('ai_assistant_settings', {})
        
        # Статистика из конфигурации
        self.stats = bot_config.get('stats', {})
    
    def _should_show_ai_button(self, user_id: int) -> bool:
        """Проверка показывать ли кнопку ИИ"""
        return True
    
    async def _update_stats(self, event_type: str):
        """Обновление статистики"""
        try:
            if event_type in ['welcome_sent', 'goodbye_sent', 'confirmation_sent']:
                await self.db.increment_bot_messages(self.bot_id)
        except Exception as e:
            logger.error("Failed to update stats", bot_id=self.bot_id, error=str(e))
    
    async def _start_user_funnel(self, user):
        """Запуск воронки для пользователя"""
        try:
            success = await self.funnel_manager.start_user_funnel(self.bot_id, user.id, user.first_name)
            if success:
                self.stats['funnel_starts'] += 1
                logger.info("Funnel started for user", bot_id=self.bot_id, user_id=user.id)
        except Exception as e:
            logger.error("Failed to start funnel", bot_id=self.bot_id, user_id=user.id, error=str(e))
    
    async def handle_join_request_extended(self, join_request: ChatJoinRequest):
        """Обработка заявки на вступление"""
        try:
            self.stats['join_requests_processed'] += 1
            
            user = join_request.from_user
            
            if user.is_bot:
                logger.info("🤖 Skipping bot join request", bot_id=self.bot_id, user_id=user.id)
                return
            
            user_chat_id = getattr(join_request, 'user_chat_id', None)
            if user_chat_id is not None:
                self.stats['user_chat_id_available'] += 1
                target_chat_id = user_chat_id
                contact_method = "user_chat_id"
            else:
                self.stats['user_chat_id_missing'] += 1
                target_chat_id = user.id
                contact_method = "user.id (fallback)"
            
            logger.info(
                "🚪 User join request received", 
                bot_id=self.bot_id,
                user_id=user.id,
                target_chat_id=target_chat_id,
                contact_method=contact_method,
                username=user.username,
                has_welcome_button=bool(self.welcome_button_text)
            )
            
            try:
                await join_request.approve()
                logger.info("✅ Join request approved", bot_id=self.bot_id, user_id=user.id)
            except Exception as e:
                logger.error("❌ Failed to approve join request", bot_id=self.bot_id, user_id=user.id, error=str(e))
                return
            
            await asyncio.sleep(0.5)
            
            success = await self._send_welcome_message_with_button(user, target_chat_id, contact_method)
            
            if not success and contact_method == "user_chat_id":
                logger.info("🔄 Retrying with user.id fallback", bot_id=self.bot_id, user_id=user.id)
                await self._send_welcome_message_with_button(user, user.id, "user.id (retry)")
            
        except Exception as e:
            logger.error("💥 Critical error in join request handler", bot_id=self.bot_id, error=str(e), exc_info=True)
    
    async def handle_chat_member_join(self, chat_member_update: ChatMemberUpdated):
        """Обработка добавления пользователя администратором"""
        try:
            self.stats['admin_adds_processed'] += 1
            
            user = chat_member_update.new_chat_member.user
            
            if user.is_bot:
                return
            
            logger.info("👤 User added by admin", bot_id=self.bot_id, user_id=user.id)
            await self._send_welcome_message_cautious(user, user.id)
            
        except Exception as e:
            logger.error("❌ Error handling user join via admin", bot_id=self.bot_id, error=str(e))
    
    async def handle_chat_member_leave(self, chat_member_update: ChatMemberUpdated):
        """Обработка выхода пользователя из канала"""
        try:
            user = chat_member_update.old_chat_member.user
            
            if user.is_bot:
                return
            
            logger.info("🚪 User left chat", bot_id=self.bot_id, user_id=user.id)
            await self._send_goodbye_message_with_button(user)
            
        except Exception as e:
            logger.error("❌ Error handling user leave", bot_id=self.bot_id, error=str(e))
    
    async def handle_welcome_button_click(self, message: Message):
        """✅ ИСПРАВЛЕНО: Обработка нажатия кнопки приветствия"""
        try:
            # ✅ УБРАЛИ проверку текста - фильтр уже настроен правильно при регистрации
            user = message.from_user
            
            logger.info("🔘 Welcome button clicked", bot_id=self.bot_id, user_id=user.id)
            
            self.stats['button_clicks'] += 1
            
            # Убираем кнопку приветствия
            await message.answer("⏳ Обрабатываем ваш ответ...", reply_markup=ReplyKeyboardRemove())
            
            # Запускаем воронку
            await self._start_user_funnel(user)
            
            # Отправляем подтверждение с кнопкой ИИ (если включен)
            if self.confirmation_message:
                await self._send_confirmation_with_ai_button(user, message.chat.id)
            else:
                await self._send_default_confirmation_with_ai_button(user, message.chat.id)
                
        except Exception as e:
            logger.error("💥 Error handling welcome button click", bot_id=self.bot_id, error=str(e))
    
    async def handle_ai_button_click(self, message: Message):
        """Обработка нажатия кнопки вызова ИИ"""
        try:
            user = message.from_user
            
            # Проверяем что ИИ включен и настроен
            if not self.ai_assistant_enabled or not self.ai_assistant_id:
                await message.answer(
                    "❌ ИИ агент временно недоступен.",
                    reply_markup=ReplyKeyboardRemove()
                )
                return
            
            logger.info("🤖 AI button clicked", bot_id=self.bot_id, user_id=user.id)
            
            # Проверка лимита сообщений
            daily_limit = self.ai_assistant_settings.get('daily_limit')
            if daily_limit:
                usage_count = await self.db.get_ai_usage_today(self.bot_id, user.id)
                if usage_count >= daily_limit:
                    await message.answer(
                        f"❌ Лимит сообщений исчерпан!\n"
                        f"Вы можете отправить {daily_limit} сообщений ИИ агенту в день.\n"
                        f"Сегодня отправлено: {usage_count}\n"
                        f"Попробуйте завтра.",
                        reply_markup=ReplyKeyboardRemove()
                    )
                    return
            
            # Переводим в режим общения с ИИ
            from aiogram.fsm.context import FSMContext
            
            # Получаем FSM контекст (эта часть может потребовать доработки)
            remaining_messages = ""
            if daily_limit:
                usage_count = await self.db.get_ai_usage_today(self.bot_id, user.id)
                remaining = daily_limit - usage_count
                remaining_messages = f"\n📊 Осталось сообщений: {remaining}"
            
            welcome_text = f"""
🤖 <b>Добро пожаловать в чат с ИИ агентом!</b>

Задавайте любые вопросы, я постараюсь помочь.{remaining_messages}

<b>Напишите ваш вопрос:</b>
"""
            
            await message.answer(welcome_text, reply_markup=AIKeyboards.conversation_menu())
            
        except Exception as e:
            logger.error("💥 Error handling AI button click", bot_id=self.bot_id, error=str(e))
            await message.answer(
                "❌ Произошла ошибка при запуске ИИ агента.",
                reply_markup=ReplyKeyboardRemove()
            )
    
    async def _send_welcome_message_with_button(self, user, target_chat_id: int, contact_method: str) -> bool:
        """Отправка приветственного сообщения с кнопкой"""
        if not self.welcome_message:
            logger.debug("No welcome message configured", bot_id=self.bot_id)
            return True
        
        self.stats['total_attempts'] += 1
        
        try:
            formatted_message = self.formatter.format_message(self.welcome_message, user)
            
            reply_markup = None
            if self.welcome_button_text:
                reply_markup = UserKeyboards.welcome_button(self.welcome_button_text)
                self.stats['welcome_buttons_sent'] += 1
            
            # Используем экземпляр бота из конфигурации
            if self.bot:
                sent_message = await self.bot.send_message(
                    chat_id=target_chat_id,
                    text=formatted_message,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
                
                self.stats['welcome_sent'] += 1
                await self._update_stats('welcome_sent')
                
                logger.info("✅ Welcome message sent", 
                           bot_id=self.bot_id, user_id=user.id, has_button=bool(reply_markup))
                return True
            
        except TelegramForbiddenError:
            self.stats['welcome_blocked'] += 1
            return False
        except Exception as e:
            logger.error("💥 Failed to send welcome message", bot_id=self.bot_id, error=str(e))
            return False
    
    async def _send_welcome_message_cautious(self, user, target_chat_id: int):
        """Осторожная отправка приветствия для добавленных администратором"""
        if not self.welcome_message:
            return
        
        try:
            formatted_message = self.formatter.format_message(self.welcome_message, user)
            
            if self.bot:
                await self.bot.send_message(
                    chat_id=target_chat_id,
                    text=formatted_message,
                    parse_mode=ParseMode.HTML
                )
                
                self.stats['welcome_sent'] += 1
                await self._update_stats('welcome_sent')
            
        except TelegramForbiddenError:
            self.stats['welcome_blocked'] += 1
        except Exception as e:
            logger.error("💥 Failed to send message to admin-added user", bot_id=self.bot_id, error=str(e))
    
    async def _send_confirmation_with_ai_button(self, user, chat_id: int):
        """Отправка подтверждения с кнопкой ИИ"""
        if not self.confirmation_message:
            return
        
        try:
            formatted_message = self.formatter.format_message(self.confirmation_message, user)
            
            # Подготавливаем клавиатуру
            keyboard_buttons = None
            
            # Добавляем кнопку ИИ если включен и настроен
            if (self.ai_assistant_enabled and 
                self.ai_assistant_id and 
                self._should_show_ai_button(user.id)):
                
                keyboard_buttons = UserKeyboards.ai_button()
            else:
                keyboard_buttons = ReplyKeyboardRemove()
            
            if self.bot:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=formatted_message,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard_buttons
                )
                
                self.stats['confirmation_sent'] += 1
                await self._update_stats('confirmation_sent')
            
        except Exception as e:
            logger.error("💥 Failed to send confirmation with AI button", bot_id=self.bot_id, error=str(e))
    
    async def _send_default_confirmation_with_ai_button(self, user, chat_id: int):
        """Отправка дефолтного подтверждения с кнопкой ИИ"""
        try:
            # Подготавливаем клавиатуру
            keyboard_buttons = None
            
            # Добавляем кнопку ИИ если включен и настроен
            if (self.ai_assistant_enabled and 
                self.ai_assistant_id and 
                self._should_show_ai_button(user.id)):
                
                keyboard_buttons = UserKeyboards.ai_button()
            else:
                keyboard_buttons = ReplyKeyboardRemove()
            
            if self.bot:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text="✅ Спасибо! Добро пожаловать!",
                    reply_markup=keyboard_buttons
                )
            
        except Exception as e:
            logger.error("💥 Failed to send default confirmation with AI button", error=str(e))
    
    async def _send_goodbye_message_with_button(self, user):
        """Отправка прощального сообщения с кнопкой"""
        if not self.goodbye_message:
            return
        
        try:
            formatted_message = self.formatter.format_message(self.goodbye_message, user)
            
            reply_markup = None
            if self.goodbye_button_text and self.goodbye_button_url:
                reply_markup = UserKeyboards.goodbye_button(
                    self.goodbye_button_text,
                    self.goodbye_button_url
                )
                self.stats['goodbye_buttons_sent'] += 1
            
            if self.bot:
                await self.bot.send_message(
                    chat_id=user.id,
                    text=formatted_message,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
                
                self.stats['goodbye_sent'] += 1
                await self._update_stats('goodbye_sent')
            
        except TelegramForbiddenError:
            self.stats['goodbye_blocked'] += 1
        except Exception as e:
            logger.error("💥 Failed to send goodbye message", bot_id=self.bot_id, error=str(e))
