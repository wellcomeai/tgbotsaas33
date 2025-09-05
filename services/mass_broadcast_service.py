"""
Mass Broadcast Service - handles broadcast creation and management logic
"""

import structlog
from datetime import datetime
from typing import Optional, Dict, Any

logger = structlog.get_logger()


class MassBroadcastService:
    """Service for mass broadcast operations"""
    
    def __init__(self, db):
        self.db = db
    
    async def create_instant_broadcast(
        self,
        bot_id: str,
        admin_user_id: int,
        message_text: str,
        media_info: Dict = None,
        button_info: Dict = None
    ):
        """Create instant broadcast"""
        try:
            kwargs = {
                'title': f'Мгновенная рассылка {datetime.now().strftime("%d.%m.%Y %H:%M")}',
                'broadcast_type': 'instant'
            }
            
            # Add media if provided
            if media_info:
                kwargs.update({
                    'media_file_id': media_info.get('file_id'),
                    'media_file_unique_id': media_info.get('file_unique_id'),
                    'media_file_size': media_info.get('file_size'),
                    'media_filename': media_info.get('filename'),
                    'media_type': media_info.get('media_type')
                })
            
            # Add button if provided
            if button_info:
                kwargs.update({
                    'button_text': button_info.get('text'),
                    'button_url': button_info.get('url')
                })
            
            broadcast = await self.db.create_mass_broadcast(
                bot_id=bot_id,
                created_by=admin_user_id,
                message_text=message_text,
                **kwargs
            )
            
            logger.info("✅ Instant broadcast created", 
                       broadcast_id=broadcast.id,
                       bot_id=bot_id,
                       has_media=bool(media_info),
                       has_button=bool(button_info))
            
            return broadcast
            
        except Exception as e:
            logger.error("Failed to create instant broadcast", error=str(e))
            return None
    
    async def create_scheduled_broadcast(
        self,
        bot_id: str,
        admin_user_id: int,
        message_text: str,
        scheduled_at: datetime,
        media_info: Dict = None,
        button_info: Dict = None
    ):
        """Create scheduled broadcast"""
        try:
            kwargs = {
                'title': f'Запланированная рассылка {scheduled_at.strftime("%d.%m.%Y %H:%M")}',
                'broadcast_type': 'scheduled',
                'scheduled_at': scheduled_at
            }
            
            # Add media if provided
            if media_info:
                kwargs.update({
                    'media_file_id': media_info.get('file_id'),
                    'media_file_unique_id': media_info.get('file_unique_id'),
                    'media_file_size': media_info.get('file_size'),
                    'media_filename': media_info.get('filename'),
                    'media_type': media_info.get('media_type')
                })
            
            # Add button if provided
            if button_info:
                kwargs.update({
                    'button_text': button_info.get('text'),
                    'button_url': button_info.get('url')
                })
            
            broadcast = await self.db.create_mass_broadcast(
                bot_id=bot_id,
                created_by=admin_user_id,
                message_text=message_text,
                **kwargs
            )
            
            logger.info("✅ Scheduled broadcast created", 
                       broadcast_id=broadcast.id,
                       bot_id=bot_id,
                       scheduled_at=scheduled_at,
                       has_media=bool(media_info),
                       has_button=bool(button_info))
            
            return broadcast
            
        except Exception as e:
            logger.error("Failed to create scheduled broadcast", error=str(e))
            return None
    
    async def format_broadcast_for_preview(self, broadcast_id: int, sample_name: str = "Иван") -> Dict[str, Any]:
        """Format broadcast for preview"""
        try:
            broadcast = await self.db.get_mass_broadcast_by_id(broadcast_id)
            if not broadcast:
                return None
            
            # Format message text with sample data
            preview_text = broadcast.message_text
            preview_text = preview_text.replace("{first_name}", sample_name)
            preview_text = preview_text.replace("{username}", f"@{sample_name.lower()}")
            
            return {
                'id': broadcast.id,
                'text': preview_text,
                'has_media': broadcast.has_media(),
                'media_type': broadcast.media_type,
                'media_file_id': broadcast.media_file_id,
                'has_button': broadcast.has_button(),
                'button_text': broadcast.button_text,
                'button_url': broadcast.button_url,
                'type': broadcast.broadcast_type,
                'scheduled_at': broadcast.scheduled_at,
                'status': broadcast.status
            }
            
        except Exception as e:
            logger.error("Failed to format broadcast preview", broadcast_id=broadcast_id, error=str(e))
            return None
    
    async def send_instant_broadcast(self, broadcast_id: int) -> bool:
        """Send instant broadcast"""
        try:
            success = await self.db.start_mass_broadcast(broadcast_id)
            
            if success:
                logger.info("✅ Instant broadcast sending started", broadcast_id=broadcast_id)
            else:
                logger.error("Failed to start instant broadcast", broadcast_id=broadcast_id)
            
            return success
            
        except Exception as e:
            logger.error("Failed to send instant broadcast", broadcast_id=broadcast_id, error=str(e))
            return False
    
    def parse_datetime(self, date_str: str) -> Optional[datetime]:
        """Parse datetime from string format DD.MM.YYYY HH:MM"""
        try:
            return datetime.strptime(date_str, "%d.%m.%Y %H:%M")
        except ValueError:
            try:
                # Try alternative format
                return datetime.strptime(date_str, "%d.%m.%Y %H:%M:%S")
            except ValueError:
                logger.error("Failed to parse datetime", date_str=date_str)
                return None
