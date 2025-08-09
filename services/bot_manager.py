import asyncio
from typing import Dict, List, Optional
from datetime import datetime
import structlog

from database import db
from services.user_bot.core import UserBot
from services.message_scheduler import MessageScheduler

logger = structlog.get_logger()


class BotManager:
    """Manager for all user bots with admin panel support"""
    
    def __init__(self):
        self.active_bots: Dict[str, UserBot] = {}  # bot_id -> UserBot instance
        self.bot_configs: Dict[str, dict] = {}     # bot_id -> config cache
        self.sync_task: Optional[asyncio.Task] = None
        self.running = False
        
        # Message Scheduler Integration
        self.message_scheduler: Optional[MessageScheduler] = None
    
    async def start(self):
        """Start bot manager and load all active bots"""
        logger.info("Starting Bot Manager with admin panel support")
        self.running = True
        
        try:
            # Initialize message scheduler
            logger.info("Initializing message scheduler...")
            self.message_scheduler = MessageScheduler(self)
            await self.message_scheduler.start()
            
            # Load all active bots from database
            logger.info("Loading active bots from database...")
            await self._load_active_bots()
            
            # Start periodic sync task
            logger.info("Starting periodic sync task...")
            self.sync_task = asyncio.create_task(self._sync_task())
            
            logger.info("Bot Manager started successfully with admin support", 
                       active_bots=len(self.active_bots),
                       scheduler_running=self.message_scheduler.running if self.message_scheduler else False)
            
        except Exception as e:
            logger.error("Failed to start Bot Manager", error=str(e), exc_info=True)
            raise
    
    async def stop(self):
        """Stop bot manager and all user bots"""
        logger.info("Stopping Bot Manager with admin panels")
        self.running = False
        
        # Stop message scheduler
        if self.message_scheduler:
            logger.info("Stopping message scheduler...")
            await self.message_scheduler.stop()
        
        # Cancel sync task
        if self.sync_task:
            self.sync_task.cancel()
            try:
                await self.sync_task
            except asyncio.CancelledError:
                pass
        
        # Stop all active bots (including their admin panels)
        for bot_id, user_bot in self.active_bots.items():
            try:
                await user_bot.stop()
                logger.info("User bot with admin panel stopped", bot_id=bot_id, bot_username=user_bot.bot_username)
            except Exception as e:
                logger.error("Error stopping user bot", bot_id=bot_id, error=str(e))
        
        self.active_bots.clear()
        self.bot_configs.clear()
        
        logger.info("Bot Manager stopped")
    
    async def _load_active_bots(self):
        """Load all active bots from database"""
        try:
            # Get all active bots
            logger.info("Fetching active bots from database...")
            bots = await db.get_all_active_bots()
            logger.info("Found bots in database", count=len(bots))
            
            if not bots:
                logger.info("No active bots found in database")
                return
            
            for bot_data in bots:
                try:
                    logger.info(
                        "Starting user bot with admin panel", 
                        bot_id=bot_data.bot_id,
                        bot_username=bot_data.bot_username,
                        owner_user_id=bot_data.user_id,
                        is_running=bot_data.is_running,
                        has_welcome_button=bool(bot_data.welcome_button_text),
                        has_confirmation=bool(bot_data.confirmation_message),
                        has_goodbye_button=bool(bot_data.goodbye_button_text)
                    )
                    await self._start_user_bot(bot_data)
                except Exception as e:
                    logger.error(
                        "Failed to start user bot with admin panel", 
                        bot_id=bot_data.bot_id,
                        bot_username=bot_data.bot_username,
                        error=str(e),
                        exc_info=True
                    )
                    # Mark bot as error in database
                    await db.update_bot_status(bot_data.bot_id, "error", False)
            
            logger.info("Active bots with admin panels loading completed", 
                       loaded_count=len(self.active_bots),
                       total_found=len(bots))
            
        except Exception as e:
            logger.error("Failed to load active bots", error=str(e), exc_info=True)
            raise
    
    async def _start_user_bot(self, bot_data):
        """Start individual user bot with admin panel"""
        bot_id = bot_data.bot_id
        
        logger.info("Creating bot config with admin support", bot_id=bot_id, owner_user_id=bot_data.user_id)
        
        # ✅ UPDATED: Create extended bot config with owner info
        config = {
            'bot_id': bot_data.bot_id,
            'token': bot_data.token,
            'bot_username': bot_data.bot_username,
            'bot_name': bot_data.bot_name,
            'user_id': bot_data.user_id,  # ✅ Owner identification
            'welcome_message': bot_data.welcome_message,
            'welcome_button_text': bot_data.welcome_button_text,
            'confirmation_message': bot_data.confirmation_message,
            'goodbye_message': bot_data.goodbye_message,
            'goodbye_button_text': bot_data.goodbye_button_text,
            'goodbye_button_url': bot_data.goodbye_button_url,
            'status': bot_data.status,
            'is_running': bot_data.is_running
        }
        
        # Store config in cache
        self.bot_configs[bot_id] = config
        logger.info("Bot config stored with admin panel support", 
                   bot_id=bot_id,
                   owner_user_id=bot_data.user_id,
                   has_welcome_button=bool(config['welcome_button_text']),
                   has_confirmation=bool(config['confirmation_message']),
                   has_goodbye_button=bool(config['goodbye_button_text']))
        
        # Create and start user bot with admin panel
        logger.info("Creating UserBot instance with admin panel", bot_id=bot_id)
        user_bot = UserBot(config, self)
        
        logger.info("Starting UserBot instance with admin panel", bot_id=bot_id)
        await user_bot.start()
        
        # Store active bot
        self.active_bots[bot_id] = user_bot
        
        logger.info(
            "User bot started successfully with full admin panel", 
            bot_id=bot_id,
            bot_username=bot_data.bot_username,
            owner_user_id=bot_data.user_id,
            has_welcome=bool(bot_data.welcome_message),
            has_welcome_button=bool(bot_data.welcome_button_text),
            has_confirmation=bool(bot_data.confirmation_message),
            has_goodbye=bool(bot_data.goodbye_message),
            has_goodbye_button=bool(bot_data.goodbye_button_text and bot_data.goodbye_button_url)
        )
    
    async def add_bot(self, bot_data):
        """Add new bot to manager with admin panel"""
        bot_id = bot_data.bot_id
        
        # Check if bot already exists
        if bot_id in self.active_bots:
            logger.warning("Bot already exists", bot_id=bot_id)
            return
        
        try:
            await self._start_user_bot(bot_data)
            logger.info("New bot with admin panel added to manager", 
                       bot_id=bot_id, 
                       bot_username=bot_data.bot_username,
                       owner_user_id=bot_data.user_id)
        except Exception as e:
            logger.error("Failed to add new bot with admin panel", bot_id=bot_id, error=str(e))
            raise
    
    async def remove_bot(self, bot_id: str):
        """Remove bot from manager"""
        if bot_id not in self.active_bots:
            logger.warning("Bot not found in active bots", bot_id=bot_id)
            return
        
        try:
            # Stop user bot (including admin panel)
            user_bot = self.active_bots[bot_id]
            bot_username = user_bot.bot_username
            await user_bot.stop()
            
            # Remove from active bots and configs
            del self.active_bots[bot_id]
            del self.bot_configs[bot_id]
            
            logger.info("Bot with admin panel removed from manager", bot_id=bot_id, bot_username=bot_username)
            
        except Exception as e:
            logger.error("Failed to remove bot", bot_id=bot_id, error=str(e))
            raise
    
    async def update_bot_config(self, bot_id: str, **updates):
        """✅ UPDATED: Update bot configuration with admin panel sync"""
        if bot_id not in self.bot_configs:
            logger.warning("Bot config not found", bot_id=bot_id)
            return
        
        # ✅ Log which fields are being updated
        logger.info("Updating bot config via admin panel", 
                   bot_id=bot_id, 
                   updates=list(updates.keys()),
                   has_admin_updates=any(key in updates for key in [
                       'welcome_button_text', 'confirmation_message', 
                       'goodbye_button_text', 'goodbye_button_url',
                       'welcome_message', 'goodbye_message'
                   ]))
        
        # Update config cache
        self.bot_configs[bot_id].update(updates)
        
        # ✅ Update user bot if it's active (real-time config sync)
        if bot_id in self.active_bots:
            user_bot = self.active_bots[bot_id]
            user_bot.update_config(self.bot_configs[bot_id])
            logger.info("Bot admin panel config updated in real-time", 
                       bot_id=bot_id,
                       bot_username=user_bot.bot_username)
        
        logger.info("Bot config updated with admin panel support", 
                   bot_id=bot_id, 
                   updated_fields=list(updates.keys()))
    
    async def _sync_task(self):
        """Periodic sync task with database"""
        while self.running:
            try:
                await asyncio.sleep(30)  # Sync every 30 seconds
                
                if not self.running:
                    break
                
                await self._sync_with_database()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in sync task", error=str(e))
                await asyncio.sleep(10)  # Wait before retry
    
    async def _sync_with_database(self):
        """✅ UPDATED: Sync bot configs with database including admin panel changes"""
        try:
            # Get updated bot configs from database
            updated_bots = await db.get_updated_bots(list(self.bot_configs.keys()))
            
            for bot_data in updated_bots:
                bot_id = bot_data.bot_id
                
                if bot_id in self.bot_configs:
                    # Check if config changed (including admin panel changes)
                    current_config = self.bot_configs[bot_id]
                    
                    # ✅ Compare all admin-configurable fields
                    if (current_config.get('welcome_message') != bot_data.welcome_message or
                        current_config.get('welcome_button_text') != bot_data.welcome_button_text or
                        current_config.get('confirmation_message') != bot_data.confirmation_message or
                        current_config.get('goodbye_message') != bot_data.goodbye_message or
                        current_config.get('goodbye_button_text') != bot_data.goodbye_button_text or
                        current_config.get('goodbye_button_url') != bot_data.goodbye_button_url or
                        current_config.get('status') != bot_data.status or
                        current_config.get('is_running') != bot_data.is_running):
                        
                        # Update config with all fields
                        await self.update_bot_config(
                            bot_id,
                            welcome_message=bot_data.welcome_message,
                            welcome_button_text=bot_data.welcome_button_text,
                            confirmation_message=bot_data.confirmation_message,
                            goodbye_message=bot_data.goodbye_message,
                            goodbye_button_text=bot_data.goodbye_button_text,
                            goodbye_button_url=bot_data.goodbye_button_url,
                            status=bot_data.status,
                            is_running=bot_data.is_running
                        )
                        
                        logger.debug("Bot admin config synced with database", bot_id=bot_id)
            
            # Check for new bots that should be started
            all_active_bots = await db.get_all_active_bots()
            
            for bot_data in all_active_bots:
                if bot_data.bot_id not in self.active_bots and bot_data.is_running:
                    try:
                        await self.add_bot(bot_data)
                        logger.info("New bot with admin panel detected and started", 
                                   bot_id=bot_data.bot_id,
                                   bot_username=bot_data.bot_username)
                    except Exception as e:
                        logger.error("Failed to start new bot", bot_id=bot_data.bot_id, error=str(e))
            
            # Check for bots that should be stopped
            for bot_id in list(self.active_bots.keys()):
                bot_exists = any(b.bot_id == bot_id for b in all_active_bots)
                if not bot_exists:
                    await self.remove_bot(bot_id)
                    logger.info("Removed inactive bot with admin panel", bot_id=bot_id)
                    
        except Exception as e:
            logger.error("Failed to sync with database", error=str(e))
    
    def get_bot_status(self, bot_id: str) -> dict:
        """✅ UPDATED: Get bot status with admin panel stats"""
        if bot_id not in self.active_bots:
            return {"status": "inactive", "running": False}
        
        user_bot = self.active_bots[bot_id]
        config = self.bot_configs.get(bot_id, {})
        
        # ✅ Get extended stats from user bot including admin usage
        detailed_stats = user_bot.get_detailed_stats()
        
        return {
            "status": config.get("status", "unknown"),
            "running": user_bot.is_running,
            "last_activity": getattr(user_bot, 'last_activity', None),
            "error_count": getattr(user_bot, 'error_count', 0),
            "owner_user_id": user_bot.owner_user_id,  # ✅ NEW: Owner info
            "bot_username": user_bot.bot_username,
            "admin_stats": {
                "admin_sessions": detailed_stats.get("admin_sessions", 0),  # ✅ NEW
                "last_admin_activity": detailed_stats.get("bot_info", {}).get("last_activity")
            },
            "message_stats": {
                "welcome_sent": detailed_stats.get("welcome_sent", 0),
                "goodbye_sent": detailed_stats.get("goodbye_sent", 0),
                "confirmation_sent": detailed_stats.get("confirmation_sent", 0),
                "success_rate": detailed_stats.get("success_rate", 0),
                "blocked_rate": detailed_stats.get("blocked_rate", 0)
            },
            "button_stats": {
                "welcome_buttons_sent": detailed_stats.get("welcome_buttons_sent", 0),
                "goodbye_buttons_sent": detailed_stats.get("goodbye_buttons_sent", 0),
                "button_clicks": detailed_stats.get("button_clicks", 0),
                "funnel_starts": detailed_stats.get("funnel_starts", 0)
            },
            "config_status": detailed_stats.get("config", {}),
            "channel_stats": {
                "join_requests_processed": detailed_stats.get("join_requests_processed", 0),
                "admin_adds_processed": detailed_stats.get("admin_adds_processed", 0),
                "user_chat_id_available": detailed_stats.get("user_chat_id_available", 0),
                "user_chat_id_missing": detailed_stats.get("user_chat_id_missing", 0)
            }
        }
    
    def get_all_bot_statuses(self) -> dict:
        """Get status of all bots with admin info"""
        return {
            bot_id: self.get_bot_status(bot_id) 
            for bot_id in self.bot_configs.keys()
        }
    
    async def restart_bot(self, bot_id: str):
        """Restart specific bot with admin panel"""
        if bot_id not in self.active_bots:
            logger.warning("Cannot restart bot - not active", bot_id=bot_id)
            return
        
        try:
            # Get bot data from database
            bot_data = await db.get_bot_by_id(bot_id)
            if not bot_data:
                logger.error("Bot not found in database", bot_id=bot_id)
                return
            
            # Stop current bot (including admin panel)
            await self.remove_bot(bot_id)
            
            # Start fresh bot with admin panel
            await self.add_bot(bot_data)
            
            logger.info("Bot with admin panel restarted successfully", 
                       bot_id=bot_id,
                       bot_username=bot_data.bot_username)
            
        except Exception as e:
            logger.error("Failed to restart bot", bot_id=bot_id, error=str(e))
            raise
    
    def get_bot_detailed_stats(self, bot_id: str) -> dict:
        """Get detailed statistics for a specific bot"""
        if bot_id not in self.active_bots:
            return {"error": "Bot not found or not active"}
        
        user_bot = self.active_bots[bot_id]
        return user_bot.get_detailed_stats()
    
    def get_all_bots_summary(self) -> dict:
        """✅ UPDATED: Get summary statistics for all bots including admin usage"""
        summary = {
            "total_bots": len(self.active_bots),
            "running_bots": sum(1 for bot in self.active_bots.values() if bot.is_running),
            "total_welcome_sent": 0,
            "total_goodbye_sent": 0,
            "total_confirmation_sent": 0,
            "total_button_clicks": 0,
            "total_funnel_starts": 0,
            "total_admin_sessions": 0,  # ✅ NEW
            "bots_with_welcome_buttons": 0,
            "bots_with_goodbye_buttons": 0,
            "bots_with_confirmation": 0,
            "bots_with_admin_activity": 0  # ✅ NEW
        }
        
        for user_bot in self.active_bots.values():
            stats = user_bot.get_message_stats()
            summary["total_welcome_sent"] += stats.get("welcome_sent", 0)
            summary["total_goodbye_sent"] += stats.get("goodbye_sent", 0)
            summary["total_confirmation_sent"] += stats.get("confirmation_sent", 0)
            summary["total_button_clicks"] += stats.get("button_clicks", 0)
            summary["total_funnel_starts"] += stats.get("funnel_starts", 0)
            summary["total_admin_sessions"] += stats.get("admin_sessions", 0)  # ✅ NEW
            
            # Configuration status
            if user_bot.welcome_button_text:
                summary["bots_with_welcome_buttons"] += 1
            if user_bot.goodbye_button_text and user_bot.goodbye_button_url:
                summary["bots_with_goodbye_buttons"] += 1
            if user_bot.confirmation_message:
                summary["bots_with_confirmation"] += 1
            if stats.get("admin_sessions", 0) > 0:
                summary["bots_with_admin_activity"] += 1
        
        return summary
    
    # ✅ ADMIN PANEL SPECIFIC METHODS
    
    def get_bot_admin_info(self, bot_id: str) -> dict:
        """Get admin panel specific information for a bot"""
        if bot_id not in self.active_bots:
            return {"error": "Bot not found or not active"}
        
        user_bot = self.active_bots[bot_id]
        config = self.bot_configs.get(bot_id, {})
        
        return {
            "bot_id": bot_id,
            "bot_username": user_bot.bot_username,
            "owner_user_id": user_bot.owner_user_id,
            "admin_panel_url": f"https://t.me/{user_bot.bot_username}",
            "configuration": {
                "has_welcome_message": bool(user_bot.welcome_message),
                "has_welcome_button": bool(user_bot.welcome_button_text),
                "has_confirmation_message": bool(user_bot.confirmation_message),
                "has_goodbye_message": bool(user_bot.goodbye_message),
                "has_goodbye_button": bool(user_bot.goodbye_button_text and user_bot.goodbye_button_url)
            },
            "admin_usage": {
                "admin_sessions": user_bot.stats.get("admin_sessions", 0),
                "last_activity": user_bot.last_activity.isoformat() if user_bot.last_activity else None
            }
        }
    
    def get_all_admin_panels_info(self) -> dict:
        """Get admin panel information for all bots"""
        admin_info = {}
        
        for bot_id in self.active_bots.keys():
            admin_info[bot_id] = self.get_bot_admin_info(bot_id)
        
        return {
            "total_admin_panels": len(admin_info),
            "admin_panels": admin_info
        }
    
    async def notify_admin_panel_update(self, bot_id: str, update_type: str, details: dict = None):
        """Notify about admin panel configuration updates"""
        if bot_id in self.active_bots:
            user_bot = self.active_bots[bot_id]
            logger.info("Admin panel configuration updated", 
                       bot_id=bot_id,
                       bot_username=user_bot.bot_username,
                       owner_user_id=user_bot.owner_user_id,
                       update_type=update_type,
                       details=details or {})
    
    # ✅ FUNNEL AND SCHEDULER METHODS (unchanged but documented)
    
    def get_scheduler_stats(self) -> dict:
        """Get message scheduler statistics"""
        if self.message_scheduler:
            return self.message_scheduler.get_scheduler_stats()
        return {"error": "Scheduler not initialized"}
    
    async def initialize_bot_funnel(self, bot_id: str) -> bool:
        """Initialize funnel for bot (called from admin panel)"""
        try:
            from services.funnel_manager import funnel_manager
            result = await funnel_manager.initialize_bot_funnel(bot_id)
            
            if result:
                await self.notify_admin_panel_update(bot_id, "funnel_initialized")
            
            return result
        except Exception as e:
            logger.error("Failed to initialize bot funnel", bot_id=bot_id, error=str(e))
            return False
    
    async def toggle_bot_funnel(self, bot_id: str, enabled: bool) -> bool:
        """Toggle funnel for bot (called from admin panel)"""
        try:
            from services.funnel_manager import funnel_manager
            result = await funnel_manager.toggle_funnel(bot_id, enabled)
            
            if result:
                await self.notify_admin_panel_update(bot_id, "funnel_toggled", {"enabled": enabled})
            
            return result
        except Exception as e:
            logger.error("Failed to toggle bot funnel", bot_id=bot_id, enabled=enabled, error=str(e))
            return False
    
    async def get_bot_funnel_stats(self, bot_id: str) -> dict:
        """Get funnel statistics for bot"""
        try:
            from services.funnel_manager import funnel_manager
            return await funnel_manager.get_funnel_stats(bot_id)
        except Exception as e:
            logger.error("Failed to get bot funnel stats", bot_id=bot_id, error=str(e))
            return {"error": str(e)}
    
    def get_global_stats(self) -> dict:
        """Get global statistics including admin panel usage"""
        bot_summary = self.get_all_bots_summary()
        scheduler_stats = self.get_scheduler_stats()
        admin_panels_info = self.get_all_admin_panels_info()
        
        return {
            "bots": bot_summary,
            "scheduler": scheduler_stats,
            "admin_panels": {
                "total_panels": admin_panels_info["total_admin_panels"],
                "total_admin_sessions": bot_summary["total_admin_sessions"],
                "bots_with_admin_activity": bot_summary["bots_with_admin_activity"]
            },
            "system": {
                "uptime": datetime.now(),
                "bot_manager_running": self.running,
                "active_tasks": len([t for t in asyncio.all_tasks() if not t.done()])
            }
        }
