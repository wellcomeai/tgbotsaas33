"""
User Manager - handles all user-related database operations.

Responsibilities:
- User registration and updates
- User subscriptions and plans
- Token balance management
- User notifications and settings
- Referral program management
"""

from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select, update, func
import structlog

from ..connection import get_db_session

logger = structlog.get_logger()


class UserManager:
    """Manager for user-related database operations"""
    
    # ===== USER CRUD OPERATIONS =====
    
    @staticmethod
    async def get_user(user_id: int):
        """Get user by ID"""
        from database.models import User
        
        async with get_db_session() as session:
            result = await session.get(User, user_id)
            return result
    
    @staticmethod
    async def create_or_update_user(user_data: dict):
        """Create or update user"""
        from database.models import User
        
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
    async def create_or_update_user_with_tokens(user_data: dict, admin_chat_id: int = None):
        """Create or update user with token initialization"""
        from database.models import User
        
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

    @staticmethod
    async def create_user_with_trial(user_data: dict, admin_chat_id: int = None):
        """Создать пользователя с триалом"""
        from database.models import User
        from config import settings
        
        logger.info("🎁 Creating user with trial", 
                   user_id=user_data.get('id'))
        
        async with get_db_session() as session:
            # Проверяем существование
            result = await session.execute(
                select(User).where(User.id == user_data['id'])
            )
            user = result.scalar_one_or_none()
            
            if user:
                logger.info("User already exists", user_id=user.id)
                return user
            
            # Создаем с триалом и токенами
            now = datetime.now()
            trial_expires = now + timedelta(days=settings.trial_days)
            
            user_data.update({
                # Токены
                'tokens_limit_total': 500000,
                'tokens_used_total': 0,
                'tokens_admin_chat_id': admin_chat_id,
                'tokens_initialized_at': now,
                
                # Триал
                'is_trial_user': True,
                'trial_started_at': now,
                'trial_expires_at': trial_expires,
                'plan': 'trial'
            })
            
            user = User(**user_data)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            
            logger.info("✅ User created with 3-day trial", 
                       user_id=user.id,
                       trial_expires=trial_expires)
            
            return user

    @staticmethod
    async def check_user_has_access(user_id: int) -> tuple[bool, dict]:
        """Проверить имеет ли пользователь доступ"""
        user = await UserManager.get_user(user_id)
        
        if not user:
            return False, {'status': 'not_found'}
        
        status = user.get_subscription_status()
        return status['has_access'], status

    @staticmethod
    async def convert_trial_to_paid(user_id: int) -> bool:
        """Конвертировать триал в платную подписку"""
        from database.models import User
        from config import settings
        
        async with get_db_session() as session:
            now = datetime.now()
            expires_at = now + timedelta(days=settings.subscription_days_per_payment)
            
            await session.execute(
                update(User)
                .where(User.id == user_id)
                .values(
                    trial_converted=True,
                    subscription_active=True,
                    subscription_expires_at=expires_at,
                    last_payment_date=now,
                    plan='ai_admin',
                    updated_at=now
                )
            )
            await session.commit()
            
            logger.info("✅ Trial converted to paid subscription", 
                       user_id=user_id,
                       expires_at=expires_at)
            return True
    
    # ===== USER SUBSCRIPTION OPERATIONS =====
    
    @staticmethod
    async def check_user_subscription(user_id: int) -> bool:
        """Check if user has active subscription"""
        from database.models import User
        
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
        
        async with get_db_session() as session:
            result = await session.execute(
                select(User)
                .where(
                    User.subscription_active == True,
                    User.subscription_expires_at < datetime.now()
                )
            )
            return result.scalars().all()
    
    # ===== TOKEN MANAGEMENT METHODS =====

    @staticmethod
    async def add_tokens_to_user(user_id: int, additional_tokens: int) -> bool:
        """Добавление токенов пользователю (для пополнения)"""
        from database.models import User
        
        logger.info("💰 Adding tokens to user", 
                   user_id=user_id,
                   additional_tokens=additional_tokens)
        
        try:
            async with get_db_session() as session:
                # Получаем текущий лимит
                current_result = await session.execute(
                    select(User.tokens_limit_total)
                    .where(User.id == user_id)
                )
                current_limit = current_result.scalar_one_or_none()
                
                if current_limit is None:
                    logger.error("❌ User not found for token addition", user_id=user_id)
                    return False
                
                new_limit = (current_limit or 0) + additional_tokens
                
                # Обновляем лимит
                await session.execute(
                    update(User)
                    .where(User.id == user_id)
                    .values(
                        tokens_limit_total=new_limit,
                        updated_at=datetime.now()
                    )
                )
                await session.commit()
                
                logger.info("✅ Tokens added to user successfully", 
                           user_id=user_id,
                           old_limit=current_limit,
                           additional_tokens=additional_tokens,
                           new_limit=new_limit)
                
                return True
                
        except Exception as e:
            logger.error("💥 Failed to add tokens to user", 
                        user_id=user_id,
                        error=str(e),
                        error_type=type(e).__name__)
            return False

    @staticmethod
    async def check_token_limit(user_id: int) -> tuple[bool, int, int]:
        """Проверить лимит токенов для пользователя"""
        from database.models import User
        
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
    async def get_user_token_balance(user_id: int) -> dict:
        """Получить детальный баланс токенов пользователя"""
        from database.models import User, UserBot
        
        logger.info("💰 Getting user token balance", user_id=user_id)
        
        try:
            async with get_db_session() as session:
                # Получаем данные из User (основные)
                user_result = await session.execute(
                    select(User)
                    .where(User.id == user_id)
                )
                user = user_result.scalar_one_or_none()
                
                if not user:
                    logger.error("❌ User not found for token balance", user_id=user_id)
                    return {
                        'total_used': 0,
                        'input_tokens': 0,
                        'output_tokens': 0,
                        'limit': 500000,
                        'remaining': 500000,
                        'percentage_used': 0.0,
                        'bots_count': 0,
                        'admin_chat_id': None,
                        'last_usage_at': None
                    }
                
                # Получаем детальную статистику из UserBot
                detail_result = await session.execute(
                    select(
                        func.sum(UserBot.tokens_used_input).label('total_input'),
                        func.sum(UserBot.tokens_used_output).label('total_output'),
                        func.count(UserBot.id).label('bots_count'),
                        func.max(UserBot.openai_admin_chat_id).label('admin_chat_id'),
                        func.max(UserBot.updated_at).label('last_usage_at')
                    ).where(
                        UserBot.user_id == user_id,
                        UserBot.ai_assistant_type == 'openai',
                        UserBot.openai_agent_id.isnot(None)
                    )
                )
                
                details = detail_result.first()
                
                total_used = int(user.tokens_used_total or 0)
                input_tokens = int(details.total_input or 0)
                output_tokens = int(details.total_output or 0)
                limit = int(user.tokens_limit_total or 500000)
                remaining = max(0, limit - total_used)
                percentage_used = (total_used / limit * 100) if limit > 0 else 0
                bots_count = int(details.bots_count or 0)
                admin_chat_id = details.admin_chat_id
                last_usage_at = details.last_usage_at
                
                balance = {
                    'total_used': total_used,
                    'input_tokens': input_tokens,
                    'output_tokens': output_tokens,
                    'limit': limit,
                    'remaining': remaining,
                    'percentage_used': round(percentage_used, 2),
                    'bots_count': bots_count,
                    'admin_chat_id': admin_chat_id,
                    'last_usage_at': last_usage_at
                }
                
                logger.info("📊 User token balance retrieved", 
                           user_id=user_id,
                           **{k: v for k, v in balance.items() if k != 'admin_chat_id'})
                
                return balance
                
        except Exception as e:
            logger.error("💥 Failed to get user token balance", 
                        user_id=user_id,
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            
            return {
                'total_used': 0,
                'input_tokens': 0,
                'output_tokens': 0,
                'limit': 500000,
                'remaining': 500000,
                'percentage_used': 0.0,
                'bots_count': 0,
                'admin_chat_id': None,
                'last_usage_at': None
            }

    @staticmethod
    async def get_admin_chat_id_for_token_notification(user_id: int) -> Optional[int]:
        """Получить admin_chat_id для отправки уведомлений о токенах"""
        from database.models import UserBot
        
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    select(UserBot.openai_admin_chat_id)
                    .where(
                        UserBot.user_id == user_id,
                        UserBot.ai_assistant_type == 'openai',
                        UserBot.openai_admin_chat_id.isnot(None)
                    )
                    .limit(1)
                )
                
                admin_chat_id = result.scalar_one_or_none()
                
                logger.debug("🔍 Admin chat ID lookup", 
                            user_id=user_id,
                            admin_chat_id=admin_chat_id)
                
                return admin_chat_id
                
        except Exception as e:
            logger.error("💥 Failed to get admin chat ID", 
                        user_id=user_id,
                        error=str(e))
            return None

    @staticmethod
    async def should_send_token_notification(user_id: int) -> bool:
        """Проверить нужно ли отправлять уведомление о токенах"""
        from database.models import UserBot
        
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    select(UserBot.openai_token_notification_sent)
                    .where(
                        UserBot.user_id == user_id,
                        UserBot.ai_assistant_type == 'openai',
                        UserBot.openai_agent_id.isnot(None)
                    )
                    .limit(1)
                )
                
                notification_sent = result.scalar_one_or_none()
                should_send = not bool(notification_sent)
                
                logger.debug("🔔 Token notification check", 
                            user_id=user_id,
                            notification_sent=notification_sent,
                            should_send=should_send)
                
                return should_send
                
        except Exception as e:
            logger.error("💥 Failed to check token notification status", 
                        user_id=user_id,
                        error=str(e))
            return False

    @staticmethod
    async def set_token_notification_sent(user_id: int, sent: bool = True):
        """Установить флаг отправки уведомления о токенах"""
        from database.models import UserBot
        
        logger.info("🔔 Setting token notification flag", 
                   user_id=user_id, 
                   sent=sent)
        
        try:
            async with get_db_session() as session:
                # Обновляем флаг для всех OpenAI ботов пользователя
                result = await session.execute(
                    update(UserBot)
                    .where(
                        UserBot.user_id == user_id,
                        UserBot.ai_assistant_type == 'openai',
                        UserBot.openai_agent_id.isnot(None)
                    )
                    .values(
                        openai_token_notification_sent=sent,
                        updated_at=datetime.now()
                    )
                )
                
                await session.commit()
                
                affected_rows = result.rowcount
                
                logger.info("✅ Token notification flag updated", 
                           user_id=user_id,
                           sent=sent,
                           affected_bots=affected_rows)
                
                return affected_rows > 0
                
        except Exception as e:
            logger.error("💥 Failed to set token notification flag", 
                        user_id=user_id,
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            return False

    # ===== USER STATISTICS AND ANALYTICS =====
    
    @staticmethod
    async def get_user_stats(user_id: int) -> dict:
        """Get comprehensive user statistics"""
        from database.models import User, UserBot
        
        async with get_db_session() as session:
            # Get user info
            user_result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user = user_result.scalar_one_or_none()
            
            if not user:
                return {}
            
            # Get bot count
            bots_result = await session.execute(
                select(func.count(UserBot.id)).where(UserBot.user_id == user_id)
            )
            bots_count = bots_result.scalar() or 0
            
            # Get active bots count
            active_bots_result = await session.execute(
                select(func.count(UserBot.id))
                .where(UserBot.user_id == user_id, UserBot.status == 'active')
            )
            active_bots_count = active_bots_result.scalar() or 0
            
            # Get AI-enabled bots count
            ai_bots_result = await session.execute(
                select(func.count(UserBot.id))
                .where(UserBot.user_id == user_id, UserBot.ai_assistant_enabled == True)
            )
            ai_bots_count = ai_bots_result.scalar() or 0
            
            return {
                'user_id': user.id,
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'plan': user.plan,
                'subscription_active': user.subscription_active,
                'subscription_expires_at': user.subscription_expires_at,
                'created_at': user.created_at,
                'last_activity': user.last_activity,
                'bots_count': bots_count,
                'active_bots_count': active_bots_count,
                'ai_bots_count': ai_bots_count,
                'tokens_used': user.tokens_used_total or 0,
                'tokens_limit': user.tokens_limit_total or 500000,
                'tokens_remaining': (user.tokens_limit_total or 500000) - (user.tokens_used_total or 0),
                'tokens_initialized_at': user.tokens_initialized_at
            }
    
    # ===== USER SEARCH AND LISTING =====
    
    @staticmethod
    async def search_users(query: str, limit: int = 50):
        """Search users by username or name"""
        from database.models import User
        
        async with get_db_session() as session:
            result = await session.execute(
                select(User)
                .where(
                    User.username.ilike(f'%{query}%') |
                    User.first_name.ilike(f'%{query}%') |
                    User.last_name.ilike(f'%{query}%')
                )
                .order_by(User.last_activity.desc())
                .limit(limit)
            )
            return result.scalars().all()
    
    @staticmethod
    async def get_recent_users(limit: int = 20):
        """Get recently registered users"""
        from database.models import User
        
        async with get_db_session() as session:
            result = await session.execute(
                select(User)
                .order_by(User.created_at.desc())
                .limit(limit)
            )
            return result.scalars().all()
    
    @staticmethod
    async def get_users_by_plan(plan: str, limit: int = 100):
        """Get users by subscription plan"""
        from database.models import User
        
        async with get_db_session() as session:
            result = await session.execute(
                select(User)
                .where(User.plan == plan)
                .order_by(User.created_at.desc())
                .limit(limit)
            )
            return result.scalars().all()
    
    @staticmethod
    async def get_users_with_low_tokens(threshold_percentage: float = 0.1, limit: int = 50):
        """Get users with low token balance (below threshold percentage)"""
        from database.models import User
        
        async with get_db_session() as session:
            result = await session.execute(
                select(User)
                .where(
                    User.tokens_used_total.isnot(None),
                    User.tokens_limit_total.isnot(None),
                    User.tokens_used_total >= (User.tokens_limit_total * threshold_percentage)
                )
                .order_by((User.tokens_used_total / User.tokens_limit_total).desc())
                .limit(limit)
            )
            return result.scalars().all()

    # ===== REFERRAL PROGRAM METHODS =====

    @staticmethod
    async def ensure_user_has_referral_code(user_id: int) -> str:
        """Ensure user has referral code, create if not exists"""
        from database import db
        
        # Получаем пользователя
        user = await UserManager.get_user(user_id)
        if not user:
            logger.error("❌ User not found for referral code", user_id=user_id)
            return None
        
        # Если код уже есть, возвращаем его
        if user.referral_code:
            return user.referral_code
        
        # Генерируем новый код
        referral_code = await db.generate_referral_code()
        success = await db.set_user_referral_code(user_id, referral_code)
        
        if success:
            logger.info("✅ New referral code generated", 
                       user_id=user_id, referral_code=referral_code)
            return referral_code
        
        return None

    @staticmethod
    async def process_referral_link(new_user_id: int, referral_code: str) -> bool:
        """Process referral link for new user"""
        from database import db
        
        logger.info("🔗 Processing referral link", 
                   new_user_id=new_user_id, referral_code=referral_code)
        
        # Находим рефера по коду
        referrer = await db.get_user_by_referral_code(referral_code)
        if not referrer:
            logger.warning("❌ Referrer not found by code", referral_code=referral_code)
            return False
        
        # Проверяем что это не сам рефер
        if referrer.id == new_user_id:
            logger.warning("❌ User trying to refer themselves", user_id=new_user_id)
            return False
        
        # Устанавливаем связь
        success = await db.set_user_referrer(new_user_id, referrer.id)
        
        if success:
            logger.info("✅ Referral link processed successfully", 
                       new_user_id=new_user_id, 
                       referrer_id=referrer.id,
                       referrer_username=referrer.username)
        
        return success

    @staticmethod
    async def process_referral_payment(user_id: int, payment_amount: float, 
                                     transaction_type: str = "subscription") -> dict:
        """Process referral commission for payment"""
        from database import db
        from config import settings
        
        logger.info("💰 Processing referral payment", 
                   user_id=user_id, 
                   payment_amount=payment_amount,
                   transaction_type=transaction_type)
        
        try:
            # Получаем пользователя
            user = await UserManager.get_user(user_id)
            if not user or not user.referred_by:
                logger.info("❌ No referrer for user", user_id=user_id)
                return {'success': False, 'reason': 'no_referrer'}
            
            referrer_id = user.referred_by
            
            # Рассчитываем комиссию
            commission_rate = getattr(settings, 'referral_commission_rate', 15.0)  # 15%
            commission_amount = payment_amount * (commission_rate / 100)
            
            # Создаем транзакцию
            transaction_created = await db.create_referral_transaction(
                referrer_id=referrer_id,
                referred_id=user_id,
                payment_amount=payment_amount,
                commission_amount=commission_amount,
                transaction_type=transaction_type
            )
            
            if not transaction_created:
                return {'success': False, 'reason': 'transaction_failed'}
            
            # Начисляем комиссию рефереру
            earnings_added = await db.add_referral_earnings(referrer_id, commission_amount)
            
            if earnings_added:
                logger.info("✅ Referral commission processed successfully", 
                           referrer_id=referrer_id,
                           referred_user_id=user_id,
                           commission_amount=commission_amount,
                           transaction_type=transaction_type)
                
                return {
                    'success': True,
                    'referrer_id': referrer_id,
                    'commission_amount': commission_amount,
                    'commission_rate': commission_rate
                }
            else:
                return {'success': False, 'reason': 'earnings_failed'}
                
        except Exception as e:
            logger.error("💥 Failed to process referral payment", 
                        user_id=user_id,
                        payment_amount=payment_amount,
                        error=str(e))
            return {'success': False, 'reason': 'exception', 'error': str(e)}

    @staticmethod
    async def get_user_referral_info(user_id: int) -> dict:
        """Get complete referral information for user"""
        from database import db
        
        try:
            stats = await db.get_user_referral_stats(user_id)
            transactions = await db.get_referral_transactions_for_payment(user_id, limit=5)
            
            return {
                'stats': stats,
                'recent_transactions': transactions
            }
            
        except Exception as e:
            logger.error("💥 Failed to get referral info", user_id=user_id, error=str(e))
            return {'error': str(e)}
