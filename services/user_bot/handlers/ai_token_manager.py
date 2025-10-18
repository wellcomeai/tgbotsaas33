"""
Менеджер токенов для OpenAI агентов
Управляет балансами, лимитами и уведомлениями о токенах
"""

import structlog
from datetime import datetime
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from services.notifications import send_token_warning_notification
from config import Emoji

logger = structlog.get_logger()


class TokenManager:
    """Менеджер токенов для OpenAI агентов"""
    
    def __init__(self, db, bot_config: dict):
        self.db = db
        self.bot_config = bot_config
        self.bot_id = bot_config['bot_id']
        self.owner_user_id = bot_config['owner_user_id']
        self.bot_username = bot_config['bot_username']
        
        logger.info("🔧 TokenManager initialized", 
                   bot_id=self.bot_id,
                   owner_user_id=self.owner_user_id)

    async def initialize_user_token_balance(self, user_id: int, admin_chat_id: int) -> bool:
        """Инициализация токенового баланса для пользователя если это его первый OpenAI агент"""
        try:
            logger.info("🔍 Checking if user needs token balance initialization", 
                       user_id=user_id, admin_chat_id=admin_chat_id)
            
            # Используем новый метод из DatabaseManager
            success = await self.db.initialize_token_balance(
                user_id=user_id, 
                admin_chat_id=admin_chat_id,
                bot_id=self.bot_id
            )
            
            if success:
                logger.info("✅ Token balance initialized successfully", 
                           user_id=user_id, admin_chat_id=admin_chat_id)
                return True
            else:
                logger.error("❌ Failed to initialize token balance", user_id=user_id)
                return False
                
        except Exception as e:
            logger.error("💥 Exception in token balance initialization", 
                        user_id=user_id, error=str(e), exc_info=True)
            return False

    async def check_token_limits_before_request(self, user_id: int) -> tuple[bool, str]:
        """✅ Проверка лимитов токенов перед запросом к OpenAI"""
        try:
            logger.info("🔍 Checking token limits before OpenAI request", 
                       user_id=user_id, bot_id=self.bot_id)
            
            # Проверяем лимит токенов
            has_tokens, used_tokens, limit_tokens = await self.db.check_token_limit(user_id)
            
            logger.info("📊 Token limit check result", 
                       user_id=user_id,
                       has_tokens=has_tokens,
                       used_tokens=used_tokens,
                       limit_tokens=limit_tokens)
            
            if not has_tokens:
                # Токены закончились
                logger.warning("❌ User exceeded token limit", 
                              user_id=user_id,
                              used=used_tokens,
                              limit=limit_tokens)
                
                # Отправляем уведомление администратору
                await self._send_token_exhausted_notification(user_id, self.bot_id, limit_tokens - used_tokens)
                
                error_message = f"""
❌ <b>Токены закончились!</b>

Вы использовали: {used_tokens:,} / {limit_tokens:,} токенов

<b>Что делать:</b>
• Обратитесь к администратору для пополнения
• Или дождитесь обновления лимитов

💡 <i>Токены нужны для работы OpenAI агента</i>
"""
                return False, error_message
            
            # Проверяем процент использования для предупреждений
            usage_percentage = (used_tokens / limit_tokens) * 100 if limit_tokens > 0 else 0
            
            logger.info("📈 Token usage percentage", 
                       user_id=user_id,
                       percentage=usage_percentage)
            
            # Отправляем предупреждения при достижении лимитов
            if usage_percentage >= 80:
                should_notify = await self.db.should_send_token_notification(user_id)
                if should_notify:
                    await self._send_token_warning(user_id, used_tokens, limit_tokens, usage_percentage)
            
            return True, ""
            
        except Exception as e:
            logger.error("💥 Error checking token limits", 
                        user_id=user_id,
                        error=str(e),
                        error_type=type(e).__name__)
            # В случае ошибки разрешаем запрос (fail-open)
            return True, ""
    
    async def save_token_usage_after_response(self, user_id: int, input_tokens: int, output_tokens: int, admin_chat_id: int = None):
        """✅ Сохранение использованных токенов после ответа OpenAI"""
        try:
            logger.info("💰 Saving token usage after OpenAI response", 
                       user_id=user_id,
                       bot_id=self.bot_id,
                       input_tokens=input_tokens,
                       output_tokens=output_tokens)
            
            # Используем admin_chat_id из настроек агента если не передан
            if not admin_chat_id:
                admin_chat_id = self.owner_user_id
            
            # Сохраняем использование токенов
            success = await self.db.save_token_usage(
                bot_id=self.bot_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                admin_chat_id=admin_chat_id,
                user_id=user_id
            )
            
            if success:
                logger.info("✅ Token usage saved successfully")
            else:
                logger.error("❌ Failed to save token usage")
            
            return success
            
        except Exception as e:
            logger.error("💥 Error saving token usage", 
                        user_id=user_id,
                        error=str(e),
                        error_type=type(e).__name__)
            return False
    
    async def _send_token_warning(self, user_id: int, used_tokens: int, limit_tokens: int, percentage: float):
        """✅ Отправка предупреждения о достижении лимита токенов"""
        try:
            logger.info("⚠️ Sending token usage warning", 
                       user_id=user_id,
                       percentage=percentage,
                       used=used_tokens,
                       limit=limit_tokens)
            
            # Получаем admin_chat_id для отправки уведомления
            admin_chat_id = await self.db.get_admin_chat_id_for_token_notification(user_id)
            
            if admin_chat_id:
                # Отправляем уведомление через notification service
                await send_token_warning_notification(
                    admin_chat_id=admin_chat_id,
                    user_id=user_id,
                    used_tokens=used_tokens,
                    limit_tokens=limit_tokens,
                    percentage=percentage,
                    bot_username=self.bot_username
                )
                
                # Помечаем что уведомление отправлено
                await self.db.set_token_notification_sent(user_id, True)
                
                logger.info("✅ Token warning notification sent successfully")
            else:
                logger.warning("⚠️ No admin chat ID found for token notification", user_id=user_id)
            
        except Exception as e:
            logger.error("💥 Error sending token warning", 
                        user_id=user_id,
                        error=str(e),
                        error_type=type(e).__name__)

    async def _send_token_exhausted_notification(self, user_id: int, bot_id: str, remaining_tokens: int):
        """Отправка уведомления об исчерпании токенов"""
        try:
            logger.info("📢 Sending token exhausted notification", 
                       user_id=user_id,
                       bot_id=bot_id,
                       remaining_tokens=remaining_tokens)
            
            # Получаем admin_chat_id из конфигурации бота
            bot_config = await self.db.get_bot_full_config(bot_id)
            if not bot_config:
                logger.error("❌ Cannot send notification: bot config not found", bot_id=bot_id)
                return
            
            admin_chat_id = bot_config.get('openai_admin_chat_id')
            if not admin_chat_id:
                logger.warning("⚠️ No admin_chat_id found for token notification", 
                              bot_id=bot_id,
                              user_id=user_id)
                return
            
            # ✅ ИСПРАВЛЕНО: Используем правильный метод
            notification_sent = await self.db.should_send_token_notification(user_id)
            if not notification_sent:  # should_send возвращает True если нужно отправить
                logger.info("ℹ️ Token exhausted notification already sent", user_id=user_id)
                return
            
            # Отправляем уведомление через бота
            try:
                # Получаем экземпляр бота для отправки уведомления
                try:
                    from services.bot_manager import bot_manager
                    
                    notification_text = f"""
🚨 <b>Токены OpenAI исчерпаны!</b>

🤖 <b>Бот:</b> {bot_config.get('bot_username', 'Unknown')}
👤 <b>Пользователь ID:</b> {user_id}
🎯 <b>Оставшиеся токены:</b> {remaining_tokens}

❌ ИИ агент временно недоступен для пользователей.
💰 Пополните баланс токенов для продолжения работы.
"""
                    
                    await bot_manager.send_admin_notification(
                        admin_chat_id, 
                        notification_text
                    )
                    
                    # Отмечаем что уведомление отправлено
                    await self.db.set_token_notification_sent(user_id, True)
                    
                    logger.info("✅ Token exhausted notification sent", 
                               admin_chat_id=admin_chat_id,
                               user_id=user_id)
                    
                except ImportError:
                    logger.warning("⚠️ bot_manager not available for notifications")
                except Exception as e:
                    logger.error("💥 Failed to send notification via bot_manager", 
                               error=str(e))
                    
            except Exception as e:
                logger.error("💥 Failed to send token exhausted notification", 
                           admin_chat_id=admin_chat_id,
                           error=str(e))
                
        except Exception as e:
            logger.error("💥 Error in token exhausted notification", 
                        user_id=user_id,
                        error=str(e),
                        error_type=type(e).__name__)
    
    def format_number(self, number: int) -> str:
        """✅ Форматирование чисел с пробелами (22 500)"""
        return f"{number:,}".replace(",", " ")
    
    async def handle_request_token_topup(self, callback: CallbackQuery):
        """✅ Обработчик запроса пополнения токенов"""
        await callback.answer()
        
        if callback.from_user.id != self.owner_user_id:
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            logger.info("💳 Token topup request", 
                       user_id=self.owner_user_id,
                       bot_id=self.bot_id)
            
            # Получаем текущую статистику токенов
            token_balance = await self.db.get_user_token_balance(self.owner_user_id)
            
            used_formatted = self.format_number(token_balance.get('total_used', 0))
            limit_formatted = self.format_number(token_balance.get('limit', 500000))
            remaining_formatted = self.format_number(token_balance.get('remaining', 500000))
            percentage = token_balance.get('percentage_used', 0.0)
            
            text = f"""
💳 <b>Запрос пополнения токенов</b>

<b>Текущая статистика:</b>
📊 Использовано: {used_formatted} / {limit_formatted} ({percentage:.1f}%)
📉 Осталось: {remaining_formatted}

<b>Ваш запрос отправлен администратору!</b>

Администратор получит уведомление с вашими данными:
• User ID: {self.owner_user_id}
• Bot: @{self.bot_username}
• Текущее использование: {percentage:.1f}%

⏰ <b>Обычно пополнение происходит в течение 24 часов</b>

<i>Вы получите уведомление, когда токены будут пополнены.</i>
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Понятно", callback_data="admin_tokens")],
                [InlineKeyboardButton(text=f"{Emoji.BACK} Главное меню", callback_data="admin_main")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
            # Отправляем уведомление администраторам (можно добавить в будущем)
            logger.info("📨 Token topup request processed", 
                       user_id=self.owner_user_id,
                       current_usage=percentage)
            
        except Exception as e:
            logger.error("💥 Error processing token topup request", 
                        user_id=self.owner_user_id,
                        error=str(e),
                        error_type=type(e).__name__)
            await callback.answer("Ошибка при обработке запроса", show_alert=True)
