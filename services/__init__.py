from .bot_manager import BotManager
from .user_bot import UserBot
from .funnel_manager import funnel_manager
from .message_scheduler import MessageScheduler
from .ai_assistant import ai_client, AIAssistantClient, AIAssistantError
from .mass_broadcast_service import MassBroadcastService  # ✅ НОВОЕ
from .mass_broadcast_scheduler import MassBroadcastScheduler  # ✅ НОВОЕ

# ✅ НОВОЕ: Безопасный импорт content_agent_service
try:
    from .content_agent import content_agent_service, ContentAgentService
    CONTENT_AGENT_AVAILABLE = True
except ImportError as e:
    content_agent_service = None
    ContentAgentService = None
    CONTENT_AGENT_AVAILABLE = False

__all__ = [
    "BotManager", 
    "UserBot", 
    "funnel_manager", 
    "MessageScheduler",
    "ai_client",
    "AIAssistantClient", 
    "AIAssistantError",
    "MassBroadcastService",  # ✅ НОВОЕ
    "MassBroadcastScheduler",  # ✅ НОВОЕ
    "content_agent_service",
    "ContentAgentService", 
    "CONTENT_AGENT_AVAILABLE"
]
