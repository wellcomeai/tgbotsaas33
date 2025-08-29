"""
✅ ПОЛНОСТЬЮ ИСПРАВЛЕННЫЙ ContentManager для деплоя с поддержкой ссылок И КАНАЛОВ
🔧 СОВМЕСТИМОСТЬ: Полная совместимость с content_handlers.py
🚀 НОВОЕ: Поддержка медиагрупп, extract_media_info и извлечение ссылок + КАНАЛЫ
📊 ТОКЕНЫ: Правильная структура возврата токенов + интеграция с TokenManager
🛡️ БЕЗОПАСНОСТЬ: Улучшенная обработка ошибок
🔗 ССЫЛКИ: Извлечение и форматирование ссылок для AI агента
📺 КАНАЛЫ: Управление каналами и сохранение результатов рерайта
✅ ИСПРАВЛЕНО: Гарантированные медиа ключи в get_last_rewrite и save_rewrite_result

ОСНОВНЫЕ ИСПРАВЛЕНИЯ:
1. Унифицирована структура возврата result['content']['rewritten_text']
2. Добавлен метод extract_media_info(message) для обработки медиа
3. Специальная логика для медиагрупп (media_info['type'] == 'media_group')
4. Правильная структура токенов: result['tokens']['total_tokens']
5. Информация об агенте: result['agent']['name']
6. Полная совместимость с Pydantic объектами ResponseUsage
7. ✅ НОВОЕ: Полная интеграция с TokenManager - токены контент-агентов учитываются в общих лимитах
8. ✅ ИСПРАВЛЕНО: Двойное сохранение токенов через TokenManager + детальная статистика
9. ✨ НОВОЕ: Поддержка извлечения и форматирования ссылок для AI агента
10. 📺 НОВОЕ: Методы для работы с каналами и сохранения результатов рерайта
11. ✅ ИСПРАВЛЕНО: Гарантированные медиа ключи - дублирование media/media_info в обоих методах
"""

import time
import json
import structlog
from typing import Dict, Any, Optional, List, Union
from datetime import datetime, timedelta
from sqlalchemy import select, update, func, text

from ..connection import get_db_session

logger = structlog.get_logger()


class ContentManager:
    """✅ ПОЛНОСТЬЮ ИСПРАВЛЕННЫЙ менеджер контент-агентов с поддержкой медиагрупп, TokenManager, ссылок и каналов"""
    
    def __init__(self):
        # ✅ Используем существующий OpenAI клиент
        self.openai_client = self._get_openai_client()
        logger.info("🎨 ContentManager initialized with media group support, TokenManager integration, links and channels support", 
                   has_client=bool(self.openai_client))
    
    def _get_openai_client(self):
        """Получение существующего OpenAI клиента"""
        try:
            # ✅ Используем существующий клиент из services/openai_assistant
            from services.openai_assistant import openai_client
            logger.info("✅ Using existing OpenAI assistant client")
            return openai_client
        except ImportError as e:
            logger.warning("⚠️ OpenAI assistant client not available", error=str(e))
            return self._create_mock_client()
    
    def _create_mock_client(self):
        """✅ ИСПРАВЛЕНО: Заглушка для Responses API"""
        class MockOpenAIClient:
            async def _responses_with_retry(self, **kwargs):
                import uuid
                logger.warning("🧪 Using MOCK Responses API client for development")
                
                # Имитируем структуру ответа Responses API
                class MockResponse:
                    def __init__(self):
                        self.id = f"mock_resp_{uuid.uuid4().hex[:12]}"
                        self.output = [
                            {
                                "type": "message",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": f"[ТЕСТОВЫЙ РЕРАЙТ] {kwargs.get('input', 'текст')} [агент: mock]"
                                    }
                                ]
                            }
                        ]
                        
                        # ✅ ИСПРАВЛЕНО: Mock usage как Pydantic объект, а не словарь
                        class MockUsage:
                            def __init__(self):
                                self.input_tokens = len(kwargs.get('input', '')) // 4
                                self.output_tokens = len(kwargs.get('input', '')) // 3
                                self.total_tokens = self.input_tokens + self.output_tokens
                        
                        self.usage = MockUsage()
                    
                    @property
                    def output_text(self):
                        if self.output and self.output[0].get('content'):
                            return self.output[0]['content'][0].get('text', '')
                        return ''
                
                return MockResponse()
            
            async def create_assistant(self, **kwargs):
                return await self._responses_with_retry(**kwargs)
            
            async def send_message(self, assistant_id: str, message: str, user_id: int):
                return await self._responses_with_retry(
                    model="mock-gpt-4o",
                    instructions="Mock content agent",
                    input=message,
                    previous_response_id=assistant_id,
                    store=True
                )
        
        return MockOpenAIClient()
    
    # ===== ✨ НОВОЕ: MEDIA EXTRACTION =====
    
    def extract_media_info(self, message) -> Optional[Dict[str, Any]]:
        """✅ НОВОЕ: Извлечение информации о медиа из сообщения Telegram"""
        
        try:
            media_info = None
            
            # Проверяем тип медиа и извлекаем информацию
            if message.photo:
                # Берем фото наибольшего размера
                largest_photo = max(message.photo, key=lambda x: x.width * x.height)
                media_info = {
                    'type': 'photo',
                    'file_id': largest_photo.file_id,
                    'file_unique_id': largest_photo.file_unique_id,
                    'width': largest_photo.width,
                    'height': largest_photo.height,
                    'file_size': largest_photo.file_size
                }
                
            elif message.video:
                media_info = {
                    'type': 'video',
                    'file_id': message.video.file_id,
                    'file_unique_id': message.video.file_unique_id,
                    'width': message.video.width,
                    'height': message.video.height,
                    'duration': message.video.duration,
                    'file_size': message.video.file_size,
                    'mime_type': message.video.mime_type
                }
                
            elif message.animation:
                media_info = {
                    'type': 'animation',
                    'file_id': message.animation.file_id,
                    'file_unique_id': message.animation.file_unique_id,
                    'width': message.animation.width,
                    'height': message.animation.height,
                    'duration': message.animation.duration,
                    'file_size': message.animation.file_size,
                    'mime_type': message.animation.mime_type
                }
                
            elif message.audio:
                media_info = {
                    'type': 'audio',
                    'file_id': message.audio.file_id,
                    'file_unique_id': message.audio.file_unique_id,
                    'duration': message.audio.duration,
                    'performer': message.audio.performer,
                    'title': message.audio.title,
                    'file_size': message.audio.file_size,
                    'mime_type': message.audio.mime_type
                }
                
            elif message.voice:
                media_info = {
                    'type': 'voice',
                    'file_id': message.voice.file_id,
                    'file_unique_id': message.voice.file_unique_id,
                    'duration': message.voice.duration,
                    'file_size': message.voice.file_size,
                    'mime_type': message.voice.mime_type
                }
                
            elif message.document:
                media_info = {
                    'type': 'document',
                    'file_id': message.document.file_id,
                    'file_unique_id': message.document.file_unique_id,
                    'file_name': message.document.file_name,
                    'file_size': message.document.file_size,
                    'mime_type': message.document.mime_type
                }
            
            if media_info:
                # Добавляем общую информацию
                media_info.update({
                    'message_id': message.message_id,
                    'date': message.date.isoformat() if message.date else None,
                    'media_group_id': message.media_group_id,
                    'has_spoiler': getattr(message, 'has_media_spoiler', False)
                })
                
                logger.debug("📎 Media info extracted", 
                           media_type=media_info['type'],
                           message_id=message.message_id,
                           has_media_group=bool(message.media_group_id))
                
                return media_info
            
            return None
            
        except Exception as e:
            logger.error("💥 Error extracting media info", 
                        message_id=getattr(message, 'message_id', 'unknown'),
                        error=str(e))
            return None
    
    def _format_links_for_ai(self, links: Dict[str, Any]) -> str:
        """✨ НОВОЕ: Форматирование ссылок для передачи AI агенту"""
        
        try:
            formatted_parts = []
            
            # Обычные ссылки
            if links.get('urls'):
                urls_text = "\n".join([f"• {link['url']}" for link in links['urls']])
                formatted_parts.append(f"📎 Прямые ссылки:\n{urls_text}")
            
            # Гиперссылки (текст + ссылка)
            if links.get('text_links'):
                text_links = "\n".join([
                    f"• Текст: '{link['text']}' → Ссылка: {link['url']}" 
                    for link in links['text_links']
                ])
                formatted_parts.append(f"🔗 Скрытые гиперссылки:\n{text_links}")
            
            # Email адреса
            if links.get('emails'):
                emails_text = "\n".join([f"• {email}" for email in links['emails']])
                formatted_parts.append(f"📧 Email адреса:\n{emails_text}")
            
            # Телефоны
            if links.get('phone_numbers'):
                phones_text = "\n".join([f"• {phone}" for phone in links['phone_numbers']])
                formatted_parts.append(f"📞 Телефоны:\n{phones_text}")
            
            # Упоминания
            if links.get('mentions'):
                mentions_text = "\n".join([f"• {mention}" for mention in links['mentions']])
                formatted_parts.append(f"👤 Упоминания:\n{mentions_text}")
            
            result = "\n\n".join(formatted_parts)
            
            logger.debug("🔗 Links formatted for AI", 
                        total_sections=len(formatted_parts),
                        formatted_length=len(result))
            
            return result
            
        except Exception as e:
            logger.error("💥 Error formatting links for AI", error=str(e))
            return ""
    
    async def _ensure_tables_exist(self):
        """✅ Обновленный метод с таблицей каналов"""
        try:
            async with get_db_session() as session:
                # Проверяем существование таблицы content_agents
                check_agents_query = text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'content_agents'
                );
                """)
                
                agents_exists = await session.execute(check_agents_query)
                
                if not agents_exists.scalar():
                    logger.info("🗄️ Creating content_agents table")
                    await self._create_content_tables(session)
                
        except Exception as e:
            logger.error("💥 Failed to ensure tables exist", error=str(e))
    
    async def _create_content_tables(self, session):
        """✅ Создание таблиц с правильным constraint + таблица каналов"""
        try:
            # Таблица контент-агентов с УНИКАЛЬНЫМ CONSTRAINT
            agents_table = text("""
            CREATE TABLE IF NOT EXISTS content_agents (
                id SERIAL PRIMARY KEY,
                bot_id VARCHAR(255) NOT NULL,
                agent_name VARCHAR(255) NOT NULL,
                instructions TEXT NOT NULL,
                openai_agent_id VARCHAR(255),
                is_active BOOLEAN DEFAULT true,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                
                -- ✅ УНИКАЛЬНЫЙ CONSTRAINT: один активный агент на бота
                CONSTRAINT unique_bot_content_agent UNIQUE (bot_id, is_active)
            );
            """)
            
            # Таблица статистики с токеновыми полями  
            stats_table = text("""
            CREATE TABLE IF NOT EXISTS content_rewrite_stats (
                id SERIAL PRIMARY KEY,
                bot_id VARCHAR(255) NOT NULL,
                user_id BIGINT,
                tokens_used INTEGER NOT NULL DEFAULT 0,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                processing_time FLOAT NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW()
            );
            """)
            
            # 📺 НОВАЯ таблица каналов
            channels_table = text("""
            CREATE TABLE IF NOT EXISTS bot_admin_channels (
                id SERIAL PRIMARY KEY,
                bot_id VARCHAR(255) NOT NULL REFERENCES user_bots(bot_id) ON DELETE CASCADE,
                chat_id BIGINT NOT NULL,
                chat_title VARCHAR(255),
                chat_username VARCHAR(255),
                chat_type VARCHAR(50) DEFAULT 'channel',
                added_at TIMESTAMP DEFAULT NOW(),
                is_active BOOLEAN DEFAULT true,
                can_post_messages BOOLEAN DEFAULT true,
                last_rerait JSONB,
                
                CONSTRAINT unique_bot_channel UNIQUE (bot_id, is_active)
            );
            """)
            
            # Индексы для оптимизации
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_content_agents_bot_id ON content_agents(bot_id);",
                "CREATE INDEX IF NOT EXISTS idx_content_agents_active ON content_agents(bot_id, is_active);", 
                "CREATE INDEX IF NOT EXISTS idx_content_stats_bot_id ON content_rewrite_stats(bot_id);",
                "CREATE INDEX IF NOT EXISTS idx_content_stats_created ON content_rewrite_stats(created_at);",
                "CREATE INDEX IF NOT EXISTS idx_channels_bot_id ON bot_admin_channels(bot_id);",
                "CREATE INDEX IF NOT EXISTS idx_channels_chat_id ON bot_admin_channels(chat_id);"
            ]
            
            await session.execute(agents_table)
            await session.execute(stats_table)
            await session.execute(channels_table)
            
            for index_sql in indexes:
                try:
                    await session.execute(text(index_sql))
                except Exception as idx_error:
                    logger.warning("⚠️ Index creation failed", index=index_sql, error=str(idx_error))
            
            await session.commit()
            
            logger.info("✅ Content tables created successfully with unique constraint and channels support")
            
        except Exception as e:
            logger.error("💥 Error creating content tables", error=str(e))
            await session.rollback()
            raise
    
    # ===== 📺 НОВОЕ: МЕТОДЫ ДЛЯ РАБОТЫ С КАНАЛАМИ =====
    
    async def save_channel_info(self, bot_id: str, channel_data: Dict[str, Any]) -> bool:
        """Сохранение информации о канале"""
        try:
            await self._ensure_tables_exist()
            
            async with get_db_session() as session:
                # Проверяем существующий канал
                check_query = text("""
                SELECT id FROM bot_admin_channels 
                WHERE bot_id = :bot_id AND is_active = true
                LIMIT 1
                """)
                existing = await session.execute(check_query, {'bot_id': bot_id})
                
                if existing.fetchone():
                    # Обновляем существующий
                    update_query = text("""
                    UPDATE bot_admin_channels 
                    SET chat_id = :chat_id, chat_title = :chat_title, 
                        chat_username = :chat_username, chat_type = :chat_type,
                        added_at = NOW()
                    WHERE bot_id = :bot_id AND is_active = true
                    """)
                    await session.execute(update_query, {
                        'bot_id': bot_id,
                        'chat_id': channel_data['chat_id'],
                        'chat_title': channel_data.get('chat_title'),
                        'chat_username': channel_data.get('chat_username'),
                        'chat_type': channel_data.get('chat_type', 'channel')
                    })
                else:
                    # Создаем новый
                    insert_query = text("""
                    INSERT INTO bot_admin_channels 
                    (bot_id, chat_id, chat_title, chat_username, chat_type, added_at, is_active, can_post_messages)
                    VALUES (:bot_id, :chat_id, :chat_title, :chat_username, :chat_type, NOW(), true, true)
                    """)
                    await session.execute(insert_query, {
                        'bot_id': bot_id,
                        'chat_id': channel_data['chat_id'],
                        'chat_title': channel_data.get('chat_title'),
                        'chat_username': channel_data.get('chat_username'),
                        'chat_type': channel_data.get('chat_type', 'channel')
                    })
                
                await session.commit()
                return True
                
        except Exception as e:
            logger.error("💥 Error saving channel info", bot_id=bot_id, error=str(e))
            return False

    async def get_channel_info(self, bot_id: str) -> Optional[Dict[str, Any]]:
        """Получение информации о канале"""
        try:
            async with get_db_session() as session:
                query = text("""
                SELECT chat_id, chat_title, chat_username, chat_type, added_at, last_rerait
                FROM bot_admin_channels 
                WHERE bot_id = :bot_id AND is_active = true
                LIMIT 1
                """)
                result = await session.execute(query, {'bot_id': bot_id})
                row = result.fetchone()
                
                if row:
                    return {
                        'chat_id': row[0],
                        'chat_title': row[1],
                        'chat_username': row[2],
                        'chat_type': row[3],
                        'added_at': row[4],
                        'last_rerait': row[5]
                    }
                return None
                
        except Exception as e:
            logger.error("💥 Error getting channel info", bot_id=bot_id, error=str(e))
            return None

    async def save_rewrite_result(self, bot_id: str, rewrite_data: Dict[str, Any]) -> bool:
        """✅ ИСПРАВЛЕНО: Сохранение результата рерайта с гарантированными медиа ключами"""
        try:
            # ✅ ИСПРАВЛЕНИЕ: Убеждаемся что оба ключа медиа присутствуют перед сохранением
            if isinstance(rewrite_data, dict):
                # Если есть media_info, но нет media - дублируем
                if 'media_info' in rewrite_data and 'media' not in rewrite_data:
                    rewrite_data['media'] = rewrite_data['media_info']
                    logger.debug("📎 Added 'media' key before saving", 
                                bot_id=bot_id,
                                has_media_info=bool(rewrite_data['media_info']))
                
                # Если есть media, но нет media_info - дублируем
                elif 'media' in rewrite_data and 'media_info' not in rewrite_data:
                    rewrite_data['media_info'] = rewrite_data['media']
                    logger.debug("📎 Added 'media_info' key before saving", 
                                bot_id=bot_id,
                                has_media=bool(rewrite_data['media']))
            
            async with get_db_session() as session:
                query = text("""
                UPDATE bot_admin_channels 
                SET last_rerait = :rewrite_data
                WHERE bot_id = :bot_id AND is_active = true
                """)
                
                result = await session.execute(query, {
                    'bot_id': bot_id,
                    'rewrite_data': json.dumps(rewrite_data)
                })
                await session.commit()
                
                success = result.rowcount > 0
                
                logger.debug("✅ Rewrite result saved with guaranteed media keys", 
                            bot_id=bot_id,
                            success=success,
                            channels_updated=result.rowcount,
                            has_media=bool(rewrite_data.get('media')),
                            has_media_info=bool(rewrite_data.get('media_info')))
                
                return success
                
        except Exception as e:
            logger.error("💥 Error saving rewrite result with media keys", 
                        bot_id=bot_id, 
                        error=str(e),
                        exc_info=True)
            return False

    async def get_last_rewrite(self, bot_id: str) -> Optional[Dict[str, Any]]:
        """✅ ИСПРАВЛЕНО: Получение последнего рерайта с гарантированными медиа ключами"""
        try:
            async with get_db_session() as session:
                query = text("""
                SELECT last_rerait FROM bot_admin_channels 
                WHERE bot_id = :bot_id AND is_active = true
                LIMIT 1
                """)
                result = await session.execute(query, {'bot_id': bot_id})
                row = result.fetchone()
                
                if row and row[0]:
                    rewrite_data = row[0]  # JSONB автоматически deserializуется
                    
                    # ✅ ИСПРАВЛЕНИЕ: Гарантируем наличие обоих медиа ключей
                    if isinstance(rewrite_data, dict):
                        # Если есть media_info, но нет media - дублируем
                        if 'media_info' in rewrite_data and 'media' not in rewrite_data:
                            rewrite_data['media'] = rewrite_data['media_info']
                            logger.debug("📎 Added 'media' key from 'media_info'", 
                                        bot_id=bot_id,
                                        has_media_info=bool(rewrite_data['media_info']))
                        
                        # Если есть media, но нет media_info - дублируем
                        elif 'media' in rewrite_data and 'media_info' not in rewrite_data:
                            rewrite_data['media_info'] = rewrite_data['media']
                            logger.debug("📎 Added 'media_info' key from 'media'", 
                                        bot_id=bot_id,
                                        has_media=bool(rewrite_data['media']))
                        
                        # Логирование для отладки
                        logger.debug("✅ Last rewrite retrieved with guaranteed media keys", 
                                   bot_id=bot_id,
                                   has_content=bool(rewrite_data.get('content')),
                                   has_media=bool(rewrite_data.get('media')),
                                   has_media_info=bool(rewrite_data.get('media_info')),
                                   rewrite_keys=list(rewrite_data.keys()))
                    
                    return rewrite_data
                
                logger.debug("⚠️ No last rewrite found", bot_id=bot_id)
                return None
                
        except Exception as e:
            logger.error("💥 Error getting last rewrite with media keys fix", 
                        bot_id=bot_id, 
                        error=str(e),
                        exc_info=True)
            return None
    
    # ===== CONTENT AGENTS CRUD =====
    
    async def create_content_agent(
        self,
        bot_id: str,
        agent_name: str,
        instructions: str,
        openai_agent_id: str = None
    ) -> Optional[Dict[str, Any]]:
        """✅ Создание контент-агента с проверкой существующих"""
        
        logger.info("💾 Creating content agent in database", 
                   bot_id=bot_id,
                   agent_name=agent_name,
                   has_openai_id=bool(openai_agent_id))
        
        try:
            await self._ensure_tables_exist()
            
            async with get_db_session() as session:
                # ✅ ПРОВЕРЯЕМ СУЩЕСТВУЮЩИЙ АГЕНТ
                check_query = text("""
                SELECT id, agent_name, instructions, openai_agent_id, 
                       is_active, created_at, updated_at
                FROM content_agents 
                WHERE bot_id = :bot_id AND is_active = true
                LIMIT 1
                """)
                
                existing_result = await session.execute(check_query, {'bot_id': bot_id})
                existing_agent = existing_result.fetchone()
                
                if existing_agent:
                    logger.info("🔄 Content agent already exists, updating instead", 
                               bot_id=bot_id,
                               existing_name=existing_agent[1],
                               new_name=agent_name)
                    
                    # ОБНОВЛЯЕМ СУЩЕСТВУЮЩИЙ АГЕНТ
                    update_query = text("""
                    UPDATE content_agents 
                    SET agent_name = :agent_name,
                        instructions = :instructions,
                        openai_agent_id = :openai_agent_id,
                        updated_at = NOW()
                    WHERE bot_id = :bot_id AND is_active = true
                    RETURNING id, bot_id, agent_name, instructions, openai_agent_id, 
                             is_active, created_at, updated_at
                    """)
                    
                    result = await session.execute(update_query, {
                        'bot_id': bot_id,
                        'agent_name': agent_name,
                        'instructions': instructions,
                        'openai_agent_id': openai_agent_id
                    })
                    
                    await session.commit()
                    row = result.fetchone()
                    
                    if row:
                        agent_data = {
                            'id': row[0],
                            'bot_id': row[1],
                            'agent_name': row[2],
                            'instructions': row[3],
                            'openai_agent_id': row[4],
                            'is_active': row[5],
                            'created_at': row[6],
                            'updated_at': row[7],
                            'action': 'updated'  # ✅ ПОКАЗЫВАЕМ ЧТО ОБНОВИЛИ
                        }
                        
                        logger.info("✅ Content agent updated successfully", 
                                   agent_id=agent_data['id'],
                                   bot_id=bot_id,
                                   agent_name=agent_name)
                        return agent_data
                
                # СОЗДАЕМ НОВЫЙ АГЕНТ ТОЛЬКО ЕСЛИ НЕТ СУЩЕСТВУЮЩЕГО
                create_query = text("""
                INSERT INTO content_agents (
                    bot_id, agent_name, instructions, openai_agent_id, 
                    is_active, created_at, updated_at
                ) VALUES (:bot_id, :agent_name, :instructions, :openai_agent_id, true, NOW(), NOW())
                RETURNING id, bot_id, agent_name, instructions, openai_agent_id, 
                         is_active, created_at, updated_at
                """)
                
                result = await session.execute(create_query, {
                    'bot_id': bot_id,
                    'agent_name': agent_name,
                    'instructions': instructions,
                    'openai_agent_id': openai_agent_id
                })
                
                await session.commit()
                row = result.fetchone()
                
                if row:
                    agent_data = {
                        'id': row[0],
                        'bot_id': row[1],
                        'agent_name': row[2],
                        'instructions': row[3],
                        'openai_agent_id': row[4],
                        'is_active': row[5],
                        'created_at': row[6],
                        'updated_at': row[7],
                        'action': 'created'  # ✅ ПОКАЗЫВАЕМ ЧТО СОЗДАЛИ
                    }
                    
                    logger.info("✅ Content agent created successfully", 
                               agent_id=agent_data['id'],
                               bot_id=bot_id,
                               agent_name=agent_name)
                    return agent_data
                else:
                    logger.error("❌ Failed to create content agent in database")
                    return None
                    
        except Exception as e:
            logger.error("💥 Database error creating content agent", 
                        bot_id=bot_id,
                        error=str(e),
                        exc_info=True)
            return None
    
    async def get_content_agent(self, bot_id: str) -> Optional[Dict[str, Any]]:
        """Получение контент-агента по bot_id"""
        try:
            await self._ensure_tables_exist()
            
            async with get_db_session() as session:
                query = text("""
                SELECT id, bot_id, agent_name, instructions, openai_agent_id, 
                       is_active, created_at, updated_at
                FROM content_agents 
                WHERE bot_id = :bot_id AND is_active = true
                ORDER BY created_at DESC
                LIMIT 1
                """)
                
                result = await session.execute(query, {'bot_id': bot_id})
                row = result.fetchone()
                
                if row:
                    return {
                        'id': row[0],
                        'bot_id': row[1],
                        'agent_name': row[2],
                        'instructions': row[3],
                        'openai_agent_id': row[4],
                        'is_active': row[5],
                        'created_at': row[6],
                        'updated_at': row[7]
                    }
                return None
                
        except Exception as e:
            logger.error("💥 Error fetching content agent", bot_id=bot_id, error=str(e))
            return None
    
    async def update_content_agent(
        self,
        bot_id: str,
        agent_name: str = None,
        instructions: str = None
    ) -> bool:
        """Обновление контент-агента"""
        try:
            await self._ensure_tables_exist()
            
            async with get_db_session() as session:
                updates = []
                params = {'bot_id': bot_id}
                
                if agent_name:
                    updates.append("agent_name = :agent_name")
                    params['agent_name'] = agent_name
                
                if instructions:
                    updates.append("instructions = :instructions")
                    params['instructions'] = instructions
                
                if not updates:
                    return False
                
                updates.append("updated_at = NOW()")
                
                query = text(f"""
                UPDATE content_agents 
                SET {', '.join(updates)}
                WHERE bot_id = :bot_id AND is_active = true
                """)
                
                result = await session.execute(query, params)
                await session.commit()
                
                rows_affected = result.rowcount
                
                logger.info("✅ Content agent updated", bot_id=bot_id, rows_affected=rows_affected)
                return rows_affected > 0
                    
        except Exception as e:
            logger.error("💥 Error updating content agent", bot_id=bot_id, error=str(e))
            return False
    
    async def delete_content_agent(self, bot_id: str, soft_delete: bool = True) -> bool:
        """Удаление контент-агента"""
        try:
            await self._ensure_tables_exist()
            
            async with get_db_session() as session:
                if soft_delete:
                    query = text("""
                    UPDATE content_agents 
                    SET is_active = false, updated_at = NOW()
                    WHERE bot_id = :bot_id AND is_active = true
                    """)
                else:
                    query = text("DELETE FROM content_agents WHERE bot_id = :bot_id")
                
                result = await session.execute(query, {'bot_id': bot_id})
                await session.commit()
                
                rows_affected = result.rowcount
                return rows_affected > 0
                    
        except Exception as e:
            logger.error("💥 Error deleting content agent", bot_id=bot_id, error=str(e))
            return False
    
    async def has_content_agent(self, bot_id: str) -> bool:
        """Проверка наличия активного контент-агента"""
        try:
            await self._ensure_tables_exist()
            
            async with get_db_session() as session:
                query = text("""
                SELECT EXISTS(
                    SELECT 1 FROM content_agents 
                    WHERE bot_id = :bot_id AND is_active = true
                )
                """)
                
                result = await session.execute(query, {'bot_id': bot_id})
                return bool(result.scalar())
                
        except Exception as e:
            logger.error("💥 Error checking content agent existence", bot_id=bot_id, error=str(e))
            return False
    
    # ===== OPENAI INTEGRATION =====
    
    async def create_openai_content_agent(
        self,
        bot_id: str,
        agent_name: str,
        instructions: str
    ) -> Optional[str]:
        """✅ Создание через Responses API"""
        
        logger.info("🤖 Creating OpenAI content agent via Responses API", 
                   bot_id=bot_id,
                   agent_name=agent_name,
                   instructions_length=len(instructions))
        
        try:
            if not self.openai_client:
                logger.error("❌ OpenAI client not available")
                return None
            
            # ✅ Вызов через _responses_with_retry как в проекте
            if hasattr(self.openai_client, '_responses_with_retry'):
                # Тестовый вызов для создания агента согласно архитектуре проекта
                result = await self.openai_client._responses_with_retry(
                    model="gpt-4o",
                    instructions=instructions,
                    input="Привет! Представься как контент-агент.",  # Тестовое сообщение
                    store=True,                                      # Сохранять контекст
                    max_output_tokens=150                           # Лимит для теста
                )
            elif hasattr(self.openai_client, 'create_assistant'):
                # Fallback: прямой вызов create_assistant
                result = await self.openai_client.create_assistant(
                    model="gpt-4o",
                    instructions=instructions
                )
            else:
                logger.error("❌ No suitable method available")
                return None
            
            # Обработка ответа от Responses API
            if result:
                # Responses API возвращает response_id как ID агента
                response_id = None
                
                if hasattr(result, 'id'):
                    response_id = result.id
                elif isinstance(result, dict):
                    response_id = result.get('id') or result.get('response_id') or result.get('assistant_id')
                elif hasattr(result, 'response_id'):
                    response_id = result.response_id
                
                if response_id:
                    logger.info("✅ OpenAI content agent created via Responses API", 
                               bot_id=bot_id,
                               agent_name=agent_name,
                               response_id=response_id)
                    return response_id
                else:
                    logger.error("❌ No response_id in result", result=str(result)[:200])
                    return None
            else:
                logger.error("❌ Empty result from OpenAI API")
                return None
                
        except Exception as e:
            logger.error("💥 Exception creating OpenAI content agent", 
                        bot_id=bot_id,
                        error=str(e),
                        exc_info=True)
            return None
    
    async def delete_openai_content_agent(self, openai_agent_id: str) -> bool:
        """✅ Удаление OpenAI агента через существующий клиент"""
        try:
            if not self.openai_client:
                return False
            
            if hasattr(self.openai_client, 'delete_assistant'):
                success = await self.openai_client.delete_assistant(openai_agent_id)
                logger.info("✅ OpenAI content agent deleted", openai_agent_id=openai_agent_id)
                return success
            else:
                logger.warning("⚠️ delete_assistant method not available")
                return True  # Предполагаем успех
                
        except Exception as e:
            logger.error("💥 Exception deleting OpenAI content agent", 
                        openai_agent_id=openai_agent_id,
                        error=str(e))
            return False
    
    # ===== ТОКЕНОВАЯ ЛОГИКА =====
    
    def calculate_tokens(self, text: str) -> Dict[str, int]:
        """
        Подсчет токенов для текста (приблизительный)
        Используется для оценки стоимости до отправки в OpenAI
        """
        try:
            # Приблизительная формула: 1 токен ≈ 4 символа для русского текста
            # Для английского: 1 токен ≈ 4-5 символов
            # Для смешанного текста: берем среднее
            
            char_count = len(text)
            
            # Подсчет русских символов
            russian_chars = sum(1 for char in text if '\u0400' <= char <= '\u04FF')
            english_chars = sum(1 for char in text if char.isalpha() and not ('\u0400' <= char <= '\u04FF'))
            other_chars = char_count - russian_chars - english_chars
            
            # Коэффициенты для разных языков
            russian_ratio = 3.5  # Русский текст более плотный
            english_ratio = 4.0   # Английский стандартный
            other_ratio = 2.0     # Числа, символы более плотные
            
            estimated_tokens = int(
                (russian_chars / russian_ratio) +
                (english_chars / english_ratio) +
                (other_chars / other_ratio)
            )
            
            # Минимум 1 токен
            estimated_tokens = max(1, estimated_tokens)
            
            logger.debug("📊 Token calculation", 
                        text_length=char_count,
                        russian_chars=russian_chars,
                        english_chars=english_chars,
                        estimated_tokens=estimated_tokens)
            
            return {
                'input_tokens': estimated_tokens,
                'estimated_cost_usd': self.estimate_cost(estimated_tokens, 0),
                'char_count': char_count,
                'breakdown': {
                    'russian_chars': russian_chars,
                    'english_chars': english_chars,
                    'other_chars': other_chars
                }
            }
            
        except Exception as e:
            logger.error("💥 Error calculating tokens", error=str(e))
            return {
                'input_tokens': len(text) // 4,  # Fallback
                'estimated_cost_usd': 0.0,
                'char_count': len(text),
                'breakdown': {}
            }
    
    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """
        Оценка стоимости в USD для GPT-4o
        Актуальные цены на январь 2025
        """
        try:
            # OpenAI GPT-4o цены (за 1K токенов)
            INPUT_COST_PER_1K = 0.005   # $0.005 за 1K input токенов
            OUTPUT_COST_PER_1K = 0.015  # $0.015 за 1K output токенов
            
            input_cost = (input_tokens / 1000) * INPUT_COST_PER_1K
            output_cost = (output_tokens / 1000) * OUTPUT_COST_PER_1K
            
            total_cost = input_cost + output_cost
            
            return round(total_cost, 6)
            
        except Exception as e:
            logger.error("💥 Error estimating cost", error=str(e))
            return 0.0
    
    # ===== ✅ ЗАМЕНЕНО: НОВАЯ ЛОГИКА ЧЕРЕЗ TokenManager =====
    
    async def check_token_limits(self, bot_id: str, user_id: int, estimated_tokens: int) -> Dict[str, Any]:
        """
        ✅ УПРОЩЕНО: Проверка лимитов через единую систему TokenManager
        ContentManager больше не управляет лимитами, только статистикой
        """
        try:
            from database.managers.token_manager import TokenManager
            
            # Используем единую систему проверки лимитов
            has_tokens, used_tokens, limit_tokens = await TokenManager.check_token_limit(user_id)
            
            result = {
                'can_proceed': has_tokens,
                'current_usage': {
                    'total_used': used_tokens,
                    'estimated_total': used_tokens + estimated_tokens
                },
                'limits': {
                    'total_limit': limit_tokens
                },
                'estimated_tokens': estimated_tokens,
                'estimated_cost': self.estimate_cost(estimated_tokens, estimated_tokens),
                'warnings': [],
                'method': 'unified_token_system'
            }
            
            if not has_tokens:
                result['warnings'].append('Превышен лимит токенов пользователя')
            
            logger.info("🔍 Token limits check via unified system", 
                       bot_id=bot_id,
                       user_id=user_id,
                       can_proceed=result['can_proceed'],
                       used_tokens=used_tokens,
                       limit_tokens=limit_tokens,
                       estimated_tokens=estimated_tokens)
            
            return result
            
        except ImportError:
            logger.warning("⚠️ TokenManager not available, allowing request")
            # В случае ошибки - разрешаем продолжить
            return {
                'can_proceed': True,
                'current_usage': {'total_used': 0, 'estimated_total': estimated_tokens},
                'limits': {'total_limit': 500000},
                'estimated_tokens': estimated_tokens,
                'estimated_cost': 0.0,
                'warnings': ['TokenManager недоступен - проверка лимитов пропущена'],
                'method': 'fallback'
            }
        except Exception as e:
            logger.error("💥 Error checking token limits via unified system", 
                        bot_id=bot_id,
                        user_id=user_id,
                        error=str(e))
            # В случае ошибки - разрешаем продолжить
            return {
                'can_proceed': True,
                'current_usage': {'total_used': 0, 'estimated_total': estimated_tokens},
                'limits': {'total_limit': 500000},
                'estimated_tokens': estimated_tokens,
                'estimated_cost': 0.0,
                'warnings': [f'Ошибка проверки лимитов: {str(e)}'],
                'method': 'error_fallback'
            }
    
    async def get_daily_token_usage(self, bot_id: str, user_id: int) -> int:
        """✅ Получение использования токенов за сегодня"""
        try:
            await self._ensure_tables_exist()
            
            async with get_db_session() as session:
                query = text("""
                SELECT COALESCE(SUM(tokens_used), 0) as daily_usage
                FROM content_rewrite_stats 
                WHERE bot_id = :bot_id AND user_id = :user_id 
                AND created_at >= CURRENT_DATE
                """)
                
                result = await session.execute(query, {'bot_id': bot_id, 'user_id': user_id})
                usage = result.scalar()
                return int(usage) if usage else 0
                
        except Exception as e:
            logger.error("💥 Error getting daily token usage", error=str(e))
            return 0
    
    async def get_token_limit(self, bot_id: str, period: str) -> int:
        """Получение лимита токенов для бота"""
        try:
            # Стандартные лимиты (можно вынести в настройки)
            default_limits = {
                'daily': 5000,    # 5K токенов в день
                'monthly': 50000  # 50K токенов в месяц
            }
            
            # Попытка получить из настроек бота (если есть таблица user_bots)
            try:
                async with get_db_session() as session:
                    query = text("""
                    SELECT ai_assistant_settings
                    FROM user_bots 
                    WHERE bot_id = :bot_id
                    """)
                    
                    result = await session.execute(query, {'bot_id': bot_id})
                    settings = result.scalar()
                    
                    if settings and isinstance(settings, dict):
                        content_settings = settings.get('content_settings', {})
                        custom_limit = content_settings.get(f'{period}_token_limit')
                        
                        if custom_limit and isinstance(custom_limit, int):
                            return custom_limit
            except:
                pass  # Игнорируем ошибки получения настроек
            
            return default_limits.get(period, 1000)
            
        except Exception as e:
            logger.error("💥 Error getting token limit", error=str(e))
            return 1000  # Fallback лимит
    
    async def _will_exceed_monthly_limit(self, bot_id: str, estimated_tokens: int, monthly_limit: int) -> bool:
        """✅ Проверка превышения месячного лимита"""
        try:
            await self._ensure_tables_exist()
            
            async with get_db_session() as session:
                query = text("""
                SELECT COALESCE(SUM(tokens_used), 0) as monthly_usage
                FROM content_rewrite_stats 
                WHERE bot_id = :bot_id 
                AND created_at >= DATE_TRUNC('month', CURRENT_DATE)
                """)
                
                result = await session.execute(query, {'bot_id': bot_id})
                monthly_usage = int(result.scalar() or 0)
                
                return (monthly_usage + estimated_tokens) > monthly_limit
                
        except Exception as e:
            logger.error("💥 Error checking monthly limit", error=str(e))
            return False

    # ===== ✅ НОВОЕ: ПОЛУЧЕНИЕ admin_chat_id БОТА =====
    
    async def _get_bot_admin_chat_id(self, bot_id: str) -> Optional[int]:
        """
        ✅ НОВОЕ: Получение admin_chat_id для бота из таблицы user_bots
        Необходимо для корректного сохранения токенов через TokenManager
        """
        try:
            async with get_db_session() as session:
                query = text("""
                SELECT admin_chat_id 
                FROM user_bots 
                WHERE bot_id = :bot_id
                LIMIT 1
                """)
                
                result = await session.execute(query, {'bot_id': bot_id})
                admin_chat_id = result.scalar()
                
                if admin_chat_id:
                    logger.debug("✅ Admin chat ID found for bot", 
                               bot_id=bot_id,
                               admin_chat_id=admin_chat_id)
                    return int(admin_chat_id)
                else:
                    logger.warning("⚠️ No admin_chat_id found for bot", bot_id=bot_id)
                    return None
                    
        except Exception as e:
            logger.error("💥 Error getting bot admin_chat_id", 
                        bot_id=bot_id,
                        error=str(e))
            return None
    
    # ===== 🔧 ИСПРАВЛЕНО: CONTENT PROCESSING С ПРАВИЛЬНОЙ СТРУКТУРОЙ И ССЫЛКАМИ =====
    
    async def process_content_rewrite(
        self,
        bot_id: str,
        original_text: str,
        media_info: Optional[Dict[str, Any]] = None,
        links_info: Optional[Dict[str, Any]] = None,  # ✨ НОВОЕ
        user_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """✅ ИСПРАВЛЕНО: Обработка рерайта с правильной структурой для content_handlers.py + поддержка ссылок"""
        
        logger.info("📝 Processing content rewrite with unified structure + links", 
                   bot_id=bot_id,
                   text_length=len(original_text),
                   has_media=bool(media_info),
                   has_links=bool(links_info and links_info.get('has_links')),
                   total_links=links_info.get('total_links', 0) if links_info else 0,
                   user_id=user_id,
                   media_type=media_info.get('type') if media_info else None)
        
        try:
            # 1. Получаем агента
            agent = await self.get_content_agent(bot_id)
            if not agent:
                return {
                    'success': False,
                    'error': 'no_agent',
                    'message': 'Контент-агент не найден'
                }
            
            openai_agent_id = agent.get('openai_agent_id')
            if not openai_agent_id:
                return {
                    'success': False,
                    'error': 'no_openai_id',
                    'message': 'OpenAI агент не настроен'
                }
            
            # 2. Подсчитываем токены
            token_calc = self.calculate_tokens(original_text)
            estimated_input_tokens = token_calc['input_tokens']
            
            # 3. Проверяем лимиты ЧЕРЕЗ TokenManager
            if user_id:
                limits_check = await self.check_token_limits(bot_id, user_id, estimated_input_tokens)
                
                if not limits_check['can_proceed']:
                    return {
                        'success': False,
                        'error': 'token_limit_exceeded',
                        'message': 'Превышен лимит токенов',
                        'details': limits_check
                    }
            
            # ✨ 4. ОБНОВЛЕНО: Специальная обработка для медиагрупп + ссылки
            enhanced_instructions = agent['instructions']

            if media_info and media_info.get('type') == 'media_group':
                logger.info("📸 Processing media group rewrite", 
                           bot_id=bot_id,
                           media_count=media_info.get('count', 0),
                           media_group_id=media_info.get('media_group_id'))
                
                enhanced_instructions += f"""

СПЕЦИАЛЬНАЯ ЗАДАЧА: Переписывай этот текст для альбома из {media_info.get('count', 0)} медиафайлов.
Учитывай, что это групповой контент с несколькими фото/видео.
Сохраняй смысл, но адаптируй под формат альбома.
"""

            # ✨ НОВОЕ: Добавляем информацию о ссылках в промпт
            if links_info and links_info.get('has_links'):
                links_context = self._format_links_for_ai(links_info['links'])
                
                enhanced_instructions += f"""

🔗 ВАЖНАЯ ИНФОРМАЦИЯ О ССЫЛКАХ В ТЕКСТЕ:
{links_context}

ПРИ РЕРАЙТЕ ОБЯЗАТЕЛЬНО:
- Сохраняй все ссылки в переписанном тексте
- Если есть скрытые гиперссылки (текст с ссылкой), укажи и текст и саму ссылку
- Не удаляй и не изменяй URL адреса
- Email адреса и телефоны оставляй без изменений
- Упоминания пользователей (@username) сохраняй точно
"""
                
                logger.info("🔗 Links information added to AI instructions", 
                           bot_id=bot_id,
                           total_links=links_info.get('total_links', 0),
                           links_context_length=len(links_context))
            
            # 5. Выполняем рерайт через Responses API
            start_time = time.time()
            
            # ✅ Используем правильный вызов для Responses API
            if hasattr(self.openai_client, '_responses_with_retry'):
                # Основной метод - через _responses_with_retry
                rewrite_result = await self.openai_client._responses_with_retry(
                    model="gpt-4o",
                    instructions=f"Ты контент-агент. {enhanced_instructions}",
                    input=original_text,
                    previous_response_id=openai_agent_id,  # ID агента как context
                    store=True,                           # Сохранять контекст
                    max_output_tokens=2000               # Лимит токенов для ответа
                )
            elif hasattr(self.openai_client, 'send_message'):
                # Fallback: метод send_message
                rewrite_result = await self.openai_client.send_message(
                    assistant_id=openai_agent_id,
                    message=original_text,
                    user_id=user_id or 0
                )
            else:
                # Последний fallback: mock
                rewrite_result = await self.openai_client._responses_with_retry(
                    model="mock-gpt-4o",
                    instructions=enhanced_instructions,
                    input=original_text
                )
            
            processing_time = time.time() - start_time
            
            # 6. Обрабатываем результат Responses API
            rewritten_text = ""
            actual_tokens = {}
            
            if rewrite_result:
                # Извлекаем текст из ответа Responses API
                if hasattr(rewrite_result, 'output_text'):
                    rewritten_text = rewrite_result.output_text
                elif hasattr(rewrite_result, 'output') and rewrite_result.output:
                    # Обрабатываем структуру output
                    for output_item in rewrite_result.output:
                        if output_item.get('type') == 'message':
                            content = output_item.get('content', [])
                            for content_item in content:
                                if content_item.get('type') == 'output_text':
                                    rewritten_text = content_item.get('text', '')
                                    break
                            if rewritten_text:
                                break
                
                # ✅ Извлекаем токены КАК В client.py - через hasattr и прямые атрибуты
                if hasattr(rewrite_result, 'usage') and rewrite_result.usage is not None:
                    usage_obj = rewrite_result.usage
                    
                    input_tokens = None
                    output_tokens = None
                    
                    # ✅ КОПИРУЕМ ЛОГИКУ ИЗ client.py
                    if hasattr(usage_obj, 'input_tokens') and getattr(usage_obj, 'input_tokens') is not None:
                        input_tokens = usage_obj.input_tokens  # ⭐ ПРЯМОЕ обращение к атрибуту
                    elif hasattr(usage_obj, 'prompt_tokens') and getattr(usage_obj, 'prompt_tokens') is not None:
                        input_tokens = usage_obj.prompt_tokens  # ⭐ ПРЯМОЕ обращение к атрибуту
                    
                    if hasattr(usage_obj, 'output_tokens') and getattr(usage_obj, 'output_tokens') is not None:
                        output_tokens = usage_obj.output_tokens  # ⭐ ПРЯМОЕ обращение к атрибуту
                    elif hasattr(usage_obj, 'completion_tokens') and getattr(usage_obj, 'completion_tokens') is not None:
                        output_tokens = usage_obj.completion_tokens  # ⭐ ПРЯМОЕ обращение к атрибуту
                    
                    # Fallback если не нашли токены
                    if input_tokens is None or output_tokens is None:
                        estimated_input = max(1, int(len(original_text.split()) * 1.3))
                        estimated_output = max(1, int(len(rewritten_text.split()) * 1.3)) if rewritten_text else 1
                        
                        input_tokens = input_tokens or estimated_input
                        output_tokens = output_tokens or estimated_output
                    
                    actual_tokens = {
                        'input_tokens': int(input_tokens),      # ✅ ПРАВИЛЬНАЯ СТРУКТУРА для handlers
                        'output_tokens': int(output_tokens),    # ✅ ПРАВИЛЬНАЯ СТРУКТУРА для handlers
                        'total_tokens': int(input_tokens + output_tokens)  # ✅ ПРАВИЛЬНАЯ СТРУКТУРА для handlers
                    }
                    
                    logger.debug("✅ Tokens extracted successfully", 
                                input_tokens=input_tokens,
                                output_tokens=output_tokens,
                                total_tokens=input_tokens + output_tokens)
                    
                elif isinstance(rewrite_result, dict):
                    # Старый формат для backward compatibility
                    rewritten_text = rewrite_result.get('content', str(rewrite_result))
                    actual_tokens = {
                        'input_tokens': estimated_input_tokens,
                        'output_tokens': len(rewritten_text) // 4,
                        'total_tokens': estimated_input_tokens + len(rewritten_text) // 4
                    }
                else:
                    # Простой текстовый ответ
                    if not rewritten_text:
                        rewritten_text = str(rewrite_result)
                    
                    # Приблизительный подсчет токенов
                    output_calc = self.calculate_tokens(rewritten_text)
                    actual_tokens = {
                        'input_tokens': estimated_input_tokens,
                        'output_tokens': output_calc['input_tokens'],
                        'total_tokens': estimated_input_tokens + output_calc['input_tokens']
                    }
            
            if rewritten_text:
                # ✅ 7. НОВОЕ: СОХРАНЯЕМ ТОКЕНЫ В ЕДИНУЮ СИСТЕМУ TokenManager
                try:
                    from database.managers.token_manager import TokenManager
                    
                    # Получаем admin_chat_id для бота
                    admin_chat_id = await self._get_bot_admin_chat_id(bot_id)
                    
                    # ✅ ГЛАВНОЕ ИЗМЕНЕНИЕ: Сохраняем токены в единую систему
                    await TokenManager.save_token_usage(
                        bot_id=bot_id,
                        input_tokens=actual_tokens.get('input_tokens', 0),
                        output_tokens=actual_tokens.get('output_tokens', 0),
                        admin_chat_id=admin_chat_id,
                        user_id=user_id
                    )
                    
                    logger.info("✅ Tokens saved to unified TokenManager system", 
                               bot_id=bot_id,
                               user_id=user_id,
                               input_tokens=actual_tokens.get('input_tokens', 0),
                               output_tokens=actual_tokens.get('output_tokens', 0),
                               total_tokens=actual_tokens.get('total_tokens', 0),
                               admin_chat_id=admin_chat_id)
                    
                except ImportError:
                    logger.warning("⚠️ TokenManager not available - tokens not saved to unified system")
                except Exception as token_error:
                    logger.error("💥 Failed to save tokens via TokenManager", 
                                bot_id=bot_id,
                                user_id=user_id,
                                error=str(token_error))
                
                # ✅ 8. ДОПОЛНИТЕЛЬНО: Сохраняем детальную статистику для аналитики
                await self._save_rewrite_stats(
                    bot_id=bot_id,
                    user_id=user_id,
                    tokens_used=actual_tokens.get('total_tokens', estimated_input_tokens),
                    processing_time=processing_time,
                    input_tokens=actual_tokens.get('input_tokens', estimated_input_tokens),
                    output_tokens=actual_tokens.get('output_tokens', 0)
                )
                
                logger.info("✅ Content rewrite successful with unified token integration and links support", 
                           bot_id=bot_id,
                           original_length=len(original_text),
                           rewritten_length=len(rewritten_text),
                           tokens_used=actual_tokens.get('total_tokens', 0),
                           processing_time=f"{processing_time:.2f}s",
                           is_media_group=media_info.get('type') == 'media_group' if media_info else False,
                           has_links=bool(links_info and links_info.get('has_links')),
                           total_links=links_info.get('total_links', 0) if links_info else 0,
                           integration_status="✅ Tokens saved via TokenManager + detailed stats + links processed")
                
                # ✅ 9. ИСПРАВЛЕНО: ПРАВИЛЬНАЯ СТРУКТУРА ДЛЯ content_handlers.py С ПОДДЕРЖКОЙ ССЫЛОК
                return {
                    'success': True,
                    'content': {                                    # ✅ ОБЕРНУТО В content
                        'original_text': original_text,
                        'rewritten_text': rewritten_text,
                        'text_length_change': len(rewritten_text) - len(original_text)
                    },
                    'tokens': {                                     # ✅ ПРАВИЛЬНОЕ ИМЕНОВАНИЕ
                        'input_tokens': actual_tokens.get('input_tokens', 0),
                        'output_tokens': actual_tokens.get('output_tokens', 0),
                        'total_tokens': actual_tokens.get('total_tokens', 0),
                        'estimated_cost_usd': self.estimate_cost(
                            actual_tokens.get('input_tokens', 0),
                            actual_tokens.get('output_tokens', 0)
                        )
                    },
                    'agent': {                                      # ✅ ДОБАВЛЕНА ИНФОРМАЦИЯ ОБ АГЕНТЕ
                        'name': agent['agent_name'],
                        'id': agent['id'],
                        'instructions': agent['instructions']
                    },
                    'media_info': media_info,                       # ✅ ИНФОРМАЦИЯ О МЕДИА
                    'links_info': links_info,                       # ✨ НОВОЕ: ИНФОРМАЦИЯ О ССЫЛКАХ
                    'processing_time': processing_time,
                    'model_used': 'gpt-4o',
                    'agent_type': 'openai_responses',
                    'is_media_group': media_info.get('type') == 'media_group' if media_info else False,
                    'has_links': bool(links_info and links_info.get('has_links')),  # ✨ НОВОЕ
                    'token_integration': 'unified_system',          # ✅ МАРКЕР ИНТЕГРАЦИИ
                    'links_processing': 'enhanced_instructions'     # ✨ НОВОЕ: МАРКЕР ОБРАБОТКИ ССЫЛОК
                }
            else:
                return {
                    'success': False,
                    'error': 'no_response',
                    'message': 'OpenAI агент не вернул ответ'
                }
                
        except Exception as e:
            logger.error("💥 Exception in content rewrite with links support", 
                        bot_id=bot_id,
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            return {
                'success': False,
                'error': 'processing_exception',
                'message': f'Ошибка обработки: {str(e)}'
            }
    
    # ===== ✅ ОБНОВЛЕНО: НОВАЯ ЛОГИКА СОХРАНЕНИЯ СТАТИСТИКИ =====
    
    async def _save_rewrite_stats(
        self,
        bot_id: str,
        user_id: Optional[int],
        tokens_used: int,
        processing_time: float,
        input_tokens: int = 0,
        output_tokens: int = 0
    ) -> None:
        """
        ✅ ОБНОВЛЕНО: Сохраняем только детальную статистику для аналитики
        Основные токены теперь сохраняются через TokenManager.save_token_usage()
        """
        try:
            await self._ensure_tables_exist()
            
            async with get_db_session() as session:
                query = text("""
                INSERT INTO content_rewrite_stats (
                    bot_id, user_id, tokens_used, processing_time, 
                    input_tokens, output_tokens, created_at
                ) VALUES (:bot_id, :user_id, :tokens_used, :processing_time, 
                         :input_tokens, :output_tokens, NOW())
                """)
                
                await session.execute(query, {
                    'bot_id': bot_id,
                    'user_id': user_id,
                    'tokens_used': tokens_used,
                    'processing_time': processing_time,
                    'input_tokens': input_tokens,
                    'output_tokens': output_tokens
                })
                
                await session.commit()
                
                logger.debug("📊 Content rewrite detailed statistics saved", 
                            bot_id=bot_id,
                            tokens_used=tokens_used,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            processing_time=processing_time,
                            note="✅ Main tokens saved via TokenManager.save_token_usage()")
                
        except Exception as e:
            logger.warning("⚠️ Failed to save content rewrite detailed statistics (non-critical)", 
                          bot_id=bot_id,
                          error=str(e))
    
    # ===== STATISTICS =====
    
    async def get_content_agent_stats(self, bot_id: str) -> Dict[str, Any]:
        """✅ Расширенная статистика с токенами"""
        try:
            agent = await self.get_content_agent(bot_id)
            if not agent:
                return {}
            
            await self._ensure_tables_exist()
            
            async with get_db_session() as session:
                # Детальная статистика токенов
                stats_query = text("""
                SELECT 
                    COALESCE(SUM(tokens_used), 0) as total_tokens,
                    COALESCE(SUM(input_tokens), 0) as total_input_tokens,
                    COALESCE(SUM(output_tokens), 0) as total_output_tokens,
                    COUNT(*) as total_rewrites,
                    AVG(processing_time) as avg_processing_time,
                    MAX(created_at) as last_usage_at,
                    AVG(tokens_used) as avg_tokens_per_rewrite
                FROM content_rewrite_stats 
                WHERE bot_id = :bot_id
                """)
                
                stats_result = await session.execute(stats_query, {'bot_id': bot_id})
                stats_row = stats_result.fetchone()
                
                # Статистика за последние 7 дней
                weekly_query = text("""
                SELECT 
                    COALESCE(SUM(tokens_used), 0) as weekly_tokens,
                    COUNT(*) as weekly_rewrites
                FROM content_rewrite_stats 
                WHERE bot_id = :bot_id AND created_at >= NOW() - INTERVAL '7 days'
                """)
                
                weekly_result = await session.execute(weekly_query, {'bot_id': bot_id})
                weekly_row = weekly_result.fetchone()
                
                total_tokens = int(stats_row[0]) if stats_row else 0
                total_cost = self.estimate_cost(
                    int(stats_row[1]) if stats_row else 0,
                    int(stats_row[2]) if stats_row else 0
                )
                
                stats = {
                    'has_openai_id': bool(agent.get('openai_agent_id')),
                    'tokens_used': total_tokens,
                    'input_tokens': int(stats_row[1]) if stats_row else 0,
                    'output_tokens': int(stats_row[2]) if stats_row else 0,
                    'total_cost_usd': total_cost,
                    'total_rewrites': int(stats_row[3]) if stats_row else 0,
                    'avg_processing_time': float(stats_row[4]) if stats_row and stats_row[4] else 0,
                    'avg_tokens_per_rewrite': float(stats_row[6]) if stats_row and stats_row[6] else 0,
                    'last_usage_at': stats_row[5].isoformat() if stats_row and stats_row[5] else None,
                    'weekly_stats': {
                        'tokens': int(weekly_row[0]) if weekly_row else 0,
                        'rewrites': int(weekly_row[1]) if weekly_row else 0
                    }
                }
                
                logger.debug("📊 Extended content agent stats retrieved", 
                            bot_id=bot_id,
                            total_tokens=total_tokens,
                            total_cost=total_cost)
                
                return stats
                
        except Exception as e:
            logger.error("💥 Error fetching content agent stats", 
                        bot_id=bot_id,
                        error=str(e))
            return {}
    
    async def get_all_content_agents_summary(self) -> Dict[str, Any]:
        """✅ Сводная статистика всех агентов с токенами"""
        try:
            await self._ensure_tables_exist()
            
            async with get_db_session() as session:
                summary_query = text("""
                SELECT 
                    COUNT(*) as total_content_agents,
                    COUNT(CASE WHEN is_active = true THEN 1 END) as active_agents,
                    COUNT(CASE WHEN openai_agent_id IS NOT NULL THEN 1 END) as agents_with_openai
                FROM content_agents
                """)
                
                summary_result = await session.execute(summary_query)
                summary_row = summary_result.fetchone()
                
                # Общая статистика использования токенов
                usage_query = text("""
                SELECT 
                    COALESCE(SUM(tokens_used), 0) as total_tokens_used,
                    COALESCE(SUM(input_tokens), 0) as total_input_tokens,
                    COALESCE(SUM(output_tokens), 0) as total_output_tokens,
                    COUNT(*) as total_rewrites_made,
                    AVG(processing_time) as avg_processing_time
                FROM content_rewrite_stats
                """)
                
                usage_result = await session.execute(usage_query)
                usage_row = usage_result.fetchone()
                
                total_cost = self.estimate_cost(
                    int(usage_row[1]) if usage_row else 0,
                    int(usage_row[2]) if usage_row else 0
                )
                
                summary = {
                    'total_content_agents': int(summary_row[0]) if summary_row else 0,
                    'active_agents': int(summary_row[1]) if summary_row else 0,
                    'agents_with_openai': int(summary_row[2]) if summary_row else 0,
                    'total_tokens_used': int(usage_row[0]) if usage_row else 0,
                    'total_input_tokens': int(usage_row[1]) if usage_row else 0,
                    'total_output_tokens': int(usage_row[2]) if usage_row else 0,
                    'total_cost_usd': total_cost,
                    'total_rewrites_made': int(usage_row[3]) if usage_row else 0,
                    'avg_processing_time': float(usage_row[4]) if usage_row and usage_row[4] else 0
                }
                
                logger.info("📊 Content agents summary with tokens retrieved", 
                           summary=summary)
                return summary
                
        except Exception as e:
            logger.error("💥 Error fetching content agents summary", error=str(e))
            return {}


    # ===== ДОПОЛНИТЕЛЬНЫЙ МЕТОД ДЛЯ БЕЗОПАСНОСТИ =====
    
    async def get_total_agents_count(self, bot_id: str) -> Dict[str, int]:
        """Проверка общего количества агентов для бота (лимит 2)"""
        try:
            async with get_db_session() as session:
                # Обычный ИИ агент из user_bots
                ai_agent_query = text("""
                SELECT COUNT(*) FROM user_bots 
                WHERE bot_id = :bot_id 
                AND ai_assistant_enabled = true 
                AND openai_agent_id IS NOT NULL
                """)
                
                ai_result = await session.execute(ai_agent_query, {'bot_id': bot_id})
                ai_agents_count = int(ai_result.scalar() or 0)
                
                # Контент агент из content_agents
                content_agents_count = 1 if await self.has_content_agent(bot_id) else 0
                
                total_agents = ai_agents_count + content_agents_count
                
                logger.info("🔍 Agents count check", 
                           bot_id=bot_id,
                           ai_agents=ai_agents_count,
                           content_agents=content_agents_count,
                           total=total_agents)
                
                return {
                    'ai_agents': ai_agents_count,
                    'content_agents': content_agents_count,
                    'total': total_agents,
                    'can_create_content_agent': content_agents_count == 0,
                    'within_limit': total_agents <= 2
                }
                
        except Exception as e:
            logger.error("💥 Error checking agents count", error=str(e))
            return {
                'ai_agents': 0,
                'content_agents': 0,
                'total': 0,
                'can_create_content_agent': True,
                'within_limit': True
            }


# ===== АВТОМАТИЧЕСКАЯ ИНИЦИАЛИЗАЦИЯ ТАБЛИЦ =====

async def init_content_tables():
    """✅ Публичная функция для инициализации таблиц"""
    try:
        manager = ContentManager()
        await manager._ensure_tables_exist()
        logger.info("✅ Content tables initialized successfully")
        return True
    except Exception as e:
        logger.error("💥 Failed to initialize content tables", error=str(e))
        return False
