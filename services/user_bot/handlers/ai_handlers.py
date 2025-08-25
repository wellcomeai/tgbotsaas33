"""
AI обработчики для UserBot - ИСПРАВЛЕННАЯ ВЕРСИЯ
✅ АДМИН: Настройка и управление ИИ агентами  
✅ ПОЛЬЗОВАТЕЛИ: Обработка диалогов с ИИ (БЕЗ показа кнопки - это в channel_handlers)
✅ ЧИСТОЕ РАЗДЕЛЕНИЕ: channel_handlers показывает кнопку, ai_handlers её обрабатывает
✅ ЕДИНАЯ СИСТЕМА ПРОВЕРОК: AIAccessChecker
✅ ИНСТАНС-ПОДХОД: Без глобальных переменных
✅ ИСПРАВЛЕНО: handle_user_ai_exit() теперь показывает кнопку ИИ после завершения
✅ ИСПРАВЛЕНО: Разные callback_data для админа и пользователей (устранен конфликт)
"""

import asyncio
import structlog
from datetime import datetime
from aiogram import F, Dispatcher
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from ..states import AISettingsStates
from ..keyboards import AIKeyboards, AdminKeyboards
from ..formatters import MessageFormatter

logger = structlog.get_logger()


class AIAccessChecker:
    """Единая система проверок доступа к ИИ"""
    
    def __init__(self, db, bot_config):
        self.db = db
        self.bot_config = bot_config
    
    async def check_subscription(self, user_id: int) -> tuple[bool, str]:
        """Проверка подписки на канал"""
        try:
            subscription_settings = await self.db.get_subscription_settings(self.bot_config['bot_id'])
            
            if not subscription_settings or not subscription_settings.get('subscription_check_enabled'):
                return True, ""
            
            channel_id = subscription_settings.get('subscription_channel_id')
            deny_message = subscription_settings.get('subscription_deny_message', 
                                                    'Для доступа к ИИ агенту необходимо подписаться на наш канал.')
            
            if not channel_id:
                return True, ""
            
            bot = self.bot_config.get('bot')
            if not bot:
                return True, ""
            
            member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            is_subscribed = member.status in ['member', 'administrator', 'creator']
            
            return is_subscribed, deny_message if not is_subscribed else ""
            
        except Exception as e:
            logger.warning("⚠️ Could not check channel subscription", error=str(e))
            return True, ""
    
    async def check_ai_agent_availability(self) -> tuple[bool, str]:
        """Проверка доступности ИИ агента"""
        try:
            fresh_ai_config = await self.db.get_ai_config(self.bot_config['bot_id'])
            
            if not fresh_ai_config or not fresh_ai_config.get('enabled') or not fresh_ai_config.get('agent_id'):
                return False, "❌ ИИ агент временно недоступен."
            
            return True, ""
            
        except Exception as e:
            logger.error("💥 Error checking AI agent availability", error=str(e))
            return False, "❌ Ошибка проверки доступности агента."
    
    async def check_token_limits(self, user_id: int) -> tuple[bool, str, dict]:
        """Проверка лимитов токенов"""
        try:
            fresh_ai_config = await self.db.get_ai_config(self.bot_config['bot_id'])
            
            if not fresh_ai_config or fresh_ai_config.get('type') != 'openai':
                return True, "", {}
            
            token_info = await self.db.get_user_token_balance(self.bot_config['owner_user_id'])
            
            if not token_info:
                return False, "❌ Система токенов не инициализирована", {}
            
            tokens_used = token_info.get('total_used', 0)
            tokens_limit = token_info.get('limit', 500000)
            remaining_tokens = tokens_limit - tokens_used
            
            if remaining_tokens <= 0:
                return False, f"""
❌ <b>Токены исчерпаны!</b>

Для этого ИИ агента закончились токены.
Использовано: {tokens_used:,} из {tokens_limit:,}

Обратитесь к администратору для пополнения баланса.
""", token_info
            
            return True, "", token_info
            
        except Exception as e:
            logger.error("💥 Error checking token limit", error=str(e))
            return False, "❌ Ошибка при проверке лимита токенов", {}
    
    async def check_daily_limits(self, user_id: int) -> tuple[bool, str]:
        """Проверка дневных лимитов пользователя"""
        try:
            fresh_ai_config = await self.db.get_ai_config(self.bot_config['bot_id'])
            agent_settings = fresh_ai_config.get('settings', {})
            daily_limit = agent_settings.get('daily_limit')
            
            if not daily_limit:
                return True, ""
            
            usage_count = await self.db.get_ai_usage_today(self.bot_config['bot_id'], user_id)
            
            if usage_count >= daily_limit:
                return False, f"""❌ Лимит сообщений исчерпан!
Лимит: {daily_limit} в день. Использовано: {usage_count}
Попробуйте завтра."""
            
            return True, ""
            
        except Exception as e:
            logger.error("💥 Error checking daily limits", error=str(e))
            return True, ""  # В случае ошибки разрешаем доступ
    
    async def check_full_access(self, user_id: int) -> dict:
        """Полная проверка всех ограничений"""
        result = {
            'allowed': False,
            'message': '',
            'subscription_ok': False,
            'agent_ok': False, 
            'tokens_ok': False,
            'daily_limit_ok': False,
            'token_info': {}
        }
        
        # 1. Проверка подписки
        subscription_ok, subscription_msg = await self.check_subscription(user_id)
        result['subscription_ok'] = subscription_ok
        if not subscription_ok:
            result['message'] = subscription_msg
            return result
        
        # 2. Проверка агента
        agent_ok, agent_msg = await self.check_ai_agent_availability()
        result['agent_ok'] = agent_ok
        if not agent_ok:
            result['message'] = agent_msg
            return result
        
        # 3. Проверка токенов
        tokens_ok, tokens_msg, token_info = await self.check_token_limits(user_id)
        result['tokens_ok'] = tokens_ok
        result['token_info'] = token_info
        if not tokens_ok:
            result['message'] = tokens_msg
            return result
        
        # 4. Проверка дневного лимита
        daily_ok, daily_msg = await self.check_daily_limits(user_id)
        result['daily_limit_ok'] = daily_ok
        if not daily_ok:
            result['message'] = daily_msg
            return result
        
        # Все проверки пройдены
        result['allowed'] = True
        return result


class AIHandler:
    """Единый обработчик ИИ функций"""
    
    def __init__(self, db, bot_config, user_bot=None):
        self.db = db
        self.bot_config = bot_config
        self.user_bot = user_bot
        self.formatter = MessageFormatter()
        self.access_checker = AIAccessChecker(db, bot_config)
        self.owner_user_id = bot_config['owner_user_id']
        self.bot_id = bot_config['bot_id']
    
    def _is_owner(self, user_id: int) -> bool:
        """Проверка, является ли пользователь владельцем"""
        return user_id == self.owner_user_id

    async def _create_openai_handler(self):
        """Создание экземпляра OpenAIHandler"""
        try:
            from .ai_openai_handler import OpenAIHandler
            
            openai_handler = OpenAIHandler(
                db=self.db,
                bot_config=self.bot_config,
                ai_assistant=None,
                user_bot=None
            )
            
            logger.info("✅ OpenAIHandler created", bot_id=self.bot_id)
            return openai_handler
            
        except Exception as e:
            logger.error("💥 Failed to create OpenAIHandler", error=str(e))
            return None

    async def _get_fresh_ai_config(self) -> dict:
        """Получить свежую конфигурацию ИИ агента"""
        try:
            ai_config = await self.db.get_ai_config(self.bot_id)
            return ai_config or {}
        except Exception as e:
            logger.error("💥 Failed to get fresh AI config", error=str(e))
            return {}

    async def _get_openai_response_for_user(self, message: Message, user_id: int) -> str:
        """Получение ответа от OpenAI для пользователя"""
        try:
            fresh_ai_config = await self._get_fresh_ai_config()
            
            if not fresh_ai_config or fresh_ai_config.get('type') != 'openai':
                return "❌ ИИ агент неправильно настроен."
            
            agent_id = fresh_ai_config.get('agent_id')
            if not agent_id:
                return "❌ Агент не найден."
            
            try:
                from services.openai_assistant import openai_client
                from services.openai_assistant.models import OpenAIResponsesContext
                
                context = OpenAIResponsesContext(
                    user_id=user_id,
                    user_name=message.from_user.first_name or "Пользователь",
                    username=message.from_user.username,
                    bot_id=self.bot_id,
                    chat_id=message.chat.id,
                    is_admin=False
                )
                
                response = await openai_client.send_message(
                    assistant_id=agent_id,
                    message=message.text,
                    user_id=user_id,
                    context=context
                )
                
                if response:
                    # Записываем использование
                    try:
                        await self.db.increment_ai_usage(self.bot_id, user_id)
                        logger.info("📊 AI usage incremented", user_id=user_id)
                    except Exception as stats_error:
                        logger.warning("⚠️ Failed to update usage stats", error=str(stats_error))
                    
                    return response
                else:
                    return "❌ Получен пустой ответ от ИИ."
                    
            except ImportError:
                logger.warning("📦 OpenAI service not available", user_id=user_id)
                
                settings = fresh_ai_config.get('settings', {})
                agent_name = settings.get('agent_name', 'ИИ Агент')
                
                try:
                    await self.db.increment_ai_usage(self.bot_id, user_id)
                except:
                    pass
                
                return f"🤖 {agent_name}: Сервис временно недоступен."
                
        except Exception as e:
            logger.error("💥 Error getting OpenAI response", error=str(e))
            return "❌ Внутренняя ошибка системы."

    # ===== АДМИНСКИЕ ОБРАБОТЧИКИ =====

    async def handle_navigation_callbacks(self, callback: CallbackQuery, state: FSMContext):
        """Навигационные callback для админа"""
        logger.info("🧭 Admin navigation callback", 
                   user_id=callback.from_user.id,
                   callback_data=callback.data)
        
        try:
            openai_handler = await self._create_openai_handler()
            if not openai_handler:
                await callback.answer("❌ Ошибка создания обработчика", show_alert=True)
                return
            
            is_owner_check = lambda user_id: self._is_owner(user_id)
            
            await openai_handler.handle_navigation_action(callback, state, is_owner_check)
            
            logger.info("✅ Admin navigation handled", callback_data=callback.data)
            
        except Exception as e:
            logger.error("💥 Error in admin navigation", error=str(e))
            await callback.answer("❌ Произошла ошибка", show_alert=True)

    async def handle_admin_ai_exit_conversation(self, callback: CallbackQuery, state: FSMContext):
        """Завершение админского диалога с ИИ"""
        logger.info("🚪 Admin AI exit conversation", user_id=callback.from_user.id)
        
        try:
            openai_handler = await self._create_openai_handler()
            if not openai_handler:
                await callback.answer("❌ Ошибка создания обработчика", show_alert=True)
                return
            
            await openai_handler.handle_exit_conversation(callback, state)
            logger.info("✅ Admin AI conversation ended", callback_data=callback.data)
            
        except Exception as e:
            logger.error("💥 Error in admin AI exit handler", error=str(e))
            await callback.answer("❌ Произошла ошибка", show_alert=True)

    async def handle_openai_callbacks(self, callback: CallbackQuery, state: FSMContext):
        """Обработчик OpenAI действий для админа"""
        logger.info(f"🎨 Admin OpenAI callback: {callback.data}", user_id=callback.from_user.id)
        
        try:
            is_owner_check = lambda user_id: self._is_owner(user_id)
            
            openai_handler = await self._create_openai_handler()
            if not openai_handler:
                await callback.answer("❌ Ошибка создания обработчика", show_alert=True)
                return
            
            if callback.data == "openai_confirm_delete":
                await openai_handler.handle_confirm_delete(callback, is_owner_check)
            else:
                await openai_handler.handle_openai_action(callback, state, is_owner_check)
            
            logger.info("✅ Admin OpenAI action handled", callback_data=callback.data)
            
        except Exception as e:
            logger.error("💥 Error in admin OpenAI handler", error=str(e))
            await callback.answer("❌ Произошла ошибка", show_alert=True)

    # ===== FSM ОБРАБОТЧИКИ ДЛЯ АДМИНА =====

    async def handle_openai_name_input(self, message: Message, state: FSMContext):
        """Обработка ввода имени OpenAI агента (АДМИН)"""
        logger.info("📝 Admin OpenAI name input", user_id=message.from_user.id)
        
        try:
            is_owner_check = lambda user_id: self._is_owner(user_id)
            
            openai_handler = await self._create_openai_handler()
            if not openai_handler:
                await message.answer("❌ Ошибка создания обработчика")
                return
            
            await openai_handler.handle_name_input(message, state, is_owner_check)
            
        except Exception as e:
            logger.error("💥 Error in admin name input", error=str(e))
            await message.answer("❌ Произошла ошибка")

    async def handle_openai_role_input(self, message: Message, state: FSMContext):
        """Обработка ввода роли OpenAI агента (АДМИН)"""
        logger.info("📝 Admin OpenAI role input", user_id=message.from_user.id)
        
        try:
            is_owner_check = lambda user_id: self._is_owner(user_id)
            
            openai_handler = await self._create_openai_handler()
            if not openai_handler:
                await message.answer("❌ Ошибка создания обработчика")
                return
            
            await openai_handler.handle_role_input(message, state, is_owner_check)
            
        except Exception as e:
            logger.error("💥 Error in admin role input", error=str(e))
            await message.answer("❌ Произошла ошибка")

    async def handle_agent_name_edit(self, message: Message, state: FSMContext):
        """Обработка редактирования имени агента (АДМИН)"""
        logger.info("✏️ Admin agent name edit", user_id=message.from_user.id)
        
        try:
            is_owner_check = lambda user_id: self._is_owner(user_id)
            
            openai_handler = await self._create_openai_handler()
            if not openai_handler:
                await message.answer("❌ Ошибка создания обработчика")
                return
            
            await openai_handler.handle_name_edit_input(message, state, is_owner_check)
            
        except Exception as e:
            logger.error("💥 Error in admin name edit", error=str(e))
            await message.answer("❌ Произошла ошибка")

    async def handle_agent_prompt_edit(self, message: Message, state: FSMContext):
        """Обработка редактирования промпта агента (АДМИН)"""
        logger.info("🎭 Admin agent prompt edit", user_id=message.from_user.id)
        
        try:
            is_owner_check = lambda user_id: self._is_owner(user_id)
            
            openai_handler = await self._create_openai_handler()
            if not openai_handler:
                await message.answer("❌ Ошибка создания обработчика")
                return
            
            await openai_handler.handle_prompt_edit_input(message, state, is_owner_check)
            
        except Exception as e:
            logger.error("💥 Error in admin prompt edit", error=str(e))
            await message.answer("❌ Произошла ошибка")

    async def handle_admin_ai_conversation(self, message: Message, state: FSMContext):
        """Обработка админского тестирования ИИ"""
        logger.info("💬 Admin AI testing conversation", user_id=message.from_user.id)
        
        try:
            # Проверяем команды выхода
            if message.text in ['/exit', '/stop', '/cancel']:
                await state.clear()
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_main")]
                ])
                
                await message.answer("🚪 Диалог с ИИ завершен", reply_markup=keyboard)
                return
            
            if not self._is_owner(message.from_user.id):
                await message.answer("❌ Доступ запрещен")
                return
            
            data = await state.get_data()
            agent_type = data.get('agent_type', 'openai')
            
            if agent_type == 'openai':
                openai_handler = await self._create_openai_handler()
                if not openai_handler:
                    await message.answer("❌ Ошибка создания обработчика OpenAI")
                    return
                
                await message.bot.send_chat_action(message.chat.id, "typing")
                
                response = await openai_handler.handle_openai_conversation(message, data)
                
                if response:
                    # ✅ ИЗМЕНЕНО: Используем admin_ai_exit_conversation для админа
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🚪 Завершить диалог", callback_data="admin_ai_exit_conversation")]
                    ])
                    
                    await message.answer(response, reply_markup=keyboard)
                else:
                    await message.answer("❌ Не удалось получить ответ от ИИ")
            else:
                await message.answer("❌ Неподдерживаемый тип агента")
                
        except Exception as e:
            logger.error("💥 Error in admin AI conversation", error=str(e))
            await message.answer("❌ Произошла ошибка при общении с ИИ")

    # ===== ПОЛЬЗОВАТЕЛЬСКИЕ ОБРАБОТЧИКИ =====

    async def handle_user_ai_button_click(self, message: Message, state: FSMContext):
        """🤖 Обработка кнопки 'Позвать ИИ' от пользователей"""
        user = message.from_user
        
        logger.info("🤖 User AI button clicked", 
                   bot_id=self.bot_id,
                   user_id=user.id,
                   username=user.username)
        
        try:
            # Очищаем любое текущее состояние
            current_state = await state.get_state()
            if current_state:
                await state.clear()
            
            # ✅ ЕДИНАЯ ПРОВЕРКА через AccessChecker
            access_result = await self.access_checker.check_full_access(user.id)
            
            if not access_result['allowed']:
                logger.warning("❌ User access denied", 
                             user_id=user.id, 
                             reason=access_result['message'][:50])
                await message.answer(access_result['message'], reply_markup=ReplyKeyboardRemove())
                return
            
            # ===== ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ - ЗАПУСК ДИАЛОГА =====
            
            await state.set_state(AISettingsStates.user_in_ai_conversation)
            await state.update_data(
                agent_type='openai',
                user_id=user.id,
                bot_id=self.bot_id,
                started_at=datetime.now().isoformat(),
                is_user_conversation=True
            )
            
            # Формируем приветствие
            fresh_ai_config = await self._get_fresh_ai_config()
            agent_settings = fresh_ai_config.get('settings', {})
            agent_name = agent_settings.get('agent_name', 'ИИ Агент')
            
            # Подсчитываем оставшиеся сообщения
            remaining_messages = ""
            daily_limit = agent_settings.get('daily_limit')
            if daily_limit:
                usage_count = await self.db.get_ai_usage_today(self.bot_id, user.id)
                remaining = daily_limit - usage_count
                remaining_messages = f"\n📊 Осталось сообщений сегодня: {remaining}"
            
            welcome_text = f"""
🤖 <b>Добро пожаловать в чат с {agent_name}!</b>

Я готов помочь вам с любыми вопросами. Просто напишите что вас интересует.{remaining_messages}

<b>Напишите ваш вопрос:</b>
"""
            
            # ✅ ИЗМЕНЕНО: Используем user_ai_exit_conversation для пользователей
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚪 Завершить диалог", callback_data="user_ai_exit_conversation")]
            ])
            
            await message.answer(welcome_text, reply_markup=keyboard)
            
            logger.info("🎉 User AI conversation started", user_id=user.id)
            
        except Exception as e:
            logger.error("💥 Error in user AI button handler", user_id=user.id, error=str(e))
            
            try:
                await state.clear()
            except:
                pass
            
            await message.answer("❌ Произошла ошибка при запуске диалога с ИИ.")

    async def handle_user_ai_conversation(self, message: Message, state: FSMContext):
        """💬 Обработка диалога пользователя с ИИ"""
        user = message.from_user
        
        logger.info("💬 User AI conversation message", 
                   user_id=user.id,
                   message_length=len(message.text))
        
        try:
            # Проверяем FSM состояние
            current_state = await state.get_state()
            if current_state != AISettingsStates.user_in_ai_conversation:
                logger.warning("❌ Wrong FSM state", user_id=user.id)
                return
            
            data = await state.get_data()
            is_user_conversation = data.get('is_user_conversation', False)
            
            # Проверяем что это пользовательский диалог
            if not is_user_conversation:
                logger.warning("❌ Not a user conversation", user_id=user.id)
                return
            
            # Быстрые проверки доступности
            access_result = await self.access_checker.check_full_access(user.id)
            if not access_result['allowed']:
                await message.answer(access_result['message'])
                await state.clear()
                return
            
            # Показываем индикатор набора
            await message.bot.send_chat_action(message.chat.id, "typing")
            
            # Получаем ответ от ИИ
            ai_response = await self._get_openai_response_for_user(message, user.id)
            
            if ai_response:
                # ✅ ИЗМЕНЕНО: Используем user_ai_exit_conversation для пользователей
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🚪 Завершить диалог", callback_data="user_ai_exit_conversation")]
                ])
                
                await message.answer(ai_response, reply_markup=keyboard)
                logger.info("✅ User AI response sent", user_id=user.id)
            else:
                await message.answer("❌ Не удалось получить ответ от ИИ.")
                
        except Exception as e:
            logger.error("💥 Error in user AI conversation", user_id=user.id, error=str(e))
            await message.answer("❌ Произошла ошибка при общении с ИИ.")

    async def handle_user_ai_exit(self, callback: CallbackQuery, state: FSMContext):
        """🚪 Завершение диалога с ИИ для пользователей - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
        user_id = callback.from_user.id
        
        logger.info("🚪 User AI conversation exit", user_id=user_id)
        
        try:
            await callback.answer()
            
            current_state = await state.get_state()
            if current_state:
                await state.clear()
            
            # Редактируем текущее сообщение (убираем кнопку завершения)
            await callback.message.edit_text(
                "🚪 Диалог с ИИ завершен.\n\n"
                "Спасибо за общение!"
            )
            
            # ✅ НОВОЕ: Отправляем новое сообщение с кнопкой ИИ
            from ..keyboards import UserKeyboards
            
            await callback.message.answer(
                "💬 Всегда можете обратиться к ИИ снова!",
                reply_markup=UserKeyboards.ai_button()
            )
            
            logger.info("✅ User AI conversation ended with new AI button", user_id=user_id)
            
        except Exception as e:
            logger.error("💥 Error ending user AI conversation", user_id=user_id, error=str(e))
            
            # Fallback: хотя бы попытаемся показать кнопку ИИ
            try:
                from ..keyboards import UserKeyboards
                await callback.message.answer(
                    "💬 Обратитесь к ИИ снова:",
                    reply_markup=UserKeyboards.ai_button()
                )
            except Exception as fallback_error:
                logger.error("💥 Fallback also failed", error=str(fallback_error))

    async def handle_user_exit_commands(self, message: Message, state: FSMContext):
        """🚪 Команды выхода из диалога для пользователей"""
        user_id = message.from_user.id
        command = message.text.lower()
        
        logger.info("🚪 User exit command", user_id=user_id, command=command)
        
        try:
            current_state = await state.get_state()
            
            if current_state == AISettingsStates.user_in_ai_conversation:
                data = await state.get_data()
                is_user_conversation = data.get('is_user_conversation', False)
                
                if is_user_conversation:
                    await state.clear()
                    
                    await message.answer(
                        "🚪 Диалог с ИИ завершен по команде.\n\n"
                        "Для нового диалога нажмите \"🤖 Позвать ИИ\"",
                        reply_markup=ReplyKeyboardRemove()
                    )
                    
                    logger.info("✅ User AI conversation ended by command", user_id=user_id)
            
        except Exception as e:
            logger.error("💥 Error handling user exit command", user_id=user_id, error=str(e))


def register_ai_handlers(dp: Dispatcher, **kwargs):
    """✅ ИСПРАВЛЕННАЯ РЕГИСТРАЦИЯ без глобальных переменных"""
    
    # Создаем экземпляр обработчика
    ai_handler = AIHandler(
        db=kwargs['db'],
        bot_config=kwargs['bot_config'],
        user_bot=kwargs.get('user_bot')
    )
    
    owner_user_id = ai_handler.owner_user_id
    
    try:
        logger.info("🎯 Registering AI handlers with instance-based approach", 
                   bot_id=ai_handler.bot_id,
                   owner_user_id=owner_user_id)
        
        # ===== 🏆 АДМИНСКИЕ ИИ ОБРАБОТЧИКИ (ТОЛЬКО ВЛАДЕЛЕЦ) =====
        
        # FSM состояния для настройки агентов
        dp.message.register(
            ai_handler.handle_openai_name_input,
            StateFilter(AISettingsStates.admin_waiting_for_openai_name),
            F.from_user.id == owner_user_id
        )
        
        dp.message.register(
            ai_handler.handle_openai_role_input,
            StateFilter(AISettingsStates.admin_waiting_for_openai_role),
            F.from_user.id == owner_user_id
        )
        
        dp.message.register(
            ai_handler.handle_agent_name_edit,
            StateFilter(AISettingsStates.admin_editing_agent_name),
            F.from_user.id == owner_user_id
        )
        
        dp.message.register(
            ai_handler.handle_agent_prompt_edit,
            StateFilter(AISettingsStates.admin_editing_agent_prompt),
            F.from_user.id == owner_user_id
        )
        
        # Админское тестирование ИИ
        dp.message.register(
            ai_handler.handle_admin_ai_conversation,
            StateFilter(AISettingsStates.admin_in_ai_conversation),
            F.from_user.id == owner_user_id
        )
        
        # Callback обработчики для админа
        dp.callback_query.register(
            ai_handler.handle_navigation_callbacks,
            F.data.in_(["admin_panel", "admin_ai", "admin_main"]),
            F.from_user.id == owner_user_id
        )
        
        # ✅ ИЗМЕНЕНО: Используем admin_ai_exit_conversation для админа
        dp.callback_query.register(
            ai_handler.handle_admin_ai_exit_conversation,
            F.data == "admin_ai_exit_conversation",
            F.from_user.id == owner_user_id
        )
        
        dp.callback_query.register(
            ai_handler.handle_openai_callbacks,
            F.data.startswith("openai_"),
            F.from_user.id == owner_user_id
        )
        
        # ===== 👥 ПОЛЬЗОВАТЕЛЬСКИЕ ИИ ОБРАБОТЧИКИ (НЕ ВЛАДЕЛЕЦ) =====
        
        # ОБРАБОТКА кнопки "Позвать ИИ" (показ кнопки в channel_handlers)
        dp.message.register(
            ai_handler.handle_user_ai_button_click,
            F.text == "🤖 Позвать ИИ",
            F.chat.type == "private",
            F.from_user.id != owner_user_id
        )
        
        # Диалог с ИИ для пользователей
        dp.message.register(
            ai_handler.handle_user_ai_conversation,
            StateFilter(AISettingsStates.user_in_ai_conversation),
            F.chat.type == "private",
            F.from_user.id != owner_user_id
        )
        
        # ✅ ИЗМЕНЕНО: Используем user_ai_exit_conversation для пользователей
        dp.callback_query.register(
            ai_handler.handle_user_ai_exit,
            F.data == "user_ai_exit_conversation",
            F.from_user.id != owner_user_id
        )
        
        # Команды выхода для пользователей
        dp.message.register(
            ai_handler.handle_user_exit_commands,
            F.text.lower().in_(['/exit', '/stop', '/cancel', 'выход', 'стоп']),
            F.chat.type == "private",
            F.from_user.id != owner_user_id
        )
        
        logger.info("✅ AI handlers registered with instance approach", 
                   owner_user_id=owner_user_id,
                   admin_handlers=7,
                   user_handlers=4,
                   improvements=["AIAccessChecker", "No global vars", "Separate FSM states", "Fixed user exit button", "Separate callback_data"])
        
    except Exception as e:
        logger.error("💥 Failed to register AI handlers", 
                    bot_id=kwargs.get('bot_config', {}).get('bot_id', 'unknown'),
                    error=str(e), exc_info=True)
        raise
