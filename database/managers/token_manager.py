"""
Token Manager - handles all OpenAI token management operations.

Responsibilities:
- Token usage tracking and synchronization between User and UserBot
- Token balance management and limits
- Token notifications and alerts
- Token analytics and reporting
- Token initialization for new OpenAI agents
"""

from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, List, Any
from sqlalchemy import select, update, func, desc
import structlog

from ..connection import get_db_session

logger = structlog.get_logger()


class TokenManager:
    """Manager for OpenAI token related database operations"""
    
    # ===== TOKEN USAGE TRACKING =====
    
    @staticmethod
    async def save_token_usage(bot_id: str, input_tokens: int, output_tokens: int, admin_chat_id: int = None, user_id: int = None):
        """Сохранение использования токенов OpenAI с синхронизацией User и UserBot"""
        from database.models import UserBot, User
        
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
                
                # Получаем текущие токены из UserBot
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
                
                # 2. Синхронизируем User.tokens_used_total
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
                
                # Записываем историю пополнения
                await TokenManager._log_token_transaction(
                    user_id=user_id,
                    transaction_type='purchase',
                    amount=additional_tokens,
                    description=f'Token purchase: +{additional_tokens} tokens'
                )
                
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
    async def check_token_limit(user_id: int) -> Tuple[bool, int, int]:
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
    async def get_user_token_balance(user_id: int) -> Dict:
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

    # ===== TOKEN INITIALIZATION =====

    @staticmethod
    async def initialize_token_balance(user_id: int, admin_chat_id: int, bot_id: str = None):
        """
        Инициализировать баланс токенов для пользователя при создании первого OpenAI агента
        С синхронизацией User и UserBot
        """
        from database.models import UserBot, User
        
        logger.info("🚀 Initializing token balance with User sync", 
                   user_id=user_id,
                   admin_chat_id=admin_chat_id,
                   bot_id=bot_id)
        
        try:
            async with get_db_session() as session:
                # Проверяем существуют ли уже OpenAI боты у пользователя
                existing_bots_result = await session.execute(
                    select(func.count(UserBot.id))
                    .where(
                        UserBot.user_id == user_id,
                        UserBot.ai_assistant_type == 'openai',
                        UserBot.openai_agent_id.isnot(None)
                    )
                )
                
                existing_count = existing_bots_result.scalar() or 0
                
                logger.info("📊 Existing OpenAI bots check", 
                           user_id=user_id,
                           existing_count=existing_count)
                
                # Если это первый OpenAI бот - инициализируем баланс
                if existing_count == 0:
                    logger.info("🆕 First OpenAI bot - initializing token balance")
                    
                    # 1. Инициализируем User
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
                    
                    # 2. Инициализируем UserBot(s)
                    if bot_id:
                        # Инициализируем для конкретного бота
                        await session.execute(
                            update(UserBot)
                            .where(UserBot.bot_id == bot_id)
                            .values(
                                tokens_limit_total=500000,
                                tokens_used_total=0,
                                tokens_used_input=0,
                                tokens_used_output=0,
                                openai_admin_chat_id=admin_chat_id,
                                openai_token_notification_sent=False,
                                updated_at=datetime.now()
                            )
                        )
                    else:
                        # Инициализируем для всех OpenAI ботов пользователя
                        await session.execute(
                            update(UserBot)
                            .where(
                                UserBot.user_id == user_id,
                                UserBot.ai_assistant_type == 'openai'
                            )
                            .values(
                                tokens_limit_total=500000,
                                tokens_used_total=0,
                                tokens_used_input=0,
                                tokens_used_output=0,
                                openai_admin_chat_id=admin_chat_id,
                                openai_token_notification_sent=False,
                                updated_at=datetime.now()
                            )
                        )
                    
                    await session.commit()
                    
                    # Записываем историю инициализации
                    await TokenManager._log_token_transaction(
                        user_id=user_id,
                        transaction_type='initialization',
                        amount=500000,
                        description='Initial token balance for new OpenAI agent'
                    )
                    
                    logger.info("✅ Token balance initialized successfully with User sync", 
                               user_id=user_id,
                               admin_chat_id=admin_chat_id,
                               tokens_limit=500000)
                    
                    return True
                else:
                    # Если уже есть OpenAI боты - просто обновляем admin_chat_id для нового бота
                    if bot_id:
                        await session.execute(
                            update(UserBot)
                            .where(UserBot.bot_id == bot_id)
                            .values(
                                openai_admin_chat_id=admin_chat_id,
                                updated_at=datetime.now()
                            )
                        )
                        await session.commit()
                    
                    logger.info("ℹ️ Token balance already exists, updated admin_chat_id", 
                               user_id=user_id,
                               existing_count=existing_count)
                    
                    return True
                    
        except Exception as e:
            logger.error("💥 Failed to initialize token balance with User sync", 
                        user_id=user_id,
                        admin_chat_id=admin_chat_id,
                        bot_id=bot_id,
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            return False

    # ===== TOKEN NOTIFICATIONS =====

    @staticmethod
    async def get_admin_chat_id_for_token_notification(user_id: int) -> Optional[int]:
        """Получить admin_chat_id для отправки уведомлений о токенах"""
        from database.models import UserBot, User
        
        try:
            async with get_db_session() as session:
                # Попробуем сначала получить из UserBot
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
                
                # Если не найдено в UserBot, попробуем User
                if not admin_chat_id:
                    user_result = await session.execute(
                        select(User.tokens_admin_chat_id)
                        .where(User.id == user_id)
                    )
                    admin_chat_id = user_result.scalar_one_or_none()
                
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

    # ===== TOKEN ANALYTICS =====

    @staticmethod
    async def get_token_usage_analytics(user_id: int, days: int = 30) -> Dict[str, Any]:
        """Получить аналитику использования токенов пользователя"""
        from database.models import UserBot
        
        start_date = datetime.now() - timedelta(days=days)
        
        try:
            async with get_db_session() as session:
                # Статистика по ботам
                bots_result = await session.execute(
                    select(
                        UserBot.bot_id,
                        UserBot.bot_name,
                        UserBot.tokens_used_total,
                        UserBot.tokens_used_input,
                        UserBot.tokens_used_output,
                        UserBot.updated_at
                    ).where(
                        UserBot.user_id == user_id,
                        UserBot.ai_assistant_type == 'openai',
                        UserBot.tokens_used_total > 0
                    )
                    .order_by(desc(UserBot.tokens_used_total))
                )
                
                bots_data = bots_result.fetchall()
                
                # Общая статистика
                total_stats = {
                    'total_tokens': sum(bot.tokens_used_total or 0 for bot in bots_data),
                    'input_tokens': sum(bot.tokens_used_input or 0 for bot in bots_data),
                    'output_tokens': sum(bot.tokens_used_output or 0 for bot in bots_data),
                    'active_bots': len(bots_data)
                }
                
                # Баланс пользователя
                balance = await TokenManager.get_user_token_balance(user_id)
                
                return {
                    'user_id': user_id,
                    'period_days': days,
                    'balance': balance,
                    'usage_stats': total_stats,
                    'bots_breakdown': [
                        {
                            'bot_id': bot.bot_id,
                            'bot_name': bot.bot_name,
                            'total_tokens': int(bot.tokens_used_total or 0),
                            'input_tokens': int(bot.tokens_used_input or 0),
                            'output_tokens': int(bot.tokens_used_output or 0),
                            'last_usage': bot.updated_at,
                            'percentage_of_total': round(
                                ((bot.tokens_used_total or 0) / max(total_stats['total_tokens'], 1)) * 100,
                                2
                            )
                        }
                        for bot in bots_data
                    ],
                    'cost_estimation': {
                        'input_cost_usd': round((total_stats['input_tokens'] / 1000) * 0.005, 4),  # GPT-4o pricing
                        'output_cost_usd': round((total_stats['output_tokens'] / 1000) * 0.015, 4),
                        'total_cost_usd': round(
                            ((total_stats['input_tokens'] / 1000) * 0.005) + 
                            ((total_stats['output_tokens'] / 1000) * 0.015),
                            4
                        )
                    }
                }
                
        except Exception as e:
            logger.error("💥 Failed to get token usage analytics", 
                        user_id=user_id,
                        error=str(e))
            return {}

    @staticmethod
    async def get_platform_token_stats(days: int = 30) -> Dict[str, Any]:
        """Получить статистику токенов по всей платформе"""
        from database.models import User, UserBot
        
        start_date = datetime.now() - timedelta(days=days)
        
        try:
            async with get_db_session() as session:
                # Общая статистика по пользователям
                users_stats_result = await session.execute(
                    select(
                        func.count(User.id).label('total_users'),
                        func.sum(User.tokens_used_total).label('total_tokens_used'),
                        func.sum(User.tokens_limit_total).label('total_tokens_limit'),
                        func.avg(User.tokens_used_total).label('avg_tokens_per_user')
                    ).where(User.tokens_limit_total.isnot(None))
                )
                users_stats = users_stats_result.first()
                
                # Статистика по ботам
                bots_stats_result = await session.execute(
                    select(
                        func.count(UserBot.id).label('total_openai_bots'),
                        func.sum(UserBot.tokens_used_input).label('total_input_tokens'),
                        func.sum(UserBot.tokens_used_output).label('total_output_tokens'),
                        func.avg(UserBot.tokens_used_total).label('avg_tokens_per_bot')
                    ).where(
                        UserBot.ai_assistant_type == 'openai',
                        UserBot.tokens_used_total.isnot(None)
                    )
                )
                bots_stats = bots_stats_result.first()
                
                # Топ пользователи по использованию
                top_users_result = await session.execute(
                    select(
                        User.id,
                        User.username,
                        User.tokens_used_total,
                        User.tokens_limit_total
                    ).where(User.tokens_used_total > 0)
                    .order_by(desc(User.tokens_used_total))
                    .limit(10)
                )
                top_users = top_users_result.fetchall()
                
                total_used = int(users_stats.total_tokens_used or 0)
                total_limit = int(users_stats.total_tokens_limit or 0)
                
                return {
                    'period_days': days,
                    'platform_stats': {
                        'total_users_with_tokens': int(users_stats.total_users or 0),
                        'total_openai_bots': int(bots_stats.total_openai_bots or 0),
                        'total_tokens_used': total_used,
                        'total_tokens_limit': total_limit,
                        'total_tokens_remaining': max(0, total_limit - total_used),
                        'platform_usage_percentage': round((total_used / max(total_limit, 1)) * 100, 2),
                        'avg_tokens_per_user': round(float(users_stats.avg_tokens_per_user or 0), 2),
                        'avg_tokens_per_bot': round(float(bots_stats.avg_tokens_per_bot or 0), 2)
                    },
                    'token_breakdown': {
                        'total_input_tokens': int(bots_stats.total_input_tokens or 0),
                        'total_output_tokens': int(bots_stats.total_output_tokens or 0),
                        'input_percentage': round(
                            ((bots_stats.total_input_tokens or 0) / max(total_used, 1)) * 100,
                            2
                        ),
                        'output_percentage': round(
                            ((bots_stats.total_output_tokens or 0) / max(total_used, 1)) * 100,
                            2
                        )
                    },
                    'top_users': [
                        {
                            'user_id': user.id,
                            'username': user.username,
                            'tokens_used': int(user.tokens_used_total),
                            'tokens_limit': int(user.tokens_limit_total),
                            'usage_percentage': round(
                                (user.tokens_used_total / max(user.tokens_limit_total, 1)) * 100,
                                2
                            )
                        }
                        for user in top_users
                    ],
                    'cost_estimation': {
                        'total_input_cost_usd': round(((bots_stats.total_input_tokens or 0) / 1000) * 0.005, 2),
                        'total_output_cost_usd': round(((bots_stats.total_output_tokens or 0) / 1000) * 0.015, 2),
                        'total_platform_cost_usd': round(
                            (((bots_stats.total_input_tokens or 0) / 1000) * 0.005) + 
                            (((bots_stats.total_output_tokens or 0) / 1000) * 0.015),
                            2
                        )
                    }
                }
                
        except Exception as e:
            logger.error("💥 Failed to get platform token stats", error=str(e))
            return {}

    @staticmethod
    async def get_users_near_limit(threshold_percentage: float = 0.8) -> List[Dict]:
        """Получить пользователей близких к лимиту токенов"""
        from database.models import User
        
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    select(
                        User.id,
                        User.username,
                        User.first_name,
                        User.tokens_used_total,
                        User.tokens_limit_total,
                        User.tokens_admin_chat_id
                    ).where(
                        User.tokens_used_total.isnot(None),
                        User.tokens_limit_total.isnot(None),
                        User.tokens_used_total >= (User.tokens_limit_total * threshold_percentage)
                    )
                    .order_by(desc(User.tokens_used_total / User.tokens_limit_total))
                )
                
                users = result.fetchall()
                
                return [
                    {
                        'user_id': user.id,
                        'username': user.username,
                        'first_name': user.first_name,
                        'tokens_used': int(user.tokens_used_total),
                        'tokens_limit': int(user.tokens_limit_total),
                        'usage_percentage': round(
                            (user.tokens_used_total / user.tokens_limit_total) * 100,
                            2
                        ),
                        'tokens_remaining': user.tokens_limit_total - user.tokens_used_total,
                        'admin_chat_id': user.tokens_admin_chat_id
                    }
                    for user in users
                ]
                
        except Exception as e:
            logger.error("💥 Failed to get users near limit", error=str(e))
            return []

    # ===== TOKEN TRANSACTIONS HISTORY =====

    @staticmethod
    async def _log_token_transaction(
        user_id: int,
        transaction_type: str,
        amount: int,
        description: str = None,
        metadata: Dict = None
    ):
        """Внутренний метод для логирования транзакций токенов"""
        # Note: This would require a TokenTransaction model to be implemented
        # For now, we'll just log it
        logger.info("📝 Token transaction logged",
                   user_id=user_id,
                   transaction_type=transaction_type,
                   amount=amount,
                   description=description,
                   metadata=metadata)

    @staticmethod
    async def set_user_token_limit(user_id: int, new_limit: int) -> bool:
        """Установить новый лимит токенов для пользователя"""
        from database.models import User
        
        try:
            async with get_db_session() as session:
                # Получаем текущий лимит
                current_result = await session.execute(
                    select(User.tokens_limit_total).where(User.id == user_id)
                )
                current_limit = current_result.scalar_one_or_none()
                
                if current_limit is None:
                    logger.error("❌ User not found for token limit update", user_id=user_id)
                    return False
                
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
                
                # Логируем изменение
                if new_limit > current_limit:
                    await TokenManager._log_token_transaction(
                        user_id=user_id,
                        transaction_type='limit_increase',
                        amount=new_limit - current_limit,
                        description=f'Token limit increased from {current_limit} to {new_limit}'
                    )
                elif new_limit < current_limit:
                    await TokenManager._log_token_transaction(
                        user_id=user_id,
                        transaction_type='limit_decrease',
                        amount=current_limit - new_limit,
                        description=f'Token limit decreased from {current_limit} to {new_limit}'
                    )
                
                logger.info("✅ User token limit updated", 
                           user_id=user_id,
                           old_limit=current_limit,
                           new_limit=new_limit)
                
                return True
                
        except Exception as e:
            logger.error("💥 Failed to set user token limit", 
                        user_id=user_id,
                        error=str(e))
            return False

    # ===== TOKEN MAINTENANCE =====

    @staticmethod
    async def reset_token_notifications(user_id: int = None) -> int:
        """Сбросить флаги уведомлений о токенах"""
        from database.models import UserBot
        
        try:
            async with get_db_session() as session:
                query = update(UserBot).values(
                    openai_token_notification_sent=False,
                    updated_at=datetime.now()
                ).where(
                    UserBot.ai_assistant_type == 'openai',
                    UserBot.openai_agent_id.isnot(None)
                )
                
                if user_id:
                    query = query.where(UserBot.user_id == user_id)
                
                result = await session.execute(query)
                await session.commit()
                
                affected_count = result.rowcount
                
                logger.info("✅ Token notifications reset", 
                           user_id=user_id,
                           affected_bots=affected_count)
                
                return affected_count
                
        except Exception as e:
            logger.error("💥 Failed to reset token notifications", 
                        user_id=user_id,
                        error=str(e))
            return 0

    @staticmethod
    async def get_token_summary() -> Dict[str, Any]:
        """Получить общую сводку по токенам"""
        try:
            # Получаем статистику платформы
            platform_stats = await TokenManager.get_platform_token_stats(days=30)
            
            # Получаем пользователей близких к лимиту
            users_near_limit = await TokenManager.get_users_near_limit(threshold_percentage=0.9)
            
            return {
                'platform_overview': platform_stats.get('platform_stats', {}),
                'cost_overview': platform_stats.get('cost_estimation', {}),
                'alerts': {
                    'users_near_limit_90': len(users_near_limit),
                    'users_near_limit_details': users_near_limit[:5]  # Top 5
                },
                'health_metrics': {
                    'avg_usage_percentage': platform_stats.get('platform_stats', {}).get('platform_usage_percentage', 0),
                    'total_active_bots': platform_stats.get('platform_stats', {}).get('total_openai_bots', 0),
                    'cost_per_user': round(
                        platform_stats.get('cost_estimation', {}).get('total_platform_cost_usd', 0) / 
                        max(platform_stats.get('platform_stats', {}).get('total_users_with_tokens', 1), 1),
                        4
                    )
                }
            }
            
        except Exception as e:
            logger.error("💥 Failed to get token summary", error=str(e))
            return {}
