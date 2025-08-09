"""
Обработчики ИИ ассистента
"""

import structlog
from datetime import datetime
from aiogram import Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext

from config import Emoji
from ..states import AISettingsStates
from ..keyboards import AIKeyboards

logger = structlog.get_logger()


def register_ai_handlers(dp: Dispatcher, **kwargs):
    """Регистрация обработчиков ИИ"""
    
    db = kwargs['db']
    bot_config = kwargs['bot_config']  # ИЗМЕНЕНО: получаем полную конфигурацию
    ai_assistant = kwargs.get('ai_assistant')
    user_bot = kwargs.get('user_bot')  # Получаем ссылку на UserBot
    
    try:
        handler = AIHandler(db, bot_config, ai_assistant, user_bot)
        
        # Callback обработчики
        dp.callback_query.register(handler.cb_admin_ai, F.data == "admin_ai")
        dp.callback_query.register(handler.cb_ai_action, F.data.startswith("ai_"))
        
        # Обработчики ввода
        dp.message.register(
            handler.handle_api_token_input,
            AISettingsStates.waiting_for_api_token
        )
        dp.message.register(
            handler.handle_bot_id_input,
            AISettingsStates.waiting_for_bot_id
        )
        dp.message.register(
            handler.handle_ai_assistant_id_input,
            AISettingsStates.waiting_for_assistant_id
        )
        dp.message.register(
            handler.handle_ai_daily_limit_input,
            AISettingsStates.waiting_for_daily_limit
        )
        dp.message.register(
            handler.handle_ai_conversation,
            AISettingsStates.in_ai_conversation
        )
        
        # Обработчики кнопок
        dp.message.register(
            handler.handle_ai_button_click,
            F.text == "🤖 Позвать ИИ"
        )
        
        dp.message.register(
            handler.handle_ai_exit,
            F.text == "🚪 Завершить диалог с ИИ"
        )
        
        logger.info("AI handlers registered successfully", 
                   bot_id=bot_config['bot_id'])
        
    except Exception as e:
        logger.error("Failed to register AI handlers", 
                    bot_id=kwargs.get('bot_config', {}).get('bot_id', 'unknown'),
                    error=str(e), exc_info=True)
        raise


class AIHandler:
    """Обработчик ИИ ассистента"""
    
    def __init__(self, db, bot_config: dict, ai_assistant, user_bot):
        self.db = db
        self.bot_config = bot_config
        self.bot_id = bot_config['bot_id']
        self.owner_user_id = bot_config['owner_user_id']
        self.ai_assistant = ai_assistant
        self.user_bot = user_bot  # Сохраняем ссылку на UserBot
        
        # Получаем настройки ИИ из конфигурации
        self.bot_username = bot_config['bot_username']
        self.ai_assistant_id = bot_config.get('ai_assistant_id')
        self.ai_assistant_enabled = bot_config.get('ai_assistant_enabled', False)
        self.ai_assistant_settings = bot_config.get('ai_assistant_settings', {})
    
    def _is_owner(self, user_id: int) -> bool:
        """Проверка владельца"""
        return user_id == self.owner_user_id
    
    def _should_show_ai_button(self, user_id: int) -> bool:
        """Проверка показывать ли кнопку ИИ"""
        return True
    
    async def _cancel_and_show_ai(self, message: Message, state: FSMContext):
        """Отмена и показ настроек ИИ"""
        await state.clear()
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
        ])
        await message.answer("Настройка отменена", reply_markup=keyboard)
    
    async def cb_admin_ai(self, callback: CallbackQuery):
        """Настройки ИИ"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        ai_status = "включен" if self.ai_assistant_enabled else "выключен"
        
        # Проверяем статус конфигурации
        platform = self.ai_assistant_settings.get('detected_platform')
        config_status = "не настроен"
        platform_info = ""
        
        if self.ai_assistant_id:
            if platform == 'chatforyou':
                bot_id_value = self.ai_assistant_settings.get('chatforyou_bot_id')
                if bot_id_value:
                    config_status = f"API: {self.ai_assistant_id[:10]}... | ID: {bot_id_value}"
                else:
                    config_status = f"API: {self.ai_assistant_id[:10]}... | ID: не задан"
            else:
                config_status = f"API: {self.ai_assistant_id[:10]}..."
            
            if platform:
                platform_names = {
                    'chatforyou': 'ChatForYou',
                    'protalk': 'ProTalk'
                }
                platform_display = platform_names.get(platform, platform)
                platform_info = f"\n🌐 Платформа: {platform_display}"
        
        daily_limit = self.ai_assistant_settings.get('daily_limit')
        limit_text = f"{daily_limit} сообщений в день" if daily_limit else "безлимитно"
        
        text = f"""
🤖 <b>ИИ Агент @{self.bot_username}</b>

<b>Текущие настройки:</b>
🤖 Статус: {ai_status}
🔑 Конфигурация: {config_status}{platform_info}
📊 Лимит: {limit_text}

<b>Поддерживаемые платформы:</b>
- ChatForYou (требует API токен + ID сотрудника)
- ProTalk (требует только API токен)

<b>Настройка происходит в 2 шага:</b>
1️⃣ Ввод API токена
2️⃣ Ввод ID сотрудника (только для ChatForYou)

<b>Как работает ИИ агент:</b>
1. Доступен только подписчикам канала
2. Запускается кнопкой "🤖 Позвать ИИ"
3. Работает в режиме диалога
4. Учитывает лимиты сообщений
"""
        
        # Проверяем полную конфигурацию
        is_configured = False
        if self.ai_assistant_id:
            if platform == 'chatforyou':
                is_configured = bool(self.ai_assistant_settings.get('chatforyou_bot_id'))
            else:
                is_configured = True
        
        await callback.message.edit_text(
            text,
            reply_markup=AIKeyboards.settings_menu(
                self.ai_assistant_enabled,
                is_configured,
                platform,
                daily_limit
            )
        )
    
    async def cb_ai_action(self, callback: CallbackQuery, state: FSMContext):
        """Обработка действий ИИ"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        action = callback.data.replace("ai_", "")
        
        if action == "toggle":
            await self._toggle_ai_assistant(callback)
        elif action == "set_id":
            await self._set_assistant_id(callback, state)
        elif action == "set_limit":
            await self._set_daily_limit(callback, state)
        elif action == "test":
            await self._test_ai_assistant(callback, state)
        elif action == "unlimited":
            await self._set_unlimited_limit(callback)
    
    async def _toggle_ai_assistant(self, callback: CallbackQuery):
        """Переключение ИИ ассистента"""
        try:
            new_status = not self.ai_assistant_enabled
            
            # Создаем или обновляем настройки
            ai_settings = self.ai_assistant_settings.copy()
            
            await self.db.update_ai_assistant(
                self.bot_id,
                enabled=new_status,
                settings=ai_settings
            )
            
            # ✅ ИСПРАВЛЕНО: Обновляем в текущей конфигурации
            self.ai_assistant_enabled = new_status
            
            # ✅ ИСПРАВЛЕНО: Обновляем в UserBot
            if self.user_bot:
                await self.user_bot.update_ai_settings(ai_assistant_enabled=new_status)
            
            # ✅ ИСПРАВЛЕНО: Обновляем bot_manager
            if self.bot_config.get('bot_manager'):
                await self.bot_config['bot_manager'].update_bot_config(
                    self.bot_id,
                    ai_assistant_enabled=new_status,
                    ai_assistant_settings=ai_settings
                )
            
            status_text = "включен" if new_status else "выключен"
            await callback.answer(f"ИИ агент {status_text}!", show_alert=True)
            
            # Обновляем меню
            await self.cb_admin_ai(callback)
            
        except Exception as e:
            logger.error("Failed to toggle AI assistant", error=str(e))
            await callback.answer("Ошибка при изменении настроек", show_alert=True)
    
    async def _set_assistant_id(self, callback: CallbackQuery, state: FSMContext):
        """Настройка ID ассистента"""
        await state.set_state(AISettingsStates.waiting_for_api_token)
        
        text = f"""
🔑 <b>Шаг 1/2: API токен</b>

Введите API токен от ChatForYou или ProTalk.

<b>Поддерживаемые платформы:</b>
- ChatForYou (api.chatforyou.ru)
- ProTalk (api.pro-talk.ru)

Система автоматически определит платформу по токену.

<b>Пример токена:</b> <code>your_api_token_here</code>

<b>Отправьте API токен:</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="admin_ai")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def _set_daily_limit(self, callback: CallbackQuery, state: FSMContext):
        """Установка дневного лимита"""
        await state.set_state(AISettingsStates.waiting_for_daily_limit)
        
        current_limit = self.ai_assistant_settings.get('daily_limit')
        limit_text = f"{current_limit} сообщений" if current_limit else "безлимит"
        
        text = f"""
📊 <b>Лимит сообщений в день</b>

<b>Текущий лимит:</b> {limit_text}

Укажите максимальное количество сообщений, которое один пользователь может отправить ИИ агенту за день.

<b>Примеры:</b>
- <code>50</code> - 50 сообщений в день
- <code>0</code> или <code>безлимит</code> - без ограничений

<b>Отправьте лимит:</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="♾️ Безлимит", callback_data="ai_unlimited")],
            [InlineKeyboardButton(text="Отмена", callback_data="admin_ai")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def _set_unlimited_limit(self, callback: CallbackQuery):
        """Установка безлимита"""
        try:
            ai_settings = self.ai_assistant_settings.copy()
            ai_settings['daily_limit'] = None
            
            await self.db.update_ai_assistant(
                self.bot_id,
                settings=ai_settings
            )
            
            # ✅ ИСПРАВЛЕНО: Обновляем в текущей конфигурации
            self.ai_assistant_settings = ai_settings
            
            # ✅ ИСПРАВЛЕНО: Обновляем в UserBot
            if self.user_bot:
                await self.user_bot.update_ai_settings(ai_assistant_settings=ai_settings)
            
            # ✅ ИСПРАВЛЕНО: Обновляем bot_manager
            if self.bot_config.get('bot_manager'):
                await self.bot_config['bot_manager'].update_bot_config(
                    self.bot_id,
                    ai_assistant_settings=ai_settings
                )
            
            await callback.answer("Установлен безлимит!", show_alert=True)
            await self.cb_admin_ai(callback)
            
        except Exception as e:
            logger.error("Failed to set unlimited limit", error=str(e))
            await callback.answer("Ошибка при сохранении настроек", show_alert=True)
    
    async def _test_ai_assistant(self, callback: CallbackQuery, state: FSMContext):
        """Тестирование ИИ ассистента"""
        if not self.ai_assistant_id:
            await callback.answer("❌ Сначала настройте API токен", show_alert=True)
            return
        
        platform = self.ai_assistant_settings.get('detected_platform')
        if not platform:
            await callback.answer("❌ Платформа не определена. Перенастройте токен.", show_alert=True)
            return
        
        if platform == 'chatforyou' and not self.ai_assistant_settings.get('chatforyou_bot_id'):
            await callback.answer("❌ Для ChatForYou требуется ID сотрудника", show_alert=True)
            return
        
        await state.set_state(AISettingsStates.in_ai_conversation)
        await state.update_data(is_test_mode=True)
        
        platform_names = {
            'chatforyou': 'ChatForYou',
            'protalk': 'ProTalk'
        }
        platform_display = platform_names.get(platform, platform)
        
        bot_id_info = ""
        if platform == 'chatforyou':
            bot_id_info = f"\n<b>ID сотрудника:</b> {self.ai_assistant_settings.get('chatforyou_bot_id')}"
        
        text = f"""
🧪 <b>Тестирование ИИ агента</b>

<b>API Token:</b> {self.ai_assistant_id[:15]}...
<b>Платформа:</b> {platform_display}{bot_id_info}

Отправьте любое сообщение для тестирования ИИ агента. 

<b>Напишите ваш вопрос:</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚪 Выйти из тестирования", callback_data="admin_ai")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def handle_api_token_input(self, message: Message, state: FSMContext):
        """Обработка ввода API токена"""
        if not self._is_owner(message.from_user.id):
            return
        
        if message.text == "/cancel":
            await self._cancel_and_show_ai(message, state)
            return
        
        api_token = message.text.strip()
        
        try:
            await message.answer("🔍 Определяем платформу...")
            
            # Определяем платформу без тестирования ChatForYou
            success, platform, error_msg = await self.db.detect_and_validate_ai_platform(api_token)
            
            if not success:
                await message.answer(
                    f"❌ {error_msg}\n\n"
                    f"Проверьте токен и попробуйте еще раз:"
                )
                return
            
            # Сохраняем токен и платформу в состоянии
            await state.update_data(api_token=api_token, platform=platform)
            
            if platform == 'chatforyou':
                # Переходим к шагу 2 для ChatForYou
                await state.set_state(AISettingsStates.waiting_for_bot_id)
                
                text = f"""
✅ <b>Токен сохранен для платформы ChatForYou!</b>

🆔 <b>Шаг 2/2: ID сотрудника</b>

Для завершения настройки ChatForYou введите ваш ID сотрудника.

<b>Пример:</b> <code>21472</code>

<b>Важно:</b> ID должен быть числом, активным в системе ChatForYou.

<b>Отправьте ID сотрудника:</b>
"""
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Отмена", callback_data="admin_ai")]
                ])
                
                await message.answer(text, reply_markup=keyboard)
                
            else:
                # ProTalk готов к использованию
                ai_settings = self.ai_assistant_settings.copy()
                ai_settings.update({
                    'detected_platform': platform,
                    'platform_detected_at': datetime.now().isoformat(),
                    'platform_validation': 'completed'
                })
                
                await self.db.update_ai_assistant_with_platform(
                    self.bot_id,
                    api_token=api_token,
                    bot_id_value=None,
                    settings=ai_settings,
                    platform=platform
                )
                
                # ✅ ИСПРАВЛЕНО: Обновляем в текущей конфигурации
                self.ai_assistant_id = api_token
                self.ai_assistant_settings = ai_settings
                
                # ✅ ИСПРАВЛЕНО: Обновляем в UserBot
                if self.user_bot:
                    await self.user_bot.update_ai_settings(
                        ai_assistant_id=api_token,
                        ai_assistant_settings=ai_settings
                    )
                
                # ✅ ИСПРАВЛЕНО: Обновляем bot_manager
                if self.bot_config.get('bot_manager'):
                    await self.bot_config['bot_manager'].update_bot_config(
                        self.bot_id,
                        ai_assistant_id=api_token,
                        ai_assistant_settings=ai_settings
                    )
                
                success_text = f"""
✅ <b>ProTalk настроен и готов!</b>

<b>API Token:</b> <code>{api_token[:15]}...</code>
<b>Платформа:</b> ProTalk
<b>Статус:</b> ✅ Готов к работе

🔥 Теперь можете протестировать работу ИИ агента!
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🧪 Тестировать ИИ", callback_data="ai_test")],
                    [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
                ])
                
                await message.answer(success_text, reply_markup=keyboard)
                await state.clear()
                
        except Exception as e:
            logger.error("Failed to process API token", error=str(e))
            await message.answer("❌ Ошибка при обработке токена")
            await state.clear()
    
    async def handle_bot_id_input(self, message: Message, state: FSMContext):
        """Обработка ввода ID сотрудника для ChatForYou"""
        if not self._is_owner(message.from_user.id):
            return
        
        if message.text == "/cancel":
            await self._cancel_and_show_ai(message, state)
            return
        
        bot_id_value = message.text.strip()
        
        # Валидация ID
        try:
            int(bot_id_value)
        except ValueError:
            await message.answer(
                f"❌ <b>ID сотрудника должен быть числом!</b>\n\n"
                f"Вы ввели: {bot_id_value}\n"
                f"Пример правильного ID: <code>21472</code>\n\n"
                f"Попробуйте еще раз:"
            )
            return
        
        bot_id_value = int(bot_id_value)
        
        try:
            # Получаем данные из шага 1
            data = await state.get_data()
            api_token = data.get('api_token')
            platform = data.get('platform')
            
            if not api_token or platform != 'chatforyou':
                await message.answer("❌ Ошибка: данные первого шага потеряны. Начните заново.")
                await state.clear()
                return
            
            # Финальное тестирование с реальными данными
            await message.answer("🔍 Проверяем соединение с ChatForYou...")
            
            success, verified_platform, error_msg = await self.db.detect_and_validate_ai_platform(
                api_token, 
                test_bot_id=bot_id_value
            )
            
            if not success:
                await message.answer(
                    f"❌ <b>Ошибка подключения к ChatForYou</b>\n\n"
                    f"{error_msg}\n\n"
                    f"<b>Возможные причины:</b>\n"
                    f"• Неправильный API токен\n"
                    f"• Неправильный ID сотрудника\n"
                    f"• ID не активен в системе ChatForYou\n"
                    f"• Нет прав доступа к API\n\n"
                    f"Проверьте данные и попробуйте еще раз:"
                )
                return
            
            if verified_platform != 'chatforyou':
                await message.answer(
                    f"❌ Ошибка: платформа изменилась после проверки ({platform} → {verified_platform})"
                )
                await state.clear()
                return
            
            # Сохраняем конфигурацию
            ai_settings = self.ai_assistant_settings.copy()
            ai_settings.update({
                'detected_platform': platform,
                'chatforyou_bot_id': bot_id_value,
                'platform_detected_at': datetime.now().isoformat(),
                'bot_id_verified': True,
                'bot_id_verified_at': datetime.now().isoformat(),
                'platform_validation': 'completed',
                'validation_method': 'real_api_test'
            })
            
            await self.db.update_ai_assistant_with_platform(
                self.bot_id,
                api_token=api_token,
                bot_id_value=bot_id_value,
                settings=ai_settings,
                platform=platform
            )
            
            # ✅ ИСПРАВЛЕНО: Обновляем в текущей конфигурации
            self.ai_assistant_id = api_token
            self.ai_assistant_settings = ai_settings
            
            # ✅ ИСПРАВЛЕНО: Обновляем в UserBot
            if self.user_bot:
                await self.user_bot.update_ai_settings(
                    ai_assistant_id=api_token,
                    ai_assistant_settings=ai_settings
                )
            
            # ✅ ИСПРАВЛЕНО: Обновляем bot_manager
            if self.bot_config.get('bot_manager'):
                await self.bot_config['bot_manager'].update_bot_config(
                    self.bot_id,
                    ai_assistant_id=api_token,
                    ai_assistant_settings=ai_settings
                )
            
            success_text = f"""
🎉 <b>ChatForYou полностью настроен и протестирован!</b>

<b>API Token:</b> <code>{api_token[:15]}...</code>
<b>ID сотрудника:</b> {bot_id_value}
<b>Платформа:</b> ChatForYou
<b>Статус:</b> ✅ Проверено реальным API запросом

🔥 <b>Выполненные проверки:</b>
- ✅ API токен валиден
- ✅ ID сотрудника активен и доступен
- ✅ Соединение с ChatForYou работает
- ✅ Тестовый запрос выполнен успешно

Теперь ИИ агент готов к работе с пользователями!
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🧪 Тестировать ИИ", callback_data="ai_test")],
                [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
            ])
            
            await message.answer(success_text, reply_markup=keyboard)
            await state.clear()
            
            logger.info("ChatForYou configuration completed", 
                       bot_id=self.bot_id, 
                       api_token_preview=api_token[:10],
                       chatforyou_bot_id=bot_id_value)
            
        except Exception as e:
            logger.error("Failed to validate ChatForYou configuration", error=str(e))
            await message.answer("❌ Ошибка при проверке конфигурации ChatForYou")
            await state.clear()
    
    async def handle_ai_assistant_id_input(self, message: Message, state: FSMContext):
        """Обработчик для совместимости"""
        await self.handle_api_token_input(message, state)
    
    async def handle_ai_daily_limit_input(self, message: Message, state: FSMContext):
        """Обработка ввода дневного лимита"""
        if not self._is_owner(message.from_user.id):
            return
        
        try:
            limit_text = message.text.strip().lower()
            
            if limit_text in ['0', 'безлимит', 'unlimited']:
                daily_limit = None
            else:
                daily_limit = int(limit_text)
                if daily_limit < 0:
                    await message.answer("❌ Лимит не может быть отрицательным!")
                    return
            
            ai_settings = self.ai_assistant_settings.copy()
            ai_settings['daily_limit'] = daily_limit
            
            await self.db.update_ai_assistant(
                self.bot_id,
                settings=ai_settings
            )
            
            # ✅ ИСПРАВЛЕНО: Обновляем в текущей конфигурации
            self.ai_assistant_settings = ai_settings
            
            # ✅ ИСПРАВЛЕНО: Обновляем в UserBot
            if self.user_bot:
                await self.user_bot.update_ai_settings(ai_assistant_settings=ai_settings)
            
            # ✅ ИСПРАВЛЕНО: Обновляем bot_manager
            if self.bot_config.get('bot_manager'):
                await self.bot_config['bot_manager'].update_bot_config(
                    self.bot_id,
                    ai_assistant_settings=ai_settings
                )
            
            limit_display = f"{daily_limit} сообщений в день" if daily_limit else "безлимит"
            
            success_text = f"""
✅ <b>Лимит сообщений обновлен!</b>

<b>Новый лимит:</b> {limit_display}

Теперь каждый пользователь сможет отправлять ИИ не более указанного количества сообщений в день.
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
            ])
            
            await message.answer(success_text, reply_markup=keyboard)
            await state.clear()
            
        except ValueError:
            await message.answer("❌ Неверный формат числа! Введите число или 'безлимит':")
        except Exception as e:
            logger.error("Failed to save daily limit", error=str(e))
            await message.answer("❌ Ошибка при сохранении лимита")
            await state.clear()
    
    async def handle_ai_conversation(self, message: Message, state: FSMContext):
        """Обработка диалога с ИИ"""
        try:
            data = await state.get_data()
            is_test_mode = data.get('is_test_mode', False)
            user_id = message.from_user.id
            
            # В тестовом режиме только владелец может тестировать
            if is_test_mode and not self._is_owner(user_id):
                return
            
            # В обычном режиме - проверяем подписку и лимиты
            if not is_test_mode:
                # Проверка подписки на канал
                channel_id = self.ai_assistant_settings.get('channel_id')
                if channel_id:
                    try:
                        from aiogram import Bot
                        bot = Bot(token=message.bot.token)
                        member = await bot.get_chat_member(channel_id, user_id)
                        if member.status in ['left', 'kicked']:
                            await message.answer(
                                "❌ ИИ агент доступен только подписчикам канала!\n"
                                "Подпишитесь на канал и попробуйте снова.",
                                reply_markup=ReplyKeyboardRemove()
                            )
                            await state.clear()
                            return
                    except Exception as e:
                        logger.warning("Could not check channel subscription", error=str(e))
                
                # Проверка лимита
                daily_limit = self.ai_assistant_settings.get('daily_limit')
                if daily_limit:
                    usage_count = await self.db.get_ai_usage_today(self.bot_id, user_id)
                    if usage_count >= daily_limit:
                        await message.answer(
                            f"❌ Лимит сообщений исчерпан!\n"
                            f"Вы можете отправить {daily_limit} сообщений в день.\n"
                            f"Попробуйте завтра.",
                            reply_markup=ReplyKeyboardRemove()
                        )
                        await state.clear()
                        return
            
            # Получаем платформу из настроек
            platform = self.ai_assistant_settings.get('detected_platform')
            if not platform:
                await message.answer(
                    "❌ Платформа ИИ не определена. Перенастройте токен.",
                    reply_markup=ReplyKeyboardRemove()
                )
                await state.clear()
                return
            
            # Получаем bot_id для ChatForYou
            bot_id_value = None
            if platform == 'chatforyou':
                bot_id_value = self.ai_assistant_settings.get('chatforyou_bot_id')
                if not bot_id_value:
                    await message.answer(
                        "❌ ID сотрудника не настроен для ChatForYou",
                        reply_markup=ReplyKeyboardRemove()
                    )
                    await state.clear()
                    return
            
            # Отправляем typing
            await message.bot.send_chat_action(message.chat.id, "typing")
            
            # Подготавливаем контекст
            context = {}
            if self.ai_assistant_settings.get('context_info', True):
                context = {
                    "user_name": message.from_user.first_name or "Пользователь",
                    "username": message.from_user.username,
                    "is_test": is_test_mode
                }
            
            # Отправляем сообщение ИИ
            from services.ai_assistant import ai_client
            
            ai_response = await ai_client.send_message(
                api_token=self.ai_assistant_id,
                message=message.text,
                user_id=user_id,
                bot_id=bot_id_value,
                platform=platform,
                context=context
            )
            
            if ai_response:
                # Увеличиваем счетчик использования (не для тест режима)
                if not is_test_mode:
                    await self.db.increment_ai_usage(self.bot_id, user_id)
                
                # Отправляем ответ
                keyboard = None
                if is_test_mode:
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🚪 Выйти из тестирования", callback_data="admin_ai")]
                    ])
                else:
                    keyboard = AIKeyboards.conversation_menu()
                
                await message.answer(ai_response, reply_markup=keyboard)
                
            else:
                await message.answer(
                    "❌ Извините, ИИ агент временно недоступен. Попробуйте позже.",
                    reply_markup=ReplyKeyboardRemove()
                )
                await state.clear()
                
        except Exception as e:
            logger.error("Error in AI conversation", error=str(e))
            await message.answer(
                "❌ Произошла ошибка при обращении к ИИ агенту.",
                reply_markup=ReplyKeyboardRemove()
            )
            await state.clear()
    
    async def handle_ai_button_click(self, message: Message, state: FSMContext):
        """Обработка нажатия кнопки вызова ИИ"""
        try:
            user = message.from_user
            
            # Проверяем что ИИ включен и настроен
            if not self.ai_assistant_enabled or not self.ai_assistant_id:
                await message.answer(
                    "❌ ИИ агент временно недоступен.",
                    reply_markup=ReplyKeyboardRemove()
                )
                return
            
            logger.info("🤖 AI button clicked", bot_id=self.bot_id, user_id=user.id)
            
            # Проверка лимита сообщений
            daily_limit = self.ai_assistant_settings.get('daily_limit')
            if daily_limit:
                usage_count = await self.db.get_ai_usage_today(self.bot_id, user.id)
                if usage_count >= daily_limit:
                    await message.answer(
                        f"❌ Лимит сообщений исчерпан!\n"
                        f"Вы можете отправить {daily_limit} сообщений ИИ агенту в день.\n"
                        f"Сегодня отправлено: {usage_count}\n"
                        f"Попробуйте завтра.",
                        reply_markup=ReplyKeyboardRemove()
                    )
                    return
            
            # Переводим в режим общения с ИИ
            await state.set_state(AISettingsStates.in_ai_conversation)
            
            remaining_messages = ""
            if daily_limit:
                usage_count = await self.db.get_ai_usage_today(self.bot_id, user.id)
                remaining = daily_limit - usage_count
                remaining_messages = f"\n📊 Осталось сообщений: {remaining}"
            
            welcome_text = f"""
🤖 <b>Добро пожаловать в чат с ИИ агентом!</b>

Задавайте любые вопросы, я постараюсь помочь.{remaining_messages}

<b>Напишите ваш вопрос:</b>
"""
            
            await message.answer(welcome_text, reply_markup=AIKeyboards.conversation_menu())
            
        except Exception as e:
            logger.error("💥 Error handling AI button click", bot_id=self.bot_id, error=str(e))
            await message.answer(
                "❌ Произошла ошибка при запуске ИИ агента.",
                reply_markup=ReplyKeyboardRemove()
            )
    
    async def handle_ai_exit(self, message: Message, state: FSMContext):
        """Обработка выхода из диалога с ИИ"""
        if message.text == "🚪 Завершить диалог с ИИ":
            await message.answer(
                "👋 Диалог с ИИ агентом завершен. Спасибо за общение!",
                reply_markup=ReplyKeyboardRemove()
            )
            await state.clear()
