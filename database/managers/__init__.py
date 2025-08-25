"""
Database managers module - specialized database operation managers.

This module contains specialized managers for different database operations:

- UserManager: User operations (registration, subscriptions, tokens)
- BotManager: Bot operations (creation, configuration, status)  
- AIManager: AI assistant operations (OpenAI, ChatForYou, ProTalk)
- TokenManager: Token usage tracking and limits
- MessageManager: Bot messages and settings
- BroadcastManager: Broadcast sequences and scheduled messages
- CacheManager: Cache operations and data refresh
- ContentManager: Content agents operations (OpenAI content rewriting)

Each manager is responsible for its specific domain of operations.
"""

import structlog
from typing import Optional, Dict, Any

logger = structlog.get_logger()

# ===== MANAGER IMPORTS WITH GRACEFUL FALLBACK =====

# Import existing managers
try:
    from .user_manager import UserManager
    USER_MANAGER_AVAILABLE = True
    logger.info("✅ UserManager loaded successfully")
except ImportError as e:
    USER_MANAGER_AVAILABLE = False
    logger.warning("❌ UserManager not available", error=str(e))
    UserManager = None

# Bot Manager
try:
    from .bot_manager import BotManager
    BOT_MANAGER_AVAILABLE = True
    logger.info("✅ BotManager loaded successfully")
except ImportError as e:
    BOT_MANAGER_AVAILABLE = False
    logger.warning("❌ BotManager not available", error=str(e))
    BotManager = None

# AI Manager
try:
    from .ai_manager import AIManager
    AI_MANAGER_AVAILABLE = True
    logger.info("✅ AIManager loaded successfully")
except ImportError as e:
    AI_MANAGER_AVAILABLE = False
    logger.warning("❌ AIManager not available", error=str(e))
    AIManager = None

# Token Manager
try:
    from .token_manager import TokenManager
    TOKEN_MANAGER_AVAILABLE = True
    logger.info("✅ TokenManager loaded successfully")
except ImportError as e:
    TOKEN_MANAGER_AVAILABLE = False
    logger.warning("❌ TokenManager not available", error=str(e))
    TokenManager = None

# Message Manager
try:
    from .message_manager import MessageManager
    MESSAGE_MANAGER_AVAILABLE = True
    logger.info("✅ MessageManager loaded successfully")
except ImportError as e:
    MESSAGE_MANAGER_AVAILABLE = False
    logger.warning("❌ MessageManager not available", error=str(e))
    MessageManager = None

# Broadcast Manager
try:
    from .broadcast_manager import BroadcastManager
    BROADCAST_MANAGER_AVAILABLE = True
    logger.info("✅ BroadcastManager loaded successfully")
except ImportError as e:
    BROADCAST_MANAGER_AVAILABLE = False
    logger.warning("❌ BroadcastManager not available", error=str(e))
    BroadcastManager = None

# Cache Manager
try:
    from .cache_manager import CacheManager
    CACHE_MANAGER_AVAILABLE = True
    logger.info("✅ CacheManager loaded successfully")
except ImportError as e:
    CACHE_MANAGER_AVAILABLE = False
    logger.warning("❌ CacheManager not available", error=str(e))
    CacheManager = None

# Content Manager
try:
    from .content_manager import ContentManager
    CONTENT_MANAGER_AVAILABLE = True
    logger.info("✅ ContentManager loaded successfully")
except ImportError as e:
    CONTENT_MANAGER_AVAILABLE = False
    logger.warning("❌ ContentManager not available", error=str(e))
    ContentManager = None

# ===== MANAGER REGISTRY =====

MANAGER_REGISTRY = {
    'users': {
        'class': UserManager,
        'available': USER_MANAGER_AVAILABLE,
        'description': 'User operations (registration, subscriptions, tokens)'
    },
    'bots': {
        'class': BotManager,
        'available': BOT_MANAGER_AVAILABLE,
        'description': 'Bot operations (creation, configuration, status)'
    },
    'ai': {
        'class': AIManager,
        'available': AI_MANAGER_AVAILABLE,
        'description': 'AI assistant operations (OpenAI, ChatForYou, ProTalk)'
    },
    'tokens': {
        'class': TokenManager,
        'available': TOKEN_MANAGER_AVAILABLE,
        'description': 'Token usage tracking and limits'
    },
    'messages': {
        'class': MessageManager,
        'available': MESSAGE_MANAGER_AVAILABLE,
        'description': 'Bot messages and settings'
    },
    'broadcasts': {
        'class': BroadcastManager,
        'available': BROADCAST_MANAGER_AVAILABLE,
        'description': 'Broadcast sequences and scheduled messages'
    },
    'cache': {
        'class': CacheManager,
        'available': CACHE_MANAGER_AVAILABLE,
        'description': 'Cache operations and data refresh'
    },
    'content': {
        'class': ContentManager,
        'available': CONTENT_MANAGER_AVAILABLE,
        'description': 'Content agents operations (OpenAI content rewriting)'
    }
}

# ===== UTILITY FUNCTIONS =====

def get_available_managers() -> Dict[str, Any]:
    """Get list of available managers"""
    return {
        name: info for name, info in MANAGER_REGISTRY.items() 
        if info['available']
    }

def get_unavailable_managers() -> Dict[str, Any]:
    """Get list of unavailable managers"""
    return {
        name: info for name, info in MANAGER_REGISTRY.items() 
        if not info['available']
    }

def get_manager_status() -> Dict[str, bool]:
    """Get status of all managers for debugging"""
    return {
        name: info['available'] 
        for name, info in MANAGER_REGISTRY.items()
    }

def get_manager_by_name(name: str) -> Optional[Any]:
    """Get manager class by name"""
    if name in MANAGER_REGISTRY and MANAGER_REGISTRY[name]['available']:
        return MANAGER_REGISTRY[name]['class']
    return None

def is_manager_available(name: str) -> bool:
    """Check if specific manager is available"""
    return MANAGER_REGISTRY.get(name, {}).get('available', False)

def get_managers_summary() -> Dict[str, Any]:
    """Get comprehensive summary of all managers"""
    available = get_available_managers()
    unavailable = get_unavailable_managers()
    
    return {
        'total_managers': len(MANAGER_REGISTRY),
        'available_count': len(available),
        'unavailable_count': len(unavailable),
        'available_managers': list(available.keys()),
        'unavailable_managers': list(unavailable.keys()),
        'availability_percentage': round((len(available) / len(MANAGER_REGISTRY)) * 100, 1),
        'status': 'full' if len(unavailable) == 0 else 'partial' if len(available) > 0 else 'none'
    }

# ===== MANAGER FACTORY =====

class ManagerFactory:
    """Factory for creating manager instances"""
    
    @staticmethod
    def create_user_manager():
        """Create UserManager instance"""
        if USER_MANAGER_AVAILABLE:
            return UserManager()
        return None
    
    @staticmethod
    def create_bot_manager():
        """Create BotManager instance"""
        if BOT_MANAGER_AVAILABLE:
            return BotManager()
        return None
    
    @staticmethod
    def create_ai_manager():
        """Create AIManager instance"""
        if AI_MANAGER_AVAILABLE:
            return AIManager()
        return None
    
    @staticmethod
    def create_token_manager():
        """Create TokenManager instance"""
        if TOKEN_MANAGER_AVAILABLE:
            return TokenManager()
        return None
    
    @staticmethod
    def create_message_manager():
        """Create MessageManager instance"""
        if MESSAGE_MANAGER_AVAILABLE:
            return MessageManager()
        return None
    
    @staticmethod
    def create_broadcast_manager():
        """Create BroadcastManager instance"""
        if BROADCAST_MANAGER_AVAILABLE:
            return BroadcastManager()
        return None
    
    @staticmethod
    def create_cache_manager():
        """Create CacheManager instance"""
        if CACHE_MANAGER_AVAILABLE:
            return CacheManager()
        return None
    
    @staticmethod
    def create_content_manager():
        """Create ContentManager instance"""
        if CONTENT_MANAGER_AVAILABLE:
            return ContentManager()
        return None
    
    @staticmethod
    def create_all_managers() -> Dict[str, Any]:
        """Create all available manager instances"""
        managers = {}
        
        if USER_MANAGER_AVAILABLE:
            managers['users'] = UserManager()
        if BOT_MANAGER_AVAILABLE:
            managers['bots'] = BotManager()
        if AI_MANAGER_AVAILABLE:
            managers['ai'] = AIManager()
        if TOKEN_MANAGER_AVAILABLE:
            managers['tokens'] = TokenManager()
        if MESSAGE_MANAGER_AVAILABLE:
            managers['messages'] = MessageManager()
        if BROADCAST_MANAGER_AVAILABLE:
            managers['broadcasts'] = BroadcastManager()
        if CACHE_MANAGER_AVAILABLE:
            managers['cache'] = CacheManager()
        if CONTENT_MANAGER_AVAILABLE:
            managers['content'] = ContentManager()
        
        return managers

# ===== MANAGER VALIDATOR =====

def validate_managers() -> Dict[str, Any]:
    """Validate all managers and their required methods"""
    validation_results = {}
    
    for name, info in MANAGER_REGISTRY.items():
        if not info['available']:
            validation_results[name] = {
                'status': 'unavailable',
                'error': 'Manager not imported'
            }
            continue
        
        manager_class = info['class']
        validation_results[name] = {
            'status': 'available',
            'class_name': manager_class.__name__,
            'module': manager_class.__module__,
            'methods': [method for method in dir(manager_class) if not method.startswith('_')],
            'static_methods': [
                method for method in dir(manager_class) 
                if not method.startswith('_') and 
                isinstance(getattr(manager_class, method), staticmethod)
            ]
        }
    
    return validation_results

# ===== INITIALIZATION LOGGING =====

def log_managers_initialization():
    """Log manager initialization status"""
    summary = get_managers_summary()
    
    logger.info("📊 Database Managers Initialization Summary",
               total_managers=summary['total_managers'],
               available_count=summary['available_count'],
               unavailable_count=summary['unavailable_count'],
               availability_percentage=summary['availability_percentage'],
               status=summary['status'])
    
    if summary['available_managers']:
        logger.info("✅ Available managers", managers=summary['available_managers'])
    
    if summary['unavailable_managers']:
        logger.warning("❌ Unavailable managers", managers=summary['unavailable_managers'])
    
    return summary

# ===== EXPORTS =====

__all__ = [
    # Manager classes (if available)
    'UserManager',
    'BotManager', 
    'AIManager',
    'TokenManager',
    'MessageManager',
    'BroadcastManager',
    'CacheManager',
    'ContentManager',
    
    # Manager registry and utilities
    'MANAGER_REGISTRY',
    'get_available_managers',
    'get_unavailable_managers', 
    'get_manager_status',
    'get_manager_by_name',
    'is_manager_available',
    'get_managers_summary',
    
    # Factory and validation
    'ManagerFactory',
    'validate_managers',
    'log_managers_initialization',
    
    # Availability flags
    'USER_MANAGER_AVAILABLE',
    'BOT_MANAGER_AVAILABLE',
    'AI_MANAGER_AVAILABLE',
    'TOKEN_MANAGER_AVAILABLE',
    'MESSAGE_MANAGER_AVAILABLE',
    'BROADCAST_MANAGER_AVAILABLE',
    'CACHE_MANAGER_AVAILABLE',
    'CONTENT_MANAGER_AVAILABLE'
]

# ===== AUTOMATIC INITIALIZATION LOGGING =====

# Log initialization status when module is imported
initialization_summary = log_managers_initialization()
