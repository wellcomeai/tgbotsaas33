"""
Обработчики массовых рассылок
✅ ОБНОВЛЕНО: Поддержка форматирования через Telegram entities (html_text)
"""

import structlog
from datetime import datetime, timezone, timedelta
from aiogram import Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from config import Emoji, settings
from ..states import MassBroadcastStates
from ..keyboards import AdminKeyboards
from ..formatters import MediaExtractor
from services.mass_broadcast_service import MassBroadcastService

logger = structlog.get_logger()


def register_mass_broadcast_handlers(dp: Dispatcher, **kwargs):
    """Регистрация обработчиков массовых рассылок"""
    
    db = kwargs['db']
    bot_config = kwargs['bot_config']
    user_bot = kwargs.get('user_bot')
    
    try:
        handler = MassBroadcastHandler(db, bot_config, user_bot)
        
        # Callback обработчики
        dp.callback_query.register(handler.cb_mass_broadcast_main, F.data == "mass_broadcast_main")
        dp.callback_query.register(handler.cb_mass_broadcast_action, F.data.startswith("mass_broadcast_"))
        
        # FSM обработчики
        dp.message.register(handler.handle_instant_text, MassBroadcastStates.instant_waiting_for_text)
        dp.message.register(handler.handle_instant_media, 
                          F.photo | F.video | F.document | F.audio | F.voice | F.video_note,
                          MassBroadcastStates.instant_waiting_for_media)
        dp.message.register(handler.handle_instant_button_text, MassBroadcastStates.instant_waiting_for_button_text)
        dp.message.register(handler.handle_instant_button_url, MassBroadcastStates.instant_waiting_for_button_url)
        
        dp.message.register(handler.handle_scheduled_text, MassBroadcastStates.scheduled_waiting_for_text)
        dp.message.register(handler.handle_scheduled_media,
                          F.photo | F.video | F.document | F.audio | F.voice | F.video_note,
                          MassBroadcastStates.scheduled_waiting_for_media)
        dp.message.register(handler.handle_scheduled_button_text, MassBroadcastStates.scheduled_waiting_for_button_text)
        dp.message.register(handler.handle_scheduled_button_url, MassBroadcastStates.scheduled_waiting_for_button_url)
        dp.message.register(handler.handle_scheduled_datetime, MassBroadcastStates.scheduled_waiting_for_datetime)
        
        logger.info("Mass broadcast handlers registered successfully with entities support", 
                   bot_id=bot_config['bot_id'])
        
    except Exception as e:
        logger.error("Failed to register mass broadcast handlers", 
                    bot_id=kwargs.get('bot_config', {}).get('bot_id', 'unknown'),
                    error=str(e), exc_info=True)
        raise


class MassBroadcastHandler:
    """Обработчик массовых рассылок"""
    
    def __init__(self, db, bot_config: dict, user_bot):
        self.db = db
        self.bot_config = bot_config
        self.bot_id = bot_config['bot_id']
        self.owner_user_id = bot_config['owner_user_id']
        self.bot_username = bot_config['bot_username']
        self.user_bot = user_bot
        self.media_extractor = MediaExtractor()
        self.service = MassBroadcastService(db)
        
        # Временное хранение данных рассылки
        self.temp_broadcasts = {}
    
    def _is_owner(self, user_id: int) -> bool:
        """Проверка владельца"""
        return user_id == self.owner_user_id
    
    def _get_temp_broadcast(self, user_id: int, broadcast_type: str) -> dict:
        """Получить временные данные рассылки"""
        key = f"{user_id}_{broadcast_type}"
        if key not in self.temp_broadcasts:
            self.temp_broadcasts[key] = {
                'message_text': None,
                'media_info': None,
                'button_info': None
            }
        return self.temp_broadcasts[key]
    
    def _clear_temp_broadcast(self, user_id: int, broadcast_type: str):
        """Очистить временные данные рассылки"""
        key = f"{user_id}_{broadcast_type}"
        if key in self.temp_broadcasts:
            del self.temp_broadcasts[key]
    
    async def _safe_edit_message(self, callback: CallbackQuery, text: str, reply_markup=None, parse_mode="HTML"):
        """Безопасное редактирование сообщения с проверкой типа"""
        try:
            # Проверяем, есть ли текст в сообщении
            if callback.message.text:
                await callback.message.edit_text(
                    text=text, 
                    reply_markup=reply_markup, 
                    parse_mode=parse_mode
                )
            elif callback.message.caption is not None:
                # Сообщение содержит медиа с подписью
                await callback.message.edit_caption(
                    caption=text, 
                    reply_markup=reply_markup, 
                    parse_mode=parse_mode
                )
            else:
                # Сообщение содержит медиа без подписи или другой тип
                # Удаляем старое и отправляем новое
                await callback.message.delete()
                await callback.bot.send_message(
                    chat_id=callback.message.chat.id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
        except Exception as e:
            logger.warning(f"Failed to edit message safely, using fallback: {e}")
            try:
                # Fallback: удаляем старое и отправляем новое
                await callback.message.delete()
                await callback.bot.send_message(
                    chat_id=callback.message.chat.id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
            except Exception as fallback_error:
                logger.error(f"Fallback message edit also failed: {fallback_error}")
                # Последний fallback: просто отправляем новое сообщение
                await callback.bot.send_message(
                    chat_id=callback.message.chat.id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
    
    async def cb_mass_broadcast_main(self, callback: CallbackQuery, state: FSMContext):
        """Главное меню массовых рассылок"""
        await callback.answer()
        await state.clear()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        # Получаем статистику
        stats = await self.db.get_mass_broadcast_stats(self.bot_id, days=30)
        
        text = f"""
📨 <b>Массовые рассылки @{self.bot_username}</b>

📊 <b>Статистика за 30 дней:</b>
   Отправлено рассылок: {stats.get('total_broadcasts', 0)}
   Мгновенных: {stats.get('by_type', {}).get('instant', 0)}
   Запланированных: {stats.get('by_type', {}).get('scheduled', 0)}
   
📈 <b>Доставка:</b>
   Успешно доставлено: {stats.get('deliveries', {}).get('successful', 0)}
   Ошибок доставки: {stats.get('deliveries', {}).get('failed', 0)}
   Процент успеха: {stats.get('deliveries', {}).get('success_rate', 0)}%

Выберите тип рассылки:
"""
        
        await self._safe_edit_message(
            callback,
            text,
            reply_markup=AdminKeyboards.mass_broadcast_main_menu()
        )
    
    async def cb_mass_broadcast_action(self, callback: CallbackQuery, state: FSMContext):
        """Обработка действий массовых рассылок"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        action = callback.data.replace("mass_broadcast_", "")
        parts = action.split("_")
        
        if parts[0] == "instant":
            await self._handle_instant_broadcast_action(callback, state, parts[1:])
        elif parts[0] == "scheduled":
            await self._handle_scheduled_broadcast_action(callback, state, parts[1:])
        elif action == "list_scheduled":
            await self._show_scheduled_broadcasts(callback)
        elif action == "stats":
            await self._show_broadcast_stats(callback)
        elif action.startswith("send_instant_"):
            broadcast_id = int(action.split("_")[-1])
            await self._send_instant_broadcast(callback, broadcast_id)
        elif action.startswith("confirm_send_"):
            broadcast_id = int(action.split("_")[-1])
            await self._confirm_send_broadcast(callback, broadcast_id)
        elif action.startswith("cancel_"):
            broadcast_id = int(action.split("_")[-1])
            await self._cancel_scheduled_broadcast(callback, broadcast_id)
    
    async def _handle_instant_broadcast_action(self, callback: CallbackQuery, state: FSMContext, parts: list):
        """Обработка действий мгновенной рассылки"""
        if not parts:
            await self._show_instant_creation_menu(callback, state)
            return
        
        action = parts[0]
        
        if action == "text":
            await self._request_instant_text(callback, state)
        elif action == "media":
            await self._request_instant_media(callback, state)
        elif action == "button":
            await self._request_instant_button(callback, state)
        elif action == "preview":
            await self._show_instant_preview(callback, state)
        elif action == "send":
            await self._prepare_instant_send(callback, state)
        elif action == "menu":
            await self._show_instant_creation_menu(callback, state)
    
    async def _handle_scheduled_broadcast_action(self, callback: CallbackQuery, state: FSMContext, parts: list):
        """Обработка действий запланированной рассылки"""
        if not parts:
            await self._show_scheduled_creation_menu(callback, state)
            return
        
        action = parts[0]
        
        if action == "text":
            await self._request_scheduled_text(callback, state)
        elif action == "media":
            await self._request_scheduled_media(callback, state)
        elif action == "button":
            await self._request_scheduled_button(callback, state)
        elif action == "preview":
            await self._show_scheduled_preview(callback, state)
        elif action == "datetime":
            await self._request_scheduled_datetime(callback, state)
        elif action == "menu":
            await self._show_scheduled_creation_menu(callback, state)
    
    # ===== МГНОВЕННАЯ РАССЫЛКА =====
    
    async def _show_instant_creation_menu(self, callback: CallbackQuery, state: FSMContext):
        """Показать меню создания мгновенной рассылки"""
        temp_data = self._get_temp_broadcast(callback.from_user.id, "instant")
        
        text = f"""
🚀 <b>Мгновенная рассылка</b>

Настройте параметры рассылки:

📝 <b>Текст:</b> {'✅ Готов' if temp_data['message_text'] else '❌ Не задан'}
📎 <b>Медиа:</b> {'✅ Прикреплено' if temp_data['media_info'] else '⚪ Не добавлено'}
🔘 <b>Кнопка:</b> {'✅ Настроена' if temp_data['button_info'] else '⚪ Не добавлена'}

{Emoji.INFO} <b>Рассылка будет отправлена сразу всем активным подписчикам бота.</b>
"""
        
        await self._safe_edit_message(
            callback,
            text,
            reply_markup=AdminKeyboards.mass_broadcast_creation_menu(
                "instant",
                has_text=bool(temp_data['message_text']),
                has_media=bool(temp_data['media_info']),
                has_button=bool(temp_data['button_info'])
            )
        )
    
    async def _request_instant_text(self, callback: CallbackQuery, state: FSMContext):
        """✅ ОБНОВЛЕНО: Запросить текст мгновенной рассылки с подсказкой о форматировании"""
        await state.set_state(MassBroadcastStates.instant_waiting_for_text)
        
        text = f"""
📝 <b>Текст мгновенной рассылки</b>

Отправьте текст, который получат все подписчики бота.

{Emoji.INFO} <b>Доступные переменные:</b>
- <code>{{first_name}}</code> - имя пользователя

<b>💡 Форматирование:</b>
Используйте кнопки Telegram для форматирования:
- <b>Жирный</b> (Ctrl+B / ⌘+B)
- <i>Курсив</i> (Ctrl+I / ⌘+I)
- <code>Моноширинный</code>
- <s>Зачеркнутый</s>

{Emoji.WARNING} <b>Лимиты:</b>
- Максимум {settings.max_funnel_message_length} символов
- Поддерживается HTML-разметка

<b>Отправьте текст рассылки:</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="mass_broadcast_instant_menu")]
        ])
        
        await self._safe_edit_message(callback, text, reply_markup=keyboard)
    
    async def handle_instant_text(self, message: Message, state: FSMContext):
        """✅ ОБНОВЛЕНО: Обработка текста мгновенной рассылки с поддержкой форматирования"""
        if not self._is_owner(message.from_user.id):
            return
        
        if len(message.text) > settings.max_funnel_message_length:
            await message.answer(
                f"{Emoji.WARNING} Текст слишком длинный! "
                f"Максимум {settings.max_funnel_message_length} символов."
            )
            return
        
        # ✅ КЛЮЧЕВОЕ ИЗМЕНЕНИЕ: Используем html_text для сохранения форматирования
        formatted_text = message.html_text if message.html_text else message.text
        
        # Сохраняем текст
        temp_data = self._get_temp_broadcast(message.from_user.id, "instant")
        temp_data['message_text'] = formatted_text
        
        await message.answer(
            f"✅ <b>Текст рассылки сохранен!</b>\n\n"
            f"<b>Текст (с форматированием):</b>\n{formatted_text[:100]}{'...' if len(formatted_text) > 100 else ''}\n\n"
            f"💡 <i>Форматирование сохранено и будет отображаться у пользователей!</i>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ К настройке", callback_data="mass_broadcast_instant_menu")]
            ])
        )
        
        logger.info("Instant broadcast text saved with formatting",
                   bot_id=self.bot_id,
                   has_html=bool(message.html_text))
        
        await state.clear()
    
    async def _request_instant_media(self, callback: CallbackQuery, state: FSMContext):
        """Запросить медиа для мгновенной рассылки"""
        temp_data = self._get_temp_broadcast(callback.from_user.id, "instant")
        
        if temp_data['media_info']:
            # Уже есть медиа, показываем меню
            text = f"""
📎 <b>Медиа для рассылки</b>

<b>Текущее медиа:</b>
Тип: {temp_data['media_info']['media_type']}
Файл: {temp_data['media_info'].get('filename', 'без названия')}

Вы можете заменить медиа или убрать его.
"""
            
            await self._safe_edit_message(
                callback,
                text,
                reply_markup=AdminKeyboards.mass_broadcast_media_setup_menu("instant")
            )
        else:
            # Запрашиваем медиа
            await state.set_state(MassBroadcastStates.instant_waiting_for_media)
            
            text = """
📎 <b>Медиа для рассылки</b>

Отправьте медиа файл, который будет прикреплен к рассылке.

<b>Поддерживаемые типы:</b>
📸 Фото
🎥 Видео
📎 Документы
🎵 Аудио
🎤 Голосовые сообщения
⭕ Видеокружки

<b>Отправьте медиа файл:</b>
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отменить", callback_data="mass_broadcast_instant_menu")]
            ])
            
            await self._safe_edit_message(callback, text, reply_markup=keyboard)
    
    async def handle_instant_media(self, message: Message, state: FSMContext):
        """Обработка медиа мгновенной рассылки"""
        if not self._is_owner(message.from_user.id):
            return
        
        media_info = await self.media_extractor.extract_media_info(message)
        if not media_info:
            await message.answer("❌ Неподдерживаемый тип файла")
            return
        
        # Сохраняем медиа
        temp_data = self._get_temp_broadcast(message.from_user.id, "instant")
        temp_data['media_info'] = media_info
        
        file_size_mb = (media_info.get('file_size', 0) / 1024 / 1024) if media_info.get('file_size') else 0
        
        await message.answer(
            f"✅ <b>Медиа добавлено!</b>\n\n"
            f"<b>Тип:</b> {media_info['media_type']}\n"
            f"<b>Размер:</b> {file_size_mb:.2f} МБ\n"
            f"<b>Файл:</b> {media_info.get('filename', 'без названия')}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ К настройке", callback_data="mass_broadcast_instant_menu")]
            ])
        )
        
        await state.clear()

    async def _request_instant_button(self, callback: CallbackQuery, state: FSMContext):
        """Запросить настройку кнопки для мгновенной рассылки"""
        temp_data = self._get_temp_broadcast(callback.from_user.id, "instant")
        
        if temp_data['button_info']:
            # Уже есть кнопка, показываем меню
            button_info = temp_data['button_info']
            text = f"""
🔘 <b>Кнопка для рассылки</b>

<b>Текущая кнопка:</b>
Текст: {button_info.get('text', 'Не задан')}
URL: {button_info.get('url', 'Не задан')}

Вы можете изменить кнопку или убрать её.
"""
            
            await self._safe_edit_message(
                callback,
                text,
                reply_markup=AdminKeyboards.mass_broadcast_button_setup_menu("instant")
            )
        else:
            # Запрашиваем текст кнопки
            await state.set_state(MassBroadcastStates.instant_waiting_for_button_text)
            
            text = """
🔘 <b>Inline кнопка для рассылки</b>

Отправьте текст, который будет отображаться на кнопке.

<b>Примеры:</b>
- "Подробнее"
- "Перейти на сайт"
- "Связаться с нами"

<b>Отправьте текст кнопки:</b>
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отменить", callback_data="mass_broadcast_instant_menu")]
            ])
            
            await self._safe_edit_message(callback, text, reply_markup=keyboard)

    async def handle_instant_button_text(self, message: Message, state: FSMContext):
        """Обработка текста кнопки мгновенной рассылки"""
        if not self._is_owner(message.from_user.id):
            return
        
        if len(message.text) > 64:  # Лимит Telegram для текста кнопки
            await message.answer(
                f"{Emoji.WARNING} Текст кнопки слишком длинный! "
                f"Максимум 64 символа."
            )
            return
        
        # Сохраняем текст кнопки и запрашиваем URL
        temp_data = self._get_temp_broadcast(message.from_user.id, "instant")
        if not temp_data['button_info']:
            temp_data['button_info'] = {}
        temp_data['button_info']['text'] = message.text
        
        await state.set_state(MassBroadcastStates.instant_waiting_for_button_url)
        
        text = f"""
🔗 <b>URL для кнопки</b>

Отправьте ссылку, на которую будет вести кнопка "{message.text}".

<b>Требования:</b>
- Ссылка должна начинаться с http:// или https://
- Максимум 1024 символа

<b>Отправьте URL:</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="mass_broadcast_instant_menu")]
        ])
        
        await message.answer(text, reply_markup=keyboard)

    async def handle_instant_button_url(self, message: Message, state: FSMContext):
        """Обработка URL кнопки мгновенной рассылки"""
        if not self._is_owner(message.from_user.id):
            return
        
        url = message.text.strip()
        
        # Проверяем URL
        if not (url.startswith('http://') or url.startswith('https://')):
            await message.answer(
                f"{Emoji.WARNING} URL должен начинаться с http:// или https://"
            )
            return
        
        if len(url) > 1024:
            await message.answer(
                f"{Emoji.WARNING} URL слишком длинный! Максимум 1024 символа."
            )
            return
        
        # Сохраняем URL кнопки
        temp_data = self._get_temp_broadcast(message.from_user.id, "instant")
        temp_data['button_info']['url'] = url
        
        button_text = temp_data['button_info']['text']
        
        await message.answer(
            f"✅ <b>Кнопка настроена!</b>\n\n"
            f"<b>Текст:</b> {button_text}\n"
            f"<b>URL:</b> {url}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ К настройке", callback_data="mass_broadcast_instant_menu")]
            ])
        )
        
        await state.clear()
    
    async def _show_instant_preview(self, callback: CallbackQuery, state: FSMContext):
        """Показать предпросмотр мгновенной рассылки"""
        temp_data = self._get_temp_broadcast(callback.from_user.id, "instant")
        
        if not temp_data['message_text']:
            await callback.answer("❌ Сначала добавьте текст рассылки", show_alert=True)
            return
        
        # Создаем рассылку в статусе draft
        broadcast = await self.service.create_instant_broadcast(
            bot_id=self.bot_id,
            admin_user_id=callback.from_user.id,
            message_text=temp_data['message_text'],
            media_info=temp_data['media_info'],
            button_info=temp_data['button_info']
        )
        
        if not broadcast:
            await callback.answer("❌ Ошибка при создании рассылки", show_alert=True)
            return
        
        # Показываем предпросмотр
        preview = await self.service.format_broadcast_for_preview(broadcast.id)
        
        text = f"""
👁️ <b>Предпросмотр мгновенной рассылки</b>

<b>Получатели:</b> все активные подписчики
<b>Отправка:</b> сразу после подтверждения

--- <b>Сообщение:</b> ---
{preview['text']}
--- <b>Конец сообщения</b> ---
"""
        
        keyboard = AdminKeyboards.mass_broadcast_preview_menu("instant", broadcast.id)
        
        # Отправляем с медиа если есть
        if preview['has_media'] and preview['media_file_id']:
            try:
                if preview['media_type'] == 'photo':
                    await callback.message.delete()
                    await callback.bot.send_photo(
                        chat_id=callback.message.chat.id,
                        photo=preview['media_file_id'],
                        caption=text,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                # Аналогично для других типов медиа...
                else:
                    await self._safe_edit_message(callback, text, reply_markup=keyboard)
            except:
                await self._safe_edit_message(callback, text, reply_markup=keyboard)
        else:
            await self._safe_edit_message(callback, text, reply_markup=keyboard)
        
        # Очищаем временные данные
        self._clear_temp_broadcast(callback.from_user.id, "instant")
    
    async def _send_instant_broadcast(self, callback: CallbackQuery, broadcast_id: int):
        """Отправить мгновенную рассылку"""
        # Показываем подтверждение
        broadcast = await self.db.get_mass_broadcast_by_id(broadcast_id)
        if not broadcast:
            await callback.answer("❌ Рассылка не найдена", show_alert=True)
            return
        
        text = f"""
⚠️ <b>Подтверждение отправки</b>

Вы действительно хотите отправить рассылку всем активным подписчикам?

<b>Текст:</b> {broadcast.get_preview_text(100)}
<b>Медиа:</b> {'Да' if broadcast.has_media() else 'Нет'}
<b>Кнопка:</b> {'Да' if broadcast.has_button() else 'Нет'}

{Emoji.WARNING} <b>Это действие нельзя отменить!</b>
"""
        
        await self._safe_edit_message(
            callback,
            text,
            reply_markup=AdminKeyboards.mass_broadcast_confirm_send(broadcast_id)
        )
    
    async def _confirm_send_broadcast(self, callback: CallbackQuery, broadcast_id: int):
        """Подтвердить отправку рассылки"""
        success = await self.service.send_instant_broadcast(broadcast_id)
        
        if success:
            await callback.answer("✅ Рассылка запущена! Отправка началась.", show_alert=True)
            
            text = """
🚀 <b>Рассылка запущена!</b>

Сообщения отправляются всем активным подписчикам.
Процесс может занять несколько минут.

Следите за статистикой в разделе "📊 Статистика рассылок".
"""
            
            await self._safe_edit_message(
                callback,
                text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📊 Статистика", callback_data="mass_broadcast_stats")],
                    [InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_main")]
                ])
            )
        else:
            await callback.answer("❌ Ошибка при запуске рассылки", show_alert=True)
    
    async def _prepare_instant_send(self, callback: CallbackQuery, state: FSMContext):
        """Подготовить отправку мгновенной рассылки"""
        temp_data = self._get_temp_broadcast(callback.from_user.id, "instant")
        
        if not temp_data['message_text']:
            await callback.answer("❌ Сначала добавьте текст рассылки", show_alert=True)
            return
        
        await self._show_instant_preview(callback, state)
    
    # ===== ЗАПЛАНИРОВАННЫЕ РАССЫЛКИ =====

    async def _show_scheduled_creation_menu(self, callback: CallbackQuery, state: FSMContext):
        """Показать меню создания запланированной рассылки"""
        temp_data = self._get_temp_broadcast(callback.from_user.id, "scheduled")
        
        text = f"""
⏰ <b>Запланированная рассылка</b>

Настройте параметры рассылки:

📝 <b>Текст:</b> {'✅ Готов' if temp_data['message_text'] else '❌ Не задан'}
📎 <b>Медиа:</b> {'✅ Прикреплено' if temp_data['media_info'] else '⚪ Не добавлено'}
🔘 <b>Кнопка:</b> {'✅ Настроена' if temp_data['button_info'] else '⚪ Не добавлена'}

{Emoji.INFO} <b>После настройки параметров вы сможете указать время отправки.</b>
"""
        
        await self._safe_edit_message(
            callback,
            text,
            reply_markup=AdminKeyboards.mass_broadcast_creation_menu(
                "scheduled",
                has_text=bool(temp_data['message_text']),
                has_media=bool(temp_data['media_info']),
                has_button=bool(temp_data['button_info'])
            )
        )

    async def _request_scheduled_text(self, callback: CallbackQuery, state: FSMContext):
        """✅ ОБНОВЛЕНО: Запросить текст запланированной рассылки с подсказкой о форматировании"""
        await state.set_state(MassBroadcastStates.scheduled_waiting_for_text)
        
        text = f"""
📝 <b>Текст запланированной рассылки</b>

Отправьте текст, который получат все подписчики бота в указанное время.

{Emoji.INFO} <b>Доступные переменные:</b>
- <code>{{first_name}}</code> - имя пользователя

<b>💡 Форматирование:</b>
Используйте кнопки Telegram для форматирования:
- <b>Жирный</b> (Ctrl+B / ⌘+B)
- <i>Курсив</i> (Ctrl+I / ⌘+I)
- <code>Моноширинный</code>
- <s>Зачеркнутый</s>

{Emoji.WARNING} <b>Лимиты:</b>
- Максимум {settings.max_funnel_message_length} символов
- Поддерживается HTML-разметка

<b>Отправьте текст рассылки:</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="mass_broadcast_scheduled_menu")]
        ])
        
        await self._safe_edit_message(callback, text, reply_markup=keyboard)

    async def handle_scheduled_text(self, message: Message, state: FSMContext):
        """✅ ОБНОВЛЕНО: Обработка текста запланированной рассылки с поддержкой форматирования"""
        if not self._is_owner(message.from_user.id):
            return
        
        if len(message.text) > settings.max_funnel_message_length:
            await message.answer(
                f"{Emoji.WARNING} Текст слишком длинный! "
                f"Максимум {settings.max_funnel_message_length} символов."
            )
            return
        
        # ✅ КЛЮЧЕВОЕ ИЗМЕНЕНИЕ: Используем html_text для сохранения форматирования
        formatted_text = message.html_text if message.html_text else message.text
        
        # Сохраняем текст
        temp_data = self._get_temp_broadcast(message.from_user.id, "scheduled")
        temp_data['message_text'] = formatted_text
        
        await message.answer(
            f"✅ <b>Текст рассылки сохранен!</b>\n\n"
            f"<b>Текст (с форматированием):</b>\n{formatted_text[:100]}{'...' if len(formatted_text) > 100 else ''}\n\n"
            f"💡 <i>Форматирование сохранено и будет отображаться у пользователей!</i>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ К настройке", callback_data="mass_broadcast_scheduled_menu")]
            ])
        )
        
        logger.info("Scheduled broadcast text saved with formatting",
                   bot_id=self.bot_id,
                   has_html=bool(message.html_text))
        
        await state.clear()

    async def _request_scheduled_media(self, callback: CallbackQuery, state: FSMContext):
        """Запросить медиа для запланированной рассылки"""
        temp_data = self._get_temp_broadcast(callback.from_user.id, "scheduled")
        
        if temp_data['media_info']:
            # Уже есть медиа, показываем меню
            text = f"""
📎 <b>Медиа для рассылки</b>

<b>Текущее медиа:</b>
Тип: {temp_data['media_info']['media_type']}
Файл: {temp_data['media_info'].get('filename', 'без названия')}

Вы можете заменить медиа или убрать его.
"""
            
            await self._safe_edit_message(
                callback,
                text,
                reply_markup=AdminKeyboards.mass_broadcast_media_setup_menu("scheduled")
            )
        else:
            # Запрашиваем медиа
            await state.set_state(MassBroadcastStates.scheduled_waiting_for_media)
            
            text = """
📎 <b>Медиа для рассылки</b>

Отправьте медиа файл, который будет прикреплен к рассылке.

<b>Поддерживаемые типы:</b>
📸 Фото
🎥 Видео
📎 Документы
🎵 Аудио
🎤 Голосовые сообщения
⭕ Видеокружки

<b>Отправьте медиа файл:</b>
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отменить", callback_data="mass_broadcast_scheduled_menu")]
            ])
            
            await self._safe_edit_message(callback, text, reply_markup=keyboard)

    async def handle_scheduled_media(self, message: Message, state: FSMContext):
        """Обработка медиа запланированной рассылки"""
        if not self._is_owner(message.from_user.id):
            return
        
        media_info = await self.media_extractor.extract_media_info(message)
        if not media_info:
            await message.answer("❌ Неподдерживаемый тип файла")
            return
        
        # Сохраняем медиа
        temp_data = self._get_temp_broadcast(message.from_user.id, "scheduled")
        temp_data['media_info'] = media_info
        
        file_size_mb = (media_info.get('file_size', 0) / 1024 / 1024) if media_info.get('file_size') else 0
        
        await message.answer(
            f"✅ <b>Медиа добавлено!</b>\n\n"
            f"<b>Тип:</b> {media_info['media_type']}\n"
            f"<b>Размер:</b> {file_size_mb:.2f} МБ\n"
            f"<b>Файл:</b> {media_info.get('filename', 'без названия')}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ К настройке", callback_data="mass_broadcast_scheduled_menu")]
            ])
        )
        
        await state.clear()

    async def _request_scheduled_button(self, callback: CallbackQuery, state: FSMContext):
        """Запросить настройку кнопки для запланированной рассылки"""
        temp_data = self._get_temp_broadcast(callback.from_user.id, "scheduled")
        
        if temp_data['button_info']:
            # Уже есть кнопка, показываем меню
            button_info = temp_data['button_info']
            text = f"""
🔘 <b>Кнопка для рассылки</b>

<b>Текущая кнопка:</b>
Текст: {button_info.get('text', 'Не задан')}
URL: {button_info.get('url', 'Не задан')}

Вы можете изменить кнопку или убрать её.
"""
            
            await self._safe_edit_message(
                callback,
                text,
                reply_markup=AdminKeyboards.mass_broadcast_button_setup_menu("scheduled")
            )
        else:
            # Запрашиваем текст кнопки
            await state.set_state(MassBroadcastStates.scheduled_waiting_for_button_text)
            
            text = """
🔘 <b>Inline кнопка для рассылки</b>

Отправьте текст, который будет отображаться на кнопке.

<b>Примеры:</b>
- "Подробнее"
- "Перейти на сайт"  
- "Связаться с нами"

<b>Отправьте текст кнопки:</b>
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отменить", callback_data="mass_broadcast_scheduled_menu")]
            ])
            
            await self._safe_edit_message(callback, text, reply_markup=keyboard)

    async def handle_scheduled_button_text(self, message: Message, state: FSMContext):
        """Обработка текста кнопки запланированной рассылки"""
        if not self._is_owner(message.from_user.id):
            return
        
        if len(message.text) > 64:  # Лимит Telegram для текста кнопки
            await message.answer(
                f"{Emoji.WARNING} Текст кнопки слишком длинный! "
                f"Максимум 64 символа."
            )
            return
        
        # Сохраняем текст кнопки и запрашиваем URL
        temp_data = self._get_temp_broadcast(message.from_user.id, "scheduled")
        if not temp_data['button_info']:
            temp_data['button_info'] = {}
        temp_data['button_info']['text'] = message.text
        
        await state.set_state(MassBroadcastStates.scheduled_waiting_for_button_url)
        
        text = f"""
🔗 <b>URL для кнопки</b>

Отправьте ссылку, на которую будет вести кнопка "{message.text}".

<b>Требования:</b>
- Ссылка должна начинаться с http:// или https://
- Максимум 1024 символа

<b>Отправьте URL:</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="mass_broadcast_scheduled_menu")]
        ])
        
        await message.answer(text, reply_markup=keyboard)

    async def handle_scheduled_button_url(self, message: Message, state: FSMContext):
        """Обработка URL кнопки запланированной рассылки"""
        if not self._is_owner(message.from_user.id):
            return
        
        url = message.text.strip()
        
        # Проверяем URL
        if not (url.startswith('http://') or url.startswith('https://')):
            await message.answer(
                f"{Emoji.WARNING} URL должен начинаться с http:// или https://"
            )
            return
        
        if len(url) > 1024:
            await message.answer(
                f"{Emoji.WARNING} URL слишком длинный! Максимум 1024 символа."
            )
            return
        
        # Сохраняем URL кнопки
        temp_data = self._get_temp_broadcast(message.from_user.id, "scheduled")
        temp_data['button_info']['url'] = url
        
        button_text = temp_data['button_info']['text']
        
        await message.answer(
            f"✅ <b>Кнопка настроена!</b>\n\n"
            f"<b>Текст:</b> {button_text}\n"
            f"<b>URL:</b> {url}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ К настройке", callback_data="mass_broadcast_scheduled_menu")]
            ])
        )
        
        await state.clear()

    async def _request_scheduled_datetime(self, callback: CallbackQuery, state: FSMContext):
        """Запросить дату и время отправки запланированной рассылки"""
        temp_data = self._get_temp_broadcast(callback.from_user.id, "scheduled")
        
        if not temp_data['message_text']:
            await callback.answer("❌ Сначала добавьте текст рассылки", show_alert=True)
            return
        
        await state.set_state(MassBroadcastStates.scheduled_waiting_for_datetime)
        
        text = """
⏰ <b>Время отправки рассылки</b>

Укажите дату и время отправки в формате:
<code>ДД.ММ.ГГГГ ЧЧ:ММ</code>

<b>Примеры:</b>
- <code>25.12.2025 15:30</code>
- <code>01.01.2026 00:00</code>

<b>Требования:</b>
- Время должно быть в будущем
- Минимум через 5 минут от текущего времени

<b>Отправьте дату и время:</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="mass_broadcast_scheduled_menu")]
        ])
        
        await self._safe_edit_message(callback, text, reply_markup=keyboard)

    async def handle_scheduled_datetime(self, message: Message, state: FSMContext):
        """Обработка даты и времени запланированной рассылки"""
        if not self._is_owner(message.from_user.id):
            return
        
        try:
            # Парсим дату и время
            dt_str = message.text.strip()
            scheduled_dt = datetime.strptime(dt_str, "%d.%m.%Y %H:%M")
            
            # Добавляем timezone (предполагаем UTC)
            scheduled_dt = scheduled_dt.replace(tzinfo=timezone.utc)
            
            # Проверяем, что время в будущем
            now = datetime.now(timezone.utc)
            if scheduled_dt <= now + timedelta(minutes=5):
                await message.answer(
                    f"{Emoji.WARNING} Время отправки должно быть минимум через 5 минут от текущего времени."
                )
                return
            
            # Сохраняем рассылку в БД
            temp_data = self._get_temp_broadcast(message.from_user.id, "scheduled")
            
            broadcast = await self.service.create_scheduled_broadcast(
                bot_id=self.bot_id,
                admin_user_id=message.from_user.id,
                message_text=temp_data['message_text'],
                media_info=temp_data['media_info'],
                button_info=temp_data['button_info'],
                scheduled_at=scheduled_dt
            )
            
            if broadcast:
                # Очищаем временные данные
                self._clear_temp_broadcast(message.from_user.id, "scheduled")
                
                formatted_time = scheduled_dt.strftime("%d.%m.%Y в %H:%M")
                
                await message.answer(
                    f"✅ <b>Рассылка запланирована!</b>\n\n"
                    f"<b>Время отправки:</b> {formatted_time} UTC\n"
                    f"<b>Текст:</b> {temp_data['message_text'][:100]}{'...' if len(temp_data['message_text']) > 100 else ''}\n\n"
                    f"Рассылка будет автоматически отправлена в указанное время.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📋 Запланированные рассылки", callback_data="mass_broadcast_list_scheduled")],
                        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_main")]
                    ])
                )
            else:
                await message.answer("❌ Ошибка при сохранении рассылки")
            
        except ValueError:
            await message.answer(
                f"{Emoji.WARNING} Неправильный формат даты и времени!\n"
                f"Используйте формат: <code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n"
                f"Например: <code>25.12.2025 15:30</code>"
            )
            return
        except Exception as e:
            logger.error("Error processing scheduled datetime", error=str(e), exc_info=True)
            await message.answer("❌ Ошибка при обработке даты и времени")
            return
        
        await state.clear()

    async def _show_scheduled_preview(self, callback: CallbackQuery, state: FSMContext):
        """Показать предпросмотр запланированной рассылки"""
        temp_data = self._get_temp_broadcast(callback.from_user.id, "scheduled")
        
        if not temp_data['message_text']:
            await callback.answer("❌ Сначала добавьте текст рассылки", show_alert=True)
            return
        
        preview_text = f"""
👁️ <b>Предпросмотр запланированной рассылки</b>

<b>Получатели:</b> все активные подписчики
<b>Отправка:</b> в указанное время

--- <b>Сообщение:</b> ---
{temp_data['message_text']}
--- <b>Конец сообщения</b> ---

<b>Медиа:</b> {'Да' if temp_data['media_info'] else 'Нет'}
<b>Кнопка:</b> {'Да' if temp_data['button_info'] else 'Нет'}
"""
        
        if temp_data['button_info']:
            preview_text += f"\n<b>Кнопка:</b> {temp_data['button_info']['text']} → {temp_data['button_info']['url']}"
        
        keyboard = AdminKeyboards.mass_broadcast_preview_menu("scheduled")
        
        await self._safe_edit_message(callback, preview_text, reply_markup=keyboard)
    
    # ===== СПИСОК ЗАПЛАНИРОВАННЫХ РАССЫЛОК =====
    
    async def _show_scheduled_broadcasts(self, callback: CallbackQuery):
        """Показать список запланированных рассылок"""
        broadcasts = await self.db.get_pending_scheduled_mass_broadcasts(self.bot_id)
        
        if not broadcasts:
            text = """
📋 <b>Запланированные рассылки</b>

❌ <b>Нет запланированных рассылок</b>

Вы можете создать новую запланированную рассылку.
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏰ Создать рассылку", callback_data="mass_broadcast_scheduled")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="mass_broadcast_main")]
            ])
            
        else:
            text = f"""
📋 <b>Запланированные рассылки ({len(broadcasts)})</b>

Нажмите на рассылку для просмотра:
"""
            keyboard = AdminKeyboards.mass_broadcast_scheduled_list(broadcasts)
        
        await self._safe_edit_message(callback, text, reply_markup=keyboard)
    
    # ===== СТАТИСТИКА =====
    
    async def _show_broadcast_stats(self, callback: CallbackQuery):
        """Показать статистику рассылок"""
        stats = await self.db.get_mass_broadcast_stats(self.bot_id)
        
        text = f"""
📊 <b>Статистика рассылок за 30 дней</b>

📨 <b>Общая статистика:</b>
   Всего рассылок: {stats.get('total_broadcasts', 0)}
   Мгновенных: {stats.get('by_status', {}).get('instant', 0)}
   Запланированных: {stats.get('by_status', {}).get('scheduled', 0)}

📈 <b>По статусам:</b>
   Завершено: {stats.get('by_status', {}).get('completed', 0)}
   В процессе: {stats.get('by_status', {}).get('sending', 0)}
   Черновики: {stats.get('by_status', {}).get('draft', 0)}

🎯 <b>Доставка сообщений:</b>
   Успешно: {stats.get('deliveries', {}).get('successful', 0)}
   Ошибок: {stats.get('deliveries', {}).get('failed', 0)}
   Процент успеха: {stats.get('deliveries', {}).get('success_rate', 0)}%

{Emoji.INFO} <i>Статистика обновляется в реальном времени</i>
"""
        
        await self._safe_edit_message(
            callback,
            text,
            reply_markup=AdminKeyboards.mass_broadcast_stats_menu()
        )

    # ===== ДОПОЛНИТЕЛЬНЫЕ МЕТОДЫ =====

    async def _cancel_scheduled_broadcast(self, callback: CallbackQuery, broadcast_id: int):
        """Отменить запланированную рассылку"""
        success = await self.service.cancel_scheduled_broadcast(broadcast_id, self.bot_id)
        
        if success:
            await callback.answer("✅ Рассылка отменена", show_alert=True)
            
            text = """
🗑️ <b>Рассылка отменена</b>

Запланированная рассылка была успешно отменена и удалена.
"""
            
            await self._safe_edit_message(
                callback,
                text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📋 Запланированные рассылки", callback_data="mass_broadcast_list_scheduled")],
                    [InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_main")]
                ])
            )
        else:
            await callback.answer("❌ Ошибка при отмене рассылки", show_alert=True)
