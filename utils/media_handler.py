from typing import Dict, List, Optional, Union, Any
from dataclasses import dataclass
from datetime import datetime
import structlog

from aiogram.types import Message, PhotoSize, Document, Video, Audio, Voice, VideoNote, Animation, Sticker
from aiogram.types import InputMediaPhoto, InputMediaVideo, InputMediaDocument, InputMediaAudio

logger = structlog.get_logger()


@dataclass
class MediaItem:
    """Элемент медиа для рассылки"""
    media_type: str  # 'photo', 'video', 'document', 'audio', 'voice', 'video_note', 'animation', 'sticker'
    file_id: str
    file_unique_id: str
    caption: Optional[str] = None
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    file_name: Optional[str] = None
    duration: Optional[int] = None  # для audio/video/voice/video_note
    width: Optional[int] = None  # для photo/video/animation
    height: Optional[int] = None  # для photo/video/animation
    thumbnail_file_id: Optional[str] = None


@dataclass
class BroadcastMedia:
    """Медиа для рассылки"""
    media_items: List[MediaItem]
    text_content: Optional[str] = None  # Текст если есть
    is_album: bool = False  # Медиаальбом
    
    @property
    def has_media(self) -> bool:
        return len(self.media_items) > 0
    
    @property
    def media_count(self) -> int:
        return len(self.media_items)
    
    @property
    def primary_media_type(self) -> Optional[str]:
        return self.media_items[0].media_type if self.media_items else None


class MediaHandler:
    """Обработчик медиа для админских рассылок"""
    
    # Поддерживаемые типы медиа
    SUPPORTED_MEDIA_TYPES = {
        'photo', 'video', 'document', 'audio', 'voice', 
        'video_note', 'animation', 'sticker'
    }
    
    # Типы медиа для альбомов (MediaGroup)
    ALBUM_MEDIA_TYPES = {'photo', 'video'}
    
    # Максимальные размеры файлов (в байтах)
    MAX_FILE_SIZES = {
        'photo': 10 * 1024 * 1024,    # 10MB
        'video': 50 * 1024 * 1024,    # 50MB
        'document': 50 * 1024 * 1024, # 50MB
        'audio': 50 * 1024 * 1024,    # 50MB
        'voice': 1 * 1024 * 1024,     # 1MB
        'video_note': 1 * 1024 * 1024, # 1MB
        'animation': 50 * 1024 * 1024, # 50MB
        'sticker': 512 * 1024          # 512KB
    }
    
    @staticmethod
    def extract_media_from_message(message: Message) -> Optional[BroadcastMedia]:
        """Извлечь медиа из сообщения для рассылки"""
        try:
            media_items = []
            text_content = message.text or message.caption
            
            # Обрабатываем медиаальбом (MediaGroup)
            if hasattr(message, 'media_group_id') and message.media_group_id:
                logger.info("Processing media group", media_group_id=message.media_group_id)
                # Для медиагруппы обрабатываем только текущий элемент
                # Полный альбом будет обработан в bot handler'е
                media_item = MediaHandler._extract_single_media_item(message)
                if media_item:
                    media_items.append(media_item)
                
                return BroadcastMedia(
                    media_items=media_items,
                    text_content=text_content,
                    is_album=True
                )
            
            # Обрабатываем одиночное медиа
            media_item = MediaHandler._extract_single_media_item(message)
            if media_item:
                media_items.append(media_item)
            
            # Если нет медиа, но есть текст
            if not media_items and not text_content:
                return None
            
            return BroadcastMedia(
                media_items=media_items,
                text_content=text_content,
                is_album=False
            )
            
        except Exception as e:
            logger.error("Failed to extract media from message", error=str(e))
            return None
    
    @staticmethod
    def _extract_single_media_item(message: Message) -> Optional[MediaItem]:
        """Извлечь один медиа элемент из сообщения"""
        try:
            # Фото
            if message.photo:
                largest_photo = max(message.photo, key=lambda p: p.file_size or 0)
                return MediaItem(
                    media_type='photo',
                    file_id=largest_photo.file_id,
                    file_unique_id=largest_photo.file_unique_id,
                    caption=message.caption,
                    file_size=largest_photo.file_size,
                    width=largest_photo.width,
                    height=largest_photo.height
                )
            
            # Видео
            elif message.video:
                return MediaItem(
                    media_type='video',
                    file_id=message.video.file_id,
                    file_unique_id=message.video.file_unique_id,
                    caption=message.caption,
                    file_size=message.video.file_size,
                    mime_type=message.video.mime_type,
                    file_name=message.video.file_name,
                    duration=message.video.duration,
                    width=message.video.width,
                    height=message.video.height,
                    thumbnail_file_id=message.video.thumbnail.file_id if message.video.thumbnail else None
                )
            
            # Документ
            elif message.document:
                return MediaItem(
                    media_type='document',
                    file_id=message.document.file_id,
                    file_unique_id=message.document.file_unique_id,
                    caption=message.caption,
                    file_size=message.document.file_size,
                    mime_type=message.document.mime_type,
                    file_name=message.document.file_name,
                    thumbnail_file_id=message.document.thumbnail.file_id if message.document.thumbnail else None
                )
            
            # Аудио
            elif message.audio:
                return MediaItem(
                    media_type='audio',
                    file_id=message.audio.file_id,
                    file_unique_id=message.audio.file_unique_id,
                    caption=message.caption,
                    file_size=message.audio.file_size,
                    mime_type=message.audio.mime_type,
                    file_name=message.audio.file_name,
                    duration=message.audio.duration,
                    thumbnail_file_id=message.audio.thumbnail.file_id if message.audio.thumbnail else None
                )
            
            # Голосовое сообщение
            elif message.voice:
                return MediaItem(
                    media_type='voice',
                    file_id=message.voice.file_id,
                    file_unique_id=message.voice.file_unique_id,
                    file_size=message.voice.file_size,
                    mime_type=message.voice.mime_type,
                    duration=message.voice.duration
                )
            
            # Видеокружок
            elif message.video_note:
                return MediaItem(
                    media_type='video_note',
                    file_id=message.video_note.file_id,
                    file_unique_id=message.video_note.file_unique_id,
                    file_size=message.video_note.file_size,
                    duration=message.video_note.duration,
                    thumbnail_file_id=message.video_note.thumbnail.file_id if message.video_note.thumbnail else None
                )
            
            # Анимация (GIF)
            elif message.animation:
                return MediaItem(
                    media_type='animation',
                    file_id=message.animation.file_id,
                    file_unique_id=message.animation.file_unique_id,
                    caption=message.caption,
                    file_size=message.animation.file_size,
                    mime_type=message.animation.mime_type,
                    file_name=message.animation.file_name,
                    width=message.animation.width,
                    height=message.animation.height,
                    duration=message.animation.duration,
                    thumbnail_file_id=message.animation.thumbnail.file_id if message.animation.thumbnail else None
                )
            
            # Стикер
            elif message.sticker:
                return MediaItem(
                    media_type='sticker',
                    file_id=message.sticker.file_id,
                    file_unique_id=message.sticker.file_unique_id,
                    file_size=message.sticker.file_size,
                    width=message.sticker.width,
                    height=message.sticker.height,
                    thumbnail_file_id=message.sticker.thumbnail.file_id if message.sticker.thumbnail else None
                )
            
            return None
            
        except Exception as e:
            logger.error("Failed to extract single media item", error=str(e))
            return None
    
    @staticmethod
    def validate_media_for_broadcast(broadcast_media: BroadcastMedia) -> Dict[str, Any]:
        """Валидация медиа для рассылки"""
        validation = {
            'valid': True,
            'warnings': [],
            'errors': [],
            'total_size': 0,
            'media_summary': {}
        }
        
        try:
            if not broadcast_media.has_media and not broadcast_media.text_content:
                validation['valid'] = False
                validation['errors'].append("Сообщение должно содержать текст или медиа")
                return validation
            
            # Подсчет статистики
            media_types_count = {}
            total_size = 0
            
            for media_item in broadcast_media.media_items:
                # Подсчет типов
                media_type = media_item.media_type
                media_types_count[media_type] = media_types_count.get(media_type, 0) + 1
                
                # Подсчет размера
                if media_item.file_size:
                    total_size += media_item.file_size
                    
                    # Проверка размера файла
                    max_size = MediaHandler.MAX_FILE_SIZES.get(media_type, 50 * 1024 * 1024)
                    if media_item.file_size > max_size:
                        validation['errors'].append(
                            f"Файл {media_type} слишком большой: "
                            f"{media_item.file_size / 1024 / 1024:.1f}MB "
                            f"(максимум {max_size / 1024 / 1024:.1f}MB)"
                        )
            
            validation['total_size'] = total_size
            validation['media_summary'] = media_types_count
            
            # Проверки для медиаальбомов
            if broadcast_media.is_album:
                if len(broadcast_media.media_items) > 10:
                    validation['errors'].append("Медиаальбом не может содержать больше 10 элементов")
                
                # Проверка совместимости типов в альбоме
                album_types = {item.media_type for item in broadcast_media.media_items}
                if not album_types.issubset(MediaHandler.ALBUM_MEDIA_TYPES):
                    validation['errors'].append(
                        f"Медиаальбом может содержать только фото и видео, "
                        f"найдены: {', '.join(album_types)}"
                    )
            
            # Общие предупреждения
            if total_size > 100 * 1024 * 1024:  # 100MB
                validation['warnings'].append(
                    f"Большой размер медиа ({total_size / 1024 / 1024:.1f}MB) "
                    "может замедлить рассылку"
                )
            
            if len(broadcast_media.media_items) > 1 and not broadcast_media.is_album:
                validation['warnings'].append(
                    "Найдено несколько медиа файлов, но не как альбом. "
                    "Будет отправлен только первый файл."
                )
            
            if validation['errors']:
                validation['valid'] = False
            
            return validation
            
        except Exception as e:
            logger.error("Failed to validate media", error=str(e))
            return {
                'valid': False,
                'errors': [f"Ошибка валидации: {str(e)}"],
                'warnings': [],
                'total_size': 0,
                'media_summary': {}
            }
    
    @staticmethod
    def get_media_preview_text(broadcast_media: BroadcastMedia) -> str:
        """Получить превью медиа для подтверждения рассылки"""
        try:
            if not broadcast_media.has_media:
                return "📝 Текстовое сообщение"
            
            preview_parts = []
            
            if broadcast_media.is_album:
                album_summary = {}
                for item in broadcast_media.media_items:
                    media_type = item.media_type
                    album_summary[media_type] = album_summary.get(media_type, 0) + 1
                
                album_desc = ", ".join([
                    f"{count} {MediaHandler._get_media_emoji(media_type)} {MediaHandler._get_media_name_ru(media_type)}"
                    for media_type, count in album_summary.items()
                ])
                preview_parts.append(f"📸 Медиаальбом ({album_desc})")
            else:
                media_item = broadcast_media.media_items[0]
                emoji = MediaHandler._get_media_emoji(media_item.media_type)
                name = MediaHandler._get_media_name_ru(media_item.media_type)
                size = f" ({media_item.file_size / 1024 / 1024:.1f}MB)" if media_item.file_size else ""
                preview_parts.append(f"{emoji} {name}{size}")
            
            if broadcast_media.text_content:
                preview_parts.append(f"📝 Текст: {broadcast_media.text_content[:50]}...")
            
            return " + ".join(preview_parts)
            
        except Exception as e:
            logger.error("Failed to generate media preview", error=str(e))
            return "📎 Медиа контент"
    
    @staticmethod
    def _get_media_emoji(media_type: str) -> str:
        """Получить эмодзи для типа медиа"""
        emoji_map = {
            'photo': '🖼',
            'video': '🎥',
            'document': '📄',
            'audio': '🎵',
            'voice': '🎤',
            'video_note': '📹',
            'animation': '🎬',
            'sticker': '🎭'
        }
        return emoji_map.get(media_type, '📎')
    
    @staticmethod
    def _get_media_name_ru(media_type: str) -> str:
        """Получить русское название типа медиа"""
        name_map = {
            'photo': 'фото',
            'video': 'видео',
            'document': 'документ',
            'audio': 'аудио',
            'voice': 'голосовое',
            'video_note': 'кружок',
            'animation': 'анимация',
            'sticker': 'стикер'
        }
        return name_map.get(media_type, 'медиа')
    
    @staticmethod
    def serialize_media_for_db(broadcast_media: BroadcastMedia) -> Dict[str, Any]:
        """Сериализация медиа для сохранения в БД"""
        try:
            return {
                'has_media': broadcast_media.has_media,
                'media_count': broadcast_media.media_count,
                'is_album': broadcast_media.is_album,
                'primary_media_type': broadcast_media.primary_media_type,
                'text_content': broadcast_media.text_content,
                'media_items': [
                    {
                        'media_type': item.media_type,
                        'file_id': item.file_id,
                        'file_unique_id': item.file_unique_id,
                        'caption': item.caption,
                        'file_size': item.file_size,
                        'mime_type': item.mime_type,
                        'file_name': item.file_name,
                        'duration': item.duration,
                        'width': item.width,
                        'height': item.height,
                        'thumbnail_file_id': item.thumbnail_file_id
                    }
                    for item in broadcast_media.media_items
                ],
                'total_size': sum(item.file_size or 0 for item in broadcast_media.media_items),
                'created_at': datetime.now().isoformat()
            }
        except Exception as e:
            logger.error("Failed to serialize media for DB", error=str(e))
            return {
                'has_media': False,
                'error': str(e)
            }
