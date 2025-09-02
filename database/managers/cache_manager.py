"""
Cache Manager - handles all cache operations and data refresh.

Responsibilities:
- Bot data caching and invalidation
- User data caching and refresh
- AI configuration caching
- Cache statistics and monitoring
- Bulk cache operations and maintenance
"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Set
from sqlalchemy import select, update, func
import structlog

from ..connection import get_db_session

logger = structlog.get_logger()


class CacheManager:
    """Manager for cache operations and data refresh"""
    
    # ===== BOT CACHE OPERATIONS =====
    
    @staticmethod
    async def refresh_bot_data(bot_id: str):
        """Принудительное обновление данных бота из БД"""
        from database.models import UserBot
        
        async with get_db_session() as session:
            # Получаем свежие данные с populate_existing=True
            result = await session.execute(
                select(UserBot)
                .where(UserBot.bot_id == bot_id)
                .execution_options(populate_existing=True)
            )
            bot = result.scalar_one_or_none()
            
            if bot:
                # Принудительно обновляем объект
                await session.refresh(bot)
                logger.info("✅ Bot data refreshed from database", bot_id=bot_id)
                return bot
            else:
                logger.warning("❌ Bot not found for refresh", bot_id=bot_id)
                return None
    
    @staticmethod
    async def expire_bot_cache(bot_id: str):
        """Очистка кэша для конкретного бота"""
        from database.models import UserBot
        
        async with get_db_session() as session:
            # Получаем объект и помечаем как expired
            result = await session.execute(
                select(UserBot).where(UserBot.bot_id == bot_id)
            )
            bot = result.scalar_one_or_none()
            
            if bot:
                session.expire(bot)
                logger.info("✅ Bot cache expired", bot_id=bot_id)
                return True
            else:
                logger.warning("❌ Bot not found for cache expiration", bot_id=bot_id)
                return False
    
    @staticmethod 
    async def get_fresh_bot_data(bot_id: str):
        """Получение всегда свежих данных бота (без кэша)"""
        from database.models import UserBot
        
        async with get_db_session() as session:
            # Всегда получаем свежие данные из БД
            result = await session.execute(
                select(UserBot)
                .where(UserBot.bot_id == bot_id)
                .execution_options(populate_existing=True)
            )
            bot = result.scalar_one_or_none()
            
            if bot:
                logger.debug("🔄 Fresh bot data retrieved", bot_id=bot_id)
            else:
                logger.warning("❌ Bot not found for fresh data", bot_id=bot_id)
            
            return bot
    
    @staticmethod
    async def refresh_multiple_bots(bot_ids: List[str]) -> Dict[str, bool]:
        """Обновление данных нескольких ботов"""
        from database.models import UserBot
        
        results = {}
        
        if not bot_ids:
            return results
        
        async with get_db_session() as session:
            # Получаем все боты одним запросом
            result = await session.execute(
                select(UserBot)
                .where(UserBot.bot_id.in_(bot_ids))
                .execution_options(populate_existing=True)
            )
            bots = result.scalars().all()
            
            # Обновляем каждого бота
            for bot in bots:
                try:
                    await session.refresh(bot)
                    results[bot.bot_id] = True
                    logger.debug("✅ Bot refreshed", bot_id=bot.bot_id)
                except Exception as e:
                    results[bot.bot_id] = False
                    logger.error("❌ Failed to refresh bot", 
                                bot_id=bot.bot_id,
                                error=str(e))
            
            # Отмечаем отсутствующие боты
            found_bot_ids = {bot.bot_id for bot in bots}
            for bot_id in bot_ids:
                if bot_id not in found_bot_ids:
                    results[bot_id] = False
                    logger.warning("❌ Bot not found for refresh", bot_id=bot_id)
        
        logger.info("🔄 Multiple bots refresh completed", 
                   total_requested=len(bot_ids),
                   successful=sum(results.values()),
                   failed=len(results) - sum(results.values()))
        
        return results
    
    @staticmethod
    async def expire_multiple_bot_caches(bot_ids: List[str]) -> int:
        """Очистка кэша нескольких ботов"""
        from database.models import UserBot
        
        if not bot_ids:
            return 0
        
        expired_count = 0
        
        async with get_db_session() as session:
            # Получаем все боты одним запросом
            result = await session.execute(
                select(UserBot).where(UserBot.bot_id.in_(bot_ids))
            )
            bots = result.scalars().all()
            
            # Помечаем каждого как expired
            for bot in bots:
                try:
                    session.expire(bot)
                    expired_count += 1
                    logger.debug("✅ Bot cache expired", bot_id=bot.bot_id)
                except Exception as e:
                    logger.error("❌ Failed to expire bot cache", 
                                bot_id=bot.bot_id,
                                error=str(e))
        
        logger.info("🗑️ Multiple bot caches expired", 
                   expired_count=expired_count,
                   total_requested=len(bot_ids))
        
        return expired_count
    
    # ===== USER CACHE OPERATIONS =====
    
    @staticmethod
    async def refresh_user_data(user_id: int):
        """Принудительное обновление данных пользователя из БД"""
        from database.models import User
        
        async with get_db_session() as session:
            # Получаем свежие данные с populate_existing=True
            result = await session.execute(
                select(User)
                .where(User.id == user_id)
                .execution_options(populate_existing=True)
            )
            user = result.scalar_one_or_none()
            
            if user:
                # Принудительно обновляем объект
                await session.refresh(user)
                logger.info("✅ User data refreshed from database", user_id=user_id)
                return user
            else:
                logger.warning("❌ User not found for refresh", user_id=user_id)
                return None
    
    @staticmethod
    async def expire_user_cache(user_id: int):
        """Очистка кэша для конкретного пользователя"""
        from database.models import User
        
        async with get_db_session() as session:
            # Получаем объект и помечаем как expired
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if user:
                session.expire(user)
                logger.info("✅ User cache expired", user_id=user_id)
                return True
            else:
                logger.warning("❌ User not found for cache expiration", user_id=user_id)
                return False
    
    @staticmethod
    async def get_fresh_user_data(user_id: int):
        """Получение всегда свежих данных пользователя (без кэша)"""
        from database.models import User
        
        async with get_db_session() as session:
            # Всегда получаем свежие данные из БД
            result = await session.execute(
                select(User)
                .where(User.id == user_id)
                .execution_options(populate_existing=True)
            )
            user = result.scalar_one_or_none()
            
            if user:
                logger.debug("🔄 Fresh user data retrieved", user_id=user_id)
            else:
                logger.warning("❌ User not found for fresh data", user_id=user_id)
            
            return user
    
    @staticmethod
    async def refresh_user_with_bots(user_id: int) -> Dict[str, Any]:
        """Обновление данных пользователя вместе со всеми его ботами"""
        # Обновляем пользователя
        user = await CacheManager.refresh_user_data(user_id)
        
        if not user:
            return {'user': None, 'bots': {}}
        
        # Получаем ID всех ботов пользователя
        from database.models import UserBot
        
        async with get_db_session() as session:
            bots_result = await session.execute(
                select(UserBot.bot_id).where(UserBot.user_id == user_id)
            )
            bot_ids = [row.bot_id for row in bots_result.fetchall()]
        
        # Обновляем всех ботов
        bots_refresh_results = await CacheManager.refresh_multiple_bots(bot_ids)
        
        logger.info("🔄 User with bots refreshed", 
                   user_id=user_id,
                   bots_count=len(bot_ids),
                   bots_refreshed=sum(bots_refresh_results.values()))
        
        return {
            'user': user,
            'bots': bots_refresh_results
        }
    
    # ===== AI CONFIGURATION CACHE =====
    
    @staticmethod
    async def expire_ai_config_cache(bot_id: str):
        """Очистка кэша конфигурации ИИ"""
        # В текущей реализации конфигурация ИИ хранится в UserBot,
        # поэтому используем expire_bot_cache
        result = await CacheManager.expire_bot_cache(bot_id)
        
        if result:
            logger.info("✅ AI config cache expired", bot_id=bot_id)
        
        return result
    
    @staticmethod
    async def refresh_ai_config(bot_id: str):
        """Обновление кэша конфигурации ИИ"""
        bot = await CacheManager.refresh_bot_data(bot_id)
        
        if bot and bot.ai_assistant_enabled:
            logger.info("✅ AI config refreshed", 
                       bot_id=bot_id,
                       ai_type=bot.ai_assistant_type)
            return True
        
        return False
    
    @staticmethod
    async def expire_openai_agent_cache(agent_id: str):
        """Очистка кэша OpenAI агента по agent_id"""
        from database.models import UserBot
        
        async with get_db_session() as session:
            # Находим бота по agent_id
            result = await session.execute(
                select(UserBot.bot_id)
                .where(UserBot.openai_agent_id == agent_id)
            )
            bot_id = result.scalar_one_or_none()
            
            if bot_id:
                return await CacheManager.expire_bot_cache(bot_id)
            else:
                logger.warning("❌ Bot not found for OpenAI agent", agent_id=agent_id)
                return False
    
    # ===== BULK CACHE OPERATIONS =====
    
    @staticmethod
    async def expire_all_user_caches(user_id: int) -> Dict[str, Any]:
        """Очистка всех кэшей пользователя (пользователь + все его боты)"""
        # Очищаем кэш пользователя
        user_expired = await CacheManager.expire_user_cache(user_id)
        
        # Получаем ID всех ботов пользователя
        from database.models import UserBot
        
        async with get_db_session() as session:
            bots_result = await session.execute(
                select(UserBot.bot_id).where(UserBot.user_id == user_id)
            )
            bot_ids = [row.bot_id for row in bots_result.fetchall()]
        
        # Очищаем кэш всех ботов
        bots_expired = await CacheManager.expire_multiple_bot_caches(bot_ids)
        
        result = {
            'user_expired': user_expired,
            'bots_expired': bots_expired,
            'total_bots': len(bot_ids)
        }
        
        logger.info("🗑️ All user caches expired", 
                   user_id=user_id,
                   **result)
        
        return result
    
    @staticmethod
    async def refresh_all_active_bots() -> Dict[str, Any]:
        """Обновление кэша всех активных ботов"""
        from database.models import UserBot
        
        async with get_db_session() as session:
            # Получаем ID всех активных ботов
            result = await session.execute(
                select(UserBot.bot_id)
                .where(UserBot.status == 'active')
            )
            active_bot_ids = [row.bot_id for row in result.fetchall()]
        
        if not active_bot_ids:
            logger.info("No active bots found for refresh")
            return {'total_bots': 0, 'refreshed': 0, 'failed': 0}
        
        # Обновляем всех активных ботов
        refresh_results = await CacheManager.refresh_multiple_bots(active_bot_ids)
        
        result = {
            'total_bots': len(active_bot_ids),
            'refreshed': sum(refresh_results.values()),
            'failed': len(refresh_results) - sum(refresh_results.values())
        }
        
        logger.info("🔄 All active bots refresh completed", **result)
        
        return result
    
    @staticmethod
    async def expire_all_active_bot_caches() -> int:
        """Очистка кэша всех активных ботов"""
        from database.models import UserBot
        
        async with get_db_session() as session:
            # Получаем ID всех активных ботов
            result = await session.execute(
                select(UserBot.bot_id)
                .where(UserBot.status == 'active')
            )
            active_bot_ids = [row.bot_id for row in result.fetchall()]
        
        if not active_bot_ids:
            logger.info("No active bots found for cache expiration")
            return 0
        
        # Очищаем кэш всех активных ботов
        expired_count = await CacheManager.expire_multiple_bot_caches(active_bot_ids)
        
        logger.info("🗑️ All active bot caches expired", 
                   expired_count=expired_count,
                   total_bots=len(active_bot_ids))
        
        return expired_count
    
    # ===== CACHE ANALYTICS AND MONITORING =====
    
    @staticmethod
    async def get_cache_statistics() -> Dict[str, Any]:
        """Получение статистики кэширования"""
        from database.models import UserBot, User
        
        async with get_db_session() as session:
            # Статистика ботов
            bots_stats_result = await session.execute(
                select(
                    func.count(UserBot.id).label('total_bots'),
                    func.sum(func.case([(UserBot.status == 'active', 1)], else_=0)).label('active_bots'),
                    func.sum(func.case([(UserBot.ai_assistant_enabled == True, 1)], else_=0)).label('ai_enabled_bots'),
                    func.max(UserBot.updated_at).label('last_bot_update')
                )
            )
            bots_stats = bots_stats_result.first()
            
            # Статистика пользователей
            users_stats_result = await session.execute(
                select(
                    func.count(User.id).label('total_users'),
                    func.sum(func.case([(User.tokens_limit_total.isnot(None), 1)], else_=0)).label('users_with_tokens'),
                    func.max(User.updated_at).label('last_user_update')
                )
            )
            users_stats = users_stats_result.first()
            
            # Статистика обновлений за последний час
            one_hour_ago = datetime.now() - timedelta(hours=1)
            
            recent_updates_result = await session.execute(
                select(
                    func.count(UserBot.id).label('bots_updated_last_hour')
                ).where(UserBot.updated_at >= one_hour_ago)
            )
            recent_bots_updates = recent_updates_result.scalar() or 0
            
            recent_user_updates_result = await session.execute(
                select(
                    func.count(User.id).label('users_updated_last_hour')
                ).where(User.updated_at >= one_hour_ago)
            )
            recent_user_updates = recent_user_updates_result.scalar() or 0
            
            return {
                'bots': {
                    'total': int(bots_stats.total_bots or 0),
                    'active': int(bots_stats.active_bots or 0),
                    'ai_enabled': int(bots_stats.ai_enabled_bots or 0),
                    'last_update': bots_stats.last_bot_update,
                    'updated_last_hour': recent_bots_updates
                },
                'users': {
                    'total': int(users_stats.total_users or 0),
                    'with_tokens': int(users_stats.users_with_tokens or 0),
                    'last_update': users_stats.last_user_update,
                    'updated_last_hour': recent_user_updates
                },
                'cache_health': {
                    'bot_activity_rate': round(
                        (recent_bots_updates / max(bots_stats.total_bots or 1, 1)) * 100,
                        2
                    ),
                    'user_activity_rate': round(
                        (recent_user_updates / max(users_stats.total_users or 1, 1)) * 100,
                        2
                    ),
                    'recommendation': CacheManager._get_cache_recommendation(
                        recent_bots_updates, 
                        recent_user_updates,
                        int(bots_stats.total_bots or 0),
                        int(users_stats.total_users or 0)
                    )
                }
            }
    
    @staticmethod
    def _get_cache_recommendation(recent_bots: int, recent_users: int, total_bots: int, total_users: int) -> str:
        """Генерация рекомендаций по кэшированию"""
        bot_activity_rate = (recent_bots / max(total_bots, 1)) * 100
        user_activity_rate = (recent_users / max(total_users, 1)) * 100
        
        if bot_activity_rate > 20 or user_activity_rate > 10:
            return "high_activity_consider_cache_optimization"
        elif bot_activity_rate < 5 and user_activity_rate < 2:
            return "low_activity_cache_is_effective"
        else:
            return "normal_activity_cache_working_well"
    
    @staticmethod
    async def get_stale_data_report(hours: int = 24) -> Dict[str, Any]:
        """Отчет о устаревших данных"""
        from database.models import UserBot, User
        
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        async with get_db_session() as session:
            # Устаревшие боты
            stale_bots_result = await session.execute(
                select(
                    UserBot.bot_id,
                    UserBot.bot_name,
                    UserBot.status,
                    UserBot.updated_at
                ).where(
                    UserBot.updated_at < cutoff_time,
                    UserBot.status == 'active'
                )
                .order_by(UserBot.updated_at)
                .limit(50)
            )
            stale_bots = stale_bots_result.fetchall()
            
            # Устаревшие пользователи
            stale_users_result = await session.execute(
                select(
                    User.id,
                    User.username,
                    User.updated_at
                ).where(User.updated_at < cutoff_time)
                .order_by(User.updated_at)
                .limit(50)
            )
            stale_users = stale_users_result.fetchall()
            
            # Общая статистика
            total_stale_bots_result = await session.execute(
                select(func.count(UserBot.id))
                .where(
                    UserBot.updated_at < cutoff_time,
                    UserBot.status == 'active'
                )
            )
            total_stale_bots = total_stale_bots_result.scalar() or 0
            
            total_stale_users_result = await session.execute(
                select(func.count(User.id))
                .where(User.updated_at < cutoff_time)
            )
            total_stale_users = total_stale_users_result.scalar() or 0
            
            return {
                'cutoff_hours': hours,
                'cutoff_time': cutoff_time,
                'summary': {
                    'total_stale_bots': total_stale_bots,
                    'total_stale_users': total_stale_users,
                    'needs_refresh': total_stale_bots > 0 or total_stale_users > 0
                },
                'stale_bots': [
                    {
                        'bot_id': bot.bot_id,
                        'bot_name': bot.bot_name,
                        'status': bot.status,
                        'last_update': bot.updated_at,
                        'hours_stale': round(
                            (datetime.now() - bot.updated_at).total_seconds() / 3600,
                            2
                        )
                    }
                    for bot in stale_bots
                ],
                'stale_users': [
                    {
                        'user_id': user.id,
                        'username': user.username,
                        'last_update': user.updated_at,
                        'hours_stale': round(
                            (datetime.now() - user.updated_at).total_seconds() / 3600,
                            2
                        )
                    }
                    for user in stale_users
                ]
            }
    
    # ===== CACHE MAINTENANCE =====
    
    @staticmethod
    async def scheduled_cache_refresh(max_bots: int = 100) -> Dict[str, Any]:
        """Плановое обновление кэша (можно запускать по расписанию)"""
        logger.info("🔄 Starting scheduled cache refresh", max_bots=max_bots)
        
        # Получаем отчет о устаревших данных за последние 6 часов
        stale_report = await CacheManager.get_stale_data_report(hours=6)
        
        # Обновляем самые устаревшие боты
        stale_bot_ids = [
            bot['bot_id'] for bot in stale_report['stale_bots'][:max_bots]
        ]
        
        refresh_results = {}
        if stale_bot_ids:
            refresh_results = await CacheManager.refresh_multiple_bots(stale_bot_ids)
        
        # Обновляем устаревших пользователей (топ 20)
        stale_user_ids = [
            user['user_id'] for user in stale_report['stale_users'][:20]
        ]
        
        user_refresh_count = 0
        for user_id in stale_user_ids:
            try:
                await CacheManager.refresh_user_data(user_id)
                user_refresh_count += 1
            except Exception as e:
                logger.error("Failed to refresh user in scheduled task",
                           user_id=user_id,
                           error=str(e))
        
        result = {
            'stale_data_report': stale_report['summary'],
            'bots_refreshed': sum(refresh_results.values()) if refresh_results else 0,
            'bots_failed': len(refresh_results) - sum(refresh_results.values()) if refresh_results else 0,
            'users_refreshed': user_refresh_count,
            'total_operations': len(refresh_results) + user_refresh_count if refresh_results else user_refresh_count
        }
        
        logger.info("✅ Scheduled cache refresh completed", **result)
        
        return result
    
    @staticmethod
    async def emergency_cache_clear() -> Dict[str, Any]:
        """Экстренная очистка всех кэшей (использовать только при необходимости)"""
        logger.warning("🚨 Emergency cache clear initiated")
        
        # Очищаем кэш всех активных ботов
        active_bots_expired = await CacheManager.expire_all_active_bot_caches()
        
        # Получаем и очищаем кэш пользователей с токенами
        from database.models import User
        
        async with get_db_session() as session:
            users_result = await session.execute(
                select(User.id).where(User.tokens_limit_total.isnot(None))
            )
            token_user_ids = [row.id for row in users_result.fetchall()]
        
        users_expired = 0
        for user_id in token_user_ids:
            try:
                if await CacheManager.expire_user_cache(user_id):
                    users_expired += 1
            except Exception as e:
                logger.error("Failed to expire user cache in emergency clear",
                           user_id=user_id,
                           error=str(e))
        
        result = {
            'bots_cache_expired': active_bots_expired,
            'users_cache_expired': users_expired,
            'total_operations': active_bots_expired + users_expired
        }
        
        logger.warning("🚨 Emergency cache clear completed", **result)
        
        return result
    
    @staticmethod
    async def get_cache_health_score() -> Dict[str, Any]:
        """Получение общего индекса здоровья кэша"""
        try:
            # Получаем статистику
            stats = await CacheManager.get_cache_statistics()
            
            # Получаем отчет о устаревших данных
            stale_report = await CacheManager.get_stale_data_report(hours=12)
            
            # Вычисляем метрики здоровья
            bot_activity_rate = stats['cache_health']['bot_activity_rate']
            user_activity_rate = stats['cache_health']['user_activity_rate']
            
            stale_bot_percentage = (
                stale_report['summary']['total_stale_bots'] / 
                max(stats['bots']['total'], 1)
            ) * 100
            
            stale_user_percentage = (
                stale_report['summary']['total_stale_users'] / 
                max(stats['users']['total'], 1)
            ) * 100
            
            # Вычисляем общий индекс (0-100)
            health_score = 100
            
            # Снижаем за высокую активность (частые обновления)
            if bot_activity_rate > 15:
                health_score -= min(20, (bot_activity_rate - 15) * 2)
            
            if user_activity_rate > 8:
                health_score -= min(15, (user_activity_rate - 8) * 2)
            
            # Снижаем за устаревшие данные
            health_score -= min(30, stale_bot_percentage * 1.5)
            health_score -= min(20, stale_user_percentage * 1.0)
            
            health_score = max(0, health_score)
            
            # Определяем статус
            if health_score >= 80:
                status = "excellent"
                color = "🟢"
            elif health_score >= 60:
                status = "good"
                color = "🟡"
            elif health_score >= 40:
                status = "fair"
                color = "🟠"
            else:
                status = "poor"
                color = "🔴"
            
            return {
                'health_score': round(health_score, 1),
                'status': status,
                'color': color,
                'metrics': {
                    'bot_activity_rate': bot_activity_rate,
                    'user_activity_rate': user_activity_rate,
                    'stale_bot_percentage': round(stale_bot_percentage, 2),
                    'stale_user_percentage': round(stale_user_percentage, 2)
                },
                'recommendations': CacheManager._get_health_recommendations(
                    health_score, 
                    bot_activity_rate, 
                    user_activity_rate,
                    stale_bot_percentage,
                    stale_user_percentage
                ),
                'statistics': stats,
                'stale_summary': stale_report['summary']
            }
            
        except Exception as e:
            logger.error("💥 Failed to calculate cache health score", error=str(e))
            return {
                'health_score': 0,
                'status': 'error',
                'color': '🔴',
                'error': str(e)
            }
    
    @staticmethod
    def _get_health_recommendations(
        health_score: float,
        bot_activity: float,
        user_activity: float,
        stale_bots: float,
        stale_users: float
    ) -> List[str]:
        """Генерация рекомендаций по улучшению здоровья кэша"""
        recommendations = []
        
        if health_score < 40:
            recommendations.append("Critical: Consider emergency cache clear and optimization")
        
        if stale_bots > 20:
            recommendations.append("High stale bot percentage: Schedule more frequent bot cache refresh")
        
        if stale_users > 15:
            recommendations.append("High stale user percentage: Schedule more frequent user cache refresh")
        
        if bot_activity > 20:
            recommendations.append("Very high bot activity: Consider cache optimization or batching")
        
        if user_activity > 10:
            recommendations.append("High user activity: Monitor cache performance closely")
        
        if 40 <= health_score < 60:
            recommendations.append("Fair cache health: Schedule routine maintenance")
        
        if health_score >= 80:
            recommendations.append("Excellent cache health: Current strategy is working well")
        
        if not recommendations:
            recommendations.append("Cache health is acceptable: Continue current practices")
        
        return recommendations
