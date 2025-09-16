"""
Обработчики настроек сообщений
"""

import structlog
from aiogram import Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from config import Emoji
from ..states import BotSettingsStates
from ..formatters import MessageFormatter

logger = structlog.get_logger()


def register_settings_handlers(dp: Dispatcher, **kwargs):
    """Регистрация обработчиков настроек"""
    
    db = kwargs['db']
    bot_config = kwargs['bot_config']  # ИЗМЕНЕНО: получаем полную конфигурацию
    user_bot = kwargs.get('user_bot')  # Получаем ссылку на UserBot
    
    try:
        handler = SettingsHandler(db, bot_config, user_bot)
        
        # Callback обработчики
        dp.callback_query.register(handler.cb_settings_action, F.data.startswith("settings_"))
        
        # Обработчики ввода
        dp.message.register(
            handler.handle_welcome_message_input,
            BotSettingsStates.waiting_for_welcome_message
        )
        dp.message.register(
            handler.handle_welcome_button_input,
            BotSettingsStates.waiting_for_welcome_button
        )
        dp.message.register(
            handler.handle_confirmation_message_input,
            BotSettingsStates.waiting_for_confirmation_message
        )
        dp.message.register(
            handler.handle_goodbye_message_input,
            BotSettingsStates.waiting_for_goodbye_message
        )
        dp.message.register(
            handler.handle_goodbye_button_text_input,
            BotSettingsStates.waiting_for_goodbye_button_text
        )
        dp.message.register(
            handler.handle_goodbye_button_url_input,
            BotSettingsStates.waiting_for_goodbye_button_url
        )
        
        logger.info("Settings handlers registered successfully", 
                   bot_id=bot_config['bot_id'])
        
    except Exception as e:
        logger.error("Failed to register settings handlers", 
                    bot_id=kwargs.get('bot_config', {}).get('bot_id', 'unknown'),
                    error=str(e), exc_info=True)
        raise


class SettingsHandler:
    """Обработчик настроек сообщений"""
    
    def __init__(self, db, bot_config: dict, user_bot):
        self.db = db
        self.bot_config = bot_config
        self.bot_id = bot_config['bot_id']
        self.owner_user_id = bot_config['owner_user_id']
        self.formatter = MessageFormatter()
        self.user_bot = user_bot  # Сохраняем ссылку на UserBot
        
        # Получаем текущие настройки из конфигурации
        self.welcome_message = bot_config.get('welcome_message')
        self.welcome_button_text = bot_config.get('welcome_button_text')
        self.confirmation_message = bot_config.get('confirmation_message')
        self.goodbye_message = bot_config.get('goodbye_message')
        self.goodbye_button_text = bot_config.get('goodbye_button_text')
        self.goodbye_button_url = bot_config.get('goodbye_button_url')
    
    def _is_owner(self, user_id: int) -> bool:
        """Проверка владельца"""
        return user_id == self.owner_user_id
    
    async def _cancel_and_show_settings(self, message: Message, state: FSMContext):
        """Отмена и возврат к настройкам"""
        await state.clear()
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{Emoji.SETTINGS} К настройкам", callback_data="admin_settings")]
        ])
        await message.answer("Настройка отменена", reply_markup=keyboard)
    
    async def _handle_database_error(self, message: Message, state: FSMContext, error: Exception, operation: str):
        """Обработка ошибки БД"""
        logger.error(f"Failed to update {operation}", error=str(error))
        await message.answer(f"{Emoji.ERROR} Ошибка при сохранении {operation}. Попробуйте позже.")
        await state.clear()
    
    async def cb_settings_action(self, callback: CallbackQuery, state: FSMContext):
        """Обработка действий настроек"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        action = callback.data.replace("settings_", "")
        
        if action == "welcome":
            await self._handle_welcome_message_setup(callback, state)
        elif action == "welcome_button":
            await self._handle_welcome_button_setup(callback, state)
        elif action == "confirmation":
            await self._handle_confirmation_message_setup(callback, state)
        elif action == "goodbye":
            await self._handle_goodbye_message_setup(callback, state)
        elif action == "goodbye_button":
            await self._handle_goodbye_button_setup(callback, state)
    
    async def _handle_welcome_message_setup(self, callback: CallbackQuery, state: FSMContext):
        """Настройка приветственного сообщения"""
        await state.set_state(BotSettingsStates.waiting_for_welcome_message)
        
        # Используем текущее сообщение из self
        current_message = self.welcome_message or "Не настроено"
        
        if self.welcome_message:
            example = self.formatter.format_message_template(
                self.welcome_message, 
                username="@example_user", 
                first_name="Иван"
            )
            current_display = f"<code>{self.welcome_message}</code>\n\n<b>Пример:</b>\n{example}"
        else:
            current_display = current_message
        
        text = f"""
👋 <b>Приветственное сообщение</b>

<b>Текущее сообщение:</b>
{current_display}

<b>Что это:</b>
Первое сообщение, которое получает новый участник после вступления в канал/группу.

<b>Доступные переменные:</b>
- <code>{{username}}</code> - имя пользователя (@username)
- <code>{{first_name}}</code> - имя пользователя

Отправьте новое приветственное сообщение или /cancel для отмены:
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{Emoji.BACK} Отмена", callback_data="admin_settings")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def _handle_welcome_button_setup(self, callback: CallbackQuery, state: FSMContext):
        """Настройка кнопки приветствия"""
        await state.set_state(BotSettingsStates.waiting_for_welcome_button)
        
        current_button = self.welcome_button_text or "Не настроено"
        
        text = f"""
🔘 <b>Кнопка приветствия</b>

<b>Текущая кнопка:</b>
{current_button}

<b>Что это:</b>
Кнопка под приветственным сообщением. После нажатия пользователь получает подтверждение и запускается воронка продаж если она настроена.
- Получает доступ к ИИ агенту если настроен

<b>Примеры:</b>
- "📋 Ознакомился с правилами"
- "✅ Понятно, спасибо!"
- "🤝 Готов к общению"

Отправьте текст для кнопки или /cancel для отмены:
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{Emoji.BACK} Отмена", callback_data="admin_settings")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def _handle_confirmation_message_setup(self, callback: CallbackQuery, state: FSMContext):
        """Настройка сообщения подтверждения"""
        await state.set_state(BotSettingsStates.waiting_for_confirmation_message)
        
        current_message = self.confirmation_message or "Не настроено"
        
        if self.confirmation_message:
            example = self.formatter.format_message_template(
                self.confirmation_message, 
                username="@example_user", 
                first_name="Иван"
            )
            current_display = f"<code>{self.confirmation_message}</code>\n\n<b>Пример:</b>\n{example}"
        else:
            current_display = current_message
        
        text = f"""
✅ <b>Сообщение подтверждения</b>

<b>Текущее сообщение:</b>
{current_display}

<b>Что это:</b>
Сообщение отправляется после нажатия на кнопку приветствия. Подтверждает успешное взаимодействие.

<b>Доступные переменные:</b>
- <code>{{username}}</code> - имя пользователя (@username)
- <code>{{first_name}}</code> - имя пользователя

Отправьте сообщение подтверждения или /cancel для отмены:
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{Emoji.BACK} Отмена", callback_data="admin_settings")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def _handle_goodbye_message_setup(self, callback: CallbackQuery, state: FSMContext):
        """Настройка прощального сообщения"""
        await state.set_state(BotSettingsStates.waiting_for_goodbye_message)
        
        current_message = self.goodbye_message or "Не настроено"
        
        if self.goodbye_message:
            example = self.formatter.format_message_template(
                self.goodbye_message, 
                username="@example_user", 
                first_name="Иван"
            )
            current_display = f"<code>{self.goodbye_message}</code>\n\n<b>Пример:</b>\n{example}"
        else:
            current_display = current_message
        
        text = f"""
👋 <b>Прощальное сообщение</b>

<b>Текущее сообщение:</b>
{current_display}

<b>Что это:</b>
Сообщение отправляется пользователю после выхода из канала/группы. Помогает удержать участников.

<b>Доступные переменные:</b>
- <code>{{username}}</code> - имя пользователя (@username)
- <code>{{first_name}}</code> - имя пользователя

Отправьте новое прощальное сообщение или /cancel для отмены:
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{Emoji.BACK} Отмена", callback_data="admin_settings")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def _handle_goodbye_button_setup(self, callback: CallbackQuery, state: FSMContext):
        """Настройка кнопки прощания"""
        await state.set_state(BotSettingsStates.waiting_for_goodbye_button_text)
        
        current_text = self.goodbye_button_text or "Не настроено"
        current_url = self.goodbye_button_url or "Не настроено"
        
        text = f"""
🔗 <b>Кнопка прощания</b>

<b>Текущие настройки:</b>
Текст кнопки: {current_text}
Ссылка: {current_url}

<b>Что это:</b>
Кнопка со ссылкой под прощальным сообщением. Помогает вернуть пользователя обратно.

<b>Примеры:</b>
- "🔔 Вернуться в канал"
- "💬 Связаться с поддержкой"
- "📱 Наше приложение"

Отправьте текст кнопки или /cancel для отмены:
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{Emoji.BACK} Отмена", callback_data="admin_settings")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    # Обработчики ввода
    async def handle_welcome_message_input(self, message: Message, state: FSMContext):
        """Обработка ввода приветственного сообщения"""
        if not self._is_owner(message.from_user.id):
            return
        
        if message.text == "/cancel":
            await self._cancel_and_show_settings(message, state)
            return
        
        try:
            # Обновляем в БД
            await self.db.update_welcome_settings(self.bot_id, welcome_message=message.text)
            
            # ✅ ИСПРАВЛЕНО: Обновляем в текущей конфигурации
            self.welcome_message = message.text
            
            # ✅ ИСПРАВЛЕНО: Обновляем в UserBot
            if self.user_bot:
                await self.user_bot.update_welcome_settings(welcome_message=message.text)
            
            # ✅ ИСПРАВЛЕНО: Обновляем bot_manager
            if self.bot_config.get('bot_manager'):
                await self.bot_config['bot_manager'].update_bot_config(
                    self.bot_id,
                    welcome_message=message.text
                )
            
            example = self.formatter.format_message_template(message.text, username="@example_user", first_name="Иван")
            
            success_text = f"""
✅ <b>Приветственное сообщение обновлено!</b>

<b>Ваше сообщение:</b>
<code>{message.text}</code>

<b>Пример отображения:</b>
{example}
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"{Emoji.SETTINGS} К настройкам", callback_data="admin_settings")]
            ])
            
            await message.answer(success_text, reply_markup=keyboard)
            await state.clear()
            
            logger.info("Welcome message updated", bot_id=self.bot_id, owner_user_id=message.from_user.id)
            
        except Exception as e:
            await self._handle_database_error(message, state, e, "приветственного сообщения")
    
    async def handle_welcome_button_input(self, message: Message, state: FSMContext):
        """Обработка ввода кнопки приветствия"""
        if not self._is_owner(message.from_user.id):
            return
        
        if message.text == "/cancel":
            await self._cancel_and_show_settings(message, state)
            return
        
        try:
            # Обновляем в БД
            await self.db.update_welcome_settings(self.bot_id, welcome_button_text=message.text)
            
            # ✅ ИСПРАВЛЕНО: Обновляем в текущей конфигурации
            self.welcome_button_text = message.text
            
            # ✅ ИСПРАВЛЕНО: Обновляем в UserBot
            if self.user_bot:
                await self.user_bot.update_welcome_settings(welcome_button_text=message.text)
            
            # ✅ ИСПРАВЛЕНО: Обновляем bot_manager
            if self.bot_config.get('bot_manager'):
                await self.bot_config['bot_manager'].update_bot_config(
                    self.bot_id,
                    welcome_button_text=message.text
                )
            
            success_text = f"""
✅ <b>Кнопка приветствия настроена!</b>

<b>Текст кнопки:</b>
{message.text}

<b>Теперь:</b>
- Кнопка будет отображаться с приветственным сообщением
- После нажатия кнопка исчезнет
- Пользователю придет сообщение подтверждения (если настроено)
- Запустится воронка продаж (если настроена)
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"{Emoji.SETTINGS} К настройкам", callback_data="admin_settings")]
            ])
            
            await message.answer(success_text, reply_markup=keyboard)
            await state.clear()
            
            logger.info("Welcome button updated", bot_id=self.bot_id)
            
        except Exception as e:
            await self._handle_database_error(message, state, e, "кнопки приветствия")
    
    async def handle_confirmation_message_input(self, message: Message, state: FSMContext):
        """Обработка ввода сообщения подтверждения"""
        if not self._is_owner(message.from_user.id):
            return
        
        if message.text == "/cancel":
            await self._cancel_and_show_settings(message, state)
            return
        
        try:
            # Обновляем в БД
            await self.db.update_welcome_settings(self.bot_id, confirmation_message=message.text)
            
            # ✅ ИСПРАВЛЕНО: Обновляем в текущей конфигурации
            self.confirmation_message = message.text
            
            # ✅ ИСПРАВЛЕНО: Обновляем в UserBot
            if self.user_bot:
                await self.user_bot.update_welcome_settings(confirmation_message=message.text)
            
            # ✅ ИСПРАВЛЕНО: Обновляем bot_manager
            if self.bot_config.get('bot_manager'):
                await self.bot_config['bot_manager'].update_bot_config(
                    self.bot_id,
                    confirmation_message=message.text
                )
            
            example = self.formatter.format_message_template(message.text, username="@example_user", first_name="Иван")
            
            success_text = f"""
✅ <b>Сообщение подтверждения настроено!</b>

<b>Ваше сообщение:</b>
<code>{message.text}</code>

<b>Пример отображения:</b>
{example}

<b>Это сообщение будет отправляться после нажатия на кнопку приветствия.</b>
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"{Emoji.SETTINGS} К настройкам", callback_data="admin_settings")]
            ])
            
            await message.answer(success_text, reply_markup=keyboard)
            await state.clear()
            
            logger.info("Confirmation message updated", bot_id=self.bot_id)
            
        except Exception as e:
            await self._handle_database_error(message, state, e, "сообщения подтверждения")
    
    async def handle_goodbye_message_input(self, message: Message, state: FSMContext):
        """Обработка ввода прощального сообщения"""
        if not self._is_owner(message.from_user.id):
            return
        
        if message.text == "/cancel":
            await self._cancel_and_show_settings(message, state)
            return
        
        try:
            # Обновляем в БД
            await self.db.update_goodbye_settings(self.bot_id, goodbye_message=message.text)
            
            # ✅ ИСПРАВЛЕНО: Обновляем в текущей конфигурации
            self.goodbye_message = message.text
            
            # ✅ ИСПРАВЛЕНО: Обновляем в UserBot
            if self.user_bot:
                await self.user_bot.update_goodbye_settings(goodbye_message=message.text)
            
            # ✅ ИСПРАВЛЕНО: Обновляем bot_manager
            if self.bot_config.get('bot_manager'):
                await self.bot_config['bot_manager'].update_bot_config(
                    self.bot_id,
                    goodbye_message=message.text
                )
            
            example = self.formatter.format_message_template(message.text, username="@example_user", first_name="Иван")
            
            success_text = f"""
✅ <b>Прощальное сообщение обновлено!</b>

<b>Ваше сообщение:</b>
<code>{message.text}</code>

<b>Пример отображения:</b>
{example}
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"{Emoji.SETTINGS} К настройкам", callback_data="admin_settings")]
            ])
            
            await message.answer(success_text, reply_markup=keyboard)
            await state.clear()
            
            logger.info("Goodbye message updated", bot_id=self.bot_id)
            
        except Exception as e:
            await self._handle_database_error(message, state, e, "прощального сообщения")
    
    async def handle_goodbye_button_text_input(self, message: Message, state: FSMContext):
        """Обработка ввода текста кнопки прощания"""
        if not self._is_owner(message.from_user.id):
            return
        
        if message.text == "/cancel":
            await self._cancel_and_show_settings(message, state)
            return
        
        # Сохраняем текст и переходим к вводу URL
        await state.update_data(goodbye_button_text=message.text)
        await state.set_state(BotSettingsStates.waiting_for_goodbye_button_url)
        
        text = f"""
🔗 <b>Ссылка для кнопки прощания</b>

<b>Текст кнопки:</b> {message.text}

<b>Теперь отправьте ссылку для этой кнопки:</b>

<b>Примеры ссылок:</b>
- https://t.me/yourchannel
- https://t.me/yoursupport
- https://yourwebsite.com
- https://t.me/+invite_link

Отправьте ссылку или /cancel для отмены:
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{Emoji.BACK} Отмена", callback_data="admin_settings")]
        ])
        
        await message.answer(text, reply_markup=keyboard)
    
    async def handle_goodbye_button_url_input(self, message: Message, state: FSMContext):
        """Обработка ввода URL кнопки прощания"""
        if not self._is_owner(message.from_user.id):
            return
        
        if message.text == "/cancel":
            await self._cancel_and_show_settings(message, state)
            return
        
        data = await state.get_data()
        button_text = data.get("goodbye_button_text")
        
        if not button_text:
            await message.answer("Ошибка: данные не найдены")
            await state.clear()
            return
        
        # Базовая валидация URL
        url = message.text.strip()
        if not (url.startswith("http://") or url.startswith("https://") or url.startswith("tg://")):
            await message.answer(
                f"{Emoji.WARNING} <b>Неверный формат ссылки!</b>\n\n"
                f"Ссылка должна начинаться с:\n"
                f"• https://\n"
                f"• http://\n"
                f"• tg://\n\n"
                f"Попробуйте еще раз:"
            )
            return
        
        try:
            # Обновляем в БД
            await self.db.update_goodbye_settings(
                self.bot_id, 
                goodbye_button_text=button_text,
                goodbye_button_url=url
            )
            
            # ✅ ИСПРАВЛЕНО: Обновляем в текущей конфигурации
            self.goodbye_button_text = button_text
            self.goodbye_button_url = url
            
            # ✅ ИСПРАВЛЕНО: Обновляем в UserBot
            if self.user_bot:
                await self.user_bot.update_goodbye_settings(
                    goodbye_button_text=button_text,
                    goodbye_button_url=url
                )
            
            # ✅ ИСПРАВЛЕНО: Обновляем bot_manager
            if self.bot_config.get('bot_manager'):
                await self.bot_config['bot_manager'].update_bot_config(
                    self.bot_id,
                    goodbye_button_text=button_text,
                    goodbye_button_url=url
                )
            
            success_text = f"""
✅ <b>Кнопка прощания настроена!</b>

<b>Текст кнопки:</b> {button_text}
<b>Ссылка:</b> {url}

<b>Теперь:</b>
- Кнопка будет отображаться с прощальным сообщением
- При нажатии пользователь перейдет по ссылке
- Это поможет удержать участников
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"{Emoji.SETTINGS} К настройкам", callback_data="admin_settings")]
            ])
            
            await message.answer(success_text, reply_markup=keyboard)
            await state.clear()
            
            logger.info("Goodbye button updated", bot_id=self.bot_id)
            
        except Exception as e:
            await self._handle_database_error(message, state, e, "кнопки прощания")
