"""
Mass Broadcast Scheduler - processes scheduled broadcasts and deliveries
"""

import asyncio
import structlog
from datetime import datetime
from typing import List

logger = structlog.get_logger()


class MassBroadcastScheduler:
    """Scheduler for mass broadcasts"""
    
    def __init__(self, db, bot_manager):
        """
        ✅ ИСПРАВЛЕНО: Теперь принимаем bot_manager вместо конкретного бота
        """
        self.db = db
        self.bot_manager = bot_manager  # ✅ НОВОЕ: bot_manager для получения нужного бота
        self.is_running = False
    
    async def start(self):
        """Start the scheduler"""
        self.is_running = True
        logger.info("🚀 Mass broadcast scheduler started with bot_manager")
        
        while self.is_running:
            try:
                # Process scheduled broadcasts
                await self.process_scheduled_broadcasts()
                
                # Process pending deliveries
                await self.process_pending_deliveries()
                
                # Wait before next cycle
                await asyncio.sleep(10)  # Check every 10 seconds
                
            except Exception as e:
                logger.error("Error in scheduler loop", error=str(e))
                await asyncio.sleep(30)  # Wait longer on error
    
    async def stop(self):
        """Stop the scheduler"""
        self.is_running = False
        logger.info("⏹️ Mass broadcast scheduler stopped")
    
    async def get_user_bot_for_broadcast(self, bot_id: str):
        """
        ✅ ИСПРАВЛЕНО: Получение правильного пользовательского бота из active_bots
        """
        try:
            # ✅ ИСПРАВЛЕНИЕ: Используем правильный способ - active_bots словарь
            if not hasattr(self.bot_manager, 'active_bots'):
                logger.error("❌ BotManager has no active_bots attribute", bot_id=bot_id)
                return None
            
            if bot_id not in self.bot_manager.active_bots:
                logger.error("❌ UserBot not found in active_bots", 
                           bot_id=bot_id,
                           available_bots=list(self.bot_manager.active_bots.keys()))
                return None
            
            user_bot = self.bot_manager.active_bots[bot_id]
            
            if not user_bot.is_running:
                logger.error("❌ UserBot is not running", bot_id=bot_id)
                return None
            
            if not user_bot.bot:
                logger.error("❌ UserBot has no bot instance", bot_id=bot_id)
                return None
            
            logger.debug("✅ Found running UserBot for broadcast", 
                        bot_id=bot_id,
                        bot_username=user_bot.bot_username)
            return user_bot.bot
            
        except Exception as e:
            logger.error("💥 Error getting UserBot", bot_id=bot_id, error=str(e))
            return None
    
    async def process_scheduled_broadcasts(self):
        """Process scheduled broadcasts that are ready to send"""
        try:
            ready_broadcasts = await self.db.get_scheduled_mass_broadcasts()
            
            for broadcast in ready_broadcasts:
                logger.info("📅 Processing scheduled broadcast", 
                           broadcast_id=broadcast.id,
                           bot_id=broadcast.bot_id,
                           scheduled_at=broadcast.scheduled_at)
                
                # ✅ НОВОЕ: Проверяем что пользовательский бот доступен
                user_bot = await self.get_user_bot_for_broadcast(broadcast.bot_id)
                if not user_bot:
                    logger.error("❌ Cannot process broadcast - UserBot unavailable", 
                               broadcast_id=broadcast.id,
                               bot_id=broadcast.bot_id)
                    continue
                
                success = await self.db.start_mass_broadcast(broadcast.id)
                
                if success:
                    logger.info("✅ Scheduled broadcast started", 
                               broadcast_id=broadcast.id,
                               bot_id=broadcast.bot_id)
                else:
                    logger.error("❌ Failed to start scheduled broadcast", 
                               broadcast_id=broadcast.id,
                               bot_id=broadcast.bot_id)
                    
        except Exception as e:
            logger.error("Failed to process scheduled broadcasts", error=str(e))
    
    async def process_pending_deliveries(self):
        """Process pending deliveries"""
        try:
            deliveries = await self.db.get_pending_mass_deliveries(limit=50)
            
            for delivery, broadcast in deliveries:
                try:
                    await self.send_broadcast_message(delivery, broadcast)
                    
                except Exception as e:
                    logger.error("Failed to send broadcast message", 
                               delivery_id=delivery.id,
                               user_id=delivery.user_id,
                               bot_id=broadcast.bot_id,
                               error=str(e))
                    
                    await self.db.update_mass_delivery_status(
                        delivery.id, 
                        "failed", 
                        error_message=str(e)
                    )
            
            # Check if any broadcasts are completed
            await self.check_completed_broadcasts()
            
        except Exception as e:
            logger.error("Failed to process pending deliveries", error=str(e))
    
    async def send_broadcast_message(self, delivery, broadcast):
        """
        ✅ ИСПРАВЛЕНО: Send single broadcast message using correct UserBot
        """
        try:
            # ✅ НОВОЕ: Получаем правильный пользовательский бот
            telegram_bot = await self.get_user_bot_for_broadcast(broadcast.bot_id)
            if not telegram_bot:
                raise Exception(f"UserBot not available for bot_id: {broadcast.bot_id}")
            
            # delivery.user_id теперь содержит chat_id
            chat_id = delivery.user_id
            
            # Prepare message
            message_text = broadcast.message_text
            
            # Format with user data if needed
            message_text = message_text.replace("{first_name}", "")
            message_text = message_text.replace("{username}", "")
            
            # Prepare keyboard
            keyboard = None
            if broadcast.has_button():
                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text=broadcast.button_text,
                        url=broadcast.button_url
                    )]
                ])
            
            # ✅ ИСПРАВЛЕНО: Используем правильный telegram_bot (пользовательский)
            if broadcast.has_media():
                sent_message = await self.send_media_message(
                    telegram_bot,  # ✅ ПЕРЕДАЕМ правильный бот
                    chat_id,
                    message_text,
                    broadcast.media_file_id,
                    broadcast.media_type,
                    keyboard
                )
            else:
                sent_message = await telegram_bot.send_message(  # ✅ ИСПОЛЬЗУЕМ правильный бот
                    chat_id=chat_id,
                    text=message_text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            
            # Update delivery status
            await self.db.update_mass_delivery_status(
                delivery.id,
                "sent",
                telegram_message_id=sent_message.message_id
            )
            
            logger.debug("✅ Broadcast message sent via UserBot", 
                        delivery_id=delivery.id,
                        user_id=delivery.user_id,
                        chat_id=chat_id,
                        bot_id=broadcast.bot_id,
                        message_id=sent_message.message_id)
            
        except Exception as e:
            # Handle specific Telegram errors
            error_str = str(e).lower()
            
            if "bot was blocked by the user" in error_str:
                status = "blocked"
            elif "chat not found" in error_str:
                status = "blocked"
            elif "user is deactivated" in error_str:
                status = "blocked"
            else:
                status = "failed"
            
            await self.db.update_mass_delivery_status(
                delivery.id,
                status,
                error_message=str(e)
            )
            
            raise e
    
    async def send_media_message(self, telegram_bot, chat_id: int, text: str, file_id: str, media_type: str, keyboard=None):
        """
        ✅ ИСПРАВЛЕНО: Send message with media using specific bot
        """
        try:
            if media_type == "photo":
                return await telegram_bot.send_photo(
                    chat_id=chat_id,
                    photo=file_id,
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            elif media_type == "video":
                return await telegram_bot.send_video(
                    chat_id=chat_id,
                    video=file_id,
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            elif media_type == "document":
                return await telegram_bot.send_document(
                    chat_id=chat_id,
                    document=file_id,
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            elif media_type == "audio":
                return await telegram_bot.send_audio(
                    chat_id=chat_id,
                    audio=file_id,
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            elif media_type == "voice":
                # Voice messages can't have caption, send text separately
                await telegram_bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="HTML"
                )
                return await telegram_bot.send_voice(
                    chat_id=chat_id,
                    voice=file_id,
                    reply_markup=keyboard
                )
            elif media_type == "video_note":
                # Video notes can't have caption, send text separately
                await telegram_bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="HTML"
                )
                return await telegram_bot.send_video_note(
                    chat_id=chat_id,
                    video_note=file_id,
                    reply_markup=keyboard
                )
            else:
                # Fallback to document
                return await telegram_bot.send_document(
                    chat_id=chat_id,
                    document=file_id,
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                
        except Exception as e:
            logger.error("Failed to send media message via UserBot", 
                        chat_id=chat_id,
                        media_type=media_type,
                        error=str(e))
            raise e
    
    async def check_completed_broadcasts(self):
        """Check and mark completed broadcasts"""
        try:
            from database.models import MassBroadcast, BroadcastDelivery
            from sqlalchemy import select, func
            from database.connection import get_db_session
            
            async with get_db_session() as session:
                # Find broadcasts that are sending but have no pending deliveries
                result = await session.execute(
                    select(MassBroadcast.id)
                    .where(MassBroadcast.status == "sending")
                    .where(
                        ~select(BroadcastDelivery.id)
                        .where(
                            BroadcastDelivery.broadcast_id == MassBroadcast.id,
                            BroadcastDelivery.status == "pending"
                        )
                        .exists()
                    )
                )
                
                completed_broadcast_ids = result.scalars().all()
                
                for broadcast_id in completed_broadcast_ids:
                    await self.db.complete_mass_broadcast(broadcast_id)
                    logger.info("✅ Broadcast marked as completed", broadcast_id=broadcast_id)
                    
        except Exception as e:
            logger.error("Failed to check completed broadcasts", error=str(e))
