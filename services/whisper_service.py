"""
Whisper Service для распознавания голосовых сообщений
Интеграция OpenAI Whisper API для транскрипции голосовых сообщений в текст
"""

import asyncio
import aiohttp
import aiofiles
import tempfile
import os
from typing import Optional, Dict, Any
from pathlib import Path
import structlog

from config import settings

logger = structlog.get_logger()


class WhisperServiceError(Exception):
    """Базовая ошибка Whisper Service"""
    pass


class WhisperService:
    """Сервис для распознавания голосовых сообщений через OpenAI Whisper API"""
    
    # Константы
    MAX_FILE_SIZE = 25 * 1024 * 1024  # 25MB - лимит OpenAI
    SUPPORTED_FORMATS = {'.ogg', '.oga', '.mp3', '.wav', '.m4a', '.webm'}
    DEFAULT_MODEL = "whisper-1"
    DEFAULT_LANGUAGE = "ru"  # Русский по умолчанию
    
    def __init__(self):
        self.api_key = getattr(settings, 'openai_api_key', None)
        self.session: Optional[aiohttp.ClientSession] = None
        self.base_url = "https://api.openai.com/v1/audio/transcriptions"
        
        logger.info("WhisperService initialized", 
                   has_api_key=bool(self.api_key),
                   max_file_size=f"{self.MAX_FILE_SIZE / (1024*1024):.1f}MB")
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Получение HTTP сессии"""
        if not self.session or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=60)  # Увеличенный таймаут для аудио
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session
    
    async def close(self):
        """Закрытие сессии"""
        if self.session and not self.session.closed:
            await self.session.close()
            logger.debug("WhisperService session closed")
    
    def is_available(self) -> bool:
        """Проверка доступности сервиса"""
        return bool(self.api_key)
    
    async def download_voice_file(self, bot, file_id: str) -> Optional[str]:
        """
        Скачивание голосового файла из Telegram
        
        Args:
            bot: Экземпляр aiogram Bot
            file_id: ID файла в Telegram
            
        Returns:
            str: Путь к скачанному временному файлу или None
        """
        temp_file_path = None
        
        try:
            # Получаем информацию о файле
            file_info = await bot.get_file(file_id)
            
            logger.debug("Voice file info retrieved", 
                        file_id=file_id,
                        file_size=file_info.file_size,
                        file_path=file_info.file_path)
            
            # Проверяем размер файла
            if file_info.file_size and file_info.file_size > self.MAX_FILE_SIZE:
                raise WhisperServiceError(
                    f"Файл слишком большой: {file_info.file_size / (1024*1024):.1f}MB. "
                    f"Максимум: {self.MAX_FILE_SIZE / (1024*1024):.1f}MB"
                )
            
            # Создаем временный файл
            temp_dir = tempfile.gettempdir()
            temp_file = tempfile.NamedTemporaryFile(
                suffix='.oga',  # Telegram voice обычно в OGG/OGA
                delete=False,
                dir=temp_dir
            )
            temp_file_path = temp_file.name
            temp_file.close()
            
            # Скачиваем файл
            await bot.download_file(file_info.file_path, temp_file_path)
            
            # Проверяем что файл скачался
            if not os.path.exists(temp_file_path) or os.path.getsize(temp_file_path) == 0:
                raise WhisperServiceError("Не удалось скачать голосовой файл")
            
            logger.debug("Voice file downloaded successfully", 
                        file_id=file_id,
                        temp_path=temp_file_path,
                        file_size=os.path.getsize(temp_file_path))
            
            return temp_file_path
            
        except Exception as e:
            # Очищаем временный файл при ошибке
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except:
                    pass
            
            logger.error("Failed to download voice file", 
                        file_id=file_id,
                        error=str(e),
                        error_type=type(e).__name__)
            raise WhisperServiceError(f"Ошибка скачивания: {str(e)}")
    
    async def transcribe_audio(
        self, 
        file_path: str, 
        language: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        response_format: str = "text"
    ) -> Optional[str]:
        """
        Транскрипция аудиофайла через OpenAI Whisper API
        
        Args:
            file_path: Путь к аудиофайлу
            language: Язык аудио (по умолчанию русский)
            model: Модель Whisper
            response_format: Формат ответа
            
        Returns:
            str: Транскрибированный текст или None
        """
        if not self.is_available():
            raise WhisperServiceError("OpenAI API key не настроен")
        
        if not os.path.exists(file_path):
            raise WhisperServiceError(f"Файл не найден: {file_path}")
        
        session = await self._get_session()
        
        try:
            # Проверяем расширение файла
            file_extension = Path(file_path).suffix.lower()
            if file_extension not in self.SUPPORTED_FORMATS:
                logger.warning("Unsupported file format", 
                             file_path=file_path,
                             extension=file_extension,
                             supported=list(self.SUPPORTED_FORMATS))
            
            # Подготавливаем данные для запроса
            data = aiohttp.FormData()
            
            # Добавляем файл
            async with aiofiles.open(file_path, 'rb') as audio_file:
                file_content = await audio_file.read()
                data.add_field(
                    'file',
                    file_content,
                    filename=f"voice{file_extension}",
                    content_type='audio/ogg'
                )
            
            # Добавляем параметры
            data.add_field('model', model)
            data.add_field('response_format', response_format)
            
            # Добавляем язык если указан
            if language or self.DEFAULT_LANGUAGE:
                data.add_field('language', language or self.DEFAULT_LANGUAGE)
            
            # Заголовки
            headers = {
                'Authorization': f'Bearer {self.api_key}'
            }
            
            logger.debug("Sending transcription request", 
                        file_size=len(file_content),
                        model=model,
                        language=language or self.DEFAULT_LANGUAGE,
                        response_format=response_format)
            
            # Отправляем запрос
            async with session.post(
                self.base_url,
                data=data,
                headers=headers
            ) as response:
                
                response_text = await response.text()
                
                logger.debug("Whisper API response received", 
                           status=response.status,
                           response_length=len(response_text))
                
                if response.status == 200:
                    # Для формата "text" возвращается просто текст
                    if response_format == "text":
                        transcription = response_text.strip()
                    else:
                        # Для JSON форматов парсим
                        response_json = await response.json()
                        transcription = response_json.get('text', '').strip()
                    
                    if transcription:
                        logger.info("Audio transcription successful", 
                                   file_size=len(file_content),
                                   transcription_length=len(transcription),
                                   language=language or self.DEFAULT_LANGUAGE)
                        return transcription
                    else:
                        logger.warning("Empty transcription result")
                        return None
                        
                else:
                    # Обработка ошибок API
                    try:
                        error_data = await response.json()
                        error_message = error_data.get('error', {}).get('message', response_text)
                    except:
                        error_message = response_text
                    
                    logger.error("Whisper API error", 
                               status=response.status,
                               error_message=error_message)
                    
                    if response.status == 400:
                        raise WhisperServiceError(f"Некорректный аудиофайл: {error_message}")
                    elif response.status == 401:
                        raise WhisperServiceError("Неверный API ключ OpenAI")
                    elif response.status == 413:
                        raise WhisperServiceError("Файл слишком большой для обработки")
                    elif response.status == 429:
                        raise WhisperServiceError("Превышен лимит запросов к OpenAI")
                    else:
                        raise WhisperServiceError(f"Ошибка Whisper API: {error_message}")
                        
        except aiohttp.ClientError as e:
            logger.error("Network error during transcription", 
                        file_path=file_path,
                        error=str(e))
            raise WhisperServiceError(f"Сетевая ошибка: {str(e)}")
            
        except WhisperServiceError:
            # Перебрасываем наши ошибки как есть
            raise
            
        except Exception as e:
            logger.error("Unexpected error during transcription", 
                        file_path=file_path,
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            raise WhisperServiceError(f"Неожиданная ошибка: {str(e)}")
    
    async def transcribe_voice_message(
        self, 
        bot, 
        file_id: str,
        language: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Полный цикл обработки голосового сообщения
        
        Args:
            bot: Экземпляр aiogram Bot
            file_id: ID голосового файла в Telegram
            language: Язык для распознавания
            
        Returns:
            Dict с результатом транскрипции
        """
        temp_file_path = None
        
        try:
            start_time = asyncio.get_event_loop().time()
            
            # Скачиваем файл
            temp_file_path = await self.download_voice_file(bot, file_id)
            download_time = asyncio.get_event_loop().time() - start_time
            
            # Транскрибируем
            transcription_start = asyncio.get_event_loop().time()
            transcription = await self.transcribe_audio(
                temp_file_path, 
                language=language
            )
            transcription_time = asyncio.get_event_loop().time() - transcription_start
            
            total_time = asyncio.get_event_loop().time() - start_time
            
            # Формируем результат
            result = {
                'success': True,
                'transcription': transcription,
                'file_id': file_id,
                'language': language or self.DEFAULT_LANGUAGE,
                'timing': {
                    'download_time': round(download_time, 2),
                    'transcription_time': round(transcription_time, 2),
                    'total_time': round(total_time, 2)
                },
                'file_info': {
                    'size': os.path.getsize(temp_file_path) if temp_file_path else 0,
                    'temp_path': temp_file_path
                }
            }
            
            logger.info("Voice message transcription completed", 
                       file_id=file_id,
                       transcription_length=len(transcription) if transcription else 0,
                       total_time=total_time,
                       success=bool(transcription))
            
            return result
            
        except Exception as e:
            logger.error("Voice transcription failed", 
                        file_id=file_id,
                        error=str(e),
                        error_type=type(e).__name__)
            
            return {
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__,
                'file_id': file_id,
                'language': language or self.DEFAULT_LANGUAGE
            }
            
        finally:
            # Очищаем временный файл
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                    logger.debug("Temporary voice file cleaned up", temp_path=temp_file_path)
                except Exception as cleanup_error:
                    logger.warning("Failed to cleanup temporary file", 
                                 temp_path=temp_file_path,
                                 error=str(cleanup_error))


# Глобальный экземпляр сервиса
whisper_service = WhisperService()


# Вспомогательные функции для быстрого доступа
async def transcribe_voice(bot, file_id: str, language: Optional[str] = None) -> Dict[str, Any]:
    """
    Быстрая функция для транскрипции голосового сообщения
    
    Args:
        bot: Экземпляр aiogram Bot
        file_id: ID голосового файла
        language: Язык (необязательно)
        
    Returns:
        Dict с результатом
    """
    return await whisper_service.transcribe_voice_message(bot, file_id, language)


async def is_whisper_available() -> bool:
    """Проверка доступности Whisper сервиса"""
    return whisper_service.is_available()


async def cleanup_whisper_service():
    """Очистка ресурсов Whisper сервиса"""
    await whisper_service.close()
