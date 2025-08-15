"""
Bot Manager - handles all bot-related database operations.

Responsibilities:
- Bot creation, configuration and management
- Bot status and activity tracking
- Bot subscribers management
- Bot statistics and analytics
- Bot messages and settings updates
"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy import select, update, delete, func
from sqlalchemy.sql import text
import structlog

from ..connection import get_db_session

logger = structlog.get_logger()


class BotManager:
    """Manager for bot-related database operations"""
    
    # ===== BOT CRUD OPERATIONS =====
    
    @staticmethod
    async def get_user_bots(user_id: int):
        """Get all bots for a user"""
        from database.models import UserBot
        
        async with get_db_session() as session:
            result = await session.execute(
                select(UserBot)
                .where(UserBot.user_id == user_id)
                .order_by(UserBot.created_at.desc())
            )
            return result.scalars().all()
    
    @staticmethod
    async def create_user_bot(bot_data: dict):
        """Create a new user bot"""
        from database.models import UserBot
        
        async with get_db_session() as session:
            bot = UserBot(**bot_data)
            session.add(bot)
            await session.commit()
            await session.refresh(bot)
            
            logger.info("✅ User bot created", 
                       bot_id=bot.bot_id,
                       user_id=bot.user_id,
                       bot_username=bot.bot_username)
            
            return bot
    
    @staticmethod
    async def get_bot_by_id(bot_id: str, fresh: bool = False):
        """Get bot by ID with optional fresh data"""
        from database.models import UserBot
        
        async with get_db_session() as session:
            if fresh:
                # Получаем всегда свежие данные из БД
                result = await session.execute(
                    select(UserBot)
                    .where(UserBot.bot_id == bot_id)
                    .execution_options(populate_existing=True)
                )
                bot = result.scalar_one_or_none()
                if bot:
                    await session.refresh(bot)
                logger.info("🔄 Retrieved fresh bot data", bot_id=bot_id)
                return bot
            else:
                # Обычное получение (может быть из кэша)
                result = await session.execute(
                    select(UserBot).where(UserBot.bot_id == bot_id)
                )
                return result.scalar_one_or_none()
    
    @staticmethod
    async def get_bot_full_config(bot_id: str, fresh: bool = False) -> Optional[dict]:
        """Получение полной конфигурации бота"""
        from database.models import UserBot
        
        logger.info("🔄 Loading full bot configuration", bot_id=bot_id, fresh=fresh)
        
        async with get_db_session() as session:
            if fresh:
                # Получаем всегда свежие данные из БД
                result = await session.execute(
                    select(UserBot)
                    .where(UserBot.bot_id == bot_id)
                    .execution_options(populate_existing=True)
                )
                bot = result.scalar_one_or_none()
                if bot:
                    await session.refresh(bot)
                    logger.info("🔄 Using fresh data from database", bot_id=bot_id)
            else:
                # Обычное получение (может быть из кэша)
                result = await session.execute(
                    select(UserBot).where(UserBot.bot_id == bot_id)
                )
                bot = result.scalar_one_or_none()
            
            if not bot:
                logger.warning("❌ Bot not found for full config loading", bot_id=bot_id)
                return None
            
            # Базовая конфигурация
            config = {
                'bot_id': bot.bot_id,
                'token': bot.token,
                'bot_username': bot.bot_username,
                'bot_name': bot.bot_name,
                'user_id': bot.user_id,
                'welcome_message': bot.welcome_message,
                'welcome_button_text': bot.welcome_button_text,
                'confirmation_message': bot.confirmation_message,
                'goodbye_message': bot.goodbye_message,
                'goodbye_button_text': bot.goodbye_button_text,
                'goodbye_button_url': bot.goodbye_button_url,
                'status': bot.status,
                'is_running': bot.is_running,
                'ai_assistant_enabled': bot.ai_assistant_enabled or False,
                'ai_assistant_type': bot.ai_assistant_type
            }
            
            # Добавляем ИИ данные в зависимости от типа
            if bot.ai_assistant_type == 'openai':
                config.update({
                    'ai_assistant_id': bot.openai_agent_id,
                    'ai_assistant_settings': bot.openai_settings or {},
                    'ai_assistant_model': bot.openai_model,
                    'ai_assistant_prompt': bot.openai_agent_instructions
                })
                logger.info("✅ OpenAI configuration loaded in full config", 
                           bot_id=bot_id,
                           has_agent_id=bool(bot.openai_agent_id),
                           model=bot.openai_model)
                
            elif bot.ai_assistant_type in ['chatforyou', 'protalk']:
                config.update({
                    'ai_assistant_id': bot.external_api_token,
                    'ai_assistant_settings': bot.external_settings or {},
                    'ai_assistant_model': None,
                    'ai_assistant_prompt': None
                })
                logger.info("✅ External AI configuration loaded in full config", 
                           bot_id=bot_id,
                           platform=bot.ai_assistant_type,
                           has_api_token=bool(bot.external_api_token))
                
            else:
                config.update({
                    'ai_assistant_id': None,
                    'ai_assistant_settings': {},
                    'ai_assistant_model': None,
                    'ai_assistant_prompt': None
                })
                logger.info("⚪ No AI configuration found in full config", bot_id=bot_id)
            
            logger.info("✅ Full bot configuration loaded successfully", 
                       bot_id=bot_id,
                       ai_enabled=config['ai_assistant_enabled'],
                       ai_type=config['ai_assistant_type'],
                       data_source="database" if fresh else "cache_or_database")
            
            return config
    
    @staticmethod
    async def delete_user_bot(bot_id: str):
        """Delete user bot from database without loading relationships"""
        from database.models import UserBot
        
        async with get_db_session() as session:
            # Сначала получаем только базовую информацию для логирования
            result = await session.execute(
                select(UserBot.bot_username, UserBot.bot_id)
                .where(UserBot.bot_id == bot_id)
            )
            bot_info = result.first()
            
            if bot_info:
                # Прямое удаление без загрузки relationships
                await session.execute(
                    delete(UserBot).where(UserBot.bot_id == bot_id)
                )
                await session.commit()
                
                logger.info("✅ Bot deleted from database", 
                           bot_id=bot_id,
                           bot_username=bot_info.bot_username)
            else:
                logger.warning("❌ Bot not found for deletion", bot_id=bot_id)
    
    # ===== BOT STATUS AND ACTIVITY =====
    
    @staticmethod
    async def update_bot_status(bot_id: str, status: str, is_running: bool = None):
        """Update bot status"""
        from database.models import UserBot
        
        async with get_db_session() as session:
            update_data = {"status": status}
            if is_running is not None:
                update_data["is_running"] = is_running
                
            await session.execute(
                update(UserBot)
                .where(UserBot.bot_id == bot_id)
                .values(**update_data)
            )
            await session.commit()
            
            logger.info("✅ Bot status updated", 
                       bot_id=bot_id, 
                       status=status, 
                       is_running=is_running)
    
    @staticmethod
    async def get_all_active_bots():
        """Get all active bots"""
        from database.models import UserBot
        
        async with get_db_session() as session:
            result = await session.execute(
                select(UserBot)
                .where(UserBot.status == "active")
                .order_by(UserBot.created_at)
            )
            return result.scalars().all()
    
    @staticmethod
    async def get_updated_bots(bot_ids: list):
        """Get updated bots by IDs"""
        from database.models import UserBot
        
        if not bot_ids:
            return []
        
        async with get_db_session() as session:
            result = await session.execute(
                select(UserBot)
                .where(UserBot.bot_id.in_(bot_ids))
            )
            return result.scalars().all()
    
    @staticmethod
    async def increment_bot_messages(bot_id: str):
        """Increment bot message count"""
        from database.models import UserBot
        
        async with get_db_session() as session:
            await session.execute(
                update(UserBot)
                .where(UserBot.bot_id == bot_id)
                .values(
                    total_messages_sent=UserBot.total_messages_sent + 1,
                    last_activity=func.now()
                )
            )
            await session.commit()
            
            logger.debug("📊 Bot message count incremented", bot_id=bot_id)
    
    @staticmethod
    async def update_bot_subscribers(bot_id: str, subscriber_count: int):
        """Update bot subscriber count"""
        from database.models import UserBot
        
        async with get_db_session() as session:
            await session.execute(
                update(UserBot)
                .where(UserBot.bot_id == bot_id)
                .values(
                    total_subscribers=subscriber_count,
                    last_activity=func.now()
                )
            )
            await session.commit()
            
            logger.debug("📊 Bot subscriber count updated", 
                        bot_id=bot_id, 
                        subscriber_count=subscriber_count)
    
    # ===== BOT SUBSCRIBERS MANAGEMENT =====
    
    @staticmethod
    async def create_or_update_subscriber(
        bot_id: str,
        user_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None
    ):
        """Create or update subscriber"""
        from database.models import BotSubscriber
        
        async with get_db_session() as session:
            # Check if subscriber exists
            result = await session.execute(
                select(BotSubscriber).where(
                    BotSubscriber.bot_id == bot_id,
                    BotSubscriber.user_id == user_id
                )
            )
            subscriber = result.scalar_one_or_none()
            
            if subscriber:
                # Update existing
                subscriber.username = username
                subscriber.first_name = first_name
                subscriber.last_name = last_name
                subscriber.last_activity = datetime.now()
                subscriber.is_active = True
                action = "updated"
            else:
                # Create new
                subscriber = BotSubscriber(
                    bot_id=bot_id,
                    user_id=user_id,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    is_active=True,
                    joined_at=datetime.now(),
                    last_activity=datetime.now(),
                    funnel_enabled=True
                )
                session.add(subscriber)
                action = "created"
            
            await session.commit()
            await session.refresh(subscriber)
            
            logger.info("✅ Subscriber created/updated", 
                       bot_id=bot_id,
                       user_id=user_id,
                       action=action)
            
            return subscriber
    
    @staticmethod
    async def get_subscriber_by_bot_and_user(bot_id: str, user_id: int):
        """Get subscriber by bot_id and user_id"""
        from database.models import BotSubscriber
        
        async with get_db_session() as session:
            result = await session.execute(
                select(BotSubscriber).where(
                    BotSubscriber.bot_id == bot_id,
                    BotSubscriber.user_id == user_id
                )
            )
            return result.scalar_one_or_none()
    
    @staticmethod
    async def get_subscriber_info(user_id: int):
        """Get subscriber information"""
        from database.models import BotSubscriber
        
        async with get_db_session() as session:
            result = await session.execute(
                select(BotSubscriber).where(BotSubscriber.user_id == user_id)
            )
            return result.scalar_one_or_none()
    
    @staticmethod
    async def update_subscriber_broadcast_settings(
        bot_id: str,
        subscriber_id: int,
        accepts_broadcasts: Optional[bool] = None,
        broadcast_started_at: Optional[datetime] = None,
        last_broadcast_message: Optional[int] = None,
        funnel_enabled: Optional[bool] = None,
        funnel_started_at: Optional[datetime] = None,
        last_funnel_message: Optional[int] = None
    ):
        """Update subscriber broadcast and funnel settings"""
        from database.models import BotSubscriber
        
        async with get_db_session() as session:
            update_data = {}
            
            if accepts_broadcasts is not None:
                update_data["accepts_broadcasts"] = accepts_broadcasts
            if broadcast_started_at is not None:
                update_data["broadcast_started_at"] = broadcast_started_at
            if last_broadcast_message is not None:
                update_data["last_broadcast_message"] = last_broadcast_message
            if funnel_enabled is not None:
                update_data["funnel_enabled"] = funnel_enabled
            if funnel_started_at is not None:
                update_data["funnel_started_at"] = funnel_started_at
            if last_funnel_message is not None:
                update_data["last_funnel_message"] = last_funnel_message
            
            if update_data:
                await session.execute(
                    update(BotSubscriber)
                    .where(
                        BotSubscriber.bot_id == bot_id,
                        BotSubscriber.user_id == subscriber_id
                    )
                    .values(**update_data)
                )
                await session.commit()
                
                logger.info("✅ Subscriber broadcast settings updated", 
                           bot_id=bot_id,
                           subscriber_id=subscriber_id,
                           fields=list(update_data.keys()))
    
    # ===== BOT STATISTICS AND ANALYTICS =====
    
    @staticmethod
    async def get_bot_statistics(bot_id: str) -> dict:
        """Get comprehensive bot statistics"""
        from database.models import UserBot, BotSubscriber, ScheduledMessage, AIUsageLog
        
        async with get_db_session() as session:
            # Базовая информация о боте
            bot_result = await session.execute(
                select(UserBot).where(UserBot.bot_id == bot_id)
            )
            bot = bot_result.scalar_one_or_none()
            
            if not bot:
                return {}
            
            # Статистика подписчиков
            subscribers_result = await session.execute(
                select(
                    func.count(BotSubscriber.id).label('total_subscribers'),
                    func.count(func.nullif(BotSubscriber.is_active, False)).label('active_subscribers'),
                    func.count(func.nullif(BotSubscriber.funnel_enabled, False)).label('funnel_enabled_subscribers')
                ).where(BotSubscriber.bot_id == bot_id)
            )
            subscribers_stats = subscribers_result.first()
            
            # Статистика запланированных сообщений
            scheduled_result = await session.execute(
                select(
                    ScheduledMessage.status,
                    func.count(ScheduledMessage.id).label('count')
                ).where(ScheduledMessage.bot_id == bot_id)
                .group_by(ScheduledMessage.status)
            )
            scheduled_stats = {row.status: row.count for row in scheduled_result.fetchall()}
            
            # Статистика использования AI за последние 30 дней
            thirty_days_ago = datetime.now() - timedelta(days=30)
            ai_usage_result = await session.execute(
                select(
                    func.sum(AIUsageLog.messages_count).label('total_ai_messages'),
                    func.count(func.distinct(AIUsageLog.user_id)).label('unique_ai_users')
                ).where(
                    AIUsageLog.bot_id == bot_id,
                    AIUsageLog.date >= thirty_days_ago
                )
            )
            ai_usage_stats = ai_usage_result.first()
            
            return {
                'bot_info': {
                    'bot_id': bot.bot_id,
                    'name': bot.bot_name,
                    'username': bot.bot_username,
                    'status': bot.status,
                    'is_running': bot.is_running,
                    'created_at': bot.created_at,
                    'last_activity': bot.last_activity,
                    'total_messages_sent': bot.total_messages_sent or 0
                },
                'subscribers': {
                    'total': subscribers_stats.total_subscribers or 0,
                    'active': subscribers_stats.active_subscribers or 0,
                    'funnel_enabled': subscribers_stats.funnel_enabled_subscribers or 0
                },
                'scheduled_messages': {
                    'pending': scheduled_stats.get('pending', 0),
                    'sent': scheduled_stats.get('sent', 0),
                    'failed': scheduled_stats.get('failed', 0),
                    'cancelled': scheduled_stats.get('cancelled', 0)
                },
                'ai_usage_30_days': {
                    'total_messages': int(ai_usage_stats.total_ai_messages or 0),
                    'unique_users': int(ai_usage_stats.unique_ai_users or 0)
                },
                'ai_assistant': {
                    'enabled': bot.ai_assistant_enabled or False,
                    'type': bot.ai_assistant_type,
                    'configured': bot.ai_assistant_enabled and bot.ai_assistant_type is not None
                }
            }
    
    @staticmethod
    async def get_bot_activity_stats(bot_id: str, days: int = 30) -> dict:
        """Get bot activity statistics for specific period"""
        from database.models import UserBot, BotSubscriber, AIUsageLog
        
        async with get_db_session() as session:
            start_date = datetime.now() - timedelta(days=days)
            
            # Activity stats
            activity_result = await session.execute(
                select(
                    func.count(func.distinct(BotSubscriber.user_id)).label('active_users'),
                    func.count(BotSubscriber.id).label('total_interactions')
                ).where(
                    BotSubscriber.bot_id == bot_id,
                    BotSubscriber.last_activity >= start_date
                )
            )
            activity_stats = activity_result.first()
            
            # AI usage stats
            ai_result = await session.execute(
                select(
                    func.sum(AIUsageLog.messages_count).label('ai_messages'),
                    func.count(func.distinct(AIUsageLog.user_id)).label('ai_users')
                ).where(
                    AIUsageLog.bot_id == bot_id,
                    AIUsageLog.date >= start_date
                )
            )
            ai_stats = ai_result.first()
            
            return {
                'period_days': days,
                'active_users': activity_stats.active_users or 0,
                'total_interactions': activity_stats.total_interactions or 0,
                'ai_messages': int(ai_stats.ai_messages or 0),
                'ai_users': int(ai_stats.ai_users or 0),
                'avg_interactions_per_user': round(
                    (activity_stats.total_interactions or 0) / max(activity_stats.active_users or 1, 1),
                    2
                ),
                'ai_adoption_rate': round(
                    ((ai_stats.ai_users or 0) / max(activity_stats.active_users or 1, 1)) * 100,
                    2
                )
            }
    
    # ===== BOT SEARCH AND LISTING =====
    
    @staticmethod
    async def get_bots_by_status(status: str, limit: int = 100):
        """Get bots by status"""
        from database.models import UserBot
        
        async with get_db_session() as session:
            result = await session.execute(
                select(UserBot)
                .where(UserBot.status == status)
                .order_by(UserBot.last_activity.desc())
                .limit(limit)
            )
            return result.scalars().all()
    
    @staticmethod
    async def search_bots(query: str, user_id: Optional[int] = None, limit: int = 50):
        """Search bots by name or username"""
        from database.models import UserBot
        
        async with get_db_session() as session:
            conditions = [
                UserBot.bot_name.ilike(f'%{query}%') |
                UserBot.bot_username.ilike(f'%{query}%')
            ]
            
            if user_id:
                conditions.append(UserBot.user_id == user_id)
            
            result = await session.execute(
                select(UserBot)
                .where(*conditions)
                .order_by(UserBot.last_activity.desc())
                .limit(limit)
            )
            return result.scalars().all()
    
    @staticmethod
    async def get_bots_with_ai(ai_type: Optional[str] = None, limit: int = 100):
        """Get bots with AI assistant enabled"""
        from database.models import UserBot
        
        async with get_db_session() as session:
            conditions = [UserBot.ai_assistant_enabled == True]
            
            if ai_type:
                conditions.append(UserBot.ai_assistant_type == ai_type)
            
            result = await session.execute(
                select(UserBot)
                .where(*conditions)
                .order_by(UserBot.last_activity.desc())
                .limit(limit)
            )
            return result.scalars().all()
    
    @staticmethod
    async def get_recent_bots(limit: int = 20):
        """Get recently created bots"""
        from database.models import UserBot
        
        async with get_db_session() as session:
            result = await session.execute(
                select(UserBot)
                .order_by(UserBot.created_at.desc())
                .limit(limit)
            )
            return result.scalars().all()
    
    # ===== BOT MAINTENANCE =====
    
    @staticmethod
    async def cleanup_inactive_bots(days: int = 90):
        """Mark bots as inactive if no activity for specified days"""
        from database.models import UserBot
        
        cutoff_date = datetime.now() - timedelta(days=days)
        
        async with get_db_session() as session:
            result = await session.execute(
                update(UserBot)
                .where(
                    UserBot.last_activity < cutoff_date,
                    UserBot.status != 'inactive'
                )
                .values(status='inactive')
            )
            await session.commit()
            
            affected_count = result.rowcount
            logger.info("🧹 Inactive bots cleanup completed", 
                       days=days,
                       affected_bots=affected_count)
            
            return affected_count
    
    @staticmethod
    async def get_bots_summary() -> dict:
        """Get summary statistics for all bots"""
        from database.models import UserBot
        
        async with get_db_session() as session:
            # Total counts by status
            status_result = await session.execute(
                select(
                    UserBot.status,
                    func.count(UserBot.id).label('count')
                ).group_by(UserBot.status)
            )
            status_counts = {row.status: row.count for row in status_result.fetchall()}
            
            # AI assistant stats
            ai_result = await session.execute(
                select(
                    UserBot.ai_assistant_type,
                    func.count(UserBot.id).label('count')
                ).where(UserBot.ai_assistant_enabled == True)
                .group_by(UserBot.ai_assistant_type)
            )
            ai_counts = {row.ai_assistant_type: row.count for row in ai_result.fetchall()}
            
            # Total stats
            total_result = await session.execute(
                select(
                    func.count(UserBot.id).label('total_bots'),
                    func.count(func.distinct(UserBot.user_id)).label('unique_users'),
                    func.sum(UserBot.total_messages_sent).label('total_messages'),
                    func.sum(UserBot.total_subscribers).label('total_subscribers')
                )
            )
            total_stats = total_result.first()
            
            return {
                'total_bots': total_stats.total_bots or 0,
                'unique_users': total_stats.unique_users or 0,
                'total_messages_sent': int(total_stats.total_messages or 0),
                'total_subscribers': int(total_stats.total_subscribers or 0),
                'bots_by_status': status_counts,
                'bots_by_ai_type': ai_counts,
                'ai_enabled_bots': sum(ai_counts.values()),
                'ai_adoption_rate': round(
                    (sum(ai_counts.values()) / max(total_stats.total_bots or 1, 1)) * 100,
                    2
                )
            }
