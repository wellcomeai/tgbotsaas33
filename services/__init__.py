from .bot_manager import BotManager
from .user_bot import UserBot
from .funnel_manager import funnel_manager
from .message_scheduler import MessageScheduler
from .ai_assistant import ai_client, AIAssistantClient, AIAssistantError

# ✅ НОВОЕ: Безопасный импорт content_agent_service
try:
    from .content_agent import content_agent_service, ContentAgentService
    CONTENT_AGENT_AVAILABLE = True
except ImportError as e:
    content_agent_service = None
    ContentAgentService = None
    CONTENT_AGENT_AVAILABLE = False
    
    # Логируем предупреждение если структлог доступен
    try:
        import structlog
        logger = structlog.get_logger()
        logger.warning("ContentAgentService not available", error=str(e))
    except ImportError:
        pass  # Структлог тоже может быть недоступен

__all__ = [
    "BotManager", 
    "UserBot", 
    "funnel_manager", 
    "MessageScheduler",
    "ai_client",
    "AIAssistantClient", 
    "AIAssistantError",
    # ✅ НОВЫЕ ЭКСПОРТЫ:
    "content_agent_service",
    "ContentAgentService", 
    "CONTENT_AGENT_AVAILABLE"
]
