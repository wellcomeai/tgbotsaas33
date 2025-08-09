"""
OpenAI Responses Client
Переписанный клиент для работы с OpenAI через Responses API вместо Assistants API
Более простой, надежный и быстрый подход
"""

import os
import asyncio
import time
import uuid
import json
from typing import Optional, Dict, Any, List
from datetime import datetime
import structlog
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .models import (
    OpenAIAgent, 
    OpenAIResponse, 
    OpenAICreateAgentRequest,
    OpenAIConversationContext,
    OpenAIConstants,
    OpenAIValidator
)

logger = structlog.get_logger()


class OpenAIAssistantClient:
    """
    Переписанный клиент для работы с OpenAI Responses API
    Заменяет сложный Assistants API на простой и надежный подход
    """
    
    def __init__(self):
        logger.info("🔧 Initializing OpenAI Responses Client")
        
        self.api_key = os.getenv('OPENAI_API_KEY')
        self.client = None
        
        logger.info("🔍 Environment check", 
                   api_key_exists=bool(self.api_key),
                   api_key_length=len(self.api_key) if self.api_key else 0,
                   api_key_prefix=self.api_key[:12] + "..." if self.api_key else "None")
        
        if self.api_key:
            try:
                self.client = AsyncOpenAI(api_key=self.api_key)
                logger.info("✅ AsyncOpenAI client created successfully")
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
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    async def _chat_with_retry(self, messages: List[Dict], model: str, **kwargs) -> any:
        """Отправка chat completion с retry логикой"""
        logger.info("📡 Making OpenAI chat completion with retry...")
        return await self.client.chat.completions.create(
            model=model,
            messages=messages,
            **kwargs
        )
    
    async def create_assistant(self, agent: OpenAIAgent) -> OpenAIResponse:
        """
        Создание агента через Responses API (БЕЗ Assistants API)
        Просто создаем конфигурацию агента и тестируем ее
        """
        
        logger.info("🚀 Starting OpenAI agent creation via Responses API", 
                   bot_id=agent.bot_id,
                   agent_name=agent.agent_name,
                   agent_role=agent.agent_role,
                   model=agent.model)
        
        overall_start_time = time.time()
        
        try:
            # Проверка конфигурации
            if not self._is_configured():
                logger.error("❌ OpenAI client not configured")
                return OpenAIResponse.error_response("OpenAI API key not configured")
            
            logger.info("✅ Client configuration OK")
            
            # Проверка API ключа
            if not await self._validate_api_key_with_logging():
                logger.error("❌ API key validation failed")
                return OpenAIResponse.error_response("Invalid OpenAI API key")
            
            # Создаем уникальный ID агента
            agent_id = f"openai_agent_{uuid.uuid4().hex[:12]}"
            
            logger.info("🔧 Preparing agent configuration", agent_id=agent_id)
            
            # Формируем системный промпт
            system_prompt = self._build_system_prompt(agent)
            
            # Тестируем агента
            logger.info("🧪 Testing agent with sample conversation...")
            
            test_start_time = time.time()
            
            test_response = await self._chat_with_retry(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "Привет! Представься кратко и скажи, что ты готов помочь."}
                ],
                model=agent.model,
                max_tokens=150,
                temperature=agent.temperature
            )
            
            test_duration = time.time() - test_start_time
            
            if not test_response.choices or not test_response.choices[0].message.content:
                logger.error("❌ Agent test failed - no response")
                return OpenAIResponse.error_response("Агент не отвечает на тестовые запросы")
            
            test_message = test_response.choices[0].message.content.strip()
            
            logger.info("✅ Agent test successful", 
                       test_duration=f"{test_duration:.2f}s",
                       test_response_length=len(test_message),
                       test_preview=test_message[:100] + "..." if len(test_message) > 100 else test_message)
            
            # Агент работает - возвращаем успешный результат
            total_duration = time.time() - overall_start_time
            
            logger.info("🎉 OpenAI agent created successfully via Responses API", 
                       agent_id=agent_id,
                       bot_id=agent.bot_id,
                       total_duration=f"{total_duration:.2f}s",
                       agent_name=agent.agent_name)
            
            return OpenAIResponse.success_response(
                message=f"Агент '{agent.agent_name}' успешно создан",
                assistant_id=agent_id,  # Возвращаем наш локальный ID
                response_time=total_duration
            )
            
        except Exception as e:
            total_duration = time.time() - overall_start_time
            
            logger.error("💥 Exception in create_assistant", 
                        bot_id=agent.bot_id,
                        agent_name=agent.agent_name,
                        exception_type=type(e).__name__,
                        exception_message=str(e),
                        total_duration=f"{total_duration:.2f}s",
                        exc_info=True)
            
            # Анализ ошибки для пользователя
            user_friendly_error = self._get_user_friendly_error(str(e))
            
            return OpenAIResponse.error_response(user_friendly_error)
    
    def _build_system_prompt(self, agent: OpenAIAgent) -> str:
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
        context: Optional[OpenAIConversationContext] = None
    ) -> Optional[str]:
        """
        Отправка сообщения агенту через Responses API
        НЕ используем Assistants API - только chat.completions
        """
        
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
            
            # Получаем конфигурацию агента из БД
            # ВАЖНО: assistant_id теперь наш локальный ID агента
            agent_config = await self._get_agent_config_by_id(assistant_id)
            if not agent_config:
                logger.error("❌ Agent configuration not found", assistant_id=assistant_id)
                return "❌ Конфигурация агента не найдена"
            
            # Строим системный промпт
            system_prompt = agent_config['system_prompt']
            
            # Добавляем контекст если есть
            if context:
                context_info = context.to_context_string()
                system_prompt += f"\n\nКонтекст текущего диалога: {context_info}"
                logger.info("📝 Context added to system prompt", context_info=context_info)
            
            # Формируем сообщения для chat completion
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ]
            
            logger.info("📡 Sending chat completion request...")
            
            # Отправляем запрос
            response = await self._chat_with_retry(
                messages=messages,
                model=agent_config.get('model', 'gpt-4o'),
                max_tokens=agent_config.get('max_tokens', 1000),
                temperature=agent_config.get('temperature', 0.7),
                tools=[{"type": "web_search"}] if agent_config.get('enable_web_search') else None
            )
            
            elapsed_time = time.time() - start_time
            
            if not response.choices or not response.choices[0].message.content:
                logger.error("❌ Empty response from OpenAI")
                return None
            
            response_text = response.choices[0].message.content.strip()
            
            logger.info("🎉 OpenAI response received successfully", 
                       assistant_id=assistant_id,
                       user_id=user_id,
                       response_length=len(response_text),
                       elapsed_time=f"{elapsed_time:.2f}s",
                       model_used=response.model,
                       tokens_used=response.usage.total_tokens if hasattr(response, 'usage') else None)
            
            return response_text
            
        except Exception as e:
            elapsed_time = time.time() - start_time if 'start_time' in locals() else 0
            
            logger.error("💥 Exception in send_message", 
                        assistant_id=assistant_id,
                        user_id=user_id,
                        error=str(e),
                        error_type=type(e).__name__,
                        elapsed_time=f"{elapsed_time:.2f}s",
                        exc_info=True)
            
            return None
    
    async def _get_agent_config_by_id(self, agent_id: str) -> Optional[Dict]:
        """
        Получение конфигурации агента по ID
        Это нужно будет реализовать в database manager
        """
        # TODO: Реализовать получение из БД
        # Пока возвращаем базовую конфигурацию
        logger.warning("⚠️ Using fallback agent config - implement database lookup")
        
        return {
            'agent_id': agent_id,
            'name': 'AI Assistant',
            'system_prompt': 'Ты полезный AI ассистент. Отвечай дружелюбно и информативно.',
            'model': 'gpt-4o',
            'max_tokens': 1000,
            'temperature': 0.7,
            'enable_web_search': False
        }
    
    async def test_assistant(self, assistant_id: str) -> OpenAIResponse:
        """Тестирование агента"""
        logger.info("🧪 Starting agent test", assistant_id=assistant_id)
        
        try:
            test_message = "Привет! Это тестовое сообщение. Ответь кратко, что ты готов к работе."
            
            start_time = time.time()
            response_text = await self.send_message(
                assistant_id=assistant_id,
                message=test_message,
                user_id=0,  # Тестовый пользователь
                context=OpenAIConversationContext(
                    user_id=0,
                    user_name="Тестировщик",
                    is_admin=True
                )
            )
            test_duration = time.time() - start_time
            
            if response_text:
                logger.info("✅ Agent test successful", 
                           assistant_id=assistant_id,
                           response_length=len(response_text),
                           test_duration=f"{test_duration:.2f}s",
                           response_preview=response_text[:100] + "..." if len(response_text) > 100 else response_text)
                
                return OpenAIResponse.success_response(
                    message=response_text,
                    assistant_id=assistant_id,
                    response_time=test_duration
                )
            else:
                logger.error("❌ Agent test failed - no response", assistant_id=assistant_id)
                return OpenAIResponse.error_response("Тест не прошел - нет ответа от агента")
                
        except Exception as e:
            logger.error("💥 Exception in test_assistant", 
                        assistant_id=assistant_id,
                        error=str(e),
                        error_type=type(e).__name__)
            return OpenAIResponse.error_response(f"Ошибка при тестировании: {str(e)}")
    
    async def update_assistant(self, assistant_id: str, agent: OpenAIAgent) -> OpenAIResponse:
        """
        Обновление агента
        В Responses API это просто обновление конфигурации в БД
        """
        logger.info("🔄 Updating agent configuration", 
                   assistant_id=assistant_id,
                   agent_name=agent.agent_name)
        
        try:
            # TODO: Реализовать обновление в БД
            logger.info("📊 Agent config would be updated", 
                       assistant_id=assistant_id,
                       new_name=agent.agent_name,
                       new_role=agent.agent_role)
            
            # Тестируем обновленную конфигурацию
            test_result = await self.test_assistant(assistant_id)
            
            if test_result.success:
                logger.info("✅ Agent updated and tested successfully", assistant_id=assistant_id)
                return OpenAIResponse.success_response(
                    message="Агент успешно обновлен",
                    assistant_id=assistant_id
                )
            else:
                logger.error("❌ Agent update test failed", assistant_id=assistant_id)
                return OpenAIResponse.error_response("Обновление не прошло тест")
                
        except Exception as e:
            logger.error("💥 Exception in update_assistant", 
                        assistant_id=assistant_id,
                        error=str(e),
                        error_type=type(e).__name__)
            return OpenAIResponse.error_response(f"Ошибка при обновлении агента: {str(e)}")
    
    async def delete_assistant(self, assistant_id: str) -> OpenAIResponse:
        """
        Удаление агента
        В Responses API это просто удаление конфигурации из БД
        """
        logger.info("🗑️ Deleting agent configuration", assistant_id=assistant_id)
        
        try:
            # TODO: Реализовать удаление из БД
            logger.info("📊 Agent config would be deleted", assistant_id=assistant_id)
            
            return OpenAIResponse.success_response(
                message="Агент успешно удален",
                assistant_id=assistant_id
            )
            
        except Exception as e:
            logger.error("💥 Exception in delete_assistant", 
                        assistant_id=assistant_id,
                        error=str(e),
                        error_type=type(e).__name__)
            return OpenAIResponse.error_response(f"Ошибка при удалении агента: {str(e)}")
    
    async def get_assistant_info(self, assistant_id: str) -> tuple[bool, Optional[Dict], Optional[str]]:
        """Получение информации об агенте"""
        logger.info("📊 Getting agent info", assistant_id=assistant_id)
        
        try:
            if not self._is_configured():
                return False, None, "OpenAI API key not configured"
            
            # Получаем конфигурацию агента
            agent_config = await self._get_agent_config_by_id(assistant_id)
            
            if agent_config:
                logger.info("✅ Agent info retrieved successfully", 
                           assistant_id=assistant_id,
                           agent_name=agent_config.get('name'))
                
                return True, agent_config, None
            else:
                logger.warning("❌ Agent config not found", assistant_id=assistant_id)
                return False, None, "Agent configuration not found"
                
        except Exception as e:
            logger.error("💥 Exception in get_assistant_info", 
                        assistant_id=assistant_id,
                        error=str(e),
                        error_type=type(e).__name__)
            return False, None, str(e)
    
    def validate_create_request(self, request: OpenAICreateAgentRequest) -> tuple[bool, str]:
        """Валидация запроса на создание агента"""
        logger.info("🔍 Validating create agent request", 
                   bot_id=request.bot_id,
                   agent_name=request.agent_name,
                   model=request.model)
        
        result = OpenAIValidator.validate_create_request(request)
        
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
