import asyncio
from typing import Dict, List, Optional
from datetime import datetime
import structlog

from database import db
from services.user_bot.core import UserBot
from services.message_scheduler import MessageScheduler

logger = structlog.get_logger()


class BotManager:
    """Manager for all user bots with admin panel support and AI config loading"""
    
    def __init__(self):
        self.active_bots: Dict[str, UserBot] = {}  # bot_id -> UserBot instance
        self.bot_configs: Dict[str, dict] = {}     # bot_id -> config cache
        self.sync_task: Optional[asyncio.Task] = None
        self.running = False
        
        # Message Scheduler Integration
        self.message_scheduler: Optional[MessageScheduler] = None
    
    async def start(self):
        """Start bot manager and load all active bots"""
        logger.info("Starting Bot Manager with admin panel support and AI config loading")
        self.running = True
        
        try:
            # Initialize message scheduler
            logger.info("Initializing message scheduler...")
            self.message_scheduler = MessageScheduler(self)
            await self.message_scheduler.start()
            
            # Load all active bots from database
            logger.info("Loading active bots with AI configs from database...")
            await self._load_active_bots()
            
            # Start periodic sync task
            logger.info("Starting periodic sync task...")
            self.sync_task = asyncio.create_task(self._sync_task())
            
            logger.info("Bot Manager started successfully with admin support and AI loading", 
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
        """Load all active bots from database with AI configurations"""
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
                        "Starting user bot with admin panel and AI config", 
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
            
            logger.info("Active bots with admin panels and AI configs loading completed", 
                       loaded_count=len(self.active_bots),
                       total_found=len(bots))
            
        except Exception as e:
            logger.error("Failed to load active bots", error=str(e), exc_info=True)
            raise
    
    async def _start_user_bot(self, bot_data):
        """✅ UPDATED: Start individual user bot with admin panel and AI configuration"""
        bot_id = bot_data.bot_id
        
        logger.info("Creating bot config with admin support and AI loading", 
                   bot_id=bot_id, 
                   owner_user_id=bot_data.user_id)
        
        try:
            # ✅ КРИТИЧЕСКАЯ ДОРАБОТКА: Загрузка полной конфигурации включая ИИ
            logger.info("Loading full bot configuration including AI settings", bot_id=bot_id)
            config = await db.get_bot_full_config(bot_id)
            
            if not config:
                # ✅ Fallback: создаем базовую конфигурацию и загружаем ИИ отдельно
                logger.warning("Full config not available, creating from bot_data and loading AI separately", 
                              bot_id=bot_id)
                
                config = {
                    'bot_id': bot_data.bot_id,
                    'token': bot_data.token,
                    'bot_username': bot_data.bot_username,
                    'bot_name': bot_data.bot_name,
                    'user_id': bot_data.user_id,
                    'welcome_message': bot_data.welcome_message,
                    'welcome_button_text': bot_data.welcome_button_text,
                    'confirmation_message': bot_data.confirmation_message,
                    'goodbye_message': bot_data.goodbye_message,
                    'goodbye_button_text': bot_data.goodbye_button_text,
                    'goodbye_button_url': bot_data.goodbye_button_url,
                    'status': bot_data.status,
                    'is_running': bot_data.is_running
                }
                
                # ✅ ЗАГРУЖАЕМ ИИ КОНФИГУРАЦИЮ ОТДЕЛЬНО
                logger.info("Loading AI configuration separately", bot_id=bot_id)
                ai_config = await db.get_ai_config(bot_id)
                
                if ai_config:
                    config.update({
                        'ai_assistant_id': ai_config.get('agent_id') or ai_config.get('api_token'),
                        'ai_assistant_enabled': ai_config.get('enabled', False),
                        'ai_assistant_settings': ai_config.get('settings', {}),
                        'ai_assistant_type': ai_config.get('type', 'openai'),
                        'ai_assistant_model': ai_config.get('model'),
                        'ai_assistant_prompt': ai_config.get('system_prompt')
                    })
                    logger.info("AI configuration loaded successfully", 
                               bot_id=bot_id,
                               ai_enabled=ai_config.get('enabled', False),
                               ai_type=ai_config.get('type'),
                               has_agent_id=bool(ai_config.get('agent_id')))
                else:
                    config.update({
                        'ai_assistant_id': None,
                        'ai_assistant_enabled': False,
                        'ai_assistant_settings': {},
                        'ai_assistant_type': None,
                        'ai_assistant_model': None,
                        'ai_assistant_prompt': None
                    })
                    logger.info("No AI configuration found for bot", bot_id=bot_id)
            else:
                # ✅ Полная конфигурация уже загружена, проверяем наличие ИИ полей
                if 'ai_assistant_enabled' not in config:
                    logger.info("AI fields missing in full config, loading AI separately", bot_id=bot_id)
                    ai_config = await db.get_ai_config(bot_id)
                    if ai_config:
                        config.update({
                            'ai_assistant_id': ai_config.get('agent_id') or ai_config.get('api_token'),
                            'ai_assistant_enabled': ai_config.get('enabled', False),
                            'ai_assistant_settings': ai_config.get('settings', {}),
                            'ai_assistant_type': ai_config.get('type', 'openai'),
                            'ai_assistant_model': ai_config.get('model'),
                            'ai_assistant_prompt': ai_config.get('system_prompt')
                        })
                
                logger.info("Full bot configuration loaded successfully", 
                           bot_id=bot_id,
                           ai_enabled=config.get('ai_assistant_enabled', False))
            
        except Exception as e:
            logger.error("Failed to load bot configuration", bot_id=bot_id, error=str(e), exc_info=True)
            raise
        
        # Store config in cache
        self.bot_configs[bot_id] = config
        
        logger.info("Bot config stored with admin panel and AI support", 
                   bot_id=bot_id,
                   owner_user_id=config.get('user_id'),
                   has_welcome_button=bool(config.get('welcome_button_text')),
                   has_confirmation=bool(config.get('confirmation_message')),
                   has_goodbye_button=bool(config.get('goodbye_button_text')),
                   ai_enabled=config.get('ai_assistant_enabled', False),
                   ai_type=config.get('ai_assistant_type'))
        
        # Create and start user bot with admin panel and AI
        logger.info("Creating UserBot instance with admin panel and AI", bot_id=bot_id)
        user_bot = UserBot(config, self)
        
        logger.info("Starting UserBot instance with admin panel and AI", bot_id=bot_id)
        await user_bot.start()
        
        # Store active bot
        self.active_bots[bot_id] = user_bot
        
        logger.info(
            "User bot started successfully with full admin panel and AI support", 
            bot_id=bot_id,
            bot_username=config.get('bot_username'),
            owner_user_id=config.get('user_id'),
            has_welcome=bool(config.get('welcome_message')),
            has_welcome_button=bool(config.get('welcome_button_text')),
            has_confirmation=bool(config.get('confirmation_message')),
            has_goodbye=bool(config.get('goodbye_message')),
            has_goodbye_button=bool(config.get('goodbye_button_text') and config.get('goodbye_button_url')),
            ai_assistant_enabled=config.get('ai_assistant_enabled', False),
            ai_assistant_type=config.get('ai_assistant_type')
        )
    
    async def add_bot(self, bot_data):
        """Add new bot to manager with admin panel and AI config"""
        bot_id = bot_data.bot_id
        
        # Check if bot already exists
        if bot_id in self.active_bots:
            logger.warning("Bot already exists", bot_id=bot_id)
            return
        
        try:
            await self._start_user_bot(bot_data)
            logger.info("New bot with admin panel and AI added to manager", 
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
        """✅ УЛУЧШЕННАЯ: Update bot configuration with real-time sync"""
        if bot_id not in self.bot_configs:
            logger.warning("Bot config not found", bot_id=bot_id)
            return
        
        logger.info("🔄 Updating bot config with real-time sync", 
                   bot_id=bot_id, 
                   updates=list(updates.keys()))
        
        # ✅ 1. Обновляем config cache
        old_config = self.bot_configs[bot_id].copy()
        self.bot_configs[bot_id].update(updates)
        
        # ✅ 2. Обновляем активный UserBot
        if bot_id in self.active_bots:
            user_bot = self.active_bots[bot_id]
            user_bot.update_config(self.bot_configs[bot_id])
            
            # ✅ 3. Специальная обработка разных типов обновлений
            if any(key in updates for key in ['welcome_message', 'welcome_button_text', 'confirmation_message']):
                welcome_updates = {k: v for k, v in updates.items() 
                                 if k in ['welcome_message', 'welcome_button_text', 'confirmation_message']}
                await user_bot.update_welcome_settings(**welcome_updates)
                
            if any(key in updates for key in ['goodbye_message', 'goodbye_button_text', 'goodbye_button_url']):
                goodbye_updates = {k: v for k, v in updates.items() 
                                 if k in ['goodbye_message', 'goodbye_button_text', 'goodbye_button_url']}
                await user_bot.update_goodbye_settings(**goodbye_updates)
                
            if any(key in updates for key in ['ai_assistant_id', 'ai_assistant_enabled', 'ai_assistant_settings', 
                                             'ai_assistant_type', 'ai_assistant_model', 'ai_assistant_prompt']):
                ai_updates = {k: v for k, v in updates.items() 
                             if k in ['ai_assistant_id', 'ai_assistant_enabled', 'ai_assistant_settings',
                                     'ai_assistant_type', 'ai_assistant_model', 'ai_assistant_prompt']}
                await user_bot.update_ai_settings(**ai_updates)
            
            logger.info("✅ UserBot real-time sync completed", 
                       bot_id=bot_id,
                       bot_username=user_bot.bot_username)
        
        # ✅ 4. Логируем что именно изменилось
        changed_fields = []
        for key, new_value in updates.items():
            old_value = old_config.get(key)
            if old_value != new_value:
                changed_fields.append(f"{key}: {old_value} → {new_value}")
        
        if changed_fields:
            logger.info("📝 Config changes applied", 
                       bot_id=bot_id,
                       changes=changed_fields)
    
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
        """✅ UPDATED: Sync bot configs with database including admin panel and AI changes"""
        try:
            # Get updated bot configs from database
            updated_bots = await db.get_updated_bots(list(self.bot_configs.keys()))
            
            for bot_data in updated_bots:
                bot_id = bot_data.bot_id
                
                if bot_id in self.bot_configs:
                    # Check if config changed (including admin panel and AI changes)
                    current_config = self.bot_configs[bot_id]
                    
                    # ✅ Load current AI config for comparison
                    ai_config = await db.get_ai_config(bot_id)
                    current_ai_enabled = current_config.get('ai_assistant_enabled', False)
                    new_ai_enabled = ai_config.get('enabled', False) if ai_config else False
                    current_ai_id = current_config.get('ai_assistant_id')
                    new_ai_id = ai_config.get('agent_id') or ai_config.get('api_token') if ai_config else None
                    
                    # ✅ Compare all admin-configurable fields including AI
                    if (current_config.get('welcome_message') != bot_data.welcome_message or
                        current_config.get('welcome_button_text') != bot_data.welcome_button_text or
                        current_config.get('confirmation_message') != bot_data.confirmation_message or
                        current_config.get('goodbye_message') != bot_data.goodbye_message or
                        current_config.get('goodbye_button_text') != bot_data.goodbye_button_text or
                        current_config.get('goodbye_button_url') != bot_data.goodbye_button_url or
                        current_config.get('status') != bot_data.status or
                        current_config.get('is_running') != bot_data.is_running or
                        current_ai_enabled != new_ai_enabled or
                        current_ai_id != new_ai_id):
                        
                        # Prepare update with all fields including AI
                        update_data = {
                            'welcome_message': bot_data.welcome_message,
                            'welcome_button_text': bot_data.welcome_button_text,
                            'confirmation_message': bot_data.confirmation_message,
                            'goodbye_message': bot_data.goodbye_message,
                            'goodbye_button_text': bot_data.goodbye_button_text,
                            'goodbye_button_url': bot_data.goodbye_button_url,
                            'status': bot_data.status,
                            'is_running': bot_data.is_running
                        }
                        
                        # ✅ Add AI configuration to update
                        if ai_config:
                            update_data.update({
                                'ai_assistant_id': ai_config.get('agent_id') or ai_config.get('api_token'),
                                'ai_assistant_enabled': ai_config.get('enabled', False),
                                'ai_assistant_settings': ai_config.get('settings', {}),
                                'ai_assistant_type': ai_config.get('type', 'openai'),
                                'ai_assistant_model': ai_config.get('model'),
                                'ai_assistant_prompt': ai_config.get('system_prompt')
                            })
                        else:
                            update_data.update({
                                'ai_assistant_id': None,
                                'ai_assistant_enabled': False,
                                'ai_assistant_settings': {},
                                'ai_assistant_type': None,
                                'ai_assistant_model': None,
                                'ai_assistant_prompt': None
                            })
                        
                        # Update config with all fields
                        await self.update_bot_config(bot_id, **update_data)
                        
                        logger.debug("Bot admin and AI config synced with database", 
                                   bot_id=bot_id,
                                   ai_enabled=update_data.get('ai_assistant_enabled', False))
            
            # Check for new bots that should be started
            all_active_bots = await db.get_all_active_bots()
            
            for bot_data in all_active_bots:
                if bot_data.bot_id not in self.active_bots and bot_data.is_running:
                    try:
                        await self.add_bot(bot_data)
                        logger.info("New bot with admin panel and AI detected and started", 
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
        """✅ UPDATED: Get bot status with admin panel stats and AI info"""
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
            "owner_user_id": user_bot.owner_user_id,
            "bot_username": user_bot.bot_username,
            "admin_stats": {
                "admin_sessions": detailed_stats.get("admin_sessions", 0),
                "last_admin_activity": detailed_stats.get("bot_info", {}).get("last_activity")
            },
            "ai_assistant": {  # ✅ NEW: AI Assistant information
                "enabled": config.get("ai_assistant_enabled", False),
                "type": config.get("ai_assistant_type"),
                "model": config.get("ai_assistant_model"),
                "has_agent_id": bool(config.get("ai_assistant_id")),
                "has_custom_prompt": bool(config.get("ai_assistant_prompt"))
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
        """Get status of all bots with admin and AI info"""
        return {
            bot_id: self.get_bot_status(bot_id) 
            for bot_id in self.bot_configs.keys()
        }
    
    async def restart_bot(self, bot_id: str):
        """Restart specific bot with admin panel and AI config"""
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
            
            # Start fresh bot with admin panel and AI
            await self.add_bot(bot_data)
            
            logger.info("Bot with admin panel and AI restarted successfully", 
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
        """✅ UPDATED: Get summary statistics for all bots including admin usage and AI stats"""
        summary = {
            "total_bots": len(self.active_bots),
            "running_bots": sum(1 for bot in self.active_bots.values() if bot.is_running),
            "total_welcome_sent": 0,
            "total_goodbye_sent": 0,
            "total_confirmation_sent": 0,
            "total_button_clicks": 0,
            "total_funnel_starts": 0,
            "total_admin_sessions": 0,
            "bots_with_welcome_buttons": 0,
            "bots_with_goodbye_buttons": 0,
            "bots_with_confirmation": 0,
            "bots_with_admin_activity": 0,
            "bots_with_ai_enabled": 0,  # ✅ NEW
            "ai_types_used": {},  # ✅ NEW
            "total_ai_conversations": 0  # ✅ NEW
        }
        
        for user_bot in self.active_bots.values():
            stats = user_bot.get_message_stats()
            config = self.bot_configs.get(user_bot.bot_id, {})
            
            summary["total_welcome_sent"] += stats.get("welcome_sent", 0)
            summary["total_goodbye_sent"] += stats.get("goodbye_sent", 0)
            summary["total_confirmation_sent"] += stats.get("confirmation_sent", 0)
            summary["total_button_clicks"] += stats.get("button_clicks", 0)
            summary["total_funnel_starts"] += stats.get("funnel_starts", 0)
            summary["total_admin_sessions"] += stats.get("admin_sessions", 0)
            
            # Configuration status
            if user_bot.welcome_button_text:
                summary["bots_with_welcome_buttons"] += 1
            if user_bot.goodbye_button_text and user_bot.goodbye_button_url:
                summary["bots_with_goodbye_buttons"] += 1
            if user_bot.confirmation_message:
                summary["bots_with_confirmation"] += 1
            if stats.get("admin_sessions", 0) > 0:
                summary["bots_with_admin_activity"] += 1
            
            # ✅ AI Statistics
            if config.get("ai_assistant_enabled", False):
                summary["bots_with_ai_enabled"] += 1
                ai_type = config.get("ai_assistant_type", "unknown")
                summary["ai_types_used"][ai_type] = summary["ai_types_used"].get(ai_type, 0) + 1
                summary["total_ai_conversations"] += stats.get("ai_conversations", 0)
        
        return summary
    
    # ✅ ADMIN PANEL SPECIFIC METHODS
    
    def get_bot_admin_info(self, bot_id: str) -> dict:
        """✅ UPDATED: Get admin panel specific information for a bot including AI"""
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
            "ai_configuration": {  # ✅ NEW: AI Configuration section
                "enabled": config.get("ai_assistant_enabled", False),
                "type": config.get("ai_assistant_type"),
                "model": config.get("ai_assistant_model"),
                "has_agent_id": bool(config.get("ai_assistant_id")),
                "has_custom_prompt": bool(config.get("ai_assistant_prompt")),
                "settings": config.get("ai_assistant_settings", {})
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
    
    # ✅ AI ASSISTANT SPECIFIC METHODS
    
    async def update_ai_config(self, bot_id: str, ai_config: dict):
        """✅ NEW: Update AI configuration for specific bot"""
        if bot_id not in self.active_bots:
            logger.warning("Cannot update AI config - bot not active", bot_id=bot_id)
            return False
        
        try:
            # Update database
            await db.update_ai_config(bot_id, ai_config)
            
            # Update bot config cache
            ai_updates = {
                'ai_assistant_id': ai_config.get('agent_id') or ai_config.get('api_token'),
                'ai_assistant_enabled': ai_config.get('enabled', False),
                'ai_assistant_settings': ai_config.get('settings', {}),
                'ai_assistant_type': ai_config.get('type', 'openai'),
                'ai_assistant_model': ai_config.get('model'),
                'ai_assistant_prompt': ai_config.get('system_prompt')
            }
            
            await self.update_bot_config(bot_id, **ai_updates)
            
            logger.info("AI configuration updated successfully", 
                       bot_id=bot_id,
                       ai_enabled=ai_config.get('enabled', False),
                       ai_type=ai_config.get('type'))
            
            await self.notify_admin_panel_update(bot_id, "ai_config_updated", ai_config)
            return True
            
        except Exception as e:
            logger.error("Failed to update AI configuration", bot_id=bot_id, error=str(e))
            return False
    
    def get_ai_status(self, bot_id: str) -> dict:
        """✅ NEW: Get AI assistant status for specific bot"""
        if bot_id not in self.active_bots:
            return {"error": "Bot not found or not active"}
        
        config = self.bot_configs.get(bot_id, {})
        user_bot = self.active_bots[bot_id]
        
        ai_stats = getattr(user_bot, 'ai_stats', {})
        
        return {
            "enabled": config.get("ai_assistant_enabled", False),
            "type": config.get("ai_assistant_type"),
            "model": config.get("ai_assistant_model"),
            "has_agent_id": bool(config.get("ai_assistant_id")),
            "agent_id_masked": f"***{config.get('ai_assistant_id', '')[-4:]}" if config.get("ai_assistant_id") else None,
            "has_custom_prompt": bool(config.get("ai_assistant_prompt")),
            "conversations_handled": ai_stats.get("conversations_handled", 0),
            "messages_processed": ai_stats.get("messages_processed", 0),
            "last_ai_activity": ai_stats.get("last_activity"),
            "error_count": ai_stats.get("error_count", 0),
            "average_response_time": ai_stats.get("average_response_time", 0)
        }
    
    def get_all_ai_summary(self) -> dict:
        """✅ NEW: Get summary of AI usage across all bots"""
        total_ai_bots = 0
        ai_types = {}
        total_conversations = 0
        total_messages = 0
        total_errors = 0
        
        for bot_id in self.active_bots.keys():
            config = self.bot_configs.get(bot_id, {})
            
            if config.get("ai_assistant_enabled", False):
                total_ai_bots += 1
                ai_type = config.get("ai_assistant_type", "unknown")
                ai_types[ai_type] = ai_types.get(ai_type, 0) + 1
                
                user_bot = self.active_bots[bot_id]
                ai_stats = getattr(user_bot, 'ai_stats', {})
                total_conversations += ai_stats.get("conversations_handled", 0)
                total_messages += ai_stats.get("messages_processed", 0)
                total_errors += ai_stats.get("error_count", 0)
        
        return {
            "total_ai_enabled_bots": total_ai_bots,
            "ai_types_breakdown": ai_types,
            "total_ai_conversations": total_conversations,
            "total_ai_messages": total_messages,
            "total_ai_errors": total_errors,
            "ai_success_rate": ((total_messages - total_errors) / total_messages * 100) if total_messages > 0 else 0
        }
    
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
        """✅ UPDATED: Get global statistics including admin panel usage and AI stats"""
        bot_summary = self.get_all_bots_summary()
        scheduler_stats = self.get_scheduler_stats()
        admin_panels_info = self.get_all_admin_panels_info()
        ai_summary = self.get_all_ai_summary()
        
        return {
            "bots": bot_summary,
            "scheduler": scheduler_stats,
            "admin_panels": {
                "total_panels": admin_panels_info["total_admin_panels"],
                "total_admin_sessions": bot_summary["total_admin_sessions"],
                "bots_with_admin_activity": bot_summary["bots_with_admin_activity"]
            },
            "ai_assistant": ai_summary,  # ✅ NEW: AI Assistant global stats
            "system": {
                "uptime": datetime.now(),
                "bot_manager_running": self.running,
                "active_tasks": len([t for t in asyncio.all_tasks() if not t.done()])
            }
        }
