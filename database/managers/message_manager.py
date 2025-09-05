"""
Message Manager - handles all bot message and usage tracking operations.

Responsibilities:
- Bot welcome and goodbye messages configuration
- Daily message limits and usage tracking
- AI usage logging and statistics
- Message analytics and reporting
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
from sqlalchemy import select, update, func
from sqlalchemy.dialects.postgresql import insert  # ✅ ДОБАВЛЕН импорт для UPSERT
import structlog

from ..connection import get_db_session

logger = structlog.get_logger()


class MessageManager:
    """Manager for bot message and usage tracking operations"""
    
    # ===== BOT MESSAGE CONFIGURATION =====
    
    @staticmethod
    async def update_bot_messages(
        bot_id: str, 
        welcome_message: Optional[str] = None, 
        goodbye_message: Optional[str] = None
    ):
        """Update bot messages + cache invalidation"""
        from database.models import UserBot
        
        async with get_db_session() as session:
            update_data = {}
            
            if welcome_message is not None:
                update_data["welcome_message"] = welcome_message
            
            if goodbye_message is not None:
                update_data["goodbye_message"] = goodbye_message
            
            if update_data:
                update_data["updated_at"] = datetime.now()
                
                await session.execute(
                    update(UserBot)
                    .where(UserBot.bot_id == bot_id)
                    .values(**update_data)
                )
                await session.commit()
                
                # Clear cache after update
                await MessageManager._expire_bot_cache(bot_id)
            
            logger.info(
                "✅ Bot messages updated with cache clear", 
                bot_id=bot_id, 
                welcome_updated=welcome_message is not None,
                goodbye_updated=goodbye_message is not None
            )
    
    @staticmethod
    async def update_welcome_settings(
        bot_id: str,
        welcome_message: Optional[str] = None,
        welcome_button_text: Optional[str] = None,
        confirmation_message: Optional[str] = None
    ):
        """Update welcome message settings + cache invalidation"""
        from database.models import UserBot
        
        async with get_db_session() as session:
            update_data = {}
            
            if welcome_message is not None:
                update_data["welcome_message"] = welcome_message
            
            if welcome_button_text is not None:
                update_data["welcome_button_text"] = welcome_button_text
            
            if confirmation_message is not None:
                update_data["confirmation_message"] = confirmation_message
            
            if update_data:
                update_data["updated_at"] = datetime.now()
                
                await session.execute(
                    update(UserBot)
                    .where(UserBot.bot_id == bot_id)
                    .values(**update_data)
                )
                await session.commit()
                
                # Clear cache after update
                await MessageManager._expire_bot_cache(bot_id)
            
            logger.info(
                "✅ Welcome settings updated with cache clear", 
                bot_id=bot_id,
                fields_updated=list(update_data.keys())
            )
    
    @staticmethod
    async def update_goodbye_settings(
        bot_id: str,
        goodbye_message: Optional[str] = None,
        goodbye_button_text: Optional[str] = None,
        goodbye_button_url: Optional[str] = None
    ):
        """Update goodbye message settings + cache invalidation"""
        from database.models import UserBot
        
        async with get_db_session() as session:
            update_data = {}
            
            if goodbye_message is not None:
                update_data["goodbye_message"] = goodbye_message
            
            if goodbye_button_text is not None:
                update_data["goodbye_button_text"] = goodbye_button_text
            
            if goodbye_button_url is not None:
                update_data["goodbye_button_url"] = goodbye_button_url
            
            if update_data:
                update_data["updated_at"] = datetime.now()
                
                await session.execute(
                    update(UserBot)
                    .where(UserBot.bot_id == bot_id)
                    .values(**update_data)
                )
                await session.commit()
                
                # Clear cache after update
                await MessageManager._expire_bot_cache(bot_id)
            
            logger.info(
                "✅ Goodbye settings updated with cache clear", 
                bot_id=bot_id,
                fields_updated=list(update_data.keys())
            )
    
    @staticmethod
    async def get_bot_message_settings(bot_id: str) -> dict:
        """Get all message settings for bot"""
        from database.models import UserBot
        
        async with get_db_session() as session:
            result = await session.execute(
                select(
                    UserBot.welcome_message,
                    UserBot.welcome_button_text,
                    UserBot.confirmation_message,
                    UserBot.goodbye_message,
                    UserBot.goodbye_button_text,
                    UserBot.goodbye_button_url
                ).where(UserBot.bot_id == bot_id)
            )
            
            data = result.first()
            if not data:
                return {}
            
            return {
                'welcome_message': data.welcome_message,
                'welcome_button_text': data.welcome_button_text,
                'confirmation_message': data.confirmation_message,
                'goodbye_message': data.goodbye_message,
                'goodbye_button_text': data.goodbye_button_text,
                'goodbye_button_url': data.goodbye_button_url
            }
    
    # ===== DAILY MESSAGE LIMITS =====
    
    @staticmethod
    async def check_daily_message_limit(bot_id: str, user_id: int) -> Tuple[bool, int, int]:
        """
        Проверить дневной лимит сообщений для пользователя
        Returns: (can_send_message, used_today, daily_limit)
        """
        from database.models import UserBot, AIUsageLog
        
        # МСК timezone
        msk_tz = timezone(timedelta(hours=3))
        msk_today = datetime.now(msk_tz).date()  # ✅ ИСПРАВЛЕНО: используем .date() для DATE поля
        
        async with get_db_session() as session:
            # Получаем настройки бота
            bot_result = await session.execute(
                select(UserBot).where(UserBot.bot_id == bot_id)
            )
            bot = bot_result.scalar_one_or_none()
            
            if not bot:
                return True, 0, 0
            
            # Получаем лимит из настроек
            daily_limit = None
            if bot.ai_assistant_type == 'openai' and bot.openai_settings:
                daily_limit = bot.openai_settings.get('daily_message_limit')
            elif bot.ai_assistant_type in ['chatforyou', 'protalk'] and bot.external_settings:
                daily_limit = bot.external_settings.get('daily_message_limit')
            
            if not daily_limit or daily_limit <= 0:
                return True, 0, 0  # Нет лимита
            
            # Получаем использование за сегодня (по МСК)
            usage_result = await session.execute(
                select(AIUsageLog.messages_count)
                .where(
                    AIUsageLog.bot_id == bot_id,
                    AIUsageLog.user_id == user_id,
                    AIUsageLog.date == msk_today
                )
            )
            
            used_today = usage_result.scalar_one_or_none() or 0
            can_send = used_today < daily_limit
            
            logger.debug("📊 Daily message limit check", 
                        bot_id=bot_id,
                        user_id=user_id,
                        used_today=used_today,
                        daily_limit=daily_limit,
                        can_send=can_send)
            
            return can_send, used_today, daily_limit

    @staticmethod
    async def increment_daily_message_usage(bot_id: str, user_id: int) -> bool:
        """✅ ИСПРАВЛЕНО: Увеличить счетчик с PostgreSQL UPSERT (без race condition)"""
        from database.models import AIUsageLog
        
        logger.info("📈 Incrementing daily message usage with UPSERT", 
                   bot_id=bot_id, user_id=user_id)
        
        try:
            # МСК timezone
            msk_tz = timezone(timedelta(hours=3))
            msk_today = datetime.now(msk_tz).date()  # ✅ ИСПРАВЛЕНО: используем .date() для DATE поля
            now = datetime.now()
            
            async with get_db_session() as session:
                # ✅ UPSERT: UPDATE existing or INSERT new
                stmt = insert(AIUsageLog).values(
                    bot_id=bot_id,
                    user_id=user_id,
                    date=msk_today,
                    messages_count=1,
                    platform_used='openai',  # или определить динамически
                    successful_requests=1,
                    failed_requests=0,
                    average_response_time=None,
                    total_tokens_used=0,
                    longest_conversation=0,
                    error_types={},
                    last_error_at=None,
                    last_success_at=now,
                    created_at=now,
                    updated_at=now
                )
                
                # ✅ ON CONFLICT: Если запись существует - обновляем
                stmt = stmt.on_conflict_do_update(
                    index_elements=['bot_id', 'user_id', 'date'],  # Уникальный индекс
                    set_={
                        'messages_count': stmt.excluded.messages_count + AIUsageLog.messages_count,
                        'successful_requests': stmt.excluded.successful_requests + AIUsageLog.successful_requests,
                        'last_success_at': stmt.excluded.last_success_at,
                        'updated_at': stmt.excluded.updated_at
                    }
                )
                
                await session.execute(stmt)
                await session.commit()
                
                logger.info("✅ Daily message usage incremented successfully with UPSERT")
                return True
                
        except Exception as e:
            logger.error("💥 Failed to increment daily message usage with UPSERT", 
                        bot_id=bot_id,
                        user_id=user_id,
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            return False

    @staticmethod
    async def set_daily_message_limit(bot_id: str, limit: int) -> bool:
        """Установить дневной лимит сообщений"""
        from database.models import UserBot
        
        try:
            async with get_db_session() as session:
                # Получаем бота
                result = await session.execute(
                    select(UserBot).where(UserBot.bot_id == bot_id)
                )
                bot = result.scalar_one_or_none()
                
                if not bot:
                    return False
                
                # Обновляем настройки в зависимости от типа агента
                if bot.ai_assistant_type == 'openai':
                    if not bot.openai_settings:
                        bot.openai_settings = {}
                    current_settings = bot.openai_settings.copy()
                    current_settings['daily_message_limit'] = limit
                    
                    await session.execute(
                        update(UserBot)
                        .where(UserBot.bot_id == bot_id)
                        .values(openai_settings=current_settings)
                    )
                elif bot.ai_assistant_type in ['chatforyou', 'protalk']:
                    if not bot.external_settings:
                        bot.external_settings = {}
                    current_settings = bot.external_settings.copy()
                    current_settings['daily_message_limit'] = limit
                    
                    await session.execute(
                        update(UserBot)
                        .where(UserBot.bot_id == bot_id)
                        .values(external_settings=current_settings)
                    )
                
                await session.commit()
                
                logger.info("✅ Daily message limit updated", 
                           bot_id=bot_id,
                           limit=limit)
                
                return True
                
        except Exception as e:
            logger.error("💥 Failed to set daily message limit", 
                        bot_id=bot_id,
                        error=str(e))
            return False

    @staticmethod
    async def get_daily_message_limit(bot_id: str) -> int:
        """Получить текущий дневной лимит сообщений"""
        from database.models import UserBot
        
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    select(UserBot).where(UserBot.bot_id == bot_id)
                )
                bot = result.scalar_one_or_none()
                
                if not bot:
                    return 0
                
                if bot.ai_assistant_type == 'openai' and bot.openai_settings:
                    return bot.openai_settings.get('daily_message_limit', 0)
                elif bot.ai_assistant_type in ['chatforyou', 'protalk'] and bot.external_settings:
                    return bot.external_settings.get('daily_message_limit', 0)
                
                return 0
                
        except Exception as e:
            logger.error("💥 Failed to get daily message limit", 
                        bot_id=bot_id,
                        error=str(e))
            return 0

    # ===== AI USAGE TRACKING =====

    @staticmethod
    async def get_or_create_ai_usage(bot_id: str, user_id: int, date: datetime = None):
        """✅ ИСПРАВЛЕНО: Получить или создать запись использования ИИ с UPSERT"""
        from database.models import AIUsageLog
        
        if not date:
            # МСК timezone
            msk_tz = timezone(timedelta(hours=3))
            date = datetime.now(msk_tz).date()
        elif isinstance(date, datetime):
            date = date.date()  # Конвертируем datetime в date
        
        try:
            async with get_db_session() as session:
                # ✅ UPSERT: INSERT или получение существующей записи
                now = datetime.now()
                
                stmt = insert(AIUsageLog).values(
                    bot_id=bot_id,
                    user_id=user_id,
                    date=date,
                    messages_count=0,
                    platform_used='openai',
                    successful_requests=0,
                    failed_requests=0,
                    average_response_time=None,
                    total_tokens_used=0,
                    longest_conversation=0,
                    error_types={},
                    last_error_at=None,
                    last_success_at=None,
                    created_at=now,
                    updated_at=now
                )
                
                # ON CONFLICT: ничего не делаем, просто возвращаем существующую запись
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=['bot_id', 'user_id', 'date']
                )
                
                await session.execute(stmt)
                await session.commit()
                
                # Получаем запись (существующую или созданную)
                result = await session.execute(
                    select(AIUsageLog).where(
                        AIUsageLog.bot_id == bot_id,
                        AIUsageLog.user_id == user_id,
                        AIUsageLog.date == date
                    )
                )
                usage_log = result.scalar_one()
                
                logger.debug("📝 AI usage log retrieved/created", 
                            bot_id=bot_id,
                            user_id=user_id,
                            date=date)
                
                return usage_log
                
        except Exception as e:
            logger.error("💥 Failed to get/create AI usage log", 
                        bot_id=bot_id,
                        user_id=user_id,
                        date=date,
                        error=str(e),
                        error_type=type(e).__name__)
            raise

    @staticmethod
    async def increment_ai_usage(bot_id: str, user_id: int) -> Tuple[int, Optional[int]]:
        """✅ ИСПРАВЛЕНО: Увеличить счетчик использования ИИ с UPSERT"""
        from database.models import AIUsageLog
        
        # МСК timezone
        msk_tz = timezone(timedelta(hours=3))
        today = datetime.now(msk_tz).date()
        now = datetime.now()
        
        try:
            async with get_db_session() as session:
                # ✅ UPSERT для увеличения счетчика
                stmt = insert(AIUsageLog).values(
                    bot_id=bot_id,
                    user_id=user_id,
                    date=today,
                    messages_count=1,
                    platform_used='openai',
                    successful_requests=1,
                    failed_requests=0,
                    average_response_time=None,
                    total_tokens_used=0,
                    longest_conversation=0,
                    error_types={},
                    last_error_at=None,
                    last_success_at=now,
                    created_at=now,
                    updated_at=now
                )
                
                stmt = stmt.on_conflict_do_update(
                    index_elements=['bot_id', 'user_id', 'date'],
                    set_={
                        'messages_count': stmt.excluded.messages_count + AIUsageLog.messages_count,
                        'successful_requests': stmt.excluded.successful_requests + AIUsageLog.successful_requests,
                        'last_success_at': stmt.excluded.last_success_at,
                        'updated_at': stmt.excluded.updated_at
                    }
                )
                
                await session.execute(stmt)
                await session.commit()
                
                # Получаем обновленное значение
                result = await session.execute(
                    select(AIUsageLog.messages_count).where(
                        AIUsageLog.bot_id == bot_id,
                        AIUsageLog.user_id == user_id,
                        AIUsageLog.date == today
                    )
                )
                new_count = result.scalar_one()
                
                # Получаем лимит из настроек бота
                daily_limit = await MessageManager.get_daily_message_limit(bot_id)
                
                logger.debug("📈 AI usage incremented with UPSERT", 
                            bot_id=bot_id,
                            user_id=user_id,
                            new_count=new_count,
                            daily_limit=daily_limit)
                
                return new_count, daily_limit if daily_limit > 0 else None
                
        except Exception as e:
            logger.error("💥 Failed to increment AI usage with UPSERT", 
                        bot_id=bot_id,
                        user_id=user_id,
                        error=str(e),
                        error_type=type(e).__name__)
            raise

    @staticmethod
    async def get_ai_usage_today(bot_id: str, user_id: int) -> int:
        """Получить количество использований ИИ сегодня"""
        # МСК timezone
        msk_tz = timezone(timedelta(hours=3))
        today = datetime.now(msk_tz).date()
        
        usage_log = await MessageManager.get_or_create_ai_usage(bot_id, user_id, today)
        return usage_log.messages_count

    # ===== MESSAGE ANALYTICS =====

    @staticmethod
    async def get_bot_message_stats(bot_id: str, days: int = 30) -> dict:
        """Получить статистику сообщений бота за период"""
        from database.models import AIUsageLog, UserBot
        
        start_date = datetime.now() - timedelta(days=days)
        
        async with get_db_session() as session:
            # Статистика сообщений ИИ
            ai_stats_result = await session.execute(
                select(
                    func.sum(AIUsageLog.messages_count).label('total_ai_messages'),
                    func.count(func.distinct(AIUsageLog.user_id)).label('unique_ai_users'),
                    func.count(AIUsageLog.id).label('active_days')
                ).where(
                    AIUsageLog.bot_id == bot_id,
                    AIUsageLog.date >= start_date
                )
            )
            ai_stats = ai_stats_result.first()
            
            # Информация о боте
            bot_result = await session.execute(
                select(
                    UserBot.total_messages_sent,
                    UserBot.ai_assistant_enabled,
                    UserBot.ai_assistant_type
                ).where(UserBot.bot_id == bot_id)
            )
            bot_info = bot_result.first()
            
            # Статистика по дням
            daily_stats_result = await session.execute(
                select(
                    AIUsageLog.date,
                    func.sum(AIUsageLog.messages_count).label('messages'),
                    func.count(func.distinct(AIUsageLog.user_id)).label('users')
                ).where(
                    AIUsageLog.bot_id == bot_id,
                    AIUsageLog.date >= start_date
                )
                .group_by(AIUsageLog.date)
                .order_by(AIUsageLog.date)
            )
            daily_stats = daily_stats_result.fetchall()
            
            return {
                'period_days': days,
                'bot_info': {
                    'total_messages_sent': bot_info.total_messages_sent or 0 if bot_info else 0,
                    'ai_enabled': bot_info.ai_assistant_enabled if bot_info else False,
                    'ai_type': bot_info.ai_assistant_type if bot_info else None
                },
                'ai_stats': {
                    'total_messages': int(ai_stats.total_ai_messages or 0),
                    'unique_users': int(ai_stats.unique_ai_users or 0),
                    'active_days': int(ai_stats.active_days or 0),
                    'avg_messages_per_day': round(
                        (ai_stats.total_ai_messages or 0) / max(days, 1),
                        2
                    ),
                    'avg_messages_per_user': round(
                        (ai_stats.total_ai_messages or 0) / max(ai_stats.unique_ai_users or 1, 1),
                        2
                    )
                },
                'daily_breakdown': [
                    {
                        'date': day.date.isoformat(),
                        'messages': int(day.messages),
                        'users': int(day.users)
                    }
                    for day in daily_stats
                ]
            }

    @staticmethod
    async def get_user_message_stats(user_id: int, days: int = 30) -> dict:
        """Получить статистику сообщений пользователя за период"""
        from database.models import AIUsageLog
        
        start_date = datetime.now() - timedelta(days=days)
        
        async with get_db_session() as session:
            # Общая статистика пользователя
            user_stats_result = await session.execute(
                select(
                    func.sum(AIUsageLog.messages_count).label('total_messages'),
                    func.count(func.distinct(AIUsageLog.bot_id)).label('unique_bots'),
                    func.count(AIUsageLog.id).label('active_days')
                ).where(
                    AIUsageLog.user_id == user_id,
                    AIUsageLog.date >= start_date
                )
            )
            user_stats = user_stats_result.first()
            
            # Статистика по ботам
            bot_stats_result = await session.execute(
                select(
                    AIUsageLog.bot_id,
                    func.sum(AIUsageLog.messages_count).label('messages'),
                    func.count(AIUsageLog.id).label('active_days')
                ).where(
                    AIUsageLog.user_id == user_id,
                    AIUsageLog.date >= start_date
                )
                .group_by(AIUsageLog.bot_id)
                .order_by(func.sum(AIUsageLog.messages_count).desc())
            )
            bot_stats = bot_stats_result.fetchall()
            
            return {
                'user_id': user_id,
                'period_days': days,
                'total_stats': {
                    'total_messages': int(user_stats.total_messages or 0),
                    'unique_bots': int(user_stats.unique_bots or 0),
                    'active_days': int(user_stats.active_days or 0),
                    'avg_messages_per_day': round(
                        (user_stats.total_messages or 0) / max(days, 1),
                        2
                    )
                },
                'bots_breakdown': [
                    {
                        'bot_id': bot.bot_id,
                        'messages': int(bot.messages),
                        'active_days': int(bot.active_days)
                    }
                    for bot in bot_stats
                ]
            }

    @staticmethod
    async def get_platform_message_stats(days: int = 30) -> dict:
        """Получить статистику сообщений по всем платформам"""
        from database.models import AIUsageLog, UserBot
        
        start_date = datetime.now() - timedelta(days=days)
        
        async with get_db_session() as session:
            # Статистика по типам ИИ
            platform_stats_result = await session.execute(
                select(
                    UserBot.ai_assistant_type,
                    func.sum(AIUsageLog.messages_count).label('total_messages'),
                    func.count(func.distinct(AIUsageLog.user_id)).label('unique_users'),
                    func.count(func.distinct(AIUsageLog.bot_id)).label('unique_bots')
                ).select_from(
                    AIUsageLog.__table__.join(
                        UserBot.__table__, 
                        AIUsageLog.bot_id == UserBot.bot_id
                    )
                ).where(
                    AIUsageLog.date >= start_date,
                    UserBot.ai_assistant_enabled == True
                )
                .group_by(UserBot.ai_assistant_type)
            )
            platform_stats = platform_stats_result.fetchall()
            
            # Общая статистика
            total_stats_result = await session.execute(
                select(
                    func.sum(AIUsageLog.messages_count).label('total_messages'),
                    func.count(func.distinct(AIUsageLog.user_id)).label('unique_users'),
                    func.count(func.distinct(AIUsageLog.bot_id)).label('unique_bots')
                ).where(AIUsageLog.date >= start_date)
            )
            total_stats = total_stats_result.first()
            
            return {
                'period_days': days,
                'total_stats': {
                    'total_messages': int(total_stats.total_messages or 0),
                    'unique_users': int(total_stats.unique_users or 0),
                    'unique_bots': int(total_stats.unique_bots or 0)
                },
                'platform_breakdown': [
                    {
                        'platform': platform.ai_assistant_type or 'unknown',
                        'total_messages': int(platform.total_messages),
                        'unique_users': int(platform.unique_users),
                        'unique_bots': int(platform.unique_bots),
                        'avg_messages_per_bot': round(
                            platform.total_messages / max(platform.unique_bots, 1),
                            2
                        )
                    }
                    for platform in platform_stats
                ]
            }

    # ===== UTILITY METHODS =====
    
    @staticmethod
    async def _expire_bot_cache(bot_id: str):
        """Internal method to expire bot cache"""
        try:
            # Import here to avoid circular imports
            from database.managers.cache_manager import CacheManager
            await CacheManager.expire_bot_cache(bot_id)
        except ImportError:
            # Fallback to connection method if CacheManager not available
            from database.connection import DatabaseManager
            await DatabaseManager.expire_bot_cache(bot_id)
        except Exception as e:
            logger.warning("Failed to expire bot cache", 
                          bot_id=bot_id, 
                          error=str(e))
    
    @staticmethod
    async def clear_bot_usage_logs(bot_id: str) -> bool:
        """Очистка всех логов использования ИИ для бота"""
        from database.models import AIUsageLog
        
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    AIUsageLog.__table__.delete()
                    .where(AIUsageLog.bot_id == bot_id)
                )
                await session.commit()
                
                deleted_count = result.rowcount
                logger.info("🧹 Bot usage logs cleared", 
                           bot_id=bot_id,
                           deleted_records=deleted_count)
                
                return True
                
        except Exception as e:
            logger.error("💥 Failed to clear bot usage logs", 
                        bot_id=bot_id,
                        error=str(e))
            return False
    
    @staticmethod
    async def cleanup_old_usage_logs(days: int = 90) -> int:
        """Очистка старых логов использования"""
        from database.models import AIUsageLog
        
        cutoff_date = datetime.now() - timedelta(days=days)
        
        async with get_db_session() as session:
            # Подсчитываем количество записей для удаления
            count_result = await session.execute(
                select(func.count(AIUsageLog.id))
                .where(AIUsageLog.date < cutoff_date)
            )
            count = count_result.scalar() or 0
            
            if count > 0:
                # Удаляем старые записи
                await session.execute(
                    AIUsageLog.__table__.delete()
                    .where(AIUsageLog.date < cutoff_date)
                )
                await session.commit()
                
                logger.info("🧹 Old usage logs cleaned up", 
                           days=days,
                           deleted_records=count)
            
            return count
    
    @staticmethod
    async def get_messages_summary() -> dict:
        """Получить общую сводку по сообщениям"""
        from database.models import AIUsageLog, UserBot
        
        async with get_db_session() as session:
            # Статистика за последние 30 дней
            thirty_days_ago = datetime.now() - timedelta(days=30)
            
            recent_stats_result = await session.execute(
                select(
                    func.sum(AIUsageLog.messages_count).label('recent_messages'),
                    func.count(func.distinct(AIUsageLog.user_id)).label('recent_users'),
                    func.count(func.distinct(AIUsageLog.bot_id)).label('recent_bots')
                ).where(AIUsageLog.date >= thirty_days_ago)
            )
            recent_stats = recent_stats_result.first()
            
            # Общая статистика
            total_stats_result = await session.execute(
                select(
                    func.sum(AIUsageLog.messages_count).label('total_messages'),
                    func.count(func.distinct(AIUsageLog.user_id)).label('total_users'),
                    func.count(func.distinct(AIUsageLog.bot_id)).label('total_bots')
                )
            )
            total_stats = total_stats_result.first()
            
            # Статистика по ботам с ИИ
            ai_bots_result = await session.execute(
                select(func.count(UserBot.id))
                .where(UserBot.ai_assistant_enabled == True)
            )
            ai_bots_count = ai_bots_result.scalar() or 0
            
            return {
                'recent_30_days': {
                    'messages': int(recent_stats.recent_messages or 0),
                    'users': int(recent_stats.recent_users or 0),
                    'bots': int(recent_stats.recent_bots or 0)
                },
                'all_time': {
                    'messages': int(total_stats.total_messages or 0),
                    'users': int(total_stats.total_users or 0),
                    'bots': int(total_stats.total_bots or 0)
                },
                'ai_bots_count': ai_bots_count,
                'avg_messages_per_user_30d': round(
                    (recent_stats.recent_messages or 0) / max(recent_stats.recent_users or 1, 1),
                    2
                ),
                'avg_messages_per_bot_30d': round(
                    (recent_stats.recent_messages or 0) / max(recent_stats.recent_bots or 1, 1),
                    2
                )
            }
