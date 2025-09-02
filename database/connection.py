import asyncio
import json
import random
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import func, select
from sqlalchemy.dialects.postgresql import insert  # ✅ ДОБАВЛЕН импорт для UPSERT
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional, List, Union, Tuple, Dict
from datetime import datetime, timedelta, date
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

    @staticmethod
    async def add_tokens_to_user(user_id: int, additional_tokens: int) -> bool:
        """Add tokens to user balance"""
        logger.info("💰 Adding tokens to user", 
                   user_id=user_id,
                   additional_tokens=additional_tokens)
        
        try:
            return await DatabaseManager.update_user_tokens_limit(
                user_id, 
                additional_tokens  # This will be added to existing balance in the webhook handler
            )
        except Exception as e:
            logger.error("💥 Failed to add tokens to user", 
                        user_id=user_id,
                        additional_tokens=additional_tokens,
                        error=str(e))
            return False

    @staticmethod
    async def initialize_token_balance(user_id: int, admin_chat_id: int, bot_id: str = None) -> bool:
        """Initialize token balance for user"""
        from database.models import User
        from sqlalchemy import update, select
        
        logger.info("🔄 Initializing token balance", 
                   user_id=user_id,
                   admin_chat_id=admin_chat_id,
                   bot_id=bot_id)
        
        try:
            async with get_db_session() as session:
                # Check if user already has tokens initialized
                result = await session.execute(
                    select(User.tokens_limit_total, User.tokens_initialized_at)
                    .where(User.id == user_id)
                )
                
                data = result.first()
                if not data:
                    logger.warning("User not found for token initialization", user_id=user_id)
                    return False
                
                if data.tokens_initialized_at and data.tokens_limit_total:
                    logger.info("User tokens already initialized", 
                               user_id=user_id,
                               current_limit=data.tokens_limit_total)
                    return True
                
                # Initialize tokens
                await session.execute(
                    update(User)
                    .where(User.id == user_id)
                    .values(
                        tokens_limit_total=500000,
                        tokens_used_total=0,
                        tokens_admin_chat_id=admin_chat_id,
                        tokens_initialized_at=datetime.now(),
                        updated_at=datetime.now()
                    )
                )
                await session.commit()
                
                logger.info("✅ Token balance initialized successfully", 
                           user_id=user_id,
                           initial_tokens=500000)
                return True
                
        except Exception as e:
            logger.error("💥 Failed to initialize token balance", 
                        user_id=user_id,
                        error=str(e))
            return False

    # ===== DAILY MESSAGE LIMIT METHODS =====

    @staticmethod
    async def check_daily_message_limit(bot_id: str, user_id: int) -> tuple[bool, int, int]:
        """Проверить дневной лимит сообщений для пользователя"""
        from database.models import AIUsageLog, UserBot
        from sqlalchemy import select, func
        
        async with get_db_session() as session:
            # Получаем настройки лимита бота
            bot_result = await session.execute(
                select(UserBot.openai_settings, UserBot.external_settings, UserBot.ai_assistant_type)
                .where(UserBot.bot_id == bot_id)
            )
            bot_data = bot_result.first()
            
            if not bot_data:
                return True, 0, 0
            
            # Определяем лимит из настроек
            daily_limit = 0
            if bot_data.ai_assistant_type == 'openai' and bot_data.openai_settings:
                daily_limit = bot_data.openai_settings.get('daily_message_limit', 0)
            elif bot_data.ai_assistant_type in ['chatforyou', 'protalk'] and bot_data.external_settings:
                daily_limit = bot_data.external_settings.get('daily_message_limit', 0)
            
            if daily_limit <= 0:
                return True, 0, 0  # Лимит не установлен
            
            # Получаем использование за сегодня
            today = date.today()
            usage_result = await session.execute(
                select(AIUsageLog.messages_count)
                .where(
                    AIUsageLog.bot_id == bot_id,
                    AIUsageLog.user_id == user_id,
                    AIUsageLog.date == today
                )
            )
            
            usage_data = usage_result.first()
            used_today = usage_data.messages_count if usage_data else 0
            
            can_send = used_today < daily_limit
            return can_send, used_today, daily_limit

    @staticmethod 
    async def increment_daily_message_usage(bot_id: str, user_id: int) -> bool:
        """✅ ИСПРАВЛЕНО: Увеличить счетчик с PostgreSQL UPSERT (без race condition)"""
        from database.models import AIUsageLog
        
        logger.info("📈 Incrementing daily message usage with UPSERT", 
                   bot_id=bot_id, user_id=user_id)
        
        try:
            async with get_db_session() as session:
                today = date.today()
                now = datetime.now()
                
                # ✅ UPSERT: UPDATE existing or INSERT new
                stmt = insert(AIUsageLog).values(
                    bot_id=bot_id,
                    user_id=user_id,
                    date=today,
                    messages_count=1,
                    platform_used='openai',
                    successful_requests=0,
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
    async def get_daily_message_limit(bot_id: str) -> int:
        """Получить установленный дневной лимит для бота"""
        from database.models import UserBot
        from sqlalchemy import select
        
        async with get_db_session() as session:
            result = await session.execute(
                select(UserBot.openai_settings, UserBot.external_settings, UserBot.ai_assistant_type)
                .where(UserBot.bot_id == bot_id)
            )
            
            bot_data = result.first()
            if not bot_data:
                return 0
            
            if bot_data.ai_assistant_type == 'openai' and bot_data.openai_settings:
                return bot_data.openai_settings.get('daily_message_limit', 0)
            elif bot_data.ai_assistant_type in ['chatforyou', 'protalk'] and bot_data.external_settings:
                return bot_data.external_settings.get('daily_message_limit', 0)
            
            return 0

    @staticmethod
    async def set_daily_message_limit(bot_id: str, limit: int) -> bool:
        """Установить дневной лимит сообщений для бота"""
        from database.models import UserBot
        from sqlalchemy import select, update
        
        try:
            async with get_db_session() as session:
                # Получаем текущие настройки
                result = await session.execute(
                    select(UserBot.ai_assistant_type, UserBot.openai_settings, UserBot.external_settings)
                    .where(UserBot.bot_id == bot_id)
                )
                
                bot_data = result.first()
                if not bot_data:
                    return False
                
                # Обновляем соответствующие настройки
                if bot_data.ai_assistant_type == 'openai':
                    openai_settings = bot_data.openai_settings or {}
                    openai_settings['daily_message_limit'] = limit
                    
                    await session.execute(
                        update(UserBot)
                        .where(UserBot.bot_id == bot_id)
                        .values(openai_settings=openai_settings)
                    )
                    
                elif bot_data.ai_assistant_type in ['chatforyou', 'protalk']:
                    external_settings = bot_data.external_settings or {}
                    external_settings['daily_message_limit'] = limit
                    
                    await session.execute(
                        update(UserBot)
                        .where(UserBot.bot_id == bot_id)
                        .values(external_settings=external_settings)
                    )
                
                await session.commit()
                return True
                
        except Exception as e:
            logger.error("Failed to set daily message limit", error=str(e))
            return False

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

    # ===== RESPONSES API METHODS =====

    @staticmethod
    async def save_openai_agent_config_responses_api(bot_id: str, agent_id: str, config: dict) -> bool:
        """Save OpenAI agent configuration for Responses API"""
        from database.models import UserBot
        from sqlalchemy import update
        
        logger.info("💾 Saving OpenAI agent config for Responses API", 
                   bot_id=bot_id,
                   agent_id=agent_id)
        
        try:
            async with get_db_session() as session:
                update_data = {
                    'ai_assistant_type': 'openai',
                    'ai_assistant_enabled': True,
                    'openai_agent_id': agent_id,
                    'openai_agent_name': config.get('agent_name'),
                    'openai_agent_instructions': config.get('instructions'),
                    'openai_model': config.get('model', 'gpt-4o'),
                    'openai_use_responses_api': True,
                    'openai_store_conversations': config.get('store_conversations', True),
                    'openai_conversation_retention_days': config.get('conversation_retention', 30),
                    'openai_settings': config.get('settings', {}),
                    'updated_at': datetime.now()
                }
                
                await session.execute(
                    update(UserBot)
                    .where(UserBot.bot_id == bot_id)
                    .values(**update_data)
                )
                
                await session.commit()
                
                logger.info("✅ OpenAI agent config saved successfully", 
                           bot_id=bot_id,
                           agent_id=agent_id)
                return True
                
        except Exception as e:
            logger.error("💥 Failed to save OpenAI agent config", 
                        bot_id=bot_id,
                        agent_id=agent_id,
                        error=str(e))
            return False

    @staticmethod
    async def get_openai_agent_config(assistant_id: str) -> Optional[dict]:
        """Get OpenAI agent configuration"""
        from database.models import UserBot
        from sqlalchemy import select
        
        async with get_db_session() as session:
            result = await session.execute(
                select(UserBot).where(UserBot.openai_agent_id == assistant_id)
            )
            bot = result.scalar_one_or_none()
            
            if not bot:
                return None
            
            return {
                'bot_id': bot.bot_id,
                'agent_id': bot.openai_agent_id,
                'agent_name': bot.openai_agent_name,
                'instructions': bot.openai_agent_instructions,
                'model': bot.openai_model,
                'enabled': bot.ai_assistant_enabled,
                'use_responses_api': bot.openai_use_responses_api,
                'store_conversations': bot.openai_store_conversations,
                'settings': bot.openai_settings or {}
            }

    @staticmethod
    async def save_conversation_response_id(bot_id: str, user_id: int, response_id: str) -> bool:
        """Save conversation response_id for Responses API"""
        from database.models import UserBot
        from sqlalchemy import select, update
        
        try:
            async with get_db_session() as session:
                # Get current conversation contexts
                result = await session.execute(
                    select(UserBot.openai_conversation_contexts)
                    .where(UserBot.bot_id == bot_id)
                )
                
                current_contexts = result.scalar() or {}
                
                # Update contexts
                current_contexts[str(user_id)] = response_id
                
                # Save back to database
                await session.execute(
                    update(UserBot)
                    .where(UserBot.bot_id == bot_id)
                    .values(
                        openai_conversation_contexts=current_contexts,
                        updated_at=datetime.now()
                    )
                )
                
                await session.commit()
                return True
                
        except Exception as e:
            logger.error("Failed to save conversation response_id", 
                        bot_id=bot_id, 
                        user_id=user_id, 
                        error=str(e))
            return False

    @staticmethod
    async def get_conversation_response_id(bot_id: str, user_id: int) -> Optional[str]:
        """Get conversation response_id"""
        from database.models import UserBot
        from sqlalchemy import select
        
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    select(UserBot.openai_conversation_contexts)
                    .where(UserBot.bot_id == bot_id)
                )
                
                contexts = result.scalar() or {}
                return contexts.get(str(user_id))
                
        except Exception as e:
            logger.error("Failed to get conversation response_id", 
                        bot_id=bot_id, 
                        user_id=user_id, 
                        error=str(e))
            return None

    @staticmethod
    async def clear_conversation_response_id(bot_id: str, user_id: int) -> bool:
        """Clear conversation response_id"""
        from database.models import UserBot
        from sqlalchemy import select, update
        
        try:
            async with get_db_session() as session:
                # Get current conversation contexts
                result = await session.execute(
                    select(UserBot.openai_conversation_contexts)
                    .where(UserBot.bot_id == bot_id)
                )
                
                current_contexts = result.scalar() or {}
                
                # Remove user's context
                user_key = str(user_id)
                if user_key in current_contexts:
                    del current_contexts[user_key]
                    
                    # Save back to database
                    await session.execute(
                        update(UserBot)
                        .where(UserBot.bot_id == bot_id)
                        .values(
                            openai_conversation_contexts=current_contexts,
                            updated_at=datetime.now()
                        )
                    )
                    
                    await session.commit()
                
                return True
                
        except Exception as e:
            logger.error("Failed to clear conversation response_id", 
                        bot_id=bot_id, 
                        user_id=user_id, 
                        error=str(e))
            return False

    # ===== ADMIN STATISTICS METHODS =====

    @staticmethod
    async def get_admin_statistics() -> dict:
        """✅ НОВОЕ: Получить полную статистику для администратора"""
        from database.models import User, UserBot
        from sqlalchemy import select, func, and_
        from datetime import datetime, timedelta
        
        try:
            async with get_db_session() as session:
                now = datetime.now()
                yesterday = now - timedelta(hours=24)
                week_ago = now - timedelta(days=7)
                
                # ===== ПОЛЬЗОВАТЕЛИ =====
                
                # Общее количество пользователей
                total_users_result = await session.execute(
                    select(func.count(User.id))
                )
                total_users = total_users_result.scalar() or 0
                
                # Новые пользователи за 24 часа
                users_24h_result = await session.execute(
                    select(func.count(User.id))
                    .where(User.created_at >= yesterday)
                )
                users_24h = users_24h_result.scalar() or 0
                
                # Новые пользователи за 7 дней
                users_7d_result = await session.execute(
                    select(func.count(User.id))
                    .where(User.created_at >= week_ago)
                )
                users_7d = users_7d_result.scalar() or 0
                
                # Активные подписки
                active_subscriptions_result = await session.execute(
                    select(func.count(User.id))
                    .where(
                        and_(
                            User.subscription_active == True,
                            User.subscription_expires_at > now
                        )
                    )
                )
                active_subscriptions = active_subscriptions_result.scalar() or 0
                
                # ===== БОТЫ =====
                
                # Общее количество ботов
                total_bots_result = await session.execute(
                    select(func.count(UserBot.id))
                )
                total_bots = total_bots_result.scalar() or 0
                
                # Активные боты
                active_bots_result = await session.execute(
                    select(func.count(UserBot.id))
                    .where(UserBot.is_running == True)
                )
                active_bots = active_bots_result.scalar() or 0
                
                # Боты с AI агентами
                ai_bots_result = await session.execute(
                    select(func.count(UserBot.id))
                    .where(
                        and_(
                            UserBot.ai_assistant_enabled == True,
                            UserBot.ai_assistant_type.isnot(None)
                        )
                    )
                )
                ai_bots = ai_bots_result.scalar() or 0
                
                # ===== ИСПОЛЬЗОВАНИЕ ТОКЕНОВ =====
                
                # Общее использование токенов
                total_tokens_result = await session.execute(
                    select(func.sum(User.tokens_used_total))
                )
                total_tokens_used = int(total_tokens_result.scalar() or 0)
                
                # Общий лимит токенов
                total_tokens_limit_result = await session.execute(
                    select(func.sum(User.tokens_limit_total))
                )
                total_tokens_limit = int(total_tokens_limit_result.scalar() or 0)
                
                # ===== ТОП ПОЛЬЗОВАТЕЛИ ПО ТОКЕНАМ =====
                top_users_tokens_result = await session.execute(
                    select(
                        User.id,
                        User.username,
                        User.first_name,
                        User.tokens_used_total,
                        User.tokens_limit_total
                    )
                    .where(User.tokens_used_total > 0)
                    .order_by(User.tokens_used_total.desc())
                    .limit(10)
                )
                top_users_tokens = [
                    {
                        'user_id': row.id,
                        'username': row.username,
                        'first_name': row.first_name,
                        'tokens_used': int(row.tokens_used_total or 0),
                        'tokens_limit': int(row.tokens_limit_total or 0)
                    }
                    for row in top_users_tokens_result
                ]
                
                # ===== ТОП ПОЛЬЗОВАТЕЛИ ПО БОТАМ =====
                top_users_bots_result = await session.execute(
                    select(
                        User.id,
                        User.username,
                        User.first_name,
                        func.count(UserBot.id).label('bot_count')
                    )
                    .join(UserBot, User.id == UserBot.user_id)
                    .group_by(User.id, User.username, User.first_name)
                    .order_by(func.count(UserBot.id).desc())
                    .limit(10)
                )
                top_users_bots = [
                    {
                        'user_id': row.id,
                        'username': row.username,
                        'first_name': row.first_name,
                        'bot_count': row.bot_count
                    }
                    for row in top_users_bots_result
                ]
                
                # ===== ФОРМИРУЕМ СТАТИСТИКУ =====
                
                statistics = {
                    'users': {
                        'total': total_users,
                        'new_24h': users_24h,
                        'new_7d': users_7d,
                        'active_subscriptions': active_subscriptions,
                        'subscription_rate': round((active_subscriptions / total_users * 100), 2) if total_users > 0 else 0
                    },
                    'bots': {
                        'total': total_bots,
                        'active': active_bots,
                        'ai_enabled': ai_bots,
                        'activity_rate': round((active_bots / total_bots * 100), 2) if total_bots > 0 else 0,
                        'ai_adoption_rate': round((ai_bots / total_bots * 100), 2) if total_bots > 0 else 0
                    },
                    'tokens': {
                        'total_used': total_tokens_used,
                        'total_limit': total_tokens_limit,
                        'usage_rate': round((total_tokens_used / total_tokens_limit * 100), 2) if total_tokens_limit > 0 else 0,
                        'average_per_user': round((total_tokens_used / total_users), 0) if total_users > 0 else 0
                    },
                    'top_users': {
                        'by_tokens': top_users_tokens,
                        'by_bots': top_users_bots
                    },
                    'generated_at': now.isoformat(),
                    'period': {
                        'last_24h': yesterday.isoformat(),
                        'last_7d': week_ago.isoformat()
                    }
                }
                
                logger.info("✅ Admin statistics generated successfully", 
                           total_users=total_users,
                           new_users_24h=users_24h,
                           new_users_7d=users_7d,
                           total_bots=total_bots,
                           active_bots=active_bots)
                
                return statistics
                
        except Exception as e:
            logger.error("💥 Failed to get admin statistics", 
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            return {
                'error': str(e),
                'users': {'total': 0, 'new_24h': 0, 'new_7d': 0},
                'bots': {'total': 0, 'active': 0},
                'tokens': {'total_used': 0, 'total_limit': 0},
                'generated_at': datetime.now().isoformat()
            }
    
    @staticmethod
    async def get_all_active_master_bot_users() -> list:
        """✅ НОВОЕ: Получить всех активных пользователей master бота для рассылки"""
        from database.models import User
        from sqlalchemy import select
        
        try:
            async with get_db_session() as session:
                # Получаем всех активных пользователей
                result = await session.execute(
                    select(User.id, User.username, User.first_name, User.last_name)
                    .where(User.is_active == True)
                    .order_by(User.created_at.desc())
                )
                
                users = [
                    {
                        'user_id': row.id,
                        'username': row.username,
                        'first_name': row.first_name,
                        'last_name': row.last_name,
                        'full_name': f"{row.first_name or ''} {row.last_name or ''}".strip() or f"@{row.username}" or f"ID: {row.id}"
                    }
                    for row in result
                ]
                
                logger.info("✅ Active master bot users retrieved", count=len(users))
                return users
                
        except Exception as e:
            logger.error("💥 Failed to get active master bot users", 
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            return []
    
    @staticmethod
    async def log_admin_broadcast(admin_user_id: int, message_text: str, total_users: int) -> int:
        """✅ НОВОЕ: Логирование админ рассылки"""
        from database.models import BotAdminLog
        
        try:
            async with get_db_session() as session:
                log_entry = BotAdminLog(
                    bot_id="master_bot",  # Специальный ID для master бота
                    admin_user_id=admin_user_id,
                    action_type="admin_broadcast",
                    action_description=f"Admin broadcast to {total_users} users",
                    action_data={
                        'message_preview': message_text[:100] + '...' if len(message_text) > 100 else message_text,
                        'total_recipients': total_users,
                        'broadcast_type': 'admin_master_bot'
                    },
                    success=True
                )
                
                session.add(log_entry)
                await session.commit()
                await session.refresh(log_entry)
                
                logger.info("✅ Admin broadcast logged", 
                           log_id=log_entry.id,
                           admin_id=admin_user_id,
                           recipients=total_users)
                
                return log_entry.id
                
        except Exception as e:
            logger.error("💥 Failed to log admin broadcast", 
                        admin_id=admin_user_id,
                        recipients=total_users,
                        error=str(e))
            return 0
    
    @staticmethod
    async def get_admin_broadcast_history(limit: int = 20) -> list:
        """✅ НОВОЕ: История админ рассылок"""
        from database.models import BotAdminLog
        from sqlalchemy import select
        
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    select(BotAdminLog)
                    .where(
                        BotAdminLog.action_type == "admin_broadcast"
                    )
                    .order_by(BotAdminLog.created_at.desc())
                    .limit(limit)
                )
                
                broadcasts = [
                    {
                        'id': log.id,
                        'admin_user_id': log.admin_user_id,
                        'created_at': log.created_at.isoformat(),
                        'description': log.action_description,
                        'data': log.action_data,
                        'success': log.success
                    }
                    for log in result.scalars()
                ]
                
                logger.info("✅ Admin broadcast history retrieved", count=len(broadcasts))
                return broadcasts
                
        except Exception as e:
            logger.error("💥 Failed to get admin broadcast history", error=str(e))
            return []

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
        """✅ КАСКАДНОЕ удаление бота со всеми связанными данными"""
        from sqlalchemy import text
        
        logger.info("🗑️ Starting cascade bot deletion", bot_id=bot_id)
        
        try:
            async with get_db_session() as session:
                # Проверяем существование
                check_result = await session.execute(
                    text("SELECT bot_username FROM user_bots WHERE bot_id = :bot_id"),
                    {"bot_id": bot_id}
                )
                
                bot_data = check_result.first()
                if not bot_data:
                    logger.warning("❌ Bot not found", bot_id=bot_id)
                    return False
                
                logger.info("🔍 Found bot for deletion", 
                           bot_id=bot_id, 
                           bot_username=bot_data.bot_username)
                
                # ===== КАСКАДНОЕ УДАЛЕНИЕ СВЯЗАННЫХ ДАННЫХ =====
                
                # 1. Удаляем подписчиков бота
                await session.execute(
                    text("DELETE FROM bot_subscribers WHERE bot_id = :bot_id"),
                    {"bot_id": bot_id}
                )
                logger.info("✅ Deleted bot subscribers")
                
                # 2. Удаляем логи использования AI
                await session.execute(
                    text("DELETE FROM ai_usage_logs WHERE bot_id = :bot_id"),
                    {"bot_id": bot_id}
                )
                logger.info("✅ Deleted AI usage logs")
                
                # 3. Удаляем массовые рассылки и их доставки
                await session.execute(
                    text("DELETE FROM mass_broadcast_deliveries WHERE broadcast_id IN (SELECT id FROM mass_broadcasts WHERE bot_id = :bot_id)"),
                    {"bot_id": bot_id}
                )
                await session.execute(
                    text("DELETE FROM mass_broadcasts WHERE bot_id = :bot_id"),
                    {"bot_id": bot_id}
                )
                logger.info("✅ Deleted mass broadcasts")
                
                # 4. Удаляем админ логи
                await session.execute(
                    text("DELETE FROM bot_admin_logs WHERE bot_id = :bot_id"),
                    {"bot_id": bot_id}
                )
                logger.info("✅ Deleted admin logs")
                
                # 5. Удаляем запланированные сообщения
                await session.execute(
                    text("DELETE FROM scheduled_messages WHERE bot_id = :bot_id"),
                    {"bot_id": bot_id}
                )
                logger.info("✅ Deleted scheduled messages")
                
                # 6. Удаляем сообщения рассылок (если есть связанные таблицы)
                await session.execute(
                    text("DELETE FROM broadcast_messages WHERE sequence_id IN (SELECT id FROM broadcast_sequences WHERE bot_id = :bot_id)"),
                    {"bot_id": bot_id}
                )
                await session.execute(
                    text("DELETE FROM broadcast_sequences WHERE bot_id = :bot_id"),
                    {"bot_id": bot_id}
                )
                logger.info("✅ Deleted broadcast sequences")
                
                # 7. Наконец удаляем сам бот
                result = await session.execute(
                    text("DELETE FROM user_bots WHERE bot_id = :bot_id"),
                    {"bot_id": bot_id}
                )
                
                await session.commit()
                
                logger.info("✅ Bot and all related data deleted successfully", 
                           bot_id=bot_id,
                           bot_username=bot_data.bot_username,
                           rows_deleted=result.rowcount)
                
                return True
                
        except Exception as e:
            logger.error("💥 Cascade deletion failed", 
                        bot_id=bot_id,
                        error=str(e),
                        error_type=type(e).__name__)
            return False

    # ===== MESSAGE OPERATIONS =====
    
    @staticmethod
    async def update_bot_messages(bot_id: str, welcome_message: str = None, goodbye_message: str = None):
        """Update bot messages"""
        from database.models import UserBot
        from sqlalchemy import update
        
        update_data = {"updated_at": datetime.now()}
        
        if welcome_message is not None:
            update_data["welcome_message"] = welcome_message
        if goodbye_message is not None:
            update_data["goodbye_message"] = goodbye_message
        
        async with get_db_session() as session:
            await session.execute(
                update(UserBot)
                .where(UserBot.bot_id == bot_id)
                .values(**update_data)
            )
            await session.commit()
    
    @staticmethod
    async def update_welcome_settings(bot_id: str, welcome_message: str = None, welcome_button_text: str = None, confirmation_message: str = None):
        """Update welcome settings"""
        from database.models import UserBot
        from sqlalchemy import update
        
        update_data = {"updated_at": datetime.now()}
        
        if welcome_message is not None:
            update_data["welcome_message"] = welcome_message
        if welcome_button_text is not None:
            update_data["welcome_button_text"] = welcome_button_text
        if confirmation_message is not None:
            update_data["confirmation_message"] = confirmation_message
        
        async with get_db_session() as session:
            await session.execute(
                update(UserBot)
                .where(UserBot.bot_id == bot_id)
                .values(**update_data)
            )
            await session.commit()
    
    @staticmethod
    async def update_goodbye_settings(bot_id: str, goodbye_message: str = None, goodbye_button_text: str = None, goodbye_button_url: str = None):
        """Update goodbye settings"""
        from database.models import UserBot
        from sqlalchemy import update
        
        update_data = {"updated_at": datetime.now()}
        
        if goodbye_message is not None:
            update_data["goodbye_message"] = goodbye_message
        if goodbye_button_text is not None:
            update_data["goodbye_button_text"] = goodbye_button_text
        if goodbye_button_url is not None:
            update_data["goodbye_button_url"] = goodbye_button_url
        
        async with get_db_session() as session:
            await session.execute(
                update(UserBot)
                .where(UserBot.bot_id == bot_id)
                .values(**update_data)
            )
            await session.commit()

    # ===== BROADCAST OPERATIONS =====
    
    @staticmethod
    async def create_broadcast_sequence(bot_id: str):
        """Create broadcast sequence"""
        from database.models import BroadcastSequence
        
        async with get_db_session() as session:
            sequence = BroadcastSequence(bot_id=bot_id)
            session.add(sequence)
            await session.commit()
            await session.refresh(sequence)
            return sequence
    
    @staticmethod
    async def get_broadcast_sequence(bot_id: str):
        """Get broadcast sequence"""
        from database.models import BroadcastSequence
        from sqlalchemy import select
        
        async with get_db_session() as session:
            result = await session.execute(
                select(BroadcastSequence).where(BroadcastSequence.bot_id == bot_id)
            )
            return result.scalar_one_or_none()
    
    @staticmethod
    async def create_broadcast_message(sequence_id: int, message_number: int, message_text: str, delay_hours: float, **kwargs):
        """Create broadcast message"""
        from database.models import BroadcastMessage
        
        message_data = {
            'sequence_id': sequence_id,
            'message_number': message_number,
            'message_text': message_text,
            'delay_hours': delay_hours,
            **kwargs
        }
        
        async with get_db_session() as session:
            message = BroadcastMessage(**message_data)
            session.add(message)
            await session.commit()
            await session.refresh(message)
            return message
    
    @staticmethod
    async def schedule_broadcast_messages_for_subscriber(bot_id: str, subscriber_id: int, sequence_id: int):
        """Schedule broadcast messages for subscriber"""
        from database.models import ScheduledMessage, BroadcastMessage
        from sqlalchemy import select
        
        async with get_db_session() as session:
            # Get all messages in the sequence
            result = await session.execute(
                select(BroadcastMessage)
                .where(BroadcastMessage.sequence_id == sequence_id)
                .order_by(BroadcastMessage.message_number)
            )
            messages = result.scalars().all()
            
            # Schedule each message
            for message in messages:
                scheduled_at = datetime.now() + timedelta(hours=float(message.delay_hours))
                
                scheduled = ScheduledMessage(
                    bot_id=bot_id,
                    subscriber_id=subscriber_id,
                    message_id=message.id,
                    scheduled_at=scheduled_at
                )
                session.add(scheduled)
            
            await session.commit()

    # ===== SIMPLIFIED PLACEHOLDER METHODS =====
    # TODO: Implement remaining methods as needed
    
    @staticmethod
    async def get_bot_full_config(bot_id: str, fresh: bool = False):
        """Get full bot configuration - PLACEHOLDER"""
        logger.warning("get_bot_full_config - implement in bot_manager.py")
        return None


# Database instance for backwards compatibility
db = DatabaseManager()
