"""
OpenAI Assistant Client
Основной клиент для работы с OpenAI Assistants API
"""

import os
import asyncio
import time
from typing import Optional, Dict, Any, List
import structlog
import aiohttp
import json

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
        self.base_url = 'https://api.openai.com/v1'
        self.headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
            'OpenAI-Beta': 'assistants=v2'  # Используем v2 API
        }
        
        if not self.api_key:
            logger.warning("OPENAI_API_KEY not found in environment variables")
    
    def _is_configured(self) -> bool:
        """Проверка конфигурации клиента"""
        return bool(self.api_key)
    
    async def _make_request(
        self, 
        method: str, 
        endpoint: str, 
        data: Optional[Dict] = None,
        timeout: int = 30
    ) -> tuple[bool, Dict[str, Any]]:
        """Базовый HTTP запрос к OpenAI API"""
        if not self._is_configured():
            return False, {"error": "OpenAI API key not configured"}
        
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    json=data,
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as response:
                    response_data = await response.json()
                    
                    if response.status >= 400:
                        error_msg = response_data.get('error', {}).get('message', f'HTTP {response.status}')
                        logger.error("OpenAI API error", 
                                   status=response.status, 
                                   error=error_msg,
                                   endpoint=endpoint)
                        return False, {"error": error_msg}
                    
                    return True, response_data
                    
        except asyncio.TimeoutError:
            logger.error("OpenAI API timeout", endpoint=endpoint, timeout=timeout)
            return False, {"error": "Request timeout"}
        except Exception as e:
            logger.error("OpenAI API request failed", endpoint=endpoint, error=str(e))
            return False, {"error": str(e)}
    
    async def create_assistant(self, agent: OpenAIAgent) -> OpenAIResponse:
        """Создание ассистента в OpenAI"""
        try:
            config = agent.to_openai_config()
            
            logger.info("Creating OpenAI assistant", 
                       name=agent.agent_name, 
                       model=agent.model,
                       bot_id=agent.bot_id)
            
            success, response_data = await self._make_request(
                'POST', 
                '/assistants', 
                config
            )
            
            if not success:
                error_msg = response_data.get('error', 'Unknown error')
                logger.error("Failed to create assistant", error=error_msg)
                return OpenAIResponse.error_response(f"Ошибка создания ассистента: {error_msg}")
            
            assistant_id = response_data.get('id')
            if not assistant_id:
                logger.error("No assistant ID in response", response=response_data)
                return OpenAIResponse.error_response("Не получен ID ассистента")
            
            logger.info("OpenAI assistant created successfully", 
                       assistant_id=assistant_id,
                       name=agent.agent_name)
            
            return OpenAIResponse.success_response(
                message="Ассистент успешно создан",
                assistant_id=assistant_id
            )
            
        except Exception as e:
            logger.error("Exception in create_assistant", error=str(e))
            return OpenAIResponse.error_response(f"Ошибка при создании ассистента: {str(e)}")
    
    async def update_assistant(self, assistant_id: str, agent: OpenAIAgent) -> OpenAIResponse:
        """Обновление ассистента в OpenAI"""
        try:
            config = agent.to_openai_config()
            
            logger.info("Updating OpenAI assistant", 
                       assistant_id=assistant_id,
                       name=agent.agent_name)
            
            success, response_data = await self._make_request(
                'POST', 
                f'/assistants/{assistant_id}', 
                config
            )
            
            if not success:
                error_msg = response_data.get('error', 'Unknown error')
                logger.error("Failed to update assistant", error=error_msg)
                return OpenAIResponse.error_response(f"Ошибка обновления ассистента: {error_msg}")
            
            logger.info("OpenAI assistant updated successfully", assistant_id=assistant_id)
            
            return OpenAIResponse.success_response(
                message="Ассистент успешно обновлен",
                assistant_id=assistant_id
            )
            
        except Exception as e:
            logger.error("Exception in update_assistant", error=str(e))
            return OpenAIResponse.error_response(f"Ошибка при обновлении ассистента: {str(e)}")
    
    async def delete_assistant(self, assistant_id: str) -> OpenAIResponse:
        """Удаление ассистента из OpenAI"""
        try:
            logger.info("Deleting OpenAI assistant", assistant_id=assistant_id)
            
            success, response_data = await self._make_request(
                'DELETE', 
                f'/assistants/{assistant_id}'
            )
            
            if not success:
                error_msg = response_data.get('error', 'Unknown error')
                logger.error("Failed to delete assistant", error=error_msg)
                return OpenAIResponse.error_response(f"Ошибка удаления ассистента: {error_msg}")
            
            logger.info("OpenAI assistant deleted successfully", assistant_id=assistant_id)
            
            return OpenAIResponse.success_response(
                message="Ассистент успешно удален",
                assistant_id=assistant_id
            )
            
        except Exception as e:
            logger.error("Exception in delete_assistant", error=str(e))
            return OpenAIResponse.error_response(f"Ошибка при удалении ассистента: {str(e)}")
    
    async def create_thread(self) -> tuple[bool, Optional[str], Optional[str]]:
        """Создание нового треда для диалога"""
        try:
            logger.debug("Creating new OpenAI thread")
            
            success, response_data = await self._make_request('POST', '/threads', {})
            
            if not success:
                error_msg = response_data.get('error', 'Unknown error')
                logger.error("Failed to create thread", error=error_msg)
                return False, None, error_msg
            
            thread_id = response_data.get('id')
            if not thread_id:
                logger.error("No thread ID in response", response=response_data)
                return False, None, "Не получен ID треда"
            
            logger.debug("OpenAI thread created", thread_id=thread_id)
            return True, thread_id, None
            
        except Exception as e:
            logger.error("Exception in create_thread", error=str(e))
            return False, None, str(e)
    
    async def add_message_to_thread(
        self, 
        thread_id: str, 
        message: str, 
        context: Optional[OpenAIConversationContext] = None
    ) -> tuple[bool, Optional[str]]:
        """Добавление сообщения в тред"""
        try:
            # Подготавливаем содержимое сообщения
            content = message
            if context:
                context_info = context.to_context_string()
                content = f"{context_info}\n\nСообщение: {message}"
            
            data = {
                "role": "user",
                "content": content
            }
            
            logger.debug("Adding message to thread", thread_id=thread_id, message_length=len(message))
            
            success, response_data = await self._make_request(
                'POST', 
                f'/threads/{thread_id}/messages', 
                data
            )
            
            if not success:
                error_msg = response_data.get('error', 'Unknown error')
                logger.error("Failed to add message to thread", error=error_msg)
                return False, error_msg
            
            logger.debug("Message added to thread successfully", thread_id=thread_id)
            return True, None
            
        except Exception as e:
            logger.error("Exception in add_message_to_thread", error=str(e))
            return False, str(e)
    
    async def run_assistant(
        self, 
        thread_id: str, 
        assistant_id: str
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """Запуск ассистента для обработки треда"""
        try:
            data = {
                "assistant_id": assistant_id
            }
            
            logger.debug("Running assistant", thread_id=thread_id, assistant_id=assistant_id)
            
            success, response_data = await self._make_request(
                'POST', 
                f'/threads/{thread_id}/runs', 
                data
            )
            
            if not success:
                error_msg = response_data.get('error', 'Unknown error')
                logger.error("Failed to run assistant", error=error_msg)
                return False, None, error_msg
            
            run_id = response_data.get('id')
            if not run_id:
                logger.error("No run ID in response", response=response_data)
                return False, None, "Не получен ID запуска"
            
            logger.debug("Assistant run started", thread_id=thread_id, run_id=run_id)
            return True, run_id, None
            
        except Exception as e:
            logger.error("Exception in run_assistant", error=str(e))
            return False, None, str(e)
    
    async def wait_for_run_completion(
        self, 
        thread_id: str, 
        run_id: str,
        timeout: int = OpenAIConstants.RUN_TIMEOUT
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """Ожидание завершения запуска ассистента"""
        try:
            start_time = time.time()
            attempts = 0
            max_attempts = timeout // OpenAIConstants.POLLING_INTERVAL
            
            logger.debug("Waiting for run completion", thread_id=thread_id, run_id=run_id)
            
            while attempts < max_attempts:
                success, response_data = await self._make_request(
                    'GET', 
                    f'/threads/{thread_id}/runs/{run_id}'
                )
                
                if not success:
                    error_msg = response_data.get('error', 'Unknown error')
                    logger.error("Failed to check run status", error=error_msg)
                    return False, None, error_msg
                
                status = response_data.get('status')
                logger.debug("Run status check", run_id=run_id, status=status, attempt=attempts)
                
                if status == 'completed':
                    elapsed_time = time.time() - start_time
                    logger.debug("Run completed successfully", 
                               run_id=run_id, 
                               elapsed_time=elapsed_time)
                    return True, status, None
                
                elif status in ['failed', 'cancelled', 'expired']:
                    error_msg = f"Запуск завершился со статусом: {OpenAIConstants.RUN_STATUS.get(status, status)}"
                    logger.error("Run failed", run_id=run_id, status=status)
                    return False, status, error_msg
                
                elif status in ['queued', 'in_progress']:
                    # Продолжаем ожидание
                    await asyncio.sleep(OpenAIConstants.POLLING_INTERVAL)
                    attempts += 1
                
                else:
                    logger.warning("Unknown run status", run_id=run_id, status=status)
                    await asyncio.sleep(OpenAIConstants.POLLING_INTERVAL)
                    attempts += 1
            
            # Таймаут
            logger.error("Run timeout", run_id=run_id, timeout=timeout)
            return False, None, f"Превышено время ожидания ({timeout}с)"
            
        except Exception as e:
            logger.error("Exception in wait_for_run_completion", error=str(e))
            return False, None, str(e)
    
    async def get_thread_messages(
        self, 
        thread_id: str, 
        limit: int = 1
    ) -> tuple[bool, Optional[List[Dict]], Optional[str]]:
        """Получение сообщений из треда"""
        try:
            params = f"?limit={limit}&order=desc"
            
            logger.debug("Getting thread messages", thread_id=thread_id, limit=limit)
            
            success, response_data = await self._make_request(
                'GET', 
                f'/threads/{thread_id}/messages{params}'
            )
            
            if not success:
                error_msg = response_data.get('error', 'Unknown error')
                logger.error("Failed to get thread messages", error=error_msg)
                return False, None, error_msg
            
            messages = response_data.get('data', [])
            logger.debug("Retrieved thread messages", 
                        thread_id=thread_id, 
                        message_count=len(messages))
            
            return True, messages, None
            
        except Exception as e:
            logger.error("Exception in get_thread_messages", error=str(e))
            return False, None, str(e)
    
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
            start_time = time.time()
            
            logger.info("Sending message to OpenAI assistant", 
                       assistant_id=assistant_id,
                       user_id=user_id,
                       message_length=len(message))
            
            # 1. Создаем новый тред
            success, thread_id, error = await self.create_thread()
            if not success:
                logger.error("Failed to create thread", error=error)
                return None
            
            # 2. Добавляем сообщение в тред
            success, error = await self.add_message_to_thread(thread_id, message, context)
            if not success:
                logger.error("Failed to add message to thread", error=error)
                return None
            
            # 3. Запускаем ассистента
            success, run_id, error = await self.run_assistant(thread_id, assistant_id)
            if not success:
                logger.error("Failed to run assistant", error=error)
                return None
            
            # 4. Ждем завершения
            success, status, error = await self.wait_for_run_completion(thread_id, run_id)
            if not success:
                logger.error("Run did not complete successfully", error=error)
                return None
            
            # 5. Получаем ответ
            success, messages, error = await self.get_thread_messages(thread_id, limit=1)
            if not success:
                logger.error("Failed to get thread messages", error=error)
                return None
            
            if not messages:
                logger.error("No messages in thread response")
                return None
            
            # Извлекаем текст ответа
            latest_message = messages[0]
            if latest_message.get('role') != 'assistant':
                logger.error("Latest message is not from assistant", 
                           role=latest_message.get('role'))
                return None
            
            content = latest_message.get('content', [])
            if not content:
                logger.error("No content in assistant message")
                return None
            
            # Извлекаем текст из первого text блока
            response_text = None
            for content_item in content:
                if content_item.get('type') == 'text':
                    response_text = content_item.get('text', {}).get('value')
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
            logger.debug("Getting assistant info", assistant_id=assistant_id)
            
            success, response_data = await self._make_request(
                'GET', 
                f'/assistants/{assistant_id}'
            )
            
            if not success:
                error_msg = response_data.get('error', 'Unknown error')
                logger.error("Failed to get assistant info", error=error_msg)
                return False, None, error_msg
            
            logger.debug("Assistant info retrieved", assistant_id=assistant_id)
            return True, response_data, None
            
        except Exception as e:
            logger.error("Exception in get_assistant_info", error=str(e))
            return False, None, str(e)
    
    def validate_create_request(self, request: OpenAICreateAgentRequest) -> tuple[bool, str]:
        """Валидация запроса на создание агента"""
        return OpenAIValidator.validate_create_request(request)
    
    def is_available(self) -> bool:
        """Проверка доступности сервиса"""
        return self._is_configured()
