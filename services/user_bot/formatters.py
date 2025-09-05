"""
Форматировщики сообщений и утилиты для UserBot
"""

import re
from typing import Optional
from datetime import datetime
import structlog

logger = structlog.get_logger()


class MessageFormatter:
    """Класс для форматирования сообщений"""
    
    @staticmethod
    def format_message(template: str, user) -> str:
        """Форматирование сообщения с подстановкой переменных пользователя"""
        if not template:
            return ""
        
        try:
            # Получаем данные пользователя
            first_name = getattr(user, 'first_name', '') or ''
            last_name = getattr(user, 'last_name', '') or ''
            username = getattr(user, 'username', '') or ''
            user_id = getattr(user, 'id', 0)
            
            # Формируем переменные для замены
            variables = {
                'first_name': first_name,
                'last_name': last_name,
                'full_name': f"{first_name} {last_name}".strip() or first_name,
                'username': f"@{username}" if username else '',
                'user_id': str(user_id),
                'mention': f'<a href="tg://user?id={user_id}">{first_name}</a>' if first_name else f"User {user_id}"
            }
            
            # Заменяем переменные в шаблоне
            formatted_message = template
            for var_name, var_value in variables.items():
                # Поддерживаем разные форматы: {var}, {{var}}, $var
                formatted_message = formatted_message.replace(f"{{{var_name}}}", var_value)
                formatted_message = formatted_message.replace(f"{{{{{var_name}}}}}", var_value)
                formatted_message = formatted_message.replace(f"${var_name}", var_value)
            
            return formatted_message
            
        except Exception as e:
            logger.error("Error formatting message", 
                        template=template, 
                        user_id=getattr(user, 'id', None),
                        error=str(e))
            return template  # Возвращаем оригинальный шаблон в случае ошибки
    
    @staticmethod
    def format_message_template(template: str, username: str = None, first_name: str = None) -> str:
        """Форматирование шаблона сообщения с переменными"""
        if not template:
            return template
        
        formatted = template.replace("{username}", username or "")
        formatted = formatted.replace("{first_name}", first_name or "")
        
        return formatted
    
    @staticmethod
    def parse_delay(delay_text: str) -> Optional[float]:
        """
        ✅ ПОЛНАЯ ПОДДЕРЖКА всех форматов времени задержки
        
        Поддерживаемые форматы:
        МИНУТЫ:
        - "5m", "5м", "30min", "45 minutes", "10 минут", "5 минута", "2 минуты"
        
        ЧАСЫ:
        - "2h", "2ч", "3 hours", "1 час", "2 часа", "5 часов"
        
        ДНИ:
        - "1d", "1д", "2 days", "1 день", "2 дня", "5 дней"
        
        НЕДЕЛИ:
        - "1w", "1н", "2 weeks", "1 неделя", "2 недели", "5 недель"
        
        ЧИСЛА:
        - "30" -> интерпретируется как 30 минут (изменено для удобства)
        - "0.5" -> 0.5 минут
        
        Args:
            delay_text: Текст с описанием задержки
            
        Returns:
            float: Количество часов или None если не удалось распарсить
        """
        if not delay_text:
            return None
        
        delay_text = delay_text.strip().lower()
        
        try:
            # Регулярные выражения для разных форматов с поддержкой кириллицы
            patterns = [
                # МИНУТЫ: 5m, 5м, 30min, 45 minutes, 10 минут, 5 минута, 2 минуты
                (r'(\d+(?:\.\d+)?)\s*(?:m|м|min|minutes?|минут[аы]?)', lambda x: float(x) / 60),
                
                # ЧАСЫ: 2h, 2ч, 3 hours, 1 час, 2 часа, 5 часов
                (r'(\d+(?:\.\d+)?)\s*(?:h|ч|hours?|час[аов]?)', lambda x: float(x)),
                
                # ДНИ: 1d, 1д, 2 days, 1 день, 2 дня, 5 дней
                (r'(\d+(?:\.\d+)?)\s*(?:d|д|days?|дн[яей])', lambda x: float(x) * 24),
                
                # НЕДЕЛИ: 1w, 1н, 2 weeks, 1 неделя, 2 недели, 5 недель
                (r'(\d+(?:\.\d+)?)\s*(?:w|н|weeks?|недел[ияь])', lambda x: float(x) * 168),
                
                # ПРОСТО ЧИСЛО (интерпретируется как минуты для удобства)
                (r'^(\d+(?:\.\d+)?)$', lambda x: float(x) / 60)
            ]
            
            for pattern, converter in patterns:
                match = re.search(pattern, delay_text)
                if match:
                    try:
                        value = match.group(1)
                        hours = converter(value)
                        
                        # Ограничиваем разумными пределами
                        if 0 <= hours <= 8760:  # Максимум год (365 * 24)
                            logger.debug("Successfully parsed delay", 
                                       delay_text=delay_text, 
                                       hours=hours,
                                       pattern=pattern)
                            return hours
                        else:
                            logger.warning("Delay out of bounds", 
                                         delay_text=delay_text, 
                                         hours=hours)
                            return None
                            
                    except (ValueError, IndexError) as e:
                        logger.debug("Error converting delay value", 
                                   delay_text=delay_text, 
                                   value=match.group(1),
                                   error=str(e))
                        continue
            
            # Если ничего не подошло
            logger.warning("Could not parse delay", delay_text=delay_text)
            return None
            
        except Exception as e:
            logger.error("Error parsing delay", delay_text=delay_text, error=str(e))
            return None
    
    @staticmethod
    def format_delay(hours: float) -> str:
        """
        ✅ УЛУЧШЕННОЕ форматирование часов задержки в читаемый русский текст
        
        Args:
            hours: Количество часов
            
        Returns:
            str: Читаемое представление задержки на русском языке
        """
        try:
            if hours <= 0:
                return "немедленно"
            
            # Если меньше часа - показываем в минутах
            if hours < 1:
                minutes = round(hours * 60)
                if minutes <= 0:
                    return "немедленно"
                elif minutes == 1:
                    return "1 минуту"
                elif minutes in [2, 3, 4]:
                    return f"{minutes} минуты"
                else:
                    return f"{minutes} минут"
            
            # Если меньше суток - показываем в часах
            elif hours < 24:
                hours_int = round(hours)
                if hours_int == 1:
                    return "1 час"
                elif hours_int in [2, 3, 4]:
                    return f"{hours_int} часа"
                else:
                    return f"{hours_int} часов"
            
            # Если меньше недели - показываем в днях
            elif hours < 168:  # 7 * 24
                days = round(hours / 24)
                if days == 1:
                    return "1 день"
                elif days in [2, 3, 4]:
                    return f"{days} дня"
                else:
                    return f"{days} дней"
            
            # Если больше недели - показываем в неделях
            else:
                weeks = round(hours / 168)
                if weeks == 1:
                    return "1 неделю"
                elif weeks in [2, 3, 4]:
                    return f"{weeks} недели"
                else:
                    return f"{weeks} недель"
                    
        except Exception as e:
            logger.error("Error formatting delay", hours=hours, error=str(e))
            return f"{hours} ч."


class MediaExtractor:
    """Класс для извлечения информации о медиафайлах"""
    
    @staticmethod
    async def extract_media_info(message) -> dict:
        """Извлечение информации о медиафайле из сообщения"""
        try:
            if message.photo:
                photo = message.photo[-1]
                return {
                    'file_id': photo.file_id,
                    'file_unique_id': photo.file_unique_id,
                    'file_size': photo.file_size,
                    'media_type': 'photo',
                    'filename': None
                }
            elif message.video:
                return {
                    'file_id': message.video.file_id,
                    'file_unique_id': message.video.file_unique_id,
                    'file_size': message.video.file_size,
                    'media_type': 'video',
                    'filename': message.video.file_name
                }
            elif message.document:
                return {
                    'file_id': message.document.file_id,
                    'file_unique_id': message.document.file_unique_id,
                    'file_size': message.document.file_size,
                    'media_type': 'document',
                    'filename': message.document.file_name
                }
            elif message.audio:
                return {
                    'file_id': message.audio.file_id,
                    'file_unique_id': message.audio.file_unique_id,
                    'file_size': message.audio.file_size,
                    'media_type': 'audio',
                    'filename': message.audio.file_name
                }
            elif message.voice:
                return {
                    'file_id': message.voice.file_id,
                    'file_unique_id': message.voice.file_unique_id,
                    'file_size': message.voice.file_size,
                    'media_type': 'voice',
                    'filename': None
                }
            elif message.video_note:
                return {
                    'file_id': message.video_note.file_id,
                    'file_unique_id': message.video_note.file_unique_id,
                    'file_size': message.video_note.file_size,
                    'media_type': 'video_note',
                    'filename': None
                }
            
            return None
            
        except Exception as e:
            logger.error("Failed to extract media info", error=str(e))
            return None
