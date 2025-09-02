"""
Mass Broadcast Manager - handles all mass broadcast operations.

Responsibilities:
- Mass broadcast creation and management
- Scheduling and delivery tracking
- Statistics and analytics
"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import structlog

from ..connection import get_db_session

logger = structlog.get_logger()


class MassBroadcastManager:
    """Manager for mass broadcast operations"""
    
    # ===== BROADCAST CREATION =====
    
    @staticmethod
    async def create_broadcast(
        bot_id: str,
        created_by: int,
        message_text: str,
        title: str = None,
        broadcast_type: str = "instant",
        scheduled_at: Optional[datetime] = None,
        media_file_id: Optional[str] = None,
        media_file_unique_id: Optional[str] = None,
        media_file_size: Optional[int] = None,
        media_filename: Optional[str] = None,
        media_type: Optional[str] = None,
        button_text: Optional[str] = None,
        button_url: Optional[str] = None
    ):
        """Create new mass broadcast"""
        from database.models import MassBroadcast
        
        async with get_db_session() as session:
            broadcast = MassBroadcast(
                bot_id=bot_id,
                created_by=created_by,
                message_text=message_text,
                title=title,
                broadcast_type=broadcast_type,
                scheduled_at=scheduled_at,
                media_file_id=media_file_id,
                media_file_unique_id=media_file_unique_id,
                media_file_size=media_file_size,
                media_filename=media_filename,
                media_type=media_type,
                button_text=button_text,
                button_url=button_url,
                status="draft"
            )
            
            session.add(broadcast)
            await session.commit()
            await session.refresh(broadcast)
            
            logger.info("✅ Mass broadcast created", 
                       broadcast_id=broadcast.id,
                       bot_id=bot_id,
                       type=broadcast_type,
                       has_media=bool(media_file_id),
                       has_button=bool(button_text))
            
            return broadcast
    
    @staticmethod
    async def get_broadcast_by_id(broadcast_id: int):
        """Get broadcast by ID"""
        from database.models import MassBroadcast
        from sqlalchemy import select
        
        async with get_db_session() as session:
            result = await session.execute(
                select(MassBroadcast).where(MassBroadcast.id == broadcast_id)
            )
            return result.scalar_one_or_none()
    
    @staticmethod
    async def update_broadcast(
        broadcast_id: int,
        message_text: Optional[str] = None,
        title: Optional[str] = None,
        media_file_id: Optional[str] = None,
        media_file_unique_id: Optional[str] = None,
        media_file_size: Optional[int] = None,
        media_filename: Optional[str] = None,
        media_type: Optional[str] = None,
        button_text: Optional[str] = None,
        button_url: Optional[str] = None,
        scheduled_at: Optional[datetime] = None
    ) -> bool:
        """Update broadcast"""
        from database.models import MassBroadcast
        from sqlalchemy import update
        
        async with get_db_session() as session:
            update_data = {}
            
            if message_text is not None:
                update_data["message_text"] = message_text
            if title is not None:
                update_data["title"] = title
            if media_file_id is not None:
                update_data["media_file_id"] = media_file_id
            if media_file_unique_id is not None:
                update_data["media_file_unique_id"] = media_file_unique_id
            if media_file_size is not None:
                update_data["media_file_size"] = media_file_size
            if media_filename is not None:
                update_data["media_filename"] = media_filename
            if media_type is not None:
                update_data["media_type"] = media_type
            if button_text is not None:
                update_data["button_text"] = button_text
            if button_url is not None:
                update_data["button_url"] = button_url
            if scheduled_at is not None:
                update_data["scheduled_at"] = scheduled_at
            
            if update_data:
                update_data["updated_at"] = datetime.now()
                
                await session.execute(
                    update(MassBroadcast)
                    .where(MassBroadcast.id == broadcast_id)
                    .values(**update_data)
                )
                await session.commit()
                
                logger.info("✅ Broadcast updated", 
                           broadcast_id=broadcast_id,
                           fields_updated=list(update_data.keys()))
                return True
            
            return False
    
    @staticmethod
    async def delete_broadcast(broadcast_id: int) -> bool:
        """Delete broadcast"""
        from database.models import MassBroadcast
        
        async with get_db_session() as session:
            broadcast = await session.get(MassBroadcast, broadcast_id)
            if broadcast and broadcast.status == "draft":
                await session.delete(broadcast)
                await session.commit()
                
                logger.info("✅ Broadcast deleted", broadcast_id=broadcast_id)
                return True
            
            return False
    
    # ===== BROADCAST LISTS =====
    
    @staticmethod
    async def get_bot_broadcasts(bot_id: str, limit: int = 50):
        """Get all broadcasts for bot"""
        from database.models import MassBroadcast
        from sqlalchemy import select, desc
        
        async with get_db_session() as session:
            result = await session.execute(
                select(MassBroadcast)
                .where(MassBroadcast.bot_id == bot_id)
                .order_by(desc(MassBroadcast.created_at))
                .limit(limit)
            )
            return result.scalars().all()
    
    @staticmethod
    async def get_scheduled_broadcasts(bot_id: str = None):
        """Get scheduled broadcasts ready to send"""
        from database.models import MassBroadcast
        from sqlalchemy import select
        
        async with get_db_session() as session:
            query = select(MassBroadcast).where(
                MassBroadcast.broadcast_type == "scheduled",
                MassBroadcast.status == "draft",
                MassBroadcast.scheduled_at <= datetime.now()
            )
            
            if bot_id:
                query = query.where(MassBroadcast.bot_id == bot_id)
            
            result = await session.execute(query)
            return result.scalars().all()
    
    @staticmethod
    async def get_pending_scheduled_broadcasts(bot_id: str = None):
        """Get pending scheduled broadcasts"""
        from database.models import MassBroadcast
        from sqlalchemy import select, asc
        
        async with get_db_session() as session:
            query = select(MassBroadcast).where(
                MassBroadcast.broadcast_type == "scheduled",
                MassBroadcast.status == "draft",
                MassBroadcast.scheduled_at > datetime.now()
            ).order_by(asc(MassBroadcast.scheduled_at))
            
            if bot_id:
                query = query.where(MassBroadcast.bot_id == bot_id)
            
            result = await session.execute(query)
            return result.scalars().all()
    
    # ===== BROADCAST SENDING =====
    
    @staticmethod
    async def start_broadcast(broadcast_id: int) -> bool:
        """Start broadcast sending"""
        from database.models import MassBroadcast, BotSubscriber, BroadcastDelivery
        from sqlalchemy import update, select
        
        async with get_db_session() as session:
            # Get broadcast
            broadcast = await session.get(MassBroadcast, broadcast_id)
            if not broadcast or not broadcast.is_ready_to_send():
                return False
            
            # Get all active subscribers - изменено на chat_id
            result = await session.execute(
                select(BotSubscriber.chat_id)
                .where(
                    BotSubscriber.bot_id == broadcast.bot_id,
                    BotSubscriber.is_active == True,
                    BotSubscriber.is_banned == False,
                    BotSubscriber.chat_id.is_not(None)  # Только с chat_id
                )
            )
            subscribers = result.scalars().all()
            
            # Create delivery records
            deliveries = []
            for chat_id in subscribers:  # Теперь это chat_id
                delivery = BroadcastDelivery(
                    broadcast_id=broadcast_id,
                    bot_id=broadcast.bot_id,
                    user_id=chat_id,  # Сохраняем chat_id как user_id в delivery
                    status="pending"
                )
                deliveries.append(delivery)
            
            session.add_all(deliveries)
            
            # Update broadcast status
            await session.execute(
                update(MassBroadcast)
                .where(MassBroadcast.id == broadcast_id)
                .values(
                    status="sending",
                    total_recipients=len(subscribers),
                    started_at=datetime.now()
                )
            )
            
            await session.commit()
            
            logger.info("✅ Broadcast started", 
                       broadcast_id=broadcast_id,
                       total_recipients=len(subscribers))
            
            return True
    
    @staticmethod
    async def get_pending_deliveries(limit: int = 100):
        """Get pending deliveries for processing"""
        from database.models import BroadcastDelivery, MassBroadcast
        from sqlalchemy import select
        
        async with get_db_session() as session:
            result = await session.execute(
                select(BroadcastDelivery, MassBroadcast)
                .join(MassBroadcast, BroadcastDelivery.broadcast_id == MassBroadcast.id)
                .where(
                    BroadcastDelivery.status == "pending",
                    MassBroadcast.status == "sending"
                )
                .limit(limit)
            )
            return result.fetchall()
    
    @staticmethod
    async def update_delivery_status(
        delivery_id: int,
        status: str,
        telegram_message_id: int = None,
        error_message: str = None
    ):
        """Update delivery status"""
        from database.models import BroadcastDelivery
        from sqlalchemy import update
        
        async with get_db_session() as session:
            update_data = {
                "status": status,
                "updated_at": datetime.now()
            }
            
            if status == "sent":
                update_data["sent_at"] = datetime.now()
                if telegram_message_id:
                    update_data["telegram_message_id"] = telegram_message_id
            elif status == "delivered":
                update_data["delivered_at"] = datetime.now()
            elif status == "failed":
                update_data["error_message"] = error_message
            
            await session.execute(
                update(BroadcastDelivery)
                .where(BroadcastDelivery.id == delivery_id)
                .values(**update_data)
            )
            await session.commit()
    
    @staticmethod
    async def complete_broadcast(broadcast_id: int):
        """Mark broadcast as completed and update stats"""
        from database.models import MassBroadcast, BroadcastDelivery
        from sqlalchemy import update, select, func
        
        async with get_db_session() as session:
            # Get delivery stats
            result = await session.execute(
                select(
                    BroadcastDelivery.status,
                    func.count(BroadcastDelivery.id).label('count')
                )
                .where(BroadcastDelivery.broadcast_id == broadcast_id)
                .group_by(BroadcastDelivery.status)
            )
            
            stats = {row.status: row.count for row in result.fetchall()}
            
            # Update broadcast
            await session.execute(
                update(MassBroadcast)
                .where(MassBroadcast.id == broadcast_id)
                .values(
                    status="completed",
                    sent_count=stats.get("sent", 0) + stats.get("delivered", 0),
                    failed_count=stats.get("failed", 0),
                    completed_at=datetime.now()
                )
            )
            
            await session.commit()
            
            logger.info("✅ Broadcast completed", 
                       broadcast_id=broadcast_id,
                       sent=stats.get("sent", 0),
                       failed=stats.get("failed", 0))
    
    # ===== STATISTICS =====
    
    @staticmethod
    async def get_broadcast_stats(bot_id: str, days: int = 30) -> Dict[str, Any]:
        """Get broadcast statistics"""
        from database.models import MassBroadcast, BroadcastDelivery
        from sqlalchemy import select, func
        
        start_date = datetime.now() - timedelta(days=days)
        
        async with get_db_session() as session:
            # Total broadcasts
            total_result = await session.execute(
                select(func.count(MassBroadcast.id))
                .where(
                    MassBroadcast.bot_id == bot_id,
                    MassBroadcast.created_at >= start_date
                )
            )
            total_broadcasts = total_result.scalar() or 0
            
            # By status
            status_result = await session.execute(
                select(
                    MassBroadcast.status,
                    func.count(MassBroadcast.id).label('count')
                )
                .where(
                    MassBroadcast.bot_id == bot_id,
                    MassBroadcast.created_at >= start_date
                )
                .group_by(MassBroadcast.status)
            )
            status_stats = {row.status: row.count for row in status_result.fetchall()}
            
            # By type
            type_result = await session.execute(
                select(
                    MassBroadcast.broadcast_type,
                    func.count(MassBroadcast.id).label('count')
                )
                .where(
                    MassBroadcast.bot_id == bot_id,
                    MassBroadcast.created_at >= start_date
                )
                .group_by(MassBroadcast.broadcast_type)
            )
            type_stats = {row.broadcast_type: row.count for row in type_result.fetchall()}
            
            # Total deliveries
            delivery_result = await session.execute(
                select(
                    func.sum(MassBroadcast.total_recipients).label('total_sent'),
                    func.sum(MassBroadcast.sent_count).label('successful'),
                    func.sum(MassBroadcast.failed_count).label('failed')
                )
                .where(
                    MassBroadcast.bot_id == bot_id,
                    MassBroadcast.created_at >= start_date,
                    MassBroadcast.status == "completed"
                )
            )
            delivery_stats = delivery_result.first()
            
            return {
                'period_days': days,
                'total_broadcasts': total_broadcasts,
                'by_status': status_stats,
                'by_type': type_stats,
                'deliveries': {
                    'total_sent': int(delivery_stats.total_sent or 0),
                    'successful': int(delivery_stats.successful or 0),
                    'failed': int(delivery_stats.failed or 0),
                    'success_rate': round(
                        (delivery_stats.successful / max(delivery_stats.total_sent, 1)) * 100,
                        2
                    ) if delivery_stats.total_sent else 0
                }
            }
