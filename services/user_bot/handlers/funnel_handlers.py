"""
Обработчики воронки продаж
"""

import structlog
from aiogram import Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from config import settings, Emoji, Messages
from ..states import FunnelStates
from ..keyboards import FunnelKeyboards
from ..formatters import MessageFormatter, MediaExtractor

logger = structlog.get_logger()


def register_funnel_handlers(dp: Dispatcher, **kwargs):
    """Регистрация обработчиков воронки"""
    
    db = kwargs['db']
    bot_config = kwargs['bot_config']  # ИЗМЕНЕНО: получаем полную конфигурацию
    funnel_manager = kwargs['funnel_manager']
    user_bot = kwargs.get('user_bot')  # Получаем ссылку на UserBot
    
    try:
        handler = FunnelHandler(db, bot_config, funnel_manager, user_bot)
        
        # Callback обработчики
        dp.callback_query.register(handler.cb_funnel_action, F.data.startswith("funnel_"))
        dp.callback_query.register(handler.cb_message_action, F.data.startswith("msg_"))
        dp.callback_query.register(handler.cb_button_action, F.data.startswith("btn_"))
        dp.callback_query.register(handler.cb_media_action, F.data.startswith("media_"))
        dp.callback_query.register(handler.cb_confirm_delete, F.data.startswith("confirm_delete_"))
        
        # Обработчики ввода
        dp.message.register(
            handler.handle_funnel_message_text,
            FunnelStates.waiting_for_message_text
        )
        dp.message.register(
            handler.handle_funnel_message_delay,
            FunnelStates.waiting_for_message_delay
        )
        dp.message.register(
            handler.handle_edit_message_text,
            FunnelStates.waiting_for_edit_text
        )
        dp.message.register(
            handler.handle_edit_message_delay,
            FunnelStates.waiting_for_edit_delay
        )
        dp.message.register(
            handler.handle_funnel_button_text,
            FunnelStates.waiting_for_button_text
        )
        dp.message.register(
            handler.handle_funnel_button_url,
            FunnelStates.waiting_for_button_url
        )
        
        # Обработчики медиа
        dp.message.register(
            handler.handle_media_file_upload,
            F.photo | F.video | F.document | F.audio | F.voice | F.video_note,
            FunnelStates.waiting_for_media_file
        )
        
        logger.info("Funnel handlers registered successfully", 
                   bot_id=bot_config['bot_id'])
        
    except Exception as e:
        logger.error("Failed to register funnel handlers", 
                    bot_id=kwargs.get('bot_config', {}).get('bot_id', 'unknown'),
                    error=str(e), exc_info=True)
        raise


async def show_funnel_main_menu(callback: CallbackQuery, bot_id: int, bot_username: str, funnel_manager):
    """Показать главное меню воронки (вызывается из admin_handlers)"""
    try:
        # Получаем статистику воронки
        funnel_stats = await funnel_manager.get_funnel_stats(bot_id)
        
        status_emoji = Emoji.PLAY if funnel_stats.get("is_enabled", True) else Emoji.PAUSE
        status_text = "Включена" if funnel_stats.get("is_enabled", True) else "Выключена"
        message_count = funnel_stats.get("message_count", 0)
        
        text = f"""
{Emoji.FUNNEL} <b>Воронка продаж @{bot_username}</b>

{status_emoji} <b>Статус:</b> {status_text}
{Emoji.SEQUENCE} <b>Сообщений:</b> {message_count}
{Emoji.USERS} <b>Активных пользователей:</b> {funnel_stats.get("funnel_enabled_users", 0)}
{Emoji.ROCKET} <b>Запущено воронок:</b> {funnel_stats.get("funnel_started_users", 0)}

{Messages.FUNNEL_WELCOME if message_count == 0 else ""}
"""
        
        await callback.message.edit_text(
            text,
            reply_markup=FunnelKeyboards.main_menu()
        )
        
    except Exception as e:
        logger.error("Failed to show funnel main menu", bot_id=bot_id, error=str(e))
        await callback.answer("Ошибка при загрузке воронки", show_alert=True)


class FunnelHandler:
    """Обработчик воронки продаж"""
    
    def __init__(self, db, bot_config: dict, funnel_manager, user_bot):
        self.db = db
        self.bot_config = bot_config
        self.bot_id = bot_config['bot_id']
        self.owner_user_id = bot_config['owner_user_id']
        self.funnel_manager = funnel_manager
        self.formatter = MessageFormatter()
        self.media_extractor = MediaExtractor()
        self.user_bot = user_bot  # Сохраняем ссылку на UserBot
        
        # Получаем настройки из конфигурации
        self.bot_username = bot_config['bot_username']
    
    def _is_owner(self, user_id: int) -> bool:
        """Проверка владельца"""
        return user_id == self.owner_user_id
    
    async def _cancel_and_show_funnel(self, message: Message, state: FSMContext):
        """Отмена и показ воронки"""
        await state.clear()
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="К воронке", callback_data="funnel_messages")]
        ])
        await message.answer("Операция отменена", reply_markup=keyboard)
    
    async def cb_funnel_action(self, callback: CallbackQuery, state: FSMContext):
        """Обработка действий воронки"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        action = callback.data.replace("funnel_", "")
        
        if action == "messages":
            await self._show_funnel_messages(callback)
        elif action == "add":
            await self._start_message_creation(callback, state)
        elif action == "settings":
            await self._show_funnel_settings(callback)
        elif action == "stats":
            await self._show_funnel_stats(callback)
        elif action == "toggle":
            await self._toggle_funnel(callback)
    
    async def _show_funnel_messages(self, callback: CallbackQuery):
        """Показать список сообщений воронки"""
        try:
            messages = await self.funnel_manager.get_funnel_messages(self.bot_id)
            
            if not messages:
                text = Messages.FUNNEL_NO_MESSAGES
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=f"{Emoji.PLUS} Создать первое сообщение",
                            callback_data="funnel_add"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text=f"{Emoji.BACK} К воронке",
                            callback_data="admin_funnel"
                        )
                    ]
                ])
                
                await callback.message.edit_text(text, reply_markup=keyboard)
                return
            
            text = f"{Emoji.SEQUENCE} <b>Сообщения воронки ({len(messages)}):</b>\n\n"
            
            keyboard = []
            for msg in messages:
                # Индикаторы статуса
                media_icon = f" {Emoji.MEDIA}" if msg['has_media'] else ""
                button_icon = f" {Emoji.BUTTON}×{msg['button_count']}" if msg['button_count'] > 0 else ""
                active_icon = "" if msg['is_active'] else " ⏸"
                
                # Форматирование задержки
                delay_hours = msg['delay_hours']
                delay_text = self.formatter.format_delay(delay_hours)
                
                text += f"<b>{msg['number']}.</b> {msg['text'][:50]}...\n"
                text += f"   {Emoji.CLOCK} Через {delay_text}{media_icon}{button_icon}{active_icon}\n\n"
                
                keyboard.append([
                    InlineKeyboardButton(
                        text=f"{msg['number']}. Сообщение",
                        callback_data=f"msg_view_{msg['id']}"
                    )
                ])
            
            # Кнопки управления
            keyboard.append([
                InlineKeyboardButton(
                    text=f"{Emoji.PLUS} Добавить сообщение",
                    callback_data="funnel_add"
                )
            ])
            
            keyboard.append([
                InlineKeyboardButton(
                    text=f"{Emoji.BACK} К воронке",
                    callback_data="admin_funnel"
                )
            ])
            
            await callback.message.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
            
        except Exception as e:
            logger.error("Failed to show funnel messages", bot_id=self.bot_id, error=str(e))
            await callback.answer("Ошибка при загрузке сообщений", show_alert=True)
    
    async def _show_funnel_stats(self, callback: CallbackQuery):
        """Показать статистику воронки"""
        try:
            funnel_stats = await self.funnel_manager.get_funnel_stats(self.bot_id)
            
            text = f"""
{Emoji.STATISTICS} <b>Статистика воронки</b>

{Emoji.SEQUENCE} <b>Сообщения:</b>
   Настроено: {funnel_stats.get("message_count", 0)}
   Без ограничений: ✅

{Emoji.USERS} <b>Пользователи:</b>
   Всего подписчиков: {funnel_stats.get("total_subscribers", 0)}
   В воронке: {funnel_stats.get("funnel_enabled_users", 0)}
   Запущено: {funnel_stats.get("funnel_started_users", 0)}

{Emoji.CHART} <b>Отправки:</b>
   Отправлено: {funnel_stats.get("messages_sent", 0)}
   Ожидают: {funnel_stats.get("messages_pending", 0)}
   Ошибок: {funnel_stats.get("messages_failed", 0)}

{Emoji.INFO} <b>События:</b>
"""
            
            # Добавляем статистику событий
            events = funnel_stats.get("events", {})
            for event_type, event_data in events.items():
                count = event_data.get('count', 0)
                text += f"   {event_type}: {count}\n"
            
            if not events:
                text += "   Нет данных\n"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔄 Обновить",
                        callback_data="funnel_stats"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=f"{Emoji.BACK} К воронке",
                        callback_data="admin_funnel"
                    )
                ]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error("Failed to show funnel stats", bot_id=self.bot_id, error=str(e))
            await callback.answer("Ошибка при загрузке статистики", show_alert=True)
    
    async def _show_funnel_settings(self, callback: CallbackQuery):
        """Показать настройки воронки"""
        try:
            funnel_stats = await self.funnel_manager.get_funnel_stats(self.bot_id)
            
            is_enabled = funnel_stats.get("is_enabled", True)
            status_text = "включена" if is_enabled else "выключена"
            toggle_text = "Выключить" if is_enabled else "Включить"
            toggle_emoji = Emoji.PAUSE if is_enabled else Emoji.PLAY
            
            text = f"""
{Emoji.SETTINGS} <b>Настройки воронки</b>

{Emoji.INFO} <b>Текущий статус:</b> Воронка {status_text}
{Emoji.SEQUENCE} <b>Сообщений:</b> {funnel_stats.get("message_count", 0)} (без ограничений)

{Emoji.ROCKET} <b>Как работает воронка:</b>
- Запускается после нажатия на кнопку приветствия
- Отправляет сообщения по расписанию
- Автоматически добавляет UTM-метки для аналитики
- Работает в фоновом режиме

{Emoji.WARNING} <b>Важно:</b>
- Изменения применяются к новым пользователям
- Текущие отправки продолжают работу по старой схеме
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"{toggle_emoji} {toggle_text} воронку",
                        callback_data="funnel_toggle"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=f"{Emoji.BACK} К воронке",
                        callback_data="admin_funnel"
                    )
                ]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error("Failed to show funnel settings", bot_id=self.bot_id, error=str(e))
            await callback.answer("Ошибка при загрузке настроек", show_alert=True)
    
    async def _toggle_funnel(self, callback: CallbackQuery):
        """Переключить статус воронки"""
        try:
            funnel_stats = await self.funnel_manager.get_funnel_stats(self.bot_id)
            current_status = funnel_stats.get("is_enabled", True)
            new_status = not current_status
            
            success = await self.funnel_manager.toggle_funnel(self.bot_id, new_status)
            
            if success:
                status_text = "включена" if new_status else "выключена"
                await callback.answer(f"Воронка {status_text}!", show_alert=True)
                await self._show_funnel_settings(callback)
            else:
                await callback.answer("Ошибка при изменении статуса", show_alert=True)
                
        except Exception as e:
            logger.error("Failed to toggle funnel", bot_id=self.bot_id, error=str(e))
            await callback.answer("Ошибка при изменении статуса", show_alert=True)
    
    async def cb_message_action(self, callback: CallbackQuery, state: FSMContext):
        """Обработка действий с сообщениями"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        action_data = callback.data.replace("msg_", "")
        parts = action_data.split("_")
        
        if len(parts) < 2:
            await callback.answer("Неверный формат команды", show_alert=True)
            return
        
        action = parts[0]
        
        if action == "edit":
            sub_action = parts[1]
            message_id = int(parts[2])
        elif action in ["view", "preview", "duplicate", "delete", "media", "buttons"]:
            message_id = int(parts[1])
            sub_action = None
        else:
            await callback.answer("Неизвестное действие", show_alert=True)
            return
        
        await state.update_data(message_id=message_id)
        
        # Маршрутизация к обработчикам
        if action == "view":
            await self._show_message_details(callback, message_id)
        elif action == "preview":
            await self._show_message_preview(callback, message_id)
        elif action == "edit" and sub_action == "text":
            await self._edit_message_text(callback, state, message_id)
        elif action == "edit" and sub_action == "delay":
            await self._edit_message_delay(callback, state, message_id)
        elif action == "media":
            await self._manage_message_media(callback, state, message_id)
        elif action == "buttons":
            await self._manage_message_buttons(callback, state, message_id)
        elif action == "duplicate":
            await self._duplicate_message(callback, message_id)
        elif action == "delete":
            await self._delete_message_confirm(callback, message_id)
    
    async def _show_message_details(self, callback: CallbackQuery, message_id: int):
        """Показать детали сообщения"""
        try:
            message = await self.db.get_broadcast_message_by_id(message_id)
            if not message:
                await callback.answer("Сообщение не найдено", show_alert=True)
                return
            
            buttons = await self.db.get_message_buttons(message_id)
            
            delay_text = self.formatter.format_delay(float(message.delay_hours))
            
            preview = message.message_text[:200] + "..." if len(message.message_text) > 200 else message.message_text
            
            text = f"""
{Emoji.MESSAGE} <b>Сообщение #{message.message_number}</b>

{Emoji.CLOCK} <b>Задержка:</b> {delay_text}
{Emoji.INFO} <b>Статус:</b> {'Активно' if message.is_active else 'Неактивно'}
{Emoji.MEDIA} <b>Медиа:</b> {message.media_type or 'Нет' if getattr(message, 'media_file_id', None) else 'Нет'}

{Emoji.MESSAGE} <b>Текст сообщения:</b>
<code>{preview}</code>

{Emoji.BUTTON} <b>Кнопок:</b> {len(buttons)}
"""
            
            if buttons:
                text += f"\n{Emoji.BUTTON} <b>Кнопки:</b>\n"
                for i, btn in enumerate(buttons, 1):
                    text += f"   {i}. {btn.button_text} → {btn.button_url[:30]}...\n"
            
            await callback.message.edit_text(
                text,
                reply_markup=FunnelKeyboards.message_menu(message_id)
            )
            
        except Exception as e:
            logger.error("Failed to show message details", message_id=message_id, error=str(e))
            await callback.answer("Ошибка при загрузке сообщения", show_alert=True)
    
    async def _show_message_preview(self, callback: CallbackQuery, message_id: int):
        """Показать превью сообщения"""
        try:
            preview_text = await self.funnel_manager.get_message_preview(message_id, "Иван")
            
            message = await self.db.get_broadcast_message_by_id(message_id)
            if not message:
                await callback.answer("Сообщение не найдено", show_alert=True)
                return
            
            buttons = await self.db.get_message_buttons(message_id)
            
            text = f"""
{Messages.PREVIEW_HEADER}

{Emoji.MESSAGE} <b>Сообщение #{message.message_number}</b>
{Emoji.CLOCK} <b>Задержка:</b> {self.formatter.format_delay(float(message.delay_hours))}

<b>Предпросмотр для пользователя "Иван":</b>

<i>--- Начало сообщения ---</i>
{preview_text}
<i>--- Конец сообщения ---</i>
"""
            
            if buttons:
                text += f"\n{Emoji.BUTTON} <b>Кнопки:</b>\n"
                for btn in buttons:
                    text += f"🔘 [{btn.button_text}]({btn.button_url})\n"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"{Emoji.BACK} К сообщению",
                        callback_data=f"msg_view_{message_id}"
                    )
                ]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error("Failed to show message preview", message_id=message_id, error=str(e))
            await callback.answer("Ошибка при генерации превью", show_alert=True)
    
    async def _start_message_creation(self, callback: CallbackQuery, state: FSMContext):
        """Начать создание нового сообщения"""
        try:
            messages = await self.funnel_manager.get_funnel_messages(self.bot_id)
            existing_numbers = [msg['number'] for msg in messages] if messages else []
            next_number = 1
            while next_number in existing_numbers:
                next_number += 1
            
            await state.update_data(message_number=next_number)
            await state.set_state(FunnelStates.waiting_for_message_text)
            
            text = f"""
{Emoji.MESSAGE} <b>Создание сообщения #{next_number}</b>

Отправьте текст сообщения для воронки продаж.

{Emoji.INFO} <b>Доступные переменные:</b>
- <code>{{first_name}}</code> - имя пользователя
- <code>{{username}}</code> - @username пользователя

{Emoji.WARNING} <b>Лимиты:</b>
- Максимум {settings.max_funnel_message_length} символов
- Поддерживается HTML-разметка

<b>Отправьте текст сообщения:</b>
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"{Emoji.BACK} Отмена",
                        callback_data="funnel_messages"
                    )
                ]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error("Failed to start message creation", bot_id=self.bot_id, error=str(e))
            await callback.answer("Ошибка при создании сообщения", show_alert=True)
    
    # ✅ РЕАЛИЗОВАННЫЕ МЕТОДЫ РЕДАКТИРОВАНИЯ
    async def _edit_message_text(self, callback: CallbackQuery, state: FSMContext, message_id: int):
        """Редактирование текста сообщения"""
        try:
            message = await self.db.get_broadcast_message_by_id(message_id)
            if not message:
                await callback.answer("Сообщение не найдено", show_alert=True)
                return
            
            await state.set_state(FunnelStates.waiting_for_edit_text)
            
            text = f"""
{Emoji.EDIT} <b>Изменение текста сообщения #{message.message_number}</b>

<b>Текущий текст:</b>
<code>{message.message_text}</code>

{Emoji.INFO} <b>Доступные переменные:</b>
- <code>{{first_name}}</code> - имя пользователя
- <code>{{username}}</code> - @username пользователя

<b>Отправьте новый текст сообщения:</b>
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"{Emoji.BACK} Отмена",
                        callback_data=f"msg_view_{message_id}"
                    )
                ]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error("Failed to start text editing", message_id=message_id, error=str(e))
            await callback.answer("Ошибка при редактировании", show_alert=True)
    
    async def _edit_message_delay(self, callback: CallbackQuery, state: FSMContext, message_id: int):
        """Редактирование задержки сообщения"""
        try:
            message = await self.db.get_broadcast_message_by_id(message_id)
            if not message:
                await callback.answer("Сообщение не найдено", show_alert=True)
                return
            
            await state.set_state(FunnelStates.waiting_for_edit_delay)
            
            current_delay = self.formatter.format_delay(float(message.delay_hours))
            
            text = f"""
{Emoji.CLOCK} <b>Изменение задержки сообщения #{message.message_number}</b>

<b>Текущая задержка:</b> {current_delay}

{Emoji.INFO} <b>Примеры форматов:</b>
- <code>0</code> - сразу
- <code>5</code> или <code>5м</code> - через 5 минут
- <code>2ч</code> или <code>2h</code> - через 2 часа
- <code>1д</code> или <code>1d</code> - через 1 день

<b>Отправьте новое время задержки:</b>
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"{Emoji.BACK} Отмена",
                        callback_data=f"msg_view_{message_id}"
                    )
                ]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error("Failed to start delay editing", message_id=message_id, error=str(e))
            await callback.answer("Ошибка при редактировании", show_alert=True)
    
    # ✅ ПОЛНАЯ РЕАЛИЗАЦИЯ УПРАВЛЕНИЯ МЕДИА
    async def _manage_message_media(self, callback: CallbackQuery, state: FSMContext, message_id: int):
        """Управление медиа сообщения"""
        try:
            message = await self.db.get_broadcast_message_by_id(message_id)
            if not message:
                await callback.answer("Сообщение не найдено", show_alert=True)
                return
            
            has_media = getattr(message, 'media_file_id', None) is not None
            media_type = message.media_type or "нет"
            
            text = f"""
{Emoji.MEDIA} <b>Медиа для сообщения #{message.message_number}</b>

<b>Текущий статус:</b>
{"✅ Есть медиа" if has_media else "❌ Без медиа"}

<b>Тип медиа:</b> {media_type}

<b>Поддерживаемые типы:</b>
📸 Фото (photo)
🎥 Видео (video) 
📎 Документы (document)
🎵 Аудио (audio)
🎤 Голосовые (voice)
⭕ Видеокружки (video_note)

{"<b>Загруженное медиа:</b> " + getattr(message, 'media_filename', 'без названия') if has_media else ""}
"""
            
            keyboard_buttons = []
            
            if has_media:
                keyboard_buttons.extend([
                    [InlineKeyboardButton(text="🔄 Заменить медиа", callback_data=f"media_replace_{message_id}")],
                    [InlineKeyboardButton(text="🗑 Удалить медиа", callback_data=f"media_delete_{message_id}")]
                ])
            else:
                keyboard_buttons.append([InlineKeyboardButton(text="📎 Добавить медиа", callback_data=f"media_add_{message_id}")])
            
            keyboard_buttons.append([InlineKeyboardButton(text=f"{Emoji.BACK} К сообщению", callback_data=f"msg_view_{message_id}")])
            
            await callback.message.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
            )
            
        except Exception as e:
            logger.error("Failed to manage message media", message_id=message_id, error=str(e))
            await callback.answer("Ошибка при управлении медиа", show_alert=True)
    
    async def cb_media_action(self, callback: CallbackQuery, state: FSMContext):
        """Обработка действий с медиа"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        action_data = callback.data.replace("media_", "")
        parts = action_data.split("_")
        
        if len(parts) < 2:
            await callback.answer("Неверный формат команды", show_alert=True)
            return
        
        action = parts[0]
        message_id = int(parts[1])
        
        await state.update_data(message_id=message_id)
        
        if action in ["add", "replace"]:
            await self._start_media_upload(callback, state, message_id, action)
        elif action == "delete":
            await self._delete_message_media(callback, message_id)
    
    async def _start_media_upload(self, callback: CallbackQuery, state: FSMContext, message_id: int, action: str):
        """Начать загрузку медиа"""
        try:
            await state.set_state(FunnelStates.waiting_for_media_file)
            await state.update_data(message_id=message_id, media_action=action)
            
            action_text = "Загрузите" if action == "add" else "Загрузите новое"
            
            text = f"""
📎 <b>{action_text} медиа для сообщения</b>

<b>Поддерживаемые форматы:</b>
📸 Фото (JPG, PNG, WebP)
🎥 Видео (MP4, MOV, AVI)
📎 Документы (PDF, DOC, ZIP, etc)
🎵 Аудио (MP3, WAV, OGG)
🎤 Голосовые сообщения
⭕ Видеокружки

<b>Ограничения:</b>
• Максимальный размер: 50 МБ
• Фото: до 10 МБ
• Видео: до 50 МБ

{action_text} файл:
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data=f"msg_media_{message_id}")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error("Failed to start media upload", message_id=message_id, error=str(e))
            await callback.answer("Ошибка при настройке загрузки", show_alert=True)
    
    async def _delete_message_media(self, callback: CallbackQuery, message_id: int):
        """Удаление медиа из сообщения"""
        try:
            success = await self.funnel_manager.update_funnel_message(
                message_id=message_id,
                bot_id=self.bot_id,
                media_file_id=None,
                media_file_unique_id=None,
                media_file_size=None,
                media_filename=None,
                media_type=None
            )
            
            if success:
                await callback.answer("✅ Медиа удалено!", show_alert=True)
                await self._manage_message_media(callback, None, message_id)
            else:
                await callback.answer("❌ Ошибка при удалении медиа", show_alert=True)
                
        except Exception as e:
            logger.error("Failed to delete media", message_id=message_id, error=str(e))
            await callback.answer("Ошибка при удалении медиа", show_alert=True)
    
    async def _manage_message_buttons(self, callback: CallbackQuery, state: FSMContext, message_id: int):
        """Управление кнопками сообщения"""
        try:
            message = await self.db.get_broadcast_message_by_id(message_id)
            if not message:
                await callback.answer("Сообщение не найдено", show_alert=True)
                return
            
            buttons = await self.db.get_message_buttons(message_id)
            
            text = f"""
{Emoji.BUTTON} <b>Кнопки сообщения #{message.message_number}</b>

<b>Текущие кнопки ({len(buttons)}/{settings.max_buttons_per_message}):</b>
"""
            
            if buttons:
                for i, button in enumerate(buttons, 1):
                    text += f"\n{i}. <b>{button.button_text}</b>\n   → {button.button_url[:40]}...\n"
            else:
                text += "\nКнопок пока нет\n"
            
            await callback.message.edit_text(
                text,
                reply_markup=FunnelKeyboards.message_buttons_menu(message_id, buttons)
            )
            
        except Exception as e:
            logger.error("Failed to manage buttons", message_id=message_id, error=str(e))
            await callback.answer("Ошибка при управлении кнопками", show_alert=True)
    
    # ✅ РЕАЛИЗАЦИЯ УПРАВЛЕНИЯ КНОПКАМИ
    async def cb_button_action(self, callback: CallbackQuery, state: FSMContext):
        """Обработка действий с кнопками"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        action_data = callback.data.replace("btn_", "")
        parts = action_data.split("_")
        
        if len(parts) < 2:
            await callback.answer("Неверный формат команды", show_alert=True)
            return
        
        action = parts[0]
        target_id = int(parts[1])
        
        if action == "add":
            # target_id это message_id
            await self._start_button_creation(callback, state, target_id)
        elif action == "edit":
            # target_id это button_id
            await self._start_button_editing(callback, state, target_id)
        elif action == "delete":
            # target_id это button_id
            await self._delete_button(callback, target_id)
    
    async def _start_button_creation(self, callback: CallbackQuery, state: FSMContext, message_id: int):
        """Начать создание кнопки"""
        try:
            await state.set_state(FunnelStates.waiting_for_button_text)
            await state.update_data(message_id=message_id, button_action="add")
            
            text = f"""
🔘 <b>Создание новой кнопки</b>

<b>Шаг 1/2: Текст кнопки</b>

Отправьте текст, который будет отображаться на кнопке.

<b>Примеры:</b>
- "🛒 Купить сейчас"
- "📞 Связаться с нами"
- "🌐 Наш сайт"
- "📱 Скачать приложение"

<b>Отправьте текст кнопки:</b>
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data=f"msg_buttons_{message_id}")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error("Failed to start button creation", message_id=message_id, error=str(e))
            await callback.answer("Ошибка при создании кнопки", show_alert=True)
    
    async def _start_button_editing(self, callback: CallbackQuery, state: FSMContext, button_id: int):
        """Начать редактирование кнопки"""
        try:
            button = await self.db.get_button_by_id(button_id)
            if not button:
                await callback.answer("Кнопка не найдена", show_alert=True)
                return
            
            await state.set_state(FunnelStates.waiting_for_button_text)
            await state.update_data(button_id=button_id, button_action="edit", message_id=button.message_id)
            
            text = f"""
✏️ <b>Редактирование кнопки</b>

<b>Текущие данные:</b>
Текст: <b>{button.button_text}</b>
Ссылка: {button.button_url}

<b>Шаг 1/2: Новый текст кнопки</b>

Отправьте новый текст для кнопки или оставьте текущий, отправив /skip

<b>Отправьте текст кнопки:</b>
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data=f"msg_buttons_{button.message_id}")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error("Failed to start button editing", button_id=button_id, error=str(e))
            await callback.answer("Ошибка при редактировании кнопки", show_alert=True)
    
    async def _delete_button(self, callback: CallbackQuery, button_id: int):
        """Удалить кнопку"""
        try:
            button = await self.db.get_button_by_id(button_id)
            if not button:
                await callback.answer("Кнопка не найдена", show_alert=True)
                return
            
            success = await self.db.delete_message_button(button_id)
            
            if success:
                await callback.answer("✅ Кнопка удалена!", show_alert=True)
                await self._manage_message_buttons(callback, None, button.message_id)
            else:
                await callback.answer("❌ Ошибка при удалении кнопки", show_alert=True)
                
        except Exception as e:
            logger.error("Failed to delete button", button_id=button_id, error=str(e))
            await callback.answer("Ошибка при удалении кнопки", show_alert=True)
    
    async def _duplicate_message(self, callback: CallbackQuery, message_id: int):
        """Дублирование сообщения"""
        try:
            new_message_id = await self.funnel_manager.duplicate_message(message_id, self.bot_id)
            
            if new_message_id:
                await callback.answer("Сообщение продублировано!", show_alert=True)
                await self._show_funnel_messages(callback)
            else:
                await callback.answer("Ошибка при дублировании", show_alert=True)
                
        except Exception as e:
            logger.error("Failed to duplicate message", message_id=message_id, error=str(e))
            await callback.answer("Ошибка при дублировании", show_alert=True)
    
    async def _delete_message_confirm(self, callback: CallbackQuery, message_id: int):
        """Подтверждение удаления сообщения"""
        try:
            message = await self.db.get_broadcast_message_by_id(message_id)
            if not message:
                await callback.answer("Сообщение не найдено", show_alert=True)
                return
            
            text = f"""
{Emoji.WARNING} <b>Подтверждение удаления</b>

Вы действительно хотите удалить сообщение #{message.message_number}?

<b>Текст:</b> {message.message_text[:100]}...

{Emoji.INFO} <b>Это действие нельзя отменить!</b>
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"{Emoji.DELETE} Да, удалить",
                        callback_data=f"confirm_delete_{message_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=f"{Emoji.BACK} Отмена",
                        callback_data=f"msg_view_{message_id}"
                    )
                ]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error("Failed to show delete confirmation", message_id=message_id, error=str(e))
            await callback.answer("Ошибка", show_alert=True)
    
    async def cb_confirm_delete(self, callback: CallbackQuery, state: FSMContext):
        """Подтверждение удаления"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        action_data = callback.data.replace("confirm_delete_", "")
        message_id = int(action_data)
        
        try:
            success = await self.funnel_manager.delete_funnel_message(message_id, self.bot_id)
            
            if success:
                await callback.answer("Сообщение удалено!", show_alert=True)
                await self._show_funnel_messages(callback)
            else:
                await callback.answer("Ошибка при удалении", show_alert=True)
                
        except Exception as e:
            logger.error("Failed to delete message", message_id=message_id, error=str(e))
            await callback.answer("Ошибка при удалении", show_alert=True)
    
    # ✅ ОБРАБОТЧИКИ ВВОДА
    async def handle_funnel_message_text(self, message: Message, state: FSMContext):
        """Обработка текста сообщения воронки"""
        if not self._is_owner(message.from_user.id):
            return
        
        if message.text == "/cancel":
            await self._cancel_and_show_funnel(message, state)
            return
        
        try:
            if len(message.text) > settings.max_funnel_message_length:
                await message.answer(
                    f"{Emoji.WARNING} Текст слишком длинный! "
                    f"Максимум {settings.max_funnel_message_length} символов."
                )
                return
            
            await state.update_data(message_text=message.text)
            await state.set_state(FunnelStates.waiting_for_message_delay)
            
            text = f"""
{Emoji.CLOCK} <b>Задержка отправки</b>

Укажите, через какое время после старта воронки отправить это сообщение.

{Emoji.INFO} <b>Примеры:</b>
- <code>0</code> - сразу
- <code>5</code> или <code>5м</code> - через 5 минут
- <code>2ч</code> или <code>2h</code> - через 2 часа
- <code>1д</code> или <code>1d</code> - через 1 день

<b>Отправьте время задержки:</b>
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"{Emoji.BACK} Отмена",
                        callback_data="funnel_messages"
                    )
                ]
            ])
            
            await message.answer(text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error("Failed to handle message text", error=str(e))
            await message.answer("Ошибка при обработке текста")
            await state.clear()
    
    async def handle_funnel_message_delay(self, message: Message, state: FSMContext):
        """Обработка задержки сообщения"""
        if not self._is_owner(message.from_user.id):
            return
        
        if message.text == "/cancel":
            await self._cancel_and_show_funnel(message, state)
            return
        
        try:
            delay_hours = self.formatter.parse_delay(message.text)
            if delay_hours is None:
                await message.answer(
                    f"{Emoji.WARNING} Неверный формат времени! "
                    f"Используйте: 5м, 2ч, 1д или просто числа (минуты)."
                )
                return
            
            data = await state.get_data()
            message_text = data.get("message_text")
            message_number = data.get("message_number")
            
            # Создаем сообщение
            message_id = await self.funnel_manager.create_funnel_message(
                bot_id=self.bot_id,
                message_number=message_number,
                message_text=message_text,
                delay_hours=delay_hours
            )
            
            if message_id:
                delay_text = self.formatter.format_delay(delay_hours)
                await message.answer(
                    f"{Emoji.SUCCESS} Сообщение #{message_number} создано!\n\n"
                    f"<b>Задержка:</b> {delay_text}\n"
                    f"<b>Текст:</b> {message_text[:100]}...",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(
                            text=f"{Emoji.BACK} К воронке",
                            callback_data="funnel_messages"
                        )]
                    ])
                )
            else:
                await message.answer(f"{Emoji.ERROR} Ошибка при создании сообщения")
            
            await state.clear()
            
        except Exception as e:
            logger.error("Failed to handle message delay", error=str(e))
            await message.answer("Ошибка при сохранении сообщения")
            await state.clear()
    
    async def handle_edit_message_text(self, message: Message, state: FSMContext):
        """Обработка редактирования текста"""
        if not self._is_owner(message.from_user.id):
            return
        
        if message.text == "/cancel":
            await self._cancel_and_show_funnel(message, state)
            return
        
        try:
            if len(message.text) > settings.max_funnel_message_length:
                await message.answer(
                    f"{Emoji.WARNING} Текст слишком длинный! "
                    f"Максимум {settings.max_funnel_message_length} символов."
                )
                return
            
            data = await state.get_data()
            message_id = data.get("message_id")
            
            if not message_id:
                await message.answer("Ошибка: данные сессии потеряны")
                await state.clear()
                return
            
            success = await self.funnel_manager.update_funnel_message(
                message_id=message_id,
                bot_id=self.bot_id,
                message_text=message.text
            )
            
            if success:
                await message.answer(
                    f"✅ <b>Текст сообщения обновлен!</b>\n\n"
                    f"<b>Новый текст:</b> {message.text[:100]}...",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(
                            text=f"{Emoji.BACK} К сообщению",
                            callback_data=f"msg_view_{message_id}"
                        )]
                    ])
                )
            else:
                await message.answer("❌ Ошибка при сохранении изменений")
            
            await state.clear()
            
        except Exception as e:
            logger.error("Failed to handle text editing", error=str(e))
            await message.answer("Ошибка при сохранении текста")
            await state.clear()
    
    async def handle_edit_message_delay(self, message: Message, state: FSMContext):
        """Обработка редактирования задержки"""
        if not self._is_owner(message.from_user.id):
            return
        
        if message.text == "/cancel":
            await self._cancel_and_show_funnel(message, state)
            return
        
        try:
            delay_hours = self.formatter.parse_delay(message.text)
            if delay_hours is None:
                await message.answer(
                    f"{Emoji.WARNING} Неверный формат времени! "
                    f"Используйте: 5м, 2ч, 1д или просто числа (минуты)."
                )
                return
            
            data = await state.get_data()
            message_id = data.get("message_id")
            
            if not message_id:
                await message.answer("Ошибка: данные сессии потеряны")
                await state.clear()
                return
            
            success = await self.funnel_manager.update_funnel_message(
                message_id=message_id,
                bot_id=self.bot_id,
                delay_hours=delay_hours
            )
            
            if success:
                delay_text = self.formatter.format_delay(delay_hours)
                await message.answer(
                    f"✅ <b>Задержка сообщения обновлена!</b>\n\n"
                    f"<b>Новая задержка:</b> {delay_text}",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(
                            text=f"{Emoji.BACK} К сообщению",
                            callback_data=f"msg_view_{message_id}"
                        )]
                    ])
                )
            else:
                await message.answer("❌ Ошибка при сохранении изменений")
            
            await state.clear()
            
        except Exception as e:
            logger.error("Failed to handle delay editing", error=str(e))
            await message.answer("Ошибка при сохранении задержки")
            await state.clear()
    
    async def handle_funnel_button_text(self, message: Message, state: FSMContext):
        """Обработка текста кнопки"""
        if not self._is_owner(message.from_user.id):
            return
        
        if message.text == "/cancel":
            await self._cancel_and_show_funnel(message, state)
            return
        
        try:
            data = await state.get_data()
            button_action = data.get("button_action")
            
            if message.text == "/skip" and button_action == "edit":
                # Пропускаем изменение текста, переходим к URL
                await state.set_state(FunnelStates.waiting_for_button_url)
                
                text = f"""
🔗 <b>Шаг 2/2: Ссылка кнопки</b>

Отправьте новую ссылку для кнопки или /skip чтобы оставить текущую.

<b>Примеры ссылок:</b>
- https://yoursite.com
- https://t.me/yourchannel
- tel:+79001234567
- mailto:info@yoursite.com

<b>Отправьте ссылку:</b>
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="❌ Отмена", callback_data=f"msg_buttons_{data.get('message_id')}")]
                ])
                
                await message.answer(text, reply_markup=keyboard)
                return
            
            if len(message.text) > 64:  # Лимит Telegram для текста кнопки
                await message.answer(
                    f"{Emoji.WARNING} Текст кнопки слишком длинный! "
                    f"Максимум 64 символа."
                )
                return
            
            await state.update_data(button_text=message.text)
            await state.set_state(FunnelStates.waiting_for_button_url)
            
            text = f"""
🔗 <b>Шаг 2/2: Ссылка кнопки</b>

<b>Текст кнопки:</b> {message.text}

Теперь отправьте ссылку, на которую будет вести кнопка.

<b>Примеры ссылок:</b>
- https://yoursite.com
- https://t.me/yourchannel
- tel:+79001234567
- mailto:info@yoursite.com

<b>Отправьте ссылку:</b>
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data=f"msg_buttons_{data.get('message_id')}")]
            ])
            
            await message.answer(text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error("Failed to handle button text", error=str(e))
            await message.answer("Ошибка при обработке текста кнопки")
            await state.clear()
    
    async def handle_funnel_button_url(self, message: Message, state: FSMContext):
        """Обработка URL кнопки"""
        if not self._is_owner(message.from_user.id):
            return
        
        if message.text == "/cancel":
            await self._cancel_and_show_funnel(message, state)
            return
        
        try:
            data = await state.get_data()
            button_action = data.get("button_action")
            message_id = data.get("message_id")
            
            # Проверяем /skip для редактирования
            if message.text == "/skip" and button_action == "edit":
                button_id = data.get("button_id")
                button_text = data.get("button_text")
                
                # Обновляем только текст кнопки
                if button_text:
                    success = await self.db.update_message_button(
                        button_id=button_id,
                        button_text=button_text
                    )
                    
                    if success:
                        await message.answer(
                            "✅ Текст кнопки обновлен!",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(
                                    text=f"{Emoji.BACK} К кнопкам",
                                    callback_data=f"msg_buttons_{message_id}"
                                )]
                            ])
                        )
                    else:
                        await message.answer("❌ Ошибка при сохранении изменений")
                
                await state.clear()
                return
            
            # Базовая валидация URL
            url = message.text.strip()
            if not (url.startswith("http://") or url.startswith("https://") or 
                    url.startswith("tg://") or url.startswith("tel:") or url.startswith("mailto:")):
                await message.answer(
                    f"{Emoji.WARNING} <b>Неверный формат ссылки!</b>\n\n"
                    f"Ссылка должна начинаться с:\n"
                    f"• https://\n"
                    f"• http://\n"
                    f"• tg://\n"
                    f"• tel: (для телефонов)\n"
                    f"• mailto: (для email)\n\n"
                    f"Попробуйте еще раз:"
                )
                return
            
            button_text = data.get("button_text")
            
            if button_action == "add":
                # Создаем новую кнопку
                success = await self.db.create_message_button(
                    message_id=message_id,
                    button_text=button_text,
                    button_url=url
                )
                action_text = "создана"
            else:
                # Редактируем существующую кнопку
                button_id = data.get("button_id")
                success = await self.db.update_message_button(
                    button_id=button_id,
                    button_text=button_text,
                    button_url=url
                )
                action_text = "обновлена"
            
            if success:
                success_text = f"""
✅ <b>Кнопка {action_text}!</b>

<b>Текст:</b> {button_text}
<b>Ссылка:</b> {url}
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text=f"{Emoji.BACK} К кнопкам",
                        callback_data=f"msg_buttons_{message_id}"
                    )]
                ])
                
                await message.answer(success_text, reply_markup=keyboard)
            else:
                await message.answer("❌ Ошибка при сохранении кнопки")
            
            await state.clear()
            
        except Exception as e:
            logger.error("Failed to handle button URL", error=str(e))
            await message.answer("Ошибка при сохранении кнопки")
            await state.clear()
    
    async def handle_media_file_upload(self, message: Message, state: FSMContext):
        """Обработка загрузки медиа"""
        if not self._is_owner(message.from_user.id):
            return
        
        try:
            data = await state.get_data()
            message_id = data.get('message_id')
            
            if not message_id:
                await message.answer("Ошибка: данные сессии потеряны")
                await state.clear()
                return
            
            # Извлекаем информацию о медиа
            media_info = await self.media_extractor.extract_media_info(message)
            if not media_info:
                await message.answer("Неподдерживаемый тип файла")
                return
            
            # Сохраняем file_id
            success = await self.funnel_manager.update_funnel_message(
                message_id=message_id,
                bot_id=self.bot_id,
                media_file_id=media_info.get('file_id'),
                media_file_unique_id=media_info.get('file_unique_id'),
                media_file_size=media_info.get('file_size'),
                media_filename=media_info.get('filename'),
                media_type=media_info.get('media_type')
            )
            
            if success:
                file_size_mb = (media_info.get('file_size', 0) / 1024 / 1024) if media_info.get('file_size') else 0
                
                success_text = f"""
✅ <b>Медиа успешно добавлено!</b>

📁 <b>Тип:</b> {media_info.get('media_type')}
💾 <b>Размер:</b> {file_size_mb:.2f} МБ
📄 <b>Файл:</b> {media_info.get('filename', 'без названия')}
🆔 <b>File ID:</b> Сохранен
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text=f"{Emoji.BACK} К медиа",
                        callback_data=f"msg_media_{message_id}"
                    )]
                ])
                
                await message.answer(success_text, reply_markup=keyboard)
                
            else:
                await message.answer("❌ Ошибка при сохранении медиа")
            
            await state.clear()
            
        except Exception as e:
            logger.error("Failed to handle media upload", error=str(e), exc_info=True)
            await message.answer("❌ Ошибка при обработке медиа файла")
            await state.clear()
