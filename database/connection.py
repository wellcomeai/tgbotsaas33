import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import func
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional, List, Union, Tuple
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
        async_session_factory = async_sessionmaker(
            engine, 
            class_=AsyncSession, 
            expire_on_commit=False
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
    """Database operations manager"""
    
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
        from sqlalchemy import update
        
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
    async def get_bot_by_id(bot_id: str):
        """Get bot by ID"""
        from database.models import UserBot
        from sqlalchemy import select
        
        async with get_db_session() as session:
            result = await session.execute(
                select(UserBot).where(UserBot.bot_id == bot_id)
            )
            return result.scalar_one_or_none()
    
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
    
    # ===== UPDATED AI ASSISTANT METHODS =====
    
    @staticmethod
    async def update_ai_assistant(
        bot_id: str,
        assistant_id: Optional[str] = None,
        enabled: Optional[bool] = None,
        settings: Optional[dict] = None
    ):
        """Update AI assistant settings for bot (legacy method)"""
        from database.models import UserBot
        from sqlalchemy import update
        
        async with get_db_session() as session:
            update_data = {}
            
            if assistant_id is not None:
                update_data["ai_assistant_id"] = assistant_id
            
            if enabled is not None:
                update_data["ai_assistant_enabled"] = enabled
            
            if settings is not None:
                update_data["ai_assistant_settings"] = settings
            
            if update_data:
                await session.execute(
                    update(UserBot)
                    .where(UserBot.bot_id == bot_id)
                    .values(**update_data)
                )
                await session.commit()
            
            logger.info(
                "AI assistant updated", 
                bot_id=bot_id,
                fields_updated=list(update_data.keys())
            )
    
    @staticmethod
    async def update_ai_assistant_with_platform(
        bot_id: str,
        api_token: str,
        bot_id_value: int = None,  # ✅ CHANGED: int instead of str
        settings: dict = None,
        platform: str = "chatforyou"  # ✅ DEFAULT: always chatforyou
    ):
        """
        Update AI assistant with simplified platform handling
        
        Args:
            bot_id: ID бота в системе
            api_token: API токен
            bot_id_value: ID сотрудника ChatForYou (число)
            settings: Настройки AI ассистента
            platform: Платформа (всегда chatforyou)
        """
        from database.models import UserBot
        from sqlalchemy import update
        
        async with get_db_session() as session:
            # Prepare update data
            update_data = {
                "ai_assistant_id": api_token,
                "ai_assistant_bot_id": bot_id_value
            }
            
            # Ensure settings exist
            if settings is None:
                settings = {}
            
            settings_with_platform = settings.copy()
            settings_with_platform.update({
                'platform': 'chatforyou',
                'configured_at': datetime.now().isoformat(),
                'api_token': api_token,
            })
            
            if bot_id_value:
                settings_with_platform['chatforyou_bot_id'] = bot_id_value
            
            update_data["ai_assistant_settings"] = settings_with_platform
            
            await session.execute(
                update(UserBot)
                .where(UserBot.bot_id == bot_id)
                .values(**update_data)
            )
            await session.commit()
            
            logger.info(
                "AI assistant updated with simplified platform handling", 
                bot_id=bot_id,
                api_token_length=len(api_token) if api_token else 0,
                has_bot_id=bool(bot_id_value)
            )
    
    @staticmethod
    async def update_ai_credentials(
        bot_id: str,
        api_token: str,
        bot_id_value: int = None,  # ✅ CHANGED: int instead of str
        platform: str = "chatforyou"
    ):
        """
        Update only AI credentials (token + bot_id)
        """
        from database.models import UserBot
        from sqlalchemy import select, update
        
        async with get_db_session() as session:
            # Получаем текущие настройки
            result = await session.execute(
                select(UserBot.ai_assistant_settings).where(UserBot.bot_id == bot_id)
            )
            current_settings = result.scalar_one_or_none() or {}
            
            # Обновляем учетные данные
            updated_settings = current_settings.copy()
            updated_settings['api_token'] = api_token
            updated_settings['platform'] = 'chatforyou'
            
            if bot_id_value:
                updated_settings['chatforyou_bot_id'] = bot_id_value
            
            update_data = {
                "ai_assistant_id": api_token,
                "ai_assistant_bot_id": bot_id_value,
                "ai_assistant_settings": updated_settings
            }
            
            await session.execute(
                update(UserBot)
                .where(UserBot.bot_id == bot_id)
                .values(**update_data)
            )
            await session.commit()
            
            logger.info(
                "AI credentials updated", 
                bot_id=bot_id,
                has_bot_id=bool(bot_id_value)
            )
    
    @staticmethod
    async def get_ai_credentials(bot_id: str) -> dict:
        """
        Get AI credentials for bot
        
        Returns:
            dict with 'api_token', 'bot_id', 'platform' keys
        """
        from database.models import UserBot
        from sqlalchemy import select
        
        async with get_db_session() as session:
            result = await session.execute(
                select(UserBot).where(UserBot.bot_id == bot_id)
            )
            bot = result.scalar_one_or_none()
            
            if not bot:
                return {}
            
            # Определяем платформу
            platform = None
            if bot.ai_assistant_settings:
                platform = bot.ai_assistant_settings.get('detected_platform')
            
            # Получаем bot_id для конкретной платформы
            ai_bot_id = bot.ai_assistant_bot_id  # Основное поле
            
            # Если есть настройки и платформа, попробуем получить специфичный bot_id
            if bot.ai_assistant_settings and platform:
                if platform.lower() == 'chatforyou':
                    ai_bot_id = bot.ai_assistant_settings.get('chatforyou_bot_id', ai_bot_id)
                elif platform.lower() == 'protalk':
                    ai_bot_id = bot.ai_assistant_settings.get('protalk_bot_id', ai_bot_id)
            
            return {
                'api_token': bot.ai_assistant_id,
                'bot_id': ai_bot_id,
                'platform': platform
            }
    
    @staticmethod
    async def detect_and_validate_ai_platform(api_token: str, test_bot_id: str = None) -> Tuple[bool, Optional[str], str]:
        """
        Simplified: Just cache token and test with real data if bot_id provided
        
        Args:
            api_token: API токен для ChatForYou
            test_bot_id: ID сотрудника для финального тестирования
            
        Returns: (success, platform_name, error_message)
        """
        try:
            logger.info(f"Caching AI token: {api_token[:10]}...")
            
            if test_bot_id:
                # ✅ FINAL TEST: With real bot_id
                from services.ai_assistant import ai_client
                
                logger.info(f"Testing ChatForYou with bot_id: {test_bot_id}")
                
                try:
                    # Попытка реального запроса
                    response = await ai_client.send_message(
                        api_token=api_token,
                        message="test",
                        user_id=12345,
                        platform="chatforyou",
                        bot_id=int(test_bot_id)
                    )
                    
                    if response is not None:
                        logger.info("✅ ChatForYou test successful")
                        return True, "chatforyou", ""
                    else:
                        logger.warning("❌ ChatForYou test failed: empty response")
                        return False, None, "Проверьте правильность API токена и ID сотрудника"
                        
                except Exception as e:
                    logger.error(f"❌ ChatForYou test error: {str(e)}")
                    return False, None, f"Ошибка при проверке: {str(e)}"
            
            else:
                # ✅ INITIAL CACHE: Just accept token without validation
                logger.info("✅ Token cached for later validation")
                return True, "chatforyou", ""
                
        except Exception as e:
            logger.error(f"Error in platform detection: {str(e)}")
            return False, None, f"Ошибка при обработке токена: {str(e)}"
    
    # ===== EXISTING MESSAGE METHODS =====
    
    @staticmethod
    async def update_bot_messages(
        bot_id: str, 
        welcome_message: Optional[str] = None, 
        goodbye_message: Optional[str] = None
    ):
        """Update bot welcome and goodbye messages"""
        from database.models import UserBot
        from sqlalchemy import update
        
        async with get_db_session() as session:
            update_data = {}
            
            if welcome_message is not None:
                update_data["welcome_message"] = welcome_message
            
            if goodbye_message is not None:
                update_data["goodbye_message"] = goodbye_message
            
            if update_data:
                await session.execute(
                    update(UserBot)
                    .where(UserBot.bot_id == bot_id)
                    .values(**update_data)
                )
                await session.commit()
            
            logger.info(
                "Bot messages updated", 
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
        """Update welcome message settings including button and confirmation"""
        from database.models import UserBot
        from sqlalchemy import update
        
        async with get_db_session() as session:
            update_data = {}
            
            if welcome_message is not None:
                update_data["welcome_message"] = welcome_message
            
            if welcome_button_text is not None:
                update_data["welcome_button_text"] = welcome_button_text
            
            if confirmation_message is not None:
                update_data["confirmation_message"] = confirmation_message
            
            if update_data:
                await session.execute(
                    update(UserBot)
                    .where(UserBot.bot_id == bot_id)
                    .values(**update_data)
                )
                await session.commit()
            
            logger.info(
                "Welcome settings updated", 
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
        """Update goodbye message settings including button"""
        from database.models import UserBot
        from sqlalchemy import update
        
        async with get_db_session() as session:
            update_data = {}
            
            if goodbye_message is not None:
                update_data["goodbye_message"] = goodbye_message
            
            if goodbye_button_text is not None:
                update_data["goodbye_button_text"] = goodbye_button_text
            
            if goodbye_button_url is not None:
                update_data["goodbye_button_url"] = goodbye_button_url
            
            if update_data:
                await session.execute(
                    update(UserBot)
                    .where(UserBot.bot_id == bot_id)
                    .values(**update_data)
                )
                await session.commit()
            
            logger.info(
                "Goodbye settings updated", 
                bot_id=bot_id,
                fields_updated=list(update_data.keys())
            )
    
    # ===== BROADCAST SEQUENCE METHODS =====
    
    @staticmethod
    async def create_broadcast_sequence(bot_id: str):
        """Create broadcast sequence for bot"""
        from database.models import BroadcastSequence
        
        async with get_db_session() as session:
            sequence = BroadcastSequence(bot_id=bot_id, is_enabled=True)
            session.add(sequence)
            await session.commit()
            await session.refresh(sequence)
            return sequence
    
    @staticmethod
    async def get_broadcast_sequence(bot_id: str):
        """Get broadcast sequence for bot"""
        from database.models import BroadcastSequence
        from sqlalchemy import select
        
        async with get_db_session() as session:
            result = await session.execute(
                select(BroadcastSequence).where(BroadcastSequence.bot_id == bot_id)
            )
            return result.scalar_one_or_none()
    
    @staticmethod
    async def update_broadcast_sequence_status(bot_id: str, enabled: bool):
        """Enable/disable broadcast sequence"""
        from database.models import BroadcastSequence
        from sqlalchemy import update
        
        async with get_db_session() as session:
            await session.execute(
                update(BroadcastSequence)
                .where(BroadcastSequence.bot_id == bot_id)
                .values(is_enabled=enabled, updated_at=datetime.now())
            )
            await session.commit()
    
    # ===== UPDATED BROADCAST MESSAGE METHODS =====
    
    @staticmethod
    async def create_broadcast_message(
        sequence_id: int,
        message_number: int,
        message_text: str,
        delay_hours: Union[int, float],
        media_url: Optional[str] = None,  # Оставляем для обратной совместимости
        media_type: Optional[str] = None,
        media_file_id: Optional[str] = None,
        media_file_unique_id: Optional[str] = None,
        media_file_size: Optional[int] = None,
        media_filename: Optional[str] = None
    ):
        """Create broadcast message with Decimal conversion handling"""
        from database.models import BroadcastMessage
        from sqlalchemy import select
        
        async with get_db_session() as session:
            # Check for existing message number in sequence
            existing_result = await session.execute(
                select(BroadcastMessage).where(
                    BroadcastMessage.sequence_id == sequence_id,
                    BroadcastMessage.message_number == message_number
                )
            )
            existing_message = existing_result.scalar_one_or_none()
            
            if existing_message:
                logger.warning(
                    "Message number already exists", 
                    sequence_id=sequence_id,
                    message_number=message_number,
                    existing_message_id=existing_message.id
                )
                raise ValueError(f"Message number {message_number} already exists in sequence {sequence_id}")
            
            # Convert delay_hours to Decimal for database storage
            delay_decimal = Decimal(str(delay_hours))
            
            # Create message with new media fields
            message = BroadcastMessage(
                sequence_id=sequence_id,
                message_number=message_number,
                message_text=message_text,
                delay_hours=delay_decimal,
                media_url=media_url,
                media_type=media_type,
                media_file_id=media_file_id,
                media_file_unique_id=media_file_unique_id,
                media_file_size=media_file_size,
                media_filename=media_filename
            )
            session.add(message)
            await session.commit()
            await session.refresh(message)
            
            logger.info("Broadcast message created", 
                       message_id=message.id,
                       sequence_id=sequence_id,
                       message_number=message_number,
                       delay_hours_original=delay_hours,
                       delay_hours_stored=float(message.delay_hours))
            
            return message
    
    @staticmethod
    async def get_broadcast_messages(sequence_id: int):
        """Get all broadcast messages for sequence"""
        from database.models import BroadcastMessage
        from sqlalchemy import select
        
        async with get_db_session() as session:
            result = await session.execute(
                select(BroadcastMessage)
                .where(BroadcastMessage.sequence_id == sequence_id)
                .order_by(BroadcastMessage.message_number)
            )
            return result.scalars().all()
    
    @staticmethod
    async def get_broadcast_message_by_id(message_id: int):
        """Get broadcast message by ID"""
        from database.models import BroadcastMessage
        from sqlalchemy import select
        
        async with get_db_session() as session:
            result = await session.execute(
                select(BroadcastMessage).where(BroadcastMessage.id == message_id)
            )
            return result.scalar_one_or_none()
    
    @staticmethod
    async def update_broadcast_message(
        message_id: int,
        message_text: Optional[str] = None,
        delay_hours: Optional[Union[int, float]] = None,
        media_url: Optional[str] = None,  # Можем оставить для совместимости
        media_type: Optional[str] = None,
        is_active: Optional[bool] = None,
        utm_campaign: Optional[str] = None,
        utm_content: Optional[str] = None,
        media_file_id: Optional[str] = None,
        media_file_unique_id: Optional[str] = None,
        media_file_size: Optional[int] = None,
        media_filename: Optional[str] = None
    ):
        """Update broadcast message with Decimal conversion"""
        from database.models import BroadcastMessage
        from sqlalchemy import update
        
        async with get_db_session() as session:
            update_data = {}
            
            if message_text is not None:
                update_data["message_text"] = message_text
            if delay_hours is not None:
                # Convert to Decimal for database storage
                update_data["delay_hours"] = Decimal(str(delay_hours))
            if media_url is not None:
                update_data["media_url"] = media_url
            if media_type is not None:
                update_data["media_type"] = media_type
            if is_active is not None:
                update_data["is_active"] = is_active
            if utm_campaign is not None:
                update_data["utm_campaign"] = utm_campaign
            if utm_content is not None:
                update_data["utm_content"] = utm_content
            if media_file_id is not None:
                update_data["media_file_id"] = media_file_id
            if media_file_unique_id is not None:
                update_data["media_file_unique_id"] = media_file_unique_id
            if media_file_size is not None:
                update_data["media_file_size"] = media_file_size
            if media_filename is not None:
                update_data["media_filename"] = media_filename
            
            if update_data:
                update_data["updated_at"] = datetime.now()
                await session.execute(
                    update(BroadcastMessage)
                    .where(BroadcastMessage.id == message_id)
                    .values(**update_data)
                )
                await session.commit()
                
                logger.info("Broadcast message updated",
                           message_id=message_id,
                           delay_hours_updated=delay_hours is not None,
                           utm_updated=utm_campaign is not None or utm_content is not None)
    
    @staticmethod
    async def delete_broadcast_message(message_id: int):
        """Delete broadcast message"""
        from database.models import BroadcastMessage
        
        async with get_db_session() as session:
            message = await session.get(BroadcastMessage, message_id)
            if message:
                await session.delete(message)
                await session.commit()
    
    @staticmethod
    async def reschedule_pending_messages(message_id: int, new_delay_hours: float):
        """Reschedule pending messages when delay changes"""
        from database.models import ScheduledMessage, BroadcastMessage, BotSubscriber
        from sqlalchemy import select, update
        
        async with get_db_session() as session:
            try:
                # Get all pending messages for this message_id
                result = await session.execute(
                    select(ScheduledMessage, BroadcastMessage)
                    .join(BroadcastMessage, ScheduledMessage.message_id == BroadcastMessage.id)
                    .where(
                        BroadcastMessage.id == message_id,
                        ScheduledMessage.status == 'pending'
                    )
                )
                
                scheduled_messages = result.fetchall()
                
                if not scheduled_messages:
                    logger.info("No pending messages to reschedule", message_id=message_id)
                    return
                
                # Recalculate time for each message
                for scheduled_msg, broadcast_msg in scheduled_messages:
                    # Find when user clicked button (funnel_started_at)
                    subscriber_result = await session.execute(
                        select(BotSubscriber.funnel_started_at)
                        .where(BotSubscriber.user_id == scheduled_msg.subscriber_id)
                        .where(BotSubscriber.bot_id == scheduled_msg.bot_id)
                    )
                    subscriber = subscriber_result.scalar_one_or_none()
                    
                    if subscriber and subscriber:
                        # Recalculate scheduled_at
                        new_scheduled_at = subscriber + timedelta(hours=float(new_delay_hours))
                        
                        # Update record
                        await session.execute(
                            update(ScheduledMessage)
                            .where(ScheduledMessage.id == scheduled_msg.id)
                            .values(scheduled_at=new_scheduled_at)
                        )
                
                await session.commit()
                
                logger.info("Rescheduled pending messages", 
                           message_id=message_id,
                           new_delay_hours=new_delay_hours,
                           affected_messages=len(scheduled_messages))
                
            except Exception as e:
                logger.error("Failed to reschedule pending messages", 
                            message_id=message_id, 
                            error=str(e))
                await session.rollback()
    
    # ===== MESSAGE BUTTON METHODS =====
    
    @staticmethod
    async def create_message_button(
        message_id: int,
        button_text: str,
        button_url: str,
        position: int
    ):
        """Create message button"""
        from database.models import MessageButton
        
        async with get_db_session() as session:
            button = MessageButton(
                message_id=message_id,
                button_text=button_text,
                button_url=button_url,
                position=position
            )
            session.add(button)
            await session.commit()
            await session.refresh(button)
            return button
    
    @staticmethod
    async def get_message_buttons(message_id: int):
        """Get buttons for message"""
        from database.models import MessageButton
        from sqlalchemy import select
        
        async with get_db_session() as session:
            result = await session.execute(
                select(MessageButton)
                .where(MessageButton.message_id == message_id)
                .order_by(MessageButton.position)
            )
            return result.scalars().all()
    
    @staticmethod
    async def update_message_button(
        button_id: int,
        button_text: Optional[str] = None,
        button_url: Optional[str] = None,
        position: Optional[int] = None
    ):
        """Update message button"""
        from database.models import MessageButton
        from sqlalchemy import update
        
        async with get_db_session() as session:
            update_data = {}
            
            if button_text is not None:
                update_data["button_text"] = button_text
            if button_url is not None:
                update_data["button_url"] = button_url
            if position is not None:
                update_data["position"] = position
            
            if update_data:
                await session.execute(
                    update(MessageButton)
                    .where(MessageButton.id == button_id)
                    .values(**update_data)
                )
                await session.commit()
    
    @staticmethod
    async def delete_message_button(button_id: int):
        """Delete message button"""
        from database.models import MessageButton
        
        async with get_db_session() as session:
            button = await session.get(MessageButton, button_id)
            if button:
                await session.delete(button)
                await session.commit()
    
    # ===== SCHEDULED MESSAGE METHODS =====
    
    @staticmethod
    async def schedule_broadcast_messages_for_subscriber(
        bot_id: str,
        subscriber_id: int,
        sequence_id: int
    ):
        """Schedule all broadcast messages for new subscriber with Decimal handling"""
        from database.models import BroadcastMessage, ScheduledMessage
        from sqlalchemy import select
        
        async with get_db_session() as session:
            # Get all active messages in sequence
            result = await session.execute(
                select(BroadcastMessage)
                .where(
                    BroadcastMessage.sequence_id == sequence_id,
                    BroadcastMessage.is_active == True
                )
                .order_by(BroadcastMessage.message_number)
            )
            messages = result.scalars().all()
            
            base_time = datetime.now()
            scheduled_messages = []
            
            for message in messages:
                # Convert Decimal to float for timedelta calculation
                try:
                    delay_hours_float = float(message.delay_hours)
                    scheduled_at = base_time + timedelta(hours=delay_hours_float)
                    
                    scheduled_message = ScheduledMessage(
                        bot_id=bot_id,
                        subscriber_id=subscriber_id,
                        message_id=message.id,
                        scheduled_at=scheduled_at,
                        status='pending'
                    )
                    session.add(scheduled_message)
                    scheduled_messages.append(scheduled_message)
                    
                except (ValueError, TypeError) as e:
                    logger.error("Failed to convert delay_hours",
                               message_id=message.id,
                               delay_hours_value=message.delay_hours,
                               delay_hours_type=type(message.delay_hours),
                               error=str(e))
                    continue  # Skip this message
            
            await session.commit()
            
            logger.info(
                "Broadcast messages scheduled with Decimal conversion", 
                bot_id=bot_id,
                subscriber_id=subscriber_id,
                messages_count=len(scheduled_messages),
                total_messages=len(messages),
                delays=[float(msg.delay_hours) for msg in messages]
            )
            
            return scheduled_messages
    
    @staticmethod
    async def get_pending_scheduled_messages(limit: int = 100):
        """Get pending scheduled messages ready to send"""
        from database.models import ScheduledMessage
        from sqlalchemy import select
        
        async with get_db_session() as session:
            result = await session.execute(
                select(ScheduledMessage)
                .where(
                    ScheduledMessage.status == 'pending',
                    ScheduledMessage.scheduled_at <= datetime.now()
                )
                .order_by(ScheduledMessage.scheduled_at)
                .limit(limit)
            )
            return result.scalars().all()
    
    @staticmethod
    async def update_scheduled_message_status(
        message_id: int,
        status: str,
        error_message: Optional[str] = None
    ):
        """Update scheduled message status"""
        from database.models import ScheduledMessage
        from sqlalchemy import update
        
        async with get_db_session() as session:
            update_data = {
                "status": status,
                "sent_at": datetime.now() if status == 'sent' else None,
                "error_message": error_message
            }
            
            await session.execute(
                update(ScheduledMessage)
                .where(ScheduledMessage.id == message_id)
                .values(**update_data)
            )
            await session.commit()
    
    @staticmethod
    async def get_scheduled_messages_stats(bot_id: str):
        """Get statistics for scheduled messages"""
        from database.models import ScheduledMessage
        from sqlalchemy import select, func
        
        async with get_db_session() as session:
            # Count by status
            result = await session.execute(
                select(
                    ScheduledMessage.status,
                    func.count(ScheduledMessage.id).label('count')
                )
                .where(ScheduledMessage.bot_id == bot_id)
                .group_by(ScheduledMessage.status)
            )
            
            stats = {'pending': 0, 'sent': 0, 'failed': 0, 'cancelled': 0}
            for row in result.fetchall():
                stats[row.status] = row.count
            
            return stats
    
    # ===== AI USAGE TRACKING METHODS =====
    
    @staticmethod
    async def get_or_create_ai_usage(bot_id: str, user_id: int, date: datetime = None) -> 'AIUsageLog':
        """Получить или создать запись использования ИИ на сегодня"""
        from database.models import AIUsageLog
        from sqlalchemy import select
        
        if not date:
            date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        async with get_db_session() as session:
            # Ищем существующую запись
            result = await session.execute(
                select(AIUsageLog).where(
                    AIUsageLog.bot_id == bot_id,
                    AIUsageLog.user_id == user_id,
                    AIUsageLog.date == date
                )
            )
            usage_log = result.scalar_one_or_none()
            
            if not usage_log:
                # Создаем новую запись
                usage_log = AIUsageLog(
                    bot_id=bot_id,
                    user_id=user_id,
                    date=date,
                    messages_count=0
                )
                session.add(usage_log)
                await session.commit()
                await session.refresh(usage_log)
            
            return usage_log

    @staticmethod
    async def increment_ai_usage(bot_id: str, user_id: int) -> tuple[int, Optional[int]]:
        """Увеличить счетчик использования ИИ. Возвращает (текущий_счет, лимит_или_None)"""
        from database.models import AIUsageLog
        from sqlalchemy import update
        
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Получаем или создаем запись
        usage_log = await DatabaseManager.get_or_create_ai_usage(bot_id, user_id, today)
        
        async with get_db_session() as session:
            # Увеличиваем счетчик
            await session.execute(
                update(AIUsageLog)
                .where(AIUsageLog.id == usage_log.id)
                .values(
                    messages_count=AIUsageLog.messages_count + 1,
                    updated_at=datetime.now()
                )
            )
            await session.commit()
        
        # Получаем лимит из настроек бота
        bot = await DatabaseManager.get_bot_by_id(bot_id)
        daily_limit = None
        if bot and bot.ai_assistant_settings:
            daily_limit = bot.ai_assistant_settings.get('daily_limit')
        
        return usage_log.messages_count + 1, daily_limit

    @staticmethod
    async def get_ai_usage_today(bot_id: str, user_id: int) -> int:
        """Получить количество использований ИИ сегодня"""
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        usage_log = await DatabaseManager.get_or_create_ai_usage(bot_id, user_id, today)
        return usage_log.messages_count

    # ===== ENHANCED SUBSCRIBER METHODS =====
    
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
        from sqlalchemy import update
        
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
    
    @staticmethod
    async def get_subscriber_info(user_id: int):
        """Get subscriber information"""
        from database.models import BotSubscriber
        from sqlalchemy import select
        
        async with get_db_session() as session:
            result = await session.execute(
                select(BotSubscriber).where(BotSubscriber.user_id == user_id)
            )
            return result.scalar_one_or_none()
    
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
        from sqlalchemy import select
        
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
            
            await session.commit()
            await session.refresh(subscriber)
            return subscriber
    
    # ===== EXISTING METHODS =====
    
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
    async def get_updated_bots(bot_ids: list):
        """Get updated bots by IDs"""
        from database.models import UserBot
        from sqlalchemy import select
        
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
        from sqlalchemy import update
        
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
    
    @staticmethod
    async def update_bot_subscribers(bot_id: str, subscriber_count: int):
        """Update bot subscriber count"""
        from database.models import UserBot
        from sqlalchemy import update
        
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
    
    # ===== НОВЫЕ НЕДОСТАЮЩИЕ МЕТОДЫ =====
    
    @staticmethod
    async def get_subscriber_by_bot_and_user(bot_id: str, user_id: int):
        """Get subscriber by bot_id and user_id"""
        from database.models import BotSubscriber
        from sqlalchemy import select
        
        async with get_db_session() as session:
            result = await session.execute(
                select(BotSubscriber).where(
                    BotSubscriber.bot_id == bot_id,
                    BotSubscriber.user_id == user_id
                )
            )
            return result.scalar_one_or_none()
    
    @staticmethod
    async def get_bot_statistics(bot_id: str) -> dict:
        """Get comprehensive bot statistics"""
        from database.models import UserBot, BotSubscriber, ScheduledMessage, AIUsageLog
        from sqlalchemy import select, func
        
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
                    'name': bot.name,
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
                    'has_credentials': bool(bot.ai_assistant_id),
                    'settings': bot.ai_assistant_settings or {}
                }
            }


# Database instance
db = DatabaseManager()
