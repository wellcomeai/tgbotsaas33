"""
Conversation Mixin для OpenAI Handler
Содержит логику диалогов и тестирования OpenAI агентов через Responses API
"""

import structlog
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from ...states import AISettingsStates

logger = structlog.get_logger()


class ConversationMixin:
    """Миксин для диалогов с OpenAI агентами"""

    # ===== ТЕСТИРОВАНИЕ =====
    
    async def _test_openai_assistant(self, callback: CallbackQuery, state: FSMContext):
        """Тестирование OpenAI ассистента через Responses API"""
        logger.info("🧪 Starting OpenAI assistant test via Responses API", 
                   bot_id=self.bot_id)
        
        # ✅ ДОБАВЛЕНО: Синхронизация перед тестированием
        await self._sync_with_db_state()
        
        agent_type = self.ai_assistant_settings.get('agent_type', 'none')
        openai_assistant_id = self.ai_assistant_id if agent_type == 'openai' else None
        
        if not openai_assistant_id:
            logger.warning("❌ No OpenAI agent created for testing")
            await callback.answer("❌ Сначала создайте OpenAI агента", show_alert=True)
            return
        
        logger.info("✅ Starting OpenAI test mode via Responses API", 
                   openai_assistant_id=openai_assistant_id)
        
        await state.set_state(AISettingsStates.admin_in_ai_conversation)
        # ✅ ИЗМЕНЕНИЕ 5: Убираем различие админ/пользователь в тестировании
        await state.update_data(agent_type='openai', user_id=callback.from_user.id)
        
        # Получаем информацию о включенных инструментах
        settings = self.ai_assistant_settings.get('openai_settings', {})
        enabled_tools = []
        if settings.get('enable_web_search'):
            enabled_tools.append("🌐 Веб-поиск")
        if settings.get('enable_code_interpreter'):
            enabled_tools.append("🐍 Интерпретатор кода")
        if settings.get('enable_file_search'):
            enabled_tools.append("📁 Поиск по файлам")
        if settings.get('enable_image_generation'):
            enabled_tools.append("🎨 Генерация изображений")
        
        tools_text = ""
        if enabled_tools:
            tools_text = f"\n<b>Включенные инструменты:</b> {', '.join(enabled_tools)}"
        
        text = f"""
🧪 <b>Тестирование OpenAI агента (Responses API)</b>

<b>Агент ID:</b> {openai_assistant_id[:15]}...
<b>Модель:</b> GPT-4o (Responses API)
<b>Режим:</b> Автоматический контекст{tools_text}

✨ <b>Особенности Responses API:</b>
- Контекст сохраняется автоматически на серверах OpenAI
- Не нужно отправлять всю историю с каждым сообщением
- Поддержка встроенных инструментов

<b>Напишите ваш вопрос:</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚪 Завершить диалог", callback_data="ai_exit_conversation")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)

    # ===== ДИАЛОГ С OPENAI =====
    
    async def handle_openai_conversation(self, message: Message, data: dict) -> str:
        """✅ ИСПРАВЛЕНО: Обработка диалога с правильной проверкой агента + списание токенов + проверка голосовых"""
        logger.info("🎨 OpenAI conversation processing via Responses API", 
                   user_id=message.from_user.id,
                   has_text=self._is_text_message(message),
                   message_length=len(message.text) if message.text else 0)
        
        try:
            # ✅ ИСПРАВЛЕНО: Проверяем тип сообщения
            if not self._is_text_message(message):
                # ✅ ДОБАВЛЕНО: Списание токенов даже для неподдерживаемых сообщений
                try:
                    await self.db.increment_ai_usage(self.bot_id, message.from_user.id)
                    logger.info("💰 Tokens charged for unsupported message", 
                               bot_id=self.bot_id, 
                               user_id=message.from_user.id)
                except Exception as stats_error:
                    logger.warning("⚠️ Failed to update token usage for unsupported message", error=str(stats_error))
                
                message_type_display = self._get_message_text(message)
                return f"❌ Извините, я могу обрабатывать только текстовые сообщения. Ваше сообщение: {message_type_display}"
            
            # ✅ ИСПРАВЛЕНО: Синхронизируем перед диалогом
            await self._sync_with_db_state()
            
            agent_type = self.ai_assistant_settings.get('agent_type', 'none')
            openai_assistant_id = self.ai_assistant_id if agent_type == 'openai' else None
            
            if not openai_assistant_id:
                logger.error("❌ No OpenAI assistant ID available",
                            cached_id=self.ai_assistant_id,
                            agent_type=agent_type)
                return "❌ OpenAI агент не настроен."
            
            logger.info("📊 OpenAI Responses API conversation parameters", 
                       openai_assistant_id=openai_assistant_id,
                       user_id=message.from_user.id)
            
            # Пытаемся использовать OpenAI Responses API сервис
            try:
                from services.openai_assistant import openai_client
                from services.openai_assistant.models import OpenAIResponsesContext
                
                # СОЗДАЕМ УПРОЩЕННЫЙ КОНТЕКСТ (БЕЗ previous_response_id)
                context = OpenAIResponsesContext(
                    user_id=message.from_user.id,
                    user_name=message.from_user.first_name or "Пользователь",
                    username=message.from_user.username,
                    bot_id=self.bot_id,
                    chat_id=message.chat.id,
                    is_admin=message.from_user.id == self.owner_user_id
                )
                
                logger.info("📝 Responses API context prepared", 
                           user_name=context.user_name,
                           is_admin=context.is_admin)
                
                # ОТПРАВЛЯЕМ СООБЩЕНИЕ ЧЕРЕЗ RESPONSES API
                # Контекст разговора управляется автоматически!
                logger.info("📡 Sending message to OpenAI Responses API service")
                
                response = await openai_client.send_message(
                    assistant_id=openai_assistant_id,
                    message=message.text,
                    user_id=message.from_user.id,
                    context=context
                )
                
                logger.info("✅ OpenAI Responses API response received", 
                           response_length=len(response) if response else 0)
                
                if response:
                    # ✅ ИЗМЕНЕНИЕ 4: Записываем использование токенов для ВСЕХ (включая админов)
                    try:
                        await self.db.increment_ai_usage(self.bot_id, message.from_user.id)
                        logger.info("💰 Tokens charged", 
                                   bot_id=self.bot_id, 
                                   user_id=message.from_user.id,
                                   is_admin=message.from_user.id == self.owner_user_id)
                    except Exception as stats_error:
                        logger.warning("⚠️ Failed to update token usage", error=str(stats_error))
                    
                    logger.info("📊 Responses API conversation completed successfully")
                    return response
                else:
                    return "❌ Не удалось получить ответ от OpenAI."
                    
            except ImportError:
                # Fallback для случая когда OpenAI сервис недоступен
                logger.warning("📦 OpenAI Responses API service not available, using fallback")
                agent_name = self.ai_assistant_settings.get('agent_name', 'ИИ Агент')
                
                # ✅ ДОБАВЛЕНО: Списание токенов даже для fallback ответов
                try:
                    await self.db.increment_ai_usage(self.bot_id, message.from_user.id)
                    logger.info("💰 Tokens charged (fallback)", 
                               bot_id=self.bot_id, 
                               user_id=message.from_user.id)
                except Exception as stats_error:
                    logger.warning("⚠️ Failed to update token usage (fallback)", error=str(stats_error))
                
                return f"🤖 {agent_name}: Получил ваше сообщение '{message.text}'. Responses API сервис временно недоступен."
            
        except Exception as e:
            logger.error("💥 Error in OpenAI Responses API conversation", 
                        error=str(e),
                        error_type=type(e).__name__)
            # ✅ ИСПРАВЛЕНО: Возвращаем строку с ошибкой вместо None
            return "❌ Произошла ошибка при общении с ИИ"

    async def handle_openai_conversation_with_text(self, message: Message, data: dict, text: str) -> str:
        """✅ НОВЫЙ: Обработка диалога с OpenAI с кастомным текстом (для голосовых сообщений)"""
        logger.info("🎨 OpenAI conversation processing with custom text", 
                   user_id=message.from_user.id,
                   text_length=len(text) if text else 0,
                   is_admin=message.from_user.id == self.owner_user_id)
        
        try:
            if not text:
                logger.warning("❌ Empty text provided to OpenAI handler")
                return "❌ Пустое сообщение"
            
            # ✅ ИСПРАВЛЕНО: Синхронизируем перед диалогом
            await self._sync_with_db_state()
            
            agent_type = self.ai_assistant_settings.get('agent_type', 'none')
            openai_assistant_id = self.ai_assistant_id if agent_type == 'openai' else None
            
            if not openai_assistant_id:
                logger.error("❌ No OpenAI assistant ID available",
                            cached_id=self.ai_assistant_id,
                            agent_type=agent_type)
                return "❌ OpenAI агент не настроен."
            
            logger.info("📊 OpenAI Responses API conversation parameters", 
                       openai_assistant_id=openai_assistant_id,
                       user_id=message.from_user.id,
                       text_preview=text[:50] if text else "EMPTY")
            
            # Пытаемся использовать OpenAI Responses API сервис
            try:
                from services.openai_assistant import openai_client
                from services.openai_assistant.models import OpenAIResponsesContext
                
                # СОЗДАЕМ УПРОЩЕННЫЙ КОНТЕКСТ
                context = OpenAIResponsesContext(
                    user_id=message.from_user.id,
                    user_name=message.from_user.first_name or "Пользователь",
                    username=message.from_user.username,
                    bot_id=self.bot_id,
                    chat_id=message.chat.id,
                    is_admin=message.from_user.id == self.owner_user_id
                )
                
                logger.info("📝 Responses API context prepared", 
                           user_name=context.user_name,
                           is_admin=context.is_admin)
                
                # ОТПРАВЛЯЕМ КАСТОМНЫЙ ТЕКСТ ЧЕРЕЗ RESPONSES API
                logger.info("📡 Sending custom text to OpenAI Responses API service")
                
                response = await openai_client.send_message(
                    assistant_id=openai_assistant_id,
                    message=text,  # ✅ ИСПОЛЬЗУЕМ ПЕРЕДАННЫЙ ТЕКСТ (транскрибированный или обычный)
                    user_id=message.from_user.id,
                    context=context
                )
                
                logger.info("✅ OpenAI Responses API response received", 
                           response_length=len(response) if response else 0)
                
                if response:
                    # ✅ Записываем использование токенов для ВСЕХ (включая админов)
                    try:
                        await self.db.increment_ai_usage(self.bot_id, message.from_user.id)
                        logger.info("💰 Tokens charged for admin", 
                                   bot_id=self.bot_id, 
                                   user_id=message.from_user.id,
                                   is_admin=context.is_admin)
                    except Exception as stats_error:
                        logger.warning("⚠️ Failed to update token usage for admin", error=str(stats_error))
                    
                    logger.info("📊 Admin Responses API conversation completed successfully")
                    return response
                else:
                    return "❌ Не удалось получить ответ от OpenAI."
                    
            except ImportError:
                # Fallback для случая когда OpenAI сервис недоступен
                logger.warning("📦 OpenAI Responses API service not available, using admin fallback")
                agent_name = self.ai_assistant_settings.get('agent_name', 'ИИ Агент')
                
                # ✅ Списание токенов даже для fallback ответов
                try:
                    await self.db.increment_ai_usage(self.bot_id, message.from_user.id)
                    logger.info("💰 Tokens charged (admin fallback)", 
                               bot_id=self.bot_id, 
                               user_id=message.from_user.id)
                except Exception as stats_error:
                    logger.warning("⚠️ Failed to update token usage (admin fallback)", error=str(stats_error))
                
                return f"🤖 {agent_name}: [АДМИН ТЕСТ] Получил сообщение '{text[:100]}{'...' if len(text) > 100 else ''}'. Responses API сервис временно недоступен."
            
        except Exception as e:
            logger.error("💥 Error in admin OpenAI conversation with custom text", 
                        error=str(e),
                        error_type=type(e).__name__)
            return "❌ Произошла ошибка при общении с ИИ"
