# Замените полностью содержимое services/openai_assistant/__init__.py

"""
OpenAI Responses API Service Package
Сервис для работы с OpenAI Responses API (новая версия)
✅ Заменяет старый Chat Completions API
✅ Автоматическое управление контекстом на сервере OpenAI
✅ Встроенные инструменты (веб-поиск, код, файлы)
✅ ИСПРАВЛЕНЫ: Все импорты и названия классов
"""

import os
import structlog

logger = structlog.get_logger()

# 🔍 ДЕТАЛЬНАЯ ДИАГНОСТИКА ИНИЦИАЛИЗАЦИИ
logger.info("🚀 Initializing OpenAI Responses API Service Package")

# Проверяем наличие OpenAI API ключа
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

logger.info("🔍 Environment check", 
           api_key_exists=bool(OPENAI_API_KEY),
           api_key_length=len(OPENAI_API_KEY) if OPENAI_API_KEY else 0,
           api_key_prefix=OPENAI_API_KEY[:12] + "..." if OPENAI_API_KEY else "None")

# Простая заглушка для ответов
class SimpleResponsesResult:
    def __init__(self, success=False, error="Service not available"):
        self.success = success
        self.error = error
        self.output_text = None
        self.response_id = None
    
    @classmethod
    def error_result(cls, error_msg):
        return cls(success=False, error=error_msg)

# Заглушка клиента OpenAI Responses API
class OpenAIResponsesClientStub:
    """Заглушка для случаев когда OpenAI недоступен"""
    
    def is_available(self):
        return False
    
    def validate_create_request(self, request):
        return True, "Validation skipped (stub mode)"
    
    async def create_assistant(self, agent):
        logger.warning("🔄 OpenAI Responses API service not available, using stub", 
                      agent_name=getattr(agent, 'agent_name', 'unknown'),
                      bot_id=getattr(agent, 'bot_id', 'unknown'))
        return SimpleResponsesResult.error_result("OpenAI Responses API dependencies not installed")
    
    async def send_message(self, assistant_id, message, user_id, context=None):
        logger.warning("🔄 OpenAI Responses API service not available, using stub response", 
                      assistant_id=assistant_id,
                      user_id=user_id,
                      message_length=len(message))
        return "🤖 OpenAI Responses API сервис временно недоступен. Установите библиотеку 'openai' версии 1.40+ и настройте API ключ."
    
    async def test_assistant(self, assistant_id):
        return SimpleResponsesResult.error_result("OpenAI Responses API service not available")
    
    async def clear_conversation(self, assistant_id, user_id):
        logger.warning("🔄 Cannot clear conversation: OpenAI Responses API not available")
        return False

if OPENAI_API_KEY:
    logger.info("🔑 OpenAI API key found, trying to initialize Responses API service")
    try:
        # Пытаемся импортировать OpenAI
        logger.info("📦 Attempting to import openai library...")
        import openai
        logger.info("✅ OpenAI library found", version=getattr(openai, '__version__', 'unknown'))
        
        # Проверяем версию OpenAI (Responses API требует 1.40+)
        try:
            openai_version = getattr(openai, '__version__', '0.0.0')
            version_parts = openai_version.split('.')
            major_version = int(version_parts[0])
            minor_version = int(version_parts[1]) if len(version_parts) > 1 else 0
            
            if major_version < 1 or (major_version == 1 and minor_version < 40):
                logger.warning("⚠️ OpenAI library version too old for Responses API", 
                              current_version=openai_version,
                              required_version="1.40+")
                raise ImportError(f"OpenAI library version {openai_version} too old. Responses API requires 1.40+")
            
            logger.info("✅ OpenAI library version compatible with Responses API", 
                       version=openai_version)
        
        except (ValueError, AttributeError) as e:
            logger.warning("⚠️ Could not parse OpenAI version, proceeding anyway", error=str(e))
        
        logger.info("📦 Importing OpenAI Responses API components...")
        # ✅ ИСПРАВЛЕНО: Правильное название класса
        from .client import OpenAIResponsesClient
        from .models import (
            OpenAIResponsesAgent, 
            OpenAIResponsesResult, 
            OpenAIResponsesRequest,
            OpenAIResponsesContext,
            OpenAIResponsesConstants,
            OpenAIResponsesValidator
        )
        
        # ✅ ИСПРАВЛЕНО: Создаем реальный клиент Responses API с правильным классом
        logger.info("🔧 Creating OpenAI Responses API client instance...")
        openai_client = OpenAIResponsesClient()
        
        client_available = openai_client.is_available()
        logger.info("🔍 OpenAI Responses API client availability check", 
                   is_available=client_available,
                   client_type=type(openai_client).__name__)
        
        if client_available:
            logger.info("✅ OpenAI Responses API service initialized successfully")
        else:
            logger.warning("⚠️ OpenAI Responses API client created but API key not configured properly")
        
        __all__ = [
            'OpenAIResponsesClient',
            'OpenAIResponsesAgent', 
            'OpenAIResponsesResult',
            'OpenAIResponsesRequest',
            'OpenAIResponsesContext',
            'OpenAIResponsesConstants',
            'OpenAIResponsesValidator',
            'openai_client'
        ]
        
    except ImportError as e:
        logger.warning(f"❌ OpenAI library not installed or incompatible: {e}")
        logger.info("📦 Install with: pip install 'openai>=1.40.0'")
        logger.info("🔄 Falling back to stub client")
        
        # Используем заглушку
        openai_client = OpenAIResponsesClientStub()
        
        __all__ = ['openai_client']
        
    except Exception as e:
        logger.error(f"💥 Failed to initialize OpenAI Responses API client: {e}", 
                    exception_type=type(e).__name__,
                    exc_info=True)
        logger.info("🔄 Falling back to stub client")
        
        # Используем заглушку при любой другой ошибке
        openai_client = OpenAIResponsesClientStub()
        
        __all__ = ['openai_client']
        
else:
    logger.warning("❌ OPENAI_API_KEY not found in environment")
    logger.info("🔑 Add OPENAI_API_KEY to your .env file")
    logger.info("🔄 Using stub client")
    
    # Используем заглушку
    openai_client = OpenAIResponsesClientStub()
    
    __all__ = ['openai_client']

# Финальная информация о статусе сервиса
service_active = hasattr(openai_client, 'client') and openai_client.is_available()
service_status = '✅ Active (Responses API)' if service_active else '⚠️ Stub Mode'

logger.info(f"🏁 OpenAI Responses API Service Status: {service_status}", 
           service_type='responses_api' if service_active else 'stub',
           client_class=type(openai_client).__name__)

# Рекомендации для деплоя
if not OPENAI_API_KEY:
    logger.warning("🔧 DEPLOY RECOMMENDATION: Set OPENAI_API_KEY environment variable")
elif not service_active:
    logger.warning("🔧 DEPLOY RECOMMENDATION: Verify OpenAI library installation (>=1.40.0) and API key validity")

# Вывод информации о переходе на Responses API
logger.info("📈 OpenAI Responses API Benefits:")
logger.info("  • ✅ Automatic conversation context management on OpenAI servers")  
logger.info("  • ✅ Built-in tools: web search, code interpreter, file search")
logger.info("  • ✅ Token efficiency: no need to send full conversation history")
logger.info("  • ✅ Streaming support for real-time responses")
logger.info("  • ✅ Future-proof: OpenAI's recommended API for 2025+")
