"""
Database module providing unified access to all database operations.

Usage:
    from database import db, init_database, close_database
    
    # Initialize database
    await init_database()
    
    # Use database operations
    user = await db.get_user(123)
    bots = await db.get_user_bots(123)
    
    # Close database
    await close_database()
"""

from .connection import (
    # Database connection functions
    init_database,
    close_database, 
    get_db_session,
    
    # Main database manager
    DatabaseManager
)

# ===== UNIFIED DATABASE INTERFACE =====

class DB:
    """
    Unified database interface that routes to specialized managers.
    
    This class provides a single entry point for all database operations
    using specialized managers for different domains.
    """
    
    def __init__(self):
        # ✅ Initialize specialized managers with fallback to DatabaseManager
        try:
            from .managers.user_manager import UserManager
            self.users = UserManager()
        except ImportError:
            self.users = None
            
        try:
            from .managers.bot_manager import BotManager
            self.bots = BotManager()
        except ImportError:
            self.bots = None
            
        try:
            from .managers.ai_manager import AIManager
            self.ai = AIManager()
        except ImportError:
            self.ai = None
            
        try:
            from .managers.token_manager import TokenManager
            self.tokens = TokenManager()
        except ImportError:
            self.tokens = None
            
        try:
            from .managers.message_manager import MessageManager
            self.messages = MessageManager()
        except ImportError:
            self.messages = None
            
        try:
            from .managers.broadcast_manager import BroadcastManager
            self.broadcasts = BroadcastManager()
        except ImportError:
            self.broadcasts = None
            
        try:
            from .managers.cache_manager import CacheManager
            self.cache = CacheManager()
        except ImportError:
            self.cache = None

        try:
            from .managers.content_manager import ContentManager
            self.content = ContentManager()
        except ImportError:
            self.content = None
    
    # ===== USER OPERATIONS =====
    
    async def get_user(self, user_id: int):
        """Get user by ID"""
        if self.users:
            return await self.users.get_user(user_id)
        return await DatabaseManager.get_user(user_id)
    
    async def create_or_update_user(self, user_data: dict):
        """Create or update user"""
        if self.users:
            return await self.users.create_or_update_user(user_data)
        return await DatabaseManager.create_or_update_user(user_data)
    
    async def create_or_update_user_with_tokens(self, user_data: dict, admin_chat_id: int = None):
        """Create or update user with token initialization"""
        if self.users:
            return await self.users.create_or_update_user_with_tokens(user_data, admin_chat_id)
        return await DatabaseManager.create_or_update_user_with_tokens(user_data, admin_chat_id)
    
    async def check_user_subscription(self, user_id: int) -> bool:
        """Check if user has active subscription"""
        if self.users:
            return await self.users.check_user_subscription(user_id)
        return await DatabaseManager.check_user_subscription(user_id)
    
    async def update_user_subscription(self, user_id: int, plan: str, expires_at=None, active: bool = True):
        """Update user subscription"""
        if self.users:
            return await self.users.update_user_subscription(user_id, plan, expires_at, active)
        return await DatabaseManager.update_user_subscription(user_id, plan, expires_at, active)
    
    # ===== BOT OPERATIONS =====
    
    async def get_user_bots(self, user_id: int):
        """Get all bots for a user"""
        if self.bots:
            return await self.bots.get_user_bots(user_id)
        return await DatabaseManager.get_user_bots(user_id)
    
    async def create_user_bot(self, bot_data: dict):
        """Create a new user bot"""
        if self.bots:
            return await self.bots.create_user_bot(bot_data)
        return await DatabaseManager.create_user_bot(bot_data)
    
    async def get_bot_by_id(self, bot_id: str, fresh: bool = False):
        """Get bot by ID with optional fresh data"""
        if self.bots:
            return await self.bots.get_bot_by_id(bot_id, fresh)
        return await DatabaseManager.get_bot_by_id(bot_id, fresh)
    
    async def get_bot_full_config(self, bot_id: str, fresh: bool = False):
        """Get full bot configuration"""
        if self.bots:
            return await self.bots.get_bot_full_config(bot_id, fresh)
        return await DatabaseManager.get_bot_full_config(bot_id, fresh)
    
    async def update_bot_status(self, bot_id: str, status: str, is_running: bool = None):
        """Update bot status"""
        if self.bots:
            return await self.bots.update_bot_status(bot_id, status, is_running)
        return await DatabaseManager.update_bot_status(bot_id, status, is_running)
    
    async def get_all_active_bots(self):
        """Get all active bots"""
        if self.bots:
            return await self.bots.get_all_active_bots()
        return await DatabaseManager.get_all_active_bots()
    
    async def delete_user_bot(self, bot_id: str):
        """Delete user bot"""
        if self.bots:
            return await self.bots.delete_user_bot(bot_id)
        return await DatabaseManager.delete_user_bot(bot_id)
    
    # ===== AI OPERATIONS =====
    
    async def get_ai_config(self, bot_id: str):
        """Get AI configuration for bot"""
        if self.ai:
            return await self.ai.get_ai_config(bot_id)
        return await DatabaseManager.get_ai_config(bot_id)
    
    async def update_ai_assistant(self, bot_id: str, enabled: bool = True, assistant_id: str = None, settings: dict = None):
        """Update AI assistant configuration"""
        if self.ai:
            return await self.ai.update_ai_assistant(bot_id, enabled, assistant_id, settings)
        return await DatabaseManager.update_ai_assistant(bot_id, enabled, assistant_id, settings)
    
    async def save_openai_agent_config_responses_api(self, bot_id: str, agent_id: str, config: dict):
        """Save OpenAI agent configuration for Responses API"""
        if self.ai:
            return await self.ai.save_openai_agent_config_responses_api(bot_id, agent_id, config)
        return await DatabaseManager.save_openai_agent_config_responses_api(bot_id, agent_id, config)
    
    async def get_openai_agent_config(self, assistant_id: str):
        """Get OpenAI agent configuration"""
        if self.ai:
            return await self.ai.get_openai_agent_config(assistant_id)
        return await DatabaseManager.get_openai_agent_config(assistant_id)
    
    async def clear_ai_configuration(self, bot_id: str):
        """Clear AI configuration"""
        if self.ai:
            return await self.ai.clear_ai_configuration(bot_id)
        return await DatabaseManager.clear_ai_configuration(bot_id)
    
    # ===== TOKEN OPERATIONS =====
    
    async def save_token_usage(self, bot_id: str, input_tokens: int, output_tokens: int, admin_chat_id: int = None, user_id: int = None):
        """Save token usage for OpenAI"""
        if self.tokens:
            return await self.tokens.save_token_usage(bot_id, input_tokens, output_tokens, admin_chat_id, user_id)
        return await DatabaseManager.save_token_usage(bot_id, input_tokens, output_tokens, admin_chat_id, user_id)
    
    async def check_token_limit(self, user_id: int):
        """Check token limit for user"""
        if self.tokens:
            return await self.tokens.check_token_limit(user_id)
        return await DatabaseManager.check_token_limit(user_id)
    
    async def add_tokens_to_user(self, user_id: int, additional_tokens: int):
        """Add tokens to user"""
        if self.tokens:
            return await self.tokens.add_tokens_to_user(user_id, additional_tokens)
        return await DatabaseManager.add_tokens_to_user(user_id, additional_tokens)
    
    async def get_user_token_balance(self, user_id: int):
        """Get detailed user token balance"""
        if self.tokens:
            return await self.tokens.get_user_token_balance(user_id)
        return await DatabaseManager.get_user_token_balance(user_id)
    
    async def initialize_token_balance(self, user_id: int, admin_chat_id: int, bot_id: str = None):
        """Initialize token balance for user"""
        if self.tokens:
            return await self.tokens.initialize_token_balance(user_id, admin_chat_id, bot_id)
        return await DatabaseManager.initialize_token_balance(user_id, admin_chat_id, bot_id)
    
    # ===== MESSAGE OPERATIONS =====
    
    async def update_bot_messages(self, bot_id: str, welcome_message: str = None, goodbye_message: str = None):
        """Update bot messages"""
        if self.messages:
            return await self.messages.update_bot_messages(bot_id, welcome_message, goodbye_message)
        return await DatabaseManager.update_bot_messages(bot_id, welcome_message, goodbye_message)
    
    async def update_welcome_settings(self, bot_id: str, welcome_message: str = None, welcome_button_text: str = None, confirmation_message: str = None):
        """Update welcome settings"""
        if self.messages:
            return await self.messages.update_welcome_settings(bot_id, welcome_message, welcome_button_text, confirmation_message)
        return await DatabaseManager.update_welcome_settings(bot_id, welcome_message, welcome_button_text, confirmation_message)
    
    async def update_goodbye_settings(self, bot_id: str, goodbye_message: str = None, goodbye_button_text: str = None, goodbye_button_url: str = None):
        """Update goodbye settings"""
        if self.messages:
            return await self.messages.update_goodbye_settings(bot_id, goodbye_message, goodbye_button_text, goodbye_button_url)
        return await DatabaseManager.update_goodbye_settings(bot_id, goodbye_message, goodbye_button_text, goodbye_button_url)
    
    # ===== BROADCAST OPERATIONS =====
    
    async def create_broadcast_sequence(self, bot_id: str):
        """Create broadcast sequence"""
        if self.broadcasts:
            return await self.broadcasts.create_broadcast_sequence(bot_id)
        return await DatabaseManager.create_broadcast_sequence(bot_id)
    
    async def get_broadcast_sequence(self, bot_id: str):
        """Get broadcast sequence"""
        if self.broadcasts:
            return await self.broadcasts.get_broadcast_sequence(bot_id)
        return await DatabaseManager.get_broadcast_sequence(bot_id)
    
    async def create_broadcast_message(self, sequence_id: int, message_number: int, message_text: str, delay_hours: float, **kwargs):
        """Create broadcast message"""
        if self.broadcasts:
            return await self.broadcasts.create_broadcast_message(sequence_id, message_number, message_text, delay_hours, **kwargs)
        return await DatabaseManager.create_broadcast_message(sequence_id, message_number, message_text, delay_hours, **kwargs)
    
    async def schedule_broadcast_messages_for_subscriber(self, bot_id: str, subscriber_id: int, sequence_id: int):
        """Schedule broadcast messages for subscriber"""
        if self.broadcasts:
            return await self.broadcasts.schedule_broadcast_messages_for_subscriber(bot_id, subscriber_id, sequence_id)
        return await DatabaseManager.schedule_broadcast_messages_for_subscriber(bot_id, subscriber_id, sequence_id)
    
    # ===== CACHE OPERATIONS =====
    
    async def refresh_bot_data(self, bot_id: str):
        """Force refresh bot data from database"""
        if self.cache:
            return await self.cache.refresh_bot_data(bot_id)
        return await DatabaseManager.refresh_bot_data(bot_id)
    
    async def expire_bot_cache(self, bot_id: str):
        """Expire bot cache"""
        if self.cache:
            return await self.cache.expire_bot_cache(bot_id)
        return await DatabaseManager.expire_bot_cache(bot_id)
    
    async def get_fresh_bot_data(self, bot_id: str):
        """Get always fresh bot data (no cache)"""
        if self.cache:
            return await self.cache.get_fresh_bot_data(bot_id)
        return await DatabaseManager.get_fresh_bot_data(bot_id)
    
    # ===== CONTENT AGENT OPERATIONS =====
    
    async def create_content_agent(self, bot_id: str, agent_name: str, instructions: str, openai_agent_id: str = None):
        """Create content agent"""
        if self.content:
            return await self.content.create_content_agent(bot_id, agent_name, instructions, openai_agent_id)
        return None
    
    async def get_content_agent(self, bot_id: str):
        """Get content agent by bot_id"""
        if self.content:
            return await self.content.get_content_agent(bot_id)
        return None
    
    async def update_content_agent(self, bot_id: str, agent_name: str = None, instructions: str = None, openai_agent_id: str = None):
        """Update content agent"""
        if self.content:
            return await self.content.update_content_agent(bot_id, agent_name, instructions, openai_agent_id)
        return False
    
    async def delete_content_agent(self, bot_id: str, soft_delete: bool = True):
        """Delete content agent"""
        if self.content:
            return await self.content.delete_content_agent(bot_id, soft_delete)
        return False
    
    async def has_content_agent(self, bot_id: str):
        """Check if content agent exists"""
        if self.content:
            return await self.content.has_content_agent(bot_id)
        return False
    
    async def process_content_rewrite(self, bot_id: str, original_text: str, media_info: dict = None, user_id: int = None):
        """Process content rewrite"""
        if self.content:
            return await self.content.process_content_rewrite(bot_id, original_text, media_info, user_id)
        return None
    
    async def get_content_agent_stats(self, bot_id: str):
        """Get content agent statistics"""
        if self.content:
            return await self.content.get_content_agent_stats(bot_id)
        return {'exists': False, 'error': 'ContentManager not available'}
    
    # ===== CONVERSATION OPERATIONS (RESPONSES API) =====
    
    async def save_conversation_response_id(self, bot_id: str, user_id: int, response_id: str):
        """Save conversation response_id for Responses API"""
        if self.ai:
            return await self.ai.save_conversation_response_id(bot_id, user_id, response_id)
        return await DatabaseManager.save_conversation_response_id(bot_id, user_id, response_id)
    
    async def get_conversation_response_id(self, bot_id: str, user_id: int):
        """Get conversation response_id"""
        if self.ai:
            return await self.ai.get_conversation_response_id(bot_id, user_id)
        return await DatabaseManager.get_conversation_response_id(bot_id, user_id)
    
    async def clear_conversation_response_id(self, bot_id: str, user_id: int):
        """Clear conversation response_id"""
        if self.ai:
            return await self.ai.clear_conversation_response_id(bot_id, user_id)
        return await DatabaseManager.clear_conversation_response_id(bot_id, user_id)
    
    # ===== FALLBACK FOR MISSING METHODS =====
    
    def __getattr__(self, name):
        """
        Fallback for any missing methods - delegate to appropriate manager or DatabaseManager.
        This ensures backward compatibility while we refactor.
        """
        # Try to find method in specialized managers first
        for manager_name, manager in [
            ('users', self.users),
            ('bots', self.bots), 
            ('ai', self.ai),
            ('tokens', self.tokens),
            ('messages', self.messages),
            ('broadcasts', self.broadcasts),
            ('cache', self.cache),
            ('content', self.content)
        ]:
            if manager and hasattr(manager, name):
                return getattr(manager, name)
        
        # Fallback to DatabaseManager
        if hasattr(DatabaseManager, name):
            return getattr(DatabaseManager, name)
        else:
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")
    
    # ===== DIRECT MANAGER ACCESS =====
    
    @property
    def user_manager(self):
        """Direct access to user manager"""
        return self.users or DatabaseManager
    
    @property 
    def bot_manager(self):
        """Direct access to bot manager"""
        return self.bots or DatabaseManager
        
    @property
    def ai_manager(self):
        """Direct access to AI manager"""
        return self.ai or DatabaseManager
        
    @property
    def token_manager(self):
        """Direct access to token manager"""
        return self.tokens or DatabaseManager
        
    @property
    def message_manager(self):
        """Direct access to message manager"""
        return self.messages or DatabaseManager
        
    @property
    def broadcast_manager(self):
        """Direct access to broadcast manager"""
        return self.broadcasts or DatabaseManager
        
    @property
    def cache_manager(self):
        """Direct access to cache manager"""
        return self.cache or DatabaseManager

    @property
    def content_manager(self):
        """Direct access to content manager"""
        return self.content or DatabaseManager


# ===== MAIN DATABASE INSTANCE =====

# Global database instance for easy importing
db = DB()

# ===== EXPORTS =====

__all__ = [
    # Database connection
    'init_database',
    'close_database', 
    'get_db_session',
    
    # Main interface
    'db',
    'DB',
    
    # Direct access to manager (for migration period)
    'DatabaseManager',
]

# ===== CONVENIENCE IMPORTS =====

# Allow direct import of main functions
from .connection import init_database, close_database

# ===== PRODUCTION-READY STATUS =====

def get_managers_status():
    """Get status of all specialized managers for debugging"""
    return {
        'users': db.users is not None,
        'bots': db.bots is not None, 
        'ai': db.ai is not None,
        'tokens': db.tokens is not None,
        'messages': db.messages is not None,
        'broadcasts': db.broadcasts is not None,
        'cache': db.cache is not None,
        'content': db.content is not None,
        'fallback_active': any([
            db.users is None,
            db.bots is None,
            db.ai is None, 
            db.tokens is None,
            db.messages is None,
            db.broadcasts is None,
            db.cache is None,
            db.content is None
        ])
    }
