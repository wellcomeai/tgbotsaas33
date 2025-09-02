"""
Agent Creator Mixin для OpenAI Handler
Содержит логику создания новых OpenAI агентов через Responses API
"""

import structlog
import time
from datetime import datetime
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from ...states import AISettingsStates

logger = structlog.get_logger()


class AgentCreatorMixin:
    """Миксин для создания OpenAI агентов"""

    # ===== СОЗДАНИЕ АГЕНТА =====
    
    async def _create_openai_agent(self, callback: CallbackQuery, state: FSMContext):
        """✅ ИСПРАВЛЕНО: Начало создания OpenAI агента с синхронизацией"""
        logger.info("🎨 Starting OpenAI agent creation flow", 
                   user_id=callback.from_user.id,
                   bot_id=self.bot_id)
        
        # ✅ КРИТИЧНО: Принудительная синхронизация перед созданием
        logger.info("🔄 Pre-creation state sync check", 
                   current_agent_id=self.ai_assistant_id,
                   current_agent_type=self.ai_assistant_settings.get('agent_type'))
        
        sync_success = await self._sync_with_db_state(force=True)
        
        if sync_success:
            logger.info("✅ Pre-creation sync completed", 
                       synced_agent_id=self.ai_assistant_id,
                       synced_agent_type=self.ai_assistant_settings.get('agent_type'))
        else:
            logger.warning("⚠️ Pre-creation sync failed, continuing with fallback cleanup")
            # Fallback - принудительная очистка
            self.ai_assistant_id = None
            self.ai_assistant_settings = {'agent_type': 'openai'}
        
        await state.set_state(AISettingsStates.admin_waiting_for_openai_name)
        
        text = f"""
🎨 <b>Создание собственного ИИ агента</b>

<b>Шаг 1/2: Имя агента</b>

Придумайте имя для вашего ИИ агента. Оно будет отображаться пользователям при общении.

<b>Примеры хороших имен:</b>
- Консультант Мария
- Помощник Алекс
- Эксперт по продажам
- Тренер по фитнесу

<b>Введите имя агента:</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_ai")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)

    async def handle_name_input(self, message: Message, state: FSMContext, is_owner_check):
        """✅ ИСПРАВЛЕНО: Обработка ввода имени OpenAI агента с проверкой на голосовые сообщения"""
        logger.info("📝 OpenAI agent name input", 
                   user_id=message.from_user.id,
                   has_text=self._is_text_message(message),
                   message_type=type(message).__name__,
                   bot_id=self.bot_id)
        
        if not is_owner_check(message.from_user.id):
            return
        
        # ✅ ИСПРАВЛЕНО: Проверяем наличие текста в сообщении
        if not self._is_text_message(message):
            await message.answer("❌ Пожалуйста, отправьте текстовое сообщение с именем агента.")
            return
        
        message_text = message.text.strip()
        
        if message_text == "/cancel":
            await self._cancel_and_show_ai(message, state)
            return
        
        agent_name = message_text
        
        logger.info("🔍 Validating agent name", 
                   agent_name=agent_name,
                   name_length=len(agent_name))
        
        if len(agent_name) < 2:
            await message.answer("❌ Имя агента должно быть не менее 2 символов. Попробуйте еще раз:")
            return
        
        if len(agent_name) > 100:
            await message.answer("❌ Имя агента слишком длинное (максимум 100 символов). Попробуйте еще раз:")
            return
        
        # Сохраняем имя в состоянии
        await state.update_data(agent_name=agent_name)
        await state.set_state(AISettingsStates.admin_waiting_for_openai_role)
        
        logger.info("✅ Agent name accepted, moving to role input", 
                   agent_name=agent_name)
        
        text = f"""
✅ <b>Имя сохранено:</b> {agent_name}

<b>Шаг 2/2: Роль и инструкции</b>

Опишите роль вашего агента и то, как он должен отвечать пользователям. Это очень важно для качества ответов!

<b>Примеры хороших ролей:</b>
- "Ты эксперт по фитнесу. Отвечай дружелюбно, давай практичные советы по тренировкам и питанию."
- "Ты консультант по продажам. Помогай клиентам выбрать подходящий товар, отвечай профессионально."
- "Ты психолог-консультант. Выслушивай внимательно и давай поддерживающие советы."

<b>Введите роль и инструкции:</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_ai")]
        ])
        
        await message.answer(text, reply_markup=keyboard)

    async def handle_role_input(self, message: Message, state: FSMContext, is_owner_check):
        """✅ ИСПРАВЛЕНО: Обработка ввода роли OpenAI агента с улучшенным UX + проверка голосовых"""
        logger.info("📝 OpenAI agent role input", 
                   user_id=message.from_user.id,
                   has_text=self._is_text_message(message),
                   input_length=len(message.text) if message.text else 0,
                   bot_id=self.bot_id)
        
        if not is_owner_check(message.from_user.id):
            return
        
        # ✅ ИСПРАВЛЕНО: Проверяем наличие текста в сообщении
        if not self._is_text_message(message):
            await message.answer("❌ Пожалуйста, отправьте текстовое сообщение с описанием роли агента.")
            return
        
        message_text = message.text.strip()
        
        if message_text == "/cancel":
            await self._cancel_and_show_ai(message, state)
            return
        
        agent_role = message_text
        
        logger.info("🔍 Validating agent role", 
                   role_length=len(agent_role))
        
        if len(agent_role) < 10:
            await message.answer("❌ Описание роли слишком короткое (минимум 10 символов). Попробуйте еще раз:")
            return
        
        if len(agent_role) > 1000:
            await message.answer("❌ Описание роли слишком длинное (максимум 1000 символов). Попробуйте еще раз:")
            return
        
        try:
            # Сохраняем chat_id для токеновой системы
            admin_chat_id = message.chat.id
            await state.update_data(admin_chat_id=admin_chat_id)
            
            logger.info("📱 Admin chat ID captured for token tracking", 
                       admin_chat_id=admin_chat_id, user_id=message.from_user.id)
            
            # Получаем данные из состояния
            data = await state.get_data()
            agent_name = data.get('agent_name')
            
            logger.info("📊 Agent creation data", 
                       agent_name=agent_name,
                       agent_role=agent_role)
            
            if not agent_name:
                logger.error("❌ Agent name lost from state")
                await message.answer("❌ Ошибка: имя агента потеряно. Начните заново.")
                await state.clear()
                return
            
            # Показываем прогресс пользователю
            progress_message = await message.answer("🔄 Создаю агента через Responses API...")
            
            # Сохраняем состояние для передачи в _create_agent_in_openai
            self._current_state_data = data
            
            logger.info("🚀 Calling _create_agent_in_openai")
            success, response_data = await self._create_agent_in_openai(agent_name, agent_role)
            
            logger.info("📊 Agent creation result", 
                       success=success,
                       response_keys=list(response_data.keys()) if response_data else None)
            
            if success:
                creation_method = response_data.get('creation_method', 'unknown')
                duration = response_data.get('total_duration', 'unknown')
                
                success_message = f"🎉 <b>Агент успешно создан!</b>\n\n"
                success_message += f"<b>Имя:</b> {agent_name}\n"
                success_message += f"<b>Роль:</b> {agent_role[:100]}{'...' if len(agent_role) > 100 else ''}\n"
                
                if creation_method == 'responses_api':
                    success_message += f"\n✅ <b>Создан через Responses API</b> за {duration}\n"
                    success_message += f"• Автоматическое управление контекстом\n"
                    success_message += f"• Встроенные инструменты OpenAI\n"
                elif creation_method == 'fallback_stub':
                    success_message += f"\n⚠️ <b>Тестовый режим</b> (Responses API недоступен)\n"
                
                success_message += f"\nТеперь можете протестировать работу агента!"
                
                await progress_message.edit_text(
                    success_message,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🧪 Тестировать", callback_data="openai_test")],
                        [InlineKeyboardButton(text="🧰 Настроить инструменты", callback_data="openai_tools_settings")],
                        [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
                    ])
                )
            else:
                error_msg = response_data.get('error', 'Неизвестная ошибка')
                
                # Анализируем тип ошибки и даем понятное объяснение
                if "500" in error_msg or "server_error" in error_msg:
                    user_friendly_error = """
❌ <b>Временная проблема с OpenAI</b>

Серверы OpenAI сейчас перегружены. Это частая ситуация.

<b>Что делать:</b>
- Попробуйте через 2-3 минуты
- Или создайте агента позже
- Проблема решится автоматически

<b>Это НЕ ошибка вашего бота!</b>
"""
                elif "429" in error_msg or "rate" in error_msg:
                    user_friendly_error = """
❌ <b>Превышен лимит запросов</b>

OpenAI ограничивает количество запросов в минуту.

<b>Что делать:</b>
- Подождите 1-2 минуты
- Попробуйте создать агента снова
- Это временное ограничение
"""
                elif "401" in error_msg or "unauthorized" in error_msg:
                    user_friendly_error = """
❌ <b>Проблема с API ключом</b>

Возможно API ключ OpenAI неактивен.

<b>Обратитесь к администратору</b>
"""
                else:
                    user_friendly_error = f"""
❌ <b>Ошибка при создании агента</b>

{error_msg}

<b>Попробуйте еще раз через несколько минут</b>
"""
                
                logger.error("❌ Agent creation failed", error=error_msg)
                
                await progress_message.edit_text(
                    user_friendly_error,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="openai_create")],
                        [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
                    ])
                )
            
            await state.clear()
            
        except Exception as e:
            logger.error("💥 Failed to create OpenAI agent", 
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            await message.answer(
                "❌ Произошла ошибка при создании агента. Попробуйте еще раз.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
                ])
            )
            await state.clear()

    async def _create_agent_in_openai(self, name: str, role: str) -> tuple[bool, dict]:
        """Создание агента через Responses API"""
        logger.info("🎬 Starting OpenAI agent creation via Responses API", 
                   bot_id=self.bot_id,
                   owner_user_id=self.owner_user_id,
                   agent_name=name,
                   agent_role=role)
        
        overall_start_time = time.time()
        
        try:
            # Импорт обновленного сервиса
            logger.info("📦 Importing OpenAI Responses API service...")
            
            try:
                from services.openai_assistant import openai_client
                from services.openai_assistant.models import OpenAIResponsesRequest
                
                logger.info("✅ OpenAI Responses API service imported successfully", 
                           client_type=type(openai_client).__name__)
                
                # Проверка доступности клиента
                if not openai_client.is_available():
                    logger.warning("⚠️ OpenAI client reports not available")
                    return False, {"error": "OpenAI сервис недоступен"}
                
                # Получаем admin_chat_id из FSM состояния
                admin_chat_id = None
                try:
                    if hasattr(self, '_current_state_data'):
                        admin_chat_id = self._current_state_data.get('admin_chat_id')
                    
                    if not admin_chat_id:
                        admin_chat_id = self.owner_user_id
                        
                    logger.info("📱 Admin chat ID for Responses API", 
                               admin_chat_id=admin_chat_id)
                        
                except Exception as e:
                    logger.warning("⚠️ Could not determine admin_chat_id", error=str(e))
                    admin_chat_id = self.owner_user_id
                
                # Создание запроса для Responses API
                logger.info("📋 Creating Responses API agent request...")
                
                system_prompt = f"Ты - {role}. Твое имя {name}. Отвечай полезно и дружелюбно."
                
                request = OpenAIResponsesRequest(
                    bot_id=self.bot_id,
                    agent_name=name,
                    agent_role=role,
                    system_prompt=system_prompt,
                    model="gpt-4o",  # Используем лучшую модель для Responses API
                    temperature=0.7,
                    max_tokens=4000,
                    store_conversations=True,    # ВКЛЮЧАЕМ автоматическое хранение контекста
                    conversation_retention=30,   # Храним 30 дней
                    enable_streaming=True,       # Потоковые ответы
                    enable_web_search=False,     # Пока без дополнительных инструментов
                    enable_code_interpreter=False,
                    enable_file_search=False,
                    enable_image_generation=False
                )
                
                logger.info("✅ Responses API request created", 
                           agent_name=request.agent_name,
                           model=request.model,
                           store_conversations=request.store_conversations,
                           tools_enabled=sum([
                               request.enable_web_search,
                               request.enable_code_interpreter,
                               request.enable_file_search,
                               request.enable_image_generation
                           ]))
                
                # Валидация запроса
                logger.info("🔍 Validating Responses API request...")
                
                is_valid, error_msg = openai_client.validate_create_request(request)
                
                if not is_valid:
                    logger.error("❌ Responses API request validation failed", 
                               validation_error=error_msg)
                    return False, {"error": error_msg}
                
                logger.info("✅ Request validation passed")
                
                # Конвертация в агента
                agent = request.to_agent()
                
                logger.info("✅ Agent object created for Responses API", 
                           agent_name=agent.agent_name,
                           store_conversations=agent.store_conversations,
                           enable_streaming=agent.enable_streaming)
                
                # ОСНОВНОЙ ВЫЗОВ СОЗДАНИЯ ЧЕРЕЗ RESPONSES API
                logger.info("🚀 Calling OpenAI Responses API assistant creation...")
                
                creation_start_time = time.time()
                
                response = await openai_client.create_assistant(agent)
                
                creation_duration = time.time() - creation_start_time
                
                logger.info("📡 OpenAI Responses API call completed", 
                           duration=f"{creation_duration:.2f}s",
                           response_success=response.success,
                           response_text=response.output_text if response.success else None,
                           response_error=response.error if not response.success else None,
                           response_id=response.response_id if response.success else None)
                
                if response.success:
                    # УСПЕШНОЕ СОЗДАНИЕ ЧЕРЕЗ RESPONSES API
                    logger.info("🎉 OpenAI agent created successfully via Responses API")
                    
                    assistant_id = response.response_id  # Используем response_id как assistant_id
                    
                    # Сохраняем агента с Responses API настройками
                    save_success = await self._save_agent_with_responses_api(
                        assistant_id=assistant_id,
                        name=name,
                        role=role,
                        system_prompt=system_prompt,
                        agent=agent,
                        admin_chat_id=admin_chat_id
                    )
                    
                    if not save_success:
                        logger.error("❌ Failed to save Responses API agent")
                        return False, {"error": "Ошибка при сохранении агента"}
                    
                    logger.info("✅ Responses API agent created and saved")
                    
                    # ✅ ИСПРАВЛЕНО: Синхронизируем после создания
                    await self._sync_with_db_state(force=True)
                    
                    # Безопасное обновление других компонентов
                    try:
                        await self._safe_update_user_bot(
                            ai_assistant_id=assistant_id,
                            ai_assistant_settings=self.ai_assistant_settings
                        )
                        logger.info("✅ UserBot updated for Responses API")
                    except Exception as update_error:
                        logger.error("⚠️ UserBot update failed", error=str(update_error))
                    
                    try:
                        await self._safe_update_bot_manager(
                            ai_assistant_id=assistant_id,
                            ai_assistant_settings=self.ai_assistant_settings
                        )
                        logger.info("✅ BotManager updated for Responses API")
                    except Exception as update_error:
                        logger.error("⚠️ BotManager update failed", error=str(update_error))
                    
                    total_duration = time.time() - overall_start_time
                    
                    logger.info("🏁 Responses API agent creation completed successfully", 
                               bot_id=self.bot_id,
                               agent_name=name,
                               assistant_id=assistant_id,
                               total_duration=f"{total_duration:.2f}s",
                               creation_duration=f"{creation_duration:.2f}s")
                    
                    return True, {
                        "assistant_id": assistant_id,
                        "message": response.output_text,
                        "creation_method": "responses_api",
                        "creation_duration": creation_duration,
                        "total_duration": total_duration
                    }
                    
                else:
                    # ОШИБКА СОЗДАНИЯ
                    logger.error("💥 OpenAI Responses API creation failed", 
                               bot_id=self.bot_id,
                               agent_name=name,
                               error=response.error,
                               duration=f"{creation_duration:.2f}s")
                    
                    return False, {"error": response.error}
                    
            except ImportError as import_error:
                # FALLBACK ПРИ ОТСУТСТВИИ OPENAI СЕРВИСА
                logger.warning("📦 OpenAI Responses API service not available, using fallback", 
                              import_error=str(import_error))
                
                # Создание заглушки (если нужно для обратной совместимости)
                fake_assistant_id = f"asst_fallback_{int(datetime.now().timestamp())}"
                
                ai_settings = self.ai_assistant_settings.copy()
                ai_settings.update({
                    'agent_type': 'openai',
                    'agent_name': name,
                    'agent_role': role,
                    'created_at': datetime.now().isoformat(),
                    'status': 'stub_created',
                    'creation_method': 'fallback_stub',
                    'reason': 'responses_api_service_not_available',
                    'import_error': str(import_error)
                })
                
                try:
                    await self.db.update_ai_assistant(
                        self.bot_id, 
                        assistant_id=fake_assistant_id,
                        settings=ai_settings
                    )
                    
                    # ✅ ИСПРАВЛЕНО: Синхронизируем после создания fallback
                    await self._sync_with_db_state(force=True)
                    
                    total_duration = time.time() - overall_start_time
                    
                    logger.info("✅ Stub agent created (Responses API unavailable)", 
                               bot_id=self.bot_id,
                               agent_name=name,
                               fake_assistant_id=fake_assistant_id,
                               total_duration=f"{total_duration:.2f}s")
                    
                    return True, {
                        "message": "Агент создан (тестовый режим - Responses API недоступен)",
                        "assistant_id": fake_assistant_id,
                        "creation_method": "fallback_stub",
                        "total_duration": total_duration
                    }
                    
                except Exception as db_error:
                    logger.error("💥 Failed to save stub configuration", error=str(db_error))
                    return False, {"error": f"Fallback creation failed: {str(db_error)}"}
                    
        except Exception as e:
            # ОБЩАЯ ОБРАБОТКА ОШИБОК
            total_duration = time.time() - overall_start_time
            
            logger.error("💥 Exception in _create_agent_in_openai (Responses API)", 
                        bot_id=self.bot_id,
                        agent_name=name,
                        exception_type=type(e).__name__,
                        exception_message=str(e),
                        total_duration=f"{total_duration:.2f}s",
                        exc_info=True)
            
            return False, {"error": f"Внутренняя ошибка: {str(e)}"}

    async def _save_agent_with_responses_api(self, assistant_id: str, name: str, role: str, 
                                           system_prompt: str, agent: any, admin_chat_id: int) -> bool:
        """✅ ИСПРАВЛЕНО: Сохранение агента с правильной синхронизацией"""
        try:
            logger.info("💾 Saving OpenAI agent via new DatabaseManager architecture", 
                       assistant_id=assistant_id, 
                       admin_chat_id=admin_chat_id,
                       bot_id=self.bot_id)
            
            # ✅ ИСПРАВЛЕНО: Правильная структура данных с agent_type
            agent_settings = {
                'agent_type': 'openai',  # ✅ КРИТИЧНО: Устанавливаем тип агента
                'agent_name': name,
                'agent_role': role,
                'system_prompt': system_prompt,
                'model_used': agent.model,
                'model': agent.model,  # Дублируем для совместимости
                'admin_chat_id': admin_chat_id,
                'created_at': datetime.now().isoformat(),
                'creation_method': 'responses_api',
                
                # Responses API специфичные настройки
                'store_conversations': agent.store_conversations,
                'conversation_retention': agent.conversation_retention,
                'enable_streaming': getattr(agent, 'enable_streaming', True),
                'enable_web_search': False,
                'enable_code_interpreter': False,
                'enable_file_search': False,
                'enable_image_generation': False,
                
                # ✅ НОВОЕ: Настройки для синхронизации
                'openai_settings': {
                    'api_type': 'responses',
                    'store_conversations': agent.store_conversations,
                    'conversation_retention': agent.conversation_retention,
                    'enable_streaming': getattr(agent, 'enable_streaming', True),
                    'enable_web_search': False,
                    'enable_code_interpreter': False,
                    'enable_file_search': False,
                    'enable_image_generation': False,
                    'temperature': 0.7,
                    'max_tokens': 4000,
                    'top_p': 1.0,
                    'frequency_penalty': 0.0,
                    'presence_penalty': 0.0,
                    # ✅ НОВОЕ: Массив для хранения информации о файлах
                    'uploaded_files': [],
                    'files_last_updated': datetime.now().isoformat()
                }
            }
            
            logger.info("📊 Agent settings prepared", 
                       agent_type=agent_settings['agent_type'],
                       agent_name=agent_settings['agent_name'],
                       creation_method=agent_settings['creation_method'])
            
            # ✅ ИСПРАВЛЕНО: Инициализируем токеновый баланс
            try:
                # Проверяем существует ли метод
                if hasattr(self.db, 'create_or_update_user_with_tokens'):
                    user_data = {'id': self.owner_user_id}
                    await self.db.create_or_update_user_with_tokens(
                        user_data=user_data,
                        admin_chat_id=admin_chat_id
                    )
                    logger.info("✅ Token balance initialized")
                else:
                    logger.warning("⚠️ Token balance initialization method not available")
            except Exception as token_error:
                logger.warning("⚠️ Failed to initialize token balance", error=str(token_error))
            
            # ✅ ИСПРАВЛЕНО: Используем правильный метод синхронизации
            from database.managers.ai_manager import AIManager
            
            success = await AIManager.save_openai_agent_config_responses_api(
                bot_id=self.bot_id,
                agent_id=assistant_id,
                config=agent_settings
            )
            
            if success:
                logger.info("✅ OpenAI agent saved via new DatabaseManager")
                
                # ✅ ДОПОЛНИТЕЛЬНО: Обновляем кеш бота
                await self.db.expire_bot_cache(self.bot_id)
                
                return True
            else:
                logger.error("❌ Failed to save OpenAI agent via DatabaseManager")
                return False
                
        except Exception as e:
            logger.error("💥 Failed to save OpenAI agent", 
                        bot_id=self.bot_id,
                        assistant_id=assistant_id,
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            return False
