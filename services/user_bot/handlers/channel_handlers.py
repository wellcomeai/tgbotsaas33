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
from services.notifications import send_token_exhausted_notification, send_token_warning_notification
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
        
        # ✅ ИСПРАВЛЕНО: НЕ используем кэшированные данные для ИИ агента
        # Удаляем эти строки:
        # self.ai_assistant_id = bot_config.get('ai_assistant_id')
        # self.ai_assistant_settings = bot_config.get('ai_assistant_settings', {})
        
        # Статистика из конфигурации
        self.stats = bot_config.get('stats', {})
    
    async def _should_show_ai_button(self, user_id: int) -> bool:
        """✅ ИСПРАВЛЕНО: Проверка показа кнопки ИИ со свежими данными из БД"""
        try:
            # ✅ КРИТИЧНО: Получаем свежие данные из БД, а не кэшированные!
            fresh_config = await self.db.get_ai_config(self.bot_id)
            
            if not fresh_config:
                logger.debug("No AI config found", bot_id=self.bot_id, user_id=user_id)
                return False
            
            # Проверяем что ИИ включен и настроен
            ai_enabled = fresh_config.get('enabled', False)
            ai_agent_id = fresh_config.get('agent_id')
            
            has_agent = ai_enabled and bool(ai_agent_id)
            
            logger.debug("🔍 AI button visibility check (fresh data)", 
                        user_id=user_id,
                        bot_id=self.bot_id,
                        ai_enabled=ai_enabled,
                        has_agent_id=bool(ai_agent_id),
                        will_show=has_agent)
            
            return has_agent
            
        except Exception as e:
            logger.error("💥 Error checking AI button visibility", 
                        bot_id=self.bot_id, 
                        user_id=user_id, 
                        error=str(e))
            # В случае ошибки возвращаем False (безопасный fallback)
            return False
    
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
    
    # ===== ОБНОВЛЕННЫЕ МЕТОДЫ ДЛЯ РАБОТЫ С ТОКЕНАМИ =====
    
    async def _check_openai_token_limit(self, user_id: int) -> tuple[bool, str, dict]:
        """
        ✅ ОБНОВЛЕНО: Проверка лимита токенов со свежими данными ИИ агента
        
        Returns:
            tuple: (can_use, message, token_info)
                - can_use: bool - можно ли использовать агента
                - message: str - сообщение для пользователя
                - token_info: dict - информация о токенах
        """
        try:
            # ✅ КРИТИЧНО: Получаем свежие данные об ИИ агенте
            fresh_ai_config = await self.db.get_ai_config(self.bot_id)
            
            if not fresh_ai_config:
                return True, "", {}
            
            # Проверяем, что это OpenAI агент
            ai_type = fresh_ai_config.get('type')
            if ai_type != 'openai':
                return True, "", {}
            
            agent_settings = fresh_ai_config.get('settings', {})
            
            # Получаем информацию о токенах из БД
            token_info = await self.db.get_user_token_balance(self.owner_user_id)
            
            if not token_info:
                logger.warning("❌ No token info found for user", 
                              owner_user_id=self.owner_user_id,
                              bot_id=self.bot_id)
                return False, "❌ Система токенов не инициализирована", {}
            
            tokens_used = token_info.get('total_used', 0)
            tokens_limit = token_info.get('limit', 500000)
            remaining_tokens = tokens_limit - tokens_used
            
            logger.info("🔍 Token limit check", 
                       user_id=user_id,
                       bot_id=self.bot_id,
                       tokens_used=tokens_used,
                       tokens_limit=tokens_limit,
                       remaining_tokens=remaining_tokens)
            
            # Проверяем, исчерпаны ли токены
            if remaining_tokens <= 0:
                # Отправляем уведомление админу если еще не отправляли
                await self._send_token_exhausted_notification(token_info)
                
                return False, f"""
❌ <b>Токены исчерпаны!</b>

Для этого ИИ агента закончились токены.
Использовано: {tokens_used:,} из {tokens_limit:,}

Обратитесь к администратору для пополнения баланса.
""", token_info
            
            # Проверяем, близки ли токены к исчерпанию (90%)
            warning_threshold = tokens_limit * 0.9
            if tokens_used >= warning_threshold and not token_info.get('warning_sent', False):
                await self._send_token_warning_notification(token_info)
            
            return True, "", token_info
            
        except Exception as e:
            logger.error("💥 Error checking token limit", 
                        user_id=user_id,
                        bot_id=self.bot_id,
                        error=str(e),
                        exc_info=True)
            return False, "❌ Ошибка при проверке лимита токенов", {}
    
    async def _send_token_exhausted_notification(self, token_info: dict):
        """Отправка уведомления админу об исчерпании токенов"""
        try:
            # Проверяем, не отправляли ли уже уведомление
            if token_info.get('notification_sent', False):
                return
            
            admin_chat_id = token_info.get('admin_chat_id')
            if not admin_chat_id:
                logger.warning("❌ No admin_chat_id for token notification", 
                              owner_user_id=self.owner_user_id)
                return
            
            tokens_used = token_info.get('total_used', 0)
            tokens_limit = token_info.get('limit', 500000)
            
            # ✅ ИСПРАВЛЕНО: Получаем актуальные данные об агенте
            fresh_ai_config = await self.db.get_ai_config(self.bot_id)
            agent_name = "OpenAI агент"
            if fresh_ai_config and fresh_ai_config.get('settings'):
                agent_name = fresh_ai_config['settings'].get('agent_name', agent_name)
            
            notification_text = f"""
🚨 <b>Токены исчерпаны!</b>

<b>Бот:</b> @{self.bot_config.get('bot_username', 'unknown')}
<b>ИИ Агент:</b> {agent_name}

<b>Использовано:</b> {tokens_used:,} токенов
<b>Лимит:</b> {tokens_limit:,} токенов

❌ <b>Агент остановлен</b> - пользователи не могут им пользоваться.

Для продолжения работы необходимо пополнить баланс токенов.
"""
            
            if self.bot:
                await self.bot.send_message(
                    chat_id=admin_chat_id,
                    text=notification_text,
                    parse_mode=ParseMode.HTML
                )
                
                # Помечаем, что уведомление отправлено
                await self.db.set_token_notification_sent(self.owner_user_id, True)
                
                logger.info("📧 Token exhausted notification sent", 
                           admin_chat_id=admin_chat_id,
                           bot_id=self.bot_id,
                           tokens_used=tokens_used)
            
        except Exception as e:
            logger.error("💥 Failed to send token exhausted notification", 
                        bot_id=self.bot_id,
                        error=str(e))
    
    async def _send_token_warning_notification(self, token_info: dict):
        """Отправка предупреждения админу о скором исчерпании токенов"""
        try:
            admin_chat_id = token_info.get('admin_chat_id')
            if not admin_chat_id:
                return
            
            tokens_used = token_info.get('total_used', 0)
            tokens_limit = token_info.get('limit', 500000)
            remaining_tokens = tokens_limit - tokens_used
            usage_percent = (tokens_used / tokens_limit) * 100
            
            # ✅ ИСПРАВЛЕНО: Получаем актуальные данные об агенте
            fresh_ai_config = await self.db.get_ai_config(self.bot_id)
            agent_name = "OpenAI агент"
            if fresh_ai_config and fresh_ai_config.get('settings'):
                agent_name = fresh_ai_config['settings'].get('agent_name', agent_name)
            
            notification_text = f"""
⚠️ <b>Внимание: Токены заканчиваются!</b>

<b>Бот:</b> @{self.bot_config.get('bot_username', 'unknown')}
<b>ИИ Агент:</b> {agent_name}

<b>Использовано:</b> {tokens_used:,} токенов ({usage_percent:.1f}%)
<b>Осталось:</b> {remaining_tokens:,} токенов
<b>Лимит:</b> {tokens_limit:,} токенов

Рекомендуется пополнить баланс токенов заранее, чтобы избежать остановки агента.
"""
            
            if self.bot:
                await self.bot.send_message(
                    chat_id=admin_chat_id,
                    text=notification_text,
                    parse_mode=ParseMode.HTML
                )
                
                # Помечаем, что предупреждение отправлено
                await self.db.set_token_warning_sent(self.owner_user_id, True)
                
                logger.info("📧 Token warning notification sent", 
                           admin_chat_id=admin_chat_id,
                           bot_id=self.bot_id,
                           usage_percent=usage_percent)
            
        except Exception as e:
            logger.error("💥 Failed to send token warning notification", 
                        bot_id=self.bot_id,
                        error=str(e))
    
    # ===== ОБРАБОТЧИКИ СОБЫТИЙ КАНАЛА (без изменений) =====
    
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
    
    # ===== ✅ ИСПРАВЛЕННЫЕ ОСНОВНЫЕ МЕТОДЫ =====
    
    async def handle_welcome_button_click(self, message: Message):
        """✅ ИСПРАВЛЕНО: Обработка нажатия кнопки приветствия с правильной логикой подтверждения"""
        try:
            user = message.from_user
            
            logger.info("🔘 Welcome button clicked", bot_id=self.bot_id, user_id=user.id)
            
            self.stats['button_clicks'] += 1
            
            # Убираем кнопку приветствия
            await message.answer("⏳ Обрабатываем ваш ответ...", reply_markup=ReplyKeyboardRemove())
            
            # Запускаем воронку
            await self._start_user_funnel(user)
            
            # ✅ НОВАЯ ЛОГИКА: проверяем наличие агента со свежими данными
            has_agent = await self._should_show_ai_button(user.id)
            
            if self.confirmation_message:
                # Отправляем настроенное подтверждение
                await self._send_confirmation_with_conditional_ai_button(user, message.chat.id, has_agent)
            else:
                # Отправляем дефолтное подтверждение
                await self._send_default_confirmation_with_conditional_ai_button(user, message.chat.id, has_agent)
                
        except Exception as e:
            logger.error("💥 Error handling welcome button click", bot_id=self.bot_id, error=str(e))
    
    async def handle_ai_button_click(self, message: Message):
        """✅ ОБНОВЛЕНО: Обработка нажатия кнопки вызова ИИ со свежими данными и проверкой токенов"""
        try:
            user = message.from_user
            
            # ✅ КРИТИЧНО: Базовая проверка доступности агента со свежими данными
            if not await self._should_show_ai_button(user.id):
                logger.warning("❌ AI button clicked but agent not available", 
                              bot_id=self.bot_id, 
                              user_id=user.id)
                return
            
            logger.info("🤖 AI button clicked", bot_id=self.bot_id, user_id=user.id)
            
            # ✅ Получаем свежие настройки ИИ агента для лимитов
            fresh_ai_config = await self.db.get_ai_config(self.bot_id)
            agent_settings = fresh_ai_config.get('settings', {}) if fresh_ai_config else {}
            
            # ✅ НОВОЕ: Проверка лимита токенов для OpenAI агентов
            can_use, token_message, token_info = await self._check_openai_token_limit(user.id)
            
            if not can_use:
                logger.warning("❌ Token limit exceeded", 
                              bot_id=self.bot_id,
                              user_id=user.id,
                              tokens_used=token_info.get('total_used', 0),
                              tokens_limit=token_info.get('limit', 0))
                
                await message.answer(
                    token_message,
                    reply_markup=ReplyKeyboardRemove()
                )
                return
            
            # Проверка дневного лимита сообщений (используем свежие настройки)
            daily_limit = agent_settings.get('daily_limit')
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
            
            # Формируем информацию об остатке токенов для OpenAI агентов
            token_display = ""
            if token_info and fresh_ai_config and fresh_ai_config.get('type') == 'openai':
                tokens_used = token_info.get('total_used', 0)
                tokens_limit = token_info.get('limit', 500000)
                remaining_tokens = tokens_limit - tokens_used
                
                token_display = f"\n💰 Токенов осталось: {remaining_tokens:,}"
            
            # Формируем информацию об остатке дневных сообщений
            remaining_messages = ""
            if daily_limit:
                usage_count = await self.db.get_ai_usage_today(self.bot_id, user.id)
                remaining = daily_limit - usage_count
                remaining_messages = f"\n📊 Осталось сообщений: {remaining}"
            
            welcome_text = f"""
🤖 <b>Добро пожаловать в чат с ИИ агентом!</b>

Задавайте любые вопросы, я постараюсь помочь.{remaining_messages}{token_display}

<b>Напишите ваш вопрос:</b>
"""
            
            # Используем обычное меню с reply кнопкой
            await message.answer(welcome_text, reply_markup=AIKeyboards.conversation_menu())
            
            logger.info("✅ AI conversation started", 
                       bot_id=self.bot_id,
                       user_id=user.id,
                       has_token_info=bool(token_info),
                       remaining_tokens=token_info.get('total_used', 0) if token_info else None)
            
        except Exception as e:
            logger.error("💥 Error handling AI button click", bot_id=self.bot_id, error=str(e), exc_info=True)
            # Для обработки ошибок не показываем пользователю детали
            pass
    
    # ===== ✅ НОВЫЕ МЕТОДЫ ДЛЯ УСЛОВНОГО ПОКАЗА КНОПКИ ИИ =====
    
    async def _send_confirmation_with_conditional_ai_button(self, user, chat_id: int, has_agent: bool):
        """✅ НОВОЕ: Отправка подтверждения с кнопкой ИИ только если агент есть"""
        if not self.confirmation_message:
            return
        
        try:
            formatted_message = self.formatter.format_message(self.confirmation_message, user)
            
            # Подготавливаем клавиатуру в зависимости от наличия агента
            if has_agent:
                keyboard = UserKeyboards.ai_button()
                logger.debug("✅ Showing AI button with confirmation", 
                            bot_id=self.bot_id, 
                            user_id=user.id)
            else:
                keyboard = ReplyKeyboardRemove()
                logger.debug("❌ No AI button - agent not available", 
                            bot_id=self.bot_id, 
                            user_id=user.id)
            
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
            logger.error("💥 Failed to send confirmation with conditional AI button", bot_id=self.bot_id, error=str(e))
    
    async def _send_default_confirmation_with_conditional_ai_button(self, user, chat_id: int, has_agent: bool):
        """✅ НОВОЕ: Отправка дефолтного подтверждения с кнопкой ИИ только если агент есть"""
        try:
            # Подготавливаем клавиатуру в зависимости от наличия агента
            if has_agent:
                keyboard = UserKeyboards.ai_button()
                logger.debug("✅ Showing AI button with default confirmation", 
                            bot_id=self.bot_id, 
                            user_id=user.id)
            else:
                keyboard = ReplyKeyboardRemove()
                logger.debug("❌ No AI button - agent not available", 
                            bot_id=self.bot_id, 
                            user_id=user.id)
            
            if self.bot:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text="✅ Спасибо! Добро пожаловать!",
                    reply_markup=keyboard
                )
            
        except Exception as e:
            logger.error("💥 Failed to send default confirmation with conditional AI button", error=str(e))
    
    # ===== ОСТАЛЬНЫЕ МЕТОДЫ БЕЗ ИЗМЕНЕНИЙ =====
    
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
