"""
Контроль доступа для функций бота
"""
import structlog
from database.managers.user_manager import UserManager

logger = structlog.get_logger()

async def check_user_access(user_id: int, feature: str = "general") -> tuple[bool, dict]:
    """
    Проверить доступ пользователя к функции
    
    Returns:
        (has_access, status_info)
    """
    has_access, status = await UserManager.check_user_has_access(user_id)
    
    logger.debug("Access check", 
                user_id=user_id, 
                feature=feature,
                has_access=has_access,
                status=status.get('status'))
    
    return has_access, status

def require_access(feature: str = "general"):
    """Декоратор для проверки доступа"""
    def decorator(func):
        async def wrapper(message_or_callback, *args, **kwargs):
            user_id = message_or_callback.from_user.id
            has_access, status = await check_user_access(user_id, feature)
            
            if not has_access:
                await send_access_denied_message(message_or_callback, status)
                return
            
            return await func(message_or_callback, *args, **kwargs)
        return wrapper
    return decorator

async def send_access_denied_message(message_or_callback, status: dict):
    """Отправить сообщение об ограничении доступа"""
    from config import Emoji, settings
    
    if status['status'] == 'expired':
        if status.get('trial_expired'):
            text = f"""
{Emoji.WARNING} <b>Пробный период завершен!</b>

Ваши 3 дня бесплатного использования истекли.

💎 <b>Для продолжения работы:</b>
- Оформите подписку AI ADMIN
- Стоимость: {settings.robokassa_payment_amount}₽ за 30 дней
- Все функции будут восстановлены мгновенно

{Emoji.FIRE} <b>Что даёт подписка:</b>
- Безлимитные боты и подписчики
- ИИ агенты без ограничений  
- Приоритетная поддержка
- Расширенная статистика
"""
        else:
            text = f"""
{Emoji.WARNING} <b>Подписка истекла!</b>

Для продолжения использования Bot Factory необходимо продлить подписку.

💰 Стоимость: {settings.robokassa_payment_amount}₽ за 30 дней
"""
    else:
        text = f"{Emoji.ERROR} Доступ ограничен. Обратитесь в поддержку."
    
    # Клавиатура с кнопкой оплаты
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"💳 Оплатить {settings.robokassa_payment_amount}₽",
                callback_data="pay_subscription"
            )
        ],
        [
            InlineKeyboardButton(
                text="🏠 Главное меню",
                callback_data="back_to_main"
            )
        ]
    ])
    
    try:
        if hasattr(message_or_callback, 'message'):
            # Callback query
            await message_or_callback.message.edit_text(text, reply_markup=keyboard)
        else:
            # Message
            await message_or_callback.answer(text, reply_markup=keyboard)
    except Exception as e:
        logger.error("Failed to send access denied message", error=str(e))
