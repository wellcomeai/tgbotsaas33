"""
Broadcast Manager - handles all broadcast sequences and scheduled messages operations.

Responsibilities:
- Broadcast sequences management
- Broadcast messages with media support
- Message buttons and interactions
- Scheduled messages and delivery tracking
- Funnel automation and subscriber management
"""

from datetime import datetime, timedelta
from typing import Optional, Union, List, Dict, Any
from decimal import Decimal
from sqlalchemy import select, update, delete, func
import structlog

from ..connection import get_db_session

logger = structlog.get_logger()


class BroadcastManager:
    """Manager for broadcast sequences and scheduled messages operations"""
    
    # ===== BROADCAST SEQUENCE MANAGEMENT =====
    
    @staticmethod
    async def create_broadcast_sequence(bot_id: str):
        """Create broadcast sequence for bot"""
        from database.models import BroadcastSequence
        
        async with get_db_session() as session:
            sequence = BroadcastSequence(bot_id=bot_id, is_enabled=True)
            session.add(sequence)
            await session.commit()
            await session.refresh(sequence)
            
            logger.info("✅ Broadcast sequence created", 
                       bot_id=bot_id,
                       sequence_id=sequence.id)
            
            return sequence
    
    @staticmethod
    async def get_broadcast_sequence(bot_id: str):
        """Get broadcast sequence for bot"""
        from database.models import BroadcastSequence
        
        async with get_db_session() as session:
            result = await session.execute(
                select(BroadcastSequence).where(BroadcastSequence.bot_id == bot_id)
            )
            return result.scalar_one_or_none()
    
    @staticmethod
    async def update_broadcast_sequence_status(bot_id: str, enabled: bool):
        """Enable/disable broadcast sequence"""
        from database.models import BroadcastSequence
        
        async with get_db_session() as session:
            await session.execute(
                update(BroadcastSequence)
                .where(BroadcastSequence.bot_id == bot_id)
                .values(is_enabled=enabled, updated_at=datetime.now())
            )
            await session.commit()
            
            logger.info("✅ Broadcast sequence status updated", 
                       bot_id=bot_id,
                       enabled=enabled)
    
    @staticmethod
    async def delete_broadcast_sequence(bot_id: str):
        """Delete broadcast sequence and all related messages"""
        from database.models import BroadcastSequence, BroadcastMessage, MessageButton
        
        async with get_db_session() as session:
            # Get sequence ID first
            sequence_result = await session.execute(
                select(BroadcastSequence.id).where(BroadcastSequence.bot_id == bot_id)
            )
            sequence_id = sequence_result.scalar_one_or_none()
            
            if sequence_id:
                # Delete message buttons first
                await session.execute(
                    delete(MessageButton)
                    .where(MessageButton.message_id.in_(
                        select(BroadcastMessage.id)
                        .where(BroadcastMessage.sequence_id == sequence_id)
                    ))
                )
                
                # Delete broadcast messages
                await session.execute(
                    delete(BroadcastMessage)
                    .where(BroadcastMessage.sequence_id == sequence_id)
                )
                
                # Delete sequence
                await session.execute(
                    delete(BroadcastSequence)
                    .where(BroadcastSequence.bot_id == bot_id)
                )
                
                await session.commit()
                
                logger.info("✅ Broadcast sequence deleted", 
                           bot_id=bot_id,
                           sequence_id=sequence_id)
    
    # ===== BROADCAST MESSAGES MANAGEMENT =====
    
    @staticmethod
    async def create_broadcast_message(
        sequence_id: int,
        message_number: int,
        message_text: str,
        delay_hours: Union[int, float],
        media_url: Optional[str] = None,
        media_type: Optional[str] = None,
        media_file_id: Optional[str] = None,
        media_file_unique_id: Optional[str] = None,
        media_file_size: Optional[int] = None,
        media_filename: Optional[str] = None
    ):
        """Create broadcast message with Decimal conversion handling"""
        from database.models import BroadcastMessage
        
        async with get_db_session() as session:
            # Check for existing message number in sequence
            existing_result = await session.execute(
                select(BroadcastMessage).where(
                    BroadcastMessage.sequence_id == sequence_id,
                    BroadcastMessage.message_number == message_number
                )
            )
            existing_message = existing_result.scalar_one_or_none()
            
            if existing_message:
                logger.warning(
                    "Message number already exists", 
                    sequence_id=sequence_id,
                    message_number=message_number,
                    existing_message_id=existing_message.id
                )
                raise ValueError(f"Message number {message_number} already exists in sequence {sequence_id}")
            
            # Convert delay_hours to Decimal for database storage
            delay_decimal = Decimal(str(delay_hours))
            
            # Create message with new media fields
            message = BroadcastMessage(
                sequence_id=sequence_id,
                message_number=message_number,
                message_text=message_text,
                delay_hours=delay_decimal,
                media_url=media_url,
                media_type=media_type,
                media_file_id=media_file_id,
                media_file_unique_id=media_file_unique_id,
                media_file_size=media_file_size,
                media_filename=media_filename
            )
            session.add(message)
            await session.commit()
            await session.refresh(message)
            
            logger.info("✅ Broadcast message created", 
                       message_id=message.id,
                       sequence_id=sequence_id,
                       message_number=message_number,
                       delay_hours_original=delay_hours,
                       delay_hours_stored=float(message.delay_hours),
                       has_media=bool(media_url or media_file_id))
            
            return message
    
    @staticmethod
    async def get_broadcast_messages(sequence_id: int):
        """Get all broadcast messages for sequence"""
        from database.models import BroadcastMessage
        
        async with get_db_session() as session:
            result = await session.execute(
                select(BroadcastMessage)
                .where(BroadcastMessage.sequence_id == sequence_id)
                .order_by(BroadcastMessage.message_number)
            )
            return result.scalars().all()
    
    @staticmethod
    async def get_broadcast_message_by_id(message_id: int):
        """Get broadcast message by ID"""
        from database.models import BroadcastMessage
        
        async with get_db_session() as session:
            result = await session.execute(
                select(BroadcastMessage).where(BroadcastMessage.id == message_id)
            )
            return result.scalar_one_or_none()
    
    @staticmethod
    async def update_broadcast_message(
        message_id: int,
        message_text: Optional[str] = None,
        delay_hours: Optional[Union[int, float]] = None,
        media_url: Optional[str] = None,
        media_type: Optional[str] = None,
        is_active: Optional[bool] = None,
        utm_campaign: Optional[str] = None,
        utm_content: Optional[str] = None,
        media_file_id: Optional[str] = None,
        media_file_unique_id: Optional[str] = None,
        media_file_size: Optional[int] = None,
        media_filename: Optional[str] = None
    ):
        """Update broadcast message with Decimal conversion"""
        from database.models import BroadcastMessage
        
        async with get_db_session() as session:
            update_data = {}
            
            if message_text is not None:
                update_data["message_text"] = message_text
            if delay_hours is not None:
                # Convert to Decimal for database storage
                update_data["delay_hours"] = Decimal(str(delay_hours))
                # Reschedule pending messages with new delay
                await BroadcastManager.reschedule_pending_messages(message_id, float(delay_hours))
            if media_url is not None:
                update_data["media_url"] = media_url
            if media_type is not None:
                update_data["media_type"] = media_type
            if is_active is not None:
                update_data["is_active"] = is_active
            if utm_campaign is not None:
                update_data["utm_campaign"] = utm_campaign
            if utm_content is not None:
                update_data["utm_content"] = utm_content
            if media_file_id is not None:
                update_data["media_file_id"] = media_file_id
            if media_file_unique_id is not None:
                update_data["media_file_unique_id"] = media_file_unique_id
            if media_file_size is not None:
                update_data["media_file_size"] = media_file_size
            if media_filename is not None:
                update_data["media_filename"] = media_filename
            
            if update_data:
                update_data["updated_at"] = datetime.now()
                await session.execute(
                    update(BroadcastMessage)
                    .where(BroadcastMessage.id == message_id)
                    .values(**update_data)
                )
                await session.commit()
                
                logger.info("✅ Broadcast message updated",
                           message_id=message_id,
                           delay_hours_updated=delay_hours is not None,
                           utm_updated=utm_campaign is not None or utm_content is not None,
                           media_updated=any([
                               media_url is not None,
                               media_file_id is not None,
                               media_type is not None
                           ]))
    
    @staticmethod
    async def delete_broadcast_message(message_id: int):
        """Delete broadcast message"""
        from database.models import BroadcastMessage, MessageButton
        
        async with get_db_session() as session:
            # Delete message buttons first
            await session.execute(
                delete(MessageButton).where(MessageButton.message_id == message_id)
            )
            
            # Delete the message
            message = await session.get(BroadcastMessage, message_id)
            if message:
                await session.delete(message)
                await session.commit()
                
                logger.info("✅ Broadcast message deleted", 
                           message_id=message_id)
    
    @staticmethod
    async def reschedule_pending_messages(message_id: int, new_delay_hours: float):
        """Reschedule pending messages when delay changes"""
        from database.models import ScheduledMessage, BroadcastMessage, BotSubscriber
        
        async with get_db_session() as session:
            try:
                # Get all pending messages for this message_id
                result = await session.execute(
                    select(ScheduledMessage, BroadcastMessage)
                    .join(BroadcastMessage, ScheduledMessage.message_id == BroadcastMessage.id)
                    .where(
                        BroadcastMessage.id == message_id,
                        ScheduledMessage.status == 'pending'
                    )
                )
                
                scheduled_messages = result.fetchall()
                
                if not scheduled_messages:
                    logger.info("No pending messages to reschedule", message_id=message_id)
                    return
                
                # Recalculate time for each message
                for scheduled_msg, broadcast_msg in scheduled_messages:
                    # Find when user clicked button (funnel_started_at)
                    subscriber_result = await session.execute(
                        select(BotSubscriber.funnel_started_at)
                        .where(BotSubscriber.user_id == scheduled_msg.subscriber_id)
                        .where(BotSubscriber.bot_id == scheduled_msg.bot_id)
                    )
                    subscriber = subscriber_result.scalar_one_or_none()
                    
                    if subscriber and subscriber:
                        # Recalculate scheduled_at
                        new_scheduled_at = subscriber + timedelta(hours=float(new_delay_hours))
                        
                        # Update record
                        await session.execute(
                            update(ScheduledMessage)
                            .where(ScheduledMessage.id == scheduled_msg.id)
                            .values(scheduled_at=new_scheduled_at)
                        )
                
                await session.commit()
                
                logger.info("✅ Rescheduled pending messages", 
                           message_id=message_id,
                           new_delay_hours=new_delay_hours,
                           affected_messages=len(scheduled_messages))
                
            except Exception as e:
                logger.error("💥 Failed to reschedule pending messages", 
                            message_id=message_id, 
                            error=str(e))
                await session.rollback()
    
    # ===== MESSAGE BUTTONS MANAGEMENT =====
    
    @staticmethod
    async def create_message_button(
        message_id: int,
        button_text: str,
        button_url: str,
        position: int
    ):
        """Create message button"""
        from database.models import MessageButton
        
        async with get_db_session() as session:
            button = MessageButton(
                message_id=message_id,
                button_text=button_text,
                button_url=button_url,
                position=position
            )
            session.add(button)
            await session.commit()
            await session.refresh(button)
            
            logger.info("✅ Message button created", 
                       button_id=button.id,
                       message_id=message_id,
                       position=position)
            
            return button
    
    @staticmethod
    async def get_message_buttons(message_id: int):
        """Get buttons for message"""
        from database.models import MessageButton
        
        async with get_db_session() as session:
            result = await session.execute(
                select(MessageButton)
                .where(MessageButton.message_id == message_id)
                .order_by(MessageButton.position)
            )
            return result.scalars().all()
    
    @staticmethod
    async def update_message_button(
        button_id: int,
        button_text: Optional[str] = None,
        button_url: Optional[str] = None,
        position: Optional[int] = None
    ):
        """Update message button"""
        from database.models import MessageButton
        
        async with get_db_session() as session:
            update_data = {}
            
            if button_text is not None:
                update_data["button_text"] = button_text
            if button_url is not None:
                update_data["button_url"] = button_url
            if position is not None:
                update_data["position"] = position
            
            if update_data:
                await session.execute(
                    update(MessageButton)
                    .where(MessageButton.id == button_id)
                    .values(**update_data)
                )
                await session.commit()
                
                logger.info("✅ Message button updated", 
                           button_id=button_id,
                           fields_updated=list(update_data.keys()))
    
    @staticmethod
    async def delete_message_button(button_id: int):
        """Delete message button"""
        from database.models import MessageButton
        
        async with get_db_session() as session:
            button = await session.get(MessageButton, button_id)
            if button:
                await session.delete(button)
                await session.commit()
                
                logger.info("✅ Message button deleted", button_id=button_id)
    
    # ===== SCHEDULED MESSAGES MANAGEMENT =====
    
    @staticmethod
    async def schedule_broadcast_messages_for_subscriber(
        bot_id: str,
        subscriber_id: int,
        sequence_id: int
    ):
        """Schedule all broadcast messages for new subscriber with Decimal handling"""
        from database.models import BroadcastMessage, ScheduledMessage
        
        async with get_db_session() as session:
            # Get all active messages in sequence
            result = await session.execute(
                select(BroadcastMessage)
                .where(
                    BroadcastMessage.sequence_id == sequence_id,
                    BroadcastMessage.is_active == True
                )
                .order_by(BroadcastMessage.message_number)
            )
            messages = result.scalars().all()
            
            base_time = datetime.now()
            scheduled_messages = []
            
            for message in messages:
                # Convert Decimal to float for timedelta calculation
                try:
                    delay_hours_float = float(message.delay_hours)
                    scheduled_at = base_time + timedelta(hours=delay_hours_float)
                    
                    scheduled_message = ScheduledMessage(
                        bot_id=bot_id,
                        subscriber_id=subscriber_id,
                        message_id=message.id,
                        scheduled_at=scheduled_at,
                        status='pending'
                    )
                    session.add(scheduled_message)
                    scheduled_messages.append(scheduled_message)
                    
                except (ValueError, TypeError) as e:
                    logger.error("Failed to convert delay_hours",
                               message_id=message.id,
                               delay_hours_value=message.delay_hours,
                               delay_hours_type=type(message.delay_hours),
                               error=str(e))
                    continue  # Skip this message
            
            await session.commit()
            
            logger.info(
                "✅ Broadcast messages scheduled with Decimal conversion", 
                bot_id=bot_id,
                subscriber_id=subscriber_id,
                messages_count=len(scheduled_messages),
                total_messages=len(messages),
                delays=[float(msg.delay_hours) for msg in messages]
            )
            
            return scheduled_messages
    
    @staticmethod
    async def get_pending_scheduled_messages(limit: int = 100):
        """Get pending scheduled messages ready to send"""
        from database.models import ScheduledMessage
        
        async with get_db_session() as session:
            result = await session.execute(
                select(ScheduledMessage)
                .where(
                    ScheduledMessage.status == 'pending',
                    ScheduledMessage.scheduled_at <= datetime.now()
                )
                .order_by(ScheduledMessage.scheduled_at)
                .limit(limit)
            )
            return result.scalars().all()
    
    @staticmethod
    async def update_scheduled_message_status(
        message_id: int,
        status: str,
        error_message: Optional[str] = None
    ):
        """Update scheduled message status"""
        from database.models import ScheduledMessage
        
        async with get_db_session() as session:
            update_data = {
                "status": status,
                "sent_at": datetime.now() if status == 'sent' else None,
                "error_message": error_message
            }
            
            await session.execute(
                update(ScheduledMessage)
                .where(ScheduledMessage.id == message_id)
                .values(**update_data)
            )
            await session.commit()
            
            logger.info("✅ Scheduled message status updated", 
                       message_id=message_id,
                       status=status,
                       has_error=bool(error_message))
    
    @staticmethod
    async def get_scheduled_messages_stats(bot_id: str):
        """Get statistics for scheduled messages"""
        from database.models import ScheduledMessage
        
        async with get_db_session() as session:
            # Count by status
            result = await session.execute(
                select(
                    ScheduledMessage.status,
                    func.count(ScheduledMessage.id).label('count')
                )
                .where(ScheduledMessage.bot_id == bot_id)
                .group_by(ScheduledMessage.status)
            )
            
            stats = {'pending': 0, 'sent': 0, 'failed': 0, 'cancelled': 0}
            for row in result.fetchall():
                stats[row.status] = row.count
            
            return stats
    
    @staticmethod
    async def cancel_scheduled_messages_for_subscriber(bot_id: str, subscriber_id: int):
        """Cancel all pending messages for subscriber"""
        from database.models import ScheduledMessage
        
        async with get_db_session() as session:
            result = await session.execute(
                update(ScheduledMessage)
                .where(
                    ScheduledMessage.bot_id == bot_id,
                    ScheduledMessage.subscriber_id == subscriber_id,
                    ScheduledMessage.status == 'pending'
                )
                .values(
                    status='cancelled',
                    updated_at=datetime.now()
                )
            )
            await session.commit()
            
            cancelled_count = result.rowcount
            
            logger.info("✅ Scheduled messages cancelled for subscriber", 
                       bot_id=bot_id,
                       subscriber_id=subscriber_id,
                       cancelled_count=cancelled_count)
            
            return cancelled_count
    
    # ===== BROADCAST ANALYTICS =====
    
    @staticmethod
    async def get_broadcast_analytics(bot_id: str, days: int = 30) -> Dict[str, Any]:
        """Get comprehensive broadcast analytics"""
        from database.models import (
            BroadcastSequence, BroadcastMessage, ScheduledMessage, 
            BotSubscriber, MessageButton
        )
        
        start_date = datetime.now() - timedelta(days=days)
        
        async with get_db_session() as session:
            # Get sequence info
            sequence_result = await session.execute(
                select(BroadcastSequence).where(BroadcastSequence.bot_id == bot_id)
            )
            sequence = sequence_result.scalar_one_or_none()
            
            if not sequence:
                return {'error': 'No broadcast sequence found'}
            
            # Messages count
            messages_result = await session.execute(
                select(func.count(BroadcastMessage.id))
                .where(BroadcastMessage.sequence_id == sequence.id)
            )
            messages_count = messages_result.scalar() or 0
            
            # Active messages count
            active_messages_result = await session.execute(
                select(func.count(BroadcastMessage.id))
                .where(
                    BroadcastMessage.sequence_id == sequence.id,
                    BroadcastMessage.is_active == True
                )
            )
            active_messages_count = active_messages_result.scalar() or 0
            
            # Scheduled messages stats
            scheduled_stats_result = await session.execute(
                select(
                    ScheduledMessage.status,
                    func.count(ScheduledMessage.id).label('count')
                ).where(
                    ScheduledMessage.bot_id == bot_id,
                    ScheduledMessage.created_at >= start_date
                )
                .group_by(ScheduledMessage.status)
            )
            scheduled_stats = {row.status: row.count for row in scheduled_stats_result.fetchall()}
            
            # Subscribers with funnel enabled
            funnel_subscribers_result = await session.execute(
                select(func.count(BotSubscriber.id))
                .where(
                    BotSubscriber.bot_id == bot_id,
                    BotSubscriber.funnel_enabled == True
                )
            )
            funnel_subscribers = funnel_subscribers_result.scalar() or 0
            
            # Messages with buttons
            messages_with_buttons_result = await session.execute(
                select(func.count(func.distinct(MessageButton.message_id)))
                .join(BroadcastMessage, MessageButton.message_id == BroadcastMessage.id)
                .where(BroadcastMessage.sequence_id == sequence.id)
            )
            messages_with_buttons = messages_with_buttons_result.scalar() or 0
            
            return {
                'sequence_info': {
                    'id': sequence.id,
                    'enabled': sequence.is_enabled,
                    'created_at': sequence.created_at,
                    'updated_at': sequence.updated_at
                },
                'messages': {
                    'total': messages_count,
                    'active': active_messages_count,
                    'with_buttons': messages_with_buttons,
                    'inactive': messages_count - active_messages_count
                },
                'scheduled_messages_30d': {
                    'pending': scheduled_stats.get('pending', 0),
                    'sent': scheduled_stats.get('sent', 0),
                    'failed': scheduled_stats.get('failed', 0),
                    'cancelled': scheduled_stats.get('cancelled', 0),
                    'total': sum(scheduled_stats.values())
                },
                'subscribers': {
                    'funnel_enabled': funnel_subscribers
                },
                'performance': {
                    'delivery_rate': round(
                        (scheduled_stats.get('sent', 0) / max(sum(scheduled_stats.values()), 1)) * 100,
                        2
                    ),
                    'failure_rate': round(
                        (scheduled_stats.get('failed', 0) / max(sum(scheduled_stats.values()), 1)) * 100,
                        2
                    )
                }
            }
    
    @staticmethod
    async def get_message_performance_stats(message_id: int) -> Dict[str, Any]:
        """Get performance statistics for specific message"""
        from database.models import ScheduledMessage, BroadcastMessage
        
        async with get_db_session() as session:
            # Get message info
            message_result = await session.execute(
                select(BroadcastMessage).where(BroadcastMessage.id == message_id)
            )
            message = message_result.scalar_one_or_none()
            
            if not message:
                return {'error': 'Message not found'}
            
            # Get delivery stats
            delivery_stats_result = await session.execute(
                select(
                    ScheduledMessage.status,
                    func.count(ScheduledMessage.id).label('count')
                ).where(ScheduledMessage.message_id == message_id)
                .group_by(ScheduledMessage.status)
            )
            delivery_stats = {row.status: row.count for row in delivery_stats_result.fetchall()}
            
            # Get timing stats
            timing_stats_result = await session.execute(
                select(
                    func.avg(
                        func.extract('epoch', ScheduledMessage.sent_at - ScheduledMessage.scheduled_at)
                    ).label('avg_delay_seconds'),
                    func.min(ScheduledMessage.sent_at).label('first_sent'),
                    func.max(ScheduledMessage.sent_at).label('last_sent')
                ).where(
                    ScheduledMessage.message_id == message_id,
                    ScheduledMessage.status == 'sent'
                )
            )
            timing_stats = timing_stats_result.first()
            
            total_scheduled = sum(delivery_stats.values())
            
            return {
                'message_info': {
                    'id': message.id,
                    'message_number': message.message_number,
                    'delay_hours': float(message.delay_hours),
                    'is_active': message.is_active,
                    'has_media': bool(message.media_url or message.media_file_id)
                },
                'delivery_stats': delivery_stats,
                'performance': {
                    'total_scheduled': total_scheduled,
                    'delivery_rate': round(
                        (delivery_stats.get('sent', 0) / max(total_scheduled, 1)) * 100,
                        2
                    ),
                    'failure_rate': round(
                        (delivery_stats.get('failed', 0) / max(total_scheduled, 1)) * 100,
                        2
                    ),
                    'pending_rate': round(
                        (delivery_stats.get('pending', 0) / max(total_scheduled, 1)) * 100,
                        2
                    )
                },
                'timing': {
                    'avg_delay_seconds': float(timing_stats.avg_delay_seconds or 0),
                    'first_sent': timing_stats.first_sent,
                    'last_sent': timing_stats.last_sent
                }
            }
    
    # ===== BROADCAST MAINTENANCE =====
    
    @staticmethod
    async def cleanup_old_scheduled_messages(days: int = 30) -> int:
        """Clean up old scheduled messages"""
        from database.models import ScheduledMessage
        
        cutoff_date = datetime.now() - timedelta(days=days)
        
        async with get_db_session() as session:
            # Count messages to be deleted
            count_result = await session.execute(
                select(func.count(ScheduledMessage.id))
                .where(
                    ScheduledMessage.status.in_(['sent', 'failed', 'cancelled']),
                    ScheduledMessage.updated_at < cutoff_date
                )
            )
            count = count_result.scalar() or 0
            
            if count > 0:
                # Delete old messages
                await session.execute(
                    delete(ScheduledMessage)
                    .where(
                        ScheduledMessage.status.in_(['sent', 'failed', 'cancelled']),
                        ScheduledMessage.updated_at < cutoff_date
                    )
                )
                await session.commit()
                
                logger.info("🧹 Old scheduled messages cleaned up", 
                           days=days,
                           deleted_count=count)
            
            return count
    
    @staticmethod
    async def get_broadcast_summary() -> Dict[str, Any]:
        """Get overall broadcast system summary"""
        from database.models import (
            BroadcastSequence, BroadcastMessage, ScheduledMessage, MessageButton
        )
        
        async with get_db_session() as session:
            # Sequences stats
            sequences_result = await session.execute(
                select(
                    func.count(BroadcastSequence.id).label('total'),
                    func.sum(func.cast(BroadcastSequence.is_enabled, func.Integer)).label('enabled')
                )
            )
            sequences_stats = sequences_result.first()
            
            # Messages stats
            messages_result = await session.execute(
                select(
                    func.count(BroadcastMessage.id).label('total'),
                    func.sum(func.cast(BroadcastMessage.is_active, func.Integer)).label('active')
                )
            )
            messages_stats = messages_result.first()
            
            # Scheduled messages stats (last 30 days)
            thirty_days_ago = datetime.now() - timedelta(days=30)
            scheduled_result = await session.execute(
                select(
                    ScheduledMessage.status,
                    func.count(ScheduledMessage.id).label('count')
                ).where(ScheduledMessage.created_at >= thirty_days_ago)
                .group_by(ScheduledMessage.status)
            )
            scheduled_stats = {row.status: row.count for row in scheduled_result.fetchall()}
            
            # Buttons stats
            buttons_result = await session.execute(
                select(func.count(MessageButton.id))
            )
            buttons_count = buttons_result.scalar() or 0
            
            return {
                'sequences': {
                    'total': sequences_stats.total or 0,
                    'enabled': sequences_stats.enabled or 0,
                    'disabled': (sequences_stats.total or 0) - (sequences_stats.enabled or 0)
                },
                'messages': {
                    'total': messages_stats.total or 0,
                    'active': messages_stats.active or 0,
                    'inactive': (messages_stats.total or 0) - (messages_stats.active or 0),
                    'total_buttons': buttons_count
                },
                'scheduled_30d': scheduled_stats,
                'performance_30d': {
                    'total_scheduled': sum(scheduled_stats.values()),
                    'delivery_rate': round(
                        (scheduled_stats.get('sent', 0) / max(sum(scheduled_stats.values()), 1)) * 100,
                        2
                    ),
                    'failure_rate': round(
                        (scheduled_stats.get('failed', 0) / max(sum(scheduled_stats.values()), 1)) * 100,
                        2
                    )
                }
            }
