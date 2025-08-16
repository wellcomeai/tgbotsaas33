import asyncio
import json
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import func, select
from sqlalchemy import text
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
    
    # ===== UTILITY METHODS =====
    
    @staticmethod
    async def fetch_all(query, *params):
        """Execute query and fetch all results"""
        from sqlalchemy import text
        async with get_db_session() as session:
            result = await session.execute(text(query), params if params else [])
            return result.fetchall()

    @staticmethod
    async def fetch_one(query, *params):
        """Execute query and fetch one result"""
        from sqlalchemy import text
        async with get_db_session() as session:
            result = await session.execute(text(query), params if params else [])
            return result.fetchone()

    @staticmethod
    async def execute(query, *params):
        """Execute query without returning results"""
        from sqlalchemy import text
        async with get_db_session() as session:
            await session.execute(text(query), params if params else [])
            await session.commit()
    
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
        """✅ ОБНОВЛЕНО: Get bot by ID with optional fresh data"""
        from database.models import UserBot
        from sqlalchemy import select
        
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
    async def create_payment_record(payment_data: dict):
        """✅ КРИТИЧЕСКИ ИСПРАВЛЕННЫЙ: Create payment record"""
        from database.models import Payment
        
        try:
            logger.info("💳 Creating payment record", 
                       user_id=payment_data.get('user_id'),
                       order_id=payment_data.get('order_id'),
                       amount=payment_data.get('amount'))
            
            async with get_db_session() as session:
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Создаем ОБЪЕКТ Payment, а не список
                # Убеждаемся что payment_data содержит правильные поля
                required_fields = ['user_id', 'order_id', 'amount', 'status']
                for field in required_fields:
                    if field not in payment_data:
                        raise ValueError(f"Missing required field: {field}")
                
                # Создаем единичный объект Payment
                payment = Payment(**payment_data)
                session.add(payment)
                await session.commit()
                await session.refresh(payment)
                
                logger.info("✅ Payment record created successfully", 
                           payment_id=payment.id,
                           user_id=payment.user_id,
                           order_id=payment.order_id,
                           amount=payment.amount,
                           status=payment.status)
                
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Возвращаем словарь с данными объекта
                return {
                    'id': payment.id,
                    'user_id': payment.user_id,
                    'order_id': payment.order_id,
                    'amount': float(payment.amount) if payment.amount else 0.0,
                    'status': payment.status,
                    'created_at': payment.created_at.isoformat() if payment.created_at else None,
                    'updated_at': payment.updated_at.isoformat() if payment.updated_at else None
                }
                
        except Exception as e:
            logger.error("❌ Failed to create payment record", 
                        error=str(e),
                        error_type=type(e).__name__,
                        payment_data=payment_data,
                        exc_info=True)
            raise

    # ===== SUBSCRIPTION METHODS =====

    @staticmethod
    async def get_subscription_by_order_id(order_id: str):
        """Get subscription by order ID"""
        from database.models import Subscription
        from sqlalchemy import select
        
        async with get_db_session() as session:
            result = await session.execute(
                select(Subscription).where(Subscription.order_id == order_id)
            )
            subscription = result.scalar_one_or_none()
            
            if subscription:
                return {
                    'id': subscription.id,
                    'user_id': subscription.user_id,
                    'plan_id': subscription.plan_id,
                    'order_id': subscription.order_id,
                    'status': subscription.status,
                    'start_date': subscription.start_date,
                    'end_date': subscription.end_date,
                    'amount': subscription.amount
                }
            return None

    @staticmethod
    async def create_subscription(subscription_data: dict):
        """Create new subscription"""
        from database.models import Subscription
        
        async with get_db_session() as session:
            subscription = Subscription(**subscription_data)
            session.add(subscription)
            await session.commit()
            await session.refresh(subscription)
            
            return {
                'id': subscription.id,
                'user_id': subscription.user_id,
                'plan_id': subscription.plan_id,
                'order_id': subscription.order_id,
                'status': subscription.status,
                'start_date': subscription.start_date,
                'end_date': subscription.end_date,
                'amount': subscription.amount
            }

    @staticmethod
    async def get_active_subscription(user_id: int):
        """✅ КРИТИЧЕСКИ ИСПРАВЛЕННЫЙ: Get active subscription for user"""
        from database.models import Subscription
        from sqlalchemy import select, and_
        
        try:
            logger.info("🔍 Getting active subscription", user_id=user_id)
            
            async with get_db_session() as session:
                result = await session.execute(
                    select(Subscription).where(
                        and_(
                            Subscription.user_id == user_id,
                            Subscription.status == 'active',
                            Subscription.end_date > datetime.now()
                        )
                    ).order_by(Subscription.end_date.desc())
                )
                subscription = result.scalar_one_or_none()
                
                if subscription:
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Возвращаем СЛОВАРЬ, а не объект
                    subscription_dict = {
                        'id': subscription.id,
                        'user_id': subscription.user_id,
                        'plan_id': subscription.plan_id,
                        'plan_name': getattr(subscription, 'plan_name', None),
                        'order_id': subscription.order_id,
                        'status': subscription.status,
                        'start_date': subscription.start_date.isoformat() if subscription.start_date else None,
                        'end_date': subscription.end_date.isoformat() if subscription.end_date else None,
                        'amount': float(subscription.amount) if subscription.amount else 0.0,
                        'created_at': subscription.created_at.isoformat() if subscription.created_at else None,
                        'updated_at': subscription.updated_at.isoformat() if subscription.updated_at else None
                    }
                    
                    logger.info("✅ Active subscription found", 
                               user_id=user_id,
                               subscription_id=subscription.id,
                               plan_id=subscription.plan_id,
                               end_date=subscription.end_date)
                    
                    return subscription_dict
                
                logger.info("❌ No active subscription found", user_id=user_id)
                return None
                
        except Exception as e:
            logger.error("❌ Failed to get active subscription", 
                        error=str(e),
                        error_type=type(e).__name__,
                        user_id=user_id,
                        exc_info=True)
            return None

    @staticmethod
    async def get_users_with_expiring_subscriptions(days_ahead: int):
        """Get subscriptions expiring in N days"""
        from database.models import Subscription
        from sqlalchemy import select, and_
        
        target_date = datetime.now() + timedelta(days=days_ahead)
        next_day = target_date + timedelta(days=1)
        
        async with get_db_session() as session:
            result = await session.execute(
                select(Subscription).where(
                    and_(
                        Subscription.status == 'active',
                        Subscription.end_date >= target_date,
                        Subscription.end_date < next_day
                    )
                )
            )
            subscriptions = result.scalars().all()
            
            return [
                {
                    'id': sub.id,
                    'user_id': sub.user_id,
                    'plan_id': sub.plan_id,
                    'plan_name': getattr(sub, 'plan_name', None),
                    'end_date': sub.end_date,
                    'status': sub.status
                }
                for sub in subscriptions
            ]

    @staticmethod
    async def get_subscription_stats():
        """Get subscription statistics"""
        try:
            query = """
                SELECT 
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE status = 'active' AND end_date > NOW()) as active,
                    COUNT(*) FILTER (WHERE status = 'expired' OR end_date <= NOW()) as expired,
                    COUNT(*) FILTER (WHERE status = 'cancelled') as cancelled,
                    SUM(amount) FILTER (WHERE status = 'active') as active_revenue,
                    SUM(amount) as total_revenue
                FROM subscriptions
            """
            
            async with get_db_session() as session:
                result = await session.execute(text(query))
                row = result.fetchone()
                
                if row:
                    # Правильное извлечение данных из Row объекта
                    total = int(row.total or 0)
                    active = int(row.active or 0)
                    expired = int(row.expired or 0)
                    cancelled = int(row.cancelled or 0)
                    active_revenue = float(row.active_revenue or 0)
                    total_revenue = float(row.total_revenue or 0)
                    
                    return {
                        'total': total,
                        'active': active,
                        'expired': expired,
                        'cancelled': cancelled,
                        'active_revenue': active_revenue,
                        'revenue': total_revenue
                    }
                else:
                    return {
                        'total': 0,
                        'active': 0,
                        'expired': 0,
                        'cancelled': 0,
                        'active_revenue': 0.0,
                        'revenue': 0.0
                    }
                    
        except Exception as e:
            logger.error("Failed to get subscription stats", error=str(e), exc_info=True)
            return {
                'total': 0,
                'active': 0,
                'expired': 0,
                'cancelled': 0,
                'active_revenue': 0.0,
                'revenue': 0.0
            }

    @staticmethod
    async def extend_subscription(subscription_id: int, new_end_date: datetime):
        """Extend subscription end date"""
        from database.models import Subscription
        from sqlalchemy import update
        
        async with get_db_session() as session:
            await session.execute(
                update(Subscription)
                .where(Subscription.id == subscription_id)
                .values(
                    end_date=new_end_date,
                    updated_at=datetime.now()
                )
            )
            await session.commit()

    @staticmethod
    async def update_subscription_status(subscription_id: int, status: str, reason: str = None):
        """Update subscription status"""
        from database.models import Subscription
        from sqlalchemy import update
        
        update_data = {
            'status': status,
            'updated_at': datetime.now()
        }
        
        if reason:
            # Добавляем причину в extra_data
            from sqlalchemy.dialects.postgresql import insert
            # Это упрощенная версия, может потребоваться более сложная логика
            
        async with get_db_session() as session:
            await session.execute(
                update(Subscription)
                .where(Subscription.id == subscription_id)
                .values(**update_data)
            )
            await session.commit()

    @staticmethod  
    async def update_user_limits(user_id: int, limits: dict):
        """Update user limits"""
        from database.models import User
        from sqlalchemy import update
        
        async with get_db_session() as session:
            await session.execute(
                update(User)
                .where(User.id == user_id)
                .values(**limits, updated_at=datetime.now())
            )
            await session.commit()

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

    # ===== AI METHODS =====
    
    @staticmethod
    async def get_ai_config(bot_id: str) -> Optional[dict]:
        """✅ УЛУЧШЕННЫЙ: Получение конфигурации AI (любой платформы) с расширенным логированием"""
        from database.models import UserBot
        from sqlalchemy import select
        
        logger.info("🔍 Loading AI config for bot startup", bot_id=bot_id)
        
        async with get_db_session() as session:
            result = await session.execute(
                select(UserBot).where(UserBot.bot_id == bot_id)
            )
            bot = result.scalar_one_or_none()
            
            if not bot or not bot.ai_assistant_enabled:
                logger.info("❌ No AI config or disabled", 
                           bot_id=bot_id,
                           bot_exists=bool(bot),
                           ai_enabled=bot.ai_assistant_enabled if bot else False)
                return None
            
            config = {
                'bot_id': bot.bot_id,
                'enabled': bot.ai_assistant_enabled,
                'type': bot.ai_assistant_type
            }
            
            if bot.ai_assistant_type == 'openai':
                config.update({
                    'agent_id': bot.openai_agent_id,
                    'agent_name': bot.openai_agent_name,
                    'instructions': bot.openai_agent_instructions,
                    'model': bot.openai_model,
                    'settings': bot.openai_settings or {}
                })
                logger.info("✅ OpenAI config loaded", 
                           bot_id=bot_id,
                           agent_id=bot.openai_agent_id,
                           model=bot.openai_model)
                
            elif bot.ai_assistant_type in ['chatforyou', 'protalk']:
                config.update({
                    'api_token': bot.external_api_token,
                    'bot_id_value': bot.external_bot_id,
                    'platform': bot.external_platform,
                    'settings': bot.external_settings or {}
                })
                logger.info("✅ External AI config loaded", 
                           bot_id=bot_id,
                           platform=bot.ai_assistant_type,
                           has_token=bool(bot.external_api_token))
            else:
                logger.warning("⚠️ Unknown AI type", 
                              bot_id=bot_id,
                              ai_type=bot.ai_assistant_type)
            
            logger.info("✅ AI config loaded successfully", 
                       bot_id=bot_id, 
                       ai_type=config['type'])
            return config
    
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

    # ===== PAYMENT METHODS =====
    
    @staticmethod
    async def get_payment_by_order_id(order_id: str):
        """Get payment record by order ID"""
        from database.models import Payment
        from sqlalchemy import select
        
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    select(Payment).where(Payment.order_id == order_id)
                )
                payment = result.scalar_one_or_none()
                
                if payment:
                    return {
                        'id': payment.id,
                        'user_id': payment.user_id,
                        'order_id': payment.order_id,
                        'amount': float(payment.amount) if payment.amount else 0.0,
                        'status': payment.status,
                        'created_at': payment.created_at.isoformat() if payment.created_at else None,
                        'updated_at': payment.updated_at.isoformat() if payment.updated_at else None
                    }
                return None
                
        except Exception as e:
            logger.error("❌ Failed to get payment by order_id", 
                        error=str(e),
                        order_id=order_id,
                        exc_info=True)
            return None
    
    @staticmethod
    async def update_payment_status(payment_id: int, status: str):
        """Update payment status"""
        from database.models import Payment
        from sqlalchemy import update
        
        try:
            async with get_db_session() as session:
                await session.execute(
                    update(Payment)
                    .where(Payment.id == payment_id)
                    .values(
                        status=status,
                        updated_at=datetime.now()
                    )
                )
                await session.commit()
                
                logger.info("✅ Payment status updated", 
                           payment_id=payment_id,
                           new_status=status)
                return True
                
        except Exception as e:
            logger.error("❌ Failed to update payment status", 
                        error=str(e),
                        payment_id=payment_id,
                        status=status,
                        exc_info=True)
            return False

    # ===== SIMPLIFIED PLACEHOLDER METHODS =====
    # TODO: Implement remaining methods as needed
    
    @staticmethod
    async def get_bot_full_config(bot_id: str, fresh: bool = False):
        """Get full bot configuration - PLACEHOLDER"""
        logger.warning("get_bot_full_config - implement in bot_manager.py")
        return None
    
    @staticmethod
    async def update_ai_assistant(bot_id: str, enabled: bool = True, assistant_id: str = None, settings: dict = None):
        """Update AI assistant - PLACEHOLDER"""
        logger.warning("update_ai_assistant - implement in ai_manager.py")
        return False


# Database instance for backwards compatibility
db = DatabaseManager()
database = db  # Алиас для совместимости с существующим кодом
