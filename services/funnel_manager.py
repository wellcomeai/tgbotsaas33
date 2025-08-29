"""
Funnel Management System for Bot Factory
Handles sales funnel creation, configuration, and management
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Union
import structlog
from urllib.parse import urlencode, urlparse, parse_qs, urlunparse

from config import settings
from database import db

logger = structlog.get_logger()


class FunnelManager:
    """Manager for sales funnel operations"""
    
    def __init__(self):
        self.active_funnels: Dict[str, dict] = {}  # bot_id -> funnel config
    
    async def initialize_bot_funnel(self, bot_id: str) -> bool:
        """Initialize or load funnel configuration for bot"""
        try:
            # Get or create broadcast sequence
            sequence = await db.get_broadcast_sequence(bot_id)
            if not sequence:
                sequence = await db.create_broadcast_sequence(bot_id)
                logger.info("Created new funnel sequence", bot_id=bot_id, sequence_id=sequence.id)
            
            # Load funnel messages - ✅ НЕ создаем автоматически
            messages = await db.get_broadcast_messages(sequence.id)
            
            # Cache funnel config
            self.active_funnels[bot_id] = {
                'sequence_id': sequence.id,
                'is_enabled': sequence.is_enabled,
                'messages': messages,
                'message_count': len(messages)
            }
            
            logger.info("Funnel initialized", 
                       bot_id=bot_id, 
                       sequence_id=sequence.id,
                       messages_count=len(messages),
                       is_enabled=sequence.is_enabled,
                       auto_created_messages=0)  # ✅ Больше не создаем автоматически
            
            return True
            
        except Exception as e:
            logger.error("Failed to initialize funnel", bot_id=bot_id, error=str(e))
            return False
    
    async def start_user_funnel(self, bot_id: str, user_id: int, username: str = None, first_name: str = None) -> bool:
        """Start funnel sequence for new user"""
        try:
            # Check if funnel exists and is enabled
            if bot_id not in self.active_funnels:
                await self.initialize_bot_funnel(bot_id)
            
            funnel_config = self.active_funnels.get(bot_id)
            if not funnel_config or not funnel_config['is_enabled']:
                logger.info("Funnel not enabled", bot_id=bot_id, user_id=user_id)
                return False
            
            if not funnel_config['messages']:
                logger.info("No funnel messages configured", bot_id=bot_id, user_id=user_id)
                return False
            
            # Create or update subscriber record
            await db.create_or_update_subscriber(
                bot_id=bot_id,
                user_id=user_id,
                username=username,
                first_name=first_name,
                last_name=None
            )
            
            # Update subscriber broadcast settings
            await db.update_subscriber_broadcast_settings(
                bot_id=bot_id,
                subscriber_id=user_id,
                accepts_broadcasts=True,
                broadcast_started_at=datetime.now(),
                last_broadcast_message=0,
                funnel_enabled=True,
                funnel_started_at=datetime.now()
            )
            
            # Schedule all funnel messages
            scheduled_messages = await db.schedule_broadcast_messages_for_subscriber(
                bot_id=bot_id,
                subscriber_id=user_id,
                sequence_id=funnel_config['sequence_id']
            )
            
            # ✅ NEW: Log funnel start event
            await self._log_funnel_event(
                bot_id=bot_id,
                subscriber_id=user_id,
                event_type='funnel_started',
                additional_data={
                    'username': username,
                    'first_name': first_name,
                    'messages_scheduled': len(scheduled_messages)
                }
            )
            
            logger.info("Funnel started for user", 
                       bot_id=bot_id, 
                       user_id=user_id,
                       username=username,
                       first_name=first_name,
                       messages_scheduled=len(scheduled_messages))
            
            return True
            
        except Exception as e:
            logger.error("Failed to start user funnel", 
                        bot_id=bot_id, 
                        user_id=user_id, 
                        error=str(e))
            return False
    
    # ✅ UPDATED: Создание сообщения без media_url
    async def create_funnel_message(
        self, 
        bot_id: str, 
        message_number: int,
        message_text: str,
        delay_hours: Union[int, float],
        media_type: Optional[str] = None,
        media_file_id: Optional[str] = None,
        media_file_unique_id: Optional[str] = None,
        media_file_size: Optional[int] = None,
        media_filename: Optional[str] = None
    ) -> Optional[int]:
        """Create new funnel message - БЕЗ ОГРАНИЧЕНИЙ на количество"""
        try:
            # Validate inputs
            if not self._validate_message_data(message_text, delay_hours):
                return None
            
            # Get sequence
            if bot_id not in self.active_funnels:
                await self.initialize_bot_funnel(bot_id)
            
            sequence_id = self.active_funnels[bot_id]['sequence_id']
            
            # ✅ UPDATED: Убираем проверку лимита сообщений
            messages = await db.get_broadcast_messages(sequence_id)
            existing_numbers = [msg.message_number for msg in messages]
            
            # Find available message number
            available_number = message_number
            while available_number in existing_numbers:
                available_number += 1
            
            # ✅ УБИРАЕМ ОГРАНИЧЕНИЕ на max_funnel_messages
            
            # Create message with UTM campaign
            utm_campaign = f"funnel_msg_{available_number}"
            utm_content = f"bot_{bot_id}_seq_{sequence_id}"
            
            logger.info("Creating funnel message", 
                       bot_id=bot_id,
                       sequence_id=sequence_id,
                       requested_number=message_number,
                       actual_number=available_number,
                       existing_count=len(existing_numbers))
            
            # ✅ UPDATED: Передаем новые параметры без media_url
            message = await db.create_broadcast_message(
                sequence_id=sequence_id,
                message_number=available_number,
                message_text=message_text,
                delay_hours=delay_hours,
                media_url=None,  # УДАЛЕНО или поставлено None
                media_type=media_type,
                media_file_id=media_file_id,
                media_file_unique_id=media_file_unique_id,
                media_file_size=media_file_size,
                media_filename=media_filename
            )
            
            # Update UTM fields
            await db.update_broadcast_message(
                message_id=message.id,
                utm_campaign=utm_campaign,
                utm_content=utm_content
            )
            
            # Refresh cache
            await self.refresh_funnel_cache(bot_id)
            
            # ✅ NEW: Log creation event
            await self._log_funnel_event(
                bot_id=bot_id,
                message_id=message.id,
                event_type='message_created',
                additional_data={
                    'message_number': available_number,
                    'delay_hours': float(delay_hours),
                    'has_media': bool(media_file_id)
                }
            )
            
            logger.info("Funnel message created successfully", 
                       bot_id=bot_id, 
                       message_id=message.id,
                       message_number=available_number,
                       delay_hours=delay_hours)
            
            return message.id
            
        except Exception as e:
            logger.error("Failed to create funnel message", 
                        bot_id=bot_id, 
                        message_number=message_number,
                        error=str(e),
                        exc_info=True)
            return None
    
    # ✅ UPDATED: Обновление сообщения без media_url
    async def update_funnel_message(
        self,
        message_id: int,
        bot_id: str,
        message_text: Optional[str] = None,
        delay_hours: Optional[Union[int, float]] = None,
        media_type: Optional[str] = None,
        is_active: Optional[bool] = None,
        media_file_id: Optional[str] = None,
        media_file_unique_id: Optional[str] = None, 
        media_file_size: Optional[int] = None,
        media_filename: Optional[str] = None
    ) -> bool:
        """Update existing funnel message"""
        try:
            # Validate data if provided
            if message_text and len(message_text) > settings.max_funnel_message_length:
                logger.warning("Message text too long", message_id=message_id, length=len(message_text))
                return False
            
            if delay_hours is not None and (delay_hours < 0 or delay_hours > 24 * 365):
                logger.warning("Invalid delay hours", message_id=message_id, delay_hours=delay_hours)
                return False
            
            # Get old message for logging
            old_message = await db.get_broadcast_message_by_id(message_id)
            if not old_message:
                logger.error("Message not found", message_id=message_id)
                return False
            
            # ✅ ОБНОВЛЕНО: передаем все новые параметры без media_url
            await db.update_broadcast_message(
                message_id=message_id,
                message_text=message_text,
                delay_hours=delay_hours,
                media_type=media_type,
                is_active=is_active,
                media_file_id=media_file_id,
                media_file_unique_id=media_file_unique_id,
                media_file_size=media_file_size,
                media_filename=media_filename
            )
            
            # ✅ НОВОЕ: Если меняется delay_hours, обновляем pending scheduled_messages
            if delay_hours is not None:
                await db.reschedule_pending_messages(message_id, float(delay_hours))
                logger.info("Rescheduled pending messages", message_id=message_id, new_delay=delay_hours)
            
            # Refresh cache
            await self.refresh_funnel_cache(bot_id)
            
            # Log update event
            await self._log_funnel_event(
                bot_id=bot_id,
                message_id=message_id,
                event_type='message_updated',
                additional_data={
                    'updated_fields': {
                        'text': message_text is not None,
                        'delay': delay_hours is not None,
                        'media': media_type is not None,
                        'active': is_active is not None,
                        'media_file': media_file_id is not None
                    }
                }
            )
            
            logger.info("Funnel message updated with media support", 
                       message_id=message_id, 
                       bot_id=bot_id,
                       has_media_file=media_file_id is not None)
            return True
            
        except Exception as e:
            logger.error("Failed to update funnel message", message_id=message_id, error=str(e))
            return False
    
    # ✅ ПОЛНАЯ РЕАЛИЗАЦИЯ: Удаление сообщения
    async def delete_funnel_message(self, message_id: int, bot_id: str) -> bool:
        """Delete funnel message"""
        try:
            # Get message info for logging
            message = await db.get_broadcast_message_by_id(message_id)
            if not message:
                logger.warning("Message not found for deletion", message_id=message_id)
                return False
            
            # ✅ NEW: Cancel pending scheduled messages for this message
            await self._cancel_scheduled_messages_for_message(message_id)
            
            await db.delete_broadcast_message(message_id)
            
            # Refresh cache
            await self.refresh_funnel_cache(bot_id)
            
            # ✅ NEW: Log deletion event
            await self._log_funnel_event(
                bot_id=bot_id,
                message_id=message_id,
                event_type='message_deleted',
                additional_data={
                    'message_number': message.message_number,
                    'text_preview': message.message_text[:50]
                }
            )
            
            logger.info("Funnel message deleted", message_id=message_id, bot_id=bot_id)
            return True
            
        except Exception as e:
            logger.error("Failed to delete funnel message", message_id=message_id, error=str(e))
            return False
    
    # ✅ NEW: Управление кнопками сообщения
    async def add_message_button(
        self,
        message_id: int,
        button_text: str,
        button_url: str,
        position: Optional[int] = None
    ) -> Optional[int]:
        """Add button to message"""
        try:
            # Get existing buttons to determine position
            buttons = await db.get_message_buttons(message_id)
            
            if len(buttons) >= settings.max_buttons_per_message:
                logger.warning("Too many buttons", message_id=message_id, count=len(buttons))
                return None
            
            if position is None:
                position = len(buttons) + 1
            
            button_id = await db.create_message_button(
                message_id=message_id,
                button_text=button_text,
                button_url=button_url,
                position=position
            )
            
            logger.info("Button added to message", 
                       message_id=message_id, 
                       button_id=button_id,
                       position=position)
            
            return button_id
            
        except Exception as e:
            logger.error("Failed to add message button", message_id=message_id, error=str(e))
            return None
    
    async def update_message_button(
        self,
        button_id: int,
        button_text: Optional[str] = None,
        button_url: Optional[str] = None,
        position: Optional[int] = None
    ) -> bool:
        """Update message button"""
        try:
            await db.update_message_button(
                button_id=button_id,
                button_text=button_text,
                button_url=button_url,
                position=position
            )
            
            logger.info("Message button updated", button_id=button_id)
            return True
            
        except Exception as e:
            logger.error("Failed to update message button", button_id=button_id, error=str(e))
            return False
    
    async def delete_message_button(self, button_id: int) -> bool:
        """Delete message button"""
        try:
            await db.delete_message_button(button_id)
            logger.info("Message button deleted", button_id=button_id)
            return True
            
        except Exception as e:
            logger.error("Failed to delete message button", button_id=button_id, error=str(e))
            return False
    
    # ✅ UPDATED: Полная статистика
    async def get_funnel_stats(self, bot_id: str) -> Dict:
        """Get comprehensive funnel statistics"""
        try:
            if bot_id not in self.active_funnels:
                await self.initialize_bot_funnel(bot_id)
            
            funnel_config = self.active_funnels[bot_id]
            
            # Basic stats
            stats = {
                'is_enabled': funnel_config['is_enabled'],
                'message_count': funnel_config['message_count'],
                'sequence_id': funnel_config['sequence_id'],
                'unlimited_messages': True  # ✅ Показываем что лимитов нет
            }
            
            # ✅ NEW: Detailed statistics from database
            detailed_stats = await self._get_detailed_funnel_stats(bot_id)
            stats.update(detailed_stats)
            
            return stats
            
        except Exception as e:
            logger.error("Failed to get funnel stats", bot_id=bot_id, error=str(e))
            return {'error': str(e)}
    
    # ✅ NEW: Получение детальной статистики
    async def _get_detailed_funnel_stats(self, bot_id: str) -> Dict:
        """Get detailed statistics from database"""
        try:
            from database import get_db_session
            from sqlalchemy import text
            
            async with get_db_session() as session:
                # Общая статистика подписчиков
                result = await session.execute(text("""
                    SELECT 
                        COUNT(*) as total_subscribers,
                        COUNT(CASE WHEN funnel_enabled = true THEN 1 END) as funnel_enabled,
                        COUNT(CASE WHEN funnel_started_at IS NOT NULL THEN 1 END) as funnel_started
                    FROM bot_subscribers 
                    WHERE bot_id = :bot_id AND is_active = true
                """), {'bot_id': bot_id})
                
                subscriber_stats = result.fetchone()
                
                # Статистика запланированных сообщений
                result = await session.execute(text("""
                    SELECT 
                        status,
                        COUNT(*) as count
                    FROM scheduled_messages 
                    WHERE bot_id = :bot_id 
                    GROUP BY status
                """), {'bot_id': bot_id})
                
                scheduled_stats = {row.status: row.count for row in result.fetchall()}
                
                # Статистика событий воронки (с проверкой существования таблицы)
                try:
                    result = await session.execute(text("""
                        SELECT 
                            event_type,
                            COUNT(*) as count,
                            MAX(event_date) as last_event
                        FROM funnel_statistics 
                        WHERE bot_id = :bot_id 
                        GROUP BY event_type
                    """), {'bot_id': bot_id})
                    
                    event_stats = {}
                    for row in result.fetchall():
                        event_stats[row.event_type] = {
                            'count': row.count,
                            'last_event': row.last_event
                        }
                except Exception:
                    # Table might not exist, use empty stats
                    event_stats = {}
                
                return {
                    'total_subscribers': subscriber_stats.total_subscribers if subscriber_stats else 0,
                    'funnel_enabled_users': subscriber_stats.funnel_enabled if subscriber_stats else 0,
                    'funnel_started_users': subscriber_stats.funnel_started if subscriber_stats else 0,
                    'messages_pending': scheduled_stats.get('pending', 0),
                    'messages_sent': scheduled_stats.get('sent', 0),
                    'messages_failed': scheduled_stats.get('failed', 0),
                    'events': event_stats
                }
        
        except Exception as e:
            logger.error("Failed to get detailed stats", bot_id=bot_id, error=str(e))
            return {}
    
    async def toggle_funnel(self, bot_id: str, enabled: bool) -> bool:
        """Enable/disable funnel for bot"""
        try:
            await db.update_broadcast_sequence_status(bot_id, enabled)
            
            # Update cache
            if bot_id in self.active_funnels:
                self.active_funnels[bot_id]['is_enabled'] = enabled
            
            # ✅ NEW: Log toggle event
            await self._log_funnel_event(
                bot_id=bot_id,
                event_type='funnel_toggled',
                additional_data={'enabled': enabled}
            )
            
            logger.info("Funnel toggled", bot_id=bot_id, enabled=enabled)
            return True
            
        except Exception as e:
            logger.error("Failed to toggle funnel", bot_id=bot_id, error=str(e))
            return False
    
    async def refresh_funnel_cache(self, bot_id: str):
        """Refresh cached funnel configuration"""
        try:
            sequence = await db.get_broadcast_sequence(bot_id)
            if sequence:
                messages = await db.get_broadcast_messages(sequence.id)
                
                self.active_funnels[bot_id] = {
                    'sequence_id': sequence.id,
                    'is_enabled': sequence.is_enabled,
                    'messages': messages,
                    'message_count': len(messages)
                }
                
                logger.debug("Funnel cache refreshed", bot_id=bot_id, message_count=len(messages))
            
        except Exception as e:
            logger.error("Failed to refresh funnel cache", bot_id=bot_id, error=str(e))
    
    # ✅ UPDATED: Получение сообщений для отображения без media_url
    async def get_funnel_messages(self, bot_id: str) -> List[Dict]:
        """Get formatted funnel messages for display"""
        try:
            if bot_id not in self.active_funnels:
                await self.initialize_bot_funnel(bot_id)
            
            funnel_config = self.active_funnels[bot_id]
            messages = funnel_config.get('messages', [])
            
            formatted_messages = []
            for message in messages:
                # Get buttons for this message
                buttons = await db.get_message_buttons(message.id)
                
                # Create preview
                preview_text = message.message_text
                if len(preview_text) > settings.max_preview_length:
                    preview_text = preview_text[:settings.max_preview_length] + "..."
                
                # ✅ UPDATED: Изменена проверка медиа
                formatted_messages.append({
                    'id': message.id,
                    'number': message.message_number,
                    'text': preview_text,
                    'full_text': message.message_text,
                    'delay_hours': float(message.delay_hours),
                    'has_media': bool(message.media_file_id),  # ИЗМЕНЕНО
                    'media_url': None,  # Больше не используем URL
                    'media_type': message.media_type,
                    'media_file_id': getattr(message, 'media_file_id', None),
                    'media_file_unique_id': getattr(message, 'media_file_unique_id', None),
                    'media_file_size': getattr(message, 'media_file_size', None),
                    'media_filename': getattr(message, 'media_filename', None),
                    'button_count': len(buttons),
                    'is_active': message.is_active,
                    'buttons': [
                        {
                            'id': btn.id,
                            'text': btn.button_text,
                            'url': btn.button_url,
                            'position': btn.position
                        }
                        for btn in buttons
                    ],
                    'created_at': message.created_at,
                    'updated_at': message.updated_at,
                    'utm_campaign': message.utm_campaign,
                    'utm_content': message.utm_content
                })
            
            # Sort by message number
            formatted_messages.sort(key=lambda x: x['number'])
            return formatted_messages
            
        except Exception as e:
            logger.error("Failed to get funnel messages", bot_id=bot_id, error=str(e))
            return []
    
    # ✅ NEW: Получение превью сообщения
    async def get_message_preview(self, message_id: int, user_first_name: str = "Иван") -> str:
        """Get formatted message preview with sample user data"""
        try:
            message = await db.get_broadcast_message_by_id(message_id)
            if not message:
                return "Сообщение не найдено"
            
            # Format with sample data
            preview = message.message_text
            preview = preview.replace("{first_name}", user_first_name)
            preview = preview.replace("{username}", f"@{user_first_name.lower()}")
            
            return preview
            
        except Exception as e:
            logger.error("Failed to get message preview", message_id=message_id, error=str(e))
            return "Ошибка при генерации превью"
    
    # ✅ НОВЫЕ МЕТОДЫ: Работа с медиа
    async def add_media_to_message(self, message_id: int, media_info: dict) -> bool:
        """Add media to funnel message"""
        try:
            await db.update_broadcast_message(
                message_id=message_id,
                media_file_id=media_info.get('file_id'),
                media_file_unique_id=media_info.get('file_unique_id'),
                media_file_size=media_info.get('file_size'),
                media_type=media_info.get('media_type'),
                media_filename=media_info.get('filename')
            )
            
            logger.info("Media added to message", 
                       message_id=message_id,
                       media_type=media_info.get('media_type'),
                       file_size=media_info.get('file_size'))
            
            return True
            
        except Exception as e:
            logger.error("Failed to add media to message", message_id=message_id, error=str(e))
            return False

    # ✅ UPDATED: Удаление медиа без media_url
    async def remove_media_from_message(self, message_id: int) -> bool:
        """Remove media from funnel message"""
        try:
            await db.update_broadcast_message(
                message_id=message_id,
                media_file_id=None,
                media_file_unique_id=None,
                media_file_size=None,
                media_filename=None,
                media_type=None
            )
            
            logger.info("Media removed from message", message_id=message_id)
            return True
            
        except Exception as e:
            logger.error("Failed to remove media from message", message_id=message_id, error=str(e))
            return False

    # ✅ UPDATED: Получение медиа-информации только для file_id
    async def get_media_info(self, message_id: int) -> dict:
        """Get media information for message"""
        try:
            message = await db.get_broadcast_message_by_id(message_id)
            if not message:
                return {}
            
            # Только file_id способ
            if getattr(message, 'media_file_id', None):
                return {
                    'type': 'file_id',
                    'file_id': message.media_file_id,
                    'file_unique_id': getattr(message, 'media_file_unique_id', None),
                    'file_size': getattr(message, 'media_file_size', None),
                    'media_type': message.media_type,
                    'filename': getattr(message, 'media_filename', None)
                }
            # Старые записи с URL игнорируем (не показываем как медиа)
            
            return {}
            
        except Exception as e:
            logger.error("Failed to get media info", message_id=message_id, error=str(e))
            return {}
    
    # ✅ ИСПРАВЛЕНО: Helper methods с JSON сериализацией
    
    async def _log_funnel_event(
        self,
        bot_id: str,
        event_type: str,
        subscriber_id: Optional[int] = None,
        message_id: Optional[int] = None,
        additional_data: Optional[Dict] = None
    ):
        """Log funnel event to statistics with JSON serialization"""
        try:
            from database import get_db_session
            from sqlalchemy import text
            
            # ✅ ИСПРАВЛЕНИЕ: Конвертируем additional_data в JSON строку
            additional_data_json = json.dumps(additional_data) if additional_data else None
            
            async with get_db_session() as session:
                # Попытка создать запись, если таблица существует
                try:
                    await session.execute(text("""
                        INSERT INTO funnel_statistics 
                        (bot_id, message_id, subscriber_id, event_type, additional_data, event_date)
                        VALUES (:bot_id, :message_id, :subscriber_id, :event_type, :additional_data, :event_date)
                    """), {
                        'bot_id': bot_id,
                        'message_id': message_id,
                        'subscriber_id': subscriber_id,
                        'event_type': event_type,
                        'additional_data': additional_data_json,
                        'event_date': datetime.now()
                    })
                    
                    await session.commit()
                    
                except Exception as table_error:
                    # Таблица funnel_statistics может не существовать
                    logger.debug("Could not log to funnel_statistics table", 
                               error=str(table_error), 
                               bot_id=bot_id, 
                               event_type=event_type)
                    # Не логируем как ошибку, так как это может быть нормальным
                
        except Exception as e:
            logger.error("Failed to log funnel event", bot_id=bot_id, event_type=event_type, error=str(e))
    
    async def _cancel_scheduled_messages_for_message(self, message_id: int):
        """Cancel all pending scheduled messages for a deleted message"""
        try:
            from database import get_db_session
            from sqlalchemy import text
            
            async with get_db_session() as session:
                result = await session.execute(text("""
                    UPDATE scheduled_messages 
                    SET status = 'cancelled'
                    WHERE message_id = :message_id AND status = 'pending'
                """), {'message_id': message_id})
                
                cancelled_count = result.rowcount
                await session.commit()
                
                if cancelled_count > 0:
                    logger.info("Cancelled scheduled messages", 
                               message_id=message_id, 
                               cancelled_count=cancelled_count)
                
        except Exception as e:
            logger.error("Failed to cancel scheduled messages", message_id=message_id, error=str(e))
    
    # ✅ UPDATED: Валидация без media_url
    def _validate_message_data(self, message_text: str, delay_hours: Union[int, float]) -> bool:
        """Validate message data"""
        if not message_text or len(message_text) > settings.max_funnel_message_length:
            return False
        
        if delay_hours < 0 or delay_hours > 24 * 365:  # Max 1 year
            return False
        
        return True
    
    def _is_valid_url(self, url: str) -> bool:
        """Basic URL validation"""
        try:
            parsed = urlparse(url)
            return parsed.scheme in ('http', 'https') and parsed.netloc
        except:
            return False
    
    def add_utm_to_url(self, url: str, user_id: int, username: str = None) -> str:
        """Add UTM parameters to URL"""
        try:
            parsed = urlparse(url)
            query_params = parse_qs(parsed.query)
            
            # Add UTM parameters
            utm_params = {
                'utm_source': 'telegram_bot',
                'utm_medium': 'funnel',
                'utm_content': f'user_{user_id}',
            }
            
            if username:
                utm_params['utm_term'] = username
            
            # Merge with existing params
            query_params.update({k: [v] for k, v in utm_params.items()})
            
            # Reconstruct URL
            new_query = urlencode(query_params, doseq=True)
            new_parsed = parsed._replace(query=new_query)
            
            return urlunparse(new_parsed)
            
        except Exception as e:
            logger.error("Failed to add UTM to URL", url=url, error=str(e))
            return url  # Return original URL if processing fails
    
    # ✅ NEW: Batch operations
    
    # ✅ UPDATED: Дублирование сообщения без media_url
    async def duplicate_message(self, message_id: int, bot_id: str, new_number: Optional[int] = None) -> Optional[int]:
        """Duplicate existing message"""
        try:
            original = await db.get_broadcast_message_by_id(message_id)
            if not original:
                return None
            
            if new_number is None:
                messages = await self.get_funnel_messages(bot_id)
                existing_numbers = [msg['number'] for msg in messages]
                new_number = max(existing_numbers) + 1 if existing_numbers else 1
            
            # Create duplicate with all media fields без media_url
            new_id = await self.create_funnel_message(
                bot_id=bot_id,
                message_number=new_number,
                message_text=original.message_text,
                delay_hours=float(original.delay_hours),
                media_type=original.media_type,
                media_file_id=getattr(original, 'media_file_id', None),
                media_file_unique_id=getattr(original, 'media_file_unique_id', None),
                media_file_size=getattr(original, 'media_file_size', None),
                media_filename=getattr(original, 'media_filename', None)
            )
            
            if new_id:
                # Copy buttons
                buttons = await db.get_message_buttons(message_id)
                for button in buttons:
                    await self.add_message_button(
                        message_id=new_id,
                        button_text=button.button_text,
                        button_url=button.button_url,
                        position=button.position
                    )
                
                logger.info("Message duplicated", 
                           original_id=message_id,
                           new_id=new_id,
                           new_number=new_number)
            
            return new_id
            
        except Exception as e:
            logger.error("Failed to duplicate message", message_id=message_id, error=str(e))
            return None


# Global funnel manager instance
funnel_manager = FunnelManager()
