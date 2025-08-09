"""
OpenAI Assistant Service Package
Сервис для работы с OpenAI Assistants API
"""

import os
import structlog

logger = structlog.get_logger()

# Проверяем наличие OpenAI API ключа
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# Простая заглушка для ответов
class SimpleResponse:
    def __init__(self, success=False, error="Service not available"):
        self.success = success
        self.error = error
        self.message = None
        self.assistant_id = None
    
    @classmethod
    def error_response(cls, error_msg):
        return cls(success=False, error=error_msg)

# Заглушка клиента OpenAI
class OpenAIAssistantClientStub:
    """Заглушка для случаев когда OpenAI недоступен"""
    
    def is_available(self):
        return False
    
    def validate_create_request(self, request):
        return True, "Validation skipped (stub mode)"
    
    async def create_assistant(self, agent):
        logger.warning("OpenAI service not available, using stub")
        return SimpleResponse.error_response("OpenAI dependencies not installed")
    
    async def send_message(self, assistant_id, message, user_id, context=None):
        logger.warning("OpenAI service not available, using stub response")
        return "🤖 OpenAI сервис временно недоступен. Установите библиотеку 'openai' и настройте API ключ."
    
    async def test_assistant(self, assistant_id):
        return SimpleResponse.error_response("OpenAI service not available")

if OPENAI_API_KEY:
    logger.info("OpenAI API key found, trying to initialize service")
    try:
        # Пытаемся импортировать OpenAI
        import openai
        logger.info("OpenAI library found, initializing real client")
        
        from .client import OpenAIAssistantClient
        from .models import OpenAIAgent, OpenAIThread, OpenAIResponse
        
        # Создаем реальный клиент
        openai_client = OpenAIAssistantClient()
        
        if openai_client.is_available():
            logger.info("✅ OpenAI Assistant service initialized successfully")
        else:
            logger.warning("⚠️ OpenAI client created but API key not configured properly")
        
        __all__ = [
            'OpenAIAssistantClient',
            'OpenAIAgent', 
            'OpenAIThread',
            'OpenAIResponse',
            'openai_client'
        ]
        
    except ImportError as e:
        logger.warning(f"❌ OpenAI library not installed: {e}")
        logger.info("📦 Install with: pip install openai")
        
        # Используем заглушку
        openai_client = OpenAIAssistantClientStub()
        
        __all__ = ['openai_client']
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize OpenAI client: {e}")
        
        # Используем заглушку при любой другой ошибке
        openai_client = OpenAIAssistantClientStub()
        
        __all__ = ['openai_client']
        
else:
    logger.warning("❌ OPENAI_API_KEY not found in environment")
    logger.info("🔑 Add OPENAI_API_KEY to your .env file")
    
    # Используем заглушку
    openai_client = OpenAIAssistantClientStub()
    
    __all__ = ['openai_client']

# Информация о статусе сервиса
logger.info(f"OpenAI Assistant Service Status: {'✅ Active' if hasattr(openai_client, 'client') and openai_client.is_available() else '⚠️ Stub Mode'}")

