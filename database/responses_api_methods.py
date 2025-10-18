"""
✅ НОВОЕ: Методы для работы с Responses API в базе данных
Автоматическое управление контекстом через response_id
"""

from typing import Optional, Dict, List
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from sqlalchemy.ext.declarative import DeclarativeMeta
from sqlalchemy.orm.attributes import flag_modified
import structlog

logger = structlog.get_logger()


class ResponsesAPIMethods:
    """
    ✅ НОВОЕ: Методы базы данных для работы с OpenAI Responses API
    Управление response_id для автоматического контекста разговоров
    """
    
    def __init__(self, db_instance):
        """Инициализация с экземпляром БД"""
        self.db = db_instance
    
    async def get_conversation_response_id(self, bot_id: str, user_id: int) -> Optional[str]:
        """
        ✅ НОВОЕ: Получить response_id последнего ответа для продолжения разговора
        
        Args:
            bot_id: ID бота
            user_id: ID пользователя Telegram
            
        Returns:
            str: response_id для продолжения разговора или None
        """
        try:
            async with self.db.get_session() as session:
                from database.models import UserBot
                
                logger.info("🔍 Getting conversation response_id from database", 
                           bot_id=bot_id, user_id=user_id)
                
                result = await session.execute(
                    select(UserBot.openai_conversation_contexts)
                    .where(UserBot.bot_id == bot_id)
                )
                
                bot_data = result.scalar_one_or_none()
                if not bot_data:
                    logger.warning("❌ Bot not found for response_id lookup", bot_id=bot_id)
                    return None
                
                if not bot_data:
                    logger.info("ℹ️ No conversation contexts found", bot_id=bot_id)
                    return None
                
                response_id = bot_data.get(str(user_id))
                
                logger.info("✅ Conversation response_id retrieved", 
                           bot_id=bot_id, 
                           user_id=user_id,
                           has_response_id=bool(response_id),
                           response_id_preview=response_id[:20] + "..." if response_id else None)
                
                return response_id
                
        except Exception as e:
            logger.error("💥 Error getting conversation response_id", 
                        bot_id=bot_id, 
                        user_id=user_id,
                        error=str(e),
                        error_type=type(e).__name__)
            return None

    async def save_conversation_response_id(self, bot_id: str, user_id: int, response_id: str) -> bool:
        """
        ✅ НОВОЕ: Сохранить response_id для продолжения разговора
        
        Args:
            bot_id: ID бота
            user_id: ID пользователя Telegram  
            response_id: response_id от OpenAI Responses API
            
        Returns:
            bool: True если успешно сохранено
        """
        try:
            async with self.db.get_session() as session:
                from database.models import UserBot
                
                logger.info("💾 Saving conversation response_id", 
                           bot_id=bot_id, 
                           user_id=user_id,
                           response_id_preview=response_id[:20] + "..." if response_id else None)
                
                # Получаем бота
                result = await session.execute(
                    select(UserBot).where(UserBot.bot_id == bot_id)
                )
                
                bot = result.scalar_one_or_none()
                if not bot:
                    logger.error("❌ Bot not found for response_id save", bot_id=bot_id)
                    return False
                
                # Обновляем contexts
                if not bot.openai_conversation_contexts:
                    bot.openai_conversation_contexts = {}
                
                bot.openai_conversation_contexts[str(user_id)] = response_id
                
                # Помечаем как измененное для SQLAlchemy
                flag_modified(bot, 'openai_conversation_contexts')
                
                await session.commit()
                
                logger.info("✅ Conversation response_id saved successfully", 
                           bot_id=bot_id, 
                           user_id=user_id,
                           total_conversations=len(bot.openai_conversation_contexts))
                
                return True
                
        except Exception as e:
            logger.error("💥 Error saving conversation response_id", 
                        bot_id=bot_id, 
                        user_id=user_id,
                        error=str(e),
                        error_type=type(e).__name__)
            return False

    async def clear_conversation_response_id(self, bot_id: str, user_id: int) -> bool:
        """
        ✅ НОВОЕ: Очистить response_id разговора
        
        Args:
            bot_id: ID бота
            user_id: ID пользователя Telegram
            
        Returns:
            bool: True если успешно очищено
        """
        try:
            async with self.db.get_session() as session:
                from database.models import UserBot
                
                logger.info("🧹 Clearing conversation response_id", 
                           bot_id=bot_id, user_id=user_id)
                
                result = await session.execute(
                    select(UserBot).where(UserBot.bot_id == bot_id)
                )
                
                bot = result.scalar_one_or_none()
                if not bot:
                    logger.warning("⚠️ Bot not found for response_id clear", bot_id=bot_id)
                    return True  # Считаем успехом если бота нет
                
                if not bot.openai_conversation_contexts:
                    logger.info("ℹ️ No conversation contexts to clear", bot_id=bot_id)
                    return True
                
                user_key = str(user_id)
                if user_key in bot.openai_conversation_contexts:
                    del bot.openai_conversation_contexts[user_key]
                    flag_modified(bot, 'openai_conversation_contexts')
                    await session.commit()
                    
                    logger.info("✅ Conversation response_id cleared successfully", 
                               bot_id=bot_id, 
                               user_id=user_id,
                               remaining_conversations=len(bot.openai_conversation_contexts))
                else:
                    logger.info("ℹ️ No response_id found for user", 
                               bot_id=bot_id, user_id=user_id)
                
                return True
                
        except Exception as e:
            logger.error("💥 Error clearing conversation response_id", 
                        bot_id=bot_id, 
                        user_id=user_id,
                        error=str(e),
                        error_type=type(e).__name__)
            return False

    async def clear_all_conversation_response_ids(self, bot_id: str) -> bool:
        """
        ✅ НОВОЕ: Очистить все response_id для бота
        
        Args:
            bot_id: ID бота
            
        Returns:
            bool: True если успешно очищено
        """
        try:
            async with self.db.get_session() as session:
                from database.models import UserBot
                
                logger.info("🧹 Clearing all conversation response_ids", bot_id=bot_id)
                
                result = await session.execute(
                    select(UserBot).where(UserBot.bot_id == bot_id)
                )
                
                bot = result.scalar_one_or_none()
                if not bot:
                    logger.warning("⚠️ Bot not found for clearing all response_ids", bot_id=bot_id)
                    return True
                
                conversations_count = len(bot.openai_conversation_contexts) if bot.openai_conversation_contexts else 0
                
                bot.openai_conversation_contexts = {}
                flag_modified(bot, 'openai_conversation_contexts')
                await session.commit()
                
                logger.info("✅ All conversation response_ids cleared", 
                           bot_id=bot_id, 
                           cleared_conversations=conversations_count)
                
                return True
                
        except Exception as e:
            logger.error("💥 Error clearing all conversation response_ids", 
                        bot_id=bot_id,
                        error=str(e),
                        error_type=type(e).__name__)
            return False

    async def get_openai_agent_config(self, assistant_id: str) -> Optional[Dict]:
        """
        ✅ НОВОЕ: Получить конфигурацию OpenAI агента для Responses API
        
        Args:
            assistant_id: ID ассистента (openai_agent_id)
            
        Returns:
            dict: Конфигурация агента или None
        """
        try:
            async with self.db.get_session() as session:
                from database.models import UserBot
                
                logger.info("🔍 Getting OpenAI agent config for Responses API", 
                           assistant_id=assistant_id)
                
                result = await session.execute(
                    select(UserBot)
                    .where(UserBot.openai_agent_id == assistant_id)
                )
                
                bot = result.scalar_one_or_none()
                if not bot:
                    logger.warning("❌ No agent found with assistant_id", 
                                  assistant_id=assistant_id)
                    return None
                
                # ✅ ФОРМИРУЕМ КОНФИГУРАЦИЮ ДЛЯ RESPONSES API
                config = {
                    'bot_id': bot.bot_id,
                    'name': bot.openai_agent_name,
                    'system_prompt': bot.openai_agent_instructions,
                    'model': bot.openai_model or 'gpt-4o',
                    'settings': bot.openai_settings or {},
                    'temperature': bot.openai_settings.get('temperature', 0.7) if bot.openai_settings else 0.7,
                    'max_tokens': bot.openai_settings.get('max_tokens', 4000) if bot.openai_settings else 4000,
                    
                    # ✅ RESPONSES API SPECIFIC SETTINGS
                    'store_conversations': bot.openai_store_conversations,
                    'conversation_retention': bot.openai_conversation_retention_days,
                    'enable_streaming': bot.openai_settings.get('enable_streaming', True) if bot.openai_settings else True,
                    
                    # ✅ ВСТРОЕННЫЕ ИНСТРУМЕНТЫ
                    'enable_web_search': bot.openai_settings.get('enable_web_search', False) if bot.openai_settings else False,
                    'enable_code_interpreter': bot.openai_settings.get('enable_code_interpreter', False) if bot.openai_settings else False,
                    'enable_file_search': bot.openai_settings.get('enable_file_search', False) if bot.openai_settings else False,
                    'enable_image_generation': bot.openai_settings.get('enable_image_generation', False) if bot.openai_settings else False,
                    'computer_use_enabled': bot.openai_settings.get('computer_use_enabled', False) if bot.openai_settings else False,
                    
                    # ✅ ДОПОЛНИТЕЛЬНЫЕ ПАРАМЕТРЫ
                    'vector_store_ids': bot.openai_settings.get('vector_store_ids', []) if bot.openai_settings else [],
                    'reasoning_effort': bot.openai_settings.get('reasoning_effort', 'medium') if bot.openai_settings else 'medium',
                    
                    # Метаданные
                    'created_at': bot.created_at.isoformat() if bot.created_at else None,
                    'updated_at': bot.updated_at.isoformat() if bot.updated_at else None,
                    'is_active': bot.ai_assistant_enabled
                }
                
                logger.info("✅ OpenAI agent config retrieved for Responses API", 
                           assistant_id=assistant_id,
                           agent_name=config['name'],
                           model=config['model'],
                           tools_enabled=sum([
                               config.get('enable_web_search', False),
                               config.get('enable_code_interpreter', False), 
                               config.get('enable_file_search', False),
                               config.get('enable_image_generation', False),
                               config.get('computer_use_enabled', False)
                           ]))
                
                return config
                
        except Exception as e:
            logger.error("💥 Error getting OpenAI agent config", 
                        assistant_id=assistant_id,
                        error=str(e),
                        error_type=type(e).__name__)
            return None

    async def get_active_conversations_count(self, bot_id: str) -> int:
        """
        ✅ НОВОЕ: Получить количество активных разговоров для бота
        
        Args:
            bot_id: ID бота
            
        Returns:
            int: Количество активных разговоров
        """
        try:
            async with self.db.get_session() as session:
                from database.models import UserBot
                
                result = await session.execute(
                    select(UserBot.openai_conversation_contexts)
                    .where(UserBot.bot_id == bot_id)
                )
                
                contexts = result.scalar_one_or_none()
                count = len(contexts) if contexts else 0
                
                logger.info("📊 Active conversations count", 
                           bot_id=bot_id, 
                           active_conversations=count)
                
                return count
                
        except Exception as e:
            logger.error("💥 Error getting active conversations count", 
                        bot_id=bot_id,
                        error=str(e))
            return 0

    async def get_conversation_users(self, bot_id: str) -> List[int]:
        """
        ✅ НОВОЕ: Получить список пользователей с активными разговорами
        
        Args:
            bot_id: ID бота
            
        Returns:
            List[int]: Список user_id с активными разговорами
        """
        try:
            async with self.db.get_session() as session:
                from database.models import UserBot
                
                result = await session.execute(
                    select(UserBot.openai_conversation_contexts)
                    .where(UserBot.bot_id == bot_id)
                )
                
                contexts = result.scalar_one_or_none()
                if not contexts:
                    return []
                
                user_ids = [int(user_id) for user_id in contexts.keys()]
                
                logger.info("👥 Conversation users retrieved", 
                           bot_id=bot_id, 
                           users_count=len(user_ids))
                
                return user_ids
                
        except Exception as e:
            logger.error("💥 Error getting conversation users", 
                        bot_id=bot_id,
                        error=str(e))
            return []

    async def update_agent_responses_settings(self, bot_id: str, settings: Dict) -> bool:
        """
        ✅ НОВОЕ: Обновить настройки Responses API для агента
        
        Args:
            bot_id: ID бота
            settings: Словарь с новыми настройками
            
        Returns:
            bool: True если успешно обновлено
        """
        try:
            async with self.db.get_session() as session:
                from database.models import UserBot
                
                logger.info("🔧 Updating agent Responses API settings", 
                           bot_id=bot_id,
                           settings_keys=list(settings.keys()))
                
                result = await session.execute(
                    select(UserBot).where(UserBot.bot_id == bot_id)
                )
                
                bot = result.scalar_one_or_none()
                if not bot:
                    logger.error("❌ Bot not found for settings update", bot_id=bot_id)
                    return False
                
                # Обновляем настройки
                if not bot.openai_settings:
                    bot.openai_settings = {}
                
                # Безопасное обновление настроек
                allowed_settings = [
                    'enable_web_search', 'enable_code_interpreter', 'enable_file_search',
                    'enable_image_generation', 'computer_use_enabled', 'vector_store_ids',
                    'reasoning_effort', 'temperature', 'max_tokens', 'enable_streaming',
                    'conversation_retention', 'store_conversations'
                ]
                
                updated_keys = []
                for key, value in settings.items():
                    if key in allowed_settings:
                        bot.openai_settings[key] = value
                        updated_keys.append(key)
                
                # Обновляем прямые поля если есть
                if 'conversation_retention' in settings:
                    bot.openai_conversation_retention_days = settings['conversation_retention']
                if 'store_conversations' in settings:
                    bot.openai_store_conversations = settings['store_conversations']
                
                flag_modified(bot, 'openai_settings')
                await session.commit()
                
                logger.info("✅ Agent Responses API settings updated", 
                           bot_id=bot_id,
                           updated_keys=updated_keys)
                
                return True
                
        except Exception as e:
            logger.error("💥 Error updating agent Responses API settings", 
                        bot_id=bot_id,
                        error=str(e))
            return False

    async def get_responses_api_stats(self, bot_id: str) -> Dict:
        """
        ✅ НОВОЕ: Получить статистику использования Responses API
        
        Args:
            bot_id: ID бота
            
        Returns:
            dict: Статистика использования
        """
        try:
            async with self.db.get_session() as session:
                from database.models import UserBot
                
                result = await session.execute(
                    select(UserBot).where(UserBot.bot_id == bot_id)
                )
                
                bot = result.scalar_one_or_none()
                if not bot:
                    return {}
                
                settings = bot.openai_settings or {}
                
                stats = {
                    # Основная информация
                    'bot_id': bot_id,
                    'agent_name': bot.openai_agent_name,
                    'model': bot.openai_model,
                    'is_active': bot.ai_assistant_enabled,
                    
                    # Responses API настройки
                    'using_responses_api': bot.openai_use_responses_api,
                    'store_conversations': bot.openai_store_conversations,
                    'conversation_retention_days': bot.openai_conversation_retention_days,
                    'enable_streaming': settings.get('enable_streaming', True),
                    
                    # Активные разговоры
                    'active_conversations': len(bot.openai_conversation_contexts) if bot.openai_conversation_contexts else 0,
                    
                    # Включенные инструменты
                    'enabled_tools': {
                        'web_search': settings.get('enable_web_search', False),
                        'code_interpreter': settings.get('enable_code_interpreter', False),
                        'file_search': settings.get('enable_file_search', False),
                        'image_generation': settings.get('enable_image_generation', False),
                        'computer_use': settings.get('computer_use_enabled', False)
                    },
                    
                    # Дополнительные параметры
                    'vector_stores_count': len(settings.get('vector_store_ids', [])),
                    'reasoning_effort': settings.get('reasoning_effort', 'medium'),
                    
                    # Статистика запросов
                    'total_requests': settings.get('total_requests', 0),
                    'successful_requests': settings.get('successful_requests', 0),
                    'failed_requests': settings.get('failed_requests', 0),
                    'last_request_at': settings.get('last_request_at'),
                    
                    # Временные метки
                    'created_at': bot.created_at.isoformat() if bot.created_at else None,
                    'updated_at': bot.updated_at.isoformat() if bot.updated_at else None,
                    'last_usage_at': bot.openai_last_usage_at.isoformat() if bot.openai_last_usage_at else None
                }
                
                # Рассчитываем success rate
                total_requests = stats['total_requests']
                if total_requests > 0:
                    stats['success_rate'] = (stats['successful_requests'] / total_requests) * 100
                else:
                    stats['success_rate'] = 0.0
                
                logger.info("📊 Responses API stats retrieved", 
                           bot_id=bot_id,
                           active_conversations=stats['active_conversations'],
                           enabled_tools_count=sum(stats['enabled_tools'].values()),
                           success_rate=stats['success_rate'])
                
                return stats
                
        except Exception as e:
            logger.error("💥 Error getting Responses API stats", 
                        bot_id=bot_id,
                        error=str(e))
            return {}
