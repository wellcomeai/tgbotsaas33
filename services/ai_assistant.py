import asyncio
import aiohttp
import json
import time
import uuid
from datetime import datetime
from typing import Optional, Dict, Any
import structlog

logger = structlog.get_logger()

class AIAssistantError(Exception):
    """Базовая ошибка AI Assistant"""
    pass

class AIAssistantClient:
    """Клиент для работы с двумя AI API платформами"""
    
    # URL платформ
    CHATFORYOU_BASE_URL = "https://api.chatforyou.ru/api/v1.0"
    PROTALK_BASE_URL = "https://api.pro-talk.ru/api/v1.0"
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Получить HTTP сессию"""
        if not self.session or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session
    
    async def close(self):
        """Закрыть сессию"""
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def send_message(
        self,
        api_token: str,
        message: str,
        user_id: int,
        platform: str,
        bot_id: str = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Отправить сообщение через определенную платформу
        """
        try:
            full_message = message
            if context:
                context_text = self._format_context(context)
                if context_text:
                    full_message = f"{context_text}\n\nПользователь: {message}"
            
            logger.info("Sending message via platform", 
                       platform=platform, 
                       user_id=user_id, 
                       message_length=len(full_message),
                       has_bot_id=bool(bot_id))
            
            if platform == "chatforyou":
                if not bot_id:
                    raise AIAssistantError("bot_id required for ChatForYou platform")
                return await self._send_via_chatforyou(api_token, full_message, user_id, bot_id)
            
            elif platform == "protalk":
                return await self._send_via_protalk(api_token, full_message, user_id)
            
            else:
                raise AIAssistantError(f"Unknown platform: {platform}")
                
        except Exception as e:
            logger.error("Error sending message via platform", 
                        platform=platform, 
                        user_id=user_id, 
                        error=str(e))
            raise AIAssistantError(f"Platform {platform} error: {str(e)}")
    
    async def _send_via_chatforyou(
        self, 
        api_token: str,
        message: str, 
        user_id: int,
        bot_id: str
    ) -> Optional[str]:
        """
        Отправка через ChatForYou API
        """
        session = await self._get_session()
        
        url = f"{self.CHATFORYOU_BASE_URL}/ask/{api_token}"
        
        payload = {
            "bot_id": str(bot_id),
            "chat_id": f"user_{user_id}",
            "message_id": f"msg_{int(time.time())}",
            "message": message
        }
        
        headers = {
            "Content-Type": "application/json"
        }
        
        logger.info("📤 Sending ChatForYou request", 
                   url=url, 
                   bot_id=bot_id, 
                   payload_preview={
                       "bot_id": payload["bot_id"],
                       "chat_id": payload["chat_id"],
                       "message_id": payload["message_id"],
                       "message_length": len(payload["message"])
                   })
        
        try:
            async with session.post(url, headers=headers, json=payload) as response:
                response_text = await response.text()
                
                logger.info("📥 ChatForYou response received", 
                           status=response.status,
                           response_length=len(response_text))
                
                if response.status != 200:
                    logger.error("ChatForYou API error", 
                                status=response.status, 
                                response=response_text)
                    raise AIAssistantError(f"ChatForYou API error: {response.status}, {response_text}")
                
                try:
                    data = await response.json()
                    
                    # Получаем ответ из поля "done"
                    ai_response = data.get('done')
                    
                    if ai_response:
                        logger.info("✅ ChatForYou response received", 
                                   response_length=len(ai_response),
                                   usage=data.get('usage', {}))
                        return ai_response
                    
                    # Проверяем на ошибки
                    if 'error' in data:
                        logger.error("ChatForYou API returned error", error=data['error'])
                        raise AIAssistantError(f"ChatForYou API error: {data['error']}")
                    
                    logger.warning("ChatForYou returned empty response", data=data)
                    return None
                    
                except json.JSONDecodeError as e:
                    logger.error("Invalid JSON from ChatForYou", error=str(e), response=response_text)
                    raise AIAssistantError(f"Invalid JSON response from ChatForYou: {str(e)}")
                    
        except aiohttp.ClientError as e:
            logger.error("Network error with ChatForYou", error=str(e))
            raise AIAssistantError(f"Network error: {str(e)}")
    
    async def _send_via_protalk(
        self, 
        api_token: str,
        message: str, 
        user_id: int
    ) -> Optional[str]:
        """
        Отправка через ProTalk API
        """
        session = await self._get_session()
        chat_id = f"user_{user_id}"
        message_id = f"msg_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
        
        logger.info("📤 Sending ProTalk message", 
                   chat_id=chat_id, 
                   message_id=message_id)
        
        # Отправляем сообщение
        await self._send_message_to_protalk(session, api_token, chat_id, message_id, message)
        
        # Ждем ответ
        await asyncio.sleep(2)
        response = await self._get_protalk_response(session, api_token, chat_id, message_id)
        
        if response:
            logger.info("✅ ProTalk response received", response_length=len(response))
        else:
            logger.warning("ProTalk returned empty response")
            
        return response
    
    async def _send_message_to_protalk(
        self, session: aiohttp.ClientSession, api_token: str, 
        chat_id: str, message_id: str, message: str
    ):
        """Отправить сообщение через ProTalk send_message API"""
        url = f"{self.PROTALK_BASE_URL}/send_message"
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "message": message
        }
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }
        
        async with session.post(url, headers=headers, json=payload) as response:
            if response.status != 200:
                text = await response.text()
                raise AIAssistantError(f"ProTalk send_message failed: {response.status}, {text}")
    
    async def _get_protalk_response(
        self, session: aiohttp.ClientSession, api_token: str, 
        chat_id: str, original_message_id: str, max_retries: int = 5
    ) -> Optional[str]:
        """Получить ответ от ProTalk через get_messages API"""
        url = f"{self.PROTALK_BASE_URL}/get_messages"
        payload = {"chat_id": chat_id}
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }
        
        for attempt in range(max_retries):
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    try:
                        data = await response.json()
                        ai_resp = self._extract_protalk_response(data, original_message_id)
                        if ai_resp:
                            return ai_resp
                    except json.JSONDecodeError:
                        pass
                
                if attempt < max_retries - 1:
                    await asyncio.sleep(1 + attempt * 0.5)
        
        return None
    
    def _extract_protalk_response(self, response_data: Any, original_message_id: str) -> Optional[str]:
        """Извлечь ответ из ProTalk API"""
        try:
            messages = []
            if isinstance(response_data, list):
                messages = response_data
            elif isinstance(response_data, dict):
                if 'messages' in response_data:
                    messages = response_data['messages']
                elif 'data' in response_data:
                    data = response_data['data']
                    if isinstance(data, list):
                        messages = data
                    elif isinstance(data, dict) and 'messages' in data:
                        messages = data['messages']
                else:
                    messages = [response_data]
            
            for msg in messages:
                if isinstance(msg, dict):
                    msg_id = msg.get('message_id', '')
                    text = msg.get('message') or msg.get('text', '')
                    if msg_id != original_message_id and text:
                        return text.strip()
                elif isinstance(msg, str):
                    return msg.strip()
            
            return None
        except Exception as e:
            logger.error("Error extracting ProTalk response", error=str(e))
            return None
    
    def _format_context(self, context: Dict[str, Any]) -> str:
        """Форматировать контекст для отправки ИИ"""
        try:
            parts = []
            if context.get('user_name'):
                parts.append(f"Имя пользователя: {context['user_name']}")
            if context.get('username'):
                parts.append(f"Username: @{context['username']}")
            if context.get('is_test'):
                parts.append("Режим: Тестирование")
            return "Контекст: " + ", ".join(parts) if parts else ""
        except Exception as e:
            logger.error("Error formatting context", error=str(e))
            return ""

# Глобальный экземпляр клиента
ai_client = AIAssistantClient()
