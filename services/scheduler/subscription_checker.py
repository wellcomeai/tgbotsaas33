"""
Subscription Checker Service
Планировщик для проверки истекающих подписок
"""

import asyncio
import structlog
from datetime import datetime, timedelta
from typing import List, Optional

from database import db
from services.notifications.payment_notifier import payment_notifier
from services.payments.subscription_manager import subscription_manager

logger = structlog.get_logger()


class SubscriptionChecker:
    """Сервис проверки истекающих подписок"""
    
    def __init__(self):
        self.running = False
        self.check_interval = 3600  # Проверяем каждый час
        self.task: Optional[asyncio.Task] = None
        
        # Настройки уведомлений (за сколько дней предупреждать)
        self.warning_days = [7, 3, 1]  # За 7, 3 и 1 день
        
        logger.info("SubscriptionChecker initialized",
                   check_interval=self.check_interval,
                   warning_days=self.warning_days)
    
    async def start(self):
        """Запуск планировщика"""
        if self.running:
            logger.warning("SubscriptionChecker already running")
            return
        
        self.running = True
        self.task = asyncio.create_task(self._run_checker())
        
        logger.info("✅ SubscriptionChecker started")
    
    async def stop(self):
        """Остановка планировщика"""
        self.running = False
        
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        
        logger.info("🛑 SubscriptionChecker stopped")
    
    async def _run_checker(self):
        """Основной цикл проверки подписок"""
        logger.info("🔄 Starting subscription checker loop")
        
        while self.running:
            try:
                await self._check_expiring_subscriptions()
                await self._deactivate_expired_subscriptions()
                
                # Ждем до следующей проверки
                await asyncio.sleep(self.check_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in subscription checker loop",
                           error=str(e),
                           exc_info=True)
                
                # При ошибке ждем меньше времени перед повтором
                await asyncio.sleep(300)  # 5 минут
    
    async def _check_expiring_subscriptions(self):
        """Проверка истекающих подписок и отправка предупреждений"""
        try:
            current_time = datetime.now()
            
            for days_ahead in self.warning_days:
                # Ищем подписки, истекающие через N дней
                target_date = current_time + timedelta(days=days_ahead)
                
                expiring_subscriptions = await db.get_users_with_expiring_subscriptions(days_ahead)
                
                for subscription in expiring_subscriptions:
                    user_id = subscription.get('user_id')
                    end_date = subscription.get('end_date')
                    
                    if not user_id or not end_date:
                        continue
                    
                    # Вычисляем точное количество дней до истечения
                    days_left = (end_date - current_time).days
                    
                    # Проверяем, не отправляли ли уже уведомление для этого периода
                    if await self._should_send_warning(subscription['id'], days_left):
                        await payment_notifier.send_subscription_expiry_warning(
                            user_id=user_id,
                            subscription=subscription,
                            days_left=days_left
                        )
                        
                        # Отмечаем что уведомление отправлено
                        await self._mark_warning_sent(subscription['id'], days_left)
                        
                        logger.info("Expiry warning sent",
                                   subscription_id=subscription['id'],
                                   user_id=user_id,
                                   days_left=days_left)
                        
                        # Небольшая задержка между уведомлениями
                        await asyncio.sleep(1)
                
                logger.debug("Checked expiring subscriptions",
                           days_ahead=days_ahead,
                           found_count=len(expiring_subscriptions))
                
        except Exception as e:
            logger.error("Failed to check expiring subscriptions",
                        error=str(e))
    
    async def _deactivate_expired_subscriptions(self):
        """Деактивация истекших подписок"""
        try:
            # Получаем все истекшие подписки
            query = """
                SELECT * FROM subscriptions 
                WHERE status = 'active' 
                AND end_date <= NOW()
            """
            
            expired_subscriptions = await db.fetch_all(query)
            
            for subscription_row in expired_subscriptions:
                subscription = dict(subscription_row)
                subscription_id = subscription['id']
                user_id = subscription['user_id']
                
                try:
                    # Деактивируем подписку
                    await subscription_manager.cancel_subscription(
                        user_id=user_id,
                        reason="Subscription expired"
                    )
                    
                    # Отправляем уведомление пользователю
                    await payment_notifier.send_subscription_expired_notification(
                        user_id=user_id,
                        subscription=subscription
                    )
                    
                    logger.info("Subscription expired and deactivated",
                               subscription_id=subscription_id,
                               user_id=user_id,
                               end_date=subscription.get('end_date'))
                    
                    # Небольшая задержка между обработкой
                    await asyncio.sleep(0.5)
                    
                except Exception as e:
                    logger.error("Failed to deactivate expired subscription",
                                error=str(e),
                                subscription_id=subscription_id,
                                user_id=user_id)
            
            if expired_subscriptions:
                logger.info("Processed expired subscriptions",
                           count=len(expired_subscriptions))
                
        except Exception as e:
            logger.error("Failed to deactivate expired subscriptions",
                        error=str(e))
    
    async def _should_send_warning(self, subscription_id: int, days_left: int) -> bool:
        """Проверка, нужно ли отправлять предупреждение"""
        try:
            # Проверяем в метаданных подписки, отправляли ли уже это предупреждение
            query = """
                SELECT extra_data FROM subscriptions 
                WHERE id = $1
            """
            
            row = await db.fetch_one(query, subscription_id)
            if not row:
                return True
            
            extra_data = row[0] or {}
            warnings_sent = extra_data.get('warnings_sent', [])
            
            # Если уже отправляли предупреждение для этого количества дней - не отправляем
            return days_left not in warnings_sent
            
        except Exception as e:
            logger.error("Error checking if warning should be sent",
                        error=str(e),
                        subscription_id=subscription_id)
            return True  # В случае ошибки лучше отправить лишнее уведомление
    
    async def _mark_warning_sent(self, subscription_id: int, days_left: int):
        """Отметка что предупреждение отправлено"""
        try:
            # Обновляем метаданные подписки
            query = """
                UPDATE subscriptions 
                SET extra_data = COALESCE(extra_data, '{}'::jsonb) || 
                              jsonb_build_object(
                                  'warnings_sent', 
                                  COALESCE(extra_data->'warnings_sent', '[]'::jsonb) || 
                                  to_jsonb($2::int)
                              )
                WHERE id = $1
            """
            
            await db.execute(query, subscription_id, days_left)
            
            logger.debug("Warning marked as sent",
                        subscription_id=subscription_id,
                        days_left=days_left)
                        
        except Exception as e:
            logger.error("Failed to mark warning as sent",
                        error=str(e),
                        subscription_id=subscription_id)
    
    async def check_subscription_now(self, user_id: int) -> Optional[dict]:
        """Немедленная проверка подписки конкретного пользователя"""
        try:
            subscription = await subscription_manager.get_active_subscription(user_id)
            
            if subscription:
                end_date = subscription.get('end_date')
                if end_date:
                    days_left = (end_date - datetime.now()).days
                    
                    return {
                        'subscription': subscription,
                        'days_left': days_left,
                        'is_active': days_left > 0,
                        'is_expiring_soon': days_left <= 7
                    }
            
            return None
            
        except Exception as e:
            logger.error("Failed to check subscription now",
                        error=str(e),
                        user_id=user_id)
            return None
    
    async def get_stats(self) -> dict:
        """Получение статистики работы планировщика"""
        try:
            # Общая статистика подписок
            stats = await subscription_manager.get_subscription_stats()
            
            # Добавляем информацию о планировщике
            stats.update({
                'checker_running': self.running,
                'check_interval_hours': self.check_interval / 3600,
                'warning_days': self.warning_days,
                'last_check': datetime.now().isoformat() if self.running else None
            })
            
            return stats
            
        except Exception as e:
            logger.error("Failed to get subscription checker stats", error=str(e))
            return {'error': str(e)}


# Создаем глобальный экземпляр планировщика
subscription_checker = SubscriptionChecker()
