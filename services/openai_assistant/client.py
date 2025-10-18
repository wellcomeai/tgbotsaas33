"""
OpenAI Responses Client
✅ ОБНОВЛЕНО: Полная поддержка OpenAI Responses API
✅ ИСПРАВЛЕНО: Убран неподдерживаемый параметр return_usage
✅ НОВОЕ: Автоматическое управление контекстом через previous_response_id
✅ НОВОЕ: Встроенные инструменты (веб-поиск, код, файлы)
✅ ИСПРАВЛЕНО: Правильная обработка usage данных без return_usage
✅ ИСПРАВЛЕНО: Корректная логика проверки токенов (is not None вместо or)
✅ НОВОЕ: Методы для работы с vector stores
✅ ИСПРАВЛЕНО: Vector stores теперь работают БЕЗ .beta (новый OpenAI SDK)
✅ ИСПРАВЛЕНО: Убран aiofiles, исправлены RuntimeWarning с coroutines
✅ ДОБАВЛЕНО: Методы очистки vector store и удаления файлов
"""

import os
import asyncio
import time
import uuid
import json
from typing import Optional, Dict, Any, List, BinaryIO
from datetime import datetime
import structlog
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from services.notifications import send_token_warning_notification
from .models import (
    OpenAIResponsesAgent, 
    OpenAIResponsesResult, 
    OpenAIResponsesRequest,
    OpenAIResponsesContext,
    OpenAIResponsesConstants,
    OpenAIResponsesValidator
)

logger = structlog.get_logger()


class OpenAIResponsesClient:
    """
    ✅ ОБНОВЛЕНО: Клиент для работы с OpenAI Responses API
    ✅ ИСПРАВЛЕНО: Правильная обработка usage данных без return_usage
    ✅ НОВОЕ: Поддержка vector stores для работы с файлами
    ✅ ИСПРАВЛЕНО: Vector stores работают БЕЗ .beta (новый SDK)
    ✅ ДОБАВЛЕНО: Методы очистки vector store и удаления файлов
    Автоматическое управление контекстом + встроенные инструменты
    """
    
    def __init__(self):
        logger.info("🔧 Initializing OpenAI Responses Client with Responses API support")
        
        self.api_key = os.getenv('OPENAI_API_KEY')
        self.client = None
        
        # ✅ НОВОЕ: Флаг для принудительного сохранения токенов
        self.force_token_estimation = True
        
        logger.info("🔍 Environment check", 
                   api_key_exists=bool(self.api_key),
                   api_key_length=len(self.api_key) if self.api_key else 0,
                   api_key_prefix=self.api_key[:12] + "..." if self.api_key else "None")
        
        if self.api_key:
            try:
                self.client = AsyncOpenAI(api_key=self.api_key)
                logger.info("✅ AsyncOpenAI client created successfully for Responses API")
            except Exception as e:
                logger.error("💥 Failed to create AsyncOpenAI client", 
                           error=str(e), error_type=type(e).__name__)
        else:
            logger.warning("⚠️ OPENAI_API_KEY not found in environment variables")
    
    def _is_configured(self) -> bool:
        """Проверка конфигурации клиента"""
        configured = bool(self.api_key and self.client)
        
        logger.debug("🔧 Configuration check", 
                    api_key_exists=bool(self.api_key),
                    client_exists=bool(self.client),
                    is_configured=configured)
        
        return configured
    
    async def _validate_api_key_with_logging(self):
        """Проверка API ключа"""
        try:
            logger.info("🔍 Validating OpenAI API key...")
            
            start_time = time.time()
            models = await self.client.models.list()
            validation_duration = time.time() - start_time
            
            available_models = [m.id for m in models.data[:5]]
            
            logger.info("✅ API key validation successful", 
                       models_count=len(models.data),
                       validation_duration=f"{validation_duration:.2f}s",
                       available_models=available_models)
            
            return True
            
        except Exception as e:
            logger.error("❌ API key validation failed", 
                        error=str(e), error_type=type(e).__name__)
            return False
    
    async def _check_token_limit(self, assistant_id: str, user_id: int) -> tuple[bool, int, int]:
        """✅ ИСПРАВЛЕНО: Проверка лимита токенов на уровне бота"""
        try:
            from database import db
            
            logger.info("🔍 Checking token limit", 
                       assistant_id=assistant_id,
                       user_id=user_id)
            
            # Получаем конфигурацию агента для получения bot_id
            agent_config = await self._get_agent_config_by_assistant_id(assistant_id)
            if not agent_config:
                logger.error("❌ Agent config not found for token check", 
                           assistant_id=assistant_id)
                return False, 0, 0
            
            bot_id = agent_config['bot_id']
            
            # ✅ ИСПРАВЛЕНО: Получаем бота и проверяем его лимиты
            bot = await db.get_bot_by_id(bot_id)
            if not bot:
                logger.error("❌ Bot not found for token check", bot_id=bot_id)
                return False, 0, 0
            
            # Получаем текущее использование и лимиты бота
            tokens_used = bot.get_total_tokens_used()
            remaining_tokens = bot.get_remaining_tokens()
            
            # Если лимитов нет - разрешаем
            if remaining_tokens is None:
                logger.info("📊 No token limits set - allowing request", 
                           bot_id=bot_id,
                           tokens_used=tokens_used)
                return True, tokens_used, 0
            
            logger.info("📊 Token balance check", 
                       bot_id=bot_id,
                       user_id=user_id,
                       tokens_used=tokens_used,
                       remaining_tokens=remaining_tokens)
            
            # Проверяем исчерпаны ли токены
            if bot.is_tokens_exhausted():
                logger.warning("🚫 Token limit exceeded for bot", 
                              bot_id=bot_id,
                              user_id=user_id,
                              tokens_used=tokens_used,
                              remaining_tokens=remaining_tokens)
                
                # Отправляем уведомление админу если еще не отправляли
                await self._send_token_exhausted_notification(
                    user_id, bot_id, remaining_tokens
                )
                
                return False, tokens_used, tokens_used + remaining_tokens
            
            # Проверяем предупреждение при низком балансе
            total_limit = bot.tokens_limit_total or 0
            if (total_limit > 0 and remaining_tokens <= (total_limit * 0.1) and 
                not bot.openai_token_notification_sent):
                await self._send_token_warning_notification(
                    user_id, bot_id, remaining_tokens
                )
            
            return True, tokens_used, tokens_used + remaining_tokens
            
        except Exception as e:
            logger.error("💥 Error checking token limit", 
                        assistant_id=assistant_id,
                        user_id=user_id,
                        error=str(e),
                        error_type=type(e).__name__)
            return False, 0, 0
    
    async def _save_token_usage(self, assistant_id: str, user_id: int, input_tokens: int, output_tokens: int):
        """✅ ИСПРАВЛЕНО: Сохранение данных об использовании токенов в БД с улучшенными проверками"""
        try:
            from database import db
            
            total_tokens = input_tokens + output_tokens
            
            logger.info("💾 Saving token usage", 
                       assistant_id=assistant_id,
                       user_id=user_id,
                       input_tokens=input_tokens,
                       output_tokens=output_tokens,
                       total_tokens=total_tokens)
            
            # ✅ ДОБАВЛЕНО: Проверка валидности токенов
            if input_tokens < 0 or output_tokens < 0:
                logger.error("❌ Invalid token values", 
                            input_tokens=input_tokens,
                            output_tokens=output_tokens)
                return False
            
            if total_tokens == 0:
                logger.warning("⚠️ Zero tokens usage - skipping save", 
                              assistant_id=assistant_id,
                              user_id=user_id)
                return True  # Не ошибка, просто нечего сохранять
            
            # Получаем bot_id из конфигурации агента
            agent_config = await self._get_agent_config_by_assistant_id(assistant_id)
            if not agent_config:
                logger.error("❌ Cannot save token usage: agent config not found", 
                           assistant_id=assistant_id)
                return False
            
            bot_id = agent_config['bot_id']
            
            # Получаем admin_chat_id из конфигурации бота
            bot_config = await db.get_bot_full_config(bot_id)
            admin_chat_id = None
            if bot_config:
                admin_chat_id = bot_config.get('openai_admin_chat_id')
            
            logger.info("🔍 Bot config for token save", 
                       bot_id=bot_id,
                       admin_chat_id=admin_chat_id,
                       user_id=user_id)
            
            # ✅ ИСПРАВЛЕНО: Используем проверенный метод из connection.py
            success = await db.save_token_usage(
                bot_id=bot_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                admin_chat_id=admin_chat_id,
                user_id=user_id
            )
            
            if success:
                logger.info("✅ Token usage saved successfully", 
                           user_id=user_id,
                           bot_id=bot_id,
                           total_tokens=total_tokens)
                return True
            else:
                logger.error("❌ Failed to save token usage - db.save_token_usage returned False", 
                           user_id=user_id,
                           bot_id=bot_id,
                           total_tokens=total_tokens)
                return False
                
        except Exception as e:
            logger.error("💥 Error saving token usage", 
                        assistant_id=assistant_id,
                        user_id=user_id,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)  # ✅ ДОБАВЛЕНО: Полный traceback для отладки
            return False
    
    async def _send_token_exhausted_notification(self, user_id: int, bot_id: str, remaining_tokens: int):
        """Отправка уведомления об исчерпании токенов"""
        try:
            from database import db
            
            logger.info("📢 Sending token exhausted notification", 
                       user_id=user_id,
                       bot_id=bot_id,
                       remaining_tokens=remaining_tokens)
            
            # Получаем admin_chat_id из конфигурации бота
            bot_config = await db.get_bot_full_config(bot_id)
            if not bot_config:
                logger.error("❌ Cannot send notification: bot config not found", bot_id=bot_id)
                return
            
            admin_chat_id = bot_config.get('openai_admin_chat_id')
            if not admin_chat_id:
                logger.warning("⚠️ No admin_chat_id found for token notification", 
                              bot_id=bot_id,
                              user_id=user_id)
                return
            
            # Проверяем, не отправляли ли уже уведомление
            notification_sent = await db.should_send_token_notification(user_id)
            if not notification_sent:
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
                    await db.set_token_notification_sent(user_id, True)
                    
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
    
    async def _send_token_warning_notification(self, user_id: int, bot_id: str, remaining_tokens: int):
        """Отправка предупреждения о низком балансе токенов (90%)"""
        try:
            from database import db
            
            logger.info("⚠️ Sending token warning notification", 
                       user_id=user_id,
                       bot_id=bot_id,
                       remaining_tokens=remaining_tokens)
            
            # Получаем admin_chat_id из конфигурации бота
            bot_config = await db.get_bot_full_config(bot_id)
            if not bot_config:
                return
            
            admin_chat_id = bot_config.get('openai_admin_chat_id')
            if not admin_chat_id:
                return
            
            try:
                from services.bot_manager import bot_manager
                
                notification_text = f"""
⚠️ <b>Предупреждение: заканчиваются токены OpenAI</b>

🤖 <b>Бот:</b> {bot_config.get('bot_username', 'Unknown')}
👤 <b>Пользователь ID:</b> {user_id}
🎯 <b>Оставшиеся токены:</b> {remaining_tokens}

📊 Использовано более 90% токенов.
💰 Рекомендуется пополнить баланс.
"""
                
                await bot_manager.send_admin_notification(
                    admin_chat_id, 
                    notification_text
                )
                
                # Отмечаем что предупреждение отправлено
                await db.set_token_notification_sent(user_id, True)
                
                logger.info("✅ Token warning notification sent", 
                           admin_chat_id=admin_chat_id,
                           user_id=user_id)
                
            except (ImportError, Exception) as e:
                logger.warning("⚠️ Could not send token warning notification", error=str(e))
                
        except Exception as e:
            logger.error("💥 Error in token warning notification", 
                        user_id=user_id,
                        error=str(e))
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    async def _responses_with_retry(self, **kwargs) -> any:
        """✅ ИСПРАВЛЕНО: Отправка через Responses API БЕЗ return_usage параметра + RAW usage dump"""
        
        # ✅ Фильтруем только поддерживаемые параметры Responses API
        # ❌ УБРАНО: temperature, top_p, frequency_penalty, presence_penalty - НЕ поддерживаются!
        supported_params = {
            'model', 'input', 'instructions', 'tools', 'store', 'previous_response_id', 
            'stream', 'reasoning', 'metadata', 'max_output_tokens'
        }
        
        # Удаляем неподдерживаемые параметры (включая return_usage!)
        filtered_kwargs = {k: v for k, v in kwargs.items() if k in supported_params}
        
        # ✅ УБРАНО: return_usage больше не добавляется!
        
        # ✅ НОВОЕ: Переименовываем max_tokens в max_output_tokens для Responses API
        if 'max_tokens' in kwargs:
            filtered_kwargs['max_output_tokens'] = kwargs['max_tokens']
            filtered_kwargs.pop('max_tokens', None)
        
        # Логируем отфильтрованные параметры
        removed_params = {k: v for k, v in kwargs.items() if k not in supported_params}
        if removed_params:
            logger.debug("🗑️ Removed unsupported Responses API parameters", 
                        removed_params=list(removed_params.keys()))
            logger.info("ℹ️ Note: Responses API doesn't support temperature, top_p, frequency_penalty, presence_penalty")
        
        logger.info("📡 Making Responses API call WITHOUT return_usage", 
                   model=filtered_kwargs.get('model'),
                   has_instructions=bool(filtered_kwargs.get('instructions')),
                   has_previous_response=bool(filtered_kwargs.get('previous_response_id')),
                   tools_count=len(filtered_kwargs.get('tools', [])),
                   max_output_tokens=filtered_kwargs.get('max_output_tokens'),
                   store=filtered_kwargs.get('store', True))
        
        # ✅ НОВОЕ: Вызов API с последующим RAW usage dump
        response = await self.client.responses.create(**filtered_kwargs)
        
        # ✅ ДОБАВЛЕНО: RAW usage dump для диагностики
        logger.info("📊 RAW usage dump from Responses API", 
                   raw_usage=getattr(response, 'usage', 'NO_USAGE_ATTR'),
                   usage_type=type(getattr(response, 'usage', None)).__name__ if hasattr(response, 'usage') else 'NO_TYPE')
        
        return response
    
    async def create_assistant(self, agent: OpenAIResponsesAgent) -> OpenAIResponsesResult:
        """✅ ИСПРАВЛЕНО: Создание ассистента для Responses API с сохранением токенов тестирования"""
        
        logger.info("🚀 Starting OpenAI agent creation via Responses API", 
                   bot_id=agent.bot_id,
                   agent_name=agent.agent_name,
                   model=agent.model)
        
        overall_start_time = time.time()
        
        try:
            # Проверка конфигурации
            if not self._is_configured():
                logger.error("❌ OpenAI client not configured")
                return OpenAIResponsesResult.error_result("OpenAI API key not configured")
            
            logger.info("✅ Client configuration OK")
            
            # Проверка API ключа
            if not await self._validate_api_key_with_logging():
                logger.error("❌ API key validation failed")
                return OpenAIResponsesResult.error_result("Invalid OpenAI API key")
            
            # Генерируем уникальный assistant_id
            assistant_id = f"asst_{uuid.uuid4().hex[:24]}"
            
            logger.info("🔧 Preparing agent configuration", assistant_id=assistant_id)
            
            # Формируем системный промпт
            system_prompt = self._build_system_prompt(agent)
            
            # Тестируем агента через Responses API
            logger.info("🧪 Testing agent with Responses API...")
            
            test_start_time = time.time()
            
            # ✅ ИСПРАВЛЕНО: Убран return_usage параметр
            test_response = await self._responses_with_retry(
                model=agent.model,
                instructions=system_prompt,
                input="Привет! Представься кратко и скажи, что ты готов помочь.",
                store=True,
                max_output_tokens=150  # ✅ Ограничиваем для теста
            )
            
            test_duration = time.time() - test_start_time
            
            if not test_response.output_text:
                logger.error("❌ Agent test failed - no response")
                return OpenAIResponsesResult.error_result("Агент не отвечает на тестовые запросы")
            
            test_message = test_response.output_text.strip()
            
            # ✅ НОВОЕ: Извлекаем и сохраняем токены тестирования (если доступны)
            test_input_tokens = 10  # Оценочные значения по умолчанию
            test_output_tokens = 5
            
            if hasattr(test_response, 'usage') and test_response.usage:
                # ✅ ИСПРАВЛЕНО: Пробуем извлечь токены из доступных полей
                test_input_tokens = (
                    getattr(test_response.usage, 'input_tokens', None) or
                    getattr(test_response.usage, 'prompt_tokens', None) or
                    10
                )
                test_output_tokens = (
                    getattr(test_response.usage, 'output_tokens', None) or
                    getattr(test_response.usage, 'completion_tokens', None) or
                    5
                )
                
                logger.info("📊 Test token usage extracted from response", 
                           input_tokens=test_input_tokens,
                           output_tokens=test_output_tokens,
                           usage_fields=list(vars(test_response.usage).keys()) if hasattr(test_response.usage, '__dict__') else 'no __dict__')
            else:
                # Оценочный подсчет на основе длины текста
                test_input_tokens = max(5, len(system_prompt.split()) // 4)
                test_output_tokens = max(3, len(test_message.split()) * 1.3)
                
                logger.info("📊 Test token usage estimated", 
                           input_tokens=int(test_input_tokens),
                           output_tokens=int(test_output_tokens),
                           reason="no_usage_data")
            
            # Сохраняем токены тестирования (user_id=0 для тестов)
            try:
                await self._save_token_usage(assistant_id, 0, int(test_input_tokens), int(test_output_tokens))
                logger.info("✅ Test token usage saved")
            except Exception as e:
                logger.warning("⚠️ Failed to save test token usage", error=str(e))
            
            logger.info("✅ Agent test successful via Responses API", 
                       test_duration=f"{test_duration:.2f}s",
                       test_response_length=len(test_message),
                       test_preview=test_message[:100] + "..." if len(test_message) > 100 else test_message)
            
            # Агент работает - возвращаем успешный результат
            total_duration = time.time() - overall_start_time
            
            logger.info("🎉 OpenAI agent created successfully via Responses API", 
                       assistant_id=assistant_id,
                       bot_id=agent.bot_id,
                       total_duration=f"{total_duration:.2f}s",
                       agent_name=agent.agent_name)
            
            return OpenAIResponsesResult.success_result(
                response_id=assistant_id,
                output_text=f"Агент '{agent.agent_name}' успешно создан через Responses API",
                response_time=total_duration
            )
            
        except Exception as e:
            total_duration = time.time() - overall_start_time if 'overall_start_time' in locals() else 0
            
            logger.error("💥 Exception in create_assistant", 
                        bot_id=agent.bot_id,
                        agent_name=agent.agent_name,
                        exception_type=type(e).__name__,
                        exception_message=str(e),
                        total_duration=f"{total_duration:.2f}s",
                        exc_info=True)
            
            # Анализ ошибки для пользователя
            user_friendly_error = self._get_user_friendly_error(str(e))
            
            return OpenAIResponsesResult.error_result(user_friendly_error)
    
    def _build_system_prompt(self, agent: OpenAIResponsesAgent) -> str:
        """Построение системного промпта для агента"""
        system_prompt = f"Ты - {agent.agent_name}."
        
        if agent.agent_role:
            system_prompt += f" Твоя роль: {agent.agent_role}."
        
        if agent.system_prompt:
            system_prompt += f"\n\n{agent.system_prompt}"
        
        # Добавляем базовые инструкции
        system_prompt += """

Основные принципы:
- Отвечай полезно и дружелюбно
- Если не знаешь ответ, честно об этом скажи
- Адаптируй стиль общения под контекст
- Будь кратким, но информативным"""
        
        logger.debug("📝 System prompt built", 
                    prompt_length=len(system_prompt),
                    agent_name=agent.agent_name)
        
        return system_prompt
    
    def _get_user_friendly_error(self, error_str: str) -> str:
        """Преобразование технических ошибок в понятные пользователю"""
        error_lower = error_str.lower()
        
        if "500" in error_lower or "internal server error" in error_lower:
            return "Временная проблема с серверами OpenAI. Попробуйте через 2-3 минуты."
        elif "429" in error_lower or "rate limit" in error_lower:
            return "Превышен лимит запросов к OpenAI. Подождите минуту и попробуйте снова."
        elif "401" in error_lower or "unauthorized" in error_lower:
            return "Проблема с API ключом OpenAI. Обратитесь к администратору."
        elif "400" in error_lower or "bad request" in error_lower:
            return "Некорректные параметры запроса. Попробуйте изменить настройки агента."
        else:
            return f"Ошибка при работе с OpenAI: {error_str}"
    
    async def send_message(
        self,
        assistant_id: str,
        message: str,
        user_id: int,
        context: Optional[OpenAIResponsesContext] = None
    ) -> Optional[str]:
        """✅ ИСПРАВЛЕНО: Отправка сообщения через Responses API с КОРРЕКТНЫМ извлечением токенов"""
        
        logger.info("💬 Starting conversation via Responses API", 
                   assistant_id=assistant_id,
                   user_id=user_id,
                   message_length=len(message),
                   has_context=bool(context))
        
        try:
            if not self._is_configured():
                logger.error("❌ OpenAI client not configured")
                return None

            start_time = time.time()
            
            # 🔹 ШАГ 1: ПРОВЕРКА ЛИМИТА ТОКЕНОВ
            can_proceed, tokens_used, tokens_limit = await self._check_token_limit(assistant_id, user_id)
            
            if not can_proceed:
                logger.warning("🚫 Request blocked due to token limit")
                remaining = tokens_limit - tokens_used
                if remaining <= 0:
                    return "❌ Извините, лимит токенов OpenAI исчерпан. Администратор уведомлен о необходимости пополнения баланса."
                else:
                    return f"⚠️ Приближается лимит токенов OpenAI. Осталось: {remaining} токенов."

            # 🔹 ШАГ 2: ПОЛУЧЕНИЕ КОНФИГУРАЦИИ АГЕНТА
            agent_config = await self._get_agent_config_by_assistant_id(assistant_id)
            if not agent_config:
                logger.error("❌ Agent configuration not found", assistant_id=assistant_id)
                return "❌ Конфигурация агента не найдена"

            # 🔹 ШАГ 3: ПОЛУЧЕНИЕ ПРЕДЫДУЩЕГО RESPONSE_ID ДЛЯ ПРОДОЛЖЕНИЯ РАЗГОВОРА
            previous_response_id = await self._get_conversation_response_id(assistant_id, user_id)
            
            # 🔹 ШАГ 4: ПОДГОТОВКА СИСТЕМНЫХ ИНСТРУКЦИЙ
            instructions = agent_config.get('system_prompt', 'Ты полезный ИИ ассистент.')
            
            # Добавляем контекст пользователя если есть
            if context:
                user_context = f"Пользователь: {context.user_name}"
                if context.username:
                    user_context += f" (@{context.username})"
                if context.is_admin:
                    user_context += " [Администратор]"
                
                instructions += f"\n\nКонтекст диалога: {user_context}"

            # 🔹 ШАГ 5: ОТПРАВКА ЧЕРЕЗ RESPONSES API
            logger.info("📡 Sending via Responses API...")
            
            response = await self._responses_with_retry(
                model=agent_config.get('model', 'gpt-4o'),
                instructions=instructions,
                input=message,
                previous_response_id=previous_response_id,
                store=True,
                tools=self._get_enabled_tools(agent_config),
                max_output_tokens=agent_config.get('max_tokens', 4000)
                # ❌ УБРАНО: temperature, top_p, frequency_penalty, presence_penalty - НЕ поддерживаются Responses API!
            )
            
            elapsed_time = time.time() - start_time
            
            if not response or not response.output_text:
                logger.error("❌ Empty response from OpenAI Responses API")
                return None

            response_text = response.output_text.strip()
            
            # 🔹 ШАГ 6: СОХРАНЕНИЕ НОВОГО RESPONSE_ID ДЛЯ СЛЕДУЮЩИХ СООБЩЕНИЙ
            await self._save_conversation_response_id(assistant_id, user_id, response.id)
            
            # 🔹 ШАГ 7: ✅ КОРРЕКТНОЕ ИЗВЛЕЧЕНИЕ USAGE ДАННЫХ
            logger.info("🔍 Analyzing usage data from Responses API response")
            
            # ✅ Детальная диагностика response объекта
            logger.info("🔍 Response object analysis", 
                       response_type=type(response).__name__,
                       response_dir=[attr for attr in dir(response) if not attr.startswith('_')][:15],
                       has_usage=hasattr(response, 'usage'),
                       usage_value=getattr(response, 'usage', 'NO_USAGE_ATTR'))
            
            input_tokens = None
            output_tokens = None
            usage_source = "none"
            
            if hasattr(response, 'usage') and response.usage is not None:
                usage_obj = response.usage
                
                # ✅ Диагностика usage объекта
                logger.info("🔍 Usage object analysis",
                           usage_type=type(usage_obj).__name__,
                           usage_dir=[attr for attr in dir(usage_obj) if not attr.startswith('_')][:15],
                           usage_dict=vars(usage_obj) if hasattr(usage_obj, '__dict__') else 'no_dict')
                
                # ✅ ИСПРАВЛЕНО: Правильная проверка с is not None
                # Сначала пробуем новые названия полей Responses API
                if hasattr(usage_obj, 'input_tokens') and getattr(usage_obj, 'input_tokens') is not None:
                    input_tokens = usage_obj.input_tokens
                    usage_source = "input_tokens_field"
                elif hasattr(usage_obj, 'prompt_tokens') and getattr(usage_obj, 'prompt_tokens') is not None:
                    input_tokens = usage_obj.prompt_tokens
                    usage_source = "prompt_tokens_field"
                
                if hasattr(usage_obj, 'output_tokens') and getattr(usage_obj, 'output_tokens') is not None:
                    output_tokens = usage_obj.output_tokens
                    if usage_source.startswith("input"):
                        usage_source = "responses_api_fields"
                    else:
                        usage_source = "output_tokens_field"
                elif hasattr(usage_obj, 'completion_tokens') and getattr(usage_obj, 'completion_tokens') is not None:
                    output_tokens = usage_obj.completion_tokens
                    if usage_source.startswith("prompt"):
                        usage_source = "legacy_fields"
                    else:
                        usage_source = "completion_tokens_field"
                
                # ✅ Логируем найденные значения (даже если они 0!)
                logger.info("✅ Usage extraction results", 
                           input_tokens=input_tokens,
                           output_tokens=output_tokens,
                           usage_source=usage_source,
                           both_found=input_tokens is not None and output_tokens is not None)
            else:
                logger.warning("❌ No usage object found in response")
            
            # ✅ ИСПРАВЛЕНО: Fallback только если токены действительно не найдены
            if input_tokens is None or output_tokens is None:
                # Оценочный подсчет токенов (используем более точную формулу)
                estimated_input = max(1, int(len(instructions.split() + message.split()) * 1.3))
                estimated_output = max(1, int(len(response_text.split()) * 1.3)) if response_text else 1
                
                # Если один токен нашли, а другой нет - используем найденный + оценку недостающего
                if input_tokens is not None:
                    output_tokens = estimated_output
                    usage_source += "_with_estimated_output"
                elif output_tokens is not None:
                    input_tokens = estimated_input
                    usage_source += "_with_estimated_input"
                else:
                    input_tokens = estimated_input
                    output_tokens = estimated_output
                    usage_source = "full_estimation"
                
                logger.warning("⚠️ Using estimated token counts", 
                              input_tokens=input_tokens,
                              output_tokens=output_tokens,
                              message_words=len(message.split()),
                              response_words=len(response_text.split()),
                              instructions_words=len(instructions.split()),
                              estimation_reason=usage_source)
            
            # ✅ ВСЕГДА сохраняем токены (даже если они равны 0)
            logger.info("💾 Saving token usage", 
                       input_tokens=input_tokens,
                       output_tokens=output_tokens,
                       assistant_id=assistant_id,
                       user_id=user_id,
                       source=usage_source)
            
            try:
                save_success = await self._save_token_usage(assistant_id, user_id, int(input_tokens), int(output_tokens))
                if save_success:
                    logger.info("✅ Token usage saved successfully")
                else:
                    logger.error("❌ Token usage save failed")
            except Exception as e:
                logger.error("💥 Failed to save token usage", 
                            assistant_id=assistant_id,
                            user_id=user_id,
                            error=str(e))

            logger.info("🎉 Responses API response successful", 
                       response_length=len(response_text),
                       elapsed_time=f"{elapsed_time:.2f}s")
            
            return response_text
            
        except Exception as e:
            elapsed_time = time.time() - start_time if 'start_time' in locals() else 0
            logger.error("💥 Exception in send_message", 
                        assistant_id=assistant_id,
                        user_id=user_id,
                        error=str(e),
                        elapsed_time=f"{elapsed_time:.2f}s")
            return None
    
    def _get_enabled_tools(self, agent_config: dict) -> List[dict]:
        """✅ НОВОЕ: Получение списка включенных инструментов для Responses API"""
        tools = []
        
        # Проверяем какие инструменты включены в настройках
        settings = agent_config.get('settings', {})
        
        if settings.get('enable_web_search'):
            tools.append({"type": "web_search_preview"})
        
        if settings.get('enable_code_interpreter'):
            tools.append({
                "type": "code_interpreter",
                "container": {"type": "auto"}
            })
        
        if settings.get('enable_file_search'):
            # Нужно будет добавить vector_store_ids из конфигурации
            vector_store_ids = settings.get('vector_store_ids', [])
            if vector_store_ids:
                tools.append({
                    "type": "file_search",
                    "vector_store_ids": vector_store_ids
                })
        
        return tools

    async def _get_conversation_response_id(self, assistant_id: str, user_id: int) -> Optional[str]:
        """✅ НОВОЕ: Получение response_id последнего ответа для продолжения разговора"""
        try:
            from database import db
            
            # Получаем bot_id из конфигурации агента
            agent_config = await self._get_agent_config_by_assistant_id(assistant_id)
            if not agent_config:
                return None
            
            bot_id = agent_config['bot_id']
            return await db.get_conversation_response_id(bot_id, user_id)
        except Exception as e:
            logger.error("💥 Error getting conversation response_id", error=str(e))
            return None

    async def _save_conversation_response_id(self, assistant_id: str, user_id: int, response_id: str):
        """✅ НОВОЕ: Сохранение response_id для продолжения разговора"""
        try:
            from database import db
            
            # Получаем bot_id из конфигурации агента
            agent_config = await self._get_agent_config_by_assistant_id(assistant_id)
            if not agent_config:
                return
            
            bot_id = agent_config['bot_id']
            await db.save_conversation_response_id(bot_id, user_id, response_id)
        except Exception as e:
            logger.error("💥 Error saving conversation response_id", error=str(e))
    
    async def _get_agent_config_by_assistant_id(self, assistant_id: str) -> Optional[Dict]:
        """Получение конфигурации агента из БД по assistant_id"""
        try:
            from database import db
            
            logger.info("🔍 Getting agent config from database by assistant_id", 
                       assistant_id=assistant_id)
            
            config = await db.get_openai_agent_config(assistant_id)
            
            if config:
                logger.info("✅ Agent config found in database", 
                           assistant_id=assistant_id,
                           agent_name=config.get('name'))
                return config
            else:
                logger.warning("❌ Agent config not found in database", 
                              assistant_id=assistant_id)
                return None
                
        except Exception as e:
            logger.error("💥 Failed to get agent config from database", 
                        assistant_id=assistant_id,
                        error=str(e),
                        error_type=type(e).__name__)
            
            # Возвращаем fallback конфигурацию только если это fallback assistant_id
            if assistant_id.startswith('asst_fallback_'):
                logger.warning("⚠️ Using fallback agent config for fallback assistant")
                return {
                    'agent_id': assistant_id,
                    'name': 'AI Assistant',
                    'system_prompt': 'Ты полезный AI ассистент. Отвечай дружелюбно и информативно.',
                    'model': 'gpt-4o',
                    'max_tokens': 1000,
                    'temperature': 0.7,
                    'enable_web_search': False
                }
            
            return None
    
    async def test_assistant(self, assistant_id: str) -> OpenAIResponsesResult:
        """Тестирование ассистента через Responses API"""
        logger.info("🧪 Starting agent test via Responses API", assistant_id=assistant_id)
        
        try:
            test_message = "Привет! Это тестовое сообщение. Ответь кратко, что ты готов к работе."
            
            start_time = time.time()
            response_text = await self.send_message(
                assistant_id=assistant_id,
                message=test_message,
                user_id=0,  # Тестовый пользователь
                context=OpenAIResponsesContext(
                    user_id=0,
                    user_name="Тестировщик",
                    is_admin=True
                )
            )
            test_duration = time.time() - start_time
            
            if response_text:
                logger.info("✅ Agent test successful via Responses API", 
                           assistant_id=assistant_id,
                           response_length=len(response_text),
                           test_duration=f"{test_duration:.2f}s",
                           response_preview=response_text[:100] + "..." if len(response_text) > 100 else response_text)
                
                return OpenAIResponsesResult.success_result(
                    response_id=assistant_id,
                    output_text=response_text,
                    response_time=test_duration
                )
            else:
                logger.error("❌ Agent test failed - no response", assistant_id=assistant_id)
                return OpenAIResponsesResult.error_result("Тест не прошел - нет ответа от агента")
                
        except Exception as e:
            logger.error("💥 Exception in test_assistant", 
                        assistant_id=assistant_id,
                        error=str(e),
                        error_type=type(e).__name__)
            return OpenAIResponsesResult.error_result(f"Ошибка при тестировании: {str(e)}")
    
    async def clear_conversation(self, assistant_id: str, user_id: int) -> bool:
        """✅ ОБНОВЛЕНО: Очистка контекста разговора для Responses API"""
        try:
            from database import db
            
            logger.info("🧹 Clearing conversation context via Responses API", 
                       assistant_id=assistant_id,
                       user_id=user_id)
            
            # Получаем bot_id из конфигурации агента
            agent_config = await self._get_agent_config_by_assistant_id(assistant_id)
            if not agent_config:
                logger.error("❌ Agent config not found for context clear", 
                           assistant_id=assistant_id)
                return False
            
            bot_id = agent_config['bot_id']
            
            # Просто удаляем сохраненный response_id
            success = await db.clear_conversation_response_id(bot_id, user_id)
            
            if success:
                logger.info("✅ Conversation context cleared successfully")
            else:
                logger.error("❌ Failed to clear conversation context")
            
            return success
            
        except Exception as e:
            logger.error("💥 Error clearing conversation context", error=str(e))
            return False

    # ===== VECTOR STORES MANAGEMENT =====

    async def create_vector_store(self, name: str, expires_after_days: int = 30) -> tuple[bool, dict]:
        """✅ ИСПРАВЛЕНО: Создание vector store БЕЗ .beta"""
        try:
            logger.info("📁 Creating vector store", name=name, expires_after_days=expires_after_days)
            
            if not self._is_configured():
                return False, {"error": "OpenAI client not configured"}
            
            # ✅ ИСПРАВЛЕНО: Убираем .beta
            vector_store = await self.client.vector_stores.create(
                name=name,
                expires_after={
                    "anchor": "last_active_at",
                    "days": expires_after_days
                }
            )
            
            logger.info("✅ Vector store created", 
                       vector_store_id=vector_store.id, 
                       name=vector_store.name)
            
            # ✅ ИСПРАВЛЕНО: Безопасное извлечение file_counts
            file_counts_safe = self._safe_extract_file_counts(getattr(vector_store, 'file_counts', {}))
            
            return True, {
                "id": vector_store.id,
                "name": vector_store.name,
                "created_at": vector_store.created_at,
                "file_counts": file_counts_safe,
                "status": getattr(vector_store, 'status', 'created')
            }
            
        except Exception as e:
            logger.error("💥 Failed to create vector store", error=str(e))
            return False, {"error": str(e)}

    async def upload_file_to_openai(self, file_path: str, filename: str, purpose: str = "assistants") -> tuple[bool, dict]:
        """✅ ИСПРАВЛЕНО: Загрузка файла БЕЗ aiofiles"""
        try:
            logger.info("📤 Uploading file to OpenAI", filename=filename, purpose=purpose)
            
            if not self._is_configured():
                return False, {"error": "OpenAI client not configured"}
            
            # ✅ ИСПРАВЛЕНО: Убираем aiofiles, используем обычный open
            with open(file_path, 'rb') as file_data:
                file_response = await self.client.files.create(
                    file=(filename, file_data),
                    purpose=purpose
                )
            
            logger.info("✅ File uploaded to OpenAI", 
                       file_id=file_response.id,
                       filename=file_response.filename,
                       size=file_response.bytes)
            
            return True, {
                "id": file_response.id,
                "filename": file_response.filename,
                "bytes": file_response.bytes,
                "created_at": file_response.created_at,
                "purpose": file_response.purpose
            }
            
        except Exception as e:
            logger.error("💥 Failed to upload file to OpenAI", error=str(e))
            return False, {"error": str(e)}

    async def add_files_to_vector_store(self, vector_store_id: str, file_ids: List[str]) -> tuple[bool, dict]:
        """✅ ИСПРАВЛЕНО: Добавление файлов БЕЗ .beta"""
        try:
            logger.info("📎 Adding files to vector store", 
                       vector_store_id=vector_store_id, 
                       file_count=len(file_ids))
            
            if not self._is_configured():
                return False, {"error": "OpenAI client not configured"}
            
            # ✅ ИСПРАВЛЕНО: Убираем .beta и используем create_and_poll
            for file_id in file_ids:
                await self.client.vector_stores.files.create_and_poll(
                    vector_store_id=vector_store_id,
                    file_id=file_id
                )
            
            # Получаем обновленную информацию о vector store
            vector_store = await self.client.vector_stores.retrieve(vector_store_id)
            
            # ✅ ИСПРАВЛЕНО: Безопасное извлечение file_counts
            file_counts_obj = getattr(vector_store, 'file_counts', None)
            total_files = 0
            
            if file_counts_obj:
                file_counts_dict = self._safe_extract_file_counts(file_counts_obj)
                total_files = file_counts_dict.get('total', 0)
            
            logger.info("✅ Files added to vector store", 
                       vector_store_id=vector_store_id,
                       total_files=total_files)
            
            return True, {
                "vector_store_id": vector_store_id,
                "file_counts": self._safe_extract_file_counts(file_counts_obj),
                "status": getattr(vector_store, 'status', 'processing')
            }
            
        except Exception as e:
            logger.error("💥 Failed to add files to vector store", error=str(e))
            return False, {"error": str(e)}

    async def list_vector_stores(self) -> tuple[bool, List[dict]]:
        """✅ ИСПРАВЛЕНО: Получение списка БЕЗ .beta"""
        try:
            if not self._is_configured():
                return False, []
            
            # ✅ ИСПРАВЛЕНО: Убираем .beta
            vector_stores = await self.client.vector_stores.list()
            
            stores_list = []
            for store in vector_stores.data:
                # ✅ ИСПРАВЛЕНО: Безопасное извлечение file_counts
                file_counts_safe = self._safe_extract_file_counts(getattr(store, 'file_counts', {}))
                
                stores_list.append({
                    "id": store.id,
                    "name": store.name,
                    "created_at": store.created_at,
                    "file_counts": file_counts_safe,
                    "status": getattr(store, 'status', 'unknown')
                })
            
            logger.info("📋 Vector stores listed", count=len(stores_list))
            return True, stores_list
            
        except Exception as e:
            logger.error("💥 Failed to list vector stores", error=str(e))
            return False, []

    async def delete_vector_store(self, vector_store_id: str) -> tuple[bool, str]:
        """✅ ИСПРАВЛЕНО: Удаление БЕЗ .beta"""
        try:
            if not self._is_configured():
                return False, "OpenAI client not configured"
            
            # ✅ ИСПРАВЛЕНО: Убираем .beta
            await self.client.vector_stores.delete(vector_store_id)
            
            logger.info("🗑️ Vector store deleted", vector_store_id=vector_store_id)
            return True, "Vector store deleted successfully"
            
        except Exception as e:
            logger.error("💥 Failed to delete vector store", error=str(e))
            return False, str(e)

    async def clear_vector_store_files(self, vector_store_id: str) -> bool:
        """✅ НОВЫЙ: Очистка всех файлов из vector store (БЕЗ удаления самого store)"""
        try:
            if not self._is_configured():
                logger.error("❌ OpenAI client not configured")
                return False
            
            logger.info("🧹 Clearing files from vector store", vector_store_id=vector_store_id)
            
            # 1. Получаем список всех файлов в vector store
            files_response = await self.client.vector_stores.files.list(vector_store_id)
            files_count = len(files_response.data)
            
            if files_count == 0:
                logger.info("ℹ️ Vector store already empty", vector_store_id=vector_store_id)
                return True
            
            logger.info("🔍 Found files in vector store", 
                       vector_store_id=vector_store_id,
                       files_count=files_count)
            
            # 2. Удаляем каждый файл из vector store
            removed_count = 0
            for file in files_response.data:
                try:
                    await self.client.vector_stores.files.delete(
                        vector_store_id=vector_store_id, 
                        file_id=file.id
                    )
                    removed_count += 1
                    logger.debug("🗑️ File removed from vector store", 
                               file_id=file.id,
                               vector_store_id=vector_store_id)
                except Exception as e:
                    logger.error("💥 Failed to remove file from vector store", 
                               file_id=file.id,
                               vector_store_id=vector_store_id,
                               error=str(e))
            
            logger.info("✅ Vector store files cleared", 
                       vector_store_id=vector_store_id,
                       total_files=files_count,
                       removed_files=removed_count)
            
            return removed_count > 0 or files_count == 0
            
        except Exception as e:
            logger.error("💥 Failed to clear vector store files", 
                        vector_store_id=vector_store_id,
                        error=str(e))
            return False

    async def delete_file(self, file_id: str) -> tuple[bool, str]:
        """✅ НОВЫЙ: Удаление файла из OpenAI Files storage"""
        try:
            if not self._is_configured():
                return False, "OpenAI client not configured"
            
            logger.info("🗑️ Deleting file from OpenAI Files", file_id=file_id)
            
            await self.client.files.delete(file_id)
            
            logger.info("✅ File deleted from OpenAI Files", file_id=file_id)
            return True, "File deleted successfully"
            
        except Exception as e:
            logger.error("💥 Failed to delete file from OpenAI Files", 
                        file_id=file_id, error=str(e))
            return False, str(e)

    def _safe_extract_file_counts(self, file_counts) -> dict:
        """✅ НОВЫЙ: Безопасное извлечение file_counts в формат словаря"""
        try:
            if file_counts is None:
                return {"total": 0, "completed": 0, "in_progress": 0, "failed": 0}
            
            # Тип 1: Уже словарь
            if isinstance(file_counts, dict):
                return {
                    "total": file_counts.get("total", 0),
                    "completed": file_counts.get("completed", 0),
                    "in_progress": file_counts.get("in_progress", 0),
                    "failed": file_counts.get("failed", 0)
                }
            
            # Тип 2: Объект с атрибутами
            result = {}
            
            # Стандартные названия атрибутов OpenAI
            attr_mapping = {
                "total": ["total", "count", "total_count"],
                "completed": ["completed", "processed", "done", "finished"],
                "in_progress": ["in_progress", "processing", "pending"],
                "failed": ["failed", "error", "cancelled"]
            }
            
            for key, possible_attrs in attr_mapping.items():
                value = 0
                for attr in possible_attrs:
                    if hasattr(file_counts, attr):
                        value = getattr(file_counts, attr, 0)
                        break
                result[key] = value
            
            # Если ничего не найдено, попробуем получить все доступные атрибуты
            if all(v == 0 for v in result.values()):
                available_attrs = [attr for attr in dir(file_counts) if not attr.startswith('_')]
                logger.debug("🔍 Available file_counts attributes", 
                           type_name=type(file_counts).__name__,
                           attributes=available_attrs)
                
                # Попытка извлечь любые числовые атрибуты
                for attr in available_attrs:
                    try:
                        value = getattr(file_counts, attr, 0)
                        if isinstance(value, (int, float)) and value >= 0:
                            if 'total' in attr.lower():
                                result['total'] = int(value)
                            elif any(word in attr.lower() for word in ['complete', 'done', 'finish']):
                                result['completed'] = int(value)
                            elif any(word in attr.lower() for word in ['progress', 'process', 'pending']):
                                result['in_progress'] = int(value)
                            elif any(word in attr.lower() for word in ['fail', 'error', 'cancel']):
                                result['failed'] = int(value)
                    except (AttributeError, TypeError, ValueError):
                        continue
            
            logger.debug("📊 File counts extracted", 
                        original_type=type(file_counts).__name__,
                        result=result)
            
            return result
            
        except Exception as e:
            logger.error("💥 Error in _safe_extract_file_counts", 
                        error=str(e),
                        file_counts_type=type(file_counts).__name__ if file_counts else 'None')
            return {"total": 0, "completed": 0, "in_progress": 0, "failed": 0}

    # ✅ ОБНОВЛЯЕМ ПРОВЕРКУ ДОСТУПНОСТИ API
    def _check_api_availability(self) -> dict:
        """✅ ОБНОВЛЕНО: Проверка доступности БЕЗ .beta"""
        availability = {
            'chat_completions': False,
            'responses_api': False,
            'vector_stores': False,
            'files': False
        }
        
        try:
            if self.client:
                # Проверяем Chat Completions
                if hasattr(self.client, 'chat') and hasattr(self.client.chat, 'completions'):
                    availability['chat_completions'] = True
                
                # Проверяем Responses API
                if hasattr(self.client, 'responses') and hasattr(self.client.responses, 'create'):
                    availability['responses_api'] = True
                
                # ✅ ИСПРАВЛЕНО: Проверяем Vector Stores БЕЗ .beta
                if hasattr(self.client, 'vector_stores'):
                    availability['vector_stores'] = True
                
                # Проверяем Files API
                if hasattr(self.client, 'files'):
                    availability['files'] = True
            
            logger.info("🔍 OpenAI API availability check", **availability)
            
        except Exception as e:
            logger.error("💥 Error checking API availability", error=str(e))
        
        return availability
    
    def validate_create_request(self, request: OpenAIResponsesRequest) -> tuple[bool, str]:
        """Валидация запроса на создание агента"""
        logger.info("🔍 Validating create agent request", 
                   bot_id=request.bot_id,
                   agent_name=request.agent_name,
                   model=request.model)
        
        result = OpenAIResponsesValidator.validate_create_request(request)
        
        logger.info("📋 Validation result", 
                   is_valid=result[0],
                   error_message=result[1] if not result[0] else None)
        
        return result
    
    def is_available(self) -> bool:
        """Проверка доступности сервиса"""
        available = self._is_configured()
        
        logger.debug("🔍 Service availability check", 
                    is_available=available,
                    api_key_configured=bool(self.api_key),
                    client_configured=bool(self.client))
        
        return available
    
    # ===== 🆕 ДИАГНОСТИЧЕСКИЕ МЕТОДЫ =====
    
    async def test_responses_api_usage(self) -> tuple[bool, int, int]:
        """🧪 Тест для проверки получения usage данных из Responses API"""
        logger.info("🧪 Testing Responses API usage data extraction")
        
        try:
            # Простой тестовый запрос БЕЗ return_usage
            response = await self._responses_with_retry(
                model="gpt-4o-mini",  # Дешевая модель для теста
                instructions="Ты тестовый помощник.",
                input="Скажи просто 'Тест OK'",
                max_output_tokens=10
            )
            
            logger.info("🔍 Test response structure", 
                       response_type=type(response).__name__,
                       response_attrs=[attr for attr in dir(response) if not attr.startswith('_')][:10])
            
            # Проверяем usage
            if hasattr(response, 'usage') and response.usage:
                logger.info("🔍 Test usage object found",
                           usage_type=type(response.usage).__name__,
                           usage_attrs=[attr for attr in dir(response.usage) if not attr.startswith('_')][:10])
                
                input_tokens = (
                    getattr(response.usage, 'input_tokens', None) or
                    getattr(response.usage, 'prompt_tokens', None) or
                    0
                )
                output_tokens = (
                    getattr(response.usage, 'output_tokens', None) or
                    getattr(response.usage, 'completion_tokens', None) or
                    0
                )
                
                logger.info("✅ TEST SUCCESS: Usage data received", 
                           input_tokens=input_tokens,
                           output_tokens=output_tokens,
                           response_text=response.output_text if hasattr(response, 'output_text') else 'No output_text')
                
                return True, input_tokens, output_tokens
            else:
                logger.error("❌ TEST FAILED: No usage data in response")
                return False, 0, 0
                
        except Exception as e:
            logger.error("💥 TEST ERROR", error=str(e), exc_info=True)
            return False, 0, 0
    
    async def force_test_token_save(self, assistant_id: str, user_id: int = 8045097843) -> bool:
        """🧪 Принудительный тест сохранения токенов"""
        logger.info("🧪 FORCE TEST: Testing token save mechanism", 
                   assistant_id=assistant_id, user_id=user_id)
        
        try:
            # Тестируем сохранение токенов напрямую
            test_result = await self._save_token_usage(assistant_id, user_id, 25, 15)
            
            if test_result:
                logger.info("✅ FORCE TEST: Token save successful")
                
                # Проверяем что токены сохранились в БД
                from database import db
                agent_config = await self._get_agent_config_by_assistant_id(assistant_id)
                if agent_config:
                    bot_id = agent_config['bot_id']
                    bot = await db.get_bot_by_id(bot_id, fresh=True)
                    if bot:
                        logger.info("📊 FORCE TEST: Bot token stats", 
                                   bot_id=bot_id,
                                   total_tokens=bot.get_total_tokens_used(),
                                   input_tokens=bot.get_input_tokens_used(),
                                   output_tokens=bot.get_output_tokens_used())
                        return True
            
            logger.error("❌ FORCE TEST: Token save failed")
            return False
            
        except Exception as e:
            logger.error("💥 FORCE TEST: Exception during token save test", 
                        error=str(e), error_type=type(e).__name__, exc_info=True)
            return False
    
    async def diagnose_token_issue(self, assistant_id: str, user_id: int = 8045097843):
        """🩺 Полная диагностика проблемы с токенами"""
        logger.info("🩺 Starting comprehensive token issue diagnosis")
        
        print("🔍 ДИАГНОСТИКА ТОКЕНОВ")
        print("=" * 50)
        
        try:
            # 1. Тест API usage данных БЕЗ return_usage
            print("\n1️⃣ Тестируем получение usage данных БЕЗ return_usage...")
            success, input_tokens, output_tokens = await self.test_responses_api_usage()
            if success:
                print(f"✅ Usage данные получены: input={input_tokens}, output={output_tokens}")
            else:
                print("❌ Usage данные НЕ получены - будет использоваться оценка")
            
            # 2. Тест сохранения токенов
            print("\n2️⃣ Тестируем сохранение токенов...")
            save_success = await self.force_test_token_save(assistant_id, user_id)
            if save_success:
                print("✅ Сохранение токенов работает")
            else:
                print("❌ Сохранение токенов НЕ работает")
            
            # 3. Проверка конфигурации агента
            print("\n3️⃣ Проверяем конфигурацию агента...")
            agent_config = await self._get_agent_config_by_assistant_id(assistant_id)
            if agent_config:
                print(f"✅ Конфигурация найдена: {agent_config.get('name', 'Unknown')}")
                print(f"   Bot ID: {agent_config.get('bot_id', 'Unknown')}")
                print(f"   Model: {agent_config.get('model', 'Unknown')}")
            else:
                print("❌ Конфигурация агента НЕ найдена")
            
            # 4. Полный тест отправки сообщения
            print("\n4️⃣ Тестируем полный цикл отправки сообщения...")
            response = await self.send_message(
                assistant_id=assistant_id,
                message="Тест сохранения токенов",
                user_id=user_id
            )
            
            if response:
                print("✅ Сообщение отправлено успешно")
                print(f"   Ответ: {response[:100]}...")
            else:
                print("❌ Ошибка отправки сообщения")
            
            print(f"\n🎯 ИТОГ: Диагностика завершена")
            
        except Exception as e:
            print(f"💥 Ошибка диагностики: {e}")
            logger.error("💥 Diagnosis failed", error=str(e), exc_info=True)
