# Замените начало файла services/openai_assistant/__init__.py на это:

"""
OpenAI Assistant Service Package
Сервис для работы с OpenAI Assistants API
"""

import os
import structlog

logger = structlog.get_logger()

# 🔍 ДЕТАЛЬНАЯ ДИАГНОСТИКА ИНИЦИАЛИЗАЦИИ
logger.info("🚀 Initializing OpenAI Assistant Service Package")

# Проверяем наличие OpenAI API ключа
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

logger.info("🔍 Environment check", 
           api_key_exists=bool(OPENAI_API_KEY),
           api_key_length=len(OPENAI_API_KEY) if OPENAI_API_KEY else 0,
           api_key_prefix=OPENAI_API_KEY[:12] + "..." if OPENAI_API_KEY else "None")

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
        logger.warning("🔄 OpenAI service not available, using stub", 
                      agent_name=getattr(agent, 'agent_name', 'unknown'),
                      bot_id=getattr(agent, 'bot_id', 'unknown'))
        return SimpleResponse.error_response("OpenAI dependencies not installed")
    
    async def send_message(self, assistant_id, message, user_id, context=None):
        logger.warning("🔄 OpenAI service not available, using stub response", 
                      assistant_id=assistant_id,
                      user_id=user_id,
                      message_length=len(message))
        return "🤖 OpenAI сервис временно недоступен. Установите библиотеку 'openai' и настройте API ключ."
    
    async def test_assistant(self, assistant_id):
        return SimpleResponse.error_response("OpenAI service not available")

if OPENAI_API_KEY:
    logger.info("🔑 OpenAI API key found, trying to initialize service")
    try:
        # Пытаемся импортировать OpenAI
        logger.info("📦 Attempting to import openai library...")
        import openai
        logger.info("✅ OpenAI library found", version=getattr(openai, '__version__', 'unknown'))
        
        logger.info("📦 Importing OpenAI service components...")
        from .client import OpenAIAssistantClient
        from .models import OpenAIAgent, OpenAIThread, OpenAIResponse
        
        # Создаем реальный клиент
        logger.info("🔧 Creating OpenAI client instance...")
        openai_client = OpenAIAssistantClient()
        
        client_available = openai_client.is_available()
        logger.info("🔍 OpenAI client availability check", 
                   is_available=client_available,
                   client_type=type(openai_client).__name__)
        
        if client_available:
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
        logger.info("🔄 Falling back to stub client")
        
        # Используем заглушку
        openai_client = OpenAIAssistantClientStub()
        
        __all__ = ['openai_client']
        
    except Exception as e:
        logger.error(f"💥 Failed to initialize OpenAI client: {e}", 
                    exception_type=type(e).__name__,
                    exc_info=True)
        logger.info("🔄 Falling back to stub client")
        
        # Используем заглушку при любой другой ошибке
        openai_client = OpenAIAssistantClientStub()
        
        __all__ = ['openai_client']
        
else:
    logger.warning("❌ OPENAI_API_KEY not found in environment")
    logger.info("🔑 Add OPENAI_API_KEY to your .env file")
    logger.info("🔄 Using stub client")
    
    # Используем заглушку
    openai_client = OpenAIAssistantClientStub()
    
    __all__ = ['openai_client']

# Финальная информация о статусе сервиса
service_active = hasattr(openai_client, 'client') and openai_client.is_available()
service_status = '✅ Active' if service_active else '⚠️ Stub Mode'

logger.info(f"🏁 OpenAI Assistant Service Status: {service_status}", 
           service_type='real' if service_active else 'stub',
           client_class=type(openai_client).__name__)

# Рекомендации для деплоя
if not OPENAI_API_KEY:
    logger.warning("🔧 DEPLOY RECOMMENDATION: Set OPENAI_API_KEY environment variable")
elif not service_active:
    logger.warning("🔧 DEPLOY RECOMMENDATION: Verify OpenAI library installation and API key validity")
