"""
Обработчики событий канала
✅ ТОЛЬКО: События канала (join_request, chat_member) 
✅ ТОЛЬКО: Кнопка приветствия + показ кнопки ИИ
❌ БЕЗ: Обработка диалога с ИИ (это в ai_handlers.py)

АРХИТЕКТУРА:
- Этот файл показывает кнопку ИИ, но НЕ обрабатывает её нажатие
- Обработка нажатий кнопки ИИ и диалога - в ai_handlers.py  
- Четкое разделение ответственности без дублирования
"""

import asyncio
import structlog
from aiogram import Dispatcher, F
from aiogram.types import (
    ChatMemberUpdated, ChatJoinRequest, Message,
    ReplyKeyboardRemove
)
from aiogram.filters import IS_MEMBER, IS_NOT_MEMBER, ChatMemberUpdatedFilter
from aiogram.exceptions import TelegramForbiddenError
from aiogram.enums import ParseMode
from ..keyboards import UserKeyboards
from ..formatters import MessageFormatter

logger = structlog.get_logger()


def register_channel_handlers(dp: Dispatcher, **kwargs):
    """✅ ИСПРАВЛЕНО: Регистрация только событий канала + показ кнопки ИИ"""
    
    db = kwargs['db']
    bot_config = kwargs['bot_config']
    funnel_manager = kwargs['funnel_manager']
    user_bot = kwargs.get('user_bot')
    owner_user_id = bot_config['owner_user_id']
    
    logger.info("📺 Registering channel handlers (EVENTS + AI BUTTON DISPLAY ONLY)", 
               bot_id=bot_config['bot_id'])
    
    try:
        handler = ChannelHandler(db, bot_config, funnel_manager, user_bot)
        
        # ===== СОБЫТИЯ КАНАЛА =====
        dp.chat_join_request.register(handler.handle_join_request_extended)
        
        dp.chat_member.register(
            handler.handle_chat_member_join,
            ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER)
        )
        
        dp.chat_member.register(
            handler.handle_chat_member_leave,
            ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER)
        )
        
        # ===== КНОПКА ПРИВЕТСТВИЯ (ТОЛЬКО НЕ АДМИНЫ) =====
        dp.message.register(
            handler.handle_welcome_button_click,
            F.chat.type == "private",
            F.text.regexp(r'^.{1,50}$'),
            F.from_user.id != owner_user_id
        )
        
        logger.info("✅ Channel handlers registered successfully", 
                   bot_id=bot_config['bot_id'],
                   owner_user_id=owner_user_id,
                   handlers=["join_request", "chat_member_join", "chat_member_leave", "welcome_button"])
        
    except Exception as e:
        logger.error("💥 Failed to register channel handlers", 
                    bot_id=kwargs.get('bot_config', {}).get('bot_id', 'unknown'),
                    error=str(e), exc_info=True)
        raise


class ChannelHandler:
    """✅ ИСПРАВЛЕНО: Обработчик событий канала + показ кнопки ИИ (БЕЗ обработки диалогов)"""
    
    def __init__(self, db, bot_config: dict, funnel_manager, user_bot):
        self.db = db
        self.bot_config = bot_config
        self.bot_id = bot_config['bot_id']
        self.owner_user_id = bot_config['owner_user_id']
        self.funnel_manager = funnel_manager
        self.formatter = MessageFormatter()
        self.user_bot = user_bot
        
        # Экземпляр бота для отправки сообщений
        self.bot = bot_config.get('bot')
        
        # Статистика (не критичная)
        self.stats = bot_config.get('stats', {})
        
        logger.info("✅ ChannelHandler initialized (EVENTS + AI BUTTON DISPLAY ONLY)", 
                   bot_id=self.bot_id,
                   owner_user_id=self.owner_user_id,
                   has_bot_instance=bool(self.bot))

    # ===== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ =====
    
    async def _get_fresh_message_config(self) -> dict:
        """Получить свежие настройки сообщений из БД"""
        try:
            bot = await self.db.get_bot_by_id(self.bot_id, fresh=True)
            
            if not bot:
                logger.warning("⚠️ Bot not found for fresh config", bot_id=self.bot_id)
                return {}
            
            config = {
                'welcome_message': bot.welcome_message,
                'welcome_button_text': bot.welcome_button_text,
                'confirmation_message': bot.confirmation_message,
                'goodbye_message': bot.goodbye_message,
                'goodbye_button_text': bot.goodbye_button_text,
                'goodbye_button_url': bot.goodbye_button_url
            }
            
            logger.debug("✅ Fresh message config loaded", 
                        bot_id=self.bot_id,
                        has_welcome=bool(config.get('welcome_message')),
                        has_welcome_button=bool(config.get('welcome_button_text')),
                        has_confirmation=bool(config.get('confirmation_message')))
            
            return config
            
        except Exception as e:
            logger.error("💥 Failed to get fresh message config", 
                        bot_id=self.bot_id, error=str(e))
            return {}
    
    async def _get_fresh_ai_config(self) -> dict:
        """Получить свежую конфигурацию ИИ агента"""
        try:
            ai_config = await self.db.get_ai_config(self.bot_id)
            
            if not ai_config:
                logger.debug("❌ No AI config found", bot_id=self.bot_id)
                return {}
            
            logger.debug("✅ Fresh AI config loaded", 
                        bot_id=self.bot_id,
                        ai_enabled=ai_config.get('enabled', False),
                        ai_type=ai_config.get('type'),
                        has_agent_id=bool(ai_config.get('agent_id')))
            
            return ai_config
            
        except Exception as e:
            logger.error("💥 Failed to get fresh AI config", 
                        bot_id=self.bot_id, error=str(e))
            return {}
    
    async def _should_show_ai_button(self, user_id: int) -> tuple[bool, str]:
        """
        ✅ КЛЮЧЕВАЯ ФУНКЦИЯ: Проверка показа кнопки ИИ
        
        Возвращает решение показывать ли кнопку "🤖 Позвать ИИ"
        Обработка самого нажатия - в ai_handlers.py
        
        Returns:
            tuple: (should_show, reason)
        """
        try:
            logger.info("🔍 Checking AI button visibility", 
                       user_id=user_id, bot_id=self.bot_id)
            
            # Получаем свежие данные из БД
            fresh_ai_config = await self._get_fresh_ai_config()
            
            if not fresh_ai_config:
                reason = "No AI config in database"
                logger.debug(f"❌ AI button check failed: {reason}", 
                            user_id=user_id, bot_id=self.bot_id)
                return False, reason
            
            # Проверяем что ИИ включен
            ai_enabled = fresh_ai_config.get('enabled', False)
            if not ai_enabled:
                reason = "AI agent is disabled in config"
                logger.debug(f"❌ AI button check failed: {reason}", 
                            user_id=user_id, bot_id=self.bot_id)
                return False, reason
            
            # Проверяем наличие агента
            ai_agent_id = fresh_ai_config.get('agent_id')
            if not ai_agent_id:
                reason = "No AI agent ID configured"
                logger.debug(f"❌ AI button check failed: {reason}", 
                            user_id=user_id, bot_id=self.bot_id)
                return False, reason
            
            logger.info("✅ AI button visibility check passed", 
                       user_id=user_id,
                       bot_id=self.bot_id,
                       ai_type=fresh_ai_config.get('type'),
                       agent_id_preview=ai_agent_id[:15] + "..." if len(ai_agent_id) > 15 else ai_agent_id)
            
            return True, "AI agent is available"
            
        except Exception as e:
            reason = f"Error checking AI config: {str(e)}"
            logger.error("💥 Error in AI button visibility check", 
                        bot_id=self.bot_id, 
                        user_id=user_id, 
                        error=str(e))
            return False, reason
    
    # ===== ОБРАБОТЧИКИ СОБЫТИЙ КАНАЛА =====
    
    async def handle_join_request_extended(self, join_request: ChatJoinRequest):
        """Обработка заявки на вступление с детальным логированием"""
        try:
            self.stats['join_requests_processed'] += 1
            
            user = join_request.from_user
            
            if user.is_bot:
                logger.info("🤖 Skipping bot join request", 
                           bot_id=self.bot_id, 
                           user_id=user.id,
                           bot_username=user.username)
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
            
            logger.info("🚪 User join request received", 
                       bot_id=self.bot_id,
                       user_id=user.id,
                       target_chat_id=target_chat_id,
                       contact_method=contact_method,
                       username=user.username,
                       first_name=user.first_name)
            
            # Одобряем заявку
            try:
                await join_request.approve()
                logger.info("✅ Join request approved", bot_id=self.bot_id, user_id=user.id)
            except Exception as e:
                logger.error("❌ Failed to approve join request", 
                            bot_id=self.bot_id, 
                            user_id=user.id, 
                            error=str(e))
                return
            
            # Небольшая задержка перед отправкой
            await asyncio.sleep(0.5)
            
            # Отправляем приветствие
            success = await self._send_welcome_message_with_button(user, target_chat_id, contact_method)
            
            if not success and contact_method == "user_chat_id":
                logger.info("🔄 Retrying welcome with user.id fallback", 
                           bot_id=self.bot_id, 
                           user_id=user.id)
                await self._send_welcome_message_with_button(user, user.id, "user.id (retry)")
            
        except Exception as e:
            logger.error("💥 Critical error in join request handler", 
                        bot_id=self.bot_id, 
                        error=str(e), 
                        exc_info=True)
    
    async def handle_chat_member_join(self, chat_member_update: ChatMemberUpdated):
        """Обработка добавления пользователя администратором"""
        try:
            self.stats['admin_adds_processed'] += 1
            
            user = chat_member_update.new_chat_member.user
            
            if user.is_bot:
                return
            
            logger.info("👤 User added by admin", 
                       bot_id=self.bot_id, 
                       user_id=user.id,
                       username=user.username)
            
            await self._send_welcome_message_cautious(user, user.id)
            
        except Exception as e:
            logger.error("❌ Error handling user join via admin", 
                        bot_id=self.bot_id, 
                        error=str(e))
    
    async def handle_chat_member_leave(self, chat_member_update: ChatMemberUpdated):
        """Обработка выхода пользователя из канала"""
        try:
            user = chat_member_update.old_chat_member.user
            
            if user.is_bot:
                return
            
            logger.info("🚪 User left chat", 
                       bot_id=self.bot_id, 
                       user_id=user.id,
                       username=user.username)
            
            await self._send_goodbye_message_with_button(user)
            
        except Exception as e:
            logger.error("❌ Error handling user leave", 
                        bot_id=self.bot_id, 
                        error=str(e))
    
    # ===== ОБРАБОТЧИК КНОПКИ ПРИВЕТСТВИЯ =====
    
    async def handle_welcome_button_click(self, message: Message):
        """✅ КЛЮЧЕВАЯ ФУНКЦИЯ: Обработка нажатия кнопки приветствия + показ кнопки ИИ"""
        try:
            # Получаем свежие данные для проверки
            config = await self._get_fresh_message_config()
            welcome_button_text = config.get('welcome_button_text')
            
            # Проверяем что нажата правильная кнопка
            if message.text != welcome_button_text:
                logger.debug("❌ Message text doesn't match welcome button", 
                           bot_id=self.bot_id, 
                           user_id=message.from_user.id,
                           expected=welcome_button_text,
                           received=message.text)
                return
            
            user = message.from_user
            logger.info("🔘 Welcome button clicked (verified)", 
                       bot_id=self.bot_id, 
                       user_id=user.id,
                       button_text=welcome_button_text)
            
            self.stats['button_clicks'] += 1
            
            # Сохраняем подписчика с chat_id
            await self.db.create_or_update_subscriber(
                bot_id=self.bot_id,
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                chat_id=message.chat.id
            )
            
            logger.info("✅ Subscriber saved with chat_id", 
                       bot_id=self.bot_id,
                       user_id=user.id,
                       chat_id=message.chat.id)
            
            # Убираем кнопку приветствия
            await message.answer("⏳ Обрабатываем ваш ответ...", reply_markup=ReplyKeyboardRemove())
            
            # Запускаем воронку
            await self._start_user_funnel(user)
            
            # ✅ КЛЮЧЕВАЯ ЛОГИКА: Проверяем наличие агента для показа кнопки ИИ
            has_agent, reason = await self._should_show_ai_button(user.id)
            
            logger.info("🔍 AI button availability for confirmation", 
                       user_id=user.id,
                       has_agent=has_agent,
                       reason=reason)
            
            # Отправляем подтверждение с кнопкой ИИ (если агент есть)
            confirmation_message = config.get('confirmation_message')
            if confirmation_message:
                await self._send_confirmation_with_conditional_ai_button(
                    user, message.chat.id, has_agent
                )
            else:
                await self._send_default_confirmation_with_conditional_ai_button(
                    user, message.chat.id, has_agent
                )
                
        except Exception as e:
            logger.error("💥 Error handling welcome button click", 
                        bot_id=self.bot_id, 
                        user_id=message.from_user.id,
                        error=str(e))
    
    # ===== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ =====
    
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
            success = await self.funnel_manager.start_user_funnel(
                self.bot_id, user.id, user.first_name
            )
            if success:
                self.stats['funnel_starts'] += 1
                logger.info("✅ Funnel started for user", 
                           bot_id=self.bot_id, 
                           user_id=user.id)
        except Exception as e:
            logger.error("❌ Failed to start funnel", 
                        bot_id=self.bot_id, 
                        user_id=user.id, 
                        error=str(e))
    
    # ===== МЕТОДЫ ОТПРАВКИ СООБЩЕНИЙ С УСЛОВНОЙ КНОПКОЙ ИИ =====
    
    async def _send_confirmation_with_conditional_ai_button(self, user, chat_id: int, has_agent: bool):
        """Отправка подтверждения с кнопкой ИИ только если агент есть"""
        config = await self._get_fresh_message_config()
        confirmation_message = config.get('confirmation_message')
        
        if not confirmation_message:
            return
        
        try:
            formatted_message = self.formatter.format_message(confirmation_message, user)
            
            if has_agent:
                keyboard = UserKeyboards.ai_button()
                logger.debug("✅ Showing AI button with confirmation", 
                            bot_id=self.bot_id, user_id=user.id)
            else:
                keyboard = ReplyKeyboardRemove()
                logger.debug("❌ No AI button - agent not available", 
                            bot_id=self.bot_id, user_id=user.id)
            
            if self.bot:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=formatted_message,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard
                )
                
                self.stats['confirmation_sent'] += 1
                await self._update_stats('confirmation_sent')
            
        except Exception as e:
            logger.error("💥 Failed to send confirmation with conditional AI button", 
                        bot_id=self.bot_id, error=str(e))
    
    async def _send_default_confirmation_with_conditional_ai_button(self, user, chat_id: int, has_agent: bool):
        """Отправка дефолтного подтверждения с кнопкой ИИ только если агент есть"""
        try:
            if has_agent:
                keyboard = UserKeyboards.ai_button()
                logger.debug("✅ Showing AI button with default confirmation", 
                            bot_id=self.bot_id, user_id=user.id)
            else:
                keyboard = ReplyKeyboardRemove()
                logger.debug("❌ No AI button - agent not available", 
                            bot_id=self.bot_id, user_id=user.id)
            
            if self.bot:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text="✅ Спасибо! Добро пожаловать!",
                    reply_markup=keyboard
                )
            
        except Exception as e:
            logger.error("💥 Failed to send default confirmation with conditional AI button", 
                        error=str(e))
    
    async def _send_welcome_message_with_button(self, user, target_chat_id: int, contact_method: str) -> bool:
        """Отправка приветственного сообщения с кнопкой"""
        config = await self._get_fresh_message_config()
        welcome_message = config.get('welcome_message')
        welcome_button_text = config.get('welcome_button_text')
        
        if not welcome_message:
            logger.debug("No welcome message configured", bot_id=self.bot_id)
            return True
        
        self.stats['total_attempts'] += 1
        
        try:
            formatted_message = self.formatter.format_message(welcome_message, user)
            
            reply_markup = None
            if welcome_button_text:
                reply_markup = UserKeyboards.welcome_button(welcome_button_text)
                self.stats['welcome_buttons_sent'] += 1
            
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
                           bot_id=self.bot_id, 
                           user_id=user.id, 
                           has_button=bool(reply_markup),
                           contact_method=contact_method)
                return True
            
        except TelegramForbiddenError:
            self.stats['welcome_blocked'] += 1
            logger.warning("❌ Welcome message blocked by user", 
                          bot_id=self.bot_id, 
                          user_id=user.id)
            return False
        except Exception as e:
            logger.error("💥 Failed to send welcome message", 
                        bot_id=self.bot_id, 
                        error=str(e))
            return False

    async def _send_welcome_message_cautious(self, user, target_chat_id: int):
        """Осторожная отправка приветствия для добавленных администратором"""
        config = await self._get_fresh_message_config()
        welcome_message = config.get('welcome_message')
        
        if not welcome_message:
            return
        
        try:
            formatted_message = self.formatter.format_message(welcome_message, user)
            
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
            logger.error("💥 Failed to send message to admin-added user", 
                        bot_id=self.bot_id, error=str(e))

    async def _send_goodbye_message_with_button(self, user):
        """Отправка прощального сообщения с кнопкой"""
        config = await self._get_fresh_message_config()
        goodbye_message = config.get('goodbye_message')
        goodbye_button_text = config.get('goodbye_button_text')
        goodbye_button_url = config.get('goodbye_button_url')
        
        if not goodbye_message:
            return
        
        try:
            formatted_message = self.formatter.format_message(goodbye_message, user)
            
            reply_markup = None
            if goodbye_button_text and goodbye_button_url:
                reply_markup = UserKeyboards.goodbye_button(
                    goodbye_button_text,
                    goodbye_button_url
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
            logger.error("💥 Failed to send goodbye message", 
                        bot_id=self.bot_id, error=str(e))
