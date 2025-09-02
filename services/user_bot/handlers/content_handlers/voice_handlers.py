"""
Методы работы с голосовыми сообщениями.

✅ ПОЛНАЯ ФУНКЦИОНАЛЬНОСТЬ:
1. 🎤 Транскрипция голосовых сообщений через OpenAI Whisper API
2. 🔧 Поддержка голоса для всех типов ввода (инструкции, правки, рерайты)
3. 🛡️ Обработка ошибок транскрипции и fallback сценарии
4. 🔑 Безопасное получение API ключей из разных источников
5. 📊 Детальное логирование процесса транскрипции
6. 🗂️ Работа с временными файлами и их очистка
7. 🌐 HTTP клиент для взаимодействия с OpenAI API
8. 🎯 Оптимизированные настройки для русского языка
"""

import structlog
import tempfile
import os
from typing import Optional
from aiogram.types import Voice, Message


class VoiceHandlersMixin:
    """Миксин для методов работы с голосовыми сообщениями"""
    
    async def _transcribe_voice_message(self, voice: Voice) -> str:
        """🎤 Транскрипция голосового сообщения через OpenAI Whisper API"""
        self.logger.info("🎤 Starting voice transcription process for content", 
                        voice_file_id=voice.file_id,
                        voice_duration=getattr(voice, 'duration', 'unknown'),
                        voice_file_size=getattr(voice, 'file_size', 'unknown'),
                        bot_id=self.bot_id)
        
        try:
            # 1. Импортируем необходимые модули
            try:
                from config import settings
                import os
                self.logger.info("✅ Settings and os imported successfully for voice transcription")
            except ImportError as e:
                self.logger.error("❌ Failed to import settings or os for voice", error=str(e))
                return ""
            
            # 2. Пытаемся получить API ключ разными способами
            api_key = None
            key_source = ""
            
            # Способ 1: Из settings.OPENAI_API_KEY
            try:
                api_key = getattr(settings, 'OPENAI_API_KEY', None)
                if api_key:
                    key_source = "settings.OPENAI_API_KEY"
                    self.logger.info("✅ API key found in settings for voice", source=key_source)
            except Exception as e:
                self.logger.warning("⚠️ Could not get API key from settings for voice", error=str(e))
            
            # Способ 2: Из переменной окружения OPENAI_API_KEY
            if not api_key:
                api_key = os.environ.get('OPENAI_API_KEY')
                if api_key:
                    key_source = "os.environ['OPENAI_API_KEY']"
                    self.logger.info("✅ API key found in environment for voice", source=key_source)
            
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
                        self.logger.info("✅ API key found in environment for voice", source=key_source)
                        break
            
            if not api_key:
                # Показываем доступные переменные окружения для диагностики
                openai_vars = [k for k in os.environ.keys() if 'OPENAI' in k.upper() or 'GPT' in k.upper()]
                settings_attrs = [attr for attr in dir(settings) if not attr.startswith('_')]
                
                self.logger.error("❌ OpenAI API key not found anywhere for voice transcription", 
                                env_openai_vars=openai_vars,
                                settings_attrs=settings_attrs[:10])
                return ""
            
            self.logger.info("✅ OpenAI API key found for voice transcription", 
                           source=key_source,
                           key_length=len(api_key) if api_key else 0,
                           key_preview=f"{api_key[:10]}...{api_key[-4:]}" if api_key and len(api_key) > 14 else "SHORT_KEY")
            
            # 3. Получаем модель Whisper
            whisper_model = getattr(settings, 'OPENAI_WHISPER_MODEL', 'whisper-1')
            self.logger.info("✅ Whisper model for content", model=whisper_model)
            
            # 4. Проверяем bot instance
            bot = self.bot_config.get('bot')
            if not bot:
                self.logger.error("❌ Bot instance not available in bot_config for voice", 
                                bot_config_keys=list(self.bot_config.keys()))
                return ""
            
            self.logger.info("✅ Bot instance available for voice", bot_type=type(bot).__name__)
            
            # 5. Импортируем необходимые библиотеки
            try:
                import aiohttp
                import tempfile
                self.logger.info("✅ Required libraries imported for voice")
            except ImportError as e:
                self.logger.error("❌ Failed to import required libraries for voice", error=str(e))
                return ""
            
            # 6. Получаем информацию о файле
            self.logger.info("📥 Getting voice file info for content...")
            try:
                file_info = await bot.get_file(voice.file_id)
                self.logger.info("✅ Voice file info retrieved for content", 
                               file_path=file_info.file_path,
                               file_size=getattr(file_info, 'file_size', 'unknown'))
            except Exception as e:
                self.logger.error("❌ Failed to get voice file info for content", error=str(e))
                return ""
            
            # 7. Создаем временный файл
            self.logger.info("📁 Creating temporary file for voice...")
            try:
                temp_file = tempfile.NamedTemporaryFile(suffix='.ogg', delete=False)
                temp_file_path = temp_file.name
                temp_file.close()  # Закрываем, чтобы можно было записать
                self.logger.info("✅ Temporary file created for voice", path=temp_file_path)
            except Exception as e:
                self.logger.error("❌ Failed to create temporary file for voice", error=str(e))
                return ""
            
            try:
                # 8. Скачиваем файл
                self.logger.info("⬇️ Downloading voice file for content...")
                try:
                    with open(temp_file_path, 'wb') as temp_file_handle:
                        await bot.download_file(file_info.file_path, temp_file_handle)
                    
                    # Проверяем размер скачанного файла
                    file_size = os.path.getsize(temp_file_path)
                    self.logger.info("✅ Voice file downloaded for content", size_bytes=file_size)
                    
                    if file_size == 0:
                        self.logger.error("❌ Downloaded voice file is empty")
                        return ""
                        
                except Exception as e:
                    self.logger.error("❌ Failed to download voice file for content", error=str(e))
                    return ""
                
                # 9. Отправляем в Whisper API
                self.logger.info("🌐 Sending to OpenAI Whisper API for content...")
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
                            
                            self.logger.info("📡 Making API request to Whisper for content...", 
                                           url='https://api.openai.com/v1/audio/transcriptions',
                                           model=whisper_model,
                                           language='ru')
                            
                            async with session.post(
                                'https://api.openai.com/v1/audio/transcriptions',
                                data=data,
                                headers=headers,
                                timeout=30
                            ) as response:
                                self.logger.info("📨 Received Whisper API response for content", 
                                              status=response.status,
                                              content_type=response.content_type,
                                              content_length=response.headers.get('content-length', 'unknown'))
                                
                                if response.status == 200:
                                    result = await response.json()
                                    transcribed_text = result.get('text', '').strip()
                                    
                                    self.logger.info("✅ Voice transcription successful for content", 
                                                  text_length=len(transcribed_text),
                                                  preview=transcribed_text[:100] if transcribed_text else "EMPTY")
                                    return transcribed_text
                                elif response.status == 401:
                                    error_text = await response.text()
                                    self.logger.error("❌ Whisper API authentication failed for content", 
                                                   status=response.status,
                                                   error=error_text,
                                                   key_source=key_source)
                                    return ""
                                elif response.status == 429:
                                    error_text = await response.text()
                                    self.logger.error("❌ Whisper API rate limit exceeded for content", 
                                                   status=response.status,
                                                   error=error_text)
                                    return ""
                                else:
                                    error_text = await response.text()
                                    self.logger.error("❌ Whisper API error for content", 
                                                   status=response.status,
                                                   error=error_text,
                                                   headers=dict(response.headers))
                                    return ""
                                    
                except Exception as e:
                    self.logger.error("❌ API request failed for content voice", 
                                    error=str(e), 
                                    error_type=type(e).__name__)
                    return ""
            finally:
                # 10. Удаляем временный файл
                try:
                    if os.path.exists(temp_file_path):
                        os.unlink(temp_file_path)
                        self.logger.info("🗑️ Temporary voice file cleaned up")
                except Exception as e:
                    self.logger.warning("⚠️ Failed to cleanup temp voice file", error=str(e))
            
        except Exception as e:
            self.logger.error("💥 Unexpected error in voice transcription for content", 
                            error=str(e), 
                            error_type=type(e).__name__,
                            exc_info=True)
            return ""
    
    async def _get_openai_api_key(self) -> Optional[str]:
        """🔑 Безопасное получение OpenAI API ключа из различных источников"""
        try:
            # Импортируем настройки
            try:
                from config import settings
                import os
            except ImportError as e:
                self.logger.error("❌ Failed to import settings or os", error=str(e))
                return None
            
            api_key = None
            key_source = ""
            
            # Источник 1: settings.OPENAI_API_KEY
            try:
                api_key = getattr(settings, 'OPENAI_API_KEY', None)
                if api_key:
                    key_source = "settings.OPENAI_API_KEY"
            except Exception as e:
                self.logger.warning("⚠️ Could not get API key from settings", error=str(e))
            
            # Источник 2: переменная окружения OPENAI_API_KEY
            if not api_key:
                api_key = os.environ.get('OPENAI_API_KEY')
                if api_key:
                    key_source = "os.environ['OPENAI_API_KEY']"
            
            # Источник 3: альтернативные имена переменных
            if not api_key:
                alternative_names = [
                    'OPENAI_TOKEN', 
                    'OPENAI_SECRET_KEY', 
                    'GPT_API_KEY',
                    'OPENAI_API_TOKEN'
                ]
                for name in alternative_names:
                    api_key = os.environ.get(name)
                    if api_key:
                        key_source = f"os.environ['{name}']"
                        break
            
            if api_key:
                self.logger.info("✅ OpenAI API key found", 
                               source=key_source,
                               key_length=len(api_key),
                               key_preview=f"{api_key[:10]}...{api_key[-4:]}" if len(api_key) > 14 else "SHORT_KEY")
                return api_key
            else:
                # Диагностика доступных переменных
                openai_vars = [k for k in os.environ.keys() if 'OPENAI' in k.upper() or 'GPT' in k.upper()]
                self.logger.error("❌ OpenAI API key not found in any source", 
                                env_openai_vars=openai_vars)
                return None
                
        except Exception as e:
            self.logger.error("💥 Unexpected error getting OpenAI API key", 
                            error=str(e), 
                            error_type=type(e).__name__)
            return None
    
    async def _process_voice_input(self, message: Message, context: str = "general") -> Optional[str]:
        """🎤 Обработка голосового сообщения с контекстом"""
        if not message.voice:
            return None
        
        self.logger.info("🎤 Processing voice input", 
                        user_id=message.from_user.id,
                        bot_id=self.bot_id,
                        context=context,
                        voice_duration=getattr(message.voice, 'duration', 'unknown'))
        
        # Показываем индикатор набора
        await message.bot.send_chat_action(message.chat.id, "typing")
        
        # Транскрибируем голосовое сообщение
        transcribed_text = await self._transcribe_voice_message(message.voice)
        
        if not transcribed_text:
            self.logger.warning("⚠️ Voice transcription failed", 
                               user_id=message.from_user.id,
                               context=context)
            return None
        
        # Логируем успешную транскрипцию
        self.logger.info("✅ Voice input processed successfully", 
                        user_id=message.from_user.id,
                        context=context,
                        transcribed_length=len(transcribed_text),
                        preview=transcribed_text[:100])
        
        return transcribed_text
    
    async def _show_voice_transcription_preview(self, message: Message, transcribed_text: str, context: str = ""):
        """📋 Показать превью транскрипции пользователю"""
        context_emoji = {
            "instructions": "📋",
            "edit_instructions": "✏️", 
            "rewrite": "📝",
            "general": "🎤"
        }.get(context, "🎤")
        
        context_name = {
            "instructions": "инструкции",
            "edit_instructions": "правки",
            "rewrite": "текст для рерайта",
            "general": "голосовое сообщение"
        }.get(context, "голосовое сообщение")
        
        preview_text = transcribed_text[:200] if len(transcribed_text) > 200 else transcribed_text
        ellipsis = "..." if len(transcribed_text) > 200 else ""
        
        preview_message = f"{context_emoji} <b>Распознано {context_name}:</b>\n<i>{preview_text}{ellipsis}</i>\n\n⏳ Обрабатываю..."
        
        await message.answer(preview_message)
    
    def _validate_transcribed_text(self, text: str, min_length: int = 5, max_length: int = 4000) -> tuple[bool, str]:
        """✅ Валидация транскрибированного текста"""
        if not text:
            return False, "Пустой текст после транскрипции"
        
        if len(text) < min_length:
            return False, f"Текст слишком короткий (минимум {min_length} символов)"
        
        if len(text) > max_length:
            return False, f"Текст слишком длинный (максимум {max_length} символов)"
        
        # Проверка на подозрительный контент (только нечитаемые символы)
        readable_chars = sum(1 for char in text if char.isalnum() or char.isspace() or char in '.,!?;:-()[]{}"\'/\\')
        if len(text) > 0 and readable_chars / len(text) < 0.5:
            return False, "Текст содержит слишком много нечитаемых символов"
        
        return True, "OK"
    
    def _get_voice_error_message(self, error_type: str, context: str = "general") -> str:
        """❌ Получить сообщение об ошибке для голосового ввода"""
        context_name = {
            "instructions": "инструкций",
            "edit_instructions": "правок", 
            "rewrite": "текста для рерайта",
            "general": "голосового сообщения"
        }.get(context, "голосового сообщения")
        
        error_messages = {
            "transcription_failed": f"❌ Не удалось распознать {context_name}. Попробуйте еще раз или напишите текстом.",
            "api_key_missing": f"❌ Ошибка настройки API для распознавания речи. Обратитесь к администратору.",
            "api_error": f"❌ Ошибка сервиса распознавания речи. Попробуйте позже или напишите текстом.",
            "file_error": f"❌ Не удалось обработать голосовой файл. Попробуйте записать еще раз.",
            "validation_failed": f"❌ Распознанный текст не прошел проверку. Попробуйте еще раз или напишите текстом."
        }
        
        return error_messages.get(error_type, f"❌ Ошибка обработки {context_name}")
    
    def _get_voice_success_message(self, context: str = "general") -> str:
        """✅ Получить сообщение об успешной обработке голоса"""
        success_messages = {
            "instructions": "✅ Голосовые инструкции распознаны успешно!",
            "edit_instructions": "✅ Голосовые правки распознаны успешно!",
            "rewrite": "✅ Голосовое сообщение распознано успешно!",
            "general": "✅ Голосовое сообщение обработано!"
        }
        
        return success_messages.get(context, "✅ Голосовое сообщение обработано!")
    
    def _is_voice_supported(self) -> bool:
        """🎤 Проверка поддержки голосовых сообщений"""
        try:
            # Проверяем наличие API ключа
            from config import settings
            import os
            
            api_key = getattr(settings, 'OPENAI_API_KEY', None) or os.environ.get('OPENAI_API_KEY')
            
            if not api_key:
                self.logger.warning("⚠️ Voice messages not supported: OpenAI API key not found")
                return False
            
            # Проверяем необходимые библиотеки
            try:
                import aiohttp
                import tempfile
                return True
            except ImportError as e:
                self.logger.warning("⚠️ Voice messages not supported: missing libraries", error=str(e))
                return False
                
        except Exception as e:
            self.logger.error("💥 Error checking voice support", error=str(e))
            return False
    
    def _get_voice_capabilities_info(self) -> str:
        """ℹ️ Информация о возможностях голосового ввода"""
        if not self._is_voice_supported():
            return "🎤 ❌ Голосовые сообщения не поддерживаются"
        
        return """🎤 ✅ <b>Голосовые сообщения поддерживаются:</b>
• 📋 Запись инструкций для агента голосом
• ✏️ Правки постов голосом  
• 📝 Отправка текста для рерайта голосом
• 🔧 Редактирование настроек агента голосом
• 🌐 Распознавание через OpenAI Whisper API
• 🇷🇺 Оптимизировано для русского языка"""
