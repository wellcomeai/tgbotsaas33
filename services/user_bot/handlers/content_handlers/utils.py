"""
Вспомогательные функции и клавиатуры для контент-агентов.

✅ ПОЛНАЯ ФУНКЦИОНАЛЬНОСТЬ:
1. ⌨️ Генерация всех клавиатур интерфейса
2. 🔧 Утилиты форматирования (числа, даты, текст)
3. 🛡️ Безопасные методы работы с сообщениями
4. 📊 Извлечение данных из результатов
5. 🎨 Форматирование информации для отображения
6. 🔍 Валидация и проверка данных
7. ✨ Упрощенный интерфейс без технической информации
8. 🎯 Константы и настройки для всех модулей
"""

from typing import Dict, Any, Optional, Union
from datetime import datetime
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
import structlog

# Импорт для проверки медиагрупп
try:
    from aiogram_media_group import media_group_handler
    MEDIA_GROUP_AVAILABLE = True
except ImportError:
    MEDIA_GROUP_AVAILABLE = False

# Безопасный импорт состояний
try:
    from ...states import ContentStates
    CONTENT_STATES_AVAILABLE = True
except ImportError:
    CONTENT_STATES_AVAILABLE = False


class ContentUtilsMixin:
    """Миксин с вспомогательными функциями и утилитами"""
    
    async def _get_content_keyboards(self) -> Dict[str, InlineKeyboardMarkup]:
        """Получение клавиатур для контент-агентов с поддержкой каналов"""
        
        keyboards = {
            'main_menu_no_agent': InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✨ Создать агента", callback_data="content_create_agent")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_main")]
            ]),
            
            'main_menu_with_agent': InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📝 Рерайт поста", callback_data="content_rewrite")],
                [InlineKeyboardButton(text="⚙️ Управление агентом", callback_data="content_manage")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_main")]
            ]),
            
            'create_confirmation': InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Создать агента", callback_data="content_confirm_create")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="content_main")]
            ]),
            
            'manage_menu': InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⚙️ Настройки", callback_data="content_settings")],
                [InlineKeyboardButton(text="🗑️ Удалить агента", callback_data="content_delete_agent")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="content_main")]
            ]),
            
            'settings_menu': InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📝 Изменить имя", callback_data="content_edit_name")],
                [InlineKeyboardButton(text="📋 Изменить инструкции", callback_data="content_edit_instructions")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="content_manage")]
            ]),
            
            'delete_confirmation': InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🗑️ Да, удалить", callback_data="content_confirm_delete")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="content_manage")]
            ]),
            
            'rewrite_mode': InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚪 Завершить рерайт", callback_data="content_exit_rewrite")]
            ]),
            
            'back_to_main': InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад к контенту", callback_data="content_main")]
            ]),
            
            'back_to_settings': InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад к настройкам", callback_data="content_settings")]
            ]),
            
            # Новые клавиатуры для каналов и редактирования
            'post_actions': InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✏️ Внести правки", callback_data="content_edit_post"),
                    InlineKeyboardButton(text="📤 Опубликовать", callback_data="content_publish")
                ],
                [InlineKeyboardButton(text="🔄 Режим рерайта", callback_data="content_rewrite")]
            ]),
            
            'back_to_rewrite': InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ К рерайту", callback_data="content_rewrite")]
            ]),
            
            # Дополнительные клавиатуры для различных сценариев
            'error_retry': InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="content_rewrite")],
                [InlineKeyboardButton(text="📊 Главное меню", callback_data="content_main")]
            ]),
            
            'success_continue': InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📝 Новый рерайт", callback_data="content_rewrite")],
                [InlineKeyboardButton(text="⚙️ Настройки агента", callback_data="content_settings")],
                [InlineKeyboardButton(text="📊 Главное меню", callback_data="content_main")]
            ]),
            
            'channel_setup': InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📺 Настроить канал", callback_data="content_setup_channel")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="content_main")]
            ])
        }
        
        return keyboards
    
    def _format_number(self, number: Union[int, float, str]) -> str:
        """Форматирование чисел с разделителями"""
        try:
            if isinstance(number, str):
                number = int(number) if number.isdigit() else float(number)
            
            if isinstance(number, int):
                return f"{number:,}".replace(",", " ")
            elif isinstance(number, float):
                return f"{number:,.2f}".replace(",", " ")
            else:
                return str(number)
        except (ValueError, TypeError):
            return str(number)
    
    def _format_date(self, date_input: Union[str, datetime, None] = None) -> str:
        """Форматирование даты"""
        if not date_input:
            # Возвращаем текущую дату
            return datetime.now().strftime("%d.%m.%Y %H:%M")
        
        try:
            if isinstance(date_input, str):
                # Пробуем разные форматы даты
                formats = [
                    "%Y-%m-%dT%H:%M:%S.%fZ",  # ISO с микросекундами и Z
                    "%Y-%m-%dT%H:%M:%SZ",     # ISO без микросекунд с Z
                    "%Y-%m-%dT%H:%M:%S",      # ISO без Z
                    "%Y-%m-%d %H:%M:%S",      # SQL формат
                    "%d.%m.%Y %H:%M",         # Российский формат
                    "%Y-%m-%d"                # Только дата
                ]
                
                dt = None
                for fmt in formats:
                    try:
                        dt = datetime.strptime(date_input, fmt)
                        break
                    except ValueError:
                        continue
                
                if dt is None:
                    # Пробуем fromisoformat для новых Python
                    dt = datetime.fromisoformat(date_input.replace('Z', '+00:00'))
                
            elif isinstance(date_input, datetime):
                dt = date_input
            else:
                return "Неверный формат"
            
            return dt.strftime("%d.%m.%Y %H:%M")
            
        except Exception as e:
            self.logger.warning(f"⚠️ Date formatting error: {e}", date_input=str(date_input))
            return "Ошибка формата"
    
    def _truncate_text(self, text: str, max_length: int, suffix: str = "...") -> str:
        """Обрезка текста с добавлением суффикса"""
        if not text:
            return "Не указано"
        
        if not isinstance(text, str):
            text = str(text)
        
        if len(text) <= max_length:
            return text
        
        return text[:max_length-len(suffix)] + suffix
    
    def _safe_get_from_result(self, result: Dict, key: str, default: Any = None) -> Any:
        """🔧 Безопасное извлечение данных из result словаря"""
        try:
            if not isinstance(result, dict):
                self.logger.warning("⚠️ Result is not a dictionary", 
                                   result_type=type(result).__name__)
                return default
            
            return result.get(key, default)
            
        except (AttributeError, TypeError) as e:
            self.logger.warning(f"⚠️ Failed to get key '{key}' from result", 
                               result_type=type(result).__name__,
                               error=str(e))
            return default
    
    async def _safe_edit_or_answer(self, callback: CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup = None):
        """🔧 Безопасная отправка/редактирование сообщения"""
        try:
            # Пытаемся отредактировать сообщение
            await callback.message.edit_text(text, reply_markup=reply_markup)
            self.logger.debug("✅ Message edited successfully")
            
        except Exception as e:
            error_str = str(e).lower()
            
            # Обрабатываем известные ошибки
            if "no text in the message to edit" in error_str or "message is not modified" in error_str:
                self.logger.info("ℹ️ Cannot edit message, sending new one", 
                               bot_id=self.bot_id,
                               reason="no_text_to_edit")
                await callback.message.answer(text, reply_markup=reply_markup)
                
            elif "message to edit not found" in error_str:
                self.logger.warning("⚠️ Message to edit not found, sending new one",
                                   bot_id=self.bot_id)
                await callback.message.answer(text, reply_markup=reply_markup)
                
            elif "bad request" in error_str and "exactly the same" in error_str:
                self.logger.debug("ℹ️ Message content is the same, no edit needed")
                
            else:
                # Неизвестная ошибка - логируем и пробуем answer
                self.logger.error("💥 Unexpected error editing message", 
                                 bot_id=self.bot_id,
                                 error=str(e))
                try:
                    await callback.message.answer(text, reply_markup=reply_markup)
                except Exception as answer_error:
                    self.logger.error("💥 Failed to send fallback message", 
                                     error=str(answer_error))
    
    def _is_owner(self, user_id: int) -> bool:
        """Проверка владельца"""
        is_owner = user_id == self.owner_user_id
        
        self.logger.debug("👤 Owner check", 
                         bot_id=self.bot_id,
                         user_id=user_id,
                         owner_user_id=self.owner_user_id,
                         is_owner=is_owner)
        
        return is_owner
    
    def _validate_text_input(self, text: str, min_length: int = 1, max_length: int = 4096, 
                           field_name: str = "текст") -> tuple[bool, str]:
        """✅ Валидация текстового ввода"""
        if not text:
            return False, f"{field_name.capitalize()} не может быть пустым"
        
        if not isinstance(text, str):
            text = str(text)
        
        text = text.strip()
        
        if len(text) < min_length:
            return False, f"{field_name.capitalize()} слишком короткий (минимум {min_length} символов)"
        
        if len(text) > max_length:
            return False, f"{field_name.capitalize()} слишком длинный (максимум {max_length} символов)"
        
        return True, text
    
    def _format_file_size(self, size_bytes: int) -> str:
        """📊 Форматирование размера файла"""
        if not size_bytes:
            return "Неизвестно"
        
        try:
            size_bytes = int(size_bytes)
            
            if size_bytes < 1024:
                return f"{size_bytes} B"
            elif size_bytes < 1024 * 1024:
                return f"{size_bytes / 1024:.1f} KB"
            elif size_bytes < 1024 * 1024 * 1024:
                return f"{size_bytes / (1024 * 1024):.1f} MB"
            else:
                return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
                
        except (ValueError, TypeError):
            return "Ошибка размера"
    
    def _format_duration(self, seconds: int) -> str:
        """⏱️ Форматирование продолжительности"""
        if not seconds:
            return "0:00"
        
        try:
            seconds = int(seconds)
            
            if seconds < 60:
                return f"0:{seconds:02d}"
            elif seconds < 3600:
                minutes = seconds // 60
                secs = seconds % 60
                return f"{minutes}:{secs:02d}"
            else:
                hours = seconds // 3600
                minutes = (seconds % 3600) // 60
                secs = seconds % 60
                return f"{hours}:{minutes:02d}:{secs:02d}"
                
        except (ValueError, TypeError):
            return "0:00"
    
    def _get_media_emoji(self, media_type: str) -> str:
        """🎨 Получить эмоджи для типа медиа"""
        emoji_map = {
            'photo': '📷',
            'video': '🎥', 
            'animation': '🎬',
            'audio': '🎵',
            'voice': '🎤',
            'document': '📄',
            'sticker': '🎭',
            'video_note': '🎥',
            'media_group': '📸',
            'text': '📝'
        }
        
        return emoji_map.get(media_type, '📎')
    
    def _get_status_emoji(self, status: bool) -> str:
        """✅❌ Получить эмоджи статуса"""
        return "✅" if status else "❌"
    
    def _format_agent_stats(self, stats: Dict) -> str:
        """📊 Форматирование статистики агента"""
        if not stats:
            return "Статистика недоступна"
        
        tokens_used = self._format_number(stats.get('tokens_used', 0))
        has_openai = self._get_status_emoji(stats.get('has_openai_id', False))
        last_usage = self._format_date(stats.get('last_usage_at')) if stats.get('last_usage_at') else 'Не использовался'
        
        return f"""
📊 <b>Статистика агента:</b>
• Токенов использовано: {tokens_used}
• OpenAI интеграция: {has_openai}
• Последнее использование: {last_usage}
"""
    
    def _format_system_capabilities(self) -> str:
        """🔧 Форматирование системных возможностей"""
        capabilities = []
        
        # Медиагруппы
        media_groups = self._get_status_emoji(MEDIA_GROUP_AVAILABLE)
        capabilities.append(f"• Альбомы: {media_groups}")
        
        # FSM состояния  
        fsm_states = self._get_status_emoji(CONTENT_STATES_AVAILABLE)
        capabilities.append(f"• FSM состояния: {fsm_states}")
        
        # Всегда доступные возможности
        capabilities.extend([
            "• 🔗 Ссылки: ✅ Автоматическое извлечение",
            "• ✏️ Редактирование: ✅ Внесение правок", 
            "• 📤 Публикация: ✅ Отправка в каналы",
            "• 🎤 Голосовые сообщения: ✅ Полная поддержка",
            "• 📎 Все типы медиа: ✅ Фото, видео, GIF, аудио, документы, стикеры"
        ])
        
        return "\n".join(capabilities)
    
    def _get_supported_content_types(self) -> str:
        """📎 Список поддерживаемых типов контента"""
        return """
📎 <b>Поддерживаемый контент:</b>
• 📝 Текстовые сообщения
• 📷 Фотографии (с подписью или без)
• 🎥 Видео (с подписью или без)
• 🎬 GIF/анимации (с подписью или без)
• 🎵 Аудиофайлы (с подписью или без)
• 📄 Документы (с подписью или без)
• 🎭 Стикеры (с подписью или без)
• 🎤 Голосовые сообщения
• ✨ Альбомы (медиагруппы) {'✅' if MEDIA_GROUP_AVAILABLE else '❌'}
• 🔗 Ссылки (автоматически извлекаются)
"""
    
    def _create_error_keyboard(self, retry_callback: str = "content_main", 
                              main_callback: str = "admin_main") -> InlineKeyboardMarkup:
        """❌ Создать клавиатуру для ошибки"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Повторить", callback_data=retry_callback)],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data=main_callback)]
        ])
    
    def _create_success_keyboard(self, primary_callback: str, primary_text: str,
                               secondary_callback: str = "content_main") -> InlineKeyboardMarkup:
        """✅ Создать клавиатуру для успеха"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=primary_text, callback_data=primary_callback)],
            [InlineKeyboardButton(text="📊 Главное меню", callback_data=secondary_callback)]
        ])
    
    def _get_help_text(self) -> str:
        """❓ Текст справки по контент-агентам"""
        return f"""
❓ <b>Справка по контент-агентам</b>

🎯 <b>Что это:</b>
Контент-агент - это ИИ помощник для переписывания постов. Он работает на базе OpenAI GPT-4o и следует вашим инструкциям по стилю.

🚀 <b>Возможности:</b>
{self._get_supported_content_types()}

🎤 <b>Голосовой ввод:</b>
• Инструкции для агента можно записать голосом
• Правки постов можно диктовать голосом  
• Тексты для рерайта можно отправлять голосом
• Распознавание через OpenAI Whisper API

📺 <b>Каналы:</b>
• Подключение каналов для публикации
• Автоматическая публикация готовых постов
• Сохранение медиафайлов и ссылок

✏️ <b>Редактирование:</b>
• Внесение правок в готовые посты
• Пошаговое улучшение контента
• Сохранение истории изменений

🔧 <b>Системные требования:</b>
{self._format_system_capabilities()}

💡 <b>Советы:</b>
• Чем детальнее инструкции, тем лучше результат
• Можно комбинировать текст и голосовой ввод
• Альбомы обрабатываются как единое целое
• Ссылки сохраняются автоматически
"""


# Константы для всего модуля
class ContentConstants:
    """Константы для контент-агентов"""
    
    # Лимиты
    MIN_AGENT_NAME_LENGTH = 3
    MAX_AGENT_NAME_LENGTH = 100
    MIN_INSTRUCTIONS_LENGTH = 10
    MAX_INSTRUCTIONS_LENGTH = 2000
    MIN_TEXT_LENGTH = 3
    MAX_TEXT_LENGTH = 4000
    MIN_EDIT_INSTRUCTIONS_LENGTH = 5
    
    # Типы контента
    SUPPORTED_MEDIA_TYPES = [
        'photo', 'video', 'animation', 'audio', 
        'document', 'sticker', 'voice', 'video_note'
    ]
    
    # Эмоджи
    EMOJI_SUCCESS = '✅'
    EMOJI_ERROR = '❌'
    EMOJI_WARNING = '⚠️'
    EMOJI_INFO = 'ℹ️'
    EMOJI_PROCESSING = '⏳'
    
    # Сообщения
    MESSAGES = {
        'access_denied': '❌ Доступ запрещен',
        'agent_not_found': '❌ Агент не найден',
        'processing': '⏳ Обработка...',
        'success': '✅ Успешно!',
        'error': '❌ Произошла ошибка',
        'voice_transcribing': '🎤 Распознаю голосовое сообщение...',
        'voice_failed': '❌ Не удалось распознать голосовое сообщение'
    }
