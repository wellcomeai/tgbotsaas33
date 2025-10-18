"""
Методы управления и редактирования контент-агентов.

✅ ПОЛНАЯ ФУНКЦИОНАЛЬНОСТЬ:
1. 🎤 Голосовое редактирование инструкций через OpenAI Whisper API
2. ⚙️ Управление настройками агента
3. 📝 Редактирование имени и инструкций
4. 🗑️ Удаление агентов с подтверждением
5. 📊 Отображение статистики и информации
6. 🔧 Валидация всех изменений
7. 🛡️ Обработка ошибок и edge cases
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


class AgentManagementMixin:
    """Миксин для методов управления агентами"""
    
    async def cb_manage_agent(self, callback: CallbackQuery):
        """Управление агентом"""
        self.logger.info("⚙️ Agent management accessed", 
                        user_id=callback.from_user.id,
                        bot_id=self.bot_id)
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Получаем информацию об агенте
            agent_info = await content_agent_service.get_agent_info(self.bot_id)
            
            if not agent_info:
                await callback.answer("Агент не найден", show_alert=True)
                return
            
            stats = agent_info.get('stats', {})
            
            text = f"""
⚙️ <b>Управление агентом</b>

👤 <b>Имя:</b> {agent_info['name']}
🤖 <b>OpenAI интеграция:</b> {'✅ Активна' if stats.get('has_openai_id') else '❌ Ошибка'}
📅 <b>Создан:</b> {self._format_date(agent_info.get('created_at'))}
🔄 <b>Обновлен:</b> {self._format_date(agent_info.get('updated_at'))}

📊 <b>Статистика:</b>
• Токенов использовано: {self._format_number(stats.get('tokens_used', 0))}
• Последнее использование: {self._format_date(stats.get('last_usage_at')) or 'Не использовался'}

📋 <b>Инструкции агента:</b>
<i>{self._truncate_text(agent_info['instructions'], 300)}</i>

🔧 <b>Возможности:</b>
• Альбомы: {'✅ Поддерживаются' if MEDIA_GROUP_AVAILABLE else '❌ Недоступны'}
• FSM состояния: {'✅ Доступны' if CONTENT_STATES_AVAILABLE else '❌ Недоступны'}
• 🔗 Ссылки: ✅ Автоматическое извлечение
• ✏️ Редактирование: ✅ Внесение правок
• 📤 Публикация: ✅ Отправка в каналы
• 🎤 Голосовые сообщения: ✅ Полная поддержка
• 📎 Все типы медиа: ✅ Фото, видео, GIF, аудио, документы, стикеры

<b>Выберите действие:</b>
"""
            
            keyboards = await self._get_content_keyboards()
            
            await self._safe_edit_or_answer(
                callback,
                text,
                keyboards['manage_menu']
            )
            
            self.logger.info("✅ Agent management menu displayed", 
                           bot_id=self.bot_id,
                           agent_name=agent_info['name'])
            
        except Exception as e:
            self.logger.error("💥 Failed to show agent management", 
                            bot_id=self.bot_id,
                            error=str(e))
            await callback.answer("Ошибка при загрузке управления агентом", show_alert=True)
    
    async def cb_agent_settings(self, callback: CallbackQuery):
        """Настройки агента"""
        self.logger.info("⚙️ Agent settings accessed", 
                        user_id=callback.from_user.id,
                        bot_id=self.bot_id)
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Получаем информацию об агенте
            agent_info = await content_agent_service.get_agent_info(self.bot_id)
            
            if not agent_info:
                await callback.answer("Агент не найден", show_alert=True)
                return
            
            stats = agent_info.get('stats', {})
            
            text = f"""
⚙️ <b>Настройки агента</b>

👤 <b>Текущее имя:</b> {agent_info['name']}
🔗 <b>OpenAI Agent ID:</b> <code>{agent_info.get('openai_agent_id', 'Не указан')}</code>
📅 <b>Создан:</b> {self._format_date(agent_info.get('created_at'))}
🔄 <b>Последнее изменение:</b> {self._format_date(agent_info.get('updated_at'))}

📋 <b>Текущие инструкции:</b>
<i>{self._truncate_text(agent_info['instructions'], 400)}</i>

📊 <b>Статистика использования:</b>
• Токенов потрачено: {self._format_number(stats.get('tokens_used', 0))}
• Последняя активность: {self._format_date(stats.get('last_usage_at')) or 'Не использовался'}
• OpenAI интеграция: {'✅ Активна' if stats.get('has_openai_id') else '❌ Ошибка'}

🔧 <b>Системные возможности:</b>
• Альбомы: {'✅ Поддерживаются' if MEDIA_GROUP_AVAILABLE else '❌ Недоступны'}
• FSM состояния: {'✅ Доступны' if CONTENT_STATES_AVAILABLE else '❌ Недоступны'}
• 🔗 Ссылки: ✅ Автоматическое извлечение и сохранение
• ✏️ Редактирование: ✅ Внесение правок в готовые посты
• 📤 Публикация: ✅ Прямая отправка в каналы
• 🎤 Голосовые сообщения: ✅ Полная поддержка
• 📎 Все типы медиа: ✅ Фото, видео, GIF, аудио, документы, стикеры

📎 <b>Поддерживаемые форматы:</b>
📷 Фото • 🎥 Видео • 🎬 GIF • 🎵 Аудио • 📄 Документы • 🎭 Стикеры

<b>Что можно изменить:</b>
• Имя агента (отображается в интерфейсе)
• Инструкции рерайта (влияет на стиль обработки, можно вводить голосом)

<b>Выберите что изменить:</b>
"""
            
            keyboards = await self._get_content_keyboards()
            
            await self._safe_edit_or_answer(
                callback,
                text,
                keyboards['settings_menu']
            )
            
            self.logger.info("✅ Agent settings menu displayed with voice support", 
                           bot_id=self.bot_id,
                           agent_name=agent_info['name'])
            
        except Exception as e:
            self.logger.error("💥 Failed to show agent settings", 
                            bot_id=self.bot_id,
                            error=str(e))
            await callback.answer("Ошибка при загрузке настроек агента", show_alert=True)
    
    # ===== AGENT EDITING =====
    
    async def cb_edit_agent_name(self, callback: CallbackQuery, state: FSMContext):
        """Начало редактирования имени агента"""
        self.logger.info("📝 Edit agent name started", 
                        user_id=callback.from_user.id,
                        bot_id=self.bot_id)
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Получаем текущую информацию об агенте
            agent_info = await content_agent_service.get_agent_info(self.bot_id)
            
            if not agent_info:
                await callback.answer("Агент не найден", show_alert=True)
                return
            
            text = f"""
📝 <b>Изменение имени агента</b>

👤 <b>Текущее имя:</b> {agent_info['name']}

Введите новое имя для агента. Имя должно быть:
• От 3 до 100 символов
• Понятным и описательным
• Уникальным для ваших задач

📝 <b>Примеры хороших имен:</b>
• "Креативный копирайтер"
• "Деловой редактор"
• "SMM помощник Pro"
• "Дружелюбный рерайтер"

⚠️ <b>Внимание:</b> Имя изменится только в интерфейсе бота. OpenAI агент останется тем же, инструкции не изменятся.

<b>Введите новое имя агента:</b>
"""
            
            keyboards = await self._get_content_keyboards()
            
            await self._safe_edit_or_answer(
                callback,
                text,
                keyboards['back_to_settings']
            )
            
            # Сохраняем текущие данные в состоянии для сравнения
            await state.update_data(
                current_agent_name=agent_info['name'],
                agent_id=agent_info.get('id')
            )
            
            if CONTENT_STATES_AVAILABLE:
                await state.set_state(ContentStates.editing_agent_name)
            
            self.logger.info("✅ Agent name editing flow started", 
                           bot_id=self.bot_id,
                           current_name=agent_info['name'],
                           user_id=callback.from_user.id)
            
        except Exception as e:
            self.logger.error("💥 Failed to start agent name editing", 
                            bot_id=self.bot_id,
                            error=str(e))
            await callback.answer("Ошибка при запуске редактирования имени", show_alert=True)
    
    async def handle_edit_agent_name_input(self, message: Message, state: FSMContext):
        """Обработка нового имени агента"""
        self.logger.info("📝 Edit agent name input received", 
                        user_id=message.from_user.id,
                        bot_id=self.bot_id)
        
        if not self._is_owner(message.from_user.id):
            await message.answer("❌ Доступ запрещен")
            return
        
        try:
            new_name = message.text.strip()
            
            # Валидация нового имени
            if not new_name:
                await message.answer("❌ Имя не может быть пустым. Попробуйте еще раз:")
                return
            
            if len(new_name) < 3:
                await message.answer("❌ Имя слишком короткое (минимум 3 символа). Попробуйте еще раз:")
                return
            
            if len(new_name) > 100:
                await message.answer("❌ Имя слишком длинное (максимум 100 символов). Попробуйте еще раз:")
                return
            
            # Получаем данные из состояния
            data = await state.get_data()
            current_name = data.get('current_agent_name')
            
            if not current_name:
                await message.answer("❌ Ошибка: потеряны данные агента. Попробуйте заново:")
                await state.clear()
                return
            
            # Проверяем, отличается ли новое имя от текущего
            if new_name == current_name:
                await message.answer("❌ Новое имя совпадает с текущим. Введите другое имя:")
                return
            
            # Показываем процесс изменения
            processing_msg = await message.answer(
                f"⏳ <b>Изменение имени агента...</b>\n\n"
                f"📝 Старое имя: {current_name}\n"
                f"✨ Новое имя: {new_name}\n\n"
                f"💾 Обновление базы данных..."
            )
            
            # Обновляем имя через сервис
            result = await content_agent_service.update_agent(
                bot_id=self.bot_id,
                agent_name=new_name
            )
            
            # Удаляем сообщение о процессе
            try:
                await processing_msg.delete()
            except:
                pass
            
            if result['success']:
                # Успешное обновление
                text = f"""
✅ <b>Имя агента изменено!</b>

📝 <b>Старое имя:</b> {current_name}
✨ <b>Новое имя:</b> {new_name}
🔄 <b>Изменено:</b> {self._format_date()}

🎯 <b>Что изменилось:</b>
• Имя в интерфейсе бота обновлено
• Статистика сохранена под новым именем
• OpenAI агент остался тем же

<b>Что дальше?</b>
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📋 Изменить инструкции", callback_data="content_edit_instructions")],
                    [InlineKeyboardButton(text="⚙️ К настройкам", callback_data="content_settings")],
                    [InlineKeyboardButton(text="📊 Главное меню", callback_data="content_main")]
                ])
                
                await message.answer(text, reply_markup=keyboard)
                
                self.logger.info("✅ Agent name updated successfully", 
                               bot_id=self.bot_id,
                               old_name=current_name,
                               new_name=new_name)
            else:
                # Ошибка обновления
                error_message = result.get('message', 'Неизвестная ошибка')
                
                text = f"""
❌ <b>Ошибка изменения имени</b>

<b>Причина:</b> {error_message}

🔧 <b>Что можно попробовать:</b>
• Попробовать другое имя
• Проверить подключение к базе данных
• Попробовать позже
• Обратиться к администратору

<b>Текущее имя остается:</b> {current_name}
"""
                
                keyboards = await self._get_content_keyboards()
                
                await message.answer(
                    text,
                    reply_markup=keyboards['back_to_settings']
                )
                
                self.logger.error("❌ Agent name update failed", 
                               bot_id=self.bot_id,
                               old_name=current_name,
                               new_name=new_name,
                               error=result.get('error'),
                               message=error_message)
            
            # Очищаем состояние
            await state.clear()
            
        except Exception as e:
            self.logger.error("💥 Failed to handle agent name edit input", 
                            bot_id=self.bot_id,
                            error=str(e))
            await message.answer("❌ Ошибка при обработке нового имени. Попробуйте еще раз:")
    
    async def cb_edit_agent_instructions(self, callback: CallbackQuery, state: FSMContext):
        """Начало редактирования инструкций агента"""
        self.logger.info("📋 Edit agent instructions started", 
                        user_id=callback.from_user.id,
                        bot_id=self.bot_id)
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Получаем текущую информацию об агенте
            agent_info = await content_agent_service.get_agent_info(self.bot_id)
            
            if not agent_info:
                await callback.answer("Агент не найден", show_alert=True)
                return
            
            text = f"""
📋 <b>Изменение инструкций агента</b>

👤 <b>Агент:</b> {agent_info['name']}

📝 <b>Текущие инструкции:</b>
<i>{agent_info['instructions']}</i>

Введите новые инструкции для рерайта. Инструкции должны быть:
• От 10 до 2000 символов
• Четкими и понятными для ИИ
• Описывать желаемый стиль обработки

🎤 <b>НОВОЕ: Вы можете записать новые инструкции ГОЛОСОМ!</b>

📋 <b>Примеры хороших инструкций:</b>

<b>Для соцсетей:</b>
"Переписывай в легком, дружелюбном тоне. Добавляй эмоджи, делай текст более живым и привлекательным для аудитории соцсетей."

<b>Для бизнеса:</b>
"Преобразуй в профессиональный деловой стиль. Структурируй информацию, убирай лишние эмоции, фокусируйся на фактах и выгодах."

⚠️ <b>ВАЖНО:</b> Изменение инструкций повлияет на все будущие рерайты. OpenAI агент будет обновлен с новыми инструкциями.

<b>Введите новые инструкции текстом или 🎤 запишите голосом:</b>
"""
            
            keyboards = await self._get_content_keyboards()
            
            await self._safe_edit_or_answer(
                callback,
                text,
                keyboards['back_to_settings']
            )
            
            # Сохраняем текущие данные в состоянии
            await state.update_data(
                current_instructions=agent_info['instructions'],
                agent_id=agent_info.get('id'),
                agent_name=agent_info['name']
            )
            
            if CONTENT_STATES_AVAILABLE:
                await state.set_state(ContentStates.editing_agent_instructions)
            
            self.logger.info("✅ Agent instructions editing flow started with voice support", 
                           bot_id=self.bot_id,
                           agent_name=agent_info['name'],
                           current_instructions_length=len(agent_info['instructions']),
                           user_id=callback.from_user.id)
            
        except Exception as e:
            self.logger.error("💥 Failed to start agent instructions editing", 
                            bot_id=self.bot_id,
                            error=str(e))
            await callback.answer("Ошибка при запуске редактирования инструкций", show_alert=True)
    
    async def handle_edit_agent_instructions_input(self, message: Message, state: FSMContext):
        """🎤 ОБНОВЛЕНО: Обработка новых инструкций агента (текст или голос)"""
        self.logger.info("📋 Edit agent instructions input received", 
                        user_id=message.from_user.id,
                        bot_id=self.bot_id,
                        has_text=bool(message.text),
                        has_voice=bool(message.voice),
                        instructions_length=len(message.text or "") if message.text else 0)
        
        if not self._is_owner(message.from_user.id):
            await message.answer("❌ Доступ запрещен")
            return
        
        try:
            new_instructions = None
            
            # 🎤 ОБРАБОТКА ГОЛОСОВЫХ СООБЩЕНИЙ
            if message.voice:
                self.logger.info("🎤 Voice instructions for editing received, transcribing...", 
                                user_id=message.from_user.id,
                                bot_id=self.bot_id)
                
                await message.bot.send_chat_action(message.chat.id, "typing")
                
                new_instructions = await self._transcribe_voice_message(message.voice)
                
                if not new_instructions:
                    await message.answer("❌ Не удалось распознать голосовое сообщение. Попробуйте еще раз или напишите текстом.")
                    return
                
                self.logger.info("✅ Voice instructions for editing transcribed successfully", 
                               user_id=message.from_user.id,
                               bot_id=self.bot_id,
                               transcribed_length=len(new_instructions))
                
                # Показываем что распознали
                await message.answer(f"🎤 <b>Распознано:</b>\n<i>{new_instructions[:200]}{'...' if len(new_instructions) > 200 else ''}</i>\n\n⏳ Проверяю инструкции...")
                
            elif message.text:
                new_instructions = message.text.strip()
            else:
                await message.answer("❌ Пожалуйста, отправьте текстовое или голосовое сообщение.")
                return
            
            # Валидация новых инструкций
            if not new_instructions:
                await message.answer("❌ Инструкции не могут быть пустыми. Попробуйте еще раз:")
                return
            
            if len(new_instructions) < 10:
                await message.answer("❌ Инструкции слишком короткие (минимум 10 символов). Опишите подробнее:")
                return
            
            if len(new_instructions) > 2000:
                await message.answer("❌ Инструкции слишком длинные (максимум 2000 символов). Сократите:")
                return
            
            # Получаем данные из состояния
            data = await state.get_data()
            current_instructions = data.get('current_instructions')
            agent_name = data.get('agent_name')
            
            if not current_instructions or not agent_name:
                await message.answer("❌ Ошибка: потеряны данные агента. Попробуйте заново:")
                await state.clear()
                return
            
            # Проверяем, отличаются ли новые инструкции от текущих
            if new_instructions == current_instructions:
                await message.answer("❌ Новые инструкции совпадают с текущими. Введите другие инструкции:")
                return
            
            # Показываем предпросмотр изменений
            input_method = "🎤 голосом" if message.voice else "📝 текстом"
            
            text = f"""
📋 <b>Подтверждение изменения инструкций</b>

👤 <b>Агент:</b> {agent_name}

📝 <b>Старые инструкции:</b>
<i>{self._truncate_text(current_instructions, 300)}</i>

✨ <b>Новые инструкции (введены {input_method}):</b>
<i>{self._truncate_text(new_instructions, 300)}</i>

📊 <b>Изменения:</b>
• Длина: {len(current_instructions)} → {len(new_instructions)} символов
• Изменение: {'+' if len(new_instructions) > len(current_instructions) else ''}{len(new_instructions) - len(current_instructions)} символов
• Способ ввода: {input_method}

⚠️ <b>ВНИМАНИЕ:</b>
• OpenAI агент будет обновлен новыми инструкциями
• Это повлияет на все будущие рерайты
• Изменение нельзя отменить (но можно изменить заново)

<b>Применить новые инструкции?</b>
"""
            
            # Сохраняем новые инструкции в состоянии
            await state.update_data(
                current_instructions=current_instructions,
                new_instructions=new_instructions,
                agent_name=agent_name,
                input_method=input_method
            )
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Применить изменения", callback_data="content_confirm_instructions_update")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="content_settings")]
            ])
            
            await message.answer(text, reply_markup=keyboard)
            
            self.logger.info("✅ Agent instructions change preview shown with voice support", 
                           bot_id=self.bot_id,
                           agent_name=agent_name,
                           old_length=len(current_instructions),
                           new_length=len(new_instructions),
                           input_method=input_method)
            
        except Exception as e:
            self.logger.error("💥 Failed to handle agent instructions edit input with voice", 
                            bot_id=self.bot_id,
                            error=str(e))
            await message.answer("❌ Ошибка при обработке новых инструкций. Попробуйте еще раз:")
    
    async def cb_confirm_instructions_update(self, callback: CallbackQuery, state: FSMContext):
        """✅ Подтверждение обновления инструкций агента"""
        self.logger.info("✅ Instructions update confirmation received", 
                        user_id=callback.from_user.id,
                        bot_id=self.bot_id)
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Получаем данные из состояния
            data = await state.get_data()
            current_instructions = data.get('current_instructions')
            new_instructions = data.get('new_instructions')
            agent_name = data.get('agent_name')
            input_method = data.get('input_method', '📝 текстом')
            
            if not all([current_instructions, new_instructions, agent_name]):
                await callback.answer("Ошибка: данные потеряны", show_alert=True)
                await state.clear()
                return
            
            # Показываем процесс обновления
            await self._safe_edit_or_answer(
                callback,
                f"⏳ <b>Обновление инструкций агента '{agent_name}'...</b>\n\n"
                f"📋 Новые инструкции введены {input_method}\n"
                f"🤖 Обновление OpenAI агента...\n"
                f"💾 Сохранение в базу данных...\n"
                f"🔄 Синхронизация изменений...\n\n"
                f"<i>Это может занять несколько секунд</i>"
            )
            
            # Обновляем инструкции через сервис
            result = await content_agent_service.update_agent(
                bot_id=self.bot_id,
                instructions=new_instructions
            )
            
            if result['success']:
                # Успешное обновление
                text = f"""
✅ <b>Инструкции агента обновлены!</b>

👤 <b>Агент:</b> {agent_name}
🔄 <b>Изменено:</b> {self._format_date()}
📊 <b>Изменение длины:</b> {'+' if len(new_instructions) > len(current_instructions) else ''}{len(new_instructions) - len(current_instructions)} символов
📋 <b>Способ ввода:</b> {input_method}

📝 <b>Новые инструкции:</b>
<i>{self._truncate_text(new_instructions, 400)}</i>

🎯 <b>Что изменилось:</b>
• OpenAI агент обновлен новыми инструкциями
• Все будущие рерайты будут использовать новый стиль
• Изменения вступили в силу немедленно
• Голосовой ввод работает для всех операций

<b>Протестировать новые инструкции?</b>
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📝 Тест рерайта", callback_data="content_rewrite")],
                    [InlineKeyboardButton(text="⚙️ К настройкам", callback_data="content_settings")],
                    [InlineKeyboardButton(text="📊 Главное меню", callback_data="content_main")]
                ])
                
                await self._safe_edit_or_answer(callback, text, keyboard)
                
                self.logger.info("✅ Agent instructions updated successfully with voice support", 
                               bot_id=self.bot_id,
                               agent_name=agent_name,
                               old_length=len(current_instructions),
                               new_length=len(new_instructions),
                               input_method=input_method)
            else:
                # Ошибка обновления
                error_message = result.get('message', 'Неизвестная ошибка')
                
                text = f"""
❌ <b>Ошибка обновления инструкций</b>

<b>Причина:</b> {error_message}

🔧 <b>Что можно попробовать:</b>
• Попробовать еще раз
• Проверить подключение к OpenAI
• Попробовать другие инструкции
• Обратиться к администратору

<b>Текущие инструкции остаются без изменений.</b>

<b>Попробовать снова?</b>
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="content_edit_instructions")],
                    [InlineKeyboardButton(text="⚙️ К настройкам", callback_data="content_settings")],
                    [InlineKeyboardButton(text="📊 Главное меню", callback_data="content_main")]
                ])
                
                await self._safe_edit_or_answer(callback, text, keyboard)
                
                self.logger.error("❌ Agent instructions update failed", 
                               bot_id=self.bot_id,
                               agent_name=agent_name,
                               error=result.get('error'),
                               message=error_message)
            
            # Очищаем состояние
            await state.clear()
            
        except Exception as e:
            self.logger.error("💥 Failed to confirm instructions update", 
                            bot_id=self.bot_id,
                            error=str(e),
                            error_type=type(e).__name__,
                            exc_info=True)
            
            await self._safe_edit_or_answer(
                callback,
                f"💥 <b>Критическая ошибка обновления инструкций</b>\n\n"
                f"<b>Ошибка:</b> {str(e)}\n\n"
                f"Обратитесь к администратору."
            )
            
            await state.clear()
    
    # ===== AGENT DELETION =====
    
    async def cb_delete_agent(self, callback: CallbackQuery):
        """Подтверждение удаления агента"""
        self.logger.info("🗑️ Delete agent confirmation requested", 
                        user_id=callback.from_user.id,
                        bot_id=self.bot_id)
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            agent_info = await content_agent_service.get_agent_info(self.bot_id)
            
            if not agent_info:
                await callback.answer("Агент не найден", show_alert=True)
                return
            
            stats = agent_info.get('stats', {})
            
            text = f"""
🗑️ <b>Удаление агента</b>

👤 <b>Агент:</b> {agent_info['name']}
💰 <b>Токенов использовано:</b> {self._format_number(stats.get('tokens_used', 0))}

⚠️ <b>ВНИМАНИЕ!</b>
При удалении агента:
• Агент будет удален из OpenAI
• Данные в базе будут помечены как неактивные
• Статистика использования сохранится
• Рерайт постов станет недоступен
• Обработка всех типов медиа станет недоступна
• 📷 Фото, 🎥 видео, 🎬 GIF, 🎵 аудио, 📄 документы, 🎭 стикеры
• Обработка альбомов станет недоступна
• Редактирование постов станет недоступно
• Публикация в каналы станет недоступна
• Голосовой ввод станет недоступен

❓ <b>Вы уверены что хотите удалить агента?</b>

Это действие нельзя отменить.
"""
            
            keyboards = await self._get_content_keyboards()
            
            await self._safe_edit_or_answer(
                callback,
                text,
                keyboards['delete_confirmation']
            )
            
            self.logger.info("🗑️ Agent deletion confirmation shown", 
                           bot_id=self.bot_id,
                           agent_name=agent_info['name'])
            
        except Exception as e:
            self.logger.error("💥 Failed to show agent deletion confirmation", 
                            bot_id=self.bot_id,
                            error=str(e))
            await callback.answer("Ошибка при подготовке удаления", show_alert=True)
    
    async def cb_confirm_delete_agent(self, callback: CallbackQuery):
        """✅ Окончательное подтверждение удаления агента"""
        self.logger.info("🗑️ Agent deletion confirmed", 
                        user_id=callback.from_user.id,
                        bot_id=self.bot_id)
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Показываем процесс удаления
            await self._safe_edit_or_answer(
                callback,
                "⏳ <b>Удаление агента...</b>\n\n"
                "🤖 Удаление из OpenAI...\n"
                "💾 Обновление базы данных...\n\n"
                "<i>Это может занять несколько секунд</i>"
            )
            
            # Удаляем агента через сервис
            result = await content_agent_service.delete_agent(self.bot_id, force=True)
            
            if result['success']:
                deleted_agent = result.get('deleted_agent', {})
                
                text = f"""
✅ <b>Агент удален успешно</b>

👤 <b>Удаленный агент:</b> {deleted_agent.get('name', 'Неизвестен')}
🤖 <b>OpenAI очищен:</b> {'✅' if deleted_agent.get('had_openai_integration') else 'Не требовался'}

📊 <b>Что сохранилось:</b>
• Статистика использования токенов
• Записи в логах системы
• История активности бота

🔧 <b>Что стало недоступно:</b>
• Рерайт постов
• Обработка всех типов медиа (📷🎥🎬🎵📄🎭)
• Альбомы и медиагруппы
• Голосовой ввод
• Редактирование постов
• Публикация в каналы

💡 <b>Вы можете создать нового агента в любое время.</b>

<b>Создать нового агента?</b>
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✨ Создать нового агента", callback_data="content_create_agent")],
                    [InlineKeyboardButton(text="📊 Главное меню", callback_data="content_main")]
                ])
                
                await self._safe_edit_or_answer(callback, text, keyboard)
                
                self.logger.info("✅ Content agent deleted successfully", 
                               bot_id=self.bot_id,
                               deleted_agent_name=deleted_agent.get('name'))
                               
            else:
                error_message = result.get('message', 'Неизвестная ошибка')
                
                text = f"""
❌ <b>Ошибка удаления агента</b>

<b>Причина:</b> {error_message}

🔧 <b>Что можно попробовать:</b>
• Попробовать еще раз
• Проверить подключение к OpenAI
• Обратиться к администратору

Агент может быть частично удален. Проверьте главное меню.
"""
                
                keyboards = await self._get_content_keyboards()
                
                await self._safe_edit_or_answer(
                    callback,
                    text,
                    keyboards['back_to_main']
                )
                
                self.logger.error("❌ Content agent deletion failed", 
                               bot_id=self.bot_id,
                               error=result.get('error'),
                               message=error_message)
            
        except Exception as e:
            self.logger.error("💥 Failed to confirm agent deletion", 
                            bot_id=self.bot_id,
                            error=str(e),
                            error_type=type(e).__name__,
                            exc_info=True)
            
            await self._safe_edit_or_answer(
                callback,
                f"💥 <b>Критическая ошибка удаления</b>\n\n"
                f"<b>Ошибка:</b> {str(e)}\n\n"
                f"Обратитесь к администратору."
            )
