"""
Методы работы с медиа и альбомами (медиагруппами).

✅ ПОЛНАЯ ФУНКЦИОНАЛЬНОСТЬ:
1. 📸 Обработка альбомов (медиагрупп) через aiogram-media-group
2. 🔧 Извлечение информации из всех типов медиафайлов
3. 📱 Отправка медиа с поддержкой всех форматов
4. 🔗 Интеграция с извлечением ссылок
5. 📊 Детальное логирование обработки медиа
6. 🛡️ Обработка ошибок и fallback сценарии
7. ✨ Упрощенный интерфейс результатов
8. 🏗️ Поддержка MediaGroupBuilder для альбомов
"""

from typing import List, Dict
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.utils.media_group import MediaGroupBuilder
from services.content_agent import content_agent_service

# Импорт для проверки медиагрупп
try:
    from aiogram_media_group import media_group_handler
    MEDIA_GROUP_AVAILABLE = True
except ImportError:
    MEDIA_GROUP_AVAILABLE = False

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


class MediaHandlersMixin:
    """Миксин для методов работы с медиа и альбомами"""
    
    async def handle_media_group_rewrite_input(self, messages: List[Message], state: FSMContext):
        """✅ Обработка альбома для рерайта с поддержкой ссылок"""
        
        self.logger.info("📸 Processing media group for rewrite with links support", 
                        bot_id=self.bot_id,
                        media_count=len(messages),
                        media_group_id=messages[0].media_group_id)
        
        try:
            # Показываем процесс обработки
            processing_msg = await messages[0].answer(
                f"⏳ <b>Обрабатываю альбом ({len(messages)} файлов)...</b>\n\n"
                f"🔍 Анализ медиафайлов...\n"
                f"📝 Извлечение текста...\n"
                f"🔗 Извлечение ссылок...\n"
                f"🤖 Отправка агенту...\n\n"
                f"<i>Это может занять 10-20 секунд</i>"
            )
            
            # Извлекаем текст из первого сообщения (только оно может содержать caption)
            original_text = ""
            for message in messages:
                text = message.text or message.caption or ""
                if text:
                    original_text = text.strip()
                    break
            
            if not original_text:
                await processing_msg.delete()
                await messages[0].answer(
                    "❌ <b>Текст не найден в альбоме</b>\n\n"
                    "Добавьте подпись к альбому для рерайта."
                )
                return
            
            if len(original_text) < 3:
                await processing_msg.delete()
                await messages[0].answer(
                    "❌ <b>Текст слишком короткий</b>\n\n"
                    "Минимальная длина текста: 3 символа."
                )
                return
            
            # Извлекаем информацию о всех медиафайлах
            media_group_info = []
            for i, message in enumerate(messages):
                media_info = content_agent_service.extract_media_info(message)
                if media_info:
                    media_info['position'] = i
                    media_info['message_id'] = message.message_id
                    media_group_info.append(media_info)
            
            # ✨ НОВОЕ: Извлекаем ссылки из первого сообщения альбома
            links_info = {'has_links': False, 'links': {}, 'total_links': 0}
            try:
                # Используем функцию извлечения ссылок из content_agent_service
                links_info = content_agent_service.extract_links_from_message(messages[0])
            except Exception as e:
                self.logger.warning("⚠️ Failed to extract links from media group", error=str(e))
            
            self.logger.info("📊 Media group analysis completed with links", 
                           bot_id=self.bot_id,
                           text_length=len(original_text),
                           media_files=len(media_group_info),
                           has_links=links_info['has_links'],
                           total_links=links_info['total_links'])
            
            # Выполняем рерайт через ContentManager
            rewrite_result = await content_agent_service.content_manager.process_content_rewrite(
                bot_id=self.bot_id,
                original_text=original_text,
                media_info={
                    'type': 'media_group',
                    'count': len(messages),
                    'files': media_group_info,
                    'media_group_id': messages[0].media_group_id
                },
                links_info=links_info,  # ✨ НОВОЕ
                user_id=messages[0].from_user.id
            )
            
            # Удаляем сообщение о процессе
            try:
                await processing_msg.delete()
            except:
                pass
            
            if rewrite_result and rewrite_result.get('success'):
                # Успешный рерайт альбома
                await self._send_media_group_rewrite_result(messages, rewrite_result)
                
                self.logger.info("✅ Media group rewritten successfully with links", 
                               bot_id=self.bot_id,
                               media_count=len(messages),
                               tokens_used=rewrite_result.get('tokens', {}).get('total_tokens', 0),
                               has_links=links_info['has_links'])
            else:
                # Ошибка рерайта
                from .rewrite_handlers import RewriteHandlersMixin
                await self._send_rewrite_error(messages[0], rewrite_result or {'error': 'unknown'})
                
        except Exception as e:
            self.logger.error("💥 Failed to process media group rewrite with links", 
                            bot_id=self.bot_id,
                            media_group_id=messages[0].media_group_id,
                            error=str(e))
            await messages[0].answer("Ошибка при обработке альбома")
    
    async def _send_media_group_rewrite_result(self, original_messages: List[Message], result: Dict):
        """🔧 УПРОЩЕНО: Отправка результата рерайта альбома через общий метод"""
        
        # 🔧 Безопасное извлечение данных из result
        content = self._safe_get_from_result(result, 'content', {})
        tokens = self._safe_get_from_result(result, 'tokens', {})
        media_info = self._safe_get_from_result(result, 'media_info', {})
        agent_info = self._safe_get_from_result(result, 'agent', {})
        
        # Проверяем, что основные данные получены
        if not content or not isinstance(content, dict):
            self.logger.error("❌ No content in media group result", 
                             bot_id=self.bot_id,
                             result_keys=list(result.keys()) if isinstance(result, dict) else 'not_dict')
            await original_messages[0].answer(
                "❌ <b>Ошибка: не получен результат рерайта</b>\n\n"
                "Попробуйте еще раз или обратитесь к администратору."
            )
            return
        
        rewritten_text = content.get('rewritten_text', 'Ошибка: текст не получен')
        
        try:
            # Сохраняем результат рерайта
            save_success = await content_agent_service.content_manager.save_rewrite_result(
                self.bot_id, result
            )
            
            # Получаем клавиатуру
            keyboards = await self._get_content_keyboards()
            post_actions_keyboard = keyboards['post_actions']
            
            # 🔧 ИСПРАВЛЕНИЕ: Восстанавливаем информацию о файлах, если отсутствует
            if media_info and media_info.get('type') == 'media_group':
                # Проверяем, есть ли информация о файлах
                if not media_info.get('files'):
                    # Восстанавливаем информацию из оригинальных сообщений
                    files_info = []
                    for i, message in enumerate(original_messages):
                        if message.photo:
                            largest_photo = max(message.photo, key=lambda x: x.width * x.height)
                            files_info.append({
                                'type': 'photo',
                                'file_id': largest_photo.file_id,
                                'position': i,
                                'message_id': message.message_id
                            })
                        elif message.video:
                            files_info.append({
                                'type': 'video',
                                'file_id': message.video.file_id,
                                'position': i,
                                'message_id': message.message_id
                            })
                        elif message.animation:
                            files_info.append({
                                'type': 'animation',
                                'file_id': message.animation.file_id,
                                'position': i,
                                'message_id': message.message_id
                            })
                        elif message.audio:
                            files_info.append({
                                'type': 'audio',
                                'file_id': message.audio.file_id,
                                'position': i,
                                'message_id': message.message_id
                            })
                        elif message.document:
                            files_info.append({
                                'type': 'document',
                                'file_id': message.document.file_id,
                                'position': i,
                                'message_id': message.message_id
                            })
                        # Примечание: стикеры не поддерживаются в альбомах Telegram
                    
                    # Обновляем media_info с информацией о файлах
                    media_info['files'] = files_info
                    self.logger.info("✅ Restored media files info from original messages", 
                                   bot_id=self.bot_id, files_count=len(files_info))
                
                # Используем общий метод _send_media_with_text
                await self._send_media_with_text(
                    original_messages[0],
                    rewritten_text,
                    media_info,
                    post_actions_keyboard
                )
            else:
                # Fallback для случая, если медиа-информация некорректна
                await original_messages[0].answer(
                    rewritten_text, 
                    reply_markup=post_actions_keyboard
                )
            
            # Логируем техническую информацию, но не показываем пользователю
            self.logger.info("✅ Clean media group rewrite result sent via unified method", 
                           bot_id=self.bot_id,
                           agent_name=agent_info.get('name', 'Unknown'),
                           media_files=len(original_messages),
                           tokens_used=tokens.get('total_tokens', 0),
                           original_length=len(content.get('original_text', '')),
                           rewritten_length=len(rewritten_text))
            
        except Exception as e:
            self.logger.error("💥 Failed to send clean media group rewrite result", 
                            bot_id=self.bot_id,
                            error=str(e),
                            error_type=type(e).__name__,
                            exc_info=True)
            
            # 🔧 ИСПРАВЛЕНО: Безопасный fallback
            fallback_text = rewritten_text
            
            if len(fallback_text) > 4096:
                fallback_text = fallback_text[:4093] + "..."
            
            keyboards = await self._get_content_keyboards()
            await original_messages[0].answer(
                f"{fallback_text}\n\n⚠️ Ошибка отправки медиа: {str(e)}",
                reply_markup=keyboards['post_actions']
            )
    
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
    
    def _extract_media_info(self, message: Message) -> Dict:
        """🔧 Извлечение информации о медиафайле из сообщения"""
        try:
            if message.photo:
                # Берем самое большое фото
                largest_photo = max(message.photo, key=lambda x: x.width * x.height)
                return {
                    'type': 'photo',
                    'file_id': largest_photo.file_id,
                    'file_unique_id': largest_photo.file_unique_id,
                    'width': largest_photo.width,
                    'height': largest_photo.height,
                    'file_size': getattr(largest_photo, 'file_size', None)
                }
                
            elif message.video:
                return {
                    'type': 'video',
                    'file_id': message.video.file_id,
                    'file_unique_id': message.video.file_unique_id,
                    'width': message.video.width,
                    'height': message.video.height,
                    'duration': message.video.duration,
                    'file_size': getattr(message.video, 'file_size', None),
                    'mime_type': getattr(message.video, 'mime_type', None)
                }
                
            elif message.animation:
                return {
                    'type': 'animation',
                    'file_id': message.animation.file_id,
                    'file_unique_id': message.animation.file_unique_id,
                    'width': message.animation.width,
                    'height': message.animation.height,
                    'duration': message.animation.duration,
                    'file_size': getattr(message.animation, 'file_size', None),
                    'mime_type': getattr(message.animation, 'mime_type', None)
                }
                
            elif message.audio:
                return {
                    'type': 'audio',
                    'file_id': message.audio.file_id,
                    'file_unique_id': message.audio.file_unique_id,
                    'duration': message.audio.duration,
                    'file_size': getattr(message.audio, 'file_size', None),
                    'mime_type': getattr(message.audio, 'mime_type', None),
                    'title': getattr(message.audio, 'title', None),
                    'performer': getattr(message.audio, 'performer', None)
                }
                
            elif message.document:
                return {
                    'type': 'document',
                    'file_id': message.document.file_id,
                    'file_unique_id': message.document.file_unique_id,
                    'file_name': getattr(message.document, 'file_name', None),
                    'file_size': getattr(message.document, 'file_size', None),
                    'mime_type': getattr(message.document, 'mime_type', None)
                }
                
            elif message.sticker:
                return {
                    'type': 'sticker',
                    'file_id': message.sticker.file_id,
                    'file_unique_id': message.sticker.file_unique_id,
                    'width': message.sticker.width,
                    'height': message.sticker.height,
                    'is_animated': message.sticker.is_animated,
                    'is_video': message.sticker.is_video,
                    'emoji': getattr(message.sticker, 'emoji', None),
                    'set_name': getattr(message.sticker, 'set_name', None)
                }
                
            elif message.voice:
                return {
                    'type': 'voice',
                    'file_id': message.voice.file_id,
                    'file_unique_id': message.voice.file_unique_id,
                    'duration': message.voice.duration,
                    'file_size': getattr(message.voice, 'file_size', None),
                    'mime_type': getattr(message.voice, 'mime_type', None)
                }
                
            elif message.video_note:
                return {
                    'type': 'video_note',
                    'file_id': message.video_note.file_id,
                    'file_unique_id': message.video_note.file_unique_id,
                    'length': message.video_note.length,
                    'duration': message.video_note.duration,
                    'file_size': getattr(message.video_note, 'file_size', None)
                }
            
            # Если медиа не найдено
            return None
            
        except Exception as e:
            self.logger.error("💥 Failed to extract media info", 
                            message_id=message.message_id,
                            error=str(e))
            return None
    
    def _get_supported_media_types(self) -> List[str]:
        """📎 Возвращает список поддерживаемых типов медиа"""
        return [
            'photo',       # 📷 Фотографии
            'video',       # 🎥 Видео
            'animation',   # 🎬 GIF/анимации
            'audio',       # 🎵 Аудиофайлы
            'document',    # 📄 Документы
            'sticker',     # 🎭 Стикеры
            'voice',       # 🎤 Голосовые сообщения
            'video_note'   # 🎥 Видеосообщения (кружки)
        ]
    
    def _is_media_supported(self, message: Message) -> bool:
        """🔍 Проверяет поддерживается ли тип медиа"""
        supported_types = self._get_supported_media_types()
        
        for media_type in supported_types:
            if hasattr(message, media_type) and getattr(message, media_type):
                return True
        
        return False
    
    def _get_media_type_emoji(self, media_type: str) -> str:
        """🎨 Возвращает эмоджи для типа медиа"""
        emoji_map = {
            'photo': '📷',
            'video': '🎥',
            'animation': '🎬',
            'audio': '🎵',
            'document': '📄',
            'sticker': '🎭',
            'voice': '🎤',
            'video_note': '🎥',
            'media_group': '📸'
        }
        
        return emoji_map.get(media_type, '📎')
    
    def _format_media_info(self, media_info: Dict) -> str:
        """📊 Форматирует информацию о медиа для отображения"""
        if not media_info:
            return "Нет медиа"
        
        media_type = media_info.get('type', 'unknown')
        emoji = self._get_media_type_emoji(media_type)
        
        # Базовая информация
        info_parts = [f"{emoji} {media_type.title()}"]
        
        # Размер файла
        file_size = media_info.get('file_size')
        if file_size:
            size_mb = file_size / (1024 * 1024)
            if size_mb >= 1:
                info_parts.append(f"{size_mb:.1f} MB")
            else:
                size_kb = file_size / 1024
                info_parts.append(f"{size_kb:.0f} KB")
        
        # Дополнительная информация по типу
        if media_type in ['photo', 'video', 'animation']:
            width = media_info.get('width')
            height = media_info.get('height')
            if width and height:
                info_parts.append(f"{width}x{height}")
        
        if media_type in ['video', 'animation', 'audio', 'voice']:
            duration = media_info.get('duration')
            if duration:
                minutes = duration // 60
                seconds = duration % 60
                info_parts.append(f"{minutes}:{seconds:02d}")
        
        # Имя файла для документов
        if media_type == 'document':
            file_name = media_info.get('file_name')
            if file_name:
                info_parts.append(f'"{file_name}"')
        
        return " • ".join(info_parts)
