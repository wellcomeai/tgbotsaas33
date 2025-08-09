"""
OpenAI Assistant Client
Основной клиент для работы с OpenAI Assistants API с детальным логированием и retry логикой
"""

import os
import asyncio
import time
import random
from typing import Optional, Dict, Any, List
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
    """Клиент для работы с OpenAI Assistants API с полным логированием и retry логикой"""
    
    def __init__(self):
        logger.info("🔧 Initializing OpenAIAssistantClient")
        
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
        """Проверка конфигурации клиента с логированием"""
        configured = bool(self.api_key and self.client)
        
        logger.debug("🔧 Configuration check", 
                    api_key_exists=bool(self.api_key),
                    api_key_length=len(self.api_key) if self.api_key else 0,
                    client_exists=bool(self.client),
                    is_configured=configured)
        
        return configured
    
    async def _validate_api_key_with_logging(self):
        """Проверка API ключа с логированием"""
        try:
            logger.info("🔍 Validating OpenAI API key...")
            
            start_time = time.time()
            models = await self.client.models.list()
            validation_duration = time.time() - start_time
            
            available_models = [m.id for m in models.data[:5]]  # Первые 5 моделей
            
            logger.info("✅ API key validation successful", 
                       models_count=len(models.data),
                       validation_duration=f"{validation_duration:.2f}s",
                       available_models=available_models)
            
            return True
            
        except Exception as e:
            logger.error("❌ API key validation failed", 
                        error=str(e),
                        error_type=type(e).__name__)
            
            # Анализ типа ошибки API ключа
            error_str = str(e).lower()
            if "401" in error_str or "unauthorized" in error_str:
                logger.error("🔑 Invalid API key detected")
            elif "403" in error_str or "forbidden" in error_str:
                logger.error("🚫 API key access forbidden")
            elif "429" in error_str:
                logger.error("⏱️ Rate limit reached during validation")
            
            return False
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    async def _create_assistant_with_retry(self, config: dict) -> any:
        """Создание ассистента с retry логикой"""
        logger.info("📡 Making OpenAI API call with retry logic...")
        return await self.client.beta.assistants.create(**config)
    
    async def _fallback_to_chat_completion(self, agent: OpenAIAgent) -> Optional[OpenAIResponse]:
        """Fallback на Chat Completions API когда Assistants API недоступен"""
        try:
            logger.info("🔄 Using Chat Completions fallback")
            
            # Создаем простой запрос для проверки что Chat API работает
            test_response = await self.client.chat.completions.create(
                model=agent.model,
                messages=[
                    {"role": "system", "content": agent.system_prompt or f"Ты - {agent.agent_role}. Твое имя {agent.agent_name}."},
                    {"role": "user", "content": "Привет! Ответь кратко что ты готов к работе."}
                ],
                max_tokens=100
            )
            
            if test_response.choices and test_response.choices[0].message:
                logger.info("✅ Chat Completions fallback successful")
                
                # Создаем "виртуального" ассистента
                virtual_assistant_id = f"chat_{int(time.time())}"
                
                return OpenAIResponse.success_response(
                    message=f"Агент создан через Chat API (fallback). Assistants API временно недоступен.",
                    assistant_id=virtual_assistant_id
                )
            
        except Exception as e:
            logger.error("❌ Chat Completions fallback failed", error=str(e))
        
        return None
    
    async def create_assistant(self, agent: OpenAIAgent) -> OpenAIResponse:
        """Создание ассистента в OpenAI с retry логикой и детальным логированием"""
        
        # 🔍 ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ - НАЧАЛО
        logger.info("🚀 Starting OpenAI assistant creation with retry", 
                   bot_id=agent.bot_id,
                   agent_name=agent.agent_name,
                   agent_role=agent.agent_role,
                   model=agent.model,
                   temperature=agent.temperature,
                   max_tokens=agent.max_tokens,
                   context_window=agent.context_window,
                   is_active=agent.is_active,
                   api_key_configured=bool(self.api_key),
                   api_key_prefix=self.api_key[:12] + "..." if self.api_key else "None",
                   client_configured=bool(self.client))
        
        try:
            # Проверка конфигурации
            if not self._is_configured():
                logger.error("❌ OpenAI client not configured", 
                            api_key_exists=bool(self.api_key),
                            client_exists=bool(self.client))
                return OpenAIResponse.error_response("OpenAI API key not configured")
            
            logger.info("✅ Client configuration OK")
            
            # Проверка API ключа (опционально, для диагностики)
            logger.info("🔍 Testing API key validity...")
            if not await self._validate_api_key_with_logging():
                logger.error("❌ API key validation failed")
                return OpenAIResponse.error_response("Invalid OpenAI API key")
            
            # Подготовка конфигурации
            logger.info("🔧 Preparing assistant configuration...")
            config = agent.to_openai_config()
            
            logger.info("📋 Assistant config prepared", 
                       config_keys=list(config.keys()),
                       name=config.get('name'),
                       model=config.get('model'),
                       instructions_length=len(config.get('instructions', '')),
                       tools_count=len(config.get('tools', [])),
                       metadata_keys=list(config.get('metadata', {}).keys()),
                       full_config=config)  # Полная конфигурация для отладки
            
            # Проверка лимитов OpenAI
            instructions_length = len(config.get('instructions', ''))
            name_length = len(config.get('name', ''))
            
            logger.info("🔍 Validating OpenAI limits", 
                       instructions_length=instructions_length,
                       instructions_limit=256000,
                       name_length=name_length,
                       name_limit=256)
            
            if instructions_length > 256000:
                logger.error("❌ Instructions too long", 
                            length=instructions_length,
                            max_allowed=256000,
                            exceeded_by=instructions_length - 256000)
                return OpenAIResponse.error_response("Instructions too long (max 256k characters)")
            
            if name_length > 256:
                logger.error("❌ Name too long", 
                            length=name_length,
                            max_allowed=256,
                            exceeded_by=name_length - 256)
                return OpenAIResponse.error_response("Name too long (max 256 characters)")
            
            logger.info("✅ Config validation passed")
            
            # 🎯 ОСНОВНОЙ API ВЫЗОВ С RETRY ЛОГИКОЙ
            start_time = time.time()
            retry_attempt = 0
            
            while retry_attempt < 3:
                try:
                    logger.info("📡 API attempt", 
                               attempt=retry_attempt + 1,
                               max_attempts=3,
                               config=config)
                    
                    # Основной вызов с retry декоратором
                    assistant = await self._create_assistant_with_retry(config)
                    
                    api_call_duration = time.time() - start_time
                    
                    logger.info("🎉 OpenAI API call successful", 
                               assistant_id=assistant.id,
                               assistant_name=assistant.name,
                               assistant_model=assistant.model,
                               api_call_duration=f"{api_call_duration:.2f}s",
                               created_at=assistant.created_at,
                               object_type=assistant.object,
                               retry_attempt=retry_attempt + 1,
                               assistant_tools=len(assistant.tools) if hasattr(assistant, 'tools') else 0)
                    
                    # Логирование полного ответа для диагностики
                    logger.debug("📊 Full assistant response", 
                                full_response={
                                    'id': assistant.id,
                                    'name': assistant.name,
                                    'model': assistant.model,
                                    'instructions': assistant.instructions[:100] + "..." if len(assistant.instructions) > 100 else assistant.instructions,
                                    'tools': [tool.type if hasattr(tool, 'type') else str(tool) for tool in assistant.tools] if hasattr(assistant, 'tools') else [],
                                    'metadata': assistant.metadata,
                                    'created_at': assistant.created_at
                                })
                    
                    # Успешное завершение
                    total_duration = time.time() - start_time
                    logger.info("✨ Assistant creation completed successfully", 
                               assistant_id=assistant.id,
                               bot_id=agent.bot_id,
                               total_duration=f"{total_duration:.2f}s",
                               agent_name=agent.agent_name)
                    
                    return OpenAIResponse.success_response(
                        message="Ассистент успешно создан",
                        assistant_id=assistant.id,
                        response_time=total_duration
                    )
                    
                except Exception as api_error:
                    retry_attempt += 1
                    api_call_duration = time.time() - start_time
                    
                    # 🚨 ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ ОШИБОК API
                    logger.error("💥 OpenAI API call failed", 
                                retry_attempt=retry_attempt,
                                max_attempts=3,
                                error_type=type(api_error).__name__,
                                error_message=str(api_error),
                                api_call_duration=f"{api_call_duration:.2f}s",
                                config_sent=config,
                                full_error=repr(api_error))
                    
                    # Анализ типа ошибки
                    error_str = str(api_error).lower()
                    
                    if "500" in error_str or "internal server error" in error_str:
                        logger.error("🔥 Server Error (500) - OpenAI internal problem", 
                                   recommendation="Retry in a few minutes",
                                   status_check="https://status.openai.com/")
                        
                        if retry_attempt < 3:
                            wait_time = 2 ** retry_attempt + random.uniform(0, 1)
                            logger.info("🔄 Retrying after server error", 
                                       wait_time=f"{wait_time:.1f}s",
                                       attempt=retry_attempt + 1)
                            await asyncio.sleep(wait_time)
                            continue
                        
                    elif "401" in error_str or "unauthorized" in error_str:
                        logger.error("🔑 Authentication Error (401)", 
                                   api_key_prefix=self.api_key[:12] + "..." if self.api_key else "None",
                                   recommendation="Check API key validity",
                                   check_url="https://platform.openai.com/account/api-keys")
                        # Не retry для 401
                        break
                        
                    elif "429" in error_str or "rate limit" in error_str:
                        logger.error("⏱️ Rate Limit Error (429)", 
                                   recommendation="Wait and retry, check usage tier",
                                   check_url="https://platform.openai.com/account/billing/overview")
                        
                        if retry_attempt < 3:
                            wait_time = 5 * (2 ** retry_attempt)
                            logger.info("⏱️ Retrying after rate limit", 
                                       wait_time=f"{wait_time:.1f}s",
                                       attempt=retry_attempt + 1)
                            await asyncio.sleep(wait_time)
                            continue
                        
                    elif "400" in error_str or "bad request" in error_str:
                        logger.error("❌ Bad Request (400) - Invalid parameters", 
                                   config=config,
                                   recommendation="Check request parameters",
                                   possible_issues=["Invalid model name", "Too long instructions", "Invalid tools config"])
                        # Не retry для 400
                        break
                        
                    elif "404" in error_str or "not found" in error_str:
                        logger.error("🔍 Not Found (404)", 
                                   model=config.get('model'),
                                   recommendation="Check model availability",
                                   available_models_check="Use models.list() API")
                        # Не retry для 404
                        break
                        
                    elif "503" in error_str or "service unavailable" in error_str:
                        logger.error("🚫 Service Unavailable (503)",
                                   recommendation="OpenAI service temporarily down")
                        
                        if retry_attempt < 3:
                            wait_time = 3 * (2 ** retry_attempt)
                            logger.info("🔄 Retrying after service unavailable", 
                                       wait_time=f"{wait_time:.1f}s",
                                       attempt=retry_attempt + 1)
                            await asyncio.sleep(wait_time)
                            continue
                        
                    else:
                        logger.error("❓ Unknown API error", 
                                   error_details=repr(api_error),
                                   suggestion="Check OpenAI API documentation")
                        # Не retry для неизвестных ошибок
                        break
                    
                    # Дополнительная диагностика для HTTP ошибок
                    if hasattr(api_error, 'response'):
                        logger.error("📡 HTTP Response details",
                                   status_code=getattr(api_error.response, 'status_code', 'unknown'),
                                   headers=dict(getattr(api_error.response, 'headers', {})),
                                   response_text=getattr(api_error.response, 'text', 'no text')[:500])
                    
                    # Если все попытки исчерпаны
                    if retry_attempt >= 3:
                        logger.error("❌ All retry attempts exhausted")
                        
                        # Fallback на Chat Completions
                        logger.info("🔄 Attempting fallback to Chat Completions API")
                        fallback_result = await self._fallback_to_chat_completion(agent)
                        if fallback_result:
                            return fallback_result
                        
                        # Возвращаем детальную ошибку
                        return OpenAIResponse.error_response(f"OpenAI API Error after 3 attempts: {str(api_error)}")
            
            # Не должно сюда попасть, но на всякий случай
            return OpenAIResponse.error_response("Unexpected error in retry loop")
            
        except Exception as e:
            # 🚨 ОБЩАЯ ОБРАБОТКА ОШИБОК
            logger.error("💥 Exception in create_assistant", 
                        exception_type=type(e).__name__,
                        exception_message=str(e),
                        bot_id=agent.bot_id,
                        agent_name=agent.agent_name,
                        full_exception=repr(e),
                        exc_info=True)
            
            return OpenAIResponse.error_response(f"Ошибка при создании ассистента: {str(e)}")
    
    async def update_assistant(self, assistant_id: str, agent: OpenAIAgent) -> OpenAIResponse:
        """Обновление ассистента в OpenAI с логированием"""
        logger.info("🔄 Starting assistant update", 
                   assistant_id=assistant_id,
                   agent_name=agent.agent_name)
        
        try:
            if not self._is_configured():
                logger.error("❌ OpenAI client not configured for update")
                return OpenAIResponse.error_response("OpenAI API key not configured")
            
            config = agent.to_openai_config()
            
            logger.info("📡 Updating OpenAI assistant", 
                       assistant_id=assistant_id,
                       config=config)
            
            start_time = time.time()
            assistant = await self.client.beta.assistants.update(assistant_id, **config)
            duration = time.time() - start_time
            
            logger.info("✅ OpenAI assistant updated successfully", 
                       assistant_id=assistant_id,
                       duration=f"{duration:.2f}s")
            
            return OpenAIResponse.success_response(
                message="Ассистент успешно обновлен",
                assistant_id=assistant.id,
                response_time=duration
            )
            
        except Exception as e:
            logger.error("💥 Exception in update_assistant", 
                        assistant_id=assistant_id,
                        error=str(e),
                        error_type=type(e).__name__)
            return OpenAIResponse.error_response(f"Ошибка при обновлении ассистента: {str(e)}")
    
    async def delete_assistant(self, assistant_id: str) -> OpenAIResponse:
        """Удаление ассистента из OpenAI с логированием"""
        logger.info("🗑️ Starting assistant deletion", assistant_id=assistant_id)
        
        try:
            if not self._is_configured():
                logger.error("❌ OpenAI client not configured for deletion")
                return OpenAIResponse.error_response("OpenAI API key not configured")
            
            logger.info("📡 Deleting OpenAI assistant", assistant_id=assistant_id)
            
            start_time = time.time()
            await self.client.beta.assistants.delete(assistant_id)
            duration = time.time() - start_time
            
            logger.info("✅ OpenAI assistant deleted successfully", 
                       assistant_id=assistant_id,
                       duration=f"{duration:.2f}s")
            
            return OpenAIResponse.success_response(
                message="Ассистент успешно удален",
                assistant_id=assistant_id,
                response_time=duration
            )
            
        except Exception as e:
            logger.error("💥 Exception in delete_assistant", 
                        assistant_id=assistant_id,
                        error=str(e),
                        error_type=type(e).__name__)
            return OpenAIResponse.error_response(f"Ошибка при удалении ассистента: {str(e)}")
    
    async def send_message(
        self,
        assistant_id: str,
        message: str,
        user_id: int,
        context: Optional[OpenAIConversationContext] = None
    ) -> Optional[str]:
        """
        Основной метод для отправки сообщения ассистенту с логированием
        Создает новый тред каждый раз (как требуется)
        """
        logger.info("💬 Starting message send to assistant", 
                   assistant_id=assistant_id,
                   user_id=user_id,
                   message_length=len(message),
                   has_context=bool(context))
        
        try:
            if not self._is_configured():
                logger.error("❌ OpenAI client not configured for messaging")
                return None
            
            start_time = time.time()
            
            # Подготавливаем содержимое сообщения
            content = message
            if context:
                context_info = context.to_context_string()
                content = f"{context_info}\n\nСообщение: {message}"
                logger.info("📝 Message content prepared with context", 
                           context_info=context_info,
                           final_content_length=len(content))
            
            # 1. Создаем новый тред
            logger.info("🧵 Creating new thread...")
            thread = await self.client.beta.threads.create()
            thread_id = thread.id
            
            logger.info("✅ Thread created", 
                       thread_id=thread_id,
                       creation_time=f"{time.time() - start_time:.2f}s")
            
            # 2. Добавляем сообщение в тред
            logger.info("📝 Adding message to thread...")
            await self.client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=content
            )
            
            logger.info("✅ Message added to thread", 
                       thread_id=thread_id,
                       content_length=len(content))
            
            # 3. Запускаем ассистента
            logger.info("🚀 Starting assistant run...")
            run = await self.client.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=assistant_id
            )
            
            logger.info("✅ Assistant run started", 
                       thread_id=thread_id,
                       run_id=run.id,
                       assistant_id=assistant_id)
            
            # 4. Ждем завершения
            timeout = OpenAIConstants.RUN_TIMEOUT
            polling_interval = OpenAIConstants.POLLING_INTERVAL
            max_attempts = timeout // polling_interval
            attempts = 0
            
            logger.info("⏳ Waiting for run completion", 
                       timeout=timeout,
                       polling_interval=polling_interval,
                       max_attempts=max_attempts)
            
            while attempts < max_attempts:
                run_status = await self.client.beta.threads.runs.retrieve(
                    thread_id=thread_id,
                    run_id=run.id
                )
                
                logger.debug("🔍 Run status check", 
                           run_id=run.id,
                           status=run_status.status,
                           attempt=attempts,
                           elapsed_time=f"{time.time() - start_time:.2f}s")
                
                if run_status.status == 'completed':
                    logger.info("✅ Run completed successfully", 
                               run_id=run.id,
                               attempts=attempts,
                               total_time=f"{time.time() - start_time:.2f}s")
                    break
                    
                elif run_status.status in ['failed', 'cancelled', 'expired']:
                    error_msg = f"Запуск завершился со статусом: {OpenAIConstants.RUN_STATUS.get(run_status.status, run_status.status)}"
                    logger.error("❌ Run failed", 
                               run_id=run.id,
                               status=run_status.status,
                               attempts=attempts,
                               error=error_msg)
                    return None
                    
                elif run_status.status in ['queued', 'in_progress']:
                    logger.debug("⏳ Run in progress", 
                               run_id=run.id,
                               status=run_status.status,
                               attempt=attempts)
                    await asyncio.sleep(polling_interval)
                    attempts += 1
                    
                else:
                    logger.warning("❓ Unknown run status", 
                                 run_id=run.id,
                                 status=run_status.status,
                                 attempt=attempts)
                    await asyncio.sleep(polling_interval)
                    attempts += 1
            
            if attempts >= max_attempts:
                logger.error("⏰ Run timeout", 
                           run_id=run.id,
                           timeout=timeout,
                           max_attempts=max_attempts,
                           elapsed_time=f"{time.time() - start_time:.2f}s")
                return None
            
            # 5. Получаем ответ
            logger.info("📨 Retrieving assistant response...")
            messages = await self.client.beta.threads.messages.list(
                thread_id=thread_id,
                limit=1,
                order="desc"
            )
            
            if not messages.data:
                logger.error("❌ No messages in thread response", thread_id=thread_id)
                return None
            
            latest_message = messages.data[0]
            if latest_message.role != 'assistant':
                logger.error("❌ Latest message is not from assistant", 
                           role=latest_message.role,
                           thread_id=thread_id)
                return None
            
            # Извлекаем текст ответа
            response_text = None
            for content_item in latest_message.content:
                if hasattr(content_item, 'text') and content_item.text:
                    response_text = content_item.text.value
                    break
            
            if not response_text:
                logger.error("❌ No text content found in assistant message", 
                           thread_id=thread_id,
                           content_items=len(latest_message.content))
                return None
            
            elapsed_time = time.time() - start_time
            logger.info("🎉 OpenAI assistant response received successfully", 
                       assistant_id=assistant_id,
                       user_id=user_id,
                       response_length=len(response_text),
                       elapsed_time=f"{elapsed_time:.2f}s",
                       thread_id=thread_id,
                       run_id=run.id)
            
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
    
    async def test_assistant(self, assistant_id: str) -> OpenAIResponse:
        """Тестирование ассистента с логированием"""
        logger.info("🧪 Starting assistant test", assistant_id=assistant_id)
        
        try:
            test_message = "Привет! Это тестовое сообщение. Ответь кратко, что ты готов к работе."
            
            logger.info("📝 Sending test message", 
                       message=test_message,
                       assistant_id=assistant_id)
            
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
                logger.info("✅ Assistant test successful", 
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
                logger.error("❌ Assistant test failed - no response", 
                           assistant_id=assistant_id,
                           test_duration=f"{test_duration:.2f}s")
                return OpenAIResponse.error_response("Тест не прошел - нет ответа от ассистента")
                
        except Exception as e:
            logger.error("💥 Exception in test_assistant", 
                        assistant_id=assistant_id,
                        error=str(e),
                        error_type=type(e).__name__)
            return OpenAIResponse.error_response(f"Ошибка при тестировании: {str(e)}")
    
    async def get_assistant_info(self, assistant_id: str) -> tuple[bool, Optional[Dict], Optional[str]]:
        """Получение информации об ассистенте с логированием"""
        logger.info("📊 Getting assistant info", assistant_id=assistant_id)
        
        try:
            if not self._is_configured():
                logger.error("❌ OpenAI client not configured for info retrieval")
                return False, None, "OpenAI API key not configured"
            
            logger.debug("📡 Retrieving assistant from OpenAI", assistant_id=assistant_id)
            
            start_time = time.time()
            assistant = await self.client.beta.assistants.retrieve(assistant_id)
            retrieval_duration = time.time() - start_time
            
            assistant_data = {
                'id': assistant.id,
                'name': assistant.name,
                'instructions': assistant.instructions,
                'model': assistant.model,
                'created_at': assistant.created_at,
                'metadata': assistant.metadata,
                'tools': [tool.type if hasattr(tool, 'type') else str(tool) for tool in assistant.tools] if hasattr(assistant, 'tools') else []
            }
            
            logger.info("✅ Assistant info retrieved successfully", 
                       assistant_id=assistant_id,
                       assistant_name=assistant.name,
                       model=assistant.model,
                       tools_count=len(assistant_data['tools']),
                       retrieval_duration=f"{retrieval_duration:.2f}s")
            
            return True, assistant_data, None
            
        except Exception as e:
            logger.error("💥 Exception in get_assistant_info", 
                        assistant_id=assistant_id,
                        error=str(e),
                        error_type=type(e).__name__)
            return False, None, str(e)
    
    def validate_create_request(self, request: OpenAICreateAgentRequest) -> tuple[bool, str]:
        """Валидация запроса на создание агента с логированием"""
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
        """Проверка доступности сервиса с логированием"""
        available = self._is_configured()
        
        logger.debug("🔍 Service availability check", 
                    is_available=available,
                    api_key_configured=bool(self.api_key),
                    client_configured=bool(self.client))
        
        return available
