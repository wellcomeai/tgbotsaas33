"""
Обработчик OpenAI агентов с поддержкой Responses API
Управляет созданием, настройкой и удалением OpenAI агентов
Поддерживает встроенные инструменты OpenAI (веб-поиск, код, файлы)
"""

import structlog
import time
from datetime import datetime
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from ..states import AISettingsStates
from ..keyboards import AIKeyboards

logger = structlog.get_logger()


class OpenAIHandler:
    """Обработчик OpenAI агентов с поддержкой Responses API"""
    
    def __init__(self, db, bot_config: dict, ai_assistant, user_bot):
        self.db = db
        self.bot_config = bot_config
        self.bot_id = bot_config['bot_id']
        self.owner_user_id = bot_config['owner_user_id']
        self.bot_username = bot_config['bot_username']
        self.ai_assistant = ai_assistant
        self.user_bot = user_bot
        
        # Хранимые ссылки на основной обработчик (будут обновляться)
        self._ai_assistant_id = bot_config.get('ai_assistant_id')
        self._ai_assistant_settings = bot_config.get('ai_assistant_settings', {})
        
        # Временное хранилище для данных состояния
        self._current_state_data = {}
        
        logger.info("🎨 OpenAIHandler initialized", 
                   bot_id=self.bot_id,
                   has_openai_agent=bool(self._ai_assistant_id))

    # ===== СВОЙСТВА ДЛЯ ДОСТУПА К АКТУАЛЬНЫМ ДАННЫМ =====
    
    @property
    def ai_assistant_id(self):
        """Получение актуального ID агента"""
        return self._ai_assistant_id
    
    @ai_assistant_id.setter
    def ai_assistant_id(self, value):
        """Установка ID агента"""
        self._ai_assistant_id = value
    
    @property 
    def ai_assistant_settings(self):
        """Получение актуальных настроек агента"""
        return self._ai_assistant_settings
    
    @ai_assistant_settings.setter
    def ai_assistant_settings(self, value):
        """Установка настроек агента"""
        self._ai_assistant_settings = value

    # ===== ОСНОВНЫЕ МЕТОДЫ УПРАВЛЕНИЯ =====
    
    async def handle_openai_action(self, callback: CallbackQuery, state: FSMContext, is_owner_check):
        """Обработка действий для OpenAI агента"""
        logger.info("🎯 OpenAI action callback", 
                   user_id=callback.from_user.id,
                   callback_data=callback.data)
        
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        action = callback.data.replace("openai_", "")
        
        logger.info("🔄 Processing OpenAI action", 
                   action=action,
                   bot_id=self.bot_id)
        
        if action == "create":
            await self._create_openai_agent(callback, state)
        elif action == "test":
            await self._test_openai_assistant(callback, state)
        elif action == "delete":
            await self._delete_openai_agent(callback)

    async def show_settings(self, callback: CallbackQuery, has_ai_agent: bool):
        """Показ настроек OpenAI агента с поддержкой инструментов"""
        logger.info("📋 Displaying OpenAI settings", 
                   bot_id=self.bot_id,
                   has_ai_agent=has_ai_agent)
        
        # Получаем информацию об OpenAI агенте
        agent_type = self.ai_assistant_settings.get('agent_type', 'none')
        openai_assistant_id = self.ai_assistant_id if agent_type == 'openai' else None
        agent_name = self.ai_assistant_settings.get('agent_name')
        creation_method = self.ai_assistant_settings.get('creation_method', 'unknown')
        
        # Получаем информацию о включенных инструментах
        settings = self.ai_assistant_settings.get('openai_settings', {})
        enabled_tools_count = sum([
            settings.get('enable_web_search', False),
            settings.get('enable_code_interpreter', False),
            settings.get('enable_file_search', False),
            settings.get('enable_image_generation', False)
        ])
        
        logger.info("🔍 OpenAI agent info", 
                   openai_assistant_id=openai_assistant_id,
                   agent_name=agent_name,
                   creation_method=creation_method,
                   enabled_tools_count=enabled_tools_count)
        
        agent_info = "не создан"
        agent_details = ""
        
        if openai_assistant_id:
            try:
                agent_info = f"ID: {openai_assistant_id[:15]}..."
                if agent_name:
                    agent_info = f"{agent_name} (ID: {openai_assistant_id[:15]}...)"
                
                if creation_method == 'fallback_stub':
                    agent_details += "\n⚠️ Режим: Тестовый (OpenAI недоступен)"
                elif creation_method == 'responses_api':
                    agent_details += "\n✅ Режим: Responses API (Автоматический контекст)"
                elif creation_method == 'real_openai_api':
                    agent_details += "\n✅ Режим: Реальный OpenAI"
                
                if enabled_tools_count > 0:
                    agent_details += f"\n🧰 Инструменты: {enabled_tools_count} включено"
                    
            except Exception as e:
                logger.error("💥 Failed to get OpenAI agent info", 
                           error=str(e),
                           error_type=type(e).__name__)
        
        text = f"""
🎨 <b>Собственный ИИ Агент</b>

<b>Текущие настройки:</b>
🎯 Агент: {agent_info}{agent_details}
🧠 Модель: GPT-4o (Responses API)
🔄 Контекст: Автоматическое управление
⚡ Лимиты: Управляются токенами

<b>Преимущества Responses API:</b>
- Контекст сохраняется автоматически на серверах OpenAI
- Встроенные инструменты (поиск, код, файлы)
- Не нужно отправлять всю историю с каждым сообщением
- Быстрые ответы и стабильная работа 24/7

<b>Управление агентом:</b>
"""
        
        keyboard = AIKeyboards.openai_settings_menu(bool(openai_assistant_id))
        
        # Добавляем кнопку управления инструментами если агент создан
        if openai_assistant_id:
            keyboard.inline_keyboard.insert(-1, [
                InlineKeyboardButton(text="🧰 Встроенные инструменты", callback_data="openai_tools_settings")
            ])
            # Добавляем кнопку синхронизации данных
            keyboard.inline_keyboard.insert(-1, [
                InlineKeyboardButton(text="🔄 Синхронизировать данные", callback_data="sync_agent_data")
            ])
        
        # Добавляем кнопку смены типа агента
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="🔄 Сменить тип агента", callback_data="ai_change_type")
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)

    # ===== СОЗДАНИЕ АГЕНТА =====
    
    async def _create_openai_agent(self, callback: CallbackQuery, state: FSMContext):
        """Начало создания OpenAI агента"""
        logger.info("🎨 Starting OpenAI agent creation flow", 
                   user_id=callback.from_user.id,
                   bot_id=self.bot_id)
        
        await state.set_state(AISettingsStates.waiting_for_openai_name)
        
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
        """Обработка ввода имени OpenAI агента"""
        logger.info("📝 OpenAI agent name input", 
                   user_id=message.from_user.id,
                   input_text=message.text,
                   bot_id=self.bot_id)
        
        if not is_owner_check(message.from_user.id):
            return
        
        if message.text == "/cancel":
            await self._cancel_and_show_ai(message, state)
            return
        
        agent_name = message.text.strip()
        
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
        await state.set_state(AISettingsStates.waiting_for_openai_role)
        
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
        """Обработка ввода роли OpenAI агента с улучшенным UX"""
        logger.info("📝 OpenAI agent role input", 
                   user_id=message.from_user.id,
                   input_length=len(message.text),
                   bot_id=self.bot_id)
        
        if not is_owner_check(message.from_user.id):
            return
        
        if message.text == "/cancel":
            await self._cancel_and_show_ai(message, state)
            return
        
        agent_role = message.text.strip()
        
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
• Попробуйте через 2-3 минуты
• Или создайте агента позже
• Проблема решится автоматически

<b>Это НЕ ошибка вашего бота!</b>
"""
                elif "429" in error_msg or "rate" in error_msg:
                    user_friendly_error = """
❌ <b>Превышен лимит запросов</b>

OpenAI ограничивает количество запросов в минуту.

<b>Что делать:</b>
• Подождите 1-2 минуты
• Попробуйте создать агента снова
• Это временное ограничение
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
                    
                    # Обновляем локальные настройки
                    self.ai_assistant_id = assistant_id
                    
                    # Получаем свежие данные из БД
                    fresh_config = await self.db.get_bot_full_config(self.bot_id, fresh=True)
                    if fresh_config:
                        self.ai_assistant_settings = fresh_config.get('ai_assistant_settings', {})
                        logger.info("✅ Local settings updated from synced DB data")
                    
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
                    
                    self.ai_assistant_id = fake_assistant_id
                    self.ai_assistant_settings = ai_settings
                    
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
        """Сохранение агента с настройками Responses API"""
        try:
            logger.info("💾 Saving agent via new DatabaseManager architecture", 
                       assistant_id=assistant_id, 
                       admin_chat_id=admin_chat_id)
            
            # Используем правильную структуру данных для новой архитектуры
            agent_settings = {
                'agent_type': 'openai',
                'agent_name': name,
                'agent_role': role,
                'system_prompt': system_prompt,
                'model_used': agent.model,
                'admin_chat_id': admin_chat_id,
                'created_at': datetime.now().isoformat(),
                'creation_method': 'responses_api',
                
                # Responses API специфичные настройки
                'store_conversations': agent.store_conversations,
                'conversation_retention': agent.conversation_retention,
                'enable_streaming': getattr(agent, 'enable_streaming', True),
                'enable_web_search': False,  # По умолчанию выключено
                'enable_code_interpreter': False,
                'enable_file_search': False,
                'enable_image_generation': False
            }
            
            # Инициализируем токеновый баланс (если нужно)
            await self.db.initialize_token_balance(
                user_id=self.owner_user_id,
                admin_chat_id=admin_chat_id,
                bot_id=self.bot_id
            )
            
            # Используем новый метод с правильной синхронизацией
            success = await self.db.update_ai_assistant(
                bot_id=self.bot_id,
                enabled=True,
                assistant_id=assistant_id,
                settings=agent_settings
            )
            
            if success:
                logger.info("✅ Agent saved via new architecture")
                return True
            else:
                logger.error("❌ Failed to save agent via new architecture")
                return False
                
        except Exception as e:
            logger.error("💥 Failed to save agent", error=str(e), exc_info=True)
            return False

    # ===== ТЕСТИРОВАНИЕ =====
    
    async def _test_openai_assistant(self, callback: CallbackQuery, state: FSMContext):
        """Тестирование OpenAI ассистента через Responses API"""
        logger.info("🧪 Starting OpenAI assistant test via Responses API", 
                   bot_id=self.bot_id)
        
        agent_type = self.ai_assistant_settings.get('agent_type', 'none')
        openai_assistant_id = self.ai_assistant_id if agent_type == 'openai' else None
        
        if not openai_assistant_id:
            logger.warning("❌ No OpenAI agent created for testing")
            await callback.answer("❌ Сначала создайте OpenAI агента", show_alert=True)
            return
        
        logger.info("✅ Starting OpenAI test mode via Responses API", 
                   openai_assistant_id=openai_assistant_id)
        
        await state.set_state(AISettingsStates.in_ai_conversation)
        await state.update_data(is_test_mode=True, agent_type='openai')
        
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
• Контекст сохраняется автоматически на серверах OpenAI
• Не нужно отправлять всю историю с каждым сообщением
• Поддержка встроенных инструментов

<b>Напишите ваш вопрос:</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚪 Завершить диалог", callback_data="ai_exit_conversation")],
            [InlineKeyboardButton(text="🧹 Очистить контекст", callback_data="openai_clear_context")],
            [InlineKeyboardButton(text="🔧 К настройкам", callback_data="admin_ai")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)

    # ===== УПРАВЛЕНИЕ ИНСТРУМЕНТАМИ =====
    
    async def handle_tools_settings(self, callback: CallbackQuery, is_owner_check):
        """Настройка встроенных инструментов Responses API"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Получаем текущие настройки инструментов
            settings = self.ai_assistant_settings.get('openai_settings', {})
            
            web_search = "✅" if settings.get('enable_web_search') else "❌"
            code_interpreter = "✅" if settings.get('enable_code_interpreter') else "❌"
            file_search = "✅" if settings.get('enable_file_search') else "❌"
            
            vector_stores_count = len(settings.get('vector_store_ids', []))
            file_search_info = f" ({vector_stores_count} хранилищ)" if vector_stores_count > 0 else ""
            
            text = f"""
🧰 <b>Встроенные инструменты Responses API</b>

<b>Текущие настройки:</b>
🌐 Веб-поиск: {web_search}
🐍 Интерпретатор кода: {code_interpreter}
📁 Поиск по файлам: {file_search}{file_search_info}

<b>Описание инструментов:</b>

🌐 <b>Веб-поиск</b>
• Поиск актуальной информации в интернете
• Автоматические цитаты и ссылки
• Стоимость: $25-50 за 1000 запросов

🐍 <b>Интерпретатор кода</b>
• Выполнение Python кода
• Анализ данных и построение графиков
• Математические вычисления

📁 <b>Поиск по файлам</b>
• Поиск в загруженных документах
• RAG на основе векторных хранилищ
• Стоимость: $2.50 за 1000 запросов
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🌐 Веб-поиск {web_search}", 
                                    callback_data="openai_toggle_web_search")],
                [InlineKeyboardButton(text=f"🐍 Код {code_interpreter}", 
                                    callback_data="openai_toggle_code_interpreter")],
                [InlineKeyboardButton(text=f"📁 Файлы {file_search}", 
                                    callback_data="openai_toggle_file_search")],
                [InlineKeyboardButton(text="🔧 Загрузить файлы", 
                                    callback_data="openai_upload_files")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_ai")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error("💥 Error showing tools settings", error=str(e))
            await callback.answer("Ошибка при загрузке настроек", show_alert=True)

    async def handle_toggle_web_search(self, callback: CallbackQuery, is_owner_check):
        """Переключение веб-поиска"""
        await self._toggle_openai_tool(callback, 'web_search', 'Веб-поиск', is_owner_check)

    async def handle_toggle_code_interpreter(self, callback: CallbackQuery, is_owner_check):
        """Переключение интерпретатора кода"""
        await self._toggle_openai_tool(callback, 'code_interpreter', 'Интерпретатор кода', is_owner_check)

    async def handle_toggle_file_search(self, callback: CallbackQuery, is_owner_check):
        """Переключение поиска по файлам"""
        await self._toggle_openai_tool(callback, 'file_search', 'Поиск по файлам', is_owner_check)

    async def _toggle_openai_tool(self, callback: CallbackQuery, tool_name: str, tool_display_name: str, is_owner_check):
        """Переключение встроенного инструмента"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Получаем текущие настройки
            settings = self.ai_assistant_settings.copy()
            openai_settings = settings.get('openai_settings', {})
            
            # Переключаем инструмент
            setting_key = f'enable_{tool_name}'
            current_value = openai_settings.get(setting_key, False)
            openai_settings[setting_key] = not current_value
            
            settings['openai_settings'] = openai_settings
            
            # Сохраняем в БД
            await self.db.update_ai_assistant(
                self.bot_id,
                settings=settings
            )
            
            # Обновляем локальные настройки
            self.ai_assistant_settings = settings
            
            status = "включен" if not current_value else "выключен"
            await callback.answer(f"{tool_display_name} {status}")
            
            logger.info("🔧 Tool toggled", 
                       tool_name=tool_name,
                       new_status=not current_value,
                       bot_id=self.bot_id)
            
            # Обновляем меню
            await self.handle_tools_settings(callback, is_owner_check)
            
        except Exception as e:
            logger.error("💥 Error toggling tool", tool=tool_name, error=str(e))
            await callback.answer("Ошибка при изменении настройки", show_alert=True)

    async def handle_upload_files(self, callback: CallbackQuery, is_owner_check):
        """Загрузка файлов для file_search"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        text = """
📁 <b>Загрузка файлов для поиска</b>

⚠️ <b>Функция в разработке</b>

Для включения поиска по файлам вам понадобится:
1. Создать векторное хранилище в OpenAI
2. Загрузить документы в хранилище
3. Получить ID хранилища
4. Добавить ID в настройки бота

<b>Обратитесь к администратору для настройки</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад к инструментам", callback_data="openai_tools_settings")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)

    # ===== УПРАВЛЕНИЕ КОНТЕКСТОМ =====
    
    async def handle_clear_context(self, callback: CallbackQuery, is_owner_check):
        """Очистка контекста разговора в Responses API"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            logger.info("🧹 Clearing OpenAI conversation context via Responses API", 
                       user_id=callback.from_user.id,
                       bot_id=self.bot_id)
            
            agent_type = self.ai_assistant_settings.get('agent_type', 'none')
            openai_assistant_id = self.ai_assistant_id if agent_type == 'openai' else None
            
            if not openai_assistant_id:
                await callback.answer("❌ OpenAI агент не найден", show_alert=True)
                return
            
            # Очищаем контекст через Responses API клиент
            from services.openai_assistant import openai_client
            
            success = await openai_client.clear_conversation(
                assistant_id=openai_assistant_id,
                user_id=callback.from_user.id
            )
            
            if success:
                await callback.answer("✅ Контекст разговора очищен")
                logger.info("✅ Conversation context cleared successfully")
                
                # Обновляем сообщение с кнопками
                settings = self.ai_assistant_settings.get('openai_settings', {})
                enabled_tools = []
                if settings.get('enable_web_search'):
                    enabled_tools.append("🌐 Веб-поиск")
                if settings.get('enable_code_interpreter'):
                    enabled_tools.append("🐍 Интерпретатор кода")
                if settings.get('enable_file_search'):
                    enabled_tools.append("📁 Поиск по файлам")
                
                tools_text = ""
                if enabled_tools:
                    tools_text = f"\n<b>Включенные инструменты:</b> {', '.join(enabled_tools)}"
                
                text = f"""
🧪 <b>Тестирование OpenAI агента (Responses API)</b>

<b>Агент ID:</b> {openai_assistant_id[:15]}...
<b>Модель:</b> GPT-4o (Responses API) 
<b>Режим:</b> Автоматический контекст{tools_text}

✨ <b>Контекст очищен!</b> Начинается новый разговор.

<b>Напишите ваш вопрос:</b>
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🚪 Завершить диалог", callback_data="ai_exit_conversation")],
                    [InlineKeyboardButton(text="🧹 Очистить контекст", callback_data="openai_clear_context")],
                    [InlineKeyboardButton(text="🔧 К настройкам", callback_data="admin_ai")]
                ])
                
                try:
                    await callback.message.edit_text(text, reply_markup=keyboard)
                except Exception as edit_error:
                    logger.warning("⚠️ Could not edit message after context clear", error=str(edit_error))
                    
            else:
                await callback.answer("❌ Ошибка при очистке контекста", show_alert=True)
                logger.error("❌ Failed to clear conversation context")
                
        except Exception as e:
            logger.error("💥 Error clearing conversation context", 
                        error=str(e),
                        error_type=type(e).__name__)
            await callback.answer("❌ Ошибка при очистке контекста", show_alert=True)

    # ===== УДАЛЕНИЕ АГЕНТА =====
    
    async def _delete_openai_agent(self, callback: CallbackQuery):
        """Удаление OpenAI агента"""
        logger.info("🗑️ Deleting OpenAI agent", 
                   bot_id=self.bot_id)
        
        agent_name = self.ai_assistant_settings.get('agent_name', 'агента')
        
        text = f"""
🗑️ <b>Удаление ИИ агента "{agent_name}"</b>

⚠️ <b>Внимание!</b> При удалении агента:
- Агент будет удален из нашей системы
- Пользователи не смогут к нему обращаться
- Все настройки будут потеряны
- Восстановить будет невозможно

Вы уверены, что хотите удалить агента?
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data="openai_confirm_delete")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_ai")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)

    async def handle_confirm_delete(self, callback: CallbackQuery, is_owner_check):
        """Подтверждение удаления OpenAI агента"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            logger.info("🗑️ Confirming OpenAI agent deletion", 
                       bot_id=self.bot_id)
            
            agent_type = self.ai_assistant_settings.get('agent_type', 'none')
            openai_assistant_id = self.ai_assistant_id if agent_type == 'openai' else None
            agent_name = self.ai_assistant_settings.get('agent_name', 'агента')
            
            await callback.message.edit_text("🔄 Удаляем OpenAI агента...")
            
            # Попытка удалить агента из OpenAI (если возможно)
            if openai_assistant_id:
                try:
                    from services.openai_assistant import openai_client
                    await openai_client.delete_assistant(openai_assistant_id)
                    logger.info("✅ OpenAI assistant deleted from API")
                except Exception as api_error:
                    logger.warning("⚠️ Could not delete from OpenAI API", error=str(api_error))
            
            # Очищаем конфигурацию из БД
            await self.db.clear_ai_configuration(self.bot_id)
            await self.db.expire_bot_cache(self.bot_id)
            
            # Очищаем локальные настройки
            self.ai_assistant_id = None
            self.ai_assistant_settings = {'agent_type': 'none'}
            
            # Обновляем другие компоненты
            await self._safe_update_user_bot(
                ai_assistant_id=None,
                ai_assistant_settings=self.ai_assistant_settings
            )
            await self._safe_update_bot_manager(
                ai_assistant_id=None,
                ai_assistant_settings=self.ai_assistant_settings
            )
            
            await callback.message.edit_text(
                f'✅ OpenAI агент "{agent_name}" удален успешно.',
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🤖 Создать нового агента", callback_data="admin_ai")]
                ])
            )
            
            logger.info("✅ OpenAI agent deleted successfully")
            
        except Exception as e:
            logger.error("💥 Error deleting OpenAI agent", 
                        error=str(e),
                        error_type=type(e).__name__)
            await callback.answer("Ошибка при удалении агента", show_alert=True)

    # ===== СИНХРОНИЗАЦИЯ ДАННЫХ =====
    
    async def handle_sync_agent_data(self, callback: CallbackQuery, is_owner_check):
        """Ручная синхронизация данных агента"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            logger.info("🔄 Manual agent data sync requested", bot_id=self.bot_id)
            
            # Синхронизируем данные
            success = await self.db.sync_agent_data_fields(bot_id=self.bot_id)
            
            if success:
                # Проверяем результат
                validation = await self.db.validate_agent_data_consistency(self.bot_id)
                
                status = validation.get('overall_status', 'unknown')
                if status == 'consistent':
                    await callback.answer("✅ Данные агента синхронизированы")
                else:
                    recommendations = validation.get('recommendations', [])
                    await callback.answer(f"⚠️ Найдены проблемы: {', '.join(recommendations)}")
            else:
                await callback.answer("❌ Ошибка синхронизации", show_alert=True)
                
        except Exception as e:
            logger.error("💥 Error in manual sync", error=str(e))
            await callback.answer("❌ Ошибка синхронизации", show_alert=True)

    # ===== ДИАЛОГ С OPENAI =====
    
    async def handle_openai_conversation(self, message: Message, data: dict) -> str:
        """Обработка диалога с OpenAI агентом через Responses API"""
        logger.info("🎨 OpenAI conversation processing via Responses API", 
                   user_id=message.from_user.id,
                   message_length=len(message.text))
        
        try:
            # Получаем assistant_id (теперь используем только его)
            agent_type = self.ai_assistant_settings.get('agent_type', 'none')
            openai_assistant_id = self.ai_assistant_id if agent_type == 'openai' else None
            
            if not openai_assistant_id:
                logger.error("❌ No OpenAI assistant ID")
                return "❌ OpenAI агент не настроен."
            
            logger.info("📊 OpenAI Responses API conversation parameters", 
                       openai_assistant_id=openai_assistant_id,
                       is_test_mode=data.get('is_test_mode', False))
            
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
                    is_admin=data.get('is_test_mode', False)
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
                    logger.info("📊 Responses API conversation completed successfully")
                    return response
                else:
                    return "❌ Не удалось получить ответ от OpenAI."
                    
            except ImportError:
                # Fallback для случая когда OpenAI сервис недоступен
                logger.warning("📦 OpenAI Responses API service not available, using fallback")
                agent_name = self.ai_assistant_settings.get('agent_name', 'ИИ Агент')
                return f"🤖 {agent_name}: Получил ваше сообщение '{message.text}'. Responses API сервис временно недоступен."
            
        except Exception as e:
            logger.error("💥 Error in OpenAI Responses API conversation", 
                        error=str(e),
                        error_type=type(e).__name__)
            return None

    # ===== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ =====
    
    async def _cancel_and_show_ai(self, message: Message, state: FSMContext):
        """Отмена и показ настроек ИИ"""
        logger.info("❌ Cancelling OpenAI operation", 
                   user_id=message.from_user.id,
                   bot_id=self.bot_id)
        
        await state.clear()
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
        ])
        await message.answer("Настройка отменена", reply_markup=keyboard)
    
    async def _safe_update_user_bot(self, **kwargs):
        """Безопасное обновление настроек UserBot"""
        logger.info("🔄 Attempting UserBot update", 
                   bot_id=self.bot_id,
                   update_keys=list(kwargs.keys()))
        
        try:
            if self.user_bot and hasattr(self.user_bot, 'update_ai_settings'):
                await self.user_bot.update_ai_settings(**kwargs)
                logger.info("✅ UserBot update successful")
            else:
                logger.warning("⚠️ UserBot doesn't have update_ai_settings method", 
                             bot_id=self.bot_id,
                             has_user_bot=bool(self.user_bot),
                             has_method=hasattr(self.user_bot, 'update_ai_settings') if self.user_bot else False)
        except Exception as e:
            logger.error("💥 Failed to update UserBot settings", 
                        bot_id=self.bot_id,
                        error=str(e),
                        error_type=type(e).__name__)
    
    async def _safe_update_bot_manager(self, **kwargs):
        """Безопасное обновление через bot_manager"""
        logger.info("🔄 Attempting BotManager update", 
                   bot_id=self.bot_id,
                   update_keys=list(kwargs.keys()))
        
        try:
            bot_manager = self.bot_config.get('bot_manager')
            if bot_manager and hasattr(bot_manager, 'update_bot_config'):
                await bot_manager.update_bot_config(self.bot_id, **kwargs)
                logger.info("✅ BotManager update successful")
            else:
                logger.warning("⚠️ BotManager doesn't have update_bot_config method", 
                             bot_id=self.bot_id,
                             has_bot_manager=bool(bot_manager),
                             has_method=hasattr(bot_manager, 'update_bot_config') if bot_manager else False)
        except Exception as e:
            logger.error("💥 Failed to update BotManager config", 
                        bot_id=self.bot_id,
                        error=str(e),
                        error_type=type(e).__name__)
