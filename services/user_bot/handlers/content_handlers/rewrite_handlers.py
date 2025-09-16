"""
Методы рерайта постов для контент-агентов.

✅ ПОЛНАЯ ФУНКЦИОНАЛЬНОСТЬ:
1. 🎤 Поддержка голосовых сообщений через OpenAI Whisper API
2. 📎 Обработка всех типов медиа (фото, видео, GIF, аудио, документы, стикеры)
3. 🔗 Извлечение и сохранение ссылок
4. ✏️ Редактирование готовых постов с правками
5. 📊 Детальное логирование процесса рерайта
6. 🛡️ Обработка ошибок и валидация
7. ✨ Упрощенный интерфейс для пользователей
8. 🤖 Интеграция с OpenAI для обработки контента
"""

from typing import Dict
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.utils.media_group import MediaGroupBuilder
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


class RewriteHandlersMixin:
    """Миксин для методов рерайта постов"""
    
    async def cb_rewrite_post(self, callback: CallbackQuery, state: FSMContext):
        """Начало режима рерайта постов"""
        self.logger.info("📝 Rewrite mode requested", 
                        user_id=callback.from_user.id,
                        bot_id=self.bot_id)
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Проверяем наличие агента
            agent_info = await content_agent_service.get_agent_info(self.bot_id)
            
            if not agent_info:
                await callback.answer("Агент не найден. Создайте агента сначала.", show_alert=True)
                return
            
            stats = agent_info.get('stats', {})
            
            if not stats.get('has_openai_id'):
                await callback.answer("Ошибка OpenAI интеграции. Пересоздайте агента.", show_alert=True)
                return
            
            text = f"""
📝 <b>Рерайт постов</b>

👤 <b>Активный агент:</b> {agent_info['name']}
💰 <b>Токенов использовано:</b> {self._format_number(stats.get('tokens_used', 0))}

📋 <b>Инструкции агента:</b>
<i>{self._truncate_text(agent_info['instructions'], 200)}</i>

📎 <b>Поддерживаемый контент:</b>
• 📝 Только текст
• 📷 Фото (с подписью или без)
• 🎥 Видео (с подписью или без) 
• 🎬 GIF/анимации (с подписью или без)
• 🎵 Аудио файлы (с подписью или без)
• 📄 Документы (с подписью или без)
• 🎭 Стикеры (с подписью или без)
• ✨ Альбомы (медиагруппы) {'✅' if MEDIA_GROUP_AVAILABLE else '❌ недоступно'}
• 🔗 Ссылки (автоматически извлекаются и сохраняются)
• 🎤 Голосовые сообщения (преобразуются в текст)

🎯 <b>Как использовать:</b>
1. Пришлите ЛЮБОЙ контент для рерайта:
   • Текст 
   • 📷 Фото с подписью ИЛИ без (агент опишет картинку)
   • 🎥 Видео с подписью ИЛИ без  
   • 📄 Любые файлы с подписью ИЛИ без
   • 🎤 Голосовое сообщение
2. ✨ Отправьте альбом с подписью для группового рерайта
3. 🔗 Используйте ссылки - они автоматически сохранятся
4. Агент переписывает/описывает контент согласно инструкциям
5. Получаете результат с кнопками ✏️ правки и 📤 публикации

⚠️ <b>Внимание:</b>
• Каждый рерайт тратит токены из общего лимита
• Для текста: минимальная длина 3 символа
• Для медиа БЕЗ подписи: агент создаст описание
• Медиа файлы остаются без изменений (сохраняется file_id)
• Альбомы обрабатываются как единое целое
• Ссылки извлекаются и передаются агенту для сохранения
• Голосовые сообщения транскрибируются через Whisper API
• После рерайта доступны правки и публикация

<b>Пришлите ЛЮБОЙ контент для рерайта:</b>
"""
            
            keyboards = await self._get_content_keyboards()
            
            # 🔧 ИСПРАВЛЕНИЕ: Используем answer вместо edit_text для избежания ошибки "no text to edit"
            await callback.message.answer(
                text,
                reply_markup=keyboards['rewrite_mode']
            )
            
            # Устанавливаем состояние ожидания поста
            if CONTENT_STATES_AVAILABLE:
                await state.set_state(ContentStates.waiting_for_rewrite_post)
            
            self.logger.info("✅ Rewrite mode activated successfully with voice support", 
                           bot_id=self.bot_id,
                           agent_name=agent_info['name'],
                           user_id=callback.from_user.id)
            
        except Exception as e:
            self.logger.error("💥 Failed to start rewrite mode", 
                            bot_id=self.bot_id,
                            error=str(e))
            await callback.answer("Ошибка при запуске режима рерайта", show_alert=True)
    
    async def handle_rewrite_post_input(self, message: Message, state: FSMContext):
        """🎤 ИСПРАВЛЕНО: Обработка поста для рерайта с полной поддержкой медиа и голосовых сообщений"""
        self.logger.info("📝 Rewrite post input received", 
                        user_id=message.from_user.id,
                        bot_id=self.bot_id,
                        message_id=message.message_id,
                        has_photo=bool(message.photo),
                        has_video=bool(message.video),
                        has_text=bool(message.text),
                        has_caption=bool(message.caption),
                        has_voice=bool(message.voice))
        
        if not self._is_owner(message.from_user.id):
            await message.answer("❌ Доступ запрещен")
            return
        
        try:
            # Определяем тип контента
            if message.voice:
                content_type_str = "🎤 голосовое сообщение"
            elif message.photo:
                content_type_str = "📷 фото"
            elif message.video:
                content_type_str = "🎥 видео"
            elif message.animation:
                content_type_str = "🎬 GIF/анимация"
            elif message.audio:
                content_type_str = "🎵 аудио"
            elif message.document:
                content_type_str = "📄 документ"
            elif message.sticker:
                content_type_str = "🎭 стикер"
            elif message.text:
                content_type_str = "📝 текст"
            else:
                content_type_str = "неизвестный тип контента"
            
            # Показываем процесс обработки
            processing_msg = await message.answer(
                f"⏳ <b>Обрабатываю {content_type_str}...</b>\n\n"
                f"🔍 Анализ контента...\n"
                f"🔗 Извлечение ссылок...\n"
                f"🤖 Отправка агенту...\n\n"
                f"<i>Это может занять 5-15 секунд</i>"
            )
            
            # Выполняем рерайт через сервис
            result = await content_agent_service.rewrite_post(
                bot_id=self.bot_id,
                message=message,
                user_id=message.from_user.id
            )
            
            # Удаляем сообщение о процессе
            try:
                await processing_msg.delete()
            except:
                pass
            
            if result['success']:
                # Успешный рерайт
                await self._send_rewrite_result(message, result)
                
                input_type = "voice" if message.voice else content_type_str
                
                self.logger.info("✅ Post rewritten successfully with complete media support", 
                               bot_id=self.bot_id,
                               input_type=input_type,
                               original_length=len(result['content']['original_text']),
                               rewritten_length=len(result['content']['rewritten_text']),
                               tokens_used=result['tokens']['total_tokens'],
                               has_media=result['has_media'],
                               has_links=result.get('has_links', False))
            else:
                # Ошибка рерайта
                await self._send_rewrite_error(message, result)
                
                self.logger.error("❌ Post rewrite failed", 
                               bot_id=self.bot_id,
                               input_type=content_type_str,
                               error=result.get('error'),
                               message=result.get('message'))
            
        except Exception as e:
            self.logger.error("💥 Failed to handle rewrite post input with complete media support", 
                            bot_id=self.bot_id,
                            message_id=message.message_id,
                            error=str(e),
                            error_type=type(e).__name__,
                            exc_info=True)
            
            await message.answer(
                f"💥 <b>Ошибка обработки {content_type_str}</b>\n\n"
                f"<b>Ошибка:</b> {str(e)}\n\n"
                f"Попробуйте еще раз или обратитесь к администратору."
            )
    
    async def handle_edit_instructions_input(self, message: Message, state: FSMContext):
        """🎤 ОБНОВЛЕНО: Обработка инструкций для правок (текст или голос)"""
        if not self._is_owner(message.from_user.id):
            await message.answer("❌ Доступ запрещен")
            return
        
        try:
            edit_instructions = None
            
            # 🎤 ОБРАБОТКА ГОЛОСОВЫХ СООБЩЕНИЙ
            if message.voice:
                self.logger.info("🎤 Voice edit instructions received, transcribing...", 
                                user_id=message.from_user.id,
                                bot_id=self.bot_id)
                
                await message.bot.send_chat_action(message.chat.id, "typing")
                
                edit_instructions = await self._transcribe_voice_message(message.voice)
                
                if not edit_instructions:
                    await message.answer("❌ Не удалось распознать голосовое сообщение. Попробуйте еще раз или напишите текстом.")
                    return
                
                self.logger.info("✅ Voice edit instructions transcribed successfully", 
                               user_id=message.from_user.id,
                               bot_id=self.bot_id,
                               transcribed_length=len(edit_instructions))
                
                # Показываем что распознали
                await message.answer(f"🎤 <b>Распознанные правки:</b>\n<i>{edit_instructions[:200]}{'...' if len(edit_instructions) > 200 else ''}</i>\n\n⏳ Применяю правки...")
                
            elif message.text:
                edit_instructions = message.text.strip()
            else:
                await message.answer("❌ Пожалуйста, отправьте текстовое или голосовое сообщение с инструкциями для правок.")
                return
            
            if not edit_instructions or len(edit_instructions) < 5:
                await message.answer("❌ Инструкции для правок слишком короткие")
                return
            
            # Получаем последний рерайт
            last_rewrite = await content_agent_service.content_manager.get_last_rewrite(self.bot_id)
            
            if not last_rewrite:
                await message.answer("❌ Нет данных для редактирования")
                return
            
            # Показываем процесс только если не голос (для голоса уже показали выше)
            if not message.voice:
                processing_msg = await message.answer("⏳ Применяю правки...")
            
            # Формируем новый промпт для правок
            input_method = "голосом" if message.voice else "текстом"
            
            edit_prompt = f"""
Внеси следующие правки в текст (правки были введены {input_method}):

ПРАВКИ: {edit_instructions}

ИСХОДНЫЙ ТЕКСТ:
{last_rewrite['content']['rewritten_text']}

Примени только указанные правки, сохрани остальное содержание.
"""
            
            # Выполняем рерайт с правками
            edit_result = await content_agent_service.content_manager.process_content_rewrite(
                bot_id=self.bot_id,
                original_text=edit_prompt,
                media_info=last_rewrite.get('media_info'),
                links_info=last_rewrite.get('links_info'),
                user_id=message.from_user.id
            )
            
            try:
                if not message.voice:  # Для голоса не создавали processing_msg
                    await processing_msg.delete()
            except:
                pass
            
            if edit_result and edit_result.get('success'):
                # Обновляем сохраненный рерайт
                await content_agent_service.content_manager.save_rewrite_result(
                    self.bot_id, edit_result
                )
                
                # Отправляем результат с кнопками
                keyboards = await self._get_content_keyboards()
                
                # Правильная обработка media_info
                media_info = edit_result.get('media_info') or edit_result.get('media')
                
                if media_info:
                    await self._send_media_with_text(
                        message,
                        edit_result['content']['rewritten_text'],
                        media_info,
                        keyboards['post_actions']
                    )
                else:
                    await message.answer(
                        edit_result['content']['rewritten_text'],
                        reply_markup=keyboards['post_actions']
                    )
                
                self.logger.info("✅ Edit instructions applied successfully", 
                               bot_id=self.bot_id,
                               input_method=input_method,
                               instructions_length=len(edit_instructions))
            else:
                await message.answer("❌ Ошибка применения правок")
            
            await state.clear()
            
        except Exception as e:
            self.logger.error("💥 Error processing edit instructions with voice support", error=str(e))
            await message.answer("Ошибка обработки правок")
    
    async def cb_exit_rewrite_mode(self, callback: CallbackQuery, state: FSMContext):
        """✅ Выход из режима рерайта"""
        self.logger.info("🚪 Exit rewrite mode requested", 
                        user_id=callback.from_user.id,
                        bot_id=self.bot_id)
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            await state.clear()
            
            text = f"""
🚪 <b>Режим рерайта завершен</b>

Спасибо за использование контент-агента с поддержкой голосовых сообщений!

📊 <b>Что вы можете сделать:</b>
• Посмотреть статистику использования
• Изменить настройки агента (голосом или текстом)
• Начать новую сессию рерайта
• Вернуться в главное меню админки

🎤 <b>Напоминание:</b> Все функции поддерживают голосовой ввод!

<b>Куда перейти?</b>
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📝 Новая сессия рерайта", callback_data="content_rewrite")],
                [InlineKeyboardButton(text="⚙️ Управление агентом", callback_data="content_manage")],
                [InlineKeyboardButton(text="📊 Контент-меню", callback_data="content_main")],
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_main")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
            self.logger.info("✅ Rewrite mode exited successfully with voice support reminder", 
                           bot_id=self.bot_id,
                           user_id=callback.from_user.id)
            
        except Exception as e:
            self.logger.error("💥 Failed to exit rewrite mode", 
                            bot_id=self.bot_id,
                            error=str(e))
            await callback.answer("Ошибка при выходе из режима рерайта", show_alert=True)
    
    # ===== РЕЗУЛЬТАТЫ РЕРАЙТА =====
    
    async def _send_rewrite_result(self, original_message: Message, result: Dict):
        """ИЗМЕНЕНО: Добавить кнопки после рерайта"""
        try:
            content = result['content']
            media_info = result.get('media')
            
            # Сохраняем результат рерайта
            save_success = await content_agent_service.content_manager.save_rewrite_result(
                self.bot_id, result
            )
            
            # ✨ УПРОЩЕНО: Отправляем только переписанный текст
            rewritten_text = content['rewritten_text']
            
            # Получаем правильные кнопки
            keyboards = await self._get_content_keyboards()
            post_actions_keyboard = keyboards.get('post_actions', keyboards['rewrite_mode'])
            
            # Отправляем результат с медиа или без
            if media_info:
                await self._send_media_with_text(
                    original_message,
                    rewritten_text,  # ✨ Только текст, без технической информации
                    media_info,
                    post_actions_keyboard  # Новые кнопки
                )
            else:
                await original_message.answer(
                    rewritten_text,  # ✨ Только текст, без технической информации
                    reply_markup=post_actions_keyboard  # Новые кнопки
                )
            
            # Логируем техническую информацию, но не показываем пользователю
            tokens = result['tokens']
            agent_info = result['agent']
            
            self.logger.info("✅ Clean rewrite result sent with action buttons and voice support", 
                           bot_id=self.bot_id,
                           agent_name=agent_info['name'],
                           has_media=bool(media_info),
                           tokens_used=tokens['total_tokens'],
                           original_length=len(content['original_text']),
                           rewritten_length=len(content['rewritten_text']))
            
        except Exception as e:
            self.logger.error("💥 Failed to send clean rewrite result", 
                            bot_id=self.bot_id,
                            error=str(e))
            await original_message.answer("Ошибка при отправке результата рерайта")
    
    async def _send_rewrite_error(self, original_message: Message, result: Dict):
        """Отправка ошибки рерайта с детализацией"""
        try:
            error_type = result.get('error', 'unknown')
            error_message = result.get('message', 'Неизвестная ошибка')
            
            # Формируем текст ошибки в зависимости от типа
            if error_type == 'no_content_agent':
                text = """
❌ <b>Агент не найден</b>

Контент-агент не настроен. Создайте агента в настройках перед использованием рерайта.
"""
            elif error_type == 'no_text':
                text = """
❌ <b>Контент не найден</b>

Пришлите любой контент для рерайта:
• 📝 Текстовое сообщение
• 📷 Фото (с подписью или без - агент создаст описание)
• 🎥 Видео (с подписью или без)
• 🎬 GIF/анимацию (с подписью или без)  
• 🎵 Аудио файл (с подписью или без)
• 📄 Документ (с подписью или без)
• 🎭 Стикер (с подписью или без)
• 🎤 Голосовое сообщение
• ✨ Альбом с подписью

<b>Агент может работать с любым контентом!</b>
"""
            elif error_type == 'text_too_short':
                text = """
❌ <b>Текст слишком короткий</b>

Минимальная длина текста для рерайта: 3 символа.
Пришлите более содержательный текст или голосовое сообщение.
"""
            elif error_type == 'token_limit_exceeded':
                tokens_info = result.get('tokens_used', 0)
                tokens_limit = result.get('tokens_limit', 0)
                
                text = f"""
🚫 <b>Лимит токенов исчерпан</b>

Использовано: {self._format_number(tokens_info)} / {self._format_number(tokens_limit)}

Для продолжения работы:
• Обратитесь к администратору для увеличения лимита
• Используйте более короткие тексты или голосовые сообщения
• Дождитесь пополнения токенов
"""
            else:
                text = f"""
❌ <b>Ошибка рерайта</b>

<b>Причина:</b> {error_message}

🔧 <b>Что можно попробовать:</b>
• Попробовать другой пост или голосовое сообщение
• Проверить подключение к интернету
• Попробовать позже
• Обратиться к администратору
"""
            
            keyboards = await self._get_content_keyboards()
            
            await original_message.answer(
                text,
                reply_markup=keyboards['rewrite_mode']
            )
            
            self.logger.info("✅ Rewrite error sent", 
                           bot_id=self.bot_id,
                           error_type=error_type)
            
        except Exception as e:
            self.logger.error("💥 Failed to send rewrite error", 
                            bot_id=self.bot_id,
                            error=str(e))
            await original_message.answer("Критическая ошибка при обработке ошибки рерайта")
    
    async def _send_media_with_text(self, message: Message, text: str, media_info: Dict, keyboard):
        """🔧 ИСПРАВЛЕНО: Отправка медиа с переписанным текстом (поддержка медиагрупп)"""
        try:
            media_type = media_info['type']
            
            # 🔧 ИСПРАВЛЕНИЕ: Обработка медиагрупп
            if media_type == 'media_group':
                # Для медиагрупп используем MediaGroupBuilder
                media_builder = MediaGroupBuilder(caption=text)
                
                files_info = media_info.get('files', [])
                media_added = 0
                
                for file_info in files_info:
                    file_type = file_info.get('type')
                    file_id = file_info.get('file_id')
                    
                    if file_type == 'photo' and file_id:
                        media_builder.add_photo(media=file_id)
                        media_added += 1
                    elif file_type == 'video' and file_id:
                        media_builder.add_video(media=file_id)
                        media_added += 1
                    elif file_type == 'animation' and file_id:
                        # GIF отправляем как video
                        media_builder.add_video(media=file_id)
                        media_added += 1
                    elif file_type == 'audio' and file_id:
                        media_builder.add_audio(media=file_id)
                        media_added += 1
                    elif file_type == 'document' and file_id:
                        media_builder.add_document(media=file_id)
                        media_added += 1
                    # Примечание: стикеры не поддерживаются в медиагруппах
                
                if media_added > 0:
                    # Отправляем медиагруппу
                    media_group = media_builder.build()
                    await message.answer_media_group(media=media_group)
                    
                    # Отправляем кнопки отдельным сообщением
                    await message.answer("✨ <b>Рерайт готов!</b>", reply_markup=keyboard)
                    
                    self.logger.debug("📸 Media group sent with clean rewrite result", 
                                    bot_id=self.bot_id, media_files=media_added)
                else:
                    # Fallback: отправляем только текст если медиа не добавились
                    await message.answer(text, reply_markup=keyboard)
                    self.logger.warning("⚠️ No media files added to group, sent text only", bot_id=self.bot_id)
                
                return
                
            # Обработка одиночных медиафайлов
            file_id = media_info.get('file_id')
            if not file_id:
                # Если нет file_id, отправляем только текст
                await message.answer(text, reply_markup=keyboard)
                self.logger.warning("⚠️ No file_id found, sent text only", 
                                   bot_id=self.bot_id, media_type=media_type)
                return
            
            if media_type == 'photo':
                await message.answer_photo(
                    photo=file_id,
                    caption=text,  # ✨ Только переписанный текст
                    reply_markup=keyboard
                )
                self.logger.debug("📷 Photo sent with clean rewrite result", bot_id=self.bot_id)
                
            elif media_type == 'video':
                await message.answer_video(
                    video=file_id,
                    caption=text,  # ✨ Только переписанный текст
                    reply_markup=keyboard
                )
                self.logger.debug("🎥 Video sent with clean rewrite result", bot_id=self.bot_id)
                
            elif media_type == 'animation':
                await message.answer_animation(
                    animation=file_id,
                    caption=text,  # ✨ Только переписанный текст
                    reply_markup=keyboard
                )
                self.logger.debug("🎬 Animation sent with clean rewrite result", bot_id=self.bot_id)
                
            elif media_type == 'audio':
                await message.answer_audio(
                    audio=file_id,
                    caption=text,  # ✨ Только переписанный текст
                    reply_markup=keyboard
                )
                self.logger.debug("🎵 Audio sent with clean rewrite result", bot_id=self.bot_id)
                
            elif media_type == 'document':
                await message.answer_document(
                    document=file_id,
                    caption=text,  # ✨ Только переписанный текст
                    reply_markup=keyboard
                )
                self.logger.debug("📄 Document sent with clean rewrite result", bot_id=self.bot_id)
                
            elif media_type == 'sticker':
                # Стикеры не поддерживают caption, отправляем отдельно
                await message.answer_sticker(sticker=file_id)
                await message.answer(text, reply_markup=keyboard)
                self.logger.debug("🎭 Sticker sent with separate text", bot_id=self.bot_id)
                
            else:
                # Fallback для других типов медиа
                await message.answer(text, reply_markup=keyboard)
                self.logger.debug("📄 Fallback text sent (unsupported media)", 
                                bot_id=self.bot_id, media_type=media_type)
                
        except Exception as e:
            self.logger.error("💥 Failed to send media with clean text", 
                            media_type=media_info.get('type'),
                            error=str(e),
                            exc_info=True)
            # Fallback - отправляем только текст
            await message.answer(text, reply_markup=keyboard)
