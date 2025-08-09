"""
OpenAI Assistant Service Package
Сервис для работы с OpenAI Assistants API
"""

from .client import OpenAIAssistantClient
from .models import OpenAIAgent, OpenAIThread, OpenAIResponse

# Глобальный экземпляр клиента
openai_client = OpenAIAssistantClient()

__all__ = [
    'OpenAIAssistantClient',
    'OpenAIAgent', 
    'OpenAIThread',
    'OpenAIResponse',
    'openai_client'
]
