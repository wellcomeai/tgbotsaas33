import asyncio
import json
import random
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import func, select
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional, List, Union, Tuple, Dict
from datetime import datetime, timedelta
from decimal import Decimal
import structlog

from config import settings
from database.models import Base

logger = structlog.get_logger()

# Global engine instance
engine = None
async_session_factory = None


async def init_database():
    """Initialize database connection and create tables"""
    global engine, async_session_factory
    
    try:
        # Create async engine
        engine = create_async_engine(
            settings.database_url.replace("postgresql://", "postgresql+asyncpg://"),
            poolclass=NullPool,
            echo=settings.debug,
            future=True
        )
        
        # Create session factory
        # ✅ ОСТАВЛЯЕМ expire_on_commit=False для async, но добавим принудительный refresh
        async_session_factory = async_sessionmaker(
            engine, 
            class_=AsyncSession, 
            expire_on_commit=False  # Для async compatibility
        )
        
        # Create tables
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            
        logger.info("Database initialized successfully")
        
    except Exception as e:
        logger.error("Failed to initialize database", error=str(e))
        raise


async def close_database():
    """Close database connection"""
    global engine
    
    if engine:
        await engine.dispose()
        logger.info("Database connection closed")


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Get database session context manager"""
    if not async_session_factory:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


class DatabaseManager:
    """Database operations manager - WILL BE SPLIT INTO MODULES"""
    
    # ===== USER METHODS =====
    
    @staticmethod
    async def get_user(user_id: int) -> AsyncSession:
        """Get user by ID"""
        from database.models import User
        
        async with get_db_session() as session:
            result = await session.get(User, user_id)
            return result
    
    @staticmethod
    async def create_or_update_user(user_data: dict) -> AsyncSession:
        """Create or update user"""
        from database.models import User
        from sqlalchemy import select
        
        async with get_db_session() as session:
            # Check if user exists
            result = await session.execute(
                select(User).where(User.id == user_data['id'])
            )
            user = result.scalar_one_or_none()
            
            if user:
                # Update existing user
                for key, value in user_data.items():
                    if hasattr(user, key):
                        setattr(user, key, value)
            else:
                # Create new user
                user = User(**user_data)
                session.add(user)
            
            await session.commit()
            await session.refresh(user)
            return user
    
    @staticmethod
    async def create_or_update_user_with_tokens(user_data: dict, admin_chat_id: int = None) -> AsyncSession:
        """✅ НОВЫЙ: Create or update user with token initialization"""
        from database.models import User
        from sqlalchemy import select
        
        logger.info("🚀 Creating/updating user with token initialization", 
                   user_id=user_data.get('id'),
                   admin_chat_id=admin_chat_id)
        
        async with get_db_session() as session:
            # Check if user exists
            result = await session.execute(
                select(User).where(User.id == user_data['id'])
            )
            user = result.scalar_one_or_none()
            
            if user:
                # Update existing user
                for key, value in user_data.items():
                    if hasattr(user, key):
                        setattr(user, key, value)
                        
                # Initialize tokens if not already done
                if not user.tokens_limit_total:
                    user.tokens_limit_total = 500000
                    user.tokens_used_total = 0
                    if admin_chat_id:
                        user.tokens_admin_chat_id = admin_chat_id
                    user.tokens_initialized_at = datetime.now()
                    
                logger.info("✅ User updated with token check", 
                           user_id=user.id,
                           tokens_limit=user.tokens_limit_total)
            else:
                # Create new user with tokens
                user_data.update({
                    'tokens_limit_total': 500000,
                    'tokens_used_total': 0,
                    'tokens_admin_chat_id': admin_chat_id,
                    'tokens_initialized_at': datetime.now()
                })
                
                user = User(**user_data)
                session.add(user)
                
                logger.info("✅ New user created with tokens", 
                           user_id=user_data['id'],
                           tokens_limit=500000)
            
            await session.commit()
            await session.refresh(user)
            return user

    # ===== BOT METHODS =====
    
    @staticmethod
    async def get_user_bots(user_id: int):
        """Get all bots for a user"""
        from database.models import UserBot
        from sqlalchemy import select
        
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
            return bot
    
    @staticmethod
    async def get_bot_by_id(bot_id: str, fresh: bool = False):
        """✅ ОПТИМИЗИРОВАНО: Get bot by ID with optional fresh data"""
        from database.models import UserBot
        from sqlalchemy import select
        
        async with get_db_session() as session:
            if fresh:
                # ✅ ОДИН запрос с принудительным обновлением
                result = await session.execute(
                    select(UserBot)
                    .where(UserBot.bot_id == bot_id)
                    .execution_options(populate_existing=True)
                )
                bot = result.scalar_one_or_none()
                logger.info("🔄 Retrieved fresh bot data", 
                           bot_id=bot_id, 
                           found=bool(bot))
                return bot
            else:
                # ✅ Обычное получение (с кэшем)
                result = await session.execute(
                    select(UserBot).where(UserBot.bot_id == bot_id)
                )
                return result.scalar_one_or_none()

    # ===== BOT SUBSCRIPTION METHODS =====
    
    @staticmethod
    async def get_subscription_settings(bot_id: str, fresh: bool = False) -> Optional[dict]:
        """✅ НОВЫЙ: Get current subscription settings for bot"""
        from database.models import UserBot
        from sqlalchemy import select
        
        logger.info("🔍 Getting subscription settings", 
                   bot_id=bot_id, 
                   fresh=fresh)
        
        try:
            bot = await DatabaseManager.get_bot_by_id(bot_id, fresh=fresh)
            
            if not bot:
                return None
            
            return {
                'bot_id': bot.bot_id,
                'subscription_check_enabled': bot.subscription_check_enabled,
                'subscription_channel_id': bot.subscription_channel_id,
                'subscription_channel_username': bot.subscription_channel_username,
                'subscription_deny_message': bot.subscription_deny_message,
                'updated_at': bot.updated_at.isoformat() if bot.updated_at else None
            }
            
        except Exception as e:
            logger.error("💥 Failed to get subscription settings", 
                        bot_id=bot_id,
                        error=str(e),
                        error_type=type(e).__name__)
            return None

    @staticmethod
    async def update_subscription_settings(
        bot_id: str, 
        enabled: bool = None,
        channel_id: str = None,
        channel_username: str = None,
        deny_message: str = None,
        settings: dict = None
    ) -> dict:
        """✅ ИСПРАВЛЕНО: Update subscription settings and return fresh bot data"""
        from database.models import UserBot
        from sqlalchemy import update
        
        logger.info("🔄 Updating subscription settings", 
                   bot_id=bot_id, 
                   enabled=enabled,
                   channel_id=channel_id,
                   channel_username=channel_username,
                   settings=settings)
        
        try:
            # Определяем значения из параметров или settings
            if settings:
                # Если переданы settings, используем их
                enabled_val = settings.get('enabled', enabled)
                channel_id_val = settings.get('channel_id', channel_id)
                channel_username_val = settings.get('channel_username', channel_username)
                deny_message_val = settings.get('deny_message', deny_message)
            else:
                # Используем прямые параметры
                enabled_val = enabled
                channel_id_val = channel_id
                channel_username_val = channel_username
                deny_message_val = deny_message
            
            # Подготавливаем данные для обновления (только не-None значения)
            update_data = {'updated_at': datetime.now()}
            
            if enabled_val is not None:
                update_data['subscription_check_enabled'] = enabled_val
            if channel_id_val is not None:
                update_data['subscription_channel_id'] = channel_id_val
            if channel_username_val is not None:
                update_data['subscription_channel_username'] = channel_username_val
            if deny_message_val is not None:
                update_data['subscription_deny_message'] = deny_message_val
            
            async with get_db_session() as session:
                await session.execute(
                    update(UserBot)
                    .where(UserBot.bot_id == bot_id)
                    .values(**update_data)
                )
                await session.commit()
                
                logger.info("✅ Subscription settings updated successfully", 
                           bot_id=bot_id,
                           updated_fields=list(update_data.keys()))
                
                # 🔄 Получаем свежие данные бота после обновления
                fresh_bot = await DatabaseManager.get_bot_by_id(bot_id, fresh=True)
                
                if fresh_bot:
                    return {
                        'success': True,
                        'bot_data': {
                            'bot_id': fresh_bot.bot_id,
                            'subscription_check_enabled': fresh_bot.subscription_check_enabled,
                            'subscription_channel_id': fresh_bot.subscription_channel_id,
                            'subscription_channel_username': fresh_bot.subscription_channel_username,
                            'subscription_deny_message': fresh_bot.subscription_deny_message,
                            'updated_at': fresh_bot.updated_at.isoformat() if fresh_bot.updated_at else None
                        }
                    }
                else:
                    return {'success': True, 'bot_data': None}
                
        except Exception as e:
            logger.error("💥 Failed to update subscription settings", 
                        bot_id=bot_id,
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            return {'success': False, 'error': str(e)}

    # ===== USER SUBSCRIPTION METHODS =====
    
    @staticmethod
    async def check_user_subscription(user_id: int) -> bool:
        """Check if user has active subscription"""
        from database.models import User
        from sqlalchemy import select
        
        async with get_db_session() as session:
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                return False
            
            # Free plan is always active
            if user.plan == 'free':
                return True
            
            # Check paid subscription
            if not user.subscription_active:
                return False
            
            if user.subscription_expires_at is None:
                return False
            
            return user.subscription_expires_at > datetime.now()
    
    @staticmethod
    async def update_user_subscription(
        user_id: int,
        plan: str,
        expires_at: Optional[datetime] = None,
        active: bool = True
    ):
        """Update user subscription"""
        from database.models import User
        from sqlalchemy import update, select
        
        async with get_db_session() as session:
            await session.execute(
                update(User)
                .where(User.id == user_id)
                .values(
                    plan=plan,
                    subscription_expires_at=expires_at,
                    subscription_active=active,
                    last_payment_date=datetime.now() if active else None,
                    updated_at=datetime.now()
                )
            )
            await session.commit()
            
            logger.info("User subscription updated", 
                       user_id=user_id, 
                       plan=plan, 
                       expires_at=expires_at,
                       active=active)
    
    @staticmethod
    async def get_expired_subscriptions():
        """Get users with expired subscriptions"""
        from database.models import User
        from sqlalchemy import select
        
        async with get_db_session() as session:
            result = await session.execute(
                select(User)
                .where(
                    User.subscription_active == True,
                    User.subscription_expires_at < datetime.now()
                )
            )
            return result.scalars().all()
    
    # ===== CACHE MANAGEMENT METHODS =====
    
    @staticmethod
    async def refresh_bot_data(bot_id: str):
        """✅ НОВЫЙ: Принудительное обновление данных бота из БД"""
        from database.models import UserBot
        from sqlalchemy import select
        
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
        """✅ НОВЫЙ: Очистка кэша для конкретного бота"""
        from database.models import UserBot
        from sqlalchemy import select
        
        async with get_db_session() as session:
            # Получаем объект и помечаем как expired
            result = await session.execute(
                select(UserBot).where(UserBot.bot_id == bot_id)
            )
            bot = result.scalar_one_or_none()
            
            if bot:
                session.expire(bot)
                logger.info("✅ Bot cache expired", bot_id=bot_id)
    
    @staticmethod 
    async def get_fresh_bot_data(bot_id: str):
        """✅ НОВЫЙ: Получение всегда свежих данных бота (без кэша)"""
        from database.models import UserBot
        from sqlalchemy import select
        
        async with get_db_session() as session:
            # Всегда получаем свежие данные из БД
            result = await session.execute(
                select(UserBot)
                .where(UserBot.bot_id == bot_id)
                .execution_options(populate_existing=True)
            )
            return result.scalar_one_or_none()

    # ===== АГРЕССИВНАЯ ОЧИСТКА КЭША =====

    @staticmethod
    async def force_fresh_bot_data(bot_id: str):
        """✅ АГРЕССИВНОЕ получение свежих данных с полной очисткой кэша"""
        from database.models import UserBot
        from sqlalchemy import select, text
        
        logger.info("🔥 FORCE refreshing bot data with aggressive cache clear", bot_id=bot_id)
        
        try:
            async with get_db_session() as session:
                # 1. Очищаем все кэши сессии
                session.expunge_all()
                
                # 2. Используем RAW SQL с уникальным комментарием для обхода кэша
                cache_buster = random.randint(1, 2147483647)  # PostgreSQL int32 compatible
                
                raw_query = text(f"""
                    SELECT * FROM user_bots 
                    WHERE bot_id = :bot_id 
                    AND :cache_buster > 0  /* cache_buster_{cache_buster} */
                """)
                
                result = await session.execute(
                    raw_query, 
                    {"bot_id": bot_id, "cache_buster": cache_buster}
                )
                
                row = result.first()
                
                if row:
                    # Создаем объект UserBot из raw данных
                    bot = UserBot()
                    for column, value in zip(result.keys(), row):
                        setattr(bot, column, value)
                    
                    logger.info("✅ FORCE fresh bot data retrieved", 
                               bot_id=bot_id,
                               cache_buster=cache_buster,
                               subscription_enabled=getattr(bot, 'subscription_check_enabled', None))
                    
                    return bot
                else:
                    logger.warning("❌ Bot not found in FORCE fresh query", bot_id=bot_id)
                    return None
                    
        except Exception as e:
            logger.error("💥 FORCE fresh bot data failed", 
                        bot_id=bot_id,
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            return None

    @staticmethod
    async def nuclear_cache_clear():
        """☢️ ЯДЕРНАЯ очистка всех кэшей (использовать с осторожностью)"""
        try:
            async with get_db_session() as session:
                # Очищаем все объекты из сессии
                session.expunge_all()
                
                # Очищаем кэш connection pool (если есть)
                if hasattr(session.bind, 'pool'):
                    session.bind.pool.dispose()
                
                logger.warning("☢️ NUCLEAR cache clear executed - all caches purged")
                
        except Exception as e:
            logger.error("💥 Nuclear cache clear failed", error=str(e))

    @staticmethod  
    async def get_subscription_status_no_cache(bot_id: str) -> tuple[bool, dict]:
        """✅ СПЕЦИАЛЬНЫЙ метод для получения статуса подписки БЕЗ кэша"""
        from sqlalchemy import text
        
        cache_buster = random.randint(1, 2147483647)  # PostgreSQL int32 compatible
        
        try:
            async with get_db_session() as session:
                session.expunge_all()  # Очищаем сессию
                
                # RAW SQL с уникальным комментарием
                query = text(f"""
                    SELECT 
                        subscription_check_enabled,
                        subscription_channel_id,
                        subscription_channel_username,
                        subscription_deny_message,
                        updated_at
                    FROM user_bots 
                    WHERE bot_id = :bot_id 
                    AND :cache_buster > 0  /* sub_status_{cache_buster} */
                """)
                
                result = await session.execute(
                    query, 
                    {"bot_id": bot_id, "cache_buster": cache_buster}
                )
                
                row = result.first()
                
                if row:
                    enabled = bool(row.subscription_check_enabled)
                    channel_info = {
                        'channel_id': row.subscription_channel_id,
                        'channel_username': row.subscription_channel_username, 
                        'deny_message': row.subscription_deny_message or 'Для доступа к ИИ агенту необходимо подписаться на наш канал.',
                        'updated_at': row.updated_at.isoformat() if row.updated_at else None
                    }
                    
                    logger.info("✅ Subscription status retrieved with NO CACHE", 
                               bot_id=bot_id,
                               enabled=enabled,
                               cache_buster=cache_buster,
                               has_channel=bool(channel_info['channel_id']))
                    
                    return enabled, channel_info
                else:
                    logger.warning("❌ Bot not found in no-cache subscription query", bot_id=bot_id)
                    return False, {
                        'channel_id': None,
                        'channel_username': None,
                        'deny_message': 'Для доступа к ИИ агенту необходимо подписаться на наш канал.',
                        'updated_at': None
                    }
                    
        except Exception as e:
            logger.error("💥 No-cache subscription status failed", 
                        bot_id=bot_id,
                        error=str(e),
                        error_type=type(e).__name__)
            return False, {
                'channel_id': None,
                'channel_username': None, 
                'deny_message': 'Для доступа к ИИ агенту необходимо подписаться на наш канал.',
                'updated_at': None
            }

    @staticmethod
    async def verify_update_success(bot_id: str, expected_enabled: bool) -> bool:
        """✅ ПРОВЕРКА успешности обновления через независимый запрос"""
        try:
            # Ждем немного для завершения транзакции
            await asyncio.sleep(0.1)
            
            # Получаем данные агрессивным методом
            enabled, _ = await DatabaseManager.get_subscription_status_no_cache(bot_id)
            
            success = (enabled == expected_enabled)
            
            logger.info("🧪 Update verification result", 
                       bot_id=bot_id,
                       expected=expected_enabled,
                       actual=enabled,
                       success=success)
            
            return success
            
        except Exception as e:
            logger.error("💥 Update verification failed", 
                        bot_id=bot_id, 
                        error=str(e))
            return False

    # ===== TOKEN MANAGEMENT METHODS =====

    @staticmethod
    async def save_token_usage(bot_id: str, input_tokens: int, output_tokens: int, admin_chat_id: int = None, user_id: int = None):
        """Сохранение использования токенов OpenAI с синхронизацией User и UserBot"""
        from database.models import UserBot, User
        from sqlalchemy import select, update
        
        logger.info("💰 Saving token usage with User sync", 
                   bot_id=bot_id,
                   input_tokens=input_tokens,
                   output_tokens=output_tokens,
                   admin_chat_id=admin_chat_id)
        
        try:
            async with get_db_session() as session:
                # Получаем текущего бота
                result = await session.execute(
                    select(UserBot).where(UserBot.bot_id == bot_id)
                )
                bot = result.scalar_one_or_none()
                
                if not bot:
                    logger.error("❌ Bot not found for token usage", bot_id=bot_id)
                    return False
                
                # ✅ НОВОЕ: Получаем текущие токены из UserBot
                current_input = bot.tokens_used_input or 0
                current_output = bot.tokens_used_output or 0
                current_total = bot.tokens_used_total or 0
                
                new_input = current_input + input_tokens
                new_output = current_output + output_tokens
                new_total = current_total + input_tokens + output_tokens
                
                # 1. Обновляем UserBot
                update_data = {
                    'tokens_used_input': new_input,
                    'tokens_used_output': new_output,
                    'tokens_used_total': new_total,
                    'updated_at': datetime.now()
                }
                
                if admin_chat_id and not bot.openai_admin_chat_id:
                    update_data['openai_admin_chat_id'] = admin_chat_id
                
                await session.execute(
                    update(UserBot)
                    .where(UserBot.bot_id == bot_id)
                    .values(**update_data)
                )
                
                # 2. ✅ НОВОЕ: Синхронизируем User.tokens_used_total
                # Получаем сумму всех токенов пользователя по всем OpenAI ботам
                user_total_result = await session.execute(
                    select(func.sum(UserBot.tokens_used_total))
                    .where(
                        UserBot.user_id == bot.user_id,
                        UserBot.ai_assistant_type == 'openai',
                        UserBot.openai_agent_id.isnot(None)
                    )
                )
                user_total_tokens = int(user_total_result.scalar() or 0)
                
                # Обновляем User
                await session.execute(
                    update(User)
                    .where(User.id == bot.user_id)
                    .values(
                        tokens_used_total=user_total_tokens,
                        updated_at=datetime.now()
                    )
                )
                
                await session.commit()
                
                logger.info("✅ Token usage saved with User sync", 
                           bot_id=bot_id,
                           new_bot_total=new_total,
                           user_total_tokens=user_total_tokens,
                           session_input=input_tokens,
                           session_output=output_tokens)
                
                return True
                
        except Exception as e:
            logger.error("💥 Failed to save token usage with sync", 
                        bot_id=bot_id,
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            return False

    @staticmethod
    async def check_token_limit(user_id: int) -> tuple[bool, int, int]:
        """Проверить лимит токенов для пользователя"""
        from database.models import User
        from sqlalchemy import select
        
        logger.info("🔍 Checking token limit", user_id=user_id)
        
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    select(User.tokens_used_total, User.tokens_limit_total)
                    .where(User.id == user_id)
                )
                
                data = result.first()
                if not data:
                    logger.error("❌ User not found for token check", user_id=user_id)
                    return False, 0, 500000
                
                total_used = int(data.tokens_used_total or 0)
                tokens_limit = int(data.tokens_limit_total or 500000)
                
                has_tokens = total_used < tokens_limit
                
                logger.info("📊 Token limit check result", 
                           user_id=user_id,
                           total_used=total_used,
                           tokens_limit=tokens_limit,
                           has_tokens=has_tokens,
                           remaining=tokens_limit - total_used)
                
                return has_tokens, total_used, tokens_limit
                
        except Exception as e:
            logger.error("💥 Failed to check token limit", 
                        user_id=user_id,
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            
            return False, 0, 500000

    @staticmethod
    async def update_user_tokens_limit(user_id: int, new_limit: int) -> bool:
        """Update user tokens limit"""
        from database.models import User
        from sqlalchemy import update
        
        logger.info("💰 Updating user tokens limit", 
                   user_id=user_id, 
                   new_limit=new_limit)
        
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    update(User)
                    .where(User.id == user_id)
                    .values(
                        tokens_limit_total=new_limit,
                        updated_at=datetime.now()
                    )
                )
                await session.commit()
                
                success = result.rowcount > 0
                
                logger.info("✅ User tokens limit updated" if success else "❌ No user found for tokens update", 
                           user_id=user_id,
                           new_limit=new_limit,
                           rows_affected=result.rowcount)
                
                return success
                
        except Exception as e:
            logger.error("💥 Failed to update user tokens limit", 
                        user_id=user_id,
                        new_limit=new_limit,
                        error=str(e),
                        error_type=type(e).__name__)
            return False

    @staticmethod
    async def get_user_token_balance(user_id: int) -> Optional[dict]:
        """Get user token balance info"""
        from database.models import User
        from sqlalchemy import select
        
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    select(User.tokens_limit_total, User.tokens_used_total)
                    .where(User.id == user_id)
                )
                
                data = result.first()
                if not data:
                    return None
                
                return {
                    'limit': int(data.tokens_limit_total or 500000),
                    'total_used': int(data.tokens_used_total or 0),
                    'remaining': int(data.tokens_limit_total or 500000) - int(data.tokens_used_total or 0)
                }
                
        except Exception as e:
            logger.error("Failed to get user token balance", 
                        user_id=user_id, 
                        error=str(e))
            return None

    # ===== AI METHODS =====
    
    @staticmethod
    async def get_ai_config(bot_id: str) -> Optional[dict]:
        """✅ ИСПРАВЛЕНО: Получение конфигурации AI с детальным логированием"""
        from database.models import UserBot
        from sqlalchemy import select
        
        logger.info("🔍 Loading AI config for bot startup", bot_id=bot_id)
        
        async with get_db_session() as session:
            result = await session.execute(
                select(UserBot).where(UserBot.bot_id == bot_id)
            )
            bot = result.scalar_one_or_none()
            
            if not bot:
                logger.info("❌ Bot not found", bot_id=bot_id)
                return None
            
            # ✅ ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ состояния
            logger.info("📊 Bot AI state diagnosis", 
                       bot_id=bot_id,
                       ai_assistant_enabled=bot.ai_assistant_enabled,
                       ai_assistant_type=bot.ai_assistant_type,
                       openai_agent_id=bot.openai_agent_id,
                       openai_agent_name=bot.openai_agent_name,
                       external_api_token=bool(bot.external_api_token),
                       external_bot_id=bot.external_bot_id,
                       external_platform=bot.external_platform)
            
            # ✅ ИСПРАВЛЕНО: Проверяем enabled только в конце
            if not bot.ai_assistant_enabled:
                logger.info("❌ AI assistant disabled", 
                           bot_id=bot_id,
                           ai_enabled=bot.ai_assistant_enabled)
                return None
            
            config = {
                'bot_id': bot.bot_id,
                'enabled': bot.ai_assistant_enabled,
                'type': bot.ai_assistant_type
            }
            
            if bot.ai_assistant_type == 'openai':
                # ✅ ИСПРАВЛЕНО: Проверяем наличие openai_agent_id
                if not bot.openai_agent_id:
                    logger.info("❌ OpenAI type set but no agent_id", 
                               bot_id=bot_id,
                               ai_type=bot.ai_assistant_type,
                               has_agent_id=bool(bot.openai_agent_id))
                    return None
                    
                config.update({
                    'ai_assistant_id': bot.openai_agent_id,  # ✅ ИСПРАВЛЕНО: Правильный ключ
                    'agent_id': bot.openai_agent_id,         # Для совместимости
                    'agent_name': bot.openai_agent_name,
                    'instructions': bot.openai_agent_instructions,
                    'model': bot.openai_model,
                    'settings': bot.openai_settings or {}
                })
                logger.info("✅ OpenAI config loaded successfully", 
                           bot_id=bot_id,
                           agent_id=bot.openai_agent_id,
                           agent_name=bot.openai_agent_name,
                           model=bot.openai_model)
                
            elif bot.ai_assistant_type in ['chatforyou', 'protalk']:
                # ✅ ИСПРАВЛЕНО: Проверяем наличие внешних токенов
                if not bot.external_api_token:
                    logger.info("❌ External AI type set but no token", 
                               bot_id=bot_id,
                               ai_type=bot.ai_assistant_type,
                               has_token=bool(bot.external_api_token))
                    return None
                    
                config.update({
                    'ai_assistant_id': bot.external_api_token,  # ✅ ИСПРАВЛЕНО: Правильный ключ
                    'api_token': bot.external_api_token,
                    'bot_id_value': bot.external_bot_id,
                    'platform': bot.external_platform,
                    'settings': bot.external_settings or {}
                })
                logger.info("✅ External AI config loaded successfully", 
                           bot_id=bot_id,
                           platform=bot.ai_assistant_type,
                           has_token=bool(bot.external_api_token),
                           bot_id_value=bot.external_bot_id)
            else:
                logger.warning("⚠️ Unknown AI type or not properly configured", 
                              bot_id=bot_id,
                              ai_type=bot.ai_assistant_type)
                return None
            
            logger.info("✅ AI config loaded successfully", 
                       bot_id=bot_id, 
                       ai_type=config['type'],
                       has_ai_assistant_id=bool(config.get('ai_assistant_id')),
                       config_keys=list(config.keys()))
            return config

    @staticmethod
    async def diagnose_ai_config(bot_id: str) -> dict:
        """✅ НОВЫЙ: Диагностика состояния AI конфигурации"""
        from database.models import UserBot
        from sqlalchemy import select
        
        logger.info("🔍 Diagnosing AI config", bot_id=bot_id)
        
        async with get_db_session() as session:
            result = await session.execute(
                select(UserBot).where(UserBot.bot_id == bot_id)
            )
            bot = result.scalar_one_or_none()
            
            if not bot:
                return {'status': 'bot_not_found', 'bot_id': bot_id}
            
            diagnosis = {
                'bot_id': bot_id,
                'status': 'analyzing',
                'ai_assistant_enabled': bot.ai_assistant_enabled,
                'ai_assistant_type': bot.ai_assistant_type,
                'fields': {
                    'openai': {
                        'agent_id': bot.openai_agent_id,
                        'agent_name': bot.openai_agent_name,
                        'has_instructions': bool(bot.openai_agent_instructions),
                        'model': bot.openai_model,
                        'has_settings': bool(bot.openai_settings),
                        'use_responses_api': bot.openai_use_responses_api,
                        'store_conversations': bot.openai_store_conversations
                    },
                    'external': {
                        'api_token': bool(bot.external_api_token),
                        'bot_id': bot.external_bot_id,
                        'platform': bot.external_platform,
                        'has_settings': bool(bot.external_settings)
                    }
                },
                'config_result': None,
                'issues': []
            }
            
            # Пытаемся получить конфигурацию
            try:
                config = await DatabaseManager.get_ai_config(bot_id)
                diagnosis['config_result'] = 'success' if config else 'failed'
                if config:
                    diagnosis['resolved_type'] = config.get('type')
                    diagnosis['has_ai_assistant_id'] = bool(config.get('ai_assistant_id'))
            except Exception as e:
                diagnosis['config_result'] = 'error'
                diagnosis['config_error'] = str(e)
            
            # Определяем проблемы
            if bot.ai_assistant_enabled and not bot.ai_assistant_type:
                diagnosis['issues'].append('enabled_but_no_type')
                diagnosis['status'] = 'misconfigured'
            elif bot.ai_assistant_type == 'openai':
                if not bot.openai_agent_id:
                    diagnosis['issues'].append('openai_type_but_no_agent_id')
                    diagnosis['status'] = 'incomplete'
                elif not bot.ai_assistant_enabled:
                    diagnosis['issues'].append('openai_agent_exists_but_disabled')
                    diagnosis['status'] = 'disabled'
                else:
                    diagnosis['status'] = 'configured'
            elif bot.ai_assistant_type in ['chatforyou', 'protalk']:
                if not bot.external_api_token:
                    diagnosis['issues'].append('external_type_but_no_token')
                    diagnosis['status'] = 'incomplete'
                elif not bot.ai_assistant_enabled:
                    diagnosis['issues'].append('external_configured_but_disabled')
                    diagnosis['status'] = 'disabled'
                else:
                    diagnosis['status'] = 'configured'
            else:
                diagnosis['status'] = 'not_configured'
            
            logger.info("🔍 AI config diagnosis completed", 
                       bot_id=bot_id,
                       status=diagnosis['status'],
                       issues=diagnosis['issues'],
                       config_result=diagnosis['config_result'])
            
            return diagnosis

    # ===== AI MANAGEMENT METHODS (РЕАЛИЗАЦИЯ) =====

    @staticmethod
    async def clear_ai_configuration(bot_id: str) -> bool:
        """✅ НОВЫЙ: Очистка AI конфигурации для бота"""
        from database.models import UserBot
        from sqlalchemy import update
        
        logger.info("🗑️ Clearing AI configuration", bot_id=bot_id)
        
        try:
            async with get_db_session() as session:
                # Очищаем все AI-связанные поля
                await session.execute(
                    update(UserBot)
                    .where(UserBot.bot_id == bot_id)
                    .values(
                        # Отключаем AI
                        ai_assistant_enabled=False,
                        ai_assistant_type=None,
                        
                        # Очищаем OpenAI поля
                        openai_agent_id=None,
                        openai_agent_name=None,
                        openai_agent_instructions=None,
                        openai_model=None,
                        openai_settings=None,
                        openai_use_responses_api=False,
                        openai_store_conversations=False,
                        openai_admin_chat_id=None,
                        
                        # Очищаем External AI поля
                        external_api_token=None,
                        external_bot_id=None,
                        external_platform=None,
                        external_settings=None,
                        
                        # Обновляем timestamp
                        updated_at=datetime.now()
                    )
                )
                
                await session.commit()
                
                logger.info("✅ AI configuration cleared successfully", bot_id=bot_id)
                return True
                
        except Exception as e:
            logger.error("💥 Failed to clear AI configuration", 
                        bot_id=bot_id,
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            return False

    @staticmethod
    async def update_ai_assistant(bot_id: str, enabled: bool = True, assistant_id: str = None, settings: dict = None) -> bool:
        """✅ РЕАЛИЗАЦИЯ: Обновление AI ассистента"""
        from database.models import UserBot
        from sqlalchemy import update
        
        logger.info("🔄 Updating AI assistant", 
                   bot_id=bot_id,
                   enabled=enabled,
                   has_assistant_id=bool(assistant_id),
                   has_settings=bool(settings))
        
        try:
            async with get_db_session() as session:
                update_data = {
                    'ai_assistant_enabled': enabled,
                    'updated_at': datetime.now()
                }
                
                # Если передан assistant_id, определяем тип и обновляем соответствующие поля
                if assistant_id:
                    if settings and settings.get('agent_type') == 'openai':
                        # Обновляем OpenAI агента
                        update_data.update({
                            'ai_assistant_type': 'openai',
                            'openai_agent_id': assistant_id,
                            'openai_agent_name': settings.get('agent_name'),
                            'openai_agent_instructions': settings.get('agent_role') or settings.get('system_prompt'),
                            'openai_model': settings.get('model', 'gpt-4o'),
                            'openai_settings': settings.get('openai_settings', {}),
                            'openai_use_responses_api': settings.get('creation_method') == 'responses_api',
                            'openai_store_conversations': settings.get('store_conversations', True),
                            'openai_admin_chat_id': settings.get('admin_chat_id')
                        })
                    else:
                        # Предполагаем external AI (ChatForYou/ProTalk)
                        platform = settings.get('platform', 'chatforyou')
                        update_data.update({
                            'ai_assistant_type': platform,
                            'external_api_token': assistant_id,
                            'external_bot_id': settings.get('bot_id_value'),
                            'external_platform': platform,
                            'external_settings': settings or {}
                        })
                
                # Если только settings без assistant_id
                elif settings:
                    agent_type = settings.get('agent_type')
                    if agent_type:
                        update_data['ai_assistant_type'] = agent_type
                    
                    # Обновляем настройки существующего агента
                    if agent_type == 'openai':
                        openai_updates = {}
                        if 'agent_name' in settings:
                            openai_updates['openai_agent_name'] = settings['agent_name']
                        if 'agent_role' in settings:
                            openai_updates['openai_agent_instructions'] = settings['agent_role']
                        if 'openai_settings' in settings:
                            openai_updates['openai_settings'] = settings['openai_settings']
                        
                        update_data.update(openai_updates)
                
                await session.execute(
                    update(UserBot)
                    .where(UserBot.bot_id == bot_id)
                    .values(**update_data)
                )
                
                await session.commit()
                
                logger.info("✅ AI assistant updated successfully", 
                           bot_id=bot_id,
                           enabled=enabled,
                           update_fields=list(update_data.keys()))
                return True
                
        except Exception as e:
            logger.error("💥 Failed to update AI assistant", 
                        bot_id=bot_id,
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            return False

    @staticmethod  
    async def get_openai_agent_info(bot_id: str) -> Optional[dict]:
        """✅ НОВЫЙ: Получение информации о OpenAI агенте"""
        from database.models import UserBot
        from sqlalchemy import select
        
        async with get_db_session() as session:
            result = await session.execute(
                select(UserBot).where(UserBot.bot_id == bot_id)
            )
            bot = result.scalar_one_or_none()
            
            if not bot or bot.ai_assistant_type != 'openai' or not bot.openai_agent_id:
                return None
            
            return {
                'agent_id': bot.openai_agent_id,
                'agent_name': bot.openai_agent_name,
                'instructions': bot.openai_agent_instructions,
                'model': bot.openai_model,
                'settings': bot.openai_settings or {},
                'use_responses_api': bot.openai_use_responses_api,
                'store_conversations': bot.openai_store_conversations,
                'enabled': bot.ai_assistant_enabled
            }

    @staticmethod
    async def delete_openai_agent(bot_id: str) -> bool:
        """✅ НОВЫЙ: Удаление OpenAI агента (alias для clear_ai_configuration)"""
        logger.info("🗑️ Deleting OpenAI agent", bot_id=bot_id)
        return await DatabaseManager.clear_ai_configuration(bot_id)

    @staticmethod
    async def validate_agent_data_consistency(bot_id: str) -> dict:
        """✅ НОВЫЙ: Проверка консистентности данных агента"""
        from database.models import UserBot
        from sqlalchemy import select
        
        async with get_db_session() as session:
            result = await session.execute(
                select(UserBot).where(UserBot.bot_id == bot_id)
            )
            bot = result.scalar_one_or_none()
            
            if not bot:
                return {'status': 'bot_not_found'}
            
            validation = {
                'bot_id': bot_id,
                'overall_status': 'consistent',
                'issues': [],
                'recommendations': []
            }
            
            # Проверка OpenAI агента
            if bot.ai_assistant_type == 'openai':
                if bot.ai_assistant_enabled and not bot.openai_agent_id:
                    validation['issues'].append('openai_enabled_but_no_agent_id')
                    validation['recommendations'].append('Создать OpenAI агента или отключить AI')
                
                if bot.openai_agent_id and not bot.ai_assistant_enabled:
                    validation['issues'].append('openai_agent_exists_but_disabled')
                    validation['recommendations'].append('Включить AI или удалить агента')
            
            # Проверка External агента
            if bot.ai_assistant_type in ['chatforyou', 'protalk']:
                if bot.ai_assistant_enabled and not bot.external_api_token:
                    validation['issues'].append('external_enabled_but_no_token')
                    validation['recommendations'].append('Настроить API токен или отключить AI')
            
            if validation['issues']:
                validation['overall_status'] = 'inconsistent'
            
            return validation

    @staticmethod
    async def sync_agent_data_fields(bot_id: str) -> bool:
        """✅ НОВЫЙ: Синхронизация полей данных агента"""
        logger.info("🔄 Syncing agent data fields", bot_id=bot_id)
        
        try:
            # Получаем свежие данные
            fresh_bot = await DatabaseManager.get_bot_by_id(bot_id, fresh=True)
            if not fresh_bot:
                return False
            
            # Проверяем консистентность и исправляем
            validation = await DatabaseManager.validate_agent_data_consistency(bot_id)
            
            if validation['overall_status'] == 'inconsistent':
                logger.info("🔧 Found inconsistencies, fixing...", 
                           issues=validation['issues'])
                
                # Автоисправление простых проблем
                from database.models import UserBot
                from sqlalchemy import update
                
                async with get_db_session() as session:
                    # Если есть OpenAI агент но AI отключен - включаем
                    if 'openai_agent_exists_but_disabled' in validation['issues']:
                        await session.execute(
                            update(UserBot)
                            .where(UserBot.bot_id == bot_id)
                            .values(ai_assistant_enabled=True, updated_at=datetime.now())
                        )
                    
                    # Если AI включен но нет агента - отключаем
                    if 'openai_enabled_but_no_agent_id' in validation['issues']:
                        await session.execute(
                            update(UserBot)
                            .where(UserBot.bot_id == bot_id)
                            .values(ai_assistant_enabled=False, updated_at=datetime.now())
                        )
                    
                    await session.commit()
            
            return True
            
        except Exception as e:
            logger.error("💥 Failed to sync agent data", error=str(e))
            return False

    # ===== MASS BROADCAST METHODS =====

    @staticmethod
    async def create_mass_broadcast(bot_id: str, created_by: int, message_text: str, **kwargs):
        """Create mass broadcast"""
        from database.managers.mass_broadcast_manager import MassBroadcastManager
        return await MassBroadcastManager.create_broadcast(bot_id, created_by, message_text, **kwargs)

    @staticmethod
    async def get_mass_broadcast_by_id(broadcast_id: int):
        """Get mass broadcast by ID"""
        from database.managers.mass_broadcast_manager import MassBroadcastManager
        return await MassBroadcastManager.get_broadcast_by_id(broadcast_id)

    @staticmethod
    async def update_mass_broadcast(broadcast_id: int, **kwargs):
        """Update mass broadcast"""
        from database.managers.mass_broadcast_manager import MassBroadcastManager
        return await MassBroadcastManager.update_broadcast(broadcast_id, **kwargs)

    @staticmethod
    async def delete_mass_broadcast(broadcast_id: int):
        """Delete mass broadcast"""
        from database.managers.mass_broadcast_manager import MassBroadcastManager
        return await MassBroadcastManager.delete_broadcast(broadcast_id)

    @staticmethod
    async def get_bot_mass_broadcasts(bot_id: str, limit: int = 50):
        """Get bot mass broadcasts"""
        from database.managers.mass_broadcast_manager import MassBroadcastManager
        return await MassBroadcastManager.get_bot_broadcasts(bot_id, limit)

    @staticmethod
    async def get_scheduled_mass_broadcasts(bot_id: str = None):
        """Get scheduled broadcasts ready to send"""
        from database.managers.mass_broadcast_manager import MassBroadcastManager
        return await MassBroadcastManager.get_scheduled_broadcasts(bot_id)

    @staticmethod
    async def get_pending_scheduled_mass_broadcasts(bot_id: str = None):
        """Get pending scheduled broadcasts"""
        from database.managers.mass_broadcast_manager import MassBroadcastManager
        return await MassBroadcastManager.get_pending_scheduled_broadcasts(bot_id)

    @staticmethod
    async def start_mass_broadcast(broadcast_id: int):
        """Start mass broadcast"""
        from database.managers.mass_broadcast_manager import MassBroadcastManager
        return await MassBroadcastManager.start_broadcast(broadcast_id)

    @staticmethod
    async def get_pending_mass_deliveries(limit: int = 100):
        """Get pending mass deliveries"""
        from database.managers.mass_broadcast_manager import MassBroadcastManager
        return await MassBroadcastManager.get_pending_deliveries(limit)

    @staticmethod
    async def update_mass_delivery_status(delivery_id: int, status: str, **kwargs):
        """Update mass delivery status"""
        from database.managers.mass_broadcast_manager import MassBroadcastManager
        return await MassBroadcastManager.update_delivery_status(delivery_id, status, **kwargs)

    @staticmethod
    async def complete_mass_broadcast(broadcast_id: int):
        """Complete mass broadcast"""
        from database.managers.mass_broadcast_manager import MassBroadcastManager
        return await MassBroadcastManager.complete_broadcast(broadcast_id)

    @staticmethod
    async def get_mass_broadcast_stats(bot_id: str, days: int = 30):
        """Get mass broadcast statistics"""
        from database.managers.mass_broadcast_manager import MassBroadcastManager
        return await MassBroadcastManager.get_broadcast_stats(bot_id, days)
    
    # ===== BOT STATUS METHODS =====
    
    @staticmethod
    async def update_bot_status(bot_id: str, status: str, is_running: bool = None):
        """Update bot status"""
        from database.models import UserBot
        from sqlalchemy import select, update
        
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
    
    @staticmethod
    async def get_all_active_bots():
        """Get all active bots"""
        from database.models import UserBot
        from sqlalchemy import select
        
        async with get_db_session() as session:
            result = await session.execute(
                select(UserBot)
                .where(UserBot.status == "active")
                .order_by(UserBot.created_at)
            )
            return result.scalars().all()

    @staticmethod
    async def delete_user_bot(bot_id: str):
        """Delete user bot"""
        from database.models import UserBot
        from sqlalchemy import delete
        
        async with get_db_session() as session:
            await session.execute(
                delete(UserBot).where(UserBot.bot_id == bot_id)
            )
            await session.commit()
            logger.info("Bot deleted from database", bot_id=bot_id)

    # ===== SIMPLIFIED PLACEHOLDER METHODS =====
    # TODO: Implement remaining methods as needed
    
    @staticmethod
    async def get_bot_full_config(bot_id: str, fresh: bool = False):
        """Get full bot configuration - PLACEHOLDER"""
        logger.warning("get_bot_full_config - implement in bot_manager.py")
        return None


# Database instance for backwards compatibility
db = DatabaseManager()
