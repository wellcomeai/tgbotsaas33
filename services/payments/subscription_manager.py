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
                'metadata': {
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
