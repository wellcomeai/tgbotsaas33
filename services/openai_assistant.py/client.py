"""
OpenAI Assistant Client
Основной клиент для работы с OpenAI Assistants API
"""

import os
import asyncio
import time
from typing import Optional, Dict, Any, List
import structlog
from openai import AsyncOpenAI

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
    """Клиент для работы с OpenAI Assistants API"""
    
    def __init__(self):
        self.api_key = os.getenv('OPENAI_API_KEY')
        self.client = None
        
        if self.api_key:
            self.client = AsyncOpenAI(api_key=self.api_key)
        else:
            logger.warning("OPENAI_API_KEY not found in environment variables")
    
    def _is_configured(self) -> bool:
        """Проверка конфигурации клиента"""
        return bool(self.api_key and self.client)
    
    async def create_assistant(self, agent: OpenAIAgent) -> OpenAIResponse:
        """Создание ассистента в OpenAI"""
        try:
            if not self._is_configured():
                return OpenAIResponse.error_response("OpenAI API key not configured")
            
            config = agent.to_openai_config()
            
            logger.info("Creating OpenAI assistant", 
                       name=agent.agent_name, 
                       model=agent.model,
                       bot_id=agent.bot_id)
            
            assistant = await self.client.beta.assistants.create(**config)
            
            logger.info("OpenAI assistant created successfully", 
                       assistant_id=assistant.id,
                       name=agent.agent_name)
            
            return OpenAIResponse.success_response(
                message="Ассистент успешно создан",
                assistant_id=assistant.id
            )
            
        except Exception as e:
            logger.error("Exception in create_assistant", error=str(e))
            return OpenAIResponse.error_response(f"Ошибка при создании ассистента: {str(e)}")
    
    async def update_assistant(self, assistant_id: str, agent: OpenAIAgent) -> OpenAIResponse:
        """Обновление ассистента в OpenAI"""
        try:
            if not self._is_configured():
                return OpenAIResponse.error_response("OpenAI API key not configured")
            
            config = agent.to_openai_config()
            
            logger.info("Updating OpenAI assistant", 
                       assistant_id=assistant_id,
                       name=agent.agent_name)
            
            assistant = await self.client.beta.assistants.update(assistant_id, **config)
            
            logger.info("OpenAI assistant updated successfully", assistant_id=assistant_id)
            
            return OpenAIResponse.success_response(
                message="Ассистент успешно обновлен",
                assistant_id=assistant.id
            )
            
        except Exception as e:
            logger.error("Exception in update_assistant", error=str(e))
            return OpenAIResponse.error_response(f"Ошибка при обновлении ассистента: {str(e)}")
    
    async def delete_assistant(self, assistant_id: str) -> OpenAIResponse:
        """Удаление ассистента из OpenAI"""
        try:
            if not self._is_configured():
                return OpenAIResponse.error_response("OpenAI API key not configured")
            
            logger.info("Deleting OpenAI assistant", assistant_id=assistant_id)
            
            await self.client.beta.assistants.delete(assistant_id)
            
            logger.info("OpenAI assistant deleted successfully", assistant_id=assistant_id)
            
            return OpenAIResponse.success_response(
                message="Ассистент успешно удален",
                assistant_id=assistant_id
            )
            
        except Exception as e:
            logger.error("Exception in delete_assistant", error=str(e))
            return OpenAIResponse.error_response(f"Ошибка при удалении ассистента: {str(e)}")
    
    async def send_message(
        self,
        assistant_id: str,
        message: str,
        user_id: int,
        context: Optional[OpenAIConversationContext] = None
    ) -> Optional[str]:
        """
        Основной метод для отправки сообщения ассистенту
        Создает новый тред каждый раз (как требуется)
        """
        try:
            if not self._is_configured():
                logger.error("OpenAI client not configured")
                return None
            
            start_time = time.time()
            
            logger.info("Sending message to OpenAI assistant", 
                       assistant_id=assistant_id,
                       user_id=user_id,
                       message_length=len(message))
            
            # Подготавливаем содержимое сообщения
            content = message
            if context:
                context_info = context.to_context_string()
                content = f"{context_info}\n\nСообщение: {message}"
            
            # 1. Создаем новый тред
            thread = await self.client.beta.threads.create()
            thread_id = thread.id
            
            logger.debug("Thread created", thread_id=thread_id)
            
            # 2. Добавляем сообщение в тред
            await self.client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=content
            )
            
            logger.debug("Message added to thread", thread_id=thread_id)
            
            # 3. Запускаем ассистента
            run = await self.client.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=assistant_id
            )
            
            logger.debug("Assistant run started", thread_id=thread_id, run_id=run.id)
            
            # 4. Ждем завершения
            timeout = OpenAIConstants.RUN_TIMEOUT
            polling_interval = OpenAIConstants.POLLING_INTERVAL
            max_attempts = timeout // polling_interval
            attempts = 0
            
            while attempts < max_attempts:
                run_status = await self.client.beta.threads.runs.retrieve(
                    thread_id=thread_id,
                    run_id=run.id
                )
                
                logger.debug("Run status check", run_id=run.id, status=run_status.status, attempt=attempts)
                
                if run_status.status == 'completed':
                    break
                elif run_status.status in ['failed', 'cancelled', 'expired']:
                    error_msg = f"Запуск завершился со статусом: {OpenAIConstants.RUN_STATUS.get(run_status.status, run_status.status)}"
                    logger.error("Run failed", run_id=run.id, status=run_status.status)
                    return None
                elif run_status.status in ['queued', 'in_progress']:
                    await asyncio.sleep(polling_interval)
                    attempts += 1
                else:
                    logger.warning("Unknown run status", run_id=run.id, status=run_status.status)
                    await asyncio.sleep(polling_interval)
                    attempts += 1
            
            if attempts >= max_attempts:
                logger.error("Run timeout", run_id=run.id, timeout=timeout)
                return None
            
            # 5. Получаем ответ
            messages = await self.client.beta.threads.messages.list(
                thread_id=thread_id,
                limit=1,
                order="desc"
            )
            
            if not messages.data:
                logger.error("No messages in thread response")
                return None
            
            latest_message = messages.data[0]
            if latest_message.role != 'assistant':
                logger.error("Latest message is not from assistant", role=latest_message.role)
                return None
            
            # Извлекаем текст ответа
            response_text = None
            for content_item in latest_message.content:
                if hasattr(content_item, 'text') and content_item.text:
                    response_text = content_item.text.value
                    break
            
            if not response_text:
                logger.error("No text content found in assistant message")
                return None
            
            elapsed_time = time.time() - start_time
            logger.info("OpenAI assistant response received", 
                       assistant_id=assistant_id,
                       user_id=user_id,
                       response_length=len(response_text),
                       elapsed_time=elapsed_time,
                       thread_id=thread_id)
            
            return response_text
            
        except Exception as e:
            logger.error("Exception in send_message", 
                        assistant_id=assistant_id,
                        user_id=user_id,
                        error=str(e))
            return None
    
    async def test_assistant(self, assistant_id: str) -> OpenAIResponse:
        """Тестирование ассистента"""
        try:
            logger.info("Testing OpenAI assistant", assistant_id=assistant_id)
            
            test_message = "Привет! Это тестовое сообщение. Ответь кратко, что ты готов к работе."
            
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
            
            if response_text:
                logger.info("Assistant test successful", assistant_id=assistant_id)
                return OpenAIResponse.success_response(
                    message=response_text,
                    assistant_id=assistant_id
                )
            else:
                logger.error("Assistant test failed", assistant_id=assistant_id)
                return OpenAIResponse.error_response("Тест не прошел - нет ответа от ассистента")
                
        except Exception as e:
            logger.error("Exception in test_assistant", error=str(e))
            return OpenAIResponse.error_response(f"Ошибка при тестировании: {str(e)}")
    
    async def get_assistant_info(self, assistant_id: str) -> tuple[bool, Optional[Dict], Optional[str]]:
        """Получение информации об ассистенте"""
        try:
            if not self._is_configured():
                return False, None, "OpenAI API key not configured"
            
            logger.debug("Getting assistant info", assistant_id=assistant_id)
            
            assistant = await self.client.beta.assistants.retrieve(assistant_id)
            
            assistant_data = {
                'id': assistant.id,
                'name': assistant.name,
                'instructions': assistant.instructions,
                'model': assistant.model,
                'created_at': assistant.created_at,
                'metadata': assistant.metadata
            }
            
            logger.debug("Assistant info retrieved", assistant_id=assistant_id)
            return True, assistant_data, None
            
        except Exception as e:
            logger.error("Exception in get_assistant_info", error=str(e))
            return False, None, str(e)
    
    def validate_create_request(self, request: OpenAICreateAgentRequest) -> tuple[bool, str]:
        """Валидация запроса на создание агента"""
        return OpenAIValidator.validate_create_request(request)
    
    def is_available(self) -> bool:
        """Проверка доступности сервиса"""
        return self._is_configured()
