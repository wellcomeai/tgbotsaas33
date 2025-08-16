"""
Subscription Manager
Управление подписками пользователей Bot Factory
"""

import structlog
from datetime import datetime, timedelta
from typing import Optional, Dict, List

from database import db
from config import settings

logger = structlog.get_logger()


class SubscriptionManager:
    """Менеджер подписок пользователей"""
    
    async def process_successful_payment(self, payment_data: dict) -> dict:
        """
        ✅ Обработка успешного платежа от Robokassa
        
        Args:
            payment_data: Обработанные данные платежа
            
        Returns:
            dict: Результат обработки
        """
        try:
            user_id = payment_data['user_id']
            plan_id = payment_data['plan_id']
            order_id = payment_data['order_id']
            amount = payment_data['amount']
            
            logger.info("🎯 Processing successful payment",
                       user_id=user_id,
                       plan_id=plan_id,
                       order_id=order_id,
                       amount=amount)
            
            # ✅ Проверяем что заказ еще не обработан (защита от дублирования)
            existing = await db.get_subscription_by_order_id(order_id)
            if existing:
                logger.warning("⚠️ Payment already processed", 
                              order_id=order_id,
                              existing_id=existing.get('id'),
                              existing_status=existing.get('status'))
                
                return {
                    'success': True,
                    'already_processed': True,
                    'subscription': existing,
                    'payment_data': payment_data,
                    'message': 'Payment was already processed'
                }
            
            # ✅ Проверяем что план существует
            plan = settings.subscription_plans.get(plan_id)
            if not plan:
                logger.error("❌ Unknown plan_id in payment", 
                            plan_id=plan_id,
                            order_id=order_id,
                            available_plans=list(settings.subscription_plans.keys()))
                
                return {
                    'success': False,
                    'error': f'Unknown plan_id: {plan_id}',
                    'payment_data': payment_data
                }
            
            # ✅ Проверяем сумму платежа
            expected_amount = plan['price']
            if abs(amount - expected_amount) > 0.01:  # Допускаем погрешность в 1 копейку
                logger.error("❌ Payment amount mismatch",
                            order_id=order_id,
                            received_amount=amount,
                            expected_amount=expected_amount,
                            plan_id=plan_id)
                
                return {
                    'success': False,
                    'error': f'Amount mismatch: received {amount}, expected {expected_amount}',
                    'payment_data': payment_data
                }
            
            # ✅ Создаем подписку
            subscription = await self.create_subscription(payment_data)
            
            if subscription:
                logger.info("✅ Subscription created successfully",
                           subscription_id=subscription.get('id'),
                           user_id=user_id,
                           plan_id=plan_id,
                           plan_title=plan.get('title'),
                           end_date=subscription.get('end_date'))
                
                # ✅ Логируем успешную операцию для мониторинга
                await self._log_payment_success(payment_data, subscription)
                
                return {
                    'success': True,
                    'subscription': subscription,
                    'payment_data': payment_data,
                    'message': 'Subscription created successfully'
                }
            else:
                logger.error("❌ Failed to create subscription",
                            order_id=order_id,
                            user_id=user_id,
                            plan_id=plan_id)
                
                return {
                    'success': False,
                    'error': 'Failed to create subscription in database',
                    'payment_data': payment_data
                }
            
        except Exception as e:
            logger.error("💥 Error processing successful payment",
                        error=str(e),
                        error_type=type(e).__name__,
                        payment_data=payment_data,
                        exc_info=True)
            
            return {
                'success': False,
                'error': f'Internal error: {str(e)}',
                'payment_data': payment_data
            }
    
    async def _log_payment_success(self, payment_data: dict, subscription: dict):
        """
        ✅ Логирование успешного платежа для мониторинга и аналитики
        """
        try:
            log_data = {
                'event': 'payment_success',
                'order_id': payment_data.get('order_id'),
                'user_id': payment_data.get('user_id'),
                'plan_id': payment_data.get('plan_id'),
                'amount': payment_data.get('amount'),
                'currency': 'RUB',
                'subscription_id': subscription.get('id'),
                'payment_method': 'robokassa_web',
                'timestamp': datetime.now().isoformat()
            }
            
            logger.info("💰 Payment success logged", **log_data)
            
            # Здесь можно добавить отправку в аналитику, метрики и т.д.
            
        except Exception as e:
            logger.error("❌ Failed to log payment success", error=str(e))
    
    async def create_subscription(self, payment_data: dict) -> Optional[dict]:
        """
        Создание новой подписки после успешной оплаты
        
        Args:
            payment_data: Данные об оплате от Robokassa
            
        Returns:
            dict: Данные созданной подписки или None если ошибка
        """
        try:
            user_id = payment_data['user_id']
            plan_id = payment_data['plan_id']
            order_id = payment_data['order_id']
            amount = payment_data['amount']
            
            # Получаем план
            plan = settings.subscription_plans.get(plan_id)
            if not plan:
                logger.error("Unknown plan_id", plan_id=plan_id, order_id=order_id)
                return None
            
            # Проверяем что такого заказа еще нет
            existing = await db.get_subscription_by_order_id(order_id)
            if existing:
                logger.warning("Subscription already exists", 
                              order_id=order_id,
                              existing_id=existing.get('id'))
                return existing
            
            # Вычисляем даты
            start_date = datetime.now()
            end_date = start_date + timedelta(days=plan['duration_days'])
            
            # Создаем подписку
            subscription_data = {
                'user_id': user_id,
                'plan_id': plan_id,
                'plan_name': plan['title'],
                'amount': amount,
                'currency': 'RUB',
                'order_id': order_id,
                'payment_method': 'robokassa_web',
                'start_date': start_date,
                'end_date': end_date,
                'status': 'active',
                'extra_data': {
                    'plan_details': plan,
                    'payment_data': payment_data
                }
            }
            
            # Сохраняем в БД
            created_subscription = await db.create_subscription(subscription_data)
            
            if created_subscription:
                # Обновляем лимиты пользователя
                await self._update_user_limits(user_id, plan_id, end_date)
                
                logger.info("Subscription created successfully",
                           subscription_id=created_subscription.get('id'),
                           user_id=user_id,
                           plan_id=plan_id,
                           order_id=order_id,
                           end_date=end_date.isoformat())
                
                return created_subscription
            
        except Exception as e:
            logger.error("Failed to create subscription",
                        error=str(e),
                        user_id=payment_data.get('user_id'),
                        order_id=payment_data.get('order_id'))
            
        return None
    
    async def get_active_subscription(self, user_id: int) -> Optional[dict]:
        """
        Получение активной подписки пользователя
        
        Args:
            user_id: ID пользователя
            
        Returns:
            dict: Данные активной подписки или None
        """
        try:
            subscription = await db.get_active_subscription(user_id)
            
            if subscription:
                # Проверяем что подписка действительно активна
                end_date = subscription.get('end_date')
                if end_date and end_date > datetime.now():
                    return subscription
                else:
                    # Подписка истекла, деактивируем
                    await self._deactivate_subscription(subscription['id'])
                    await self._reset_user_limits(user_id)
                    
                    logger.info("Subscription expired and deactivated",
                               subscription_id=subscription['id'],
                               user_id=user_id,
                               end_date=end_date.isoformat() if end_date else None)
            
            return None
            
        except Exception as e:
            logger.error("Failed to get active subscription",
                        error=str(e),
                        user_id=user_id)
            return None
    
    async def check_user_limits(self, user_id: int) -> dict:
        """
        Проверка лимитов пользователя
        
        Args:
            user_id: ID пользователя
            
        Returns:
            dict: Информация о лимитах пользователя
        """
        try:
            # Получаем активную подписку
            subscription = await self.get_active_subscription(user_id)
            
            if subscription:
                # У пользователя есть Pro подписка
                return {
                    'is_pro': True,
                    'max_bots': settings.pro_max_bots,
                    'max_subscribers': settings.pro_max_subscribers,
                    'max_funnel_messages': settings.pro_max_funnel_messages,
                    'subscription_end': subscription.get('end_date'),
                    'plan_name': subscription.get('plan_name'),
                    'unlimited': True
                }
            else:
                # Бесплатный план
                return {
                    'is_pro': False,
                    'max_bots': settings.max_bots_per_user,
                    'max_subscribers': settings.free_plan_subscribers_limit,
                    'max_funnel_messages': 7,  # Ограничение для бесплатного плана
                    'subscription_end': None,
                    'plan_name': 'Бесплатный',
                    'unlimited': False
                }
                
        except Exception as e:
            logger.error("Failed to check user limits",
                        error=str(e), 
                        user_id=user_id)
            
            # Возвращаем базовые лимиты в случае ошибки
            return {
                'is_pro': False,
                'max_bots': settings.max_bots_per_user,
                'max_subscribers': settings.free_plan_subscribers_limit,
                'max_funnel_messages': 7,
                'subscription_end': None,
                'plan_name': 'Бесплатный (ошибка проверки)',
                'unlimited': False
            }
    
    async def get_subscription_stats(self) -> dict:
        """Получение статистики по подпискам"""
        try:
            stats = await db.get_subscription_stats()
            
            return {
                'total_subscriptions': stats.get('total', 0),
                'active_subscriptions': stats.get('active', 0),
                'expired_subscriptions': stats.get('expired', 0),
                'total_revenue': stats.get('revenue', 0),
                'popular_plans': stats.get('popular_plans', [])
            }
            
        except Exception as e:
            logger.error("Failed to get subscription stats", error=str(e))
            return {}
    
    async def extend_subscription(self, user_id: int, days: int) -> bool:
        """
        Продление существующей подписки (для администрации)
        
        Args:
            user_id: ID пользователя
            days: Количество дней для продления
            
        Returns:
            bool: True если продлено успешно
        """
        try:
            subscription = await self.get_active_subscription(user_id)
            
            if subscription:
                # Продлеваем существующую подписку
                new_end_date = subscription['end_date'] + timedelta(days=days)
                
                await db.extend_subscription(subscription['id'], new_end_date)
                await self._update_user_limits(user_id, subscription['plan_id'], new_end_date)
                
                logger.info("Subscription extended",
                           subscription_id=subscription['id'],
                           user_id=user_id,
                           days=days,
                           new_end_date=new_end_date.isoformat())
                
                return True
            
            return False
            
        except Exception as e:
            logger.error("Failed to extend subscription",
                        error=str(e),
                        user_id=user_id,
                        days=days)
            return False
    
    async def cancel_subscription(self, user_id: int, reason: str = None) -> bool:
        """
        Отмена подписки пользователя
        
        Args:
            user_id: ID пользователя
            reason: Причина отмены
            
        Returns:
            bool: True если отменено успешно
        """
        try:
            subscription = await self.get_active_subscription(user_id)
            
            if subscription:
                await self._deactivate_subscription(subscription['id'], reason)
                await self._reset_user_limits(user_id)
                
                logger.info("Subscription cancelled",
                           subscription_id=subscription['id'],
                           user_id=user_id,
                           reason=reason)
                
                return True
            
            return False
            
        except Exception as e:
            logger.error("Failed to cancel subscription",
                        error=str(e),
                        user_id=user_id)
            return False
    
    async def get_user_subscription_history(self, user_id: int) -> List[dict]:
        """
        Получение истории подписок пользователя
        
        Args:
            user_id: ID пользователя
            
        Returns:
            List[dict]: Список всех подписок пользователя
        """
        try:
            history = await db.get_user_subscription_history(user_id)
            
            logger.info("Retrieved subscription history",
                       user_id=user_id,
                       subscriptions_count=len(history))
            
            return history
            
        except Exception as e:
            logger.error("Failed to get subscription history",
                        error=str(e),
                        user_id=user_id)
            return []
    
    async def get_expiring_subscriptions(self, days_threshold: int = 3) -> List[dict]:
        """
        Получение подписок которые истекают в ближайшие дни
        
        Args:
            days_threshold: Количество дней до истечения
            
        Returns:
            List[dict]: Список истекающих подписок
        """
        try:
            threshold_date = datetime.now() + timedelta(days=days_threshold)
            expiring = await db.get_expiring_subscriptions(threshold_date)
            
            logger.info("Retrieved expiring subscriptions",
                       threshold_days=days_threshold,
                       expiring_count=len(expiring))
            
            return expiring
            
        except Exception as e:
            logger.error("Failed to get expiring subscriptions",
                        error=str(e),
                        days_threshold=days_threshold)
            return []
    
    async def refresh_user_limits(self, user_id: int) -> bool:
        """
        Принудительное обновление лимитов пользователя на основе активной подписки
        
        Args:
            user_id: ID пользователя
            
        Returns:
            bool: True если лимиты обновлены успешно
        """
        try:
            subscription = await self.get_active_subscription(user_id)
            
            if subscription:
                await self._update_user_limits(
                    user_id, 
                    subscription['plan_id'], 
                    subscription['end_date']
                )
                
                logger.info("User limits refreshed to Pro",
                           user_id=user_id,
                           plan_id=subscription['plan_id'])
                
                return True
            else:
                await self._reset_user_limits(user_id)
                
                logger.info("User limits refreshed to Free",
                           user_id=user_id)
                
                return True
            
        except Exception as e:
            logger.error("Failed to refresh user limits",
                        error=str(e),
                        user_id=user_id)
            return False
    
    async def validate_subscription_integrity(self) -> dict:
        """
        Проверка целостности данных подписок
        
        Returns:
            dict: Результаты проверки
        """
        try:
            # Получаем статистику
            stats = await self.get_subscription_stats()
            
            # Проверяем активные подписки на истечение
            active_subscriptions = await db.get_all_active_subscriptions()
            expired_found = 0
            
            for subscription in active_subscriptions:
                end_date = subscription.get('end_date')
                if end_date and end_date <= datetime.now():
                    # Подписка истекла, но статус еще активный
                    await self._deactivate_subscription(
                        subscription['id'], 
                        'auto_expired_by_integrity_check'
                    )
                    await self._reset_user_limits(subscription['user_id'])
                    expired_found += 1
            
            logger.info("Subscription integrity check completed",
                       total_active=len(active_subscriptions),
                       expired_found=expired_found)
            
            return {
                'success': True,
                'total_active_subscriptions': len(active_subscriptions),
                'expired_subscriptions_fixed': expired_found,
                'statistics': stats
            }
            
        except Exception as e:
            logger.error("Failed to validate subscription integrity", error=str(e))
            return {
                'success': False,
                'error': str(e)
            }
    
    # Внутренние методы
    
    async def _update_user_limits(self, user_id: int, plan_id: str, end_date: datetime):
        """Обновление лимитов пользователя при активной подписке"""
        try:
            limits = {
                'max_bots': settings.pro_max_bots,
                'max_subscribers': settings.pro_max_subscribers,
                'subscription_active': True,
                'subscription_end': end_date,
                'subscription_plan': plan_id
            }
            
            await db.update_user_limits(user_id, limits)
            
            logger.debug("User limits updated to Pro",
                        user_id=user_id,
                        plan_id=plan_id,
                        end_date=end_date.isoformat())
            
        except Exception as e:
            logger.error("Failed to update user limits to Pro",
                        error=str(e),
                        user_id=user_id)
    
    async def _reset_user_limits(self, user_id: int):
        """Сброс лимитов пользователя при отсутствии подписки"""
        try:
            limits = {
                'max_bots': settings.max_bots_per_user,
                'max_subscribers': settings.free_plan_subscribers_limit,
                'subscription_active': False,
                'subscription_end': None,
                'subscription_plan': None
            }
            
            await db.update_user_limits(user_id, limits)
            
            logger.debug("User limits reset to free",
                        user_id=user_id)
            
        except Exception as e:
            logger.error("Failed to reset user limits",
                        error=str(e),
                        user_id=user_id)
    
    async def _deactivate_subscription(self, subscription_id: int, reason: str = None):
        """Деактивация подписки"""
        await db.update_subscription_status(subscription_id, 'cancelled', reason)


# Создаем глобальный экземпляр менеджера
subscription_manager = SubscriptionManager()

# Логируем успешную инициализацию
logger.info("🎉 SubscriptionManager initialized successfully",
           features=[
               "process_successful_payment",
               "create_subscription", 
               "get_active_subscription",
               "check_user_limits",
               "get_subscription_stats",
               "extend_subscription",
               "cancel_subscription",
               "get_user_subscription_history",
               "get_expiring_subscriptions", 
               "refresh_user_limits",
               "validate_subscription_integrity"
           ])
