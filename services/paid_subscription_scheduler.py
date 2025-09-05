"""
Планировщик уведомлений о платных подписках
Проверяет истекающие подписки и отправляет уведомления
"""

import asyncio
import structlog
from datetime import datetime, timedelta
from typing import List

logger = structlog.get_logger()

class PaidSubscriptionScheduler:
    """Планировщик платных подписок"""
    
    def __init__(self, db, bot_manager):
        self.db = db
        self.bot_manager = bot_manager
        self.running = False
    
    async def start(self):
        """Запуск планировщика"""
        self.running = True
        logger.info("📅 Paid subscription scheduler started")
        
        try:
            while self.running:
                await self._check_expiring_subscriptions()
                await self._remove_expired_subscribers()
                await asyncio.sleep(3600)  # Проверяем каждый час
        except asyncio.CancelledError:
            logger.info("📅 Paid subscription scheduler stopped")
        except Exception as e:
            logger.error("💥 Error in paid subscription scheduler", error=str(e))
    
    async def stop(self):
        """Остановка планировщика"""
        self.running = False
    
    async def _check_expiring_subscriptions(self):
        """Проверка истекающих подписок"""
        try:
            from database.models import PaidSubscriber, BotPaidSubscription
            from sqlalchemy import select, and_
            
            # Получаем подписки истекающие в ближайшие дни
            reminder_date = datetime.now() + timedelta(days=3)  # За 3 дня
            
            async with self.db.get_db_session() as session:
                result = await session.execute(
                    select(PaidSubscriber, BotPaidSubscription)
                    .join(BotPaidSubscription, PaidSubscriber.bot_id == BotPaidSubscription.bot_id)
                    .where(
                        and_(
                            PaidSubscriber.status == "active",
                            PaidSubscriber.subscription_end <= reminder_date,
                            PaidSubscriber.subscription_end > datetime.now(),
                            PaidSubscriber.reminder_sent_at.is_(None)
                        )
                    )
                )
                
                expiring_subscriptions = result.all()
            
            for subscriber, settings in expiring_subscriptions:
                await self._send_expiration_reminder(subscriber, settings)
                
        except Exception as e:
            logger.error("Failed to check expiring subscriptions", error=str(e))
    
    async def _remove_expired_subscribers(self):
        """Удаление истекших подписчиков из каналов"""
        try:
            from database.models import PaidSubscriber
            from sqlalchemy import select, update
            
            async with self.db.get_db_session() as session:
                result = await session.execute(
                    select(PaidSubscriber)
                    .where(
                        and_(
                            PaidSubscriber.status == "active",
                            PaidSubscriber.subscription_end <= datetime.now()
                        )
                    )
                )
                
                expired_subscribers = result.scalars().all()
            
            for subscriber in expired_subscribers:
                # Удаляем из канала
                await self._remove_from_channel(subscriber)
                
                # Обновляем статус в БД
                async with self.db.get_db_session() as session:
                    await session.execute(
                        update(PaidSubscriber)
                        .where(PaidSubscriber.id == subscriber.id)
                        .values(
                            status="expired",
                            expired_notification_sent_at=datetime.now()
                        )
                    )
                    await session.commit()
                
        except Exception as e:
            logger.error("Failed to remove expired subscribers", error=str(e))
    
    async def _remove_from_channel(self, subscriber):
        """Удаление пользователя из канала"""
        try:
            bot_instance = self.bot_manager.get_bot_instance(subscriber.bot_id)
            if not bot_instance:
                return
            
            # Удаляем из канала
            await bot_instance.ban_chat_member(
                chat_id=subscriber.channel_id,
                user_id=subscriber.user_id,
                until_date=datetime.now() + timedelta(seconds=30)  # Временный бан
            )
            
            # Сразу разбанить (чтобы мог вернуться при новой оплате)
            await asyncio.sleep(1)
            await bot_instance.unban_chat_member(subscriber.channel_id, subscriber.user_id)
            
            # Уведомить пользователя
            await bot_instance.send_message(
                subscriber.user_id,
                "⏰ <b>Ваша подписка истекла!</b>\n\n"
                "💳 Оплатите снова чтобы получить доступ к каналу",
                parse_mode="HTML"
            )
            
        except Exception as e:
            logger.error("Failed to remove user from channel", error=str(e))
