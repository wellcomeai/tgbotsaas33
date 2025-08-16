"""
Payment Notification Service
Сервис для уведомлений о платежах и подписках
"""

import structlog
from datetime import datetime, timedelta
from typing import Optional, List
from aiogram import Bot

from config import settings

logger = structlog.get_logger()


class PaymentNotificationService:
    """Сервис уведомлений о платежах"""
    
    def __init__(self, bot: Bot = None):
        self.bot = bot
    
    def set_bot(self, bot: Bot):
        """Установка экземпляра бота для отправки уведомлений"""
        self.bot = bot
    
    async def send_payment_success_notification(self, 
                                               user_id: int, 
                                               subscription: dict, 
                                               payment_data: dict):
        """
        Отправка уведомления об успешном платеже
        
        Args:
            user_id: ID пользователя
            subscription: Данные подписки
            payment_data: Данные платежа
        """
        try:
            if not self.bot:
                logger.warning("Bot not set for payment notifications")
                return
            
            plan_name = subscription.get('plan_name', 'AI ADMIN')
            amount = payment_data.get('amount', 0)
            end_date = subscription.get('end_date')
            
            text = f"""
🎉 <b>Платеж успешно обработан!</b>

💎 <b>Подписка:</b> {plan_name}
💰 <b>Сумма:</b> {amount} ₽
📅 <b>Действует до:</b> {end_date.strftime('%d.%m.%Y в %H:%M') if end_date else 'Неизвестно'}

✅ <b>Активированные Pro функции:</b>
• Безлимитное количество ботов
• Безлимитные подписчики для каждого бота  
• Расширенные воронки продаж
• Приоритетная техническая поддержка
• Доступ ко всем будущим обновлениям

🚀 <b>Теперь создавайте ботов без ограничений!</b>

💡 <b>Следующие шаги:</b>
1. Создайте нового бота или настройте существующего
2. Используйте все возможности воронок продаж
3. Подключите ИИ агентов для пользователей

Спасибо за выбор Bot Factory! 🙌
"""
            
            await self.bot.send_message(
                chat_id=user_id,
                text=text
            )
            
            logger.info("Payment success notification sent",
                       user_id=user_id,
                       subscription_id=subscription.get('id'),
                       amount=amount)
            
        except Exception as e:
            logger.error("Failed to send payment success notification",
                        error=str(e),
                        user_id=user_id)
    
    async def send_payment_failed_notification(self, 
                                             user_id: int, 
                                             order_id: str,
                                             amount: float,
                                             reason: str = None):
        """Отправка уведомления о неудачном платеже"""
        try:
            if not self.bot:
                logger.warning("Bot not set for payment notifications")
                return
            
            text = f"""
❌ <b>Платеж не прошел</b>

💳 <b>Заказ:</b> {order_id}
💰 <b>Сумма:</b> {amount} ₽

😔 К сожалению, ваш платеж не был обработан.

🔄 <b>Что можно сделать:</b>
• Попробовать другую карту
• Проверить достаточность средств
• Обратиться в поддержку банка
• Связаться с нашей поддержкой

💡 <b>Попробуйте оплатить еще раз</b> — нажмите /start и выберите "💎 Оплатить тариф"

Если проблема повторяется, обратитесь в поддержку: @support
"""
            
            await self.bot.send_message(
                chat_id=user_id,
                text=text
            )
            
            logger.info("Payment failed notification sent",
                       user_id=user_id,
                       order_id=order_id,
                       amount=amount,
                       reason=reason)
            
        except Exception as e:
            logger.error("Failed to send payment failed notification",
                        error=str(e),
                        user_id=user_id)
    
    async def send_subscription_expiry_warning(self, 
                                             user_id: int, 
                                             subscription: dict,
                                             days_left: int):
        """Предупреждение об истечении подписки"""
        try:
            if not self.bot:
                logger.warning("Bot not set for payment notifications")
                return
            
            plan_name = subscription.get('plan_name', 'AI ADMIN')
            end_date = subscription.get('end_date')
            
            if days_left <= 1:
                urgency = "⚠️ <b>СРОЧНО: Подписка истекает завтра!</b>"
                emoji = "🔥"
            elif days_left <= 3:
                urgency = "⏰ <b>Подписка истекает через несколько дней</b>"
                emoji = "⚡"
            else:
                urgency = "💡 <b>Напоминание о подписке</b>"
                emoji = "💎"
            
            text = f"""
{urgency}

{emoji} <b>Подписка:</b> {plan_name}
📅 <b>Истекает:</b> {end_date.strftime('%d.%m.%Y') if end_date else 'Неизвестно'}
⏳ <b>Осталось дней:</b> {days_left}

😟 <b>После истечения вы потеряете:</b>
• Безлимитное создание ботов
• Расширенные возможности воронок
• Приоритетную поддержку

🎯 <b>Продлите прямо сейчас со скидкой!</b>
• 12 месяцев — экономия 1,098₽
• 6 месяцев — экономия 295₽
• 3 месяца — экономия 150₽

Нажмите /start → "💎 Оплатить тариф" для продления
"""
            
            await self.bot.send_message(
                chat_id=user_id,
                text=text
            )
            
            logger.info("Subscription expiry warning sent",
                       user_id=user_id,
                       subscription_id=subscription.get('id'),
                       days_left=days_left)
            
        except Exception as e:
            logger.error("Failed to send subscription expiry warning",
                        error=str(e),
                        user_id=user_id)
    
    async def send_subscription_expired_notification(self, 
                                                   user_id: int, 
                                                   subscription: dict):
        """Уведомление об истечении подписки"""
        try:
            if not self.bot:
                logger.warning("Bot not set for payment notifications")
                return
            
            plan_name = subscription.get('plan_name', 'AI ADMIN')
            
            text = f"""
😔 <b>Подписка истекла</b>

💎 <b>Подписка:</b> {plan_name}
📅 <b>Истекла:</b> {datetime.now().strftime('%d.%m.%Y')}

🔒 <b>Теперь действуют ограничения:</b>
• Максимум {settings.max_bots_per_user} ботов
• До {settings.free_plan_subscribers_limit} подписчиков на бота
• Ограниченные воронки продаж

💡 <b>Восстановите Pro функции:</b>
Нажмите /start → "💎 Оплатить тариф"

🎁 <b>Специальное предложение для возвращения:</b>
Скидка 10% при оплате в течение 7 дней!

Мы скучаем по вам! 💙
"""
            
            await self.bot.send_message(
                chat_id=user_id,
                text=text
            )
            
            logger.info("Subscription expired notification sent",
                       user_id=user_id,
                       subscription_id=subscription.get('id'))
            
        except Exception as e:
            logger.error("Failed to send subscription expired notification",
                        error=str(e),
                        user_id=user_id)
    
    async def send_admin_payment_notification(self, 
                                            admin_chat_id: int,
                                            payment_data: dict,
                                            subscription: dict):
        """Уведомление администратора о новом платеже"""
        try:
            if not self.bot:
                logger.warning("Bot not set for admin notifications")
                return
            
            user_id = payment_data.get('user_id')
            amount = payment_data.get('amount')
            plan_id = payment_data.get('plan_id')
            order_id = payment_data.get('order_id')
            
            text = f"""
💰 <b>Новый платеж!</b>

👤 <b>Пользователь:</b> {user_id}
💎 <b>План:</b> {plan_id}
💰 <b>Сумма:</b> {amount} ₽
🆔 <b>Заказ:</b> {order_id}
📅 <b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}

✅ Подписка активирована автоматически
"""
            
            await self.bot.send_message(
                chat_id=admin_chat_id,
                text=text
            )
            
            logger.info("Admin payment notification sent",
                       admin_chat_id=admin_chat_id,
                       user_id=user_id,
                       amount=amount)
            
        except Exception as e:
            logger.error("Failed to send admin payment notification",
                        error=str(e),
                        admin_chat_id=admin_chat_id)


# Создаем глобальный экземпляр сервиса
payment_notifier = PaymentNotificationService()
