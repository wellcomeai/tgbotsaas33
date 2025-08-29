"""
AI Manager - handles all AI assistant related database operations.

Responsibilities:
- OpenAI agent configuration and management (Responses API)
- External AI platforms (ChatForYou, ProTalk) management
- AI conversation tracking and context management
- AI assistant settings and statistics
- AI platform detection and validation
- AI configuration synchronization and validation
- Vector Store and Knowledge Base management
"""

from datetime import datetime
from typing import Optional, Dict, Tuple, Any, List
from sqlalchemy import select, update, func, text
from sqlalchemy.sql import text
import structlog

from ..connection import get_db_session

logger = structlog.get_logger()


class AIManager:
    """Manager for AI assistant related database operations"""
    
    # ===== OPENAI RESPONSES API METHODS =====
    
    @staticmethod
    async def save_openai_agent_config_responses_api(bot_id: str, agent_id: str, config: Dict) -> bool:
        """✅ ИСПРАВЛЕНО: Сохранение конфигурации OpenAI агента с правильной синхронизацией"""
        from database.models import UserBot
        
        try:
            async with get_db_session() as session:
                # Генерируем полный системный промпт из конфигурации
                agent_name = config.get('agent_name', config.get('name', 'AI Ассистент'))
                agent_role = config.get('agent_role', config.get('system_prompt', 'Полезный помощник'))
                
                # Генерируем полный системный промпт
                if 'system_prompt' in config and config['system_prompt']:
                    full_system_prompt = config['system_prompt']
                else:
                    full_system_prompt = f"Ты - {agent_role}. Твое имя {agent_name}. Отвечай полезно и дружелюбно."
                
                # Обновляем конфигурацию с полным промптом
                updated_config = config.copy()
                updated_config.update({
                    'system_prompt': full_system_prompt,
                    'agent_name': agent_name,
                    'generation_method': 'auto_generated' if 'system_prompt' not in config else 'provided'
                })
                
                logger.info("💾 Saving OpenAI agent with full sync", 
                           bot_id=bot_id,
                           agent_id=agent_id,
                           agent_name=agent_name)
                
                # ✅ КРИТИЧНО: Синхронизируем ВСЕ поля для правильной работы
                await session.execute(
                    update(UserBot)
                    .where(UserBot.bot_id == bot_id)
                    .values(
                        # ✅ ОСНОВНЫЕ ПОЛЯ - КРИТИЧНО ДЛЯ РАБОТЫ
                        ai_assistant_type='openai',
                        ai_assistant_enabled=True,  # ✅ КРИТИЧНО: Включаем агента
                        
                        # ✅ OPENAI ПОЛЯ - СИНХРОНИЗИРОВАНЫ
                        openai_agent_id=agent_id,  # ✅ КРИТИЧНО: ID агента
                        openai_agent_name=agent_name,
                        openai_agent_instructions=full_system_prompt,
                        openai_model=config.get('model', config.get('model_used', 'gpt-4o')),
                        
                        # ✅ RESPONSES API НАСТРОЙКИ
                        openai_use_responses_api=True,
                        openai_store_conversations=config.get('store_conversations', True),
                        openai_conversation_retention_days=config.get('conversation_retention', 30),
                        openai_conversation_contexts={},  # Сбрасываем старые контексты
                        
                        # ✅ JSON СОДЕРЖИТ ВСЕ ДАННЫЕ
                        openai_settings=updated_config,
                        
                        # ✅ ОЧИЩАЕМ ВНЕШНИЕ ПЛАТФОРМЫ
                        external_api_token=None,
                        external_bot_id=None,
                        external_platform=None,
                        external_settings=None,
                        
                        # ✅ ВРЕМЯ ОБНОВЛЕНИЯ
                        updated_at=datetime.now()
                    )
                )
                await session.commit()
                
                logger.info("✅ OpenAI agent config saved with complete sync", 
                           bot_id=bot_id,
                           agent_id=agent_id,
                           agent_name=agent_name,
                           ai_enabled=True,  # Логируем что включили
                           system_prompt_length=len(full_system_prompt))
                
                return True
                
        except Exception as e:
            logger.error("💥 Failed to save OpenAI agent config", 
                        bot_id=bot_id,
                        agent_id=agent_id,
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            return False

    # ✅ НОВЫЙ МЕТОД: Диагностика состояния агента
    @staticmethod
    async def diagnose_agent_state(bot_id: str) -> Dict:
        """Диагностика состояния ИИ агента в БД"""
        from database.models import UserBot
        
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    select(
                        UserBot.ai_assistant_enabled,
                        UserBot.ai_assistant_type,
                        UserBot.openai_agent_id,
                        UserBot.openai_agent_name,
                        UserBot.openai_agent_instructions,
                        UserBot.openai_model,
                        UserBot.openai_settings,
                        UserBot.external_api_token,
                        UserBot.external_bot_id,
                        UserBot.external_platform
                    ).where(UserBot.bot_id == bot_id)
                )
                
                row = result.first()
                if not row:
                    return {'status': 'bot_not_found'}
                
                diagnosis = {
                    'bot_id': bot_id,
                    'ai_assistant_enabled': row.ai_assistant_enabled,
                    'ai_assistant_type': row.ai_assistant_type,
                    'openai_fields': {
                        'agent_id': row.openai_agent_id,
                        'agent_name': row.openai_agent_name,
                        'has_instructions': bool(row.openai_agent_instructions),
                        'model': row.openai_model,
                        'has_settings': bool(row.openai_settings)
                    },
                    'external_fields': {
                        'api_token': bool(row.external_api_token),
                        'bot_id': row.external_bot_id,
                        'platform': row.external_platform
                    }
                }
                
                # Определяем статус
                if row.ai_assistant_type == 'openai':
                    if row.ai_assistant_enabled and row.openai_agent_id:
                        diagnosis['status'] = 'openai_configured'
                    elif row.ai_assistant_enabled:
                        diagnosis['status'] = 'openai_enabled_no_agent'
                    else:
                        diagnosis['status'] = 'openai_disabled'
                elif row.ai_assistant_type in ['chatforyou', 'protalk']:
                    if row.ai_assistant_enabled and row.external_api_token:
                        diagnosis['status'] = 'external_configured'
                    else:
                        diagnosis['status'] = 'external_incomplete'
                else:
                    diagnosis['status'] = 'no_agent_type'
                
                logger.info("🔍 Agent diagnosis completed", 
                           bot_id=bot_id,
                           status=diagnosis['status'],
                           ai_enabled=diagnosis['ai_assistant_enabled'],
                           ai_type=diagnosis['ai_assistant_type'])
                
                return diagnosis
                
        except Exception as e:
            logger.error("💥 Failed to diagnose agent state", 
                        bot_id=bot_id,
                        error=str(e))
            return {'status': 'error', 'error': str(e)}

    @staticmethod
    async def recreate_openai_agent(bot_id: str, old_assistant_id: str, new_config: Dict) -> bool:
        """✅ ДОБАВИТЬ: Пересоздание OpenAI агента с новой конфигурацией"""
        try:
            # 1. Удаляем старую конфигурацию
            await AIManager.clear_ai_configuration(bot_id)
            
            # 2. Создаем новую конфигурацию
            success = await AIManager.save_openai_agent_config_responses_api(
                bot_id=bot_id,
                agent_id=new_config['agent_id'],
                config=new_config
            )
            
            if success:
                logger.info("✅ Agent recreated successfully", 
                           bot_id=bot_id,
                           old_id=old_assistant_id,
                           new_id=new_config['agent_id'])
                return True
            
            return False
            
        except Exception as e:
            logger.error("💥 Failed to recreate agent", 
                        bot_id=bot_id,
                        error=str(e))
            return False

    @staticmethod
    async def get_openai_agent_config_responses_api(assistant_id: str) -> Optional[Dict]:
        """✅ ИСПРАВЛЕНО: Получение конфигурации с поиском в обеих таблицах"""
        from database.models import UserBot
        
        try:
            async with get_db_session() as session:
                # ✅ СНАЧАЛА ИЩЕМ В ОСНОВНОЙ ТАБЛИЦЕ user_bots (основные AI агенты)
                result = await session.execute(
                    select(
                        UserBot.bot_id,
                        UserBot.openai_agent_id,
                        UserBot.openai_agent_name,
                        UserBot.openai_agent_instructions,
                        UserBot.openai_model,
                        UserBot.openai_settings,
                        UserBot.openai_store_conversations,
                        UserBot.openai_conversation_retention_days,
                        UserBot.openai_admin_chat_id,
                        UserBot.ai_assistant_enabled,
                        UserBot.ai_assistant_type
                    ).where(
                        UserBot.openai_agent_id == assistant_id
                    )
                )
                
                row = result.first()
                if row and row.ai_assistant_enabled and row.ai_assistant_type == 'openai':
                    # Найден основной AI агент - возвращаем его конфигурацию
                    logger.info("✅ Found main AI agent", assistant_id=assistant_id)
                    return await AIManager._build_agent_config_from_user_bot_row(row)
                
                # ✅ НОВОЕ: ЕСЛИ НЕ НАЙДЕН В user_bots, ИЩЕМ В content_agents
                content_agent_query = text("""
                    SELECT 
                        ca.bot_id,
                        ca.openai_agent_id,
                        ca.agent_name,
                        ca.instructions,
                        'gpt-4o' as model,
                        ub.openai_admin_chat_id,
                        ub.user_id
                    FROM content_agents ca
                    JOIN user_bots ub ON ca.bot_id = ub.bot_id
                    WHERE ca.openai_agent_id = :assistant_id 
                    AND ca.is_active = true
                """)
                
                content_result = await session.execute(content_agent_query, {'assistant_id': assistant_id})
                content_row = content_result.first()
                
                if content_row:
                    # Найден контент-агент - возвращаем его конфигурацию
                    logger.info("✅ Found content agent", assistant_id=assistant_id)
                    
                    config = {
                        'bot_id': content_row[0],
                        'agent_id': content_row[1],
                        'name': content_row[2],
                        'system_prompt': content_row[3],
                        'model': content_row[4],
                        'admin_chat_id': content_row[5],
                        
                        # Настройки по умолчанию для контент-агента
                        'store_conversations': True,
                        'conversation_retention': 30,
                        'enable_streaming': True,
                        
                        # Параметры модели
                        'temperature': 0.7,
                        'max_tokens': 4000,
                        'top_p': 1.0,
                        'frequency_penalty': 0.0,
                        'presence_penalty': 0.0,
                        
                        # Встроенные инструменты
                        'enable_web_search': False,
                        'enable_code_interpreter': False,
                        'enable_file_search': False,
                        'enable_image_generation': False,
                        
                        # Статус агента
                        'enabled': True,
                        'type': 'content_agent',
                        'agent_source': 'content_agents_table',  # Маркер источника
                        
                        'settings': {
                            'agent_type': 'content_agent',
                            'source_table': 'content_agents'
                        }
                    }
                    
                    return config
                
                # Агент не найден ни в одной таблице
                logger.warning("❌ OpenAI agent not found in any table", assistant_id=assistant_id)
                return None
                        
        except Exception as e:
            logger.error("💥 Failed to get OpenAI agent config", 
                        assistant_id=assistant_id,
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            return None

    @staticmethod
    async def _build_agent_config_from_user_bot_row(row) -> Dict:
        """✅ ИСПРАВЛЕНО: Создание конфигурации из строки БД с правильными vector_store_ids"""
        settings = row.openai_settings or {}
        
        agent_name = (
            settings.get('agent_name') or 
            row.openai_agent_name or 
            'AI Ассистент'
        )
        
        system_prompt = (
            settings.get('system_prompt') or 
            row.openai_agent_instructions or 
            f"Ты - {settings.get('agent_role', 'полезный помощник')}. Твое имя {agent_name}. Отвечай полезно и дружелюбно."
        )
        
        model_name = (
            settings.get('model_used') or 
            settings.get('model') or 
            row.openai_model or 
            'gpt-4o'
        )
        
        # ✅ ИСПРАВЛЕНО: Правильное извлечение vector_store_ids
        vector_store_ids = settings.get('vector_store_ids', [])
        
        logger.info("🔍 Building agent config from DB row", 
                   bot_id=row.bot_id,
                   agent_name=agent_name,
                   vector_store_ids=vector_store_ids,
                   enable_file_search=settings.get('enable_file_search', False))
        
        config = {
            'bot_id': row.bot_id,
            'agent_id': row.openai_agent_id,
            'name': agent_name,
            'system_prompt': system_prompt,
            'model': model_name,
            'admin_chat_id': row.openai_admin_chat_id,
            
            # Настройки Responses API из JSON с fallback
            'store_conversations': row.openai_store_conversations,
            'conversation_retention': row.openai_conversation_retention_days,
            'enable_streaming': settings.get('enable_streaming', True),
            
            # Параметры модели из JSON с fallback
            'temperature': settings.get('temperature', 0.7),
            'max_tokens': settings.get('max_tokens', 4000),
            'top_p': settings.get('top_p', 1.0),
            'frequency_penalty': settings.get('frequency_penalty', 0.0),
            'presence_penalty': settings.get('presence_penalty', 0.0),
            
            # ✅ ИСПРАВЛЕНО: Встроенные инструменты из JSON с правильными vector_store_ids
            'enable_web_search': settings.get('enable_web_search', False),
            'enable_code_interpreter': settings.get('enable_code_interpreter', False),
            'enable_file_search': settings.get('enable_file_search', False),
            'enable_image_generation': settings.get('enable_image_generation', False),
            
            # ✅ КРИТИЧНО: Vector Store IDs для file_search
            'vector_store_ids': vector_store_ids,
            
            # Дополнительные настройки
            'context_info': settings.get('context_info', True),
            'daily_limit': settings.get('daily_limit'),
            
            # ✅ ИСПРАВЛЕНО: settings содержит ВСЕ настройки включая vector_store_ids
            'settings': settings,
            
            # Статус агента
            'enabled': row.ai_assistant_enabled,
            'type': row.ai_assistant_type,
            'agent_source': 'user_bots_table',  # Маркер источника
        }
        
        logger.info("✅ Agent config built successfully", 
                   bot_id=row.bot_id,
                   agent_id=row.openai_agent_id,
                   config_keys=list(config.keys()),
                   settings_vector_stores=len(config['vector_store_ids']),
                   file_search_enabled=config['enable_file_search'])
        
        return config

    # ===== OPENAI LEGACY METHODS =====
    
    @staticmethod
    async def get_openai_agent_config(assistant_id: str) -> Optional[dict]:
        """Роутер между старым и новым методами get_openai_agent_config"""
        # Используем новый метод Responses API
        config = await AIManager.get_openai_agent_config_responses_api(assistant_id)
        if config:
            return config
        
        # Если не найдено, пробуем старую логику (для обратной совместимости)
        return await AIManager.get_openai_agent_config_by_id(assistant_id)

    @staticmethod
    async def get_openai_agent_config_by_id(agent_id: str) -> Optional[dict]:
        """✅ ИСПРАВЛЕНО: Legacy метод с правильным поиском"""
        from database.models import UserBot
        
        logger.info("🔍 Getting OpenAI agent config by ID (legacy)", agent_id=agent_id)
        
        async with get_db_session() as session:
            result = await session.execute(
                select(UserBot).where(UserBot.openai_agent_id == agent_id)
            )
            bot = result.scalar_one_or_none()
            
            if not bot:
                logger.warning("❌ OpenAI agent not found in database", agent_id=agent_id)
                return None
                
            # ✅ ИСПРАВЛЕНО: Проверяем после получения
            if bot.ai_assistant_type != 'openai':
                logger.warning("❌ Found bot but wrong AI type", 
                              agent_id=agent_id,
                              ai_type=bot.ai_assistant_type)
                return None
                
            if not bot.ai_assistant_enabled:
                logger.warning("❌ Found OpenAI agent but disabled", 
                              agent_id=agent_id,
                              enabled=bot.ai_assistant_enabled)
                return None
            
            config = {
                'bot_id': bot.bot_id,
                'agent_id': bot.openai_agent_id,
                'name': bot.openai_agent_name or 'AI Agent',
                'system_prompt': bot.openai_agent_instructions or '',
                'model': bot.openai_model or 'gpt-4o',
                'enabled': bot.ai_assistant_enabled,
                'settings': bot.openai_settings or {}
            }
            
            # Добавляем дополнительные настройки из openai_settings
            if bot.openai_settings:
                config.update({
                    'temperature': bot.openai_settings.get('temperature', 0.7),
                    'max_tokens': bot.openai_settings.get('max_tokens', 4000),
                    'enable_web_search': bot.openai_settings.get('enable_web_search', False),
                    'tools_enabled': bot.openai_settings.get('tools_enabled', True),
                    'daily_limit': bot.openai_settings.get('daily_limit'),
                    'channel_check': bot.openai_settings.get('channel_check'),
                    'context_info': bot.openai_settings.get('context_info', True)
                })
            
            logger.info("✅ OpenAI agent config found (legacy)", 
                       agent_id=agent_id,
                       bot_id=bot.bot_id,
                       agent_name=config['name'],
                       enabled=config['enabled'])
            
            return config

    @staticmethod
    async def get_openai_agent_config_by_bot_id(bot_id: str) -> Optional[dict]:
        """Получение конфигурации OpenAI агента по bot_id"""
        from database.models import UserBot
        
        logger.info("🔍 Getting OpenAI agent config by bot_id", bot_id=bot_id)
        
        async with get_db_session() as session:
            result = await session.execute(
                select(UserBot).where(UserBot.bot_id == bot_id)
            )
            bot = result.scalar_one_or_none()
            
            if not bot or bot.ai_assistant_type != 'openai' or not bot.openai_agent_id:
                logger.warning("❌ OpenAI agent not found for bot", bot_id=bot_id)
                return None
            
            # Используем основной метод с assistant_id
            return await AIManager.get_openai_agent_config(bot.openai_agent_id)

    @staticmethod
    async def update_openai_agent_settings(bot_id: str, settings: dict):
        """Обновление настроек OpenAI агента"""
        from database.models import UserBot
        
        logger.info("🔄 Updating OpenAI agent settings", 
                   bot_id=bot_id,
                   settings_keys=list(settings.keys()))
        
        async with get_db_session() as session:
            # Получаем текущие настройки
            result = await session.execute(
                select(UserBot.openai_settings).where(UserBot.bot_id == bot_id)
            )
            current_settings = result.scalar_one_or_none() or {}
            
            # Обновляем настройки
            updated_settings = current_settings.copy()
            updated_settings.update(settings)
            updated_settings['updated_at'] = datetime.now().isoformat()
            
            update_data = {'openai_settings': updated_settings}
            
            # Обновляем основные поля если они есть в settings
            if 'name' in settings:
                update_data['openai_agent_name'] = settings['name']
            if 'system_prompt' in settings:
                update_data['openai_agent_instructions'] = settings['system_prompt']
            if 'model' in settings:
                update_data['openai_model'] = settings['model']
            
            await session.execute(
                update(UserBot)
                .where(UserBot.bot_id == bot_id)
                .values(**update_data)
            )
            await session.commit()
            
            logger.info("✅ OpenAI agent settings updated", 
                       bot_id=bot_id,
                       fields_updated=list(settings.keys()))

    # ===== EXTERNAL AI PLATFORMS METHODS =====

    @staticmethod
    async def save_external_ai_config(bot_id: str, api_token: str, bot_id_value: str, platform: str, settings: dict = None):
        """Сохранение конфигурации внешней AI платформы (ChatForYou/ProTalk)"""
        from database.models import UserBot
        
        if platform not in ['chatforyou', 'protalk']:
            raise ValueError(f"Unsupported platform: {platform}")
        
        logger.info("💾 Saving external AI config", 
                   bot_id=bot_id, 
                   platform=platform,
                   has_bot_id=bool(bot_id_value))
        
        async with get_db_session() as session:
            external_settings = {
                'daily_limit': settings.get('daily_limit') if settings else None,
                'channel_id': settings.get('channel_id') if settings else None,
                'context_info': settings.get('context_info', True) if settings else True,
                'api_version': 'v1.0',
                'auto_detect_platform': True,
                'response_timeout': 30,
                'max_retries': 3,
                'retry_delay': 1.0,
                'detected_platform': platform,
                'platform_detected_at': datetime.now().isoformat(),
                'platform_detection_attempts': 0,
                'supported_platforms': ['chatforyou', 'protalk'],
                'rate_limit_enabled': True,
                'rate_limit_requests': 60,
                'block_inappropriate': True,
                'auto_platform_switch': False,
                'fallback_enabled': True,
                'debug_mode': False,
                'log_conversations': True,
                'log_errors': True,
                'log_performance': False,
                'configured_at': datetime.now().isoformat(),
                'total_requests': 0,
                'successful_requests': 0,
                'failed_requests': 0
            }
            
            if settings:
                external_settings.update(settings)
            
            await session.execute(
                update(UserBot)
                .where(UserBot.bot_id == bot_id)
                .values(
                    ai_assistant_type=platform,
                    ai_assistant_enabled=True,
                    external_api_token=api_token,
                    external_bot_id=bot_id_value,
                    external_platform=platform,
                    external_settings=external_settings,
                    updated_at=datetime.now()
                )
            )
            await session.commit()
            
            logger.info("✅ External AI config saved", 
                       bot_id=bot_id, 
                       platform=platform,
                       has_bot_id=bool(bot_id_value))

    @staticmethod
    async def get_external_ai_config(bot_id: str) -> Optional[dict]:
        """Получение конфигурации внешней AI платформы"""
        from database.models import UserBot
        
        async with get_db_session() as session:
            result = await session.execute(
                select(UserBot).where(UserBot.bot_id == bot_id)
            )
            bot = result.scalar_one_or_none()
            
            if not bot or bot.ai_assistant_type not in ['chatforyou', 'protalk']:
                return None
            
            return {
                'bot_id': bot.bot_id,
                'api_token': bot.external_api_token,
                'bot_id_value': bot.external_bot_id,
                'platform': bot.external_platform,
                'enabled': bot.ai_assistant_enabled,
                'settings': bot.external_settings or {}
            }

    @staticmethod
    async def update_external_ai_settings(bot_id: str, settings: dict):
        """Обновление настроек внешней AI платформы"""
        from database.models import UserBot
        
        async with get_db_session() as session:
            # Получаем текущие настройки
            result = await session.execute(
                select(UserBot.external_settings).where(UserBot.bot_id == bot_id)
            )
            current_settings = result.scalar_one_or_none() or {}
            
            # Обновляем настройки
            updated_settings = current_settings.copy()
            updated_settings.update(settings)
            updated_settings['updated_at'] = datetime.now().isoformat()
            
            await session.execute(
                update(UserBot)
                .where(UserBot.bot_id == bot_id)
                .values(external_settings=updated_settings)
            )
            await session.commit()
            
            logger.info("✅ External AI settings updated", 
                       bot_id=bot_id,
                       fields_updated=list(settings.keys()))

    # ===== UNIVERSAL AI METHODS =====

    @staticmethod
    async def get_ai_config(bot_id: str) -> Optional[dict]:
        """Получение конфигурации AI (любой платформы) с расширенным логированием"""
        from database.models import UserBot
        
        logger.info("🔍 Loading AI config for bot startup", bot_id=bot_id)
        
        async with get_db_session() as session:
            result = await session.execute(
                select(UserBot).where(UserBot.bot_id == bot_id)
            )
            bot = result.scalar_one_or_none()
            
            if not bot or not bot.ai_assistant_enabled:
                logger.info("❌ No AI config or disabled", 
                           bot_id=bot_id,
                           bot_exists=bool(bot),
                           ai_enabled=bot.ai_assistant_enabled if bot else False)
                return None
            
            config = {
                'bot_id': bot.bot_id,
                'enabled': bot.ai_assistant_enabled,
                'type': bot.ai_assistant_type
            }
            
            if bot.ai_assistant_type == 'openai':
                config.update({
                    'agent_id': bot.openai_agent_id,
                    'agent_name': bot.openai_agent_name,
                    'instructions': bot.openai_agent_instructions,
                    'model': bot.openai_model,
                    'settings': bot.openai_settings or {}
                })
                logger.info("✅ OpenAI config loaded", 
                           bot_id=bot_id,
                           agent_id=bot.openai_agent_id,
                           model=bot.openai_model)
                
            elif bot.ai_assistant_type in ['chatforyou', 'protalk']:
                config.update({
                    'api_token': bot.external_api_token,
                    'bot_id_value': bot.external_bot_id,
                    'platform': bot.external_platform,
                    'settings': bot.external_settings or {}
                })
                logger.info("✅ External AI config loaded", 
                           bot_id=bot_id,
                           platform=bot.ai_assistant_type,
                           has_token=bool(bot.external_api_token))
            else:
                logger.warning("⚠️ Unknown AI type", 
                              bot_id=bot_id,
                              ai_type=bot.ai_assistant_type)
            
            logger.info("✅ AI config loaded successfully", 
                       bot_id=bot_id, 
                       ai_type=config['type'])
            return config

    @staticmethod
    async def update_ai_assistant(
        bot_id: str,
        enabled: bool = True,
        assistant_id: Optional[str] = None,
        settings: Optional[dict] = None
    ) -> bool:
        """Универсальный метод с правильной синхронизацией данных"""
        from database.models import UserBot
        
        logger.info("🔄 Updating AI assistant with proper data sync", 
                   bot_id=bot_id,
                   enabled=enabled,
                   assistant_id_exists=bool(assistant_id),
                   settings_keys=list(settings.keys()) if settings else None)
        
        try:
            async with get_db_session() as session:
                # Получаем текущие настройки бота
                result = await session.execute(
                    select(UserBot).where(UserBot.bot_id == bot_id)
                )
                bot = result.scalar_one_or_none()
                
                if not bot:
                    logger.error("❌ Bot not found for AI assistant update", bot_id=bot_id)
                    return False
                
                # Определяем тип агента из настроек
                agent_type = settings.get('agent_type') if settings else bot.ai_assistant_type
                
                # Базовые поля для обновления
                update_data = {
                    'ai_assistant_enabled': enabled,
                    'updated_at': datetime.now()
                }
                
                # Устанавливаем тип агента если передан
                if agent_type:
                    update_data['ai_assistant_type'] = agent_type
                
                # В зависимости от типа агента обновляем соответствующие поля
                if agent_type == 'openai':
                    logger.info("🎨 Updating OpenAI agent with data sync")
                    
                    if assistant_id:
                        update_data['openai_agent_id'] = assistant_id
                    
                    if settings:
                        # Генерируем синхронизированные данные
                        agent_name = settings.get('agent_name', 'AI Ассистент')
                        agent_role = settings.get('agent_role', 'Полезный помощник')
                        
                        # Генерируем полный системный промпт
                        if 'system_prompt' in settings and settings['system_prompt']:
                            full_system_prompt = settings['system_prompt']
                        else:
                            full_system_prompt = f"Ты - {agent_role}. Твое имя {agent_name}. Отвечай полезно и дружелюбно."
                            settings['system_prompt'] = full_system_prompt
                        
                        # Синхронизируем основные поля с JSON
                        update_data.update({
                            'openai_agent_name': agent_name,
                            'openai_agent_instructions': full_system_prompt,
                            'openai_model': settings.get('model_used', 'gpt-4o'),
                            
                            # Responses API настройки
                            'openai_use_responses_api': True,
                            'openai_store_conversations': settings.get('store_conversations', True),
                            'openai_conversation_retention_days': settings.get('conversation_retention', 30),
                            'openai_conversation_contexts': {},
                            'openai_settings': settings,
                            
                            # Очищаем external поля при установке OpenAI
                            'external_api_token': None,
                            'external_bot_id': None,
                            'external_platform': None,
                            'external_settings': None
                        })
                        
                elif agent_type in ['chatforyou', 'protalk']:
                    logger.info("🌐 Updating external AI platform configuration", platform=agent_type)
                    
                    if assistant_id:
                        update_data['external_api_token'] = assistant_id
                    
                    if settings:
                        # Внешние поля
                        update_data.update({
                            'external_platform': agent_type,
                            'external_settings': settings
                        })
                        
                        # ChatForYou bot_id
                        if agent_type == 'chatforyou' and 'chatforyou_bot_id' in settings:
                            update_data['external_bot_id'] = str(settings['chatforyou_bot_id'])
                        
                        # Очищаем OpenAI поля
                        update_data.update({
                            'openai_agent_id': None,
                            'openai_agent_name': None,
                            'openai_agent_instructions': None,
                            'openai_model': 'gpt-4o',
                            'openai_use_responses_api': False,
                            'openai_store_conversations': False,
                            'openai_conversation_retention_days': 30,
                            'openai_conversation_contexts': {},
                            'openai_settings': None
                        })
                
                # Выполняем обновление
                await session.execute(
                    update(UserBot)
                    .where(UserBot.bot_id == bot_id)
                    .values(**update_data)
                )
                await session.commit()
                
                logger.info("✅ AI assistant updated with proper data sync", 
                           bot_id=bot_id,
                           agent_type=agent_type,
                           enabled=enabled,
                           fields_updated=len(update_data))
                
                return True
                
        except Exception as e:
            logger.error("💥 Failed to update AI assistant", 
                        bot_id=bot_id,
                        error=str(e))
            return False

    @staticmethod
    async def disable_ai_assistant(bot_id: str):
        """Отключение AI ассистента"""
        from database.models import UserBot
        
        async with get_db_session() as session:
            await session.execute(
                update(UserBot)
                .where(UserBot.bot_id == bot_id)
                .values(ai_assistant_enabled=False, updated_at=datetime.now())
            )
            await session.commit()
            
            logger.info("✅ AI assistant disabled", bot_id=bot_id)

    @staticmethod
    async def clear_ai_configuration(bot_id: str):
        """Полная очистка конфигурации AI"""
        from database.models import UserBot
        
        logger.info("🗑️ Clearing AI configuration", bot_id=bot_id)
        
        async with get_db_session() as session:
            await session.execute(
                update(UserBot)
                .where(UserBot.bot_id == bot_id)
                .values(
                    ai_assistant_enabled=False,
                    ai_assistant_type=None,
                    # Clear OpenAI fields
                    openai_agent_id=None,
                    openai_agent_name=None,
                    openai_agent_instructions=None,
                    openai_model='gpt-4o',
                    openai_settings=None,
                    openai_conversation_contexts={},
                    openai_store_conversations=False,
                    openai_conversation_retention_days=30,
                    openai_use_responses_api=False,
                    # Clear external platform fields
                    external_api_token=None,
                    external_bot_id=None,
                    external_platform=None,
                    external_settings=None,
                    updated_at=datetime.now()
                )
            )
            await session.commit()
            
            logger.info("✅ AI configuration cleared", bot_id=bot_id)

    @staticmethod
    async def increment_ai_stats(bot_id: str, success: bool = True):
        """Увеличение статистики использования AI"""
        from database.models import UserBot
        
        async with get_db_session() as session:
            # Получаем текущий тип AI и настройки
            result = await session.execute(
                select(UserBot.ai_assistant_type, UserBot.openai_settings, UserBot.external_settings)
                .where(UserBot.bot_id == bot_id)
            )
            bot_data = result.first()
            
            if not bot_data:
                return
            
            ai_type, openai_settings, external_settings = bot_data
            current_time = datetime.now().isoformat()
            
            if ai_type == 'openai' and openai_settings is not None:
                updated_settings = openai_settings.copy()
                updated_settings['total_requests'] = updated_settings.get('total_requests', 0) + 1
                updated_settings['last_request_at'] = current_time
                
                if success:
                    updated_settings['successful_requests'] = updated_settings.get('successful_requests', 0) + 1
                else:
                    updated_settings['failed_requests'] = updated_settings.get('failed_requests', 0) + 1
                
                await session.execute(
                    update(UserBot)
                    .where(UserBot.bot_id == bot_id)
                    .values(openai_settings=updated_settings)
                )
                
            elif ai_type in ['chatforyou', 'protalk'] and external_settings is not None:
                updated_settings = external_settings.copy()
                updated_settings['total_requests'] = updated_settings.get('total_requests', 0) + 1
                updated_settings['last_request_at'] = current_time
                
                if success:
                    updated_settings['successful_requests'] = updated_settings.get('successful_requests', 0) + 1
                else:
                    updated_settings['failed_requests'] = updated_settings.get('failed_requests', 0) + 1
                
                await session.execute(
                    update(UserBot)
                    .where(UserBot.bot_id == bot_id)
                    .values(external_settings=updated_settings)
                )
            
            await session.commit()

    # ===== CONVERSATION MANAGEMENT (RESPONSES API) =====

    @staticmethod
    async def save_conversation_response_id(bot_id: str, user_id: int, response_id: str):
        """Сохранение response_id для продолжения разговора в Responses API"""
        from database.models import UserBot
        
        try:
            async with get_db_session() as session:
                # Обновляем поле openai_conversation_contexts в таблице user_bots
                await session.execute(
                    update(UserBot)
                    .where(UserBot.bot_id == bot_id)
                    .values(
                        openai_conversation_contexts=func.coalesce(
                            UserBot.openai_conversation_contexts, 
                            text("'{}'::jsonb")
                        ).op('||')(
                            func.jsonb_build_object(str(user_id), response_id)
                        ),
                        updated_at=datetime.now()
                    )
                )
                await session.commit()
                
                logger.info("✅ Conversation response_id saved", 
                           bot_id=bot_id,
                           user_id=user_id,
                           response_id=response_id[:15] + "...")
                
                return True
                
        except Exception as e:
            logger.error("💥 Failed to save conversation response_id", 
                        bot_id=bot_id,
                        user_id=user_id,
                        error=str(e))
            return False

    @staticmethod
    async def get_conversation_response_id(bot_id: str, user_id: int) -> Optional[str]:
        """Получение response_id для продолжения разговора"""
        from database.models import UserBot
        
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    select(UserBot.openai_conversation_contexts)
                    .where(UserBot.bot_id == bot_id)
                )
                
                conversations = result.scalar_one_or_none()
                
                if conversations:
                    response_id = conversations.get(str(user_id))
                    
                    logger.info("🔍 Retrieved conversation response_id", 
                               bot_id=bot_id,
                               user_id=user_id,
                               has_response_id=bool(response_id))
                    
                    return response_id
                
                return None
                
        except Exception as e:
            logger.error("💥 Failed to get conversation response_id", 
                        bot_id=bot_id,
                        user_id=user_id,
                        error=str(e))
            return None

    @staticmethod
    async def clear_conversation_response_id(bot_id: str, user_id: int) -> bool:
        """Очистка response_id для пользователя (начать новый разговор)"""
        from database.models import UserBot
        
        try:
            async with get_db_session() as session:
                # Удаляем response_id для конкретного пользователя
                await session.execute(
                    update(UserBot)
                    .where(UserBot.bot_id == bot_id)
                    .values(
                        openai_conversation_contexts=func.coalesce(
                            UserBot.openai_conversation_contexts, 
                            {}
                        ).op('-')(str(user_id)),
                        updated_at=datetime.now()
                    )
                )
                await session.commit()
                
                logger.info("✅ Conversation response_id cleared", 
                           bot_id=bot_id,
                           user_id=user_id)
                
                return True
                
        except Exception as e:
            logger.error("💥 Failed to clear conversation response_id", 
                        bot_id=bot_id,
                        user_id=user_id,
                        error=str(e))
            return False

    @staticmethod
    async def clear_all_conversations(bot_id: str) -> bool:
        """Очистка всех активных разговоров для бота"""
        from database.models import UserBot
        
        try:
            async with get_db_session() as session:
                await session.execute(
                    update(UserBot)
                    .where(UserBot.bot_id == bot_id)
                    .values(
                        openai_conversation_contexts=text("'{}'::jsonb"),
                        updated_at=datetime.now()
                    )
                )
                await session.commit()
                
                logger.info("✅ All conversations cleared for bot", bot_id=bot_id)
                return True
                
        except Exception as e:
            logger.error("💥 Failed to clear all conversations", 
                        bot_id=bot_id,
                        error=str(e))
            return False

    @staticmethod
    async def get_active_conversations_count(bot_id: str) -> int:
        """Получение количества активных разговоров"""
        from database.models import UserBot
        
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    select(UserBot.openai_conversation_contexts)
                    .where(UserBot.bot_id == bot_id)
                )
                
                conversations = result.scalar_one_or_none()
                
                if conversations:
                    return len(conversations)
                
            return 0
                
        except Exception as e:
            logger.error("💥 Failed to get active conversations count", 
                        bot_id=bot_id,
                        error=str(e))
            return 0

    # ===== RESPONSES API TOOLS AND SETTINGS =====

    @staticmethod
    async def enable_responses_api_tool(bot_id: str, tool_name: str, enabled: bool = True) -> bool:
        """Включение/выключение встроенного инструмента Responses API"""
        from database.models import UserBot
        
        valid_tools = ['web_search', 'code_interpreter', 'file_search', 'image_generation']
        
        if tool_name not in valid_tools:
            logger.warning("❌ Invalid tool name", tool_name=tool_name)
            return False
        
        try:
            async with get_db_session() as session:
                setting_key = f'enable_{tool_name}'
                
                # Получаем текущие настройки
                result = await session.execute(
                    select(UserBot.openai_settings)
                    .where(UserBot.bot_id == bot_id, UserBot.ai_assistant_type == 'openai')
                )
                current_settings = result.scalar_one_or_none() or {}
                
                # Обновляем настройки
                updated_settings = current_settings.copy()
                updated_settings[setting_key] = enabled
                
                await session.execute(
                    update(UserBot)
                    .where(UserBot.bot_id == bot_id, UserBot.ai_assistant_type == 'openai')
                    .values(
                        openai_settings=updated_settings,
                        updated_at=datetime.now()
                    )
                )
                await session.commit()
                
                logger.info("✅ Responses API tool setting updated", 
                           bot_id=bot_id,
                           tool_name=tool_name,
                           enabled=enabled)
                
                return True
                
        except Exception as e:
            logger.error("💥 Failed to update tool setting", 
                        bot_id=bot_id,
                        tool_name=tool_name,
                        error=str(e))
            return False

    @staticmethod
    async def get_responses_api_stats(bot_id: str) -> Dict:
        """Получение статистики использования Responses API"""
        from database.models import UserBot
        
        try:
            async with get_db_session() as session:
                # Основная информация о боте
                result = await session.execute(
                    select(
                        UserBot.openai_agent_name,
                        UserBot.openai_model,
                        UserBot.openai_conversation_contexts,
                        UserBot.openai_settings,
                        UserBot.updated_at,
                        UserBot.created_at,
                        UserBot.tokens_used_total,
                        UserBot.tokens_used_input,
                        UserBot.tokens_used_output
                    ).where(
                        UserBot.bot_id == bot_id,
                        UserBot.ai_assistant_type == 'openai'
                    )
                )
                
                bot_data = result.first()
                
                if not bot_data:
                    return {}
                
                settings = bot_data.openai_settings or {}
                active_conversations = bot_data.openai_conversation_contexts or {}
                
                stats = {
                    'agent_name': bot_data.openai_agent_name,
                    'model': bot_data.openai_model,
                    'created_at': bot_data.created_at.isoformat() if bot_data.created_at else None,
                    'last_usage_at': bot_data.updated_at.isoformat() if bot_data.updated_at else None,
                    
                    # Активные разговоры
                    'active_conversations': len(active_conversations),
                    'conversation_users': list(active_conversations.keys()),
                    
                    # Статистика токенов
                    'token_stats': {
                        'total_tokens': int(bot_data.tokens_used_total or 0),
                        'input_tokens': int(bot_data.tokens_used_input or 0),
                        'output_tokens': int(bot_data.tokens_used_output or 0)
                    },
                    
                    # Настройки Responses API
                    'responses_api_settings': {
                        'store_conversations': settings.get('store_conversations', True),
                        'conversation_retention': settings.get('conversation_retention', 30),
                        'enable_streaming': settings.get('enable_streaming', True),
                        'enabled_tools': [
                            tool.replace('enable_', '') 
                            for tool, enabled in settings.items() 
                            if tool.startswith('enable_') and enabled
                        ]
                    }
                }
                
                logger.info("📊 Responses API stats retrieved", 
                           bot_id=bot_id,
                           active_conversations=stats['active_conversations'],
                           total_tokens=stats['token_stats']['total_tokens'])
                
                return stats
                
        except Exception as e:
            logger.error("💥 Failed to get Responses API stats", 
                        bot_id=bot_id,
                        error=str(e))
            return {}

    # ===== VECTOR STORES MANAGEMENT =====
    
    @staticmethod
    async def save_vector_store_ids(bot_id: str, vector_store_ids: List[str]) -> bool:
        """Сохранение vector store IDs для бота"""
        from database.models import UserBot
        
        try:
            async with get_db_session() as session:
                # Получаем текущие настройки
                result = await session.execute(
                    select(UserBot.openai_settings)
                    .where(UserBot.bot_id == bot_id, UserBot.ai_assistant_type == 'openai')
                )
                current_settings = result.scalar_one_or_none() or {}
                
                # Обновляем с vector store IDs
                updated_settings = current_settings.copy()
                updated_settings['vector_store_ids'] = vector_store_ids
                updated_settings['enable_file_search'] = True if vector_store_ids else False
                updated_settings['vector_stores_updated_at'] = datetime.now().isoformat()
                
                await session.execute(
                    update(UserBot)
                    .where(UserBot.bot_id == bot_id, UserBot.ai_assistant_type == 'openai')
                    .values(
                        openai_settings=updated_settings,
                        updated_at=datetime.now()
                    )
                )
                await session.commit()
                
                logger.info("✅ Vector store IDs saved", 
                           bot_id=bot_id,
                           vector_store_count=len(vector_store_ids))
                return True
                
        except Exception as e:
            logger.error("💥 Failed to save vector store IDs", 
                        bot_id=bot_id, error=str(e))
            return False
    
    @staticmethod
    async def get_vector_store_info(bot_id: str) -> Dict:
        """Получение информации о vector stores бота"""
        from database.models import UserBot
        
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    select(UserBot.openai_settings)
                    .where(UserBot.bot_id == bot_id, UserBot.ai_assistant_type == 'openai')
                )
                settings = result.scalar_one_or_none() or {}
                
                vector_store_ids = settings.get('vector_store_ids', [])
                file_search_enabled = settings.get('enable_file_search', False)
                
                return {
                    'vector_store_ids': vector_store_ids,
                    'file_search_enabled': file_search_enabled,
                    'vector_stores_count': len(vector_store_ids),
                    'last_updated': settings.get('vector_stores_updated_at'),
                    'settings': settings
                }
                
        except Exception as e:
            logger.error("💥 Failed to get vector store info", 
                        bot_id=bot_id, error=str(e))
            return {}
    
    @staticmethod
    async def clear_vector_stores(bot_id: str) -> bool:
        """Очистка всех vector stores для бота"""
        from database.models import UserBot
        
        try:
            async with get_db_session() as session:
                # Получаем текущие настройки
                result = await session.execute(
                    select(UserBot.openai_settings)
                    .where(UserBot.bot_id == bot_id, UserBot.ai_assistant_type == 'openai')
                )
                current_settings = result.scalar_one_or_none() or {}
                
                # Очищаем vector store данные
                updated_settings = current_settings.copy()
                updated_settings['vector_store_ids'] = []
                updated_settings['enable_file_search'] = False
                updated_settings['vector_stores_cleared_at'] = datetime.now().isoformat()
                
                await session.execute(
                    update(UserBot)
                    .where(UserBot.bot_id == bot_id, UserBot.ai_assistant_type == 'openai')
                    .values(
                        openai_settings=updated_settings,
                        updated_at=datetime.now()
                    )
                )
                await session.commit()
                
                logger.info("✅ Vector stores cleared", bot_id=bot_id)
                return True
                
        except Exception as e:
            logger.error("💥 Failed to clear vector stores", 
                        bot_id=bot_id, error=str(e))
            return False

    # ===== LEGACY COMPATIBILITY METHODS =====

    @staticmethod
    async def update_ai_assistant_with_platform(
        bot_id: str,
        api_token: str,
        bot_id_value: int = None,
        settings: dict = None,
        platform: str = "chatforyou"
    ):
        """Update AI assistant with simplified platform handling (legacy)"""
        logger.warning("Using legacy update_ai_assistant_with_platform method. Consider using save_external_ai_config.", bot_id=bot_id)
        
        # Конвертируем bot_id_value в строку для новой структуры
        bot_id_str = str(bot_id_value) if bot_id_value is not None else None
        
        await AIManager.save_external_ai_config(
            bot_id=bot_id,
            api_token=api_token,
            bot_id_value=bot_id_str,
            platform=platform,
            settings=settings
        )

    @staticmethod
    async def update_ai_credentials(
        bot_id: str,
        api_token: str,
        bot_id_value: int = None,
        platform: str = "chatforyou"
    ):
        """Update only AI credentials (token + bot_id) (legacy)"""
        logger.warning("Using legacy update_ai_credentials method. Consider using save_external_ai_config.", bot_id=bot_id)
        
        await AIManager.save_external_ai_config(
            bot_id=bot_id,
            api_token=api_token,
            bot_id_value=str(bot_id_value) if bot_id_value is not None else None,
            platform=platform
        )

    @staticmethod
    async def get_ai_credentials(bot_id: str) -> dict:
        """Get AI credentials for bot (legacy)"""
        config = await AIManager.get_ai_config(bot_id)
        
        if not config:
            return {}
        
        if config['type'] == 'openai':
            return {
                'api_token': config.get('agent_id'),
                'bot_id': None,
                'platform': 'openai'
            }
        elif config['type'] in ['chatforyou', 'protalk']:
            return {
                'api_token': config.get('api_token'),
                'bot_id': int(config.get('bot_id_value')) if config.get('bot_id_value') else None,
                'platform': config.get('platform')
            }
        
        return {}

    @staticmethod
    async def detect_and_validate_ai_platform(api_token: str, test_bot_id: str = None) -> Tuple[bool, Optional[str], str]:
        """Simplified: Just cache token and test with real data if bot_id provided (legacy)"""
        try:
            logger.info(f"Caching AI token: {api_token[:10]}...")
            
            if test_bot_id:
                from services.ai_assistant import ai_client
                
                logger.info(f"Testing ChatForYou with bot_id: {test_bot_id}")
                
                try:
                    # Попытка реального запроса
                    response = await ai_client.send_message(
                        api_token=api_token,
                        message="test",
                        user_id=12345,
                        platform="chatforyou",
                        bot_id=int(test_bot_id)
                    )
                    
                    if response is not None:
                        logger.info("✅ ChatForYou test successful")
                        return True, "chatforyou", ""
                    else:
                        logger.warning("❌ ChatForYou test failed: empty response")
                        return False, None, "Проверьте правильность API токена и ID сотрудника"
                        
                except Exception as e:
                    logger.error(f"❌ ChatForYou test error: {str(e)}")
                    return False, None, f"Ошибка при проверке: {str(e)}"
            
            else:
                logger.info("✅ Token cached for later validation")
                return True, "chatforyou", ""
                
        except Exception as e:
            logger.error(f"Error in platform detection: {str(e)}")
            return False, None, f"Ошибка при обработке токена: {str(e)}"

    # ===== DATA SYNCHRONIZATION METHODS =====

    @staticmethod
    async def sync_agent_data_fields(bot_id: str = None, user_id: int = None) -> bool:
        """Синхронизация основных полей с JSON данными для существующих агентов"""
        from database.models import UserBot
        
        try:
            async with get_db_session() as session:
                # Определяем условие поиска
                query_conditions = [
                    UserBot.ai_assistant_type == 'openai',
                    UserBot.openai_settings.isnot(None)
                ]
                
                if bot_id:
                    query_conditions.append(UserBot.bot_id == bot_id)
                elif user_id:
                    query_conditions.append(UserBot.user_id == user_id)
                
                # Получаем агентов для синхронизации
                result = await session.execute(
                    select(UserBot).where(*query_conditions)
                )
                bots = result.scalars().all()
                
                synced_count = 0
                
                for bot in bots:
                    settings = bot.openai_settings or {}
                    
                    # Извлекаем данные из JSON
                    json_name = settings.get('agent_name')
                    json_prompt = settings.get('system_prompt')
                    json_model = settings.get('model_used') or settings.get('model')
                    
                    # Проверяем нужна ли синхронизация
                    needs_sync = (
                        (json_name and bot.openai_agent_name != json_name) or
                        (json_prompt and bot.openai_agent_instructions != json_prompt) or
                        (json_model and bot.openai_model != json_model)
                    )
                    
                    if needs_sync:
                        # Генерируем полный промпт если его нет
                        if not json_prompt and json_name and settings.get('agent_role'):
                            json_prompt = f"Ты - {settings['agent_role']}. Твое имя {json_name}. Отвечай полезно и дружелюбно."
                            # Обновляем JSON тоже
                            updated_settings = settings.copy()
                            updated_settings['system_prompt'] = json_prompt
                            settings = updated_settings
                        
                        # Обновляем основные поля
                        update_data = {}
                        if json_name:
                            update_data['openai_agent_name'] = json_name
                        if json_prompt:
                            update_data['openai_agent_instructions'] = json_prompt
                        if json_model:
                            update_data['openai_model'] = json_model
                        if settings != bot.openai_settings:
                            update_data['openai_settings'] = settings
                        
                        if update_data:
                            await session.execute(
                                update(UserBot)
                                .where(UserBot.id == bot.id)
                                .values(**update_data)
                            )
                            synced_count += 1
                            
                            logger.info("🔄 Agent data synchronized", 
                                       bot_id=bot.bot_id,
                                       updated_fields=list(update_data.keys()))
                
                await session.commit()
                
                logger.info("✅ Agent data synchronization completed", 
                           synced_agents=synced_count,
                           scope=f"bot_id={bot_id}" if bot_id else f"user_id={user_id}" if user_id else "all")
                
                return True
                
        except Exception as e:
            logger.error("💥 Failed to synchronize agent data", 
                        bot_id=bot_id,
                        user_id=user_id,
                        error=str(e))
            return False

    @staticmethod
    async def validate_agent_data_consistency(bot_id: str) -> Dict:
        """Валидация согласованности данных агента"""
        from database.models import UserBot
        
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    select(UserBot).where(UserBot.bot_id == bot_id)
                )
                bot = result.scalar_one_or_none()
                
                if not bot or bot.ai_assistant_type != 'openai':
                    return {'status': 'error', 'message': 'Bot not found or not OpenAI type'}
                
                settings = bot.openai_settings or {}
                
                # Проверяем согласованность данных
                validation = {
                    'status': 'success',
                    'bot_id': bot_id,
                    'checks': {
                        'name_consistency': {
                            'db_field': bot.openai_agent_name,
                            'json_field': settings.get('agent_name'),
                            'match': bot.openai_agent_name == settings.get('agent_name'),
                            'priority_source': 'json' if settings.get('agent_name') else 'db'
                        },
                        'prompt_consistency': {
                            'db_field_length': len(bot.openai_agent_instructions or ''),
                            'json_field_length': len(settings.get('system_prompt', '')),
                            'match': bot.openai_agent_instructions == settings.get('system_prompt'),
                            'priority_source': 'json' if settings.get('system_prompt') else 'db'
                        },
                        'model_consistency': {
                            'db_field': bot.openai_model,
                            'json_field': settings.get('model_used') or settings.get('model'),
                            'match': bot.openai_model == (settings.get('model_used') or settings.get('model')),
                            'priority_source': 'json' if settings.get('model_used') or settings.get('model') else 'db'
                        }
                    },
                    'recommendations': []
                }
                
                # Генерируем рекомендации
                if not validation['checks']['name_consistency']['match']:
                    validation['recommendations'].append('Sync agent name: use JSON as priority')
                
                if not validation['checks']['prompt_consistency']['match']:
                    validation['recommendations'].append('Sync system prompt: use JSON as priority')
                    
                if not validation['checks']['model_consistency']['match']:
                    validation['recommendations'].append('Sync model: use JSON as priority')
                
                validation['overall_status'] = 'consistent' if not validation['recommendations'] else 'needs_sync'
                
                return validation
                
        except Exception as e:
            return {
                'status': 'error', 
                'message': str(e),
                'bot_id': bot_id
            }
