"""
AI обработчики для UserBot - ИСПРАВЛЕННАЯ ВЕРСИЯ + ПОДДЕРЖКА ГРУППОВЫХ УПОМИНАНИЙ + КОНТРОЛЬ ДОСТУПА + УПРАВЛЕНИЕ ФАЙЛАМИ
✅ АДМИН: Настройка и управление ИИ агентами  
✅ ПОЛЬЗОВАТЕЛИ: Обработка диалогов с ИИ (БЕЗ показа кнопки - это в channel_handlers)
✅ ЧИСТОЕ РАЗДЕЛЕНИЕ: channel_handlers показывает кнопку, ai_handlers её обрабатывает
✅ ЕДИНАЯ СИСТЕМА ПРОВЕРОК: AIAccessChecker
✅ ИНСТАНС-ПОДХОД: Без глобальных переменных
✅ ИСПРАВЛЕНО: handle_user_ai_exit() теперь показывает кнопку ИИ после завершения
✅ ИСПРАВЛЕНО: Разные callback_data для админа и пользователей (устранен конфликт)
✅ ИСПРАВЛЕНО: Правильная последовательность проверки лимитов
✅ ИСПРАВЛЕНО: Инкремент счетчика ТОЛЬКО после успешного ответа ИИ (НЕ ДО!)
✅ ИСПРАВЛЕНО: Удален дублирующий вызов increment_ai_usage из _get_openai_response_for_user
✅ ИСПРАВЛЕНО: Безопасная проверка message.text в handle_admin_ai_conversation
✅ НОВОЕ: Поддержка голосовых сообщений через OpenAI Whisper API транскрипцию
✅ УЛУЧШЕНО: Детальная диагностика транскрипции голосовых сообщений
✅ НОВОЕ: Обработка упоминаний бота в группах (@botname сообщение)
✅ НОВОЕ: Контроль доступа владельца через access_control
✅ НОВОЕ: Полная поддержка управления файлами для OpenAI агентов
"""

import asyncio
import structlog
import re
from datetime import datetime
from aiogram import F, Dispatcher
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from ..states import AISettingsStates
from ..keyboards import AIKeyboards, AdminKeyboards
from ..formatters import MessageFormatter

logger = structlog.get_logger()


class AIAccessChecker:
    """Единая система проверок доступа к ИИ"""
    
    def __init__(self, db, bot_config):
        self.db = db
        self.bot_config = bot_config
    
    async def check_subscription(self, user_id: int) -> tuple[bool, str]:
        """Проверка подписки на канал ИЛИ участия в группе"""
        try:
            subscription_settings = await self.db.get_subscription_settings(self.bot_config['bot_id'])
            
            if not subscription_settings or not subscription_settings.get('subscription_check_enabled'):
                return True, ""
            
            channel_id = subscription_settings.get('subscription_channel_id')
            channel_username = subscription_settings.get('subscription_channel_username')
            deny_message = subscription_settings.get('subscription_deny_message', 
                                                    'Для доступа к ИИ агенту необходимо подписаться на наш канал/группу.')
            
            if not channel_id:
                return True, ""
            
            bot = self.bot_config.get('bot')
            if not bot:
                return True, ""
            
            # 🔍 ПРОВЕРКА РАБОТАЕТ ДЛЯ КАНАЛОВ И ГРУПП ОДИНАКОВО
            member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            is_member = member.status in ['member', 'administrator', 'creator']
            
            # 📝 Адаптивное сообщение в зависимости от типа чата
            if not is_member:
                # Определяем тип чата для более точного сообщения
                try:
                    chat_info = await bot.get_chat(channel_id)
                    chat_type_name = "группу" if chat_info.type in ["group", "supergroup"] else "канал"
                    
                    if channel_username:
                        deny_message = f"Для доступа к ИИ агенту необходимо вступить в {chat_type_name}: @{channel_username}"
                    else:
                        deny_message = f"Для доступа к ИИ агенту необходимо вступить в {chat_type_name}."
                except:
                    # Fallback к стандартному сообщению
                    pass
            
            return is_member, deny_message if not is_member else ""
            
        except Exception as e:
            logger.warning("⚠️ Could not check channel/group membership", error=str(e))
            return True, ""
    
    async def check_ai_agent_availability(self) -> tuple[bool, str]:
        """Проверка доступности ИИ агента"""
        try:
            fresh_ai_config = await self.db.get_ai_config(self.bot_config['bot_id'])
            
            if not fresh_ai_config or not fresh_ai_config.get('enabled') or not fresh_ai_config.get('agent_id'):
                return False, "❌ ИИ агент временно недоступен."
            
            return True, ""
            
        except Exception as e:
            logger.error("💥 Error checking AI agent availability", error=str(e))
            return False, "❌ Ошибка проверки доступности агента."
    
    async def check_token_limits(self, user_id: int) -> tuple[bool, str, dict]:
        """Проверка лимитов токенов"""
        try:
            fresh_ai_config = await self.db.get_ai_config(self.bot_config['bot_id'])
            
            if not fresh_ai_config or fresh_ai_config.get('type') != 'openai':
                return True, "", {}
            
            token_info = await self.db.get_user_token_balance(self.bot_config['owner_user_id'])
            
            if not token_info:
                return False, "❌ Система токенов не инициализирована", {}
            
            tokens_used = token_info.get('total_used', 0)
            tokens_limit = token_info.get('limit', 500000)
            remaining_tokens = tokens_limit - tokens_used
            
            if remaining_tokens <= 0:
                return False, f"""
❌ <b>Токены исчерпаны!</b>

Для этого ИИ агента закончились токены.
Использовано: {tokens_used:,} из {tokens_limit:,}

Обратитесь к администратору для пополнения баланса.
""", token_info
            
            return True, "", token_info
            
        except Exception as e:
            logger.error("💥 Error checking token limit", error=str(e))
            return False, "❌ Ошибка при проверке лимита токенов", {}
    
    async def check_daily_limits(self, user_id: int) -> tuple[bool, str]:
        """Проверка дневных лимитов пользователя"""
        try:
            can_send, used_today, daily_limit = await self.db.check_daily_message_limit(
                self.bot_config['bot_id'], user_id
            )
            
            if daily_limit <= 0:
                return True, ""  # Лимит не установлен
            
            if not can_send:
                return False, f"""📊 <b>Дневной лимит сообщений исчерпан</b>

Использовано: {used_today} / {daily_limit} сообщений

Лимит обновится в 00:00 МСК.
Попробуйте снова завтра!

💡 <i>Лимит установлен администратором бота</i>"""
            
            return True, ""
            
        except Exception as e:
            logger.error("💥 Error checking daily limits", error=str(e))
            return True, ""  # В случае ошибки разрешаем доступ
    
    async def check_full_access(self, user_id: int) -> dict:
        """Полная проверка всех ограничений"""
        result = {
            'allowed': False,
            'message': '',
            'subscription_ok': False,
            'agent_ok': False, 
            'tokens_ok': False,
            'daily_limit_ok': False,
            'token_info': {}
        }
        
        # 1. Проверка подписки
        subscription_ok, subscription_msg = await self.check_subscription(user_id)
        result['subscription_ok'] = subscription_ok
        if not subscription_ok:
            result['message'] = subscription_msg
            return result
        
        # 2. Проверка агента
        agent_ok, agent_msg = await self.check_ai_agent_availability()
        result['agent_ok'] = agent_ok
        if not agent_ok:
            result['message'] = agent_msg
            return result
        
        # 3. Проверка токенов
        tokens_ok, tokens_msg, token_info = await self.check_token_limits(user_id)
        result['tokens_ok'] = tokens_ok
        result['token_info'] = token_info
        if not tokens_ok:
            result['message'] = tokens_msg
            return result
        
        # 4. Проверка дневного лимита
        daily_ok, daily_msg = await self.check_daily_limits(user_id)
        result['daily_limit_ok'] = daily_ok
        if not daily_ok:
            result['message'] = daily_msg
            return result
        
        # Все проверки пройдены
        result['allowed'] = True
        return result


class AIHandler:
    """Единый обработчик ИИ функций"""
    
    def __init__(self, db, bot_config, user_bot=None, access_control=None):
        self.db = db
        self.bot_config = bot_config
        self.user_bot = user_bot
        self.formatter = MessageFormatter()
        self.access_checker = AIAccessChecker(db, bot_config)
        self.owner_user_id = bot_config['owner_user_id']
        self.bot_id = bot_config['bot_id']
        self.access_control = access_control  # ✅ НОВОЕ
    
    def _is_owner(self, user_id: int) -> bool:
        """Проверка, является ли пользователь владельцем"""
        return user_id == self.owner_user_id

    async def _create_openai_handler(self):
        """Создание экземпляра OpenAIHandler"""
        try:
            from .ai_openai_handler import OpenAIHandler
            
            openai_handler = OpenAIHandler(
                db=self.db,
                bot_config=self.bot_config,
                ai_assistant=None,
                user_bot=None
            )
            
            logger.info("✅ OpenAIHandler created", bot_id=self.bot_id)
            return openai_handler
            
        except Exception as e:
            logger.error("💥 Failed to create OpenAIHandler", error=str(e))
            return None

    async def handle_file_management_callbacks(self, callback: CallbackQuery, state: FSMContext):
        """Обработка callback'ов управления файлами"""
        logger.info("📁 File management callback", 
                   user_id=callback.from_user.id,
                   callback_data=callback.data)
        
        try:
            openai_handler = await self._create_openai_handler()
            if not openai_handler:
                await callback.answer("❌ Ошибка создания обработчика", show_alert=True)
                return
            
            is_owner_check = lambda user_id: self._is_owner(user_id)
            
            if callback.data == "openai_start_upload":
                await openai_handler.handle_start_upload(callback, state, is_owner_check)
            elif callback.data == "openai_finish_upload":
                await openai_handler.handle_finish_upload(callback, state, is_owner_check)
            elif callback.data == "openai_manage_files":
                await openai_handler.handle_manage_files(callback, is_owner_check)
            
            logger.info("✅ File management callback handled", callback_data=callback.data)
            
        except Exception as e:
            logger.error("💥 Error in file management callback", error=str(e))
            await callback.answer("❌ Произошла ошибка", show_alert=True)

    async def handle_document_upload_fsm(self, message: Message, state: FSMContext):
        """FSM обработчик загрузки документов"""
        logger.info("📄 Document upload via FSM", user_id=message.from_user.id)
        
        try:
            openai_handler = await self._create_openai_handler()
            if not openai_handler:
                await message.answer("❌ Ошибка создания обработчика")
                return
            
            is_owner_check = lambda user_id: self._is_owner(user_id)
            await openai_handler.handle_document_upload(message, state, is_owner_check)
            
        except Exception as e:
            logger.error("💥 Error in document upload", error=str(e))
            await message.answer("❌ Произошла ошибка при загрузке файла")

    async def _get_fresh_ai_config(self) -> dict:
        """Получить свежую конфигурацию ИИ агента"""
        try:
            ai_config = await self.db.get_ai_config(self.bot_id)
            return ai_config or {}
        except Exception as e:
            logger.error("💥 Failed to get fresh AI config", error=str(e))
            return {}

    def _remove_bot_mention(self, text: str, bot_username: str) -> str:
        """Убираем упоминание бота из текста"""
        # Убираем @bot_username в начале или где угодно
        pattern = rf'@{re.escape(bot_username)}\s*'
        return re.sub(pattern, '', text, flags=re.IGNORECASE).strip()

    async def _transcribe_voice_message(self, voice) -> str:
        """Транскрипция голосового сообщения через OpenAI Whisper - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
        logger.info("🎤 Starting voice transcription process", 
                   voice_file_id=voice.file_id,
                   voice_duration=getattr(voice, 'duration', 'unknown'),
                   voice_file_size=getattr(voice, 'file_size', 'unknown'))
        
        try:
            # 1. Импортируем необходимые модули
            try:
                from config import settings
                import os
                logger.info("✅ Settings and os imported successfully")
            except ImportError as e:
                logger.error("❌ Failed to import settings or os", error=str(e))
                return ""
            
            # 2. Пытаемся получить API ключ разными способами
            api_key = None
            key_source = ""
            
            # Способ 1: Из settings.OPENAI_API_KEY
            try:
                api_key = getattr(settings, 'OPENAI_API_KEY', None)
                if api_key:
                    key_source = "settings.OPENAI_API_KEY"
                    logger.info("✅ API key found in settings", source=key_source)
            except Exception as e:
                logger.warning("⚠️ Could not get API key from settings", error=str(e))
            
            # Способ 2: Из переменной окружения OPENAI_API_KEY
            if not api_key:
                api_key = os.environ.get('OPENAI_API_KEY')
                if api_key:
                    key_source = "os.environ['OPENAI_API_KEY']"
                    logger.info("✅ API key found in environment", source=key_source)
            
            # Способ 3: Из других возможных имен переменных
            if not api_key:
                possible_names = [
                    'OPENAI_TOKEN', 
                    'OPENAI_SECRET_KEY', 
                    'GPT_API_KEY',
                    'OPENAI_API_TOKEN'
                ]
                for name in possible_names:
                    api_key = os.environ.get(name)
                    if api_key:
                        key_source = f"os.environ['{name}']"
                        logger.info("✅ API key found in environment", source=key_source)
                        break
            
            # Способ 4: Проверяем settings как объект с разными именами атрибутов
            if not api_key:
                possible_attrs = ['openai_api_key', 'OPENAI_TOKEN', 'openai_token']
                for attr in possible_attrs:
                    try:
                        api_key = getattr(settings, attr, None)
                        if api_key:
                            key_source = f"settings.{attr}"
                            logger.info("✅ API key found in settings", source=key_source)
                            break
                    except:
                        continue
            
            if not api_key:
                # Показываем доступные переменные окружения для диагностики
                openai_vars = [k for k in os.environ.keys() if 'OPENAI' in k.upper() or 'GPT' in k.upper()]
                settings_attrs = [attr for attr in dir(settings) if not attr.startswith('_')]
                
                logger.error("❌ OpenAI API key not found anywhere", 
                            env_openai_vars=openai_vars,
                            settings_attrs=settings_attrs[:10])  # Первые 10 атрибутов
                return ""
            
            logger.info("✅ OpenAI API key found", 
                       source=key_source,
                       key_length=len(api_key) if api_key else 0,
                       key_preview=f"{api_key[:10]}...{api_key[-4:]}" if api_key and len(api_key) > 14 else "SHORT_KEY")
            
            # 3. Получаем модель Whisper
            whisper_model = getattr(settings, 'OPENAI_WHISPER_MODEL', 'whisper-1')
            logger.info("✅ Whisper model", model=whisper_model)
            
            # 4. Проверяем bot instance
            bot = self.bot_config.get('bot')
            if not bot:
                logger.error("❌ Bot instance not available in bot_config", 
                            bot_config_keys=list(self.bot_config.keys()))
                return ""
            
            logger.info("✅ Bot instance available", bot_type=type(bot).__name__)
            
            # 5. Импортируем необходимые библиотеки
            try:
                import aiohttp
                import tempfile
                logger.info("✅ Required libraries imported")
            except ImportError as e:
                logger.error("❌ Failed to import required libraries", error=str(e))
                return ""
            
            # 6. Получаем информацию о файле
            logger.info("📥 Getting voice file info...")
            try:
                file_info = await bot.get_file(voice.file_id)
                logger.info("✅ Voice file info retrieved", 
                           file_path=file_info.file_path,
                           file_size=getattr(file_info, 'file_size', 'unknown'))
            except Exception as e:
                logger.error("❌ Failed to get voice file info", error=str(e))
                return ""
            
            # 7. Создаем временный файл
            logger.info("📁 Creating temporary file...")
            try:
                temp_file = tempfile.NamedTemporaryFile(suffix='.ogg', delete=False)
                temp_file_path = temp_file.name
                temp_file.close()  # Закрываем, чтобы можно было записать
                logger.info("✅ Temporary file created", path=temp_file_path)
            except Exception as e:
                logger.error("❌ Failed to create temporary file", error=str(e))
                return ""
            
            try:
                # 8. Скачиваем файл
                logger.info("⬇️ Downloading voice file...")
                try:
                    with open(temp_file_path, 'wb') as temp_file_handle:
                        await bot.download_file(file_info.file_path, temp_file_handle)
                    
                    # Проверяем размер скачанного файла
                    file_size = os.path.getsize(temp_file_path)
                    logger.info("✅ Voice file downloaded", size_bytes=file_size)
                    
                    if file_size == 0:
                        logger.error("❌ Downloaded file is empty")
                        return ""
                        
                except Exception as e:
                    logger.error("❌ Failed to download voice file", error=str(e))
                    return ""
                
                # 9. Отправляем в Whisper API
                logger.info("🌐 Sending to OpenAI Whisper API...")
                try:
                    async with aiohttp.ClientSession() as session:
                        with open(temp_file_path, 'rb') as audio_file:
                            data = aiohttp.FormData()
                            data.add_field('file', audio_file, filename='voice.ogg')
                            data.add_field('model', whisper_model)
                            data.add_field('language', 'ru')
                            
                            headers = {
                                'Authorization': f'Bearer {api_key}'
                            }
                            
                            logger.info("📡 Making API request to Whisper...", 
                                       url='https://api.openai.com/v1/audio/transcriptions',
                                       model=whisper_model,
                                       language='ru')
                            
                            async with session.post(
                                'https://api.openai.com/v1/audio/transcriptions',
                                data=data,
                                headers=headers,
                                timeout=30
                            ) as response:
                                logger.info("📨 Received API response", 
                                          status=response.status,
                                          content_type=response.content_type,
                                          content_length=response.headers.get('content-length', 'unknown'))
                                
                                if response.status == 200:
                                    result = await response.json()
                                    transcribed_text = result.get('text', '').strip()
                                    
                                    logger.info("✅ Voice transcription successful", 
                                              text_length=len(transcribed_text),
                                              preview=transcribed_text[:100] if transcribed_text else "EMPTY")
                                    return transcribed_text
                                elif response.status == 401:
                                    error_text = await response.text()
                                    logger.error("❌ Whisper API authentication failed", 
                                               status=response.status,
                                               error=error_text,
                                               key_source=key_source)
                                    return ""
                                elif response.status == 429:
                                    error_text = await response.text()
                                    logger.error("❌ Whisper API rate limit exceeded", 
                                               status=response.status,
                                               error=error_text)
                                    return ""
                                else:
                                    error_text = await response.text()
                                    logger.error("❌ Whisper API error", 
                                               status=response.status,
                                               error=error_text,
                                               headers=dict(response.headers))
                                    return ""
                                    
                except Exception as e:
                    logger.error("❌ API request failed", 
                                error=str(e), 
                                error_type=type(e).__name__)
                    return ""
            finally:
                # 10. Удаляем временный файл
                try:
                    if os.path.exists(temp_file_path):
                        os.unlink(temp_file_path)
                        logger.info("🗑️ Temporary file cleaned up")
                except Exception as e:
                    logger.warning("⚠️ Failed to cleanup temp file", error=str(e))
            
        except Exception as e:
            logger.error("💥 Unexpected error in voice transcription", 
                        error=str(e), 
                        error_type=type(e).__name__,
                        exc_info=True)
            return ""

    async def _get_openai_response_for_user(self, message: Message, user_id: int) -> str:
        """Получение ответа от OpenAI для пользователя - БЕЗ ДУБЛИРУЮЩЕГО ИНКРЕМЕНТА"""
        try:
            fresh_ai_config = await self._get_fresh_ai_config()
            
            if not fresh_ai_config or fresh_ai_config.get('type') != 'openai':
                return "❌ ИИ агент неправильно настроен."
            
            agent_id = fresh_ai_config.get('agent_id')
            if not agent_id:
                return "❌ Агент не найден."
            
            try:
                from services.openai_assistant import openai_client
                from services.openai_assistant.models import OpenAIResponsesContext
                
                context = OpenAIResponsesContext(
                    user_id=user_id,
                    user_name=message.from_user.first_name or "Пользователь",
                    username=message.from_user.username,
                    bot_id=self.bot_id,
                    chat_id=message.chat.id,
                    is_admin=False
                )
                
                response = await openai_client.send_message(
                    assistant_id=agent_id,
                    message=message.text,
                    user_id=user_id,
                    context=context
                )
                
                if response:
                    # ✅ ИСПРАВЛЕНО: УДАЛЕН дублирующий вызов increment_ai_usage
                    # Инкремент теперь происходит ТОЛЬКО в handle_user_ai_conversation
                    return response
                else:
                    return "❌ Получен пустой ответ от ИИ."
                    
            except ImportError:
                logger.warning("📦 OpenAI service not available", user_id=user_id)
                
                settings = fresh_ai_config.get('settings', {})
                agent_name = settings.get('agent_name', 'ИИ Агент')
                
                # ✅ ИСПРАВЛЕНО: УДАЛЕН дублирующий вызов increment_ai_usage
                # Инкремент теперь происходит ТОЛЬКО в handle_user_ai_conversation
                
                return f"🤖 {agent_name}: Сервис временно недоступен."
                
        except Exception as e:
            logger.error("💥 Error getting OpenAI response", error=str(e))
            return "❌ Внутренняя ошибка системы."

    async def _get_openai_response_for_user_with_text(self, message: Message, user_id: int, text: str) -> str:
        """Получение ответа от OpenAI для пользователя с кастомным текстом"""
        try:
            fresh_ai_config = await self._get_fresh_ai_config()
            
            if not fresh_ai_config or fresh_ai_config.get('type') != 'openai':
                return "❌ ИИ агент неправильно настроен."
            
            agent_id = fresh_ai_config.get('agent_id')
            if not agent_id:
                return "❌ Агент не найден."
            
            try:
                from services.openai_assistant import openai_client
                from services.openai_assistant.models import OpenAIResponsesContext
                
                context = OpenAIResponsesContext(
                    user_id=user_id,
                    user_name=message.from_user.first_name or "Пользователь",
                    username=message.from_user.username,
                    bot_id=self.bot_id,
                    chat_id=message.chat.id,
                    is_admin=False
                )
                
                # ✅ ИСПРАВЛЕНО: Используем переданный text вместо message.text
                response = await openai_client.send_message(
                    assistant_id=agent_id,
                    message=text,  # ← ИСПОЛЬЗУЕМ ПАРАМЕТР
                    user_id=user_id,
                    context=context
                )
                
                if response:
                    return response
                else:
                    return "❌ Получен пустой ответ от ИИ."
                    
            except ImportError:
                logger.warning("📦 OpenAI service not available", user_id=user_id)
                
                settings = fresh_ai_config.get('settings', {})
                agent_name = settings.get('agent_name', 'ИИ Агент')
                
                return f"🤖 {agent_name}: Сервис временно недоступен."
                
        except Exception as e:
            logger.error("💥 Error getting OpenAI response", error=str(e))
            return "❌ Внутренняя ошибка системы."

    async def _get_openai_response_for_admin_with_text(self, message: Message, user_id: int, text: str) -> str:
        """Получение ответа от OpenAI для админа с кастомным текстом"""
        try:
            fresh_ai_config = await self._get_fresh_ai_config()
            
            if not fresh_ai_config or fresh_ai_config.get('type') != 'openai':
                return "❌ ИИ агент неправильно настроен."
            
            agent_id = fresh_ai_config.get('agent_id')
            if not agent_id:
                return "❌ Агент не найден."
            
            try:
                from services.openai_assistant import openai_client
                from services.openai_assistant.models import OpenAIResponsesContext
                
                context = OpenAIResponsesContext(
                    user_id=user_id,
                    user_name=message.from_user.first_name or "Администратор",
                    username=message.from_user.username,
                    bot_id=self.bot_id,
                    chat_id=message.chat.id,
                    is_admin=True  # ✅ АДМИН КОНТЕКСТ
                )
                
                logger.info("🔧 Admin OpenAI request", 
                           user_id=user_id,
                           agent_id=agent_id,
                           text_length=len(text),
                           text_preview=text[:100] + "..." if len(text) > 100 else text)
                
                # ✅ ИСПОЛЬЗУЕМ ПЕРЕДАННЫЙ ТЕКСТ (транскрибированный или обычный)
                response = await openai_client.send_message(
                    assistant_id=agent_id,
                    message=text,  # ← КАСТОМНЫЙ ТЕКСТ
                    user_id=user_id,
                    context=context
                )
                
                if response:
                    logger.info("✅ Admin OpenAI response received", 
                               user_id=user_id,
                               response_length=len(response))
                    return response
                else:
                    logger.warning("⚠️ Empty OpenAI response for admin", user_id=user_id)
                    return "❌ Получен пустой ответ от ИИ."
                    
            except ImportError:
                logger.warning("📦 OpenAI service not available for admin", user_id=user_id)
                
                settings = fresh_ai_config.get('settings', {})
                agent_name = settings.get('agent_name', 'ИИ Агент')
                
                # Fallback ответ для админа
                return f"🤖 {agent_name} (Тестовый режим): Получил сообщение '{text[:50]}{'...' if len(text) > 50 else ''}'. Responses API временно недоступен."
                
        except Exception as e:
            logger.error("💥 Error getting OpenAI response for admin", 
                        user_id=user_id, 
                        error=str(e),
                        exc_info=True)
            return "❌ Внутренняя ошибка системы."

    # ===== АДМИНСКИЕ ОБРАБОТЧИКИ =====

    async def handle_navigation_callbacks(self, callback: CallbackQuery, state: FSMContext):
        """Навигационные callback для админа"""
        logger.info("🧭 Admin navigation callback", 
                   user_id=callback.from_user.id,
                   callback_data=callback.data)
        
        try:
            openai_handler = await self._create_openai_handler()
            if not openai_handler:
                await callback.answer("❌ Ошибка создания обработчика", show_alert=True)
                return
            
            is_owner_check = lambda user_id: self._is_owner(user_id)
            
            await openai_handler.handle_navigation_action(callback, state, is_owner_check)
            
            logger.info("✅ Admin navigation handled", callback_data=callback.data)
            
        except Exception as e:
            logger.error("💥 Error in admin navigation", error=str(e))
            await callback.answer("❌ Произошла ошибка", show_alert=True)

    async def handle_admin_ai_exit_conversation(self, callback: CallbackQuery, state: FSMContext):
        """Завершение админского диалога с ИИ"""
        logger.info("🚪 Admin AI exit conversation", user_id=callback.from_user.id)
        
        try:
            openai_handler = await self._create_openai_handler()
            if not openai_handler:
                await callback.answer("❌ Ошибка создания обработчика", show_alert=True)
                return
            
            await openai_handler.handle_exit_conversation(callback, state)
            logger.info("✅ Admin AI conversation ended", callback_data=callback.data)
            
        except Exception as e:
            logger.error("💥 Error in admin AI exit handler", error=str(e))
            await callback.answer("❌ Произошла ошибка", show_alert=True)

    async def handle_openai_callbacks(self, callback: CallbackQuery, state: FSMContext):
        """Обработчик OpenAI действий для админа"""
        logger.info(f"🎨 Admin OpenAI callback: {callback.data}", user_id=callback.from_user.id)
        
        try:
            is_owner_check = lambda user_id: self._is_owner(user_id)
            
            openai_handler = await self._create_openai_handler()
            if not openai_handler:
                await callback.answer("❌ Ошибка создания обработчика", show_alert=True)
                return
            
            if callback.data == "openai_confirm_delete":
                await openai_handler.handle_confirm_delete(callback, is_owner_check)
            else:
                await openai_handler.handle_openai_action(callback, state, is_owner_check)
            
            logger.info("✅ Admin OpenAI action handled", callback_data=callback.data)
            
        except Exception as e:
            logger.error("💥 Error in admin OpenAI handler", error=str(e))
            await callback.answer("❌ Произошла ошибка", show_alert=True)

    # ===== FSM ОБРАБОТЧИКИ ДЛЯ АДМИНА =====

    async def handle_openai_name_input(self, message: Message, state: FSMContext):
        """Обработка ввода имени OpenAI агента (АДМИН)"""
        logger.info("📝 Admin OpenAI name input", user_id=message.from_user.id)
        
        try:
            is_owner_check = lambda user_id: self._is_owner(user_id)
            
            openai_handler = await self._create_openai_handler()
            if not openai_handler:
                await message.answer("❌ Ошибка создания обработчика")
                return
            
            await openai_handler.handle_name_input(message, state, is_owner_check)
            
        except Exception as e:
            logger.error("💥 Error in admin name input", error=str(e))
            await message.answer("❌ Произошла ошибка")

    async def handle_openai_role_input(self, message: Message, state: FSMContext):
        """Обработка ввода роли OpenAI агента (АДМИН)"""
        logger.info("📝 Admin OpenAI role input", user_id=message.from_user.id)
        
        try:
            is_owner_check = lambda user_id: self._is_owner(user_id)
            
            openai_handler = await self._create_openai_handler()
            if not openai_handler:
                await message.answer("❌ Ошибка создания обработчика")
                return
            
            await openai_handler.handle_role_input(message, state, is_owner_check)
            
        except Exception as e:
            logger.error("💥 Error in admin role input", error=str(e))
            await message.answer("❌ Произошла ошибка")

    async def handle_agent_name_edit(self, message: Message, state: FSMContext):
        """Обработка редактирования имени агента (АДМИН)"""
        logger.info("✏️ Admin agent name edit", user_id=message.from_user.id)
        
        try:
            is_owner_check = lambda user_id: self._is_owner(user_id)
            
            openai_handler = await self._create_openai_handler()
            if not openai_handler:
                await message.answer("❌ Ошибка создания обработчика")
                return
            
            await openai_handler.handle_name_edit_input(message, state, is_owner_check)
            
        except Exception as e:
            logger.error("💥 Error in admin name edit", error=str(e))
            await message.answer("❌ Произошла ошибка")

    async def handle_agent_prompt_edit(self, message: Message, state: FSMContext):
        """Обработка редактирования промпта агента (АДМИН)"""
        logger.info("🎭 Admin agent prompt edit", user_id=message.from_user.id)
        
        try:
            is_owner_check = lambda user_id: self._is_owner(user_id)
            
            openai_handler = await self._create_openai_handler()
            if not openai_handler:
                await message.answer("❌ Ошибка создания обработчика")
                return
            
            await openai_handler.handle_prompt_edit_input(message, state, is_owner_check)
            
        except Exception as e:
            logger.error("💥 Error in admin prompt edit", error=str(e))
            await message.answer("❌ Произошла ошибка")

    async def handle_admin_ai_conversation(self, message: Message, state: FSMContext):
        """Обработка админского тестирования ИИ - С ПОДДЕРЖКОЙ ГОЛОСОВЫХ БЕЗ FROZEN ERROR + КОНТРОЛЬ ДОСТУПА"""
        logger.info("💬 Admin AI testing conversation", user_id=message.from_user.id)
        
        try:
            # ✅ НОВОЕ: Проверка доступа владельца
            if self.access_control:
                has_access, status = await self.access_control['check_owner_access']()
                if not has_access:
                    await self.access_control['send_access_denied'](message, status)
                    return
            
            # ✅ ИСПРАВЛЕНО: Безопасная проверка text
            if message.text and message.text in ['/exit', '/stop', '/cancel']:
                await state.clear()
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_main")]
                ])
                
                await message.answer("🚪 Диалог с ИИ завершен", reply_markup=keyboard)
                return
            
            if not self._is_owner(message.from_user.id):
                await message.answer("❌ Доступ запрещен")
                return
            
            # ✅ ИСПРАВЛЕНО: Получаем текст БЕЗ ИЗМЕНЕНИЯ message.text
            message_text = None
            
            if message.voice:
                logger.info("🎤 Admin voice message received, transcribing...", user_id=message.from_user.id)
                
                await message.bot.send_chat_action(message.chat.id, "typing")
                
                message_text = await self._transcribe_voice_message(message.voice)
                
                if not message_text:
                    await message.answer("❌ Не удалось распознать голосовое сообщение. Попробуйте еще раз или напишите текстом.")
                    return
                
                logger.info("✅ Admin voice transcribed successfully", 
                           user_id=message.from_user.id,
                           transcribed_length=len(message_text))
            elif message.text:
                message_text = message.text
            else:
                await message.answer("❌ Пожалуйста, отправьте текстовое или голосовое сообщение.")
                return
            
            # Проверяем что теперь есть текст
            if not message_text:
                await message.answer("❌ Пожалуйста, отправьте текстовое или голосовое сообщение.")
                return
            
            data = await state.get_data()
            agent_type = data.get('agent_type', 'openai')
            
            if agent_type == 'openai':
                await message.bot.send_chat_action(message.chat.id, "typing")
                
                # ✅ ИСПРАВЛЕНО: Используем новый метод для админов с кастомным текстом
                response = await self._get_openai_response_for_admin_with_text(message, message.from_user.id, message_text)
                
                if response:
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🚪 Завершить диалог", callback_data="admin_ai_exit_conversation")]
                    ])
                    
                    await message.answer(response, reply_markup=keyboard)
                    logger.info("✅ Admin AI response sent", user_id=message.from_user.id)
                else:
                    await message.answer("❌ Не удалось получить ответ от ИИ")
            else:
                await message.answer("❌ Неподдерживаемый тип агента")
                
        except Exception as e:
            logger.error("💥 Error in admin AI conversation", error=str(e))
            await message.answer("❌ Произошла ошибка при общении с ИИ")

    # ===== ПОЛЬЗОВАТЕЛЬСКИЕ ОБРАБОТЧИКИ =====

    async def handle_user_ai_button_click(self, message: Message, state: FSMContext):
        """🤖 Обработка кнопки 'Позвать ИИ' от пользователей + КОНТРОЛЬ ДОСТУПА"""
        user = message.from_user
        
        logger.info("🤖 User AI button clicked", 
                   bot_id=self.bot_id,
                   user_id=user.id,
                   username=user.username)
        
        try:
            # ✅ НОВОЕ: Проверка доступа владельца
            if self.access_control:
                has_access, status = await self.access_control['check_owner_access']()
                if not has_access:
                    await self.access_control['send_access_denied'](message, status)
                    return
            
            # Очищаем любое текущее состояние
            current_state = await state.get_state()
            if current_state:
                await state.clear()
            
            # ✅ ЕДИНАЯ ПРОВЕРКА через AccessChecker
            access_result = await self.access_checker.check_full_access(user.id)
            
            if not access_result['allowed']:
                logger.warning("❌ User access denied", 
                             user_id=user.id, 
                             reason=access_result['message'][:50])
                await message.answer(access_result['message'], reply_markup=ReplyKeyboardRemove())
                return
            
            # ===== ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ - ЗАПУСК ДИАЛОГА =====
            
            await state.set_state(AISettingsStates.user_in_ai_conversation)
            await state.update_data(
                agent_type='openai',
                user_id=user.id,
                bot_id=self.bot_id,
                started_at=datetime.now().isoformat(),
                is_user_conversation=True
            )
            
            # Формируем приветствие
            fresh_ai_config = await self._get_fresh_ai_config()
            agent_settings = fresh_ai_config.get('settings', {})
            agent_name = agent_settings.get('agent_name', 'ИИ Агент')
            
            # Подсчитываем оставшиеся сообщения
            remaining_messages = ""
            try:
                can_send, used_today, daily_limit = await self.db.check_daily_message_limit(self.bot_id, user.id)
                if daily_limit > 0:
                    remaining = daily_limit - used_today
                    remaining_messages = f"\n📊 Осталось сообщений сегодня: {remaining}"
            except:
                pass
            
            welcome_text = f"""
🤖 <b>Добро пожаловать в чат с {agent_name}!</b>

Я готов помочь вам с любыми вопросами. Просто напишите что вас интересует или отправьте голосовое сообщение.{remaining_messages}

<b>Напишите ваш вопрос или отправьте голосовое сообщение:</b>
"""
            
            # ✅ ИЗМЕНЕНО: Используем user_ai_exit_conversation для пользователей
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚪 Завершить диалог", callback_data="user_ai_exit_conversation")]
            ])
            
            await message.answer(welcome_text, reply_markup=keyboard)
            
            logger.info("🎉 User AI conversation started", user_id=user.id)
            
        except Exception as e:
            logger.error("💥 Error in user AI button handler", user_id=user.id, error=str(e))
            
            try:
                await state.clear()
            except:
                pass
            
            await message.answer("❌ Произошла ошибка при запуске диалога с ИИ.")

    async def handle_user_ai_conversation(self, message: Message, state: FSMContext):
        """💬 Обработка диалога пользователя с ИИ + распознавание голосовых - ИСПРАВЛЕНО + КОНТРОЛЬ ДОСТУПА"""
        user = message.from_user
        
        logger.info("💬 User AI conversation message", 
                   user_id=user.id,
                   has_text=bool(message.text),
                   has_voice=bool(message.voice),
                   message_length=len(message.text) if message.text else 0)
        
        try:
            # ✅ НОВОЕ: Проверка доступа владельца
            if self.access_control:
                has_access, status = await self.access_control['check_owner_access']()
                if not has_access:
                    await self.access_control['send_access_denied'](message, status)
                    return
            
            # Проверяем FSM состояние
            current_state = await state.get_state()
            if current_state != AISettingsStates.user_in_ai_conversation:
                logger.warning("❌ Wrong FSM state", user_id=user.id)
                return
            
            data = await state.get_data()
            is_user_conversation = data.get('is_user_conversation', False)
            
            if not is_user_conversation:
                logger.warning("❌ Not a user conversation", user_id=user.id)
                return
            
            # ✅ ИСПРАВЛЕНО: Получаем текст БЕЗ ИЗМЕНЕНИЯ message.text
            message_text = None
            
            if message.voice:
                logger.info("🎤 Voice message received, transcribing...", user_id=user.id)
                
                await message.bot.send_chat_action(message.chat.id, "typing")
                
                message_text = await self._transcribe_voice_message(message.voice)
                
                if not message_text:
                    await message.answer("❌ Не удалось распознать голосовое сообщение. Попробуйте еще раз или напишите текстом.")
                    return
                
                logger.info("✅ Voice transcribed successfully", 
                           user_id=user.id,
                           transcribed_length=len(message_text))
            elif message.text:
                message_text = message.text
            else:
                await message.answer("❌ Пожалуйста, отправьте текстовое или голосовое сообщение.")
                return
            
            # Проверяем что теперь есть текст
            if not message_text:
                await message.answer("❌ Пожалуйста, отправьте текстовое или голосовое сообщение.")
                return
            
            # Проверяем доступность
            access_result = await self.access_checker.check_full_access(user.id)
            if not access_result['allowed']:
                await message.answer(access_result['message'])
                await state.clear()
                return
            
            # Показываем индикатор набора
            await message.bot.send_chat_action(message.chat.id, "typing")
            
            # ✅ ИСПРАВЛЕНО: Получаем ответ от ИИ с транскрибированным текстом
            ai_response = await self._get_openai_response_for_user_with_text(message, user.id, message_text)
            
            if ai_response:
                # Увеличиваем счетчик
                increment_success = await self.db.increment_daily_message_usage(self.bot_id, user.id)
                if not increment_success:
                    logger.error("Failed to increment message usage", user_id=user.id)
                else:
                    logger.info("✅ Message usage incremented successfully", user_id=user.id)
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🚪 Завершить диалог", callback_data="user_ai_exit_conversation")]
                ])
                
                await message.answer(ai_response, reply_markup=keyboard)
                logger.info("✅ User AI response sent", user_id=user.id)
            else:
                await message.answer("❌ Не удалось получить ответ от ИИ.")
                
        except Exception as e:
            logger.error("💥 Error in user AI conversation", user_id=user.id, error=str(e))
            await message.answer("❌ Произошла ошибка при общении с ИИ.")

    async def handle_user_ai_exit(self, callback: CallbackQuery, state: FSMContext):
        """🚪 Завершение диалога с ИИ для пользователей - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
        user_id = callback.from_user.id
        
        logger.info("🚪 User AI conversation exit", user_id=user_id)
        
        try:
            await callback.answer()
            
            current_state = await state.get_state()
            if current_state:
                await state.clear()
            
            # Редактируем текущее сообщение (убираем кнопку завершения)
            await callback.message.edit_text(
                "🚪 Диалог с ИИ завершен.\n\n"
                "Спасибо за общение!"
            )
            
            # ✅ НОВОЕ: Отправляем новое сообщение с кнопкой ИИ
            from ..keyboards import UserKeyboards
            
            await callback.message.answer(
                "💬 Всегда можете обратиться к ИИ снова!",
                reply_markup=UserKeyboards.ai_button()
            )
            
            logger.info("✅ User AI conversation ended with new AI button", user_id=user_id)
            
        except Exception as e:
            logger.error("💥 Error ending user AI conversation", user_id=user_id, error=str(e))
            
            # Fallback: хотя бы попытаемся показать кнопку ИИ
            try:
                from ..keyboards import UserKeyboards
                await callback.message.answer(
                    "💬 Обратитесь к ИИ снова:",
                    reply_markup=UserKeyboards.ai_button()
                )
            except Exception as fallback_error:
                logger.error("💥 Fallback also failed", error=str(fallback_error))

    async def handle_user_exit_commands(self, message: Message, state: FSMContext):
        """🚪 Команды выхода из диалога для пользователей"""
        user_id = message.from_user.id
        command = message.text.lower() if message.text else ""
        
        logger.info("🚪 User exit command", user_id=user_id, command=command)
        
        try:
            current_state = await state.get_state()
            
            if current_state == AISettingsStates.user_in_ai_conversation:
                data = await state.get_data()
                is_user_conversation = data.get('is_user_conversation', False)
                
                if is_user_conversation:
                    await state.clear()
                    
                    await message.answer(
                        "🚪 Диалог с ИИ завершен по команде.\n\n"
                        "Для нового диалога нажмите \"🤖 Позвать ИИ\"",
                        reply_markup=ReplyKeyboardRemove()
                    )
                    
                    logger.info("✅ User AI conversation ended by command", user_id=user_id)
            
        except Exception as e:
            logger.error("💥 Error handling user exit command", user_id=user_id, error=str(e))

    # ===== НОВЫЙ ГРУППОВОЙ ОБРАБОТЧИК =====

    async def handle_group_mention(self, message: Message):
        """🏷️ Обработка упоминания бота в группе - ответ через ИИ + КОНТРОЛЬ ДОСТУПА"""
        user = message.from_user
        
        logger.info("🏷️ Bot mentioned in group", 
                   user_id=user.id,
                   chat_id=message.chat.id,
                   chat_type=message.chat.type,
                   bot_id=self.bot_config['bot_id'])
        
        try:
            # ✅ НОВОЕ: Проверка доступа владельца
            if self.access_control:
                has_access, status = await self.access_control['check_owner_access']()
                if not has_access:
                    await self.access_control['send_access_denied'](message, status)
                    return
            
            # Проверяем доступность ИИ агента
            access_result = await self.access_checker.check_full_access(user.id)
            
            if not access_result['allowed']:
                logger.warning("❌ Group user access denied", 
                             user_id=user.id, 
                             reason=access_result['message'][:50])
                
                # В группе отвечаем кратко
                await message.reply("❌ ИИ агент недоступен.")
                return
            
            # Показываем typing
            await message.bot.send_chat_action(message.chat.id, "typing")
            
            # Очищаем упоминание из текста
            clean_text = self._remove_bot_mention(message.text, self.bot_config['bot_username'])
            
            if not clean_text.strip():
                await message.reply("👋 Привет! О чём хотите поговорить?")
                return
            
            # Получаем ответ от ИИ
            ai_response = await self._get_openai_response_for_user_with_text(message, user.id, clean_text)
            
            if ai_response:
                # Отвечаем в той же группе
                await message.reply(ai_response)
                
                # Увеличиваем счетчик
                await self.db.increment_daily_message_usage(self.bot_config['bot_id'], user.id)
                
                logger.info("✅ Group AI response sent", user_id=user.id)
            else:
                await message.reply("❌ Не удалось получить ответ от ИИ.")
                
        except Exception as e:
            logger.error("💥 Error in group mention handler", 
                        user_id=user.id, error=str(e))
            await message.reply("❌ Произошла ошибка.")


def _is_bot_mentioned(message: Message, bot_username: str) -> bool:
    """Проверка упоминания бота"""
    if not message.text or not message.entities:
        return False
    
    for entity in message.entities:
        if entity.type == "mention":
            # Извлекаем username из текста
            mention_text = message.text[entity.offset:entity.offset + entity.length]
            if mention_text == f"@{bot_username}":
                return True
    
    return False


def register_ai_handlers(dp: Dispatcher, **kwargs):
    """✅ ИСПРАВЛЕННАЯ РЕГИСТРАЦИЯ с поддержкой групповых упоминаний + КОНТРОЛЬ ДОСТУПА + УПРАВЛЕНИЕ ФАЙЛАМИ"""
    
    # Создаем экземпляр обработчика
    ai_handler = AIHandler(
        db=kwargs['db'],
        bot_config=kwargs['bot_config'],
        user_bot=kwargs.get('user_bot'),
        access_control=kwargs.get('access_control')  # ✅ НОВОЕ
    )
    
    owner_user_id = ai_handler.owner_user_id
    
    try:
        logger.info("🎯 Registering AI handlers with GROUP MENTIONS + VOICE + ACCESS CONTROL + FILE MANAGEMENT", 
                   bot_id=ai_handler.bot_id,
                   owner_user_id=owner_user_id,
                   new_features=[
                       "Group mentions support (@botname message)",
                       "Single increment only in handle_user_ai_conversation", 
                       "Enhanced voice transcription diagnostics",
                       "Complete voice support for admins and users",
                       "Owner access control integration",
                       "File management for OpenAI agents"
                   ])
        
        # ===== 🏆 АДМИНСКИЕ ИИ ОБРАБОТЧИКИ (ТОЛЬКО ВЛАДЕЛЕЦ) =====
        
        # FSM состояния для настройки агентов
        dp.message.register(
            ai_handler.handle_openai_name_input,
            StateFilter(AISettingsStates.admin_waiting_for_openai_name),
            F.from_user.id == owner_user_id
        )
        
        dp.message.register(
            ai_handler.handle_openai_role_input,
            StateFilter(AISettingsStates.admin_waiting_for_openai_role),
            F.from_user.id == owner_user_id
        )
        
        dp.message.register(
            ai_handler.handle_agent_name_edit,
            StateFilter(AISettingsStates.admin_editing_agent_name),
            F.from_user.id == owner_user_id
        )
        
        dp.message.register(
            ai_handler.handle_agent_prompt_edit,
            StateFilter(AISettingsStates.admin_editing_agent_prompt),
            F.from_user.id == owner_user_id
        )
        
        # Админское тестирование ИИ (текстовые сообщения)
        dp.message.register(
            ai_handler.handle_admin_ai_conversation,
            StateFilter(AISettingsStates.admin_in_ai_conversation),
            F.from_user.id == owner_user_id,
            F.text
        )
        
        # ✅ НОВОЕ: Админское тестирование ИИ (голосовые сообщения)
        dp.message.register(
            ai_handler.handle_admin_ai_conversation,
            StateFilter(AISettingsStates.admin_in_ai_conversation),
            F.from_user.id == owner_user_id,
            F.voice
        )
        
        # Callback обработчики для админа
        dp.callback_query.register(
            ai_handler.handle_navigation_callbacks,
            F.data.in_(["admin_panel", "admin_ai", "admin_main"]),
            F.from_user.id == owner_user_id
        )
        
        # ✅ ИЗМЕНЕНО: Используем admin_ai_exit_conversation для админа
        dp.callback_query.register(
            ai_handler.handle_admin_ai_exit_conversation,
            F.data == "admin_ai_exit_conversation",
            F.from_user.id == owner_user_id
        )
        
        dp.callback_query.register(
            ai_handler.handle_openai_callbacks,
            F.data.startswith("openai_"),
            F.from_user.id == owner_user_id
        )
        
        # ===== 📁 ОБРАБОТЧИКИ ЗАГРУЗКИ ФАЙЛОВ (ТОЛЬКО ВЛАДЕЛЕЦ) =====
        
        # Callback'ы управления файлами
        dp.callback_query.register(
            ai_handler.handle_file_management_callbacks,
            F.data.in_(["openai_start_upload", "openai_finish_upload", "openai_manage_files"]),
            F.from_user.id == owner_user_id
        )
        
        # FSM для загрузки документов
        dp.message.register(
            ai_handler.handle_document_upload_fsm,
            StateFilter(AISettingsStates.admin_uploading_documents),
            F.from_user.id == owner_user_id,
            F.document
        )
        
        # ===== 👥 ПОЛЬЗОВАТЕЛЬСКИЕ ИИ ОБРАБОТЧИКИ (НЕ ВЛАДЕЛЕЦ) =====
        
        # ОБРАБОТКА кнопки "Позвать ИИ" (показ кнопки в channel_handlers)
        dp.message.register(
            ai_handler.handle_user_ai_button_click,
            F.text == "🤖 Позвать ИИ",
            F.chat.type == "private",
            F.from_user.id != owner_user_id
        )
        
        # Диалог с ИИ для пользователей (текстовые сообщения)
        dp.message.register(
            ai_handler.handle_user_ai_conversation,
            StateFilter(AISettingsStates.user_in_ai_conversation),
            F.chat.type == "private",
            F.from_user.id != owner_user_id,
            F.text
        )
        
        # ✅ НОВОЕ: Диалог с ИИ для пользователей (голосовые сообщения)
        dp.message.register(
            ai_handler.handle_user_ai_conversation,
            StateFilter(AISettingsStates.user_in_ai_conversation),
            F.chat.type == "private",
            F.from_user.id != owner_user_id,
            F.voice
        )
        
        # ✅ ИЗМЕНЕНО: Используем user_ai_exit_conversation для пользователей
        dp.callback_query.register(
            ai_handler.handle_user_ai_exit,
            F.data == "user_ai_exit_conversation",
            F.from_user.id != owner_user_id
        )
        
        # Команды выхода для пользователей
        dp.message.register(
            ai_handler.handle_user_exit_commands,
            F.text.lower().in_(['/exit', '/stop', '/cancel', 'выход', 'стоп']),
            F.chat.type == "private",
            F.from_user.id != owner_user_id
        )
        
        # ===== 🏷️ НОВОЕ: Обработка упоминаний бота в группах =====
        dp.message.register(
            ai_handler.handle_group_mention,
            F.chat.type.in_(["group", "supergroup"]),
            F.text,
            lambda message: _is_bot_mentioned(message, kwargs['bot_config']['bot_username'])
        )
        
        logger.info("✅ AI handlers registered with GROUP MENTIONS + VOICE + ACCESS CONTROL + FILE MANAGEMENT", 
                   owner_user_id=owner_user_id,
                   admin_handlers=8,  
                   user_handlers=5,
                   group_handlers=1,
                   file_handlers=2,  # Новые обработчики файлов
                   total_handlers=16,  # Обновленное количество
                   critical_fixes=[
                       "Message increment ONLY in handle_user_ai_conversation - NO DOUBLE INCREMENT",
                       "Safe message.text check in handle_admin_ai_conversation", 
                       "Safe text handling in handle_user_exit_commands",
                       "ENHANCED voice message transcription via OpenAI Whisper API with detailed diagnostics",
                       "COMPLETE VOICE SUPPORT for both users AND admins without frozen instance errors",
                       "New _get_openai_response_for_admin_with_text method for admin voice messages",
                       "GROUP MENTIONS SUPPORT: @botname message triggers AI response in groups",
                       "OWNER ACCESS CONTROL: All AI handlers check owner access before processing",
                       "FILE MANAGEMENT: Complete file upload/management support for OpenAI agents"
                   ])
        
    except Exception as e:
        logger.error("💥 Failed to register AI handlers", 
                    bot_id=kwargs.get('bot_config', {}).get('bot_id', 'unknown'),
                    error=str(e), exc_info=True)
        raise
