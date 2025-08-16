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
        """✅ ИСПРАВЛЕННЫЙ: Execute query and fetch all results as dictionaries"""
        from sqlalchemy import text
        async with get_db_session() as session:
            result = await session.execute(text(query), params if params else [])
            rows = result.fetchall()
            
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Конвертируем Row объекты в словари
            if rows:
                # Получаем названия колонок
                columns = result.keys()
                return [dict(zip(columns, row)) for row in rows]
            return []

    @staticmethod
    async def fetch_one(query, *params):
        """✅ ИСПРАВЛЕННЫЙ: Execute query and fetch one result as dictionary"""
        from sqlalchemy import text
        async with get_db_session() as session:
            result = await session.execute(text(query), params if params else [])
            row = result.fetchone()
            
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Конвертируем Row объект в словарь
            if row:
                columns = result.keys()
                return dict(zip(columns, row))
            return None

    @staticmethod
    async def execute(query, *params):
        """Execute query without returning results"""
        from sqlalchemy import text
        async with get_db_session() as session:
            await session.execute(text(query), params if params else [])
            await session.commit()
    
    # ===== USER METHODS =====
    
    @staticmethod
    async def get_user(user_id: int) -> dict:
        """✅ ИСПРАВЛЕННЫЙ: Get user by ID as dictionary"""
        from database.models import User
        
        try:
            async with get_db_session() as session:
                user = await session.get(User, user_id)
                
                if user:
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Возвращаем словарь
                    return {
                        'id': user.id,
                        'username': user.username,
                        'first_name': user.first_name,
                        'last_name': user.last_name,
                        'plan': user.plan,
                        'subscription_active': user.subscription_active,
                        'subscription_expires_at': user.subscription_expires_at.isoformat() if user.subscription_expires_at else None,
                        'last_payment_date': user.last_payment_date.isoformat() if user.last_payment_date else None,
                        'tokens_limit_total': user.tokens_limit_total,
                        'tokens_used_total': user.tokens_used_total,
                        'tokens_admin_chat_id': user.tokens_admin_chat_id,
                        'tokens_initialized_at': user.tokens_initialized_at.isoformat() if user.tokens_initialized_at else None,
                        'created_at': user.created_at.isoformat() if user.created_at else None,
                        'updated_at': user.updated_at.isoformat() if user.updated_at else None
                    }
                return None
                
        except Exception as e:
            logger.error("❌ Failed to get user", error=str(e), user_id=user_id)
            return None
    
    @staticmethod
    async def create_or_update_user(user_data: dict) -> dict:
        """✅ ИСПРАВЛЕННЫЙ: Create or update user returning dictionary"""
        from database.models import User
        from sqlalchemy import select
        
        try:
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
                
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Возвращаем словарь
                return {
                    'id': user.id,
                    'username': user.username,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'plan': user.plan,
                    'subscription_active': user.subscription_active,
                    'subscription_expires_at': user.subscription_expires_at.isoformat() if user.subscription_expires_at else None,
                    'last_payment_date': user.last_payment_date.isoformat() if user.last_payment_date else None,
                    'tokens_limit_total': user.tokens_limit_total,
                    'tokens_used_total': user.tokens_used_total,
                    'tokens_admin_chat_id': user.tokens_admin_chat_id,
                    'tokens_initialized_at': user.tokens_initialized_at.isoformat() if user.tokens_initialized_at else None,
                    'created_at': user.created_at.isoformat() if user.created_at else None,
                    'updated_at': user.updated_at.isoformat() if user.updated_at else None
                }
                
        except Exception as e:
            logger.error("❌ Failed to create/update user", error=str(e), user_data=user_data)
            return None
    
    @staticmethod
    async def create_or_update_user_with_tokens(user_data: dict, admin_chat_id: int = None) -> dict:
        """✅ ИСПРАВЛЕННЫЙ: Create or update user with token initialization returning dictionary"""
        from database.models import User
        from sqlalchemy import select
        
        try:
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
                
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Возвращаем словарь
                return {
                    'id': user.id,
                    'username': user.username,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'plan': user.plan,
                    'subscription_active': user.subscription_active,
                    'subscription_expires_at': user.subscription_expires_at.isoformat() if user.subscription_expires_at else None,
                    'last_payment_date': user.last_payment_date.isoformat() if user.last_payment_date else None,
                    'tokens_limit_total': user.tokens_limit_total,
                    'tokens_used_total': user.tokens_used_total,
                    'tokens_admin_chat_id': user.tokens_admin_chat_id,
                    'tokens_initialized_at': user.tokens_initialized_at.isoformat() if user.tokens_initialized_at else None,
                    'created_at': user.created_at.isoformat() if user.created_at else None,
                    'updated_at': user.updated_at.isoformat() if user.updated_at else None
                }
                
        except Exception as e:
            logger.error("❌ Failed to create/update user with tokens", error=str(e), user_data=user_data)
            return None

    # ===== BOT METHODS =====
    
    @staticmethod
    async def get_user_bots(user_id: int) -> List[dict]:
        """✅ ИСПРАВЛЕННЫЙ: Get all bots for a user as list of dictionaries"""
        from database.models import UserBot
        from sqlalchemy import select
        
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    select(UserBot)
                    .where(UserBot.user_id == user_id)
                    .order_by(UserBot.created_at.desc())
                )
                bots = result.scalars().all()
                
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Конвертируем в список словарей
                return [
                    {
                        'id': bot.id,
                        'bot_id': bot.bot_id,
                        'user_id': bot.user_id,
                        'bot_name': bot.bot_name,
                        'bot_username': bot.bot_username,
                        'bot_token': bot.bot_token,
                        'status': bot.status,
                        'is_running': bot.is_running,
                        'ai_assistant_enabled': bot.ai_assistant_enabled,
                        'ai_assistant_type': bot.ai_assistant_type,
                        'openai_agent_id': bot.openai_agent_id,
                        'openai_agent_name': bot.openai_agent_name,
                        'openai_agent_instructions': bot.openai_agent_instructions,
                        'openai_model': bot.openai_model,
                        'openai_settings': bot.openai_settings,
                        'openai_admin_chat_id': bot.openai_admin_chat_id,
                        'tokens_used_input': bot.tokens_used_input,
                        'tokens_used_output': bot.tokens_used_output,
                        'tokens_used_total': bot.tokens_used_total,
                        'external_api_token': bot.external_api_token,
                        'external_bot_id': bot.external_bot_id,
                        'external_platform': bot.external_platform,
                        'external_settings': bot.external_settings,
                        'created_at': bot.created_at.isoformat() if bot.created_at else None,
                        'updated_at': bot.updated_at.isoformat() if bot.updated_at else None
                    }
                    for bot in bots
                ]
                
        except Exception as e:
            logger.error("❌ Failed to get user bots", error=str(e), user_id=user_id)
            return []
    
    @staticmethod
    async def create_user_bot(bot_data: dict) -> dict:
        """✅ ИСПРАВЛЕННЫЙ: Create a new user bot returning dictionary"""
        from database.models import UserBot
        
        try:
            async with get_db_session() as session:
                bot = UserBot(**bot_data)
                session.add(bot)
                await session.commit()
                await session.refresh(bot)
                
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Возвращаем словарь
                return {
                    'id': bot.id,
                    'bot_id': bot.bot_id,
                    'user_id': bot.user_id,
                    'bot_name': bot.bot_name,
                    'bot_username': bot.bot_username,
                    'bot_token': bot.bot_token,
                    'status': bot.status,
                    'is_running': bot.is_running,
                    'ai_assistant_enabled': bot.ai_assistant_enabled,
                    'ai_assistant_type': bot.ai_assistant_type,
                    'openai_agent_id': bot.openai_agent_id,
                    'openai_agent_name': bot.openai_agent_name,
                    'openai_agent_instructions': bot.openai_agent_instructions,
                    'openai_model': bot.openai_model,
                    'openai_settings': bot.openai_settings,
                    'openai_admin_chat_id': bot.openai_admin_chat_id,
                    'tokens_used_input': bot.tokens_used_input,
                    'tokens_used_output': bot.tokens_used_output,
                    'tokens_used_total': bot.tokens_used_total,
                    'external_api_token': bot.external_api_token,
                    'external_bot_id': bot.external_bot_id,
                    'external_platform': bot.external_platform,
                    'external_settings': bot.external_settings,
                    'created_at': bot.created_at.isoformat() if bot.created_at else None,
                    'updated_at': bot.updated_at.isoformat() if bot.updated_at else None
                }
                
        except Exception as e:
            logger.error("❌ Failed to create user bot", error=str(e), bot_data=bot_data)
            return None
    
    @staticmethod
    async def get_bot_by_id(bot_id: str, fresh: bool = False) -> dict:
        """✅ ИСПРАВЛЕННЫЙ: Get bot by ID with optional fresh data returning dictionary"""
        from database.models import UserBot
        from sqlalchemy import select
        
        try:
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
                else:
                    # Обычное получение (может быть из кэша)
                    result = await session.execute(
                        select(UserBot).where(UserBot.bot_id == bot_id)
                    )
                    bot = result.scalar_one_or_none()
                
                if bot:
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Возвращаем словарь
                    return {
                        'id': bot.id,
                        'bot_id': bot.bot_id,
                        'user_id': bot.user_id,
                        'bot_name': bot.bot_name,
                        'bot_username': bot.bot_username,
                        'bot_token': bot.bot_token,
                        'status': bot.status,
                        'is_running': bot.is_running,
                        'ai_assistant_enabled': bot.ai_assistant_enabled,
                        'ai_assistant_type': bot.ai_assistant_type,
                        'openai_agent_id': bot.openai_agent_id,
                        'openai_agent_name': bot.openai_agent_name,
                        'openai_agent_instructions': bot.openai_agent_instructions,
                        'openai_model': bot.openai_model,
                        'openai_settings': bot.openai_settings,
                        'openai_admin_chat_id': bot.openai_admin_chat_id,
                        'tokens_used_input': bot.tokens_used_input,
                        'tokens_used_output': bot.tokens_used_output,
                        'tokens_used_total': bot.tokens_used_total,
                        'external_api_token': bot.external_api_token,
                        'external_bot_id': bot.external_bot_id,
                        'external_platform': bot.external_platform,
                        'external_settings': bot.external_settings,
                        'created_at': bot.created_at.isoformat() if bot.created_at else None,
                        'updated_at': bot.updated_at.isoformat() if bot.updated_at else None
                    }
                return None
                
        except Exception as e:
            logger.error("❌ Failed to get bot by id", error=str(e), bot_id=bot_id)
            return None

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

    @staticmethod
    async def create_payment_record(payment_data: dict):
        """✅ ИСПРАВЛЕННЫЙ: Create payment record с защитой от ошибок типов"""
        from database.models import Payment
        
        try:
            logger.info("💳 Creating payment record", 
                       user_id=payment_data.get('user_id'),
                       order_id=payment_data.get('order_id'),
                       amount=payment_data.get('amount'))
            
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Валидация и очистка данных
            clean_payment_data = {}
            
            # Обязательные поля
            required_fields = {
                'user_id': int,
                'order_id': str, 
                'amount': float,
                'status': str
            }
            
            for field, expected_type in required_fields.items():
                if field not in payment_data:
                    raise ValueError(f"Missing required field: {field}")
                
                value = payment_data[field]
                if value is None:
                    raise ValueError(f"Field {field} cannot be None")
                
                # Конвертируем в правильный тип
                try:
                    if expected_type == float:
                        clean_payment_data[field] = float(value)
                    elif expected_type == int:
                        clean_payment_data[field] = int(value)
                    elif expected_type == str:
                        clean_payment_data[field] = str(value)
                    else:
                        clean_payment_data[field] = value
                except (ValueError, TypeError) as e:
                    raise ValueError(f"Invalid type for field {field}: {value} (expected {expected_type.__name__})")
            
            # Опциональные поля с дефолтными значениями
            optional_fields = {
                'currency': 'RUB',
                'payment_method': 'robokassa_web',
                'provider': 'robokassa',
                'description': 'Bot Factory subscription',
                'created_at': datetime.now(),
                'updated_at': datetime.now()
            }
            
            for field, default_value in optional_fields.items():
                if field in payment_data and payment_data[field] is not None:
                    # ✅ ИСПРАВЛЕНИЕ: Проверяем что это не список или словарь
                    value = payment_data[field]
                    if isinstance(value, (list, dict)):
                        logger.warning(f"Field {field} is list/dict, using default", 
                                     field=field, 
                                     value_type=type(value).__name__)
                        clean_payment_data[field] = default_value
                    else:
                        clean_payment_data[field] = value
                else:
                    clean_payment_data[field] = default_value
            
            # ✅ ИСПРАВЛЕНИЕ: Убираем все поля которые не относятся к модели Payment
            valid_payment_fields = {
                'user_id', 'subscription_id', 'order_id', 'amount', 'currency', 
                'status', 'payment_method', 'provider', 'external_payment_id',
                'external_transaction_id', 'robokassa_inv_id', 'robokassa_signature',
                'raw_data', 'created_at', 'updated_at', 'processed_at', 
                'webhook_data', 'description', 'user_email', 'user_ip'
            }
            
            final_payment_data = {
                key: value for key, value in clean_payment_data.items() 
                if key in valid_payment_fields
            }
            
            logger.info("💾 Cleaned payment data", 
                       original_keys=list(payment_data.keys()),
                       final_keys=list(final_payment_data.keys()),
                       removed_keys=set(payment_data.keys()) - set(final_payment_data.keys()))
            
            async with get_db_session() as session:
                # Создаем объект Payment с очищенными данными
                payment = Payment(**final_payment_data)
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
                        payment_data_keys=list(payment_data.keys()) if isinstance(payment_data, dict) else None,
                        exc_info=True)
            raise

    # ===== SUBSCRIPTION METHODS =====

    @staticmethod
    async def get_subscription_by_order_id(order_id: str):
        """✅ ИСПРАВЛЕННЫЙ: Get subscription by order ID as dictionary"""
        from database.models import Subscription
        from sqlalchemy import select
        
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    select(Subscription).where(Subscription.order_id == order_id)
                )
                subscription = result.scalar_one_or_none()
                
                if subscription:
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Возвращаем словарь
                    return {
                        'id': subscription.id,
                        'user_id': subscription.user_id,
                        'plan_id': subscription.plan_id,
                        'plan_name': getattr(subscription, 'plan_name', None),
                        'order_id': subscription.order_id,
                        'status': subscription.status,
                        'amount': float(subscription.amount) if subscription.amount else 0.0,
                        'currency': getattr(subscription, 'currency', 'RUB'),
                        'start_date': subscription.start_date.isoformat() if subscription.start_date else None,
                        'end_date': subscription.end_date.isoformat() if subscription.end_date else None,
                        'created_at': subscription.created_at.isoformat() if subscription.created_at else None,
                        'updated_at': subscription.updated_at.isoformat() if subscription.updated_at else None
                    }
                return None
                
        except Exception as e:
            logger.error("❌ Failed to get subscription by order_id", error=str(e), order_id=order_id)
            return None

    @staticmethod
    async def create_subscription(subscription_data: dict):
        """✅ ИСПРАВЛЕННЫЙ: Create subscription с защитой от ошибок типов"""
        from database.models import Subscription
        
        try:
            logger.info("📦 Creating subscription", 
                       user_id=subscription_data.get('user_id'),
                       plan_id=subscription_data.get('plan_id'),
                       order_id=subscription_data.get('order_id'))
            
            # ✅ ИСПРАВЛЕНИЕ: Валидация и очистка данных подписки
            clean_data = {}
            
            # Обязательные поля с типами
            required_fields = {
                'user_id': int,
                'plan_id': str,
                'plan_name': str,
                'amount': float,
                'order_id': str,
                'status': str
            }
            
            for field, expected_type in required_fields.items():
                if field not in subscription_data:
                    raise ValueError(f"Missing required field: {field}")
                
                value = subscription_data[field]
                if value is None:
                    raise ValueError(f"Field {field} cannot be None")
                
                # Конвертируем в правильный тип
                try:
                    if expected_type == float:
                        clean_data[field] = float(value)
                    elif expected_type == int:
                        clean_data[field] = int(value)
                    elif expected_type == str:
                        clean_data[field] = str(value)
                    else:
                        clean_data[field] = value
                except (ValueError, TypeError) as e:
                    raise ValueError(f"Invalid type for field {field}: {value}")
            
            # Опциональные поля
            optional_fields = {
                'currency': 'RUB',
                'payment_method': 'robokassa_web',
                'start_date': datetime.now(),
                'end_date': None,
                'extra_data': None
            }
            
            for field, default_value in optional_fields.items():
                if field in subscription_data and subscription_data[field] is not None:
                    value = subscription_data[field]
                    # ✅ ИСПРАВЛЕНИЕ: Обработка дат
                    if field in ['start_date', 'end_date'] and not isinstance(value, datetime):
                        if isinstance(value, str):
                            try:
                                clean_data[field] = datetime.fromisoformat(value.replace('Z', '+00:00'))
                            except:
                                clean_data[field] = default_value
                        else:
                            clean_data[field] = default_value
                    # ✅ ИСПРАВЛЕНИЕ: Обработка JSON полей
                    elif field == 'extra_data':
                        if isinstance(value, dict):
                            clean_data[field] = value
                        else:
                            clean_data[field] = default_value
                    else:
                        clean_data[field] = value
                else:
                    clean_data[field] = default_value
            
            async with get_db_session() as session:
                subscription = Subscription(**clean_data)
                session.add(subscription)
                await session.commit()
                await session.refresh(subscription)
                
                logger.info("✅ Subscription created successfully",
                           subscription_id=subscription.id,
                           user_id=subscription.user_id,
                           plan_id=subscription.plan_id,
                           order_id=subscription.order_id,
                           amount=subscription.amount)
                
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Возвращаем словарь
                return {
                    'id': subscription.id,
                    'user_id': subscription.user_id,
                    'plan_id': subscription.plan_id,
                    'plan_name': subscription.plan_name,
                    'order_id': subscription.order_id,
                    'status': subscription.status,
                    'amount': float(subscription.amount) if subscription.amount else 0.0,
                    'currency': getattr(subscription, 'currency', 'RUB'),
                    'start_date': subscription.start_date.isoformat() if subscription.start_date else None,
                    'end_date': subscription.end_date.isoformat() if subscription.end_date else None,
                    'created_at': subscription.created_at.isoformat() if subscription.created_at else None,
                    'updated_at': subscription.updated_at.isoformat() if subscription.updated_at else None
                }
                
        except Exception as e:
            logger.error("❌ Failed to create subscription",
                        error=str(e),
                        error_type=type(e).__name__,
                        subscription_data_keys=list(subscription_data.keys()) if isinstance(subscription_data, dict) else None,
                        exc_info=True)
            return None

    @staticmethod
    async def get_active_subscription(user_id: int):
        """✅ ИСПРАВЛЕННЫЙ: Get active subscription с защитой от ошибок"""
        from database.models import Subscription
        from sqlalchemy import select, and_
        
        try:
            logger.info("🔍 Getting active subscription", user_id=user_id)
            
            # ✅ ИСПРАВЛЕНИЕ: Валидация входного параметра
            if not isinstance(user_id, int) or user_id <= 0:
                raise ValueError(f"Invalid user_id: {user_id}. Must be positive integer.")
            
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
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Возвращаем ПРОСТОЙ СЛОВАРЬ
                    subscription_dict = {
                        'id': subscription.id,
                        'user_id': subscription.user_id,
                        'plan_id': subscription.plan_id,
                        'plan_name': getattr(subscription, 'plan_name', None),
                        'order_id': subscription.order_id,
                        'status': subscription.status,
                        'amount': float(subscription.amount) if subscription.amount else 0.0,
                        'currency': getattr(subscription, 'currency', 'RUB')
                    }
                    
                    # ✅ ИСПРАВЛЕНИЕ: Безопасная обработка дат
                    try:
                        if subscription.start_date:
                            subscription_dict['start_date'] = subscription.start_date.isoformat()
                        else:
                            subscription_dict['start_date'] = None
                            
                        if subscription.end_date:
                            subscription_dict['end_date'] = subscription.end_date.isoformat()
                        else:
                            subscription_dict['end_date'] = None
                            
                        if subscription.created_at:
                            subscription_dict['created_at'] = subscription.created_at.isoformat()
                        else:
                            subscription_dict['created_at'] = None
                            
                        if subscription.updated_at:
                            subscription_dict['updated_at'] = subscription.updated_at.isoformat()
                        else:
                            subscription_dict['updated_at'] = None
                            
                    except Exception as date_error:
                        logger.warning("Date conversion error in subscription", 
                                     error=str(date_error),
                                     subscription_id=subscription.id)
                        # Устанавливаем None для проблемных дат
                        subscription_dict.update({
                            'start_date': None,
                            'end_date': None, 
                            'created_at': None,
                            'updated_at': None
                        })
                    
                    logger.info("✅ Active subscription found", 
                               user_id=user_id,
                               subscription_id=subscription.id,
                               plan_id=subscription.plan_id)
                    
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
    async def cleanup_database_inconsistencies():
        """✅ НОВОЕ: Очистка проблемных данных в БД которые могут вызывать ошибки типов"""
        try:
            logger.info("🧹 Starting database cleanup...")
            
            async with get_db_session() as session:
                # Проверяем Payment записи с проблемными типами
                from database.models import Payment
                from sqlalchemy import select
                
                result = await session.execute(select(Payment))
                payments = result.scalars().all()
                
                fixed_count = 0
                
                for payment in payments:
                    needs_fix = False
                    
                    # Проверяем amount
                    if payment.amount is not None and not isinstance(payment.amount, (int, float)):
                        try:
                            payment.amount = float(payment.amount)
                            needs_fix = True
                        except (ValueError, TypeError):
                            payment.amount = 0.0
                            needs_fix = True
                    
                    # Проверяем user_id
                    if payment.user_id is not None and not isinstance(payment.user_id, int):
                        try:
                            payment.user_id = int(payment.user_id)
                            needs_fix = True
                        except (ValueError, TypeError):
                            logger.error("Cannot fix user_id for payment", payment_id=payment.id)
                            continue
                    
                    # Проверяем строковые поля
                    string_fields = ['order_id', 'status', 'currency', 'payment_method', 'provider']
                    for field in string_fields:
                        value = getattr(payment, field, None)
                        if value is not None and not isinstance(value, str):
                            setattr(payment, field, str(value))
                            needs_fix = True
                    
                    if needs_fix:
                        fixed_count += 1
                
                if fixed_count > 0:
                    await session.commit()
                    logger.info("✅ Database cleanup completed", fixed_payments=fixed_count)
                else:
                    logger.info("✅ Database is clean, no fixes needed")
                
                return True
                
        except Exception as e:
            logger.error("❌ Database cleanup failed", error=str(e))
            return False

    @staticmethod
    async def get_users_with_expiring_subscriptions(days_ahead: int):
        """✅ ИСПРАВЛЕННЫЙ: Get subscriptions expiring in N days as list of dictionaries"""
        from database.models import Subscription
        from sqlalchemy import select, and_
        
        try:
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
                
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Возвращаем список словарей
                return [
                    {
                        'id': sub.id,
                        'user_id': sub.user_id,
                        'plan_id': sub.plan_id,
                        'plan_name': getattr(sub, 'plan_name', None),
                        'end_date': sub.end_date.isoformat() if sub.end_date else None,
                        'status': sub.status,
                        'amount': float(sub.amount) if sub.amount else 0.0
                    }
                    for sub in subscriptions
                ]
                
        except Exception as e:
            logger.error("❌ Failed to get expiring subscriptions", error=str(e), days_ahead=days_ahead)
            return []

    @staticmethod
    async def get_subscription_stats():
        """✅ ИСПРАВЛЕННЫЙ: Get subscription statistics as dictionary"""
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
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Правильное извлечение данных из Row объекта
                    return {
                        'total': int(row.total or 0),
                        'active': int(row.active or 0),
                        'expired': int(row.expired or 0),
                        'cancelled': int(row.cancelled or 0),
                        'active_revenue': float(row.active_revenue or 0),
                        'revenue': float(row.total_revenue or 0)
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
        """✅ ИСПРАВЛЕННЫЙ: Get users with expired subscriptions as list of dictionaries"""
        from database.models import User
        from sqlalchemy import select
        
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    select(User)
                    .where(
                        User.subscription_active == True,
                        User.subscription_expires_at < datetime.now()
                    )
                )
                users = result.scalars().all()
                
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Возвращаем список словарей
                return [
                    {
                        'id': user.id,
                        'username': user.username,
                        'plan': user.plan,
                        'subscription_expires_at': user.subscription_expires_at.isoformat() if user.subscription_expires_at else None,
                        'subscription_active': user.subscription_active
                    }
                    for user in users
                ]
                
        except Exception as e:
            logger.error("❌ Failed to get expired subscriptions", error=str(e))
            return []
    
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

    @staticmethod
    async def get_user_token_balance(user_id: int):
        """✅ ИСПРАВЛЕННЫЙ: Get user token balance as dictionary"""
        from database.models import User
        from sqlalchemy import select
        
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    select(User.tokens_used_total, User.tokens_limit_total)
                    .where(User.id == user_id)
                )
                
                data = result.first()
                if not data:
                    return None
                
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Возвращаем словарь
                return {
                    'total_used': int(data.tokens_used_total or 0),
                    'limit': int(data.tokens_limit_total or 500000)
                }
                
        except Exception as e:
            logger.error("Failed to get user token balance", 
                        error=str(e), 
                        user_id=user_id)
            return None

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
        """✅ ИСПРАВЛЕННЫЙ: Get all active bots as list of dictionaries"""
        from database.models import UserBot
        from sqlalchemy import select
        
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    select(UserBot)
                    .where(UserBot.status == "active")
                    .order_by(UserBot.created_at)
                )
                bots = result.scalars().all()
                
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Возвращаем список словарей
                return [
                    {
                        'id': bot.id,
                        'bot_id': bot.bot_id,
                        'user_id': bot.user_id,
                        'bot_name': bot.bot_name,
                        'bot_username': bot.bot_username,
                        'status': bot.status,
                        'is_running': bot.is_running,
                        'ai_assistant_enabled': bot.ai_assistant_enabled,
                        'ai_assistant_type': bot.ai_assistant_type,
                        'created_at': bot.created_at.isoformat() if bot.created_at else None
                    }
                    for bot in bots
                ]
                
        except Exception as e:
            logger.error("❌ Failed to get active bots", error=str(e))
            return []

    # ===== PAYMENT METHODS =====
    
    @staticmethod
    async def get_payment_by_order_id(order_id: str):
        """✅ ИСПРАВЛЕННЫЙ: Get payment record by order ID as dictionary"""
        from database.models import Payment
        from sqlalchemy import select
        
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    select(Payment).where(Payment.order_id == order_id)
                )
                payment = result.scalar_one_or_none()
                
                if payment:
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Возвращаем словарь
                    return {
                        'id': payment.id,
                        'user_id': payment.user_id,
                        'order_id': payment.order_id,
                        'amount': float(payment.amount) if payment.amount else 0.0,
                        'status': payment.status,
                        'currency': getattr(payment, 'currency', 'RUB'),
                        'payment_method': getattr(payment, 'payment_method', None),
                        'provider': getattr(payment, 'provider', None),
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
