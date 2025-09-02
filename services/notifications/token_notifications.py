"""
Сервис уведомлений о токенах OpenAI
Отправка уведомлений админам о состоянии токенов
"""

import structlog
from typing import Optional, Dict, Any
from datetime import datetime
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

logger = structlog.get_logger()


class TokenNotificationService:
    """Сервис для отправки уведомлений о состоянии токенов"""
    
    def __init__(self, bot: Bot):
        """
        Инициализация сервиса
        
        Args:
            bot: Экземпляр Telegram бота для отправки сообщений
        """
        self.bot = bot
        logger.info("TokenNotificationService initialized")
    
    async def send_token_exhausted_notification(
        self, 
        admin_chat_id: int, 
        bot_info: Dict[str, Any],
        token_info: Dict[str, Any]
    ) -> bool:
        """
        Отправка уведомления об исчерпании токенов
        
        Args:
            admin_chat_id: Chat ID админа для отправки уведомления
            bot_info: Информация о боте (bot_id, bot_username, agent_name)
            token_info: Информация о токенах (tokens_used, tokens_limit, etc.)
            
        Returns:
            bool: True если уведомление отправлено успешно
        """
        try:
            logger.info("📧 Sending token exhausted notification", 
                       admin_chat_id=admin_chat_id,
                       bot_id=bot_info.get('bot_id'),
                       tokens_used=token_info.get('tokens_used', 0))
            
            # Извлекаем данные
            bot_username = bot_info.get('bot_username', 'unknown')
            agent_name = bot_info.get('agent_name', 'OpenAI агент')
            tokens_used = token_info.get('tokens_used', 0)
            tokens_limit = token_info.get('tokens_limit', 500000)
            last_usage_at = token_info.get('last_usage_at')
            
            # Форматируем время последнего использования
            last_usage_text = ""
            if last_usage_at:
                if isinstance(last_usage_at, str):
                    last_usage_text = f"\n<b>Последнее использование:</b> {last_usage_at}"
                else:
                    last_usage_text = f"\n<b>Последнее использование:</b> {last_usage_at.strftime('%d.%m.%Y %H:%M')}"
            
            # Формируем текст уведомления
            notification_text = f"""
🚨 <b>Токены исчерпаны!</b>

<b>Бот:</b> @{bot_username}
<b>ИИ Агент:</b> {agent_name}

💰 <b>Статус токенов:</b>
<b>Использовано:</b> {tokens_used:,} токенов
<b>Лимит:</b> {tokens_limit:,} токенов
<b>Превышение:</b> {(tokens_used - tokens_limit):,} токенов{last_usage_text}

❌ <b>Агент остановлен</b> - пользователи не могут им пользоваться.

⚡ <b>Для восстановления работы:</b>
• Пополните баланс токенов
• Или обратитесь к техподдержке

🔔 <i>Это автоматическое уведомление от системы токенов.</i>
"""
            
            # Отправляем уведомление
            await self.bot.send_message(
                chat_id=admin_chat_id,
                text=notification_text,
                parse_mode=ParseMode.HTML,
                disable_notification=False  # Важное уведомление - со звуком
            )
            
            logger.info("✅ Token exhausted notification sent successfully", 
                       admin_chat_id=admin_chat_id,
                       bot_id=bot_info.get('bot_id'),
                       tokens_used=tokens_used,
                       tokens_limit=tokens_limit)
            
            return True
            
        except TelegramForbiddenError:
            logger.warning("❌ Admin blocked bot - cannot send token notification", 
                          admin_chat_id=admin_chat_id,
                          bot_id=bot_info.get('bot_id'))
            return False
            
        except TelegramBadRequest as e:
            logger.error("❌ Bad request when sending token notification", 
                        admin_chat_id=admin_chat_id,
                        bot_id=bot_info.get('bot_id'),
                        error=str(e))
            return False
            
        except Exception as e:
            logger.error("💥 Failed to send token exhausted notification", 
                        admin_chat_id=admin_chat_id,
                        bot_id=bot_info.get('bot_id'),
                        error=str(e),
                        exc_info=True)
            return False
    
    async def send_token_warning_notification(
        self, 
        admin_chat_id: int, 
        bot_info: Dict[str, Any],
        token_info: Dict[str, Any],
        warning_threshold: float = 0.9
    ) -> bool:
        """
        Отправка предупреждения о скором исчерпании токенов
        
        Args:
            admin_chat_id: Chat ID админа для отправки уведомления
            bot_info: Информация о боте (bot_id, bot_username, agent_name)
            token_info: Информация о токенах (tokens_used, tokens_limit, etc.)
            warning_threshold: Порог предупреждения (по умолчанию 0.9 = 90%)
            
        Returns:
            bool: True если уведомление отправлено успешно
        """
        try:
            logger.info("📧 Sending token warning notification", 
                       admin_chat_id=admin_chat_id,
                       bot_id=bot_info.get('bot_id'),
                       tokens_used=token_info.get('tokens_used', 0),
                       threshold=warning_threshold)
            
            # Извлекаем данные
            bot_username = bot_info.get('bot_username', 'unknown')
            agent_name = bot_info.get('agent_name', 'OpenAI агент')
            tokens_used = token_info.get('tokens_used', 0)
            tokens_limit = token_info.get('tokens_limit', 500000)
            remaining_tokens = tokens_limit - tokens_used
            usage_percent = (tokens_used / tokens_limit) * 100
            
            # Определяем уровень предупреждения
            if usage_percent >= 95:
                warning_emoji = "🔴"
                urgency_text = "КРИТИЧНО"
            elif usage_percent >= 90:
                warning_emoji = "🟡"
                urgency_text = "ВНИМАНИЕ"
            else:
                warning_emoji = "🟢"
                urgency_text = "УВЕДОМЛЕНИЕ"
            
            # Вычисляем примерное количество оставшихся сообщений
            # Предполагаем среднее потребление ~100 токенов на сообщение
            estimated_messages = remaining_tokens // 100
            
            # Форматируем текст уведомления
            notification_text = f"""
{warning_emoji} <b>{urgency_text}: Токены заканчиваются!</b>

<b>Бот:</b> @{bot_username}
<b>ИИ Агент:</b> {agent_name}

💰 <b>Статус токенов:</b>
<b>Использовано:</b> {tokens_used:,} токенов ({usage_percent:.1f}%)
<b>Осталось:</b> {remaining_tokens:,} токенов
<b>Лимит:</b> {tokens_limit:,} токенов

📊 <b>Примерная оценка:</b>
<b>Сообщений осталось:</b> ~{estimated_messages:,}

⚡ <b>Рекомендации:</b>
• Пополните баланс токенов заранее
• Следите за использованием агента
• Настройте дневные лимиты при необходимости

🔔 <i>Предупреждение отправляется при достижении {warning_threshold*100:.0f}% использования.</i>
"""
            
            # Отправляем уведомление
            await self.bot.send_message(
                chat_id=admin_chat_id,
                text=notification_text,
                parse_mode=ParseMode.HTML,
                disable_notification=(usage_percent < 95)  # Тихо если < 95%
            )
            
            logger.info("✅ Token warning notification sent successfully", 
                       admin_chat_id=admin_chat_id,
                       bot_id=bot_info.get('bot_id'),
                       usage_percent=usage_percent,
                       remaining_tokens=remaining_tokens)
            
            return True
            
        except TelegramForbiddenError:
            logger.warning("❌ Admin blocked bot - cannot send warning notification", 
                          admin_chat_id=admin_chat_id,
                          bot_id=bot_info.get('bot_id'))
            return False
            
        except TelegramBadRequest as e:
            logger.error("❌ Bad request when sending warning notification", 
                        admin_chat_id=admin_chat_id,
                        bot_id=bot_info.get('bot_id'),
                        error=str(e))
            return False
            
        except Exception as e:
            logger.error("💥 Failed to send token warning notification", 
                        admin_chat_id=admin_chat_id,
                        bot_id=bot_info.get('bot_id'),
                        error=str(e),
                        exc_info=True)
            return False
    
    async def send_token_replenished_notification(
        self, 
        admin_chat_id: int, 
        bot_info: Dict[str, Any],
        old_limit: int,
        new_limit: int
    ) -> bool:
        """
        Отправка уведомления о пополнении токенов (дополнительный метод)
        
        Args:
            admin_chat_id: Chat ID админа
            bot_info: Информация о боте
            old_limit: Старый лимит токенов
            new_limit: Новый лимит токенов
            
        Returns:
            bool: True если уведомление отправлено успешно
        """
        try:
            logger.info("📧 Sending token replenished notification", 
                       admin_chat_id=admin_chat_id,
                       old_limit=old_limit,
                       new_limit=new_limit)
            
            bot_username = bot_info.get('bot_username', 'unknown')
            agent_name = bot_info.get('agent_name', 'OpenAI агент')
            added_tokens = new_limit - old_limit
            
            notification_text = f"""
✅ <b>Токены пополнены!</b>

<b>Бот:</b> @{bot_username}
<b>ИИ Агент:</b> {agent_name}

💰 <b>Пополнение:</b>
<b>Было:</b> {old_limit:,} токенов
<b>Добавлено:</b> +{added_tokens:,} токенов
<b>Стало:</b> {new_limit:,} токенов

🎉 <b>Агент снова активен!</b> Пользователи могут продолжить общение.

🔔 <i>Уведомление о пополнении баланса токенов.</i>
"""
            
            await self.bot.send_message(
                chat_id=admin_chat_id,
                text=notification_text,
                parse_mode=ParseMode.HTML,
                disable_notification=True  # Позитивное уведомление - тихо
            )
            
            logger.info("✅ Token replenished notification sent successfully", 
                       admin_chat_id=admin_chat_id,
                       added_tokens=added_tokens)
            
            return True
            
        except Exception as e:
            logger.error("💥 Failed to send token replenished notification", 
                        admin_chat_id=admin_chat_id,
                        error=str(e),
                        exc_info=True)
            return False
    
    @staticmethod
    def format_token_info(token_info: Dict[str, Any]) -> str:
        """
        Форматирование информации о токенах для отображения
        
        Args:
            token_info: Словарь с информацией о токенах
            
        Returns:
            str: Отформатированная строка с информацией о токенах
        """
        tokens_used = token_info.get('tokens_used', 0)
        tokens_limit = token_info.get('tokens_limit', 500000)
        remaining_tokens = tokens_limit - tokens_used
        usage_percent = (tokens_used / tokens_limit) * 100 if tokens_limit > 0 else 0
        
        # Определяем статус
        if remaining_tokens <= 0:
            status = "❌ Исчерпаны"
        elif usage_percent >= 90:
            status = "⚠️ Заканчиваются"
        elif usage_percent >= 70:
            status = "🟡 Активное использование"
        else:
            status = "✅ В норме"
        
        return f"""
💰 <b>Токены:</b> {status}
<b>Использовано:</b> {tokens_used:,} ({usage_percent:.1f}%)
<b>Осталось:</b> {remaining_tokens:,}
<b>Лимит:</b> {tokens_limit:,}
"""


# Глобальный экземпляр сервиса (будет инициализирован при первом использовании)
_notification_service: Optional[TokenNotificationService] = None


def get_notification_service(bot: Bot) -> TokenNotificationService:
    """
    Получить экземпляр сервиса уведомлений
    
    Args:
        bot: Экземпляр бота для отправки уведомлений
        
    Returns:
        TokenNotificationService: Экземпляр сервиса уведомлений
    """
    global _notification_service
    
    if _notification_service is None:
        _notification_service = TokenNotificationService(bot)
        logger.info("TokenNotificationService instance created")
    
    return _notification_service


# Удобные функции для быстрого использования
async def send_token_exhausted_notification(
    bot: Bot,
    admin_chat_id: int, 
    bot_info: Dict[str, Any],
    token_info: Dict[str, Any]
) -> bool:
    """
    Быстрая отправка уведомления об исчерпании токенов
    
    Args:
        bot: Экземпляр бота
        admin_chat_id: Chat ID админа
        bot_info: Информация о боте
        token_info: Информация о токенах
        
    Returns:
        bool: True если отправлено успешно
    """
    service = get_notification_service(bot)
    return await service.send_token_exhausted_notification(admin_chat_id, bot_info, token_info)


async def send_token_warning_notification(
    bot: Bot,
    admin_chat_id: int, 
    bot_info: Dict[str, Any],
    token_info: Dict[str, Any],
    warning_threshold: float = 0.9
) -> bool:
    """
    Быстрая отправка предупреждения о токенах
    
    Args:
        bot: Экземпляр бота
        admin_chat_id: Chat ID админа
        bot_info: Информация о боте
        token_info: Информация о токенах
        warning_threshold: Порог предупреждения
        
    Returns:
        bool: True если отправлено успешно
    """
    service = get_notification_service(bot)
    return await service.send_token_warning_notification(admin_chat_id, bot_info, token_info, warning_threshold)
