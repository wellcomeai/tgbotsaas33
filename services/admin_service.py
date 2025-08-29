import asyncio
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
import structlog

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InputMediaPhoto, InputMediaVideo, InputMediaDocument, InputMediaAudio

from config import settings
from database import db
from utils.media_handler import MediaHandler, BroadcastMedia

logger = structlog.get_logger()


class AdminService:
    """Сервис для админских функций с поддержкой медиа"""
    
    def __init__(self, bot: Bot):
        self.bot = bot
        
    def is_super_admin(self, user_id: int) -> bool:
        """Проверка является ли пользователь суперадмином"""
        return user_id == settings.super_admin_chat_id
    
    async def get_admin_statistics(self) -> str:
        """Получить отформатированную статистику для админа"""
        try:
            stats = await db.get_admin_statistics()
            
            if 'error' in stats:
                return f"❌ <b>Ошибка получения статистики:</b>\n{stats['error']}"
            
            # Форматируем статистику
            text = f"""
📊 <b>СТАТИСТИКА ПЛАТФОРМЫ</b>

👥 <b>ПОЛЬЗОВАТЕЛИ:</b>
├ Всего: <b>{stats['users']['total']}</b>
├ Новых за 24ч: <b>{stats['users']['new_24h']}</b> 
├ Новых за 7 дней: <b>{stats['users']['new_7d']}</b>
├ Активные подписки: <b>{stats['users']['active_subscriptions']}</b>
└ Конверсия в подписку: <b>{stats['users']['subscription_rate']}%</b>

🤖 <b>БОТЫ:</b>
├ Всего создано: <b>{stats['bots']['total']}</b>
├ Активных: <b>{stats['bots']['active']}</b>
├ С ИИ агентами: <b>{stats['bots']['ai_enabled']}</b>
├ Активность: <b>{stats['bots']['activity_rate']}%</b>
└ Внедрение ИИ: <b>{stats['bots']['ai_adoption_rate']}%</b>

🔋 <b>ТОКЕНЫ OPENAI:</b>
├ Использовано: <b>{stats['tokens']['total_used']:,}</b>
├ Общий лимит: <b>{stats['tokens']['total_limit']:,}</b>
├ Использование: <b>{stats['tokens']['usage_rate']}%</b>
└ В среднем на юзера: <b>{stats['tokens']['average_per_user']:,.0f}</b>
"""

            # Добавляем топ пользователей по токенам
            if stats['top_users']['by_tokens']:
                text += "\n🏆 <b>ТОП ПО ТОКЕНАМ:</b>\n"
                for i, user in enumerate(stats['top_users']['by_tokens'][:5], 1):
                    name = user['first_name'] or user['username'] or f"ID{user['user_id']}"
                    text += f"{i}. <b>{name}</b>: {user['tokens_used']:,} токенов\n"
            
            # Добавляем топ пользователей по ботам
            if stats['top_users']['by_bots']:
                text += "\n🏆 <b>ТОП ПО БОТАМ:</b>\n"
                for i, user in enumerate(stats['top_users']['by_bots'][:5], 1):
                    name = user['first_name'] or user['username'] or f"ID{user['user_id']}"
                    text += f"{i}. <b>{name}</b>: {user['bot_count']} ботов\n"
            
            text += f"\n⏰ <b>Обновлено:</b> {datetime.fromisoformat(stats['generated_at']).strftime('%d.%m.%Y %H:%M')}"
            
            return text
            
        except Exception as e:
            logger.error("Failed to format admin statistics", error=str(e))
            return f"❌ <b>Ошибка форматирования статистики:</b>\n{str(e)}"
    
    async def validate_broadcast_media(self, broadcast_media: BroadcastMedia) -> Dict[str, Any]:
        """Валидация медиа для рассылки"""
        return MediaHandler.validate_media_for_broadcast(broadcast_media)
    
    async def start_admin_broadcast_with_media(self, admin_user_id: int, broadcast_media: BroadcastMedia) -> Dict[str, Any]:
        """✅ ИСПРАВЛЕНО: Начать админскую рассылку с медиа контентом"""
        try:
            # Валидация медиа
            validation = await self.validate_broadcast_media(broadcast_media)
            if not validation['valid']:
                return {
                    'success': False,
                    'error': f"Ошибка валидации медиа: {'; '.join(validation['errors'])}"
                }
            
            # Получаем всех активных пользователей
            users = await db.get_all_active_master_bot_users()
            
            if not users:
                return {
                    'success': False,
                    'error': 'Нет активных пользователей для рассылки'
                }
            
            # ✅ ИСПРАВЛЕНО: Генерируем уникальный ID для рассылки без сохранения в БД
            broadcast_log_id = str(uuid.uuid4())
            
            # Логируем начало рассылки в структурном логе
            logger.info("📨 Admin media broadcast started", 
                       admin_user_id=admin_user_id,
                       broadcast_id=broadcast_log_id,
                       total_users=len(users),
                       has_media=broadcast_media.has_media,
                       is_album=broadcast_media.is_album,
                       media_count=broadcast_media.media_count,
                       total_size=validation.get('total_size', 0))
            
            # Запускаем рассылку в фоне
            asyncio.create_task(self._execute_media_broadcast(
                users=users,
                broadcast_media=broadcast_media,
                admin_user_id=admin_user_id,
                broadcast_log_id=broadcast_log_id
            ))
            
            return {
                'success': True,
                'total_users': len(users),
                'broadcast_id': broadcast_log_id,
                'media_info': {
                    'has_media': broadcast_media.has_media,
                    'is_album': broadcast_media.is_album,
                    'media_count': broadcast_media.media_count,
                    'total_size': validation['total_size']
                },
                'message': f'Медиа рассылка запущена для {len(users)} пользователей'
            }
            
        except Exception as e:
            logger.error("Failed to start admin media broadcast", 
                        admin_id=admin_user_id,
                        error=str(e))
            return {
                'success': False,
                'error': f'Ошибка запуска медиа рассылки: {str(e)}'
            }
    
    async def start_admin_broadcast(self, admin_user_id: int, message_text: str) -> Dict[str, Any]:
        """Начать админскую рассылку (обратная совместимость)"""
        from utils.media_handler import BroadcastMedia
        
        # Создаем BroadcastMedia из текста
        broadcast_media = BroadcastMedia(
            media_items=[],
            text_content=message_text,
            is_album=False
        )
        
        return await self.start_admin_broadcast_with_media(admin_user_id, broadcast_media)
    
    async def _execute_media_broadcast(self, users: List[Dict], broadcast_media: BroadcastMedia, 
                                     admin_user_id: int, broadcast_log_id: str):
        """✅ ИСПРАВЛЕНО: Выполнить медиа рассылку с rate limiting"""
        sent_count = 0
        failed_count = 0
        start_time = datetime.now()
        
        media_preview = MediaHandler.get_media_preview_text(broadcast_media)
        
        logger.info("📨 Starting admin media broadcast execution", 
                   total_users=len(users),
                   admin_id=admin_user_id,
                   log_id=broadcast_log_id,
                   has_media=broadcast_media.has_media,
                   is_album=broadcast_media.is_album,
                   media_count=broadcast_media.media_count)
        
        try:
            # Отправляем сообщение админу о начале
            await self.bot.send_message(
                chat_id=admin_user_id,
                text=f"📨 <b>Медиа рассылка запущена</b>\n\n"
                     f"📎 <b>Контент:</b> {media_preview}\n"
                     f"👥 <b>Получателей:</b> {len(users)}\n\n"
                     f"Отправка началась...",
                parse_mode="HTML"
            )
            
            # Рассылка с поддержкой медиа
            for i, user in enumerate(users, 1):
                try:
                    success = await self._send_media_to_user(user['user_id'], broadcast_media)
                    
                    if success:
                        sent_count += 1
                    else:
                        failed_count += 1
                    
                    # Прогресс каждые 100 пользователей
                    if i % 100 == 0:
                        progress_text = f"📊 <b>Прогресс медиа рассылки:</b>\n\n" \
                                      f"📎 <b>Контент:</b> {media_preview}\n" \
                                      f"Отправлено: {sent_count}/{len(users)}\n" \
                                      f"Ошибок: {failed_count}\n" \
                                      f"Прогресс: {(i/len(users)*100):.1f}%"
                        
                        await self.bot.send_message(
                            chat_id=admin_user_id,
                            text=progress_text,
                            parse_mode="HTML"
                        )
                    
                except Exception as e:
                    logger.error("Error sending media to user", 
                               user_id=user['user_id'],
                               error=str(e))
                    failed_count += 1
                
                # Rate limiting между сообщениями
                await asyncio.sleep(settings.admin_broadcast_delay)
            
            # Финальный отчет
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            final_report = f"""
✅ <b>Медиа рассылка завершена!</b>

📎 <b>КОНТЕНТ:</b> {media_preview}

📊 <b>РЕЗУЛЬТАТ:</b>
├ Успешно отправлено: <b>{sent_count}</b>
├ Ошибок: <b>{failed_count}</b>  
├ Общий охват: <b>{len(users)}</b>
├ Успешность: <b>{(sent_count/len(users)*100):.1f}%</b>
└ Время выполнения: <b>{duration:.1f}сек</b>

🚀 Рассылка ID: <code>{broadcast_log_id}</code>
"""
            
            await self.bot.send_message(
                chat_id=admin_user_id,
                text=final_report,
                parse_mode="HTML"
            )
            
            logger.info("✅ Admin media broadcast completed", 
                       total=len(users),
                       sent=sent_count,
                       failed=failed_count,
                       duration=duration,
                       log_id=broadcast_log_id,
                       media_count=broadcast_media.media_count,
                       success_rate=f"{(sent_count/len(users)*100):.1f}%")
            
        except Exception as e:
            logger.error("💥 Admin media broadcast execution failed", 
                        admin_id=admin_user_id,
                        log_id=broadcast_log_id,
                        error=str(e))
            
            # Отправляем уведомление об ошибке админу
            try:
                await self.bot.send_message(
                    chat_id=admin_user_id,
                    text=f"❌ <b>Ошибка выполнения медиа рассылки:</b>\n\n{str(e)}",
                    parse_mode="HTML"
                )
            except Exception:
                pass
    
    async def _send_media_to_user(self, user_id: int, broadcast_media: BroadcastMedia) -> bool:
        """✅ Отправить медиа контент пользователю"""
        try:
            # Если нет медиа, отправляем только текст
            if not broadcast_media.has_media:
                if broadcast_media.text_content:
                    await self.bot.send_message(
                        chat_id=user_id,
                        text=broadcast_media.text_content,
                        parse_mode="HTML"
                    )
                    return True
                return False
            
            # Медиаальбом
            if broadcast_media.is_album and len(broadcast_media.media_items) > 1:
                return await self._send_media_group(user_id, broadcast_media)
            
            # Одиночное медиа
            elif len(broadcast_media.media_items) == 1:
                return await self._send_single_media(user_id, broadcast_media.media_items[0], broadcast_media.text_content)
            
            return False
            
        except TelegramRetryAfter as e:
            # Ждем при rate limit и повторяем попытку
            logger.warning("Rate limit hit in media send, waiting", wait_time=e.retry_after, user_id=user_id)
            await asyncio.sleep(e.retry_after)
            return await self._send_media_to_user(user_id, broadcast_media)
            
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            # Пользователь заблокировал бота или удалил аккаунт
            logger.debug("User blocked bot or deleted account", user_id=user_id, error=str(e))
            return False
            
        except Exception as e:
            logger.error("Failed to send media to user", user_id=user_id, error=str(e))
            return False
    
    async def _send_media_group(self, user_id: int, broadcast_media: BroadcastMedia) -> bool:
        """Отправить медиаальбом"""
        try:
            input_media = []
            
            for i, media_item in enumerate(broadcast_media.media_items[:10]):  # Максимум 10 в альбоме
                # Первый элемент альбома получает текст в caption
                caption = broadcast_media.text_content if i == 0 else None
                
                if media_item.media_type == 'photo':
                    input_media.append(InputMediaPhoto(
                        media=media_item.file_id,
                        caption=caption,
                        parse_mode="HTML" if caption else None
                    ))
                elif media_item.media_type == 'video':
                    input_media.append(InputMediaVideo(
                        media=media_item.file_id,
                        caption=caption,
                        parse_mode="HTML" if caption else None
                    ))
                elif media_item.media_type == 'document':
                    input_media.append(InputMediaDocument(
                        media=media_item.file_id,
                        caption=caption,
                        parse_mode="HTML" if caption else None
                    ))
                elif media_item.media_type == 'audio':
                    input_media.append(InputMediaAudio(
                        media=media_item.file_id,
                        caption=caption,
                        parse_mode="HTML" if caption else None
                    ))
            
            if input_media:
                await self.bot.send_media_group(
                    chat_id=user_id,
                    media=input_media
                )
                return True
            
            return False
            
        except Exception as e:
            logger.error("Failed to send media group", user_id=user_id, error=str(e))
            return False
    
    async def _send_single_media(self, user_id: int, media_item, caption: Optional[str] = None) -> bool:
        """Отправить одиночное медиа"""
        try:
            if media_item.media_type == 'photo':
                await self.bot.send_photo(
                    chat_id=user_id,
                    photo=media_item.file_id,
                    caption=caption,
                    parse_mode="HTML" if caption else None
                )
            elif media_item.media_type == 'video':
                await self.bot.send_video(
                    chat_id=user_id,
                    video=media_item.file_id,
                    caption=caption,
                    parse_mode="HTML" if caption else None
                )
            elif media_item.media_type == 'document':
                await self.bot.send_document(
                    chat_id=user_id,
                    document=media_item.file_id,
                    caption=caption,
                    parse_mode="HTML" if caption else None
                )
            elif media_item.media_type == 'audio':
                await self.bot.send_audio(
                    chat_id=user_id,
                    audio=media_item.file_id,
                    caption=caption,
                    parse_mode="HTML" if caption else None
                )
            elif media_item.media_type == 'voice':
                await self.bot.send_voice(
                    chat_id=user_id,
                    voice=media_item.file_id,
                    caption=caption,
                    parse_mode="HTML" if caption else None
                )
            elif media_item.media_type == 'video_note':
                await self.bot.send_video_note(
                    chat_id=user_id,
                    video_note=media_item.file_id
                )
                # Отправляем текст отдельно, так как video_note не поддерживает caption
                if caption:
                    await self.bot.send_message(
                        chat_id=user_id,
                        text=caption,
                        parse_mode="HTML"
                    )
            elif media_item.media_type == 'animation':
                await self.bot.send_animation(
                    chat_id=user_id,
                    animation=media_item.file_id,
                    caption=caption,
                    parse_mode="HTML" if caption else None
                )
            elif media_item.media_type == 'sticker':
                await self.bot.send_sticker(
                    chat_id=user_id,
                    sticker=media_item.file_id
                )
                # Отправляем текст отдельно, так как sticker не поддерживает caption
                if caption:
                    await self.bot.send_message(
                        chat_id=user_id,
                        text=caption,
                        parse_mode="HTML"
                    )
            else:
                return False
            
            return True
            
        except Exception as e:
            logger.error("Failed to send single media", 
                        user_id=user_id, 
                        media_type=media_item.media_type,
                        error=str(e))
            return False
    
    async def get_broadcast_history(self, admin_user_id: int) -> str:
        """✅ ИСПРАВЛЕНО: Получить историю админских рассылок"""
        try:
            # Пытаемся получить историю из БД, если метод существует
            try:
                history = await db.get_admin_broadcast_history(limit=10)
            except AttributeError:
                # Если метод не существует, возвращаем заглушку
                logger.warning("get_admin_broadcast_history method not found in db")
                return """
📭 <b>ИСТОРИЯ РАССЫЛОК</b>

⚠️ <b>Функция находится в разработке</b>

📝 История рассылок будет доступна после обновления системы логирования.
Пока что все рассылки логируются только в системные логи.

🔍 Для просмотра логов рассылок обратитесь к системным логам приложения.
"""
            
            if not history:
                return "📭 <b>История рассылок пуста</b>\n\nВы еще не делали рассылок."
            
            text = "📨 <b>ИСТОРИЯ РАССЫЛОК</b>\n\n"
            
            for i, broadcast in enumerate(history, 1):
                created_at = datetime.fromisoformat(broadcast['created_at'])
                data = broadcast.get('data', {})
                recipients = data.get('total_recipients', 0)
                preview = data.get('message_preview', 'Нет превью')
                media_info = data.get('media_info', {})
                status = "✅" if broadcast.get('success', True) else "❌"
                
                text += f"{status} <b>#{broadcast['id']}</b>\n"
                text += f"📅 {created_at.strftime('%d.%m.%Y %H:%M')}\n"
                text += f"👥 {recipients} получателей\n"
                
                # Добавляем инфо о медиа
                if media_info.get('has_media'):
                    media_desc = []
                    if media_info.get('is_album'):
                        media_desc.append(f"📸 Альбом ({media_info.get('media_count', 0)} элементов)")
                    else:
                        media_type = media_info.get('primary_media_type', 'медиа')
                        try:
                            emoji = MediaHandler._get_media_emoji(media_type)
                            name = MediaHandler._get_media_name_ru(media_type)
                            media_desc.append(f"{emoji} {name}")
                        except:
                            media_desc.append(f"📎 {media_type}")
                    
                    total_size = media_info.get('total_size', 0)
                    if total_size > 0:
                        media_desc.append(f"({total_size / 1024 / 1024:.1f}MB)")
                    
                    text += f"📎 {' '.join(media_desc)}\n"
                
                text += f"📝 {preview}\n\n"
            
            return text
            
        except Exception as e:
            logger.error("Failed to get broadcast history", error=str(e))
            return f"""
❌ <b>Ошибка получения истории:</b>

{str(e)}

💡 <b>Временное решение:</b>
История рассылок логируется в системные логи. 
Все выполненные рассылки можно отследить по логам приложения.
"""
