"""
Методы создания контент-агентов.

✅ ПОЛНАЯ ФУНКЦИОНАЛЬНОСТЬ:
1. 🎤 Поддержка голосовых инструкций через OpenAI Whisper API
2. 📺 Подключение каналов для публикации
3. 🔧 Валидация всех входных данных
4. 🛡️ Обработка ошибок и edge cases
5. 📊 Детальное логирование процесса
6. ✨ Упрощенный интерфейс для пользователей
7. 🤖 Интеграция с OpenAI для создания агентов
"""

from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from services.content_agent import content_agent_service

# Безопасный импорт состояний
try:
    from ...states import ContentStates
    CONTENT_STATES_AVAILABLE = True
except ImportError:
    from aiogram.fsm.state import State, StatesGroup
    
    class ContentStates(StatesGroup):
        waiting_for_agent_name = State()
        waiting_for_agent_instructions = State()
        editing_agent_name = State()
        editing_agent_instructions = State()
        waiting_for_rewrite_post = State()
        waiting_for_channel_post = State()
        waiting_for_edit_instructions = State()
    
    CONTENT_STATES_AVAILABLE = False

# Импорт для проверки медиагрупп
try:
    from aiogram_media_group import media_group_handler
    MEDIA_GROUP_AVAILABLE = True
except ImportError:
    MEDIA_GROUP_AVAILABLE = False


class AgentCreationMixin:
    """Миксин для методов создания агентов"""
    
    async def cb_create_agent(self, callback: CallbackQuery, state: FSMContext):
        """ИЗМЕНЕНО: Начало создания агента - сначала канал"""
        self.logger.info("✨ Create agent button pressed", 
                        user_id=callback.from_user.id,
                        bot_id=self.bot_id,
                        callback_data=callback.data)
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            self.logger.warning("🚫 Non-owner tried to create agent", 
                               user_id=callback.from_user.id,
                               bot_id=self.bot_id)
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Проверяем, не существует ли уже агент
            self.logger.debug("🔍 Checking existing agent before creation", bot_id=self.bot_id)
            has_agent = await content_agent_service.has_content_agent(self.bot_id)
            
            if has_agent:
                self.logger.warning("⚠️ Agent already exists, creation blocked", bot_id=self.bot_id)
                await callback.answer("Агент уже создан", show_alert=True)
                return
            
            text = f"""
✨ <b>Создание контент-агента</b>

<b>Шаг 1 из 3: Канал для публикации</b>

Для работы с контент-агентом нужно указать канал, куда будут публиковаться посты.

📝 <b>Как добавить канал:</b>
1. Перешлите любой пост из вашего канала
2. Бот автоматически определит канал
3. Убедитесь что бот добавлен в канал как администратор

⚠️ <b>Важно:</b> Бот должен иметь права на публикацию в канале.

<b>Перешлите пост из канала:</b>
"""
            
            keyboards = await self._get_content_keyboards()
            
            await self._safe_edit_or_answer(callback, text, keyboards['back_to_main'])
            
            if CONTENT_STATES_AVAILABLE:
                await state.set_state(ContentStates.waiting_for_channel_post)
                self.logger.info("✅ FSM state set for channel post input", bot_id=self.bot_id)
            else:
                self.logger.warning("⚠️ FSM states not available, using fallback", bot_id=self.bot_id)
            
            self.logger.info("✅ Agent creation flow started successfully", 
                           bot_id=self.bot_id,
                           user_id=callback.from_user.id)
            
        except Exception as e:
            self.logger.error("💥 Failed to start agent creation", 
                            bot_id=self.bot_id,
                            error=str(e),
                            error_type=type(e).__name__,
                            exc_info=True)
            await callback.answer("Ошибка при создании агента", show_alert=True)
    
    async def handle_channel_post_input(self, message: Message, state: FSMContext):
        """Обработка пересланного поста из канала"""
        self.logger.info("📺 Channel post input received", 
                        user_id=message.from_user.id,
                        bot_id=self.bot_id)
        
        if not self._is_owner(message.from_user.id):
            await message.answer("❌ Доступ запрещен")
            return
        
        try:
            # Проверяем что это пересланное сообщение из канала
            if not message.forward_from_chat:
                await message.answer("❌ Пришлите переслaнный пост из канала")
                return
            
            if message.forward_from_chat.type != "channel":
                await message.answer("❌ Сообщение должно быть из канала")
                return
            
            channel_id = message.forward_from_chat.id
            channel_title = message.forward_from_chat.title
            channel_username = message.forward_from_chat.username
            
            # Сохраняем информацию о канале
            channel_data = {
                'chat_id': channel_id,
                'chat_title': channel_title,
                'chat_username': channel_username,
                'chat_type': 'channel'
            }
            
            success = await content_agent_service.content_manager.save_channel_info(
                self.bot_id, channel_data
            )
            
            if not success:
                await message.answer("❌ Ошибка сохранения канала")
                return
            
            # Переходим к следующему шагу - имя агента
            text = f"""
✅ <b>Канал добавлен успешно!</b>

📺 <b>Канал:</b> {channel_title}
🆔 <b>ID:</b> <code>{channel_id}</code>
👤 <b>Username:</b> @{channel_username or 'не указан'}

<b>Шаг 2 из 3: Имя агента</b>

Придумайте имя для вашего ИИ агента:

📝 <b>Примеры:</b>
- "Редактор канала {channel_title}"
- "Копирайтер"
- "SMM помощник"

<b>Введите имя агента:</b>
"""
            
            await message.answer(text)
            await state.set_state(ContentStates.waiting_for_agent_name)
            
            self.logger.info("✅ Channel saved successfully", 
                           bot_id=self.bot_id,
                           channel_id=channel_id,
                           channel_title=channel_title)
            
        except Exception as e:
            self.logger.error("💥 Error processing channel post", 
                            bot_id=self.bot_id,
                            error=str(e))
            await message.answer("Ошибка при обработке канала")
    
    async def handle_agent_name_input(self, message: Message, state: FSMContext):
        """✅ Обработка ввода имени агента с валидацией"""
        self.logger.info("📝 Agent name input received", 
                        user_id=message.from_user.id,
                        bot_id=self.bot_id,
                        message_length=len(message.text or ""))
        
        if not self._is_owner(message.from_user.id):
            self.logger.warning("🚫 Non-owner tried to input agent name", 
                               user_id=message.from_user.id)
            await message.answer("❌ Доступ запрещен")
            return
        
        try:
            agent_name = message.text.strip()
            
            # Валидация имени
            if not agent_name:
                self.logger.debug("❌ Empty agent name provided", bot_id=self.bot_id)
                await message.answer("❌ Имя не может быть пустым. Попробуйте еще раз:")
                return
            
            if len(agent_name) < 3:
                self.logger.debug("❌ Agent name too short", bot_id=self.bot_id, length=len(agent_name))
                await message.answer("❌ Имя слишком короткое (минимум 3 символа). Попробуйте еще раз:")
                return
            
            if len(agent_name) > 100:
                self.logger.debug("❌ Agent name too long", bot_id=self.bot_id, length=len(agent_name))
                await message.answer("❌ Имя слишком длинное (максимум 100 символов). Попробуйте еще раз:")
                return
            
            # Сохраняем имя в состоянии
            await state.update_data(agent_name=agent_name)
            
            text = f"""
✨ <b>Создание контент-агента</b>

<b>Шаг 3 из 3: Инструкции для рерайта</b>

👤 <b>Имя агента:</b> {agent_name}

Теперь опишите, КАК агент должен переписывать тексты. Эти инструкции будут использоваться для всех рерайтов.

🎤 <b>НОВОЕ: Вы можете записать инструкции ГОЛОСОМ!</b>

📝 <b>Примеры инструкций:</b>

<b>Дружелюбный стиль:</b>
"Переписывай тексты в дружелюбном, теплом тоне. Используй эмоджи и обращения к читателю. Делай текст более живым и близким."

<b>Деловой стиль:</b>  
"Переписывай в официально-деловом стиле. Убирай лишние эмоции, делай текст четким и структурированным. Фокус на фактах."

<b>Креативный подход:</b>
"Делай тексты более яркими и запоминающимися. Используй метафоры, интересные сравнения. Привлекай внимание необычными формулировками."

<b>Введите ваши инструкции текстом или 🎤 запишите голосом:</b>
"""
            
            keyboards = await self._get_content_keyboards()
            
            await message.answer(
                text,
                reply_markup=keyboards['back_to_main']
            )
            
            if CONTENT_STATES_AVAILABLE:
                await state.set_state(ContentStates.waiting_for_agent_instructions)
            
            self.logger.info("✅ Agent name validated and saved", 
                           bot_id=self.bot_id,
                           agent_name=agent_name,
                           name_length=len(agent_name))
            
        except Exception as e:
            self.logger.error("💥 Failed to process agent name input", 
                            bot_id=self.bot_id,
                            error=str(e),
                            error_type=type(e).__name__,
                            exc_info=True)
            await message.answer("❌ Ошибка при обработке имени. Попробуйте еще раз:")
    
    async def handle_agent_instructions_input(self, message: Message, state: FSMContext):
        """🎤 ОБНОВЛЕНО: Обработка ввода инструкций агента (текст или голос)"""
        self.logger.info("📋 Agent instructions input received", 
                        user_id=message.from_user.id,
                        bot_id=self.bot_id,
                        has_text=bool(message.text),
                        has_voice=bool(message.voice),
                        instructions_length=len(message.text or "") if message.text else 0)
        
        if not self._is_owner(message.from_user.id):
            await message.answer("❌ Доступ запрещен")
            return
        
        try:
            instructions = None
            
            # 🎤 ОБРАБОТКА ГОЛОСОВЫХ СООБЩЕНИЙ
            if message.voice:
                self.logger.info("🎤 Voice instructions received, transcribing...", 
                                user_id=message.from_user.id,
                                bot_id=self.bot_id)
                
                await message.bot.send_chat_action(message.chat.id, "typing")
                
                instructions = await self._transcribe_voice_message(message.voice)
                
                if not instructions:
                    await message.answer("❌ Не удалось распознать голосовое сообщение. Попробуйте еще раз или напишите текстом.")
                    return
                
                self.logger.info("✅ Voice instructions transcribed successfully", 
                               user_id=message.from_user.id,
                               bot_id=self.bot_id,
                               transcribed_length=len(instructions))
                
                # Показываем что распознали
                await message.answer(f"🎤 <b>Распознано:</b>\n<i>{instructions[:200]}{'...' if len(instructions) > 200 else ''}</i>\n\n⏳ Проверяю инструкции...")
                
            elif message.text:
                instructions = message.text.strip()
            else:
                await message.answer("❌ Пожалуйста, отправьте текстовое или голосовое сообщение.")
                return
            
            # Валидация инструкций
            if not instructions:
                await message.answer("❌ Инструкции не могут быть пустыми. Попробуйте еще раз:")
                return
            
            if len(instructions) < 10:
                await message.answer("❌ Инструкции слишком короткие (минимум 10 символов). Опишите подробнее:")
                return
            
            if len(instructions) > 4096:
                await message.answer("❌ Инструкции слишком длинные (максимум 2000 символов). Сократите:")
                return
            
            # Получаем сохраненное имя
            data = await state.get_data()
            agent_name = data.get('agent_name')
            
            if not agent_name:
                await message.answer("❌ Ошибка: потеряно имя агента. Начните заново:")
                await state.clear()
                return
            
            # Показываем предпросмотр
            input_method = "🎤 голосом" if message.voice else "📝 текстом"
            
            text = f"""
✨ <b>Подтверждение создания агента</b>

👤 <b>Имя агента:</b> {agent_name}

📋 <b>Инструкции (введены {input_method}):</b>
{instructions}

📊 <b>Параметры:</b>
• Модель: OpenAI GPT-4o
• Тип: Responses API  
• Токены: из общего лимита
• Медиа: фото, видео (file_id сохраняется)
• Альбомы: {'✅ Поддерживаются' if MEDIA_GROUP_AVAILABLE else '❌ Недоступны'}
• 🔗 Ссылки: автоматическое извлечение и сохранение
• ✏️ Редактирование: внесение правок в готовые посты
• 📤 Публикация: прямая отправка в каналы
• 🎤 Голосовые сообщения: ✅ Поддерживаются

⚠️ <b>После создания агента изменить можно будет только имя и инструкции (текстом или голосом). OpenAI интеграция пересоздается полностью.</b>

<b>Создать агента с этими настройками?</b>
"""
            
            # Сохраняем инструкции в состоянии
            await state.update_data(
                agent_name=agent_name,
                instructions=instructions,
                input_method=input_method
            )
            
            keyboards = await self._get_content_keyboards()
            
            await message.answer(
                text,
                reply_markup=keyboards['create_confirmation']
            )
            
            self.logger.info("✅ Agent instructions validated and preview shown with voice support", 
                           bot_id=self.bot_id,
                           agent_name=agent_name,
                           instructions_length=len(instructions),
                           input_method=input_method)
            
        except Exception as e:
            self.logger.error("💥 Failed to process agent instructions input with voice", 
                            bot_id=self.bot_id,
                            error=str(e))
            await message.answer("❌ Ошибка при обработке инструкций. Попробуйте еще раз:")
    
    async def cb_confirm_create_agent(self, callback: CallbackQuery, state: FSMContext):
        """✅ Подтверждение создания агента"""
        self.logger.info("✅ Agent creation confirmation received", 
                        user_id=callback.from_user.id,
                        bot_id=self.bot_id)
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Получаем данные из состояния
            data = await state.get_data()
            agent_name = data.get('agent_name')
            instructions = data.get('instructions')
            input_method = data.get('input_method', '📝 текстом')
            
            if not agent_name or not instructions:
                await callback.answer("Ошибка: данные агента потеряны", show_alert=True)
                await state.clear()
                return
            
            # Показываем процесс создания
            await self._safe_edit_or_answer(
                callback,
                f"⏳ <b>Создание агента '{agent_name}'...</b>\n\n"
                f"📋 Инструкции введены {input_method}\n"
                f"🤖 Настройка OpenAI интеграции...\n"
                f"💾 Сохранение в базу данных...\n\n"
                f"<i>Это может занять несколько секунд</i>"
            )
            
            # Создаем агента через сервис
            self.logger.info("🎨 Creating content agent via service", 
                           bot_id=self.bot_id,
                           agent_name=agent_name,
                           instructions_length=len(instructions),
                           input_method=input_method,
                           user_id=callback.from_user.id)
            
            result = await content_agent_service.create_content_agent(
                bot_id=self.bot_id,
                agent_name=agent_name,
                instructions=instructions,
                user_id=callback.from_user.id
            )
            
            keyboards = await self._get_content_keyboards()
            
            if result['success']:
                # Успешное создание
                agent_data = result.get('agent', {})
                
                text = f"""
✅ <b>Агент создан успешно!</b>

👤 <b>Имя:</b> {agent_data.get('name', agent_name)}
📋 <b>Инструкции введены:</b> {input_method}
🤖 <b>OpenAI ID:</b> {agent_data.get('openai_agent_id', 'Не указан')[:20]}...
💾 <b>Сохранен в БД:</b> ID {agent_data.get('id', 'Unknown')}

🎯 <b>Агент готов к работе!</b>

📝 Теперь вы можете:
• Отправлять ЛЮБОЙ контент для рерайта (текстом или голосом)
• 📷 Фото, 🎥 видео, 🎬 GIF, 🎵 аудио, 📄 документы, 🎭 стикеры
• Отправлять альбомы для рерайта {'✅' if MEDIA_GROUP_AVAILABLE else '❌ (недоступно)'}
• 🔗 Использовать ссылки в постах (автоматически сохраняются)
• ✏️ Редактировать готовые посты
• 📤 Публиковать готовые посты в каналы
• 🎤 Использовать голосовые сообщения для всех действий
• Управлять настройками агента  
• Просматривать статистику использования

📎 <b>Медиа без подписи:</b> агент автоматически создаст описание!

<b>Перейти к рерайту постов?</b>
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📝 Рерайт постов", callback_data="content_rewrite")],
                    [InlineKeyboardButton(text="📊 Главное меню", callback_data="content_main")]
                ])
                
                await self._safe_edit_or_answer(callback, text, keyboard)
                
                self.logger.info("✅ Content agent created successfully with voice support", 
                               bot_id=self.bot_id,
                               agent_name=agent_name,
                               agent_id=agent_data.get('id'),
                               openai_agent_id=agent_data.get('openai_agent_id'),
                               input_method=input_method)
            else:
                # Ошибка создания
                error_message = result.get('message', 'Неизвестная ошибка')
                
                text = f"""
❌ <b>Ошибка создания агента</b>

<b>Причина:</b> {error_message}

🔧 <b>Что можно попробовать:</b>
• Проверить токеновый лимит
• Попробовать другое имя агента
• Проверить подключение к OpenAI
• Обратиться к администратору

<b>Попробовать еще раз?</b>
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="content_create_agent")],
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="content_main")]
                ])
                
                await self._safe_edit_or_answer(callback, text, keyboard)
                
                self.logger.error("❌ Content agent creation failed", 
                               bot_id=self.bot_id,
                               agent_name=agent_name,
                               error=result.get('error'),
                               message=error_message,
                               input_method=input_method)
            
            # Очищаем состояние
            await state.clear()
            
        except Exception as e:
            self.logger.error("💥 Failed to confirm agent creation", 
                            bot_id=self.bot_id,
                            error=str(e),
                            error_type=type(e).__name__,
                            exc_info=True)
            
            await self._safe_edit_or_answer(
                callback,
                f"💥 <b>Критическая ошибка создания агента</b>\n\n"
                f"<b>Ошибка:</b> {str(e)}\n\n"
                f"Обратитесь к администратору."
            )
            
            await state.clear()
