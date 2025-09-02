"""
Методы публикации в каналы и работа с каналами.

✅ ПОЛНАЯ ФУНКЦИОНАЛЬНОСТЬ:
1. 📤 Публикация готовых постов в каналы
2. ✏️ Редактирование постов с правками
3. 📺 Подключение и управление каналами
4. 🔧 Проверка прав бота в каналах
5. 📱 Публикация всех типов медиа в каналы
6. 🎥 Поддержка альбомов при публикации
7. 🔗 Сохранение ссылок при публикации
8. 📊 Детальное логирование публикации
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


class ChannelHandlersMixin:
    """Миксин для методов работы с каналами"""
    
    async def cb_edit_post(self, callback: CallbackQuery, state: FSMContext):
        """Начало редактирования поста"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Проверяем есть ли последний рерайт
            last_rewrite = await content_agent_service.content_manager.get_last_rewrite(self.bot_id)
            
            if not last_rewrite:
                await callback.answer("Нет данных для редактирования", show_alert=True)
                return
            
            text = """
✏️ <b>Внесение правок в пост</b>

<b>Что нужно изменить?</b>

Опишите какие правки внести:
- "Сделать тон более дружелюбным"
- "Добавить призыв к действию"
- "Убрать лишние эмоджи"
- "Сократить текст вдвое"

🎤 <b>НОВОЕ: Вы можете записать правки голосом!</b>

<b>Введите инструкции для правок текстом или 🎤 запишите голосом:</b>
"""
            
            keyboards = await self._get_content_keyboards()
            
            await callback.message.answer(
                text, 
                reply_markup=keyboards['back_to_rewrite']
            )
            
            if CONTENT_STATES_AVAILABLE:
                await state.set_state(ContentStates.waiting_for_edit_instructions)
                
        except Exception as e:
            self.logger.error("💥 Error starting post edit", error=str(e))
            await callback.answer("Ошибка начала редактирования", show_alert=True)
    
    async def cb_publish_post(self, callback: CallbackQuery):
        """Публикация поста в канал"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Получаем данные канала и последний рерайт
            channel_info = await content_agent_service.content_manager.get_channel_info(self.bot_id)
            last_rewrite = await content_agent_service.content_manager.get_last_rewrite(self.bot_id)
            
            if not channel_info or not last_rewrite:
                await callback.answer("Нет данных для публикации", show_alert=True)
                return
            
            channel_id = channel_info['chat_id']
            rewritten_text = last_rewrite['content']['rewritten_text']
            media_info = last_rewrite.get('media_info') or last_rewrite.get('media')
            
            # Показываем процесс через answer вместо edit_text
            await callback.answer("⏳ Публикую в канал...", show_alert=True)
            
            # Публикуем в канал
            if media_info:
                await self._publish_media_to_channel(channel_id, rewritten_text, media_info)
            else:
                await self.bot_config['bot'].send_message(channel_id, rewritten_text)
            
            # Создаем клавиатуру для результата
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📝 Новый рерайт", callback_data="content_rewrite")],
                [InlineKeyboardButton(text="📊 Главное меню", callback_data="content_main")]
            ])
            
            # Успешная публикация
            try:
                text = f"""
✅ <b>Пост опубликован!</b>

📺 <b>Канал:</b> {channel_info['chat_title']}
📝 <b>Текст:</b> {self._truncate_text(rewritten_text, 150)}

<b>Что дальше?</b>
"""
                await callback.message.answer(text, reply_markup=keyboard)
            except Exception as parse_error:
                # Упрощенный вариант без проблемного текста
                simple_text = f"""
✅ <b>Пост опубликован в канал!</b>

📺 <b>Канал:</b> {channel_info['chat_title']}

<b>Что дальше?</b>
"""
                await callback.message.answer(simple_text, reply_markup=keyboard)
                self.logger.info("✅ Post published but used simplified result message due to HTML parsing error")
            
        except Exception as e:
            self.logger.error("💥 Error publishing post", error=str(e))
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📝 Попробовать снова", callback_data="content_rewrite")],
                [InlineKeyboardButton(text="📊 Главное меню", callback_data="content_main")]
            ])
            await callback.message.answer("❌ Ошибка публикации в канал", reply_markup=keyboard)
    
    async def _publish_media_to_channel(self, channel_id: int, text: str, media_info: Dict):
        """🔧 ИСПРАВЛЕНО: Публикация медиа в канал с поддержкой альбомов"""    
        try:
            media_type = media_info['type']
            bot = self.bot_config['bot']
            
            # ✅ ИСПРАВЛЕНИЕ: Добавляем обработку медиагрупп
            if media_type == 'media_group':
                # Для альбомов создаем MediaGroupBuilder
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
                        # GIF публикуем как video
                        media_builder.add_video(media=file_id)
                        media_added += 1
                    elif file_type == 'audio' and file_id:
                        media_builder.add_audio(media=file_id)
                        media_added += 1
                    elif file_type == 'document' and file_id:
                        media_builder.add_document(media=file_id)
                        media_added += 1
                    # Примечание: стикеры не поддерживаются в медиагруппах Telegram
                
                if media_added > 0:
                    # Отправляем альбом
                    media_group = media_builder.build()
                    await bot.send_media_group(channel_id, media_group)
                    
                    self.logger.info("✅ Media group published to channel successfully", 
                                   bot_id=self.bot_id,
                                   channel_id=channel_id,
                                   media_files=media_added)
                else:
                    # Fallback: отправляем только текст если медиа не добавились
                    await bot.send_message(channel_id, text)
                    self.logger.warning("⚠️ No media files added to group, sent text only")
                    
            elif media_type == 'photo':
                file_id = media_info['file_id']
                await bot.send_photo(channel_id, photo=file_id, caption=text)
            elif media_type == 'video':
                file_id = media_info['file_id']
                await bot.send_video(channel_id, video=file_id, caption=text)
            elif media_type == 'animation':
                file_id = media_info['file_id']
                await bot.send_animation(channel_id, animation=file_id, caption=text)
            elif media_type == 'audio':
                file_id = media_info['file_id']
                await bot.send_audio(channel_id, audio=file_id, caption=text)
            elif media_type == 'document':
                file_id = media_info['file_id']
                await bot.send_document(channel_id, document=file_id, caption=text)
            elif media_type == 'sticker':
                file_id = media_info['file_id']
                # Стикеры не поддерживают caption, отправляем отдельно
                await bot.send_sticker(channel_id, sticker=file_id)
                await bot.send_message(channel_id, text)
            else:
                # Fallback для неизвестных типов медиа
                await bot.send_message(channel_id, text)
                self.logger.warning("⚠️ Unknown media type, sent text only", 
                                   media_type=media_type)
                
        except Exception as e:
            self.logger.error("💥 Error publishing media to channel", 
                            bot_id=self.bot_id,
                            channel_id=channel_id,
                            media_type=media_info.get('type'),
                            error=str(e))
            raise
    
    async def _check_channel_permissions(self, channel_id: int) -> Dict:
        """🔍 Проверка прав бота в канале"""
        try:
            bot = self.bot_config['bot']
            
            # Получаем информацию о чате
            chat = await bot.get_chat(channel_id)
            
            # Получаем информацию о боте как участнике канала
            bot_member = await bot.get_chat_member(channel_id, bot.id)
            
            permissions = {
                'is_member': bot_member.status in ['member', 'administrator', 'creator'],
                'is_admin': bot_member.status in ['administrator', 'creator'],
                'can_post_messages': False,
                'can_edit_messages': False,
                'can_delete_messages': False,
                'chat_title': chat.title,
                'chat_username': getattr(chat, 'username', None)
            }
            
            # Проверяем специфичные права, если бот админ
            if permissions['is_admin'] and hasattr(bot_member, 'can_post_messages'):
                permissions['can_post_messages'] = getattr(bot_member, 'can_post_messages', False)
                permissions['can_edit_messages'] = getattr(bot_member, 'can_edit_messages', False)
                permissions['can_delete_messages'] = getattr(bot_member, 'can_delete_messages', False)
            
            self.logger.info("✅ Channel permissions checked", 
                           bot_id=self.bot_id,
                           channel_id=channel_id,
                           permissions=permissions)
            
            return {
                'success': True,
                'permissions': permissions
            }
            
        except Exception as e:
            self.logger.error("💥 Error checking channel permissions", 
                            bot_id=self.bot_id,
                            channel_id=channel_id,
                            error=str(e))
            return {
                'success': False,
                'error': str(e)
            }
    
    async def _validate_channel_for_publishing(self, channel_id: int) -> tuple[bool, str]:
        """✅ Валидация канала для публикации"""
        try:
            # Проверяем права
            permissions_result = await self._check_channel_permissions(channel_id)
            
            if not permissions_result['success']:
                return False, f"Не удалось проверить канал: {permissions_result['error']}"
            
            permissions = permissions_result['permissions']
            
            # Проверяем, что бот в канале
            if not permissions['is_member']:
                return False, "Бот не добавлен в канал"
            
            # Проверяем права на публикацию
            if not permissions['is_admin']:
                return False, "Бот должен быть администратором канала"
            
            if not permissions['can_post_messages']:
                return False, "У бота нет права публикации сообщений в канале"
            
            return True, "OK"
            
        except Exception as e:
            self.logger.error("💥 Error validating channel", 
                            channel_id=channel_id,
                            error=str(e))
            return False, f"Ошибка валидации: {str(e)}"
    
    async def _get_channel_info_formatted(self, channel_id: int) -> str:
        """📺 Форматированная информация о канале"""
        try:
            permissions_result = await self._check_channel_permissions(channel_id)
            
            if not permissions_result['success']:
                return f"❌ Ошибка получения информации о канале: {permissions_result['error']}"
            
            permissions = permissions_result['permissions']
            
            # Статусы бота
            status_emoji = "✅" if permissions['is_member'] else "❌"
            admin_emoji = "👑" if permissions['is_admin'] else "👤"
            
            # Права
            rights = []
            if permissions['can_post_messages']:
                rights.append("📝 Публикация")
            if permissions['can_edit_messages']:
                rights.append("✏️ Редактирование")
            if permissions['can_delete_messages']:
                rights.append("🗑️ Удаление")
            
            rights_text = " • ".join(rights) if rights else "Нет прав"
            
            username = f"@{permissions['chat_username']}" if permissions['chat_username'] else "Без username"
            
            return f"""
📺 <b>Информация о канале:</b>
• Название: {permissions['chat_title']}
• Username: {username}
• ID: <code>{channel_id}</code>

🤖 <b>Статус бота:</b>
• {status_emoji} Участник: {'Да' if permissions['is_member'] else 'Нет'}
• {admin_emoji} Администратор: {'Да' if permissions['is_admin'] else 'Нет'}
• Права: {rights_text}

{'✅ Канал готов для публикации' if permissions['can_post_messages'] else '❌ Недостаточно прав для публикации'}
"""
            
        except Exception as e:
            self.logger.error("💥 Error formatting channel info", 
                            channel_id=channel_id,
                            error=str(e))
            return f"❌ Ошибка получения информации о канале: {str(e)}"
    
    async def _save_channel_connection(self, channel_data: Dict) -> bool:
        """💾 Сохранение подключения к каналу"""
        try:
            success = await content_agent_service.content_manager.save_channel_info(
                self.bot_id, channel_data
            )
            
            if success:
                self.logger.info("✅ Channel connection saved", 
                               bot_id=self.bot_id,
                               channel_id=channel_data.get('chat_id'),
                               channel_title=channel_data.get('chat_title'))
            else:
                self.logger.error("❌ Failed to save channel connection", 
                                bot_id=self.bot_id,
                                channel_data=channel_data)
            
            return success
            
        except Exception as e:
            self.logger.error("💥 Error saving channel connection", 
                            bot_id=self.bot_id,
                            error=str(e))
            return False
    
    def _get_publishing_status_message(self, success: bool, channel_title: str, error: str = None) -> str:
        """📊 Сообщение о статусе публикации"""
        if success:
            return f"""
✅ <b>Пост успешно опубликован!</b>

📺 <b>Канал:</b> {channel_title}
🕐 <b>Время:</b> {self._format_date()}

🎯 <b>Что дальше?</b>
• Создать новый пост для рерайта
• Посмотреть статистику агента
• Настроить другие каналы
"""
        else:
            error_text = f": {error}" if error else ""
            
            return f"""
❌ <b>Ошибка публикации{error_text}</b>

🔧 <b>Возможные причины:</b>
• Бот не добавлен в канал как администратор
• Недостаточно прав для публикации
• Канал был удален или заблокирован
• Временные проблемы с Telegram API

💡 <b>Что можно сделать:</b>
• Проверить права бота в канале
• Переподключить канал
• Попробовать опубликовать позже
• Обратиться к администратору
"""
    
    def _get_channel_setup_instructions(self) -> str:
        """📋 Инструкции по настройке канала"""
        return """
📺 <b>Настройка канала для публикации</b>

<b>Пошаговая инструкция:</b>

1️⃣ <b>Добавьте бота в канал:</b>
   • Откройте ваш канал
   • Нажмите на название канала → "Управление каналом"
   • Выберите "Администраторы" → "Добавить администратора"
   • Найдите и добавьте этого бота

2️⃣ <b>Выдайте необходимые права:</b>
   • ✅ Публикация сообщений
   • ✅ Редактирование сообщений (опционально)
   • ✅ Удаление сообщений (опционально)

3️⃣ <b>Подключите канал к боту:</b>
   • Перешлите любой пост из канала сюда
   • Бот автоматически определит канал
   • Проверит права и сохранит подключение

⚠️ <b>Важно:</b>
• Бот должен быть именно администратором (не просто участником)
• Права на публикацию обязательны
• Без прав бот не сможет публиковать посты

🎯 <b>После настройки:</b>
• Агент сможет публиковать переписанные посты
• Медиа файлы будут сохраняться
• Альбомы будут публиковаться как альбомы
• Ссылки будут сохранены в постах
"""
