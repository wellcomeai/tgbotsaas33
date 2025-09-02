"""
Обработчик диалогов с ИИ агентами
Координирует работу с TokenManager, MessageLimitManager и конкретными обработчиками
Управляет кнопкой "Позвать ИИ", диалогами и завершением разговоров
"""

import structlog
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from ..states import AISettingsStates
from ..keyboards import AIKeyboards

logger = structlog.get_logger()


class ConversationHandler:
    """Обработчик диалогов с ИИ агентами"""
    
    def __init__(self, db, bot_config: dict, ai_assistant, user_bot, token_manager, message_limit_manager):
        self.db = db
        self.bot_config = bot_config
        self.bot_id = bot_config['bot_id']
        self.owner_user_id = bot_config['owner_user_id']
        self.bot_username = bot_config['bot_username']
        self.ai_assistant = ai_assistant
        self.user_bot = user_bot
        
        # Ссылки на менеджеры
        self.token_manager = token_manager
        self.message_limit_manager = message_limit_manager
        
        # Хранимые ссылки на основной обработчик (будут обновляться)
        self._ai_assistant_id = bot_config.get('ai_assistant_id')
        self._ai_assistant_settings = bot_config.get('ai_assistant_settings', {})
        
        logger.info("💬 ConversationHandler initialized", 
                   bot_id=self.bot_id,
                   has_token_manager=bool(token_manager),
                   has_message_limit_manager=bool(message_limit_manager))

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

    # ===== КНОПКА "ПОЗВАТЬ ИИ" =====
    
    async def handle_ai_button_click(self, message: Message, state: FSMContext, has_ai_agent_check, get_agent_type_check):
        """Упрощенная обработка кнопки ИИ - всегда доступна если агент настроен"""
        logger.info("🤖 AI button clicked", 
                   user_id=message.from_user.id,
                   bot_id=self.bot_id)
        
        try:
            user = message.from_user
            agent_type = get_agent_type_check()
            
            logger.info("📊 AI button click context", 
                       agent_type=agent_type,
                       has_ai_agent=has_ai_agent_check())
            
            # ЕДИНСТВЕННАЯ ПРОВЕРКА - есть ли агент вообще
            if not has_ai_agent_check() or agent_type == 'none':
                logger.warning("❌ AI agent not configured")
                
                # Не удаляем клавиатуру, а оставляем её для повторных попыток
                main_keyboard = await self._restore_main_keyboard()
                await message.answer(
                    "❌ ИИ агент не настроен. Обратитесь к администратору.",
                    reply_markup=main_keyboard
                )
                return
            
            # ВСЕГДА запускаем диалог если агент есть
            logger.info("✅ Starting AI conversation (no blocking checks)", 
                       user_id=user.id,
                       agent_type=agent_type)
            
            await state.set_state(AISettingsStates.in_ai_conversation)
            await state.update_data(is_test_mode=False, agent_type=agent_type)
            
            # Получаем информацию об агенте для приветствия
            agent_name = "ИИ Агент"
            agent_info = ""
            
            if agent_type == 'openai':
                agent_name = self.ai_assistant_settings.get('agent_name', 'ИИ Агент')
                settings = self.ai_assistant_settings.get('openai_settings', {})
                enabled_tools = []
                if settings.get('enable_web_search'):
                    enabled_tools.append("🌐 веб-поиск")
                if settings.get('enable_code_interpreter'):
                    enabled_tools.append("🐍 выполнение кода")
                if settings.get('enable_file_search'):
                    enabled_tools.append("📁 поиск по файлам")
                
                if enabled_tools:
                    agent_info = f"\n\n🧰 Доступные возможности: {', '.join(enabled_tools)}"
                    
            elif agent_type == 'chatforyou':
                platform = self.ai_assistant_settings.get('detected_platform')
                platform_names = {
                    'chatforyou': 'ChatForYou',
                    'protalk': 'ProTalk'
                }
                platform_display = platform_names.get(platform, platform)
                if platform_display:
                    agent_info = f"\n\n🌐 Платформа: {platform_display}"
            
            welcome_text = f"""
🤖 <b>Привет! Я {agent_name}</b>

Готов помочь вам с любыми вопросами!{agent_info}

<b>Напишите ваш вопрос:</b>
"""
            
            keyboard = AIKeyboards.conversation_menu()
            
            await message.answer(
                welcome_text,
                reply_markup=keyboard
            )
            
            logger.info("✅ AI conversation started successfully (simplified flow)")
            
        except Exception as e:
            logger.error("💥 Error starting AI conversation", 
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            
            # Не удаляем клавиатуру при ошибке
            main_keyboard = await self._restore_main_keyboard()
            await message.answer(
                "❌ Ошибка при запуске ИИ агента. Попробуйте позже.",
                reply_markup=main_keyboard
            )

    # ===== ОСНОВНОЙ ДИАЛОГ =====
    
    async def handle_ai_conversation(self, message: Message, state: FSMContext, is_owner_check, get_agent_type_check):
        """Обработка диалога с ИИ агентом - все проверки здесь + лимиты сообщений"""
        logger.info("💬 AI conversation message", 
                   user_id=message.from_user.id,
                   message_length=len(message.text),
                   bot_id=self.bot_id)
        
        # В САМОМ НАЧАЛЕ проверяем кнопку завершения диалога
        if message.text == "🚪 Завершить диалог с ИИ":
            await self.handle_ai_exit(message, state)
            return
        
        try:
            data = await state.get_data()
            is_test_mode = data.get('is_test_mode', False)
            agent_type = data.get('agent_type', get_agent_type_check())
            user_id = message.from_user.id
            
            logger.info("📊 Conversation context", 
                       is_test_mode=is_test_mode,
                       agent_type=agent_type,
                       user_id=user_id)
            
            # В тестовом режиме только владелец может тестировать
            if is_test_mode and not is_owner_check(user_id):
                logger.warning("🚫 Unauthorized test conversation", user_id=user_id)
                return
            
            # ===== ВСЕ ПРОВЕРКИ ЗДЕСЬ - В ДИАЛОГЕ =====
            
            # 1. НОВОЕ: Проверка дневного лимита сообщений (для всех типов агентов)
            if not is_test_mode:  # В тестовом режиме лимиты не действуют
                can_send, error_message = await self.message_limit_manager.check_daily_message_limit(user_id)
                if not can_send:
                    logger.warning("❌ Daily message limit exceeded", 
                                  user_id=user_id,
                                  bot_id=self.bot_id)
                    
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🚪 Завершить диалог", callback_data="ai_exit_conversation")]
                    ])
                    
                    await message.answer(error_message, reply_markup=keyboard)
                    
                    # Восстанавливаем reply клавиатуру
                    main_keyboard = await self._restore_main_keyboard()
                    await message.answer(
                        "🔧 Клавиатуры восстановлены. Попробуйте завтра!",
                        reply_markup=main_keyboard
                    )
                    return
            
            # 2. Проверка для OpenAI агентов - токены
            if agent_type == 'openai':
                can_proceed, error_message = await self.token_manager.check_token_limits_before_request(user_id)
                if not can_proceed:
                    logger.warning("❌ Token limit exceeded during conversation", 
                                  user_id=user_id)
                    
                    # Показываем ошибку прямо в диалоге с возможностью выйти
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🚪 Завершить диалог", callback_data="ai_exit_conversation")]
                    ])
                    
                    # Для владельца добавляем кнопку запроса пополнения
                    if is_owner_check(user_id):
                        keyboard.inline_keyboard.insert(0, [
                            InlineKeyboardButton(text="💳 Запросить пополнение", 
                                               callback_data="request_token_topup")
                        ])
                    
                    await message.answer(error_message, reply_markup=keyboard)
                    
                    # Восстанавливаем reply клавиатуру после ошибки
                    main_keyboard = await self._restore_main_keyboard()
                    await message.answer(
                        "🔧 Клавиатуры восстановлены. Можете снова вызвать ИИ после решения проблемы с токенами!",
                        reply_markup=main_keyboard
                    )
                    return
            
            # 3. Проверка для ChatForYou агентов - конфигурация
            elif agent_type == 'chatforyou':
                platform = self.ai_assistant_settings.get('detected_platform')
                if platform == 'chatforyou' and not self.ai_assistant_settings.get('chatforyou_bot_id'):
                    logger.warning("❌ ChatForYou configuration incomplete during conversation")
                    
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🚪 Завершить диалог", callback_data="ai_exit_conversation")]
                    ])
                    
                    await message.answer(
                        "❌ Конфигурация ИИ агента неполная.\n\n"
                        "Обратитесь к администратору для настройки ChatForYou.",
                        reply_markup=keyboard
                    )
                    
                    # Восстанавливаем reply клавиатуру после ошибки
                    main_keyboard = await self._restore_main_keyboard()
                    await message.answer(
                        "🔧 Клавиатуры восстановлены. Обратитесь к администратору для настройки!",
                        reply_markup=main_keyboard
                    )
                    return
            
            # ===== ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ - ОБРАЩАЕМСЯ К ИИ =====
            
            # Отправляем typing
            await message.bot.send_chat_action(message.chat.id, "typing")
            
            ai_response = None
            
            if agent_type == 'chatforyou':
                logger.info("🌐 Processing ChatForYou conversation")
                ai_response = await self._handle_chatforyou_conversation(message, data)
            elif agent_type == 'openai':
                logger.info("🎨 Processing OpenAI conversation via Responses API")
                ai_response = await self._handle_openai_conversation(message, data)
            else:
                logger.warning("❓ Unknown agent type for conversation", agent_type=agent_type)
            
            if ai_response:
                # Правильная логика клавиатур
                if is_test_mode:
                    # Для админа - inline кнопка
                    keyboard_buttons = [
                        [InlineKeyboardButton(text="🚪 Завершить диалог", callback_data="ai_exit_conversation")]
                    ]
                    
                    # Добавляем кнопку очистки контекста только для OpenAI
                    if agent_type == 'openai':
                        keyboard_buttons.insert(0, [InlineKeyboardButton(text="🧹 Очистить контекст", callback_data="openai_clear_context")])
                    
                    keyboard_buttons.append([InlineKeyboardButton(text="🔧 К настройкам", callback_data="admin_ai")])
                    
                    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
                else:
                    # Для пользователя - reply кнопка
                    keyboard = AIKeyboards.conversation_menu()
                
                logger.info("✅ AI response received and sent", 
                           response_length=len(ai_response),
                           has_keyboard=bool(keyboard))
                
                await message.answer(ai_response, reply_markup=keyboard)
                
                # УВЕЛИЧИВАЕМ СЧЕТЧИК СООБЩЕНИЙ (для всех типов агентов)
                if not is_test_mode and ai_response:
                    try:
                        await self.message_limit_manager.increment_daily_message_usage(user_id)
                        logger.info("📊 Daily message usage incremented", user_id=user_id)
                    except Exception as usage_error:
                        logger.error("⚠️ Failed to increment message usage", error=str(usage_error))
                
                # СОХРАНЯЕМ ТОКЕНЫ ПОСЛЕ УСПЕШНОГО ОТВЕТА (только для OpenAI)
                if agent_type == 'openai' and ai_response:
                    try:
                        # Примерная оценка токенов (можно улучшить)
                        input_tokens = len(message.text.split()) * 1.3  # примерно
                        output_tokens = len(ai_response.split()) * 1.3
                        
                        await self.token_manager.save_token_usage_after_response(
                            user_id=user_id,
                            input_tokens=int(input_tokens),
                            output_tokens=int(output_tokens),
                            admin_chat_id=message.chat.id if is_test_mode else None
                        )
                        
                        logger.info("📊 Token usage saved", 
                                   input_tokens=int(input_tokens),
                                   output_tokens=int(output_tokens))
                    except Exception as token_error:
                        logger.error("⚠️ Failed to save token usage", error=str(token_error))
                
            else:
                logger.error("❌ No AI response received")
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🚪 Завершить диалог", callback_data="ai_exit_conversation")]
                ])
                
                await message.answer(
                    "❌ Извините, ИИ агент временно недоступен. Попробуйте позже.",
                    reply_markup=keyboard
                )
                
                # Восстанавливаем reply клавиатуру после ошибки
                main_keyboard = await self._restore_main_keyboard()
                await message.answer(
                    "🔧 Клавиатуры восстановлены. Попробуйте снова позже!",
                    reply_markup=main_keyboard
                )
                
        except Exception as e:
            logger.error("💥 Error in AI conversation", 
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚪 Завершить диалог", callback_data="ai_exit_conversation")]
            ])
            
            await message.answer(
                "❌ Произошла ошибка при обращении к ИИ агенту.",
                reply_markup=keyboard
            )
            
            # Восстанавливаем reply клавиатуру после ошибки
            main_keyboard = await self._restore_main_keyboard()
            await message.answer(
                "🔧 Клавиатуры восстановлены. Можете попробовать снова!",
                reply_markup=main_keyboard
            )

    # ===== ДЕЛЕГИРОВАНИЕ К КОНКРЕТНЫМ ОБРАБОТЧИКАМ =====
    
    async def _handle_chatforyou_conversation(self, message: Message, data: dict) -> str:
        """Делегирование диалога к ChatForYouHandler"""
        try:
            # Импортируем обработчик ChatForYou
            from .ai_chatforyou_handler import ChatForYouHandler
            
            # Создаем временный экземпляр с актуальными данными
            chatforyou_handler = ChatForYouHandler(
                self.db, self.bot_config, self.ai_assistant, self.user_bot
            )
            
            # Синхронизируем данные
            chatforyou_handler.ai_assistant_id = self.ai_assistant_id
            chatforyou_handler.ai_assistant_settings = self.ai_assistant_settings
            
            # Делегируем обработку
            return await chatforyou_handler.handle_chatforyou_conversation(message, data)
            
        except Exception as e:
            logger.error("💥 Error in ChatForYou conversation delegation", 
                        error=str(e),
                        error_type=type(e).__name__)
            return None
    
    async def _handle_openai_conversation(self, message: Message, data: dict) -> str:
        """Делегирование диалога к OpenAIHandler"""
        try:
            # Импортируем обработчик OpenAI
            from .ai_openai_handler import OpenAIHandler
            
            # Создаем временный экземпляр с актуальными данными
            openai_handler = OpenAIHandler(
                self.db, self.bot_config, self.ai_assistant, self.user_bot
            )
            
            # Синхронизируем данные
            openai_handler.ai_assistant_id = self.ai_assistant_id
            openai_handler.ai_assistant_settings = self.ai_assistant_settings
            
            # Делегируем обработку
            return await openai_handler.handle_openai_conversation(message, data)
            
        except Exception as e:
            logger.error("💥 Error in OpenAI conversation delegation", 
                        error=str(e),
                        error_type=type(e).__name__)
            return None

    # ===== ЗАВЕРШЕНИЕ ДИАЛОГОВ =====
    
    async def handle_ai_exit(self, message: Message, state: FSMContext):
        """Обработка завершения диалога с ИИ (reply кнопка)"""
        logger.info("🚪 AI conversation exit via reply button", 
                   user_id=message.from_user.id,
                   bot_id=self.bot_id)
        
        try:
            await state.clear()
            
            # Используем универсальный метод восстановления клавиатуры
            main_keyboard = await self._restore_main_keyboard()
            
            await message.answer(
                "👋 Диалог с ИИ агентом завершен.\n\n"
                "Можете снова обратиться к ИИ в любое время!",
                reply_markup=main_keyboard
            )
            
            logger.info("✅ User conversation ended successfully with keyboard restored")
            
        except Exception as e:
            logger.error("💥 Error ending AI conversation", 
                        error=str(e),
                        error_type=type(e).__name__)
            
            # В случае ошибки хотя бы восстанавливаем кнопку ИИ
            fallback_keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="🤖 Позвать ИИ")]
                ],
                resize_keyboard=True,
                persistent=True
            )
            
            await message.answer(
                "👋 Диалог завершен.",
                reply_markup=fallback_keyboard
            )

    async def handle_exit_conversation(self, callback: CallbackQuery, state: FSMContext):
        """Обработка inline кнопки завершения диалога с ИИ (для админа)"""
        logger.info("🚪 Exit conversation via inline button", 
                   user_id=callback.from_user.id,
                   bot_id=self.bot_id)
        
        await callback.answer()
        await state.clear()
        
        # Редактируем текущее сообщение
        await callback.message.edit_text(
            "👋 Тестирование ИИ агента завершено.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
            ])
        )
        
        # Используем универсальный метод восстановления клавиатуры
        main_keyboard = await self._restore_main_keyboard()
        
        # Отправляем отдельное сообщение для восстановления клавиатуры
        await callback.message.answer(
            "🔧 Клавиатуры восстановлены. Можете снова вызвать ИИ!",
            reply_markup=main_keyboard
        )
        
        logger.info("✅ Admin conversation ended successfully via inline button with keyboard restored")

    # ===== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ =====
    
    async def _restore_main_keyboard(self) -> any:
        """Универсальный метод восстановления главной клавиатуры"""
        try:
            # Пытаемся импортировать клавиатуры пользователя
            from ..keyboards import UserKeyboards
            main_keyboard = UserKeyboards.main_menu()
            logger.info("✅ Main keyboard restored from UserKeyboards")
            return main_keyboard
        except (ImportError, AttributeError):
            # Fallback: создаем простую клавиатуру с кнопкой ИИ
            main_keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="🤖 Позвать ИИ")]
                ],
                resize_keyboard=True,
                persistent=True
            )
            logger.info("✅ Fallback keyboard created with AI button")
            return main_keyboard

    async def _send_error_with_keyboard_restore(self, message: Message, error_text: str, inline_keyboard: InlineKeyboardMarkup = None):
        """Отправка ошибки с восстановлением клавиатуры"""
        try:
            # Отправляем ошибку с inline кнопками
            if inline_keyboard:
                await message.answer(error_text, reply_markup=inline_keyboard)
            else:
                await message.answer(error_text)
            
            # Восстанавливаем главную клавиатуру в отдельном сообщении
            main_keyboard = await self._restore_main_keyboard()
            await message.answer(
                "🔧 Клавиатуры восстановлены. Можете снова вызвать ИИ!",
                reply_markup=main_keyboard
            )
        except Exception as e:
            logger.error("💥 Error restoring keyboard", error=str(e))

    # ===== ИНТЕГРАЦИЯ С МЕНЕДЖЕРАМИ =====
    
    async def update_references(self, ai_assistant_id, ai_assistant_settings):
        """Обновление ссылок на данные агента"""
        logger.info("🔄 Updating conversation handler references", 
                   new_ai_assistant_id=bool(ai_assistant_id))
        
        self.ai_assistant_id = ai_assistant_id
        self.ai_assistant_settings = ai_assistant_settings
        
        # Также обновляем в менеджерах если нужно
        if hasattr(self.token_manager, 'ai_assistant_settings'):
            self.token_manager.ai_assistant_settings = ai_assistant_settings
        if hasattr(self.message_limit_manager, 'ai_assistant_settings'):
            self.message_limit_manager.ai_assistant_settings = ai_assistant_settings
