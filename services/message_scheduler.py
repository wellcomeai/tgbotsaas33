import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramNetworkError

from database import db

logger = logging.getLogger(__name__)


@dataclass
class MessageDetails:
    """Детали сообщения для отправки"""
    text: str
    media_file_id: Optional[str] = None
    media_type: Optional[str] = None
    keyboard: Optional[List[Dict[str, str]]] = None


class MessageFormatter:
    """Simple message formatter"""
    
    def format_message(self, text: str, user_id: int, first_name: str = None, username: str = None) -> str:
        """Format message with user variables"""
        formatted = text.replace("{user_id}", str(user_id))
        formatted = formatted.replace("{first_name}", first_name or "Пользователь")
        formatted = formatted.replace("{username}", f"@{username}" if username else first_name or "Пользователь")
        return formatted


class KeyboardManager:
    """Simple keyboard manager"""
    
    def create_keyboard(self, button_data: List[Dict[str, str]]) -> Optional[InlineKeyboardMarkup]:
        """Create keyboard from button data"""
        if not button_data:
            return None
        
        keyboard = []
        for button in button_data:
            keyboard.append([
                InlineKeyboardButton(
                    text=button.get('text', 'Button'),
                    url=button.get('url', 'https://t.me')
                )
            ])
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard)


class MessageScheduler:
    """Планировщик сообщений для Telegram бота с фоновой обработкой"""
    
    def __init__(self, bot_manager=None):
        self.bot_manager = bot_manager
        self.formatter = MessageFormatter()
        self.keyboard_manager = KeyboardManager()
        self.running = False
        self.scheduler_task: Optional[asyncio.Task] = None
        self.stats = {
            'messages_processed': 0,
            'messages_sent_success': 0,
            'messages_sent_failed': 0,
            'media_sent_success': 0,
            'text_sent_success': 0,
            'errors': [],
            'last_run': None
        }
    
    async def start(self):
        """Start message scheduler with background task"""
        self.running = True
        # ✅ ИСПРАВЛЕНО: Запускаем фоновую задачу для обработки сообщений
        self.scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info("Message scheduler started with background processing")

    async def stop(self):
        """Stop message scheduler"""
        self.running = False
        if self.scheduler_task:
            self.scheduler_task.cancel()
            try:
                await self.scheduler_task
            except asyncio.CancelledError:
                pass
        logger.info("Message scheduler stopped")
    
    async def _scheduler_loop(self):
        """✅ НОВОЕ: Основной цикл планировщика - работает каждые 30 секунд"""
        while self.running:
            try:
                logger.info("🔄 Starting scheduled messages check...")
                stats = await self.process_scheduled_messages()
                self.stats['last_run'] = datetime.now()
                
                if stats['messages_processed'] > 0:
                    logger.info(f"✅ Processed {stats['messages_processed']} messages, "
                              f"sent: {stats['messages_sent_success']}, "
                              f"failed: {stats['messages_sent_failed']}")
                else:
                    logger.debug("📭 No messages to process")
                
                # Ждем 30 секунд до следующей проверки
                await asyncio.sleep(30)
                
            except asyncio.CancelledError:
                logger.info("🛑 Scheduler loop cancelled")
                break
            except Exception as e:
                logger.error(f"❌ Error in scheduler loop: {e}")
                # При ошибке ждем минуту перед повторной попыткой
                await asyncio.sleep(60)

    def get_scheduler_stats(self) -> Dict[str, Any]:
        """Get scheduler statistics"""
        return {
            'running': self.running,
            'scheduler_task_running': self.scheduler_task is not None and not self.scheduler_task.done(),
            **self.stats
        }
    
    async def process_scheduled_messages(self) -> Dict[str, int]:
        """Обработка всех запланированных сообщений"""
        logger.debug("🔄 STARTING SCHEDULED MESSAGES PROCESSING")
        
        # Сброс текущей статистики
        current_stats = {
            'messages_processed': 0,
            'messages_sent_success': 0,
            'messages_sent_failed': 0,
            'media_sent_success': 0,
            'text_sent_success': 0,
            'errors': []
        }
        
        try:
            # ✅ ИСПРАВЛЕНО: Получаем реальные сообщения из БД
            scheduled_messages = await self._get_pending_messages()
            
            if not scheduled_messages:
                logger.debug("📭 NO SCHEDULED MESSAGES TO SEND")
                return current_stats
            
            logger.info(f"📬 FOUND SCHEDULED MESSAGES: {len(scheduled_messages)}")
            
            # Обрабатываем каждое сообщение
            for scheduled_msg in scheduled_messages:
                try:
                    await self._process_single_message(scheduled_msg, current_stats)
                    # Небольшая задержка между отправками для соблюдения лимитов Telegram
                    await asyncio.sleep(0.1)
                except Exception as e:
                    logger.error(f"❌ ERROR PROCESSING SINGLE MESSAGE {scheduled_msg.id}: {e}")
                    current_stats['messages_sent_failed'] += 1
                    current_stats['errors'].append(f"Message {scheduled_msg.id}: {str(e)}")
                
        except Exception as e:
            logger.error(f"❌ ERROR IN SCHEDULED MESSAGES PROCESSING: {e}")
            current_stats['errors'].append(f"Processing error: {str(e)}")
        
        # Обновляем общую статистику
        self.stats['messages_processed'] += current_stats['messages_processed']
        self.stats['messages_sent_success'] += current_stats['messages_sent_success']
        self.stats['messages_sent_failed'] += current_stats['messages_sent_failed']
        self.stats['media_sent_success'] += current_stats['media_sent_success']
        self.stats['text_sent_success'] += current_stats['text_sent_success']
        self.stats['errors'].extend(current_stats['errors'])
        
        # Ограничиваем количество ошибок в памяти
        if len(self.stats['errors']) > 100:
            self.stats['errors'] = self.stats['errors'][-50:]  # Оставляем последние 50
        
        logger.debug("✅ SCHEDULED MESSAGES PROCESSING COMPLETED")
        return current_stats
    
    async def _get_pending_messages(self) -> List:
        """✅ ИСПРАВЛЕНО: Получение сообщений готовых к отправке из БД"""
        try:
            # Получаем pending сообщения из базы данных
            pending_messages = await db.get_pending_scheduled_messages(limit=100)
            
            logger.debug(f"📥 Retrieved {len(pending_messages)} pending messages from DB")
            return pending_messages
            
        except Exception as e:
            logger.error(f"❌ ERROR GETTING PENDING MESSAGES: {e}")
            return []
    
    async def _process_single_message(self, scheduled_msg, current_stats: dict) -> None:
        """Обработка одного запланированного сообщения"""
        try:
            current_stats['messages_processed'] += 1
            
            logger.info(f"📤 PROCESSING SCHEDULED MESSAGE id={scheduled_msg.id}, "
                       f"subscriber={scheduled_msg.subscriber_id}, "
                       f"bot={scheduled_msg.bot_id}")
            
            # Получаем детали сообщения
            message_details = await self._get_message_details(scheduled_msg)
            
            if not message_details:
                logger.error(f"❌ NO MESSAGE DETAILS for message_id={scheduled_msg.message_id}")
                await self._mark_message_failed(scheduled_msg, "No message details")
                current_stats['messages_sent_failed'] += 1
                return
            
            # Отправляем сообщение
            success = await self._send_scheduled_message(scheduled_msg, message_details)
            
            if success:
                await self._mark_message_sent(scheduled_msg)
                current_stats['messages_sent_success'] += 1
                
                # Определяем тип отправленного контента
                if message_details.media_file_id:
                    current_stats['media_sent_success'] += 1
                else:
                    current_stats['text_sent_success'] += 1
                    
                logger.info(f"✅ MESSAGE SENT SUCCESSFULLY id={scheduled_msg.id}")
            else:
                await self._mark_message_failed(scheduled_msg, "Send failed")
                current_stats['messages_sent_failed'] += 1
                
        except Exception as e:
            logger.error(f"❌ ERROR PROCESSING MESSAGE id={scheduled_msg.id}: {e}")
            await self._mark_message_failed(scheduled_msg, str(e))
            current_stats['messages_sent_failed'] += 1
            current_stats['errors'].append(f"Message {scheduled_msg.id}: {str(e)}")
    
    async def _get_message_details(self, scheduled_msg) -> Optional[MessageDetails]:
        """✅ ИСПРАВЛЕНО: Получение деталей сообщения из БД"""
        try:
            # Получаем broadcast message из БД
            broadcast_message = await db.get_broadcast_message_by_id(scheduled_msg.message_id)
            if not broadcast_message:
                logger.error(f"Broadcast message not found: {scheduled_msg.message_id}")
                return None
            
            # Получаем кнопки для сообщения
            buttons = await db.get_message_buttons(scheduled_msg.message_id)
            
            # Форматируем кнопки
            button_data = []
            for button in buttons:
                button_data.append({
                    'text': button.button_text,
                    'url': button.button_url
                })
            
            return MessageDetails(
                text=broadcast_message.message_text,
                media_file_id=getattr(broadcast_message, 'media_file_id', None),
                media_type=broadcast_message.media_type,
                keyboard=button_data if button_data else None
            )
            
        except Exception as e:
            logger.error(f"❌ ERROR GETTING MESSAGE DETAILS for message_id={scheduled_msg.message_id}: {e}")
            return None
    
    async def _send_scheduled_message(self, scheduled_msg, message_details: MessageDetails) -> bool:
        """Отправка запланированного сообщения"""
        try:
            # ✅ ИСПРАВЛЕНО: Получаем бота из bot_manager
            if not self.bot_manager or not hasattr(self.bot_manager, 'active_bots'):
                logger.error("❌ NO BOT MANAGER OR ACTIVE BOTS")
                return False
            
            # Находим подходящего бота
            bot_instance = None
            for bot_id, user_bot in self.bot_manager.active_bots.items():
                if bot_id == scheduled_msg.bot_id:
                    bot_instance = user_bot.bot
                    break
            
            if not bot_instance:
                logger.error(f"❌ BOT NOT FOUND for bot_id={scheduled_msg.bot_id}")
                return False
            
            # ✅ ИСПРАВЛЕНО: Получаем информацию о подписчике для форматирования
            subscriber = await db.get_subscriber_by_bot_and_user(
                scheduled_msg.bot_id, 
                scheduled_msg.subscriber_id
            )
            first_name = getattr(subscriber, 'first_name', None) if subscriber else None
            username = getattr(subscriber, 'username', None) if subscriber else None
            
            # Форматируем текст сообщения
            formatted_text = self.formatter.format_message(
                message_details.text,
                user_id=scheduled_msg.subscriber_id,
                first_name=first_name,
                username=username
            )
            
            # Подготавливаем клавиатуру
            reply_markup = None
            if message_details.keyboard:
                reply_markup = self.keyboard_manager.create_keyboard(message_details.keyboard)
            
            # ✅ ИСПРАВЛЕНО: Проверяем наличие медиа через file_id
            if message_details.media_file_id and message_details.media_type:
                logger.info(f"📁 SENDING WITH MEDIA: {message_details.media_type} to {scheduled_msg.subscriber_id}")
                await self._send_media_message_file_id(
                    bot_instance,
                    scheduled_msg.subscriber_id,
                    formatted_text,
                    message_details.media_file_id,
                    message_details.media_type,
                    reply_markup
                )
            else:
                logger.info(f"💬 SENDING TEXT MESSAGE to {scheduled_msg.subscriber_id}")
                await self._send_text_message(
                    bot_instance,
                    scheduled_msg.subscriber_id,
                    formatted_text,
                    reply_markup
                )
                
            return True
            
        except TelegramForbiddenError:
            logger.warning(f"🚫 USER BLOCKED BOT: {scheduled_msg.subscriber_id}")
            return False
            
        except TelegramBadRequest as e:
            logger.error(f"❌ BAD REQUEST ERROR for user {scheduled_msg.subscriber_id}: {e}")
            return False
            
        except TelegramNetworkError as e:
            logger.error(f"❌ TELEGRAM NETWORK ERROR for user {scheduled_msg.subscriber_id}: {e}")
            return False
            
        except Exception as e:
            logger.error(f"❌ UNEXPECTED ERROR SENDING MESSAGE {scheduled_msg.id}: {e}")
            return False
    
    async def _send_media_message_file_id(
        self, 
        bot: Bot, 
        user_id: int, 
        caption: str, 
        media_file_id: str, 
        media_type: str,
        reply_markup=None
    ):
        """Send media message using file_id"""
        try:
            logger.debug(f"📁 SENDING MEDIA VIA FILE_ID to {user_id}, "
                        f"type: {media_type}, file_id: {media_file_id[:20]}...")
            
            # Нормализуем тип медиа
            media_type_lower = media_type.lower()
            
            if media_type_lower in ['photo', 'image']:
                await bot.send_photo(
                    chat_id=user_id,
                    photo=media_file_id,
                    caption=caption,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
                logger.debug("✅ PHOTO sent via file_id")
                
            elif media_type_lower in ['video']:
                await bot.send_video(
                    chat_id=user_id,
                    video=media_file_id,
                    caption=caption,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
                logger.debug("✅ VIDEO sent via file_id")
                
            elif media_type_lower in ['document']:
                await bot.send_document(
                    chat_id=user_id,
                    document=media_file_id,
                    caption=caption,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
                logger.debug("✅ DOCUMENT sent via file_id")
                
            elif media_type_lower in ['audio']:
                await bot.send_audio(
                    chat_id=user_id,
                    audio=media_file_id,
                    caption=caption,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
                logger.debug("✅ AUDIO sent via file_id")
                
            elif media_type_lower in ['voice']:
                await bot.send_voice(
                    chat_id=user_id,
                    voice=media_file_id,
                    caption=caption,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
                logger.debug("✅ VOICE sent via file_id")
                
            elif media_type_lower in ['video_note']:
                # Для видеокружков caption не поддерживается
                await bot.send_video_note(
                    chat_id=user_id,
                    video_note=media_file_id,
                    reply_markup=reply_markup
                )
                # Если есть caption, отправляем отдельным сообщением
                if caption:
                    await bot.send_message(
                        chat_id=user_id,
                        text=caption,
                        parse_mode=ParseMode.HTML
                    )
                logger.debug("✅ VIDEO_NOTE sent via file_id")
                
            else:
                # Неизвестный тип - пробуем как документ
                logger.warning(f"🤔 UNKNOWN MEDIA TYPE: {media_type}, trying as document")
                await bot.send_document(
                    chat_id=user_id,
                    document=media_file_id,
                    caption=caption,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
                logger.debug("✅ UNKNOWN TYPE sent as document")
                        
        except Exception as e:
            logger.error(f"❌ MEDIA FILE_ID FAILED for {user_id}: {e}")
            # Fallback на текстовое сообщение
            await self._send_text_message(bot, user_id, caption, reply_markup)
    
    async def _send_text_message(
        self, 
        bot: Bot, 
        user_id: int, 
        text: str, 
        reply_markup: Optional[InlineKeyboardMarkup] = None
    ) -> None:
        """Отправка текстового сообщения"""
        try:
            await bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
            logger.debug(f"✅ TEXT MESSAGE SENT to {user_id}")
            
        except Exception as e:
            logger.error(f"❌ TEXT MESSAGE FAILED for {user_id}: {e}")
            raise
    
    async def _mark_message_sent(self, scheduled_msg) -> None:
        """✅ ИСПРАВЛЕНО: Отметка сообщения как отправленного"""
        try:
            await db.update_scheduled_message_status(
                message_id=scheduled_msg.id,
                status='sent'
            )
            logger.debug(f"Message {scheduled_msg.id} marked as sent")
            
        except Exception as e:
            logger.error(f"❌ ERROR MARKING MESSAGE AS SENT {scheduled_msg.id}: {e}")
    
    async def _mark_message_failed(self, scheduled_msg, error: str) -> None:
        """✅ ИСПРАВЛЕНО: Отметка сообщения как неудачного"""
        try:
            await db.update_scheduled_message_status(
                message_id=scheduled_msg.id,
                status='failed',
                error_message=error
            )
            logger.debug(f"Message {scheduled_msg.id} marked as failed: {error}")
            
        except Exception as e:
            logger.error(f"❌ ERROR MARKING MESSAGE AS FAILED {scheduled_msg.id}: {e}")
    
    async def schedule_message(
        self,
        bot_id: str,
        user_id: int,
        message_text: str,
        scheduled_time: datetime,
        media_file_id: Optional[str] = None,
        media_type: Optional[str] = None,
        buttons: Optional[List[Dict[str, str]]] = None
    ) -> bool:
        """Планирование отдельного сообщения для отправки (для будущего использования)"""
        try:
            # Этот метод пока не реализован в БД, но может быть использован в будущем
            # для создания разовых запланированных сообщений вне воронки
            
            logger.info(f"📅 MESSAGE SCHEDULE REQUEST", 
                       bot_id=bot_id,
                       user_id=user_id,
                       scheduled_time=scheduled_time,
                       has_media=bool(media_file_id))
            
            # TODO: Реализовать создание разового запланированного сообщения
            # когда будет необходимо
            
            return True
            
        except Exception as e:
            logger.error(f"❌ ERROR SCHEDULING MESSAGE: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики работы планировщика"""
        return self.stats.copy()
    
    async def get_pending_count(self) -> int:
        """Получить количество ожидающих сообщений"""
        try:
            pending_messages = await db.get_pending_scheduled_messages(limit=1000)
            return len(pending_messages)
        except Exception as e:
            logger.error(f"Error getting pending count: {e}")
            return 0
    
    async def get_status_summary(self) -> Dict[str, Any]:
        """Получить сводку статуса планировщика"""
        return {
            'running': self.running,
            'scheduler_active': self.scheduler_task is not None and not self.scheduler_task.done(),
            'pending_messages': await self.get_pending_count(),
            'total_processed': self.stats['messages_processed'],
            'success_rate': (
                (self.stats['messages_sent_success'] / max(1, self.stats['messages_processed'])) * 100
                if self.stats['messages_processed'] > 0 else 0
            ),
            'last_run': self.stats['last_run'].isoformat() if self.stats['last_run'] else None
        }
