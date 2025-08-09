"""
Обработчики ИИ ассистента с поддержкой OpenAI Assistants (ИСПРАВЛЕННАЯ ВЕРСИЯ)
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
    bot_config = kwargs['bot_config']
    ai_assistant = kwargs.get('ai_assistant')
    user_bot = kwargs.get('user_bot')
    
    try:
        handler = AIHandler(db, bot_config, ai_assistant, user_bot)
        
        # Callback обработчики
        dp.callback_query.register(handler.cb_admin_ai, F.data == "admin_ai")
        dp.callback_query.register(handler.cb_ai_action, F.data.startswith("ai_"))
        
        # Новые обработчики для выбора типа агента
        dp.callback_query.register(handler.cb_select_agent_type, F.data.startswith("agent_type_"))
        dp.callback_query.register(handler.cb_openai_action, F.data.startswith("openai_"))
        
        # Обработчики ввода для ChatForYou (существующие)
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
        
        # Новые обработчики для OpenAI агента
        dp.message.register(
            handler.handle_openai_name_input,
            AISettingsStates.waiting_for_openai_name
        )
        dp.message.register(
            handler.handle_openai_role_input,
            AISettingsStates.waiting_for_openai_role
        )
        
        # Обработчики диалога
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
        
        logger.info("AI handlers with OpenAI support registered successfully", 
                   bot_id=bot_config['bot_id'])
        
    except Exception as e:
        logger.error("Failed to register AI handlers", 
                    bot_id=kwargs.get('bot_config', {}).get('bot_id', 'unknown'),
                    error=str(e), exc_info=True)
        raise


class AIHandler:
    """Обработчик ИИ ассистента с поддержкой ChatForYou и OpenAI"""
    
    def __init__(self, db, bot_config: dict, ai_assistant, user_bot):
        self.db = db
        self.bot_config = bot_config
        self.bot_id = bot_config['bot_id']
        self.owner_user_id = bot_config['owner_user_id']
        self.ai_assistant = ai_assistant
        self.user_bot = user_bot
        
        # Получаем настройки ИИ из конфигурации
        self.bot_username = bot_config['bot_username']
        self.ai_assistant_id = bot_config.get('ai_assistant_id')
        self.ai_assistant_enabled = bot_config.get('ai_assistant_enabled', False)
        self.ai_assistant_settings = bot_config.get('ai_assistant_settings', {})
    
    def _is_owner(self, user_id: int) -> bool:
        """Проверка владельца"""
        return user_id == self.owner_user_id
    
    def _get_agent_type(self) -> str:
        """Получение типа агента"""
        return self.ai_assistant_settings.get('agent_type', 'none')
    
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
    
    async def _safe_update_user_bot(self, **kwargs):
        """Безопасное обновление настроек UserBot"""
        try:
            if self.user_bot and hasattr(self.user_bot, 'update_ai_settings'):
                await self.user_bot.update_ai_settings(**kwargs)
            else:
                logger.warning("UserBot doesn't have update_ai_settings method", bot_id=self.bot_id)
        except Exception as e:
            logger.error("Failed to update UserBot settings", bot_id=self.bot_id, error=str(e))
    
    async def _safe_update_bot_manager(self, **kwargs):
        """Безопасное обновление через bot_manager"""
        try:
            bot_manager = self.bot_config.get('bot_manager')
            if bot_manager and hasattr(bot_manager, 'update_bot_config'):
                await bot_manager.update_bot_config(self.bot_id, **kwargs)
            else:
                logger.warning("BotManager doesn't have update_bot_config method", bot_id=self.bot_id)
        except Exception as e:
            logger.error("Failed to update BotManager config", bot_id=self.bot_id, error=str(e))
    
    async def cb_admin_ai(self, callback: CallbackQuery):
        """Главное меню настроек ИИ"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        agent_type = self._get_agent_type()
        
        # Если тип агента не выбран - показываем меню выбора
        if agent_type == 'none':
            await self._show_agent_type_selection(callback)
            return
        
        # Показываем настройки конкретного типа агента
        if agent_type == 'chatforyou':
            await self._show_chatforyou_settings(callback)
        elif agent_type == 'openai':
            await self._show_openai_settings(callback)
        else:
            # Fallback к выбору типа
            await self._show_agent_type_selection(callback)
    
    async def _show_agent_type_selection(self, callback: CallbackQuery):
        """Показ меню выбора типа агента"""
        text = f"""
🤖 <b>ИИ Агент @{self.bot_username}</b>

Выберите тип ИИ агента для вашего бота:

🌐 <b>Подключить с платформы</b>
- ChatForYou (api.chatforyou.ru)
- ProTalk (api.pro-talk.ru)
- Требует API токен

🎨 <b>Создать своего агента</b>
- На базе OpenAI GPT-4o-mini
- Настройка роли и инструкций
- Работает через наш токен

<b>Что выберете?</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Подключить с платформы", callback_data="agent_type_chatforyou")],
            [InlineKeyboardButton(text="🎨 Создать своего агента", callback_data="agent_type_openai")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def _show_chatforyou_settings(self, callback: CallbackQuery):
        """Показ настроек ChatForYou (существующая логика)"""
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
        
        text = f"""
🌐 <b>ИИ Агент с платформы</b>

<b>Текущие настройки:</b>
🤖 Статус: {ai_status}
🔑 Конфигурация: {config_status}{platform_info}

<b>Поддерживаемые платформы:</b>
- ChatForYou (требует API токен + ID сотрудника)
- ProTalk (требует только API токен)

<b>Настройка происходит в 2 шага:</b>
1️⃣ Ввод API токена
2️⃣ Ввод ID сотрудника (только для ChatForYou)
"""
        
        # Проверяем полную конфигурацию
        is_configured = False
        if self.ai_assistant_id:
            if platform == 'chatforyou':
                is_configured = bool(self.ai_assistant_settings.get('chatforyou_bot_id'))
            else:
                is_configured = True
        
        keyboard = AIKeyboards.chatforyou_settings_menu(
            self.ai_assistant_enabled,
            is_configured,
            platform
        )
        
        # Добавляем кнопку смены типа агента
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="🔄 Сменить тип агента", callback_data="ai_change_type")
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def _show_openai_settings(self, callback: CallbackQuery):
        """Показ настроек OpenAI агента"""
        agent_status = "включен" if self.ai_assistant_enabled else "выключен"
        
        # Получаем информацию об OpenAI агенте
        local_agent_id = self.ai_assistant_settings.get('local_agent_id')
        openai_assistant_id = self.ai_assistant_settings.get('openai_assistant_id')
        
        agent_info = "не создан"
        agent_details = ""
        
        if local_agent_id:
            try:
                # Здесь будем получать данные из БД через новый сервис
                # Пока заглушка
                agent_info = f"ID: {local_agent_id}"
                if openai_assistant_id:
                    agent_details = f"\n🆔 OpenAI ID: {openai_assistant_id[:15]}..."
            except Exception as e:
                logger.error("Failed to get OpenAI agent info", error=str(e))
        
        text = f"""
🎨 <b>Собственный ИИ Агент</b>

<b>Текущие настройки:</b>
🤖 Статус: {agent_status}
🎯 Агент: {agent_info}{agent_details}
🧠 Модель: GPT-4o-mini
⚡ Лимиты: без ограничений

<b>Преимущества собственного агента:</b>
- Полная настройка роли и поведения
- Быстрые ответы через OpenAI API
- Без дополнительных токенов
- Стабильная работа 24/7

<b>Управление агентом:</b>
"""
        
        # Создаем клавиатуру для OpenAI агента
        keyboard = AIKeyboards.openai_settings_menu(
            self.ai_assistant_enabled,
            bool(local_agent_id)
        )
        
        # Добавляем кнопку смены типа агента
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="🔄 Сменить тип агента", callback_data="ai_change_type")
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def cb_select_agent_type(self, callback: CallbackQuery):
        """Обработка выбора типа агента"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        agent_type = callback.data.replace("agent_type_", "")
        
        try:
            # Обновляем тип агента в настройках
            ai_settings = self.ai_assistant_settings.copy()
            ai_settings['agent_type'] = agent_type
            
            await self.db.update_ai_assistant(
                self.bot_id,
                settings=ai_settings
            )
            
            # Обновляем локальные настройки
            self.ai_assistant_settings = ai_settings
            
            # Безопасное обновление UserBot
            await self._safe_update_user_bot(ai_assistant_settings=ai_settings)
            
            # Безопасное обновление bot_manager
            await self._safe_update_bot_manager(ai_assistant_settings=ai_settings)
            
            # Переходим к настройкам выбранного типа
            if agent_type == 'chatforyou':
                await self._show_chatforyou_settings(callback)
            elif agent_type == 'openai':
                await self._show_openai_settings(callback)
                
        except Exception as e:
            logger.error("Failed to set agent type", error=str(e))
            await callback.answer("Ошибка при сохранении типа агента", show_alert=True)
    
    async def cb_ai_action(self, callback: CallbackQuery, state: FSMContext):
        """Обработка действий для ChatForYou (существующая логика)"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        action = callback.data.replace("ai_", "")
        
        if action == "toggle":
            await self._toggle_ai_assistant(callback)
        elif action == "set_id":
            await self._set_assistant_id(callback, state)
        elif action == "test":
            await self._test_ai_assistant(callback, state)
        elif action == "change_type":
            await self._change_agent_type(callback)
    
    async def cb_openai_action(self, callback: CallbackQuery, state: FSMContext):
        """Обработка действий для OpenAI агента"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        action = callback.data.replace("openai_", "")
        
        if action == "toggle":
            await self._toggle_openai_assistant(callback)
        elif action == "create":
            await self._create_openai_agent(callback, state)
        elif action == "edit":
            await self._edit_openai_agent(callback, state)
        elif action == "delete":
            await self._delete_openai_agent(callback)
        elif action == "test":
            await self._test_openai_assistant(callback, state)
    
    async def _change_agent_type(self, callback: CallbackQuery):
        """Смена типа агента"""
        text = """
🔄 <b>Смена типа ИИ агента</b>

⚠️ <b>Внимание!</b> При смене типа агента:
- Текущая конфигурация будет сброшена
- Все настройки придется настроить заново
- Диалоги пользователей завершатся

Вы уверены, что хотите сменить тип агента?
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, сменить", callback_data="ai_confirm_change_type")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_ai")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def _create_openai_agent(self, callback: CallbackQuery, state: FSMContext):
        """Начало создания OpenAI агента"""
        await state.set_state(AISettingsStates.waiting_for_openai_name)
        
        text = f"""
🎨 <b>Создание собственного ИИ агента</b>

<b>Шаг 1/2: Имя агента</b>

Придумайте имя для вашего ИИ агента. Оно будет отображаться пользователям при общении.

<b>Примеры хороших имен:</b>
- Консультант Мария
- Помощник Алекс
- Эксперт по продажам
- Тренер по фитнесу

<b>Введите имя агента:</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_ai")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def handle_openai_name_input(self, message: Message, state: FSMContext):
        """Обработка ввода имени OpenAI агента"""
        if not self._is_owner(message.from_user.id):
            return
        
        if message.text == "/cancel":
            await self._cancel_and_show_ai(message, state)
            return
        
        agent_name = message.text.strip()
        
        if len(agent_name) < 2:
            await message.answer("❌ Имя агента должно быть не менее 2 символов. Попробуйте еще раз:")
            return
        
        if len(agent_name) > 100:
            await message.answer("❌ Имя агента слишком длинное (максимум 100 символов). Попробуйте еще раз:")
            return
        
        # Сохраняем имя в состоянии
        await state.update_data(agent_name=agent_name)
        await state.set_state(AISettingsStates.waiting_for_openai_role)
        
        text = f"""
✅ <b>Имя сохранено:</b> {agent_name}

<b>Шаг 2/2: Роль и инструкции</b>

Опишите роль вашего агента и то, как он должен отвечать пользователям. Это очень важно для качества ответов!

<b>Примеры хороших ролей:</b>
- "Ты эксперт по фитнесу. Отвечай дружелюбно, давай практичные советы по тренировкам и питанию."
- "Ты консультант по продажам. Помогай клиентам выбрать подходящий товар, отвечай профессионально."
- "Ты психолог-консультант. Выслушивай внимательно и давай поддерживающие советы."

<b>Введите роль и инструкции:</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_ai")]
        ])
        
        await message.answer(text, reply_markup=keyboard)
    
    async def handle_openai_role_input(self, message: Message, state: FSMContext):
        """Обработка ввода роли OpenAI агента"""
        if not self._is_owner(message.from_user.id):
            return
        
        if message.text == "/cancel":
            await self._cancel_and_show_ai(message, state)
            return
        
        agent_role = message.text.strip()
        
        if len(agent_role) < 10:
            await message.answer("❌ Описание роли слишком короткое (минимум 10 символов). Попробуйте еще раз:")
            return
        
        if len(agent_role) > 1000:
            await message.answer("❌ Описание роли слишком длинное (максимум 1000 символов). Попробуйте еще раз:")
            return
        
        try:
            # Получаем данные из состояния
            data = await state.get_data()
            agent_name = data.get('agent_name')
            
            if not agent_name:
                await message.answer("❌ Ошибка: имя агента потеряно. Начните заново.")
                await state.clear()
                return
            
            await message.answer("🔄 Создаю агента в OpenAI...")
            
            # Пытаемся создать агента через OpenAI сервис
            success, response_data = await self._create_agent_in_openai(agent_name, agent_role)
            
            if success:
                await message.answer(
                    f"🎉 <b>Агент успешно создан!</b>\n\n"
                    f"<b>Имя:</b> {agent_name}\n"
                    f"<b>Роль:</b> {agent_role[:100]}{'...' if len(agent_role) > 100 else ''}\n\n"
                    f"Теперь можете протестировать работу агента!",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🧪 Тестировать", callback_data="openai_test")],
                        [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
                    ])
                )
            else:
                await message.answer(
                    "❌ Ошибка при создании агента в OpenAI. Попробуйте еще раз.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
                    ])
                )
            
            await state.clear()
            
        except Exception as e:
            logger.error("Failed to create OpenAI agent", error=str(e))
            await message.answer("❌ Произошла ошибка при создании агента")
            await state.clear()
    
    async def _create_agent_in_openai(self, name: str, role: str) -> tuple[bool, dict]:
        """
        Создание агента в OpenAI
        
        Returns:
            tuple: (success: bool, response_data: dict)
        """
        try:
            # Пытаемся импортировать и использовать OpenAI сервис
            try:
                from services.openai_assistant import openai_client
                from services.openai_assistant.models import OpenAICreateAgentRequest
                
                # Создаем запрос
                request = OpenAICreateAgentRequest(
                    bot_id=self.bot_id,
                    agent_name=name,
                    agent_role=role,
                    system_prompt=f"Ты - {role}. Твое имя {name}. Отвечай полезно и дружелюбно."
                )
                
                # Валидируем запрос
                is_valid, error_msg = openai_client.validate_create_request(request)
                if not is_valid:
                    logger.error("OpenAI request validation failed", error=error_msg)
                    return False, {"error": error_msg}
                
                # Создаем агента
                agent = request.to_agent()
                response = await openai_client.create_assistant(agent)
                
                if response.success:
                    # Сохраняем в настройки бота
                    ai_settings = self.ai_assistant_settings.copy()
                    ai_settings.update({
                        'agent_type': 'openai',
                        'local_agent_id': f"openai_{int(datetime.now().timestamp())}",
                        'openai_assistant_id': response.assistant_id,
                        'agent_name': name,
                        'agent_role': role,
                        'created_at': datetime.now().isoformat()
                    })
                    
                    # Обновляем в БД
                    await self.db.update_ai_assistant(
                        self.bot_id,
                        settings=ai_settings
                    )
                    
                    # Обновляем локальные настройки
                    self.ai_assistant_settings = ai_settings
                    
                    # Безопасное обновление других компонентов
                    await self._safe_update_user_bot(ai_assistant_settings=ai_settings)
                    await self._safe_update_bot_manager(ai_assistant_settings=ai_settings)
                    
                    logger.info("OpenAI agent created successfully", 
                               bot_id=self.bot_id,
                               agent_name=name,
                               assistant_id=response.assistant_id)
                    
                    return True, {
                        "assistant_id": response.assistant_id,
                        "message": response.message
                    }
                else:
                    logger.error("OpenAI assistant creation failed", 
                               bot_id=self.bot_id,
                               error=response.error)
                    return False, {"error": response.error}
                
            except ImportError as e:
                logger.error("OpenAI service not available", error=str(e))
                # Fallback: сохраняем как заглушку для будущей реализации
                ai_settings = self.ai_assistant_settings.copy()
                ai_settings.update({
                    'agent_type': 'openai',
                    'local_agent_id': f"stub_{int(datetime.now().timestamp())}",
                    'agent_name': name,
                    'agent_role': role,
                    'created_at': datetime.now().isoformat(),
                    'status': 'stub_created'  # Помечаем как заглушку
                })
                
                await self.db.update_ai_assistant(self.bot_id, settings=ai_settings)
                self.ai_assistant_settings = ai_settings
                
                logger.info("OpenAI agent created as stub (service not available)", 
                           bot_id=self.bot_id, agent_name=name)
                
                return True, {"message": "Агент создан (тестовый режим)"}
            
        except Exception as e:
            logger.error("Exception in _create_agent_in_openai", 
                        bot_id=self.bot_id, error=str(e))
            return False, {"error": f"Внутренняя ошибка: {str(e)}"}
    
    # ============ МЕТОДЫ ПЕРЕКЛЮЧЕНИЯ С БЕЗОПАСНЫМ ОБНОВЛЕНИЕМ ============
    
    async def _toggle_ai_assistant(self, callback: CallbackQuery):
        """Переключение ИИ ассистента (ChatForYou)"""
        try:
            new_status = not self.ai_assistant_enabled
            
            ai_settings = self.ai_assistant_settings.copy()
            
            await self.db.update_ai_assistant(
                self.bot_id,
                enabled=new_status,
                settings=ai_settings
            )
            
            self.ai_assistant_enabled = new_status
            
            # Безопасное обновление
            await self._safe_update_user_bot(ai_assistant_enabled=new_status)
            await self._safe_update_bot_manager(
                ai_assistant_enabled=new_status,
                ai_assistant_settings=ai_settings
            )
            
            status_text = "включен" if new_status else "выключен"
            await callback.answer(f"ИИ агент {status_text}!", show_alert=True)
            
            await self._show_chatforyou_settings(callback)
            
        except Exception as e:
            logger.error("Failed to toggle AI assistant", error=str(e))
            await callback.answer("Ошибка при изменении настроек", show_alert=True)
    
    async def _toggle_openai_assistant(self, callback: CallbackQuery):
        """Переключение OpenAI ассистента"""
        try:
            new_status = not self.ai_assistant_enabled
            
            ai_settings = self.ai_assistant_settings.copy()
            
            await self.db.update_ai_assistant(
                self.bot_id,
                enabled=new_status,
                settings=ai_settings
            )
            
            self.ai_assistant_enabled = new_status
            
            # Безопасное обновление
            await self._safe_update_user_bot(ai_assistant_enabled=new_status)
            await self._safe_update_bot_manager(
                ai_assistant_enabled=new_status,
                ai_assistant_settings=ai_settings
            )
            
            status_text = "включен" if new_status else "выключен"
            await callback.answer(f"OpenAI агент {status_text}!", show_alert=True)
            
            await self._show_openai_settings(callback)
            
        except Exception as e:
            logger.error("Failed to toggle OpenAI assistant", error=str(e))
            await callback.answer("Ошибка при изменении настроек", show_alert=True)
    
    # ============ ОСТАЛЬНЫЕ МЕТОДЫ (без изменений) ============
    
    async def _set_assistant_id(self, callback: CallbackQuery, state: FSMContext):
        """Настройка ID ассистента (ChatForYou)"""
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
    
    async def _test_ai_assistant(self, callback: CallbackQuery, state: FSMContext):
        """Тестирование ИИ ассистента (ChatForYou)"""
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
        await state.update_data(is_test_mode=True, agent_type='chatforyou')
        
        platform_names = {
            'chatforyou': 'ChatForYou',
            'protalk': 'ProTalk'
        }
        platform_display = platform_names.get(platform, platform)
        
        bot_id_info = ""
        if platform == 'chatforyou':
            bot_id_info = f"\n<b>ID сотрудника:</b> {self.ai_assistant_settings.get('chatforyou_bot_id')}"
        
        text = f"""
🧪 <b>Тестирование ИИ агента (ChatForYou)</b>

<b>API Token:</b> {self.ai_assistant_id[:15]}...
<b>Платформа:</b> {platform_display}{bot_id_info}

Отправьте любое сообщение для тестирования ИИ агента. 

<b>Напишите ваш вопрос:</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚪 Выйти из тестирования", callback_data="admin_ai")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def _test_openai_assistant(self, callback: CallbackQuery, state: FSMContext):
        """Тестирование OpenAI ассистента"""
        local_agent_id = self.ai_assistant_settings.get('local_agent_id')
        if not local_agent_id:
            await callback.answer("❌ Сначала создайте OpenAI агента", show_alert=True)
            return
        
        await state.set_state(AISettingsStates.in_ai_conversation)
        await state.update_data(is_test_mode=True, agent_type='openai')
        
        text = f"""
🧪 <b>Тестирование OpenAI агента</b>

<b>Агент ID:</b> {local_agent_id}
<b>Модель:</b> GPT-4o-mini
<b>Режим:</b> Тестирование

Отправьте любое сообщение для тестирования OpenAI агента.

<b>Напишите ваш вопрос:</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚪 Выйти из тестирования", callback_data="admin_ai")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    # ============ ОБРАБОТЧИКИ ВВОДА CHATFORYOU (без изменений) ============
    
    async def handle_api_token_input(self, message: Message, state: FSMContext):
        """Обработка ввода API токена (существующая логика)"""
        if not self._is_owner(message.from_user.id):
            return
        
        if message.text == "/cancel":
            await self._cancel_and_show_ai(message, state)
            return
        
        api_token = message.text.strip()
        
        try:
            await message.answer("🔍 Определяем платформу...")
            
            success, platform, error_msg = await self.db.detect_and_validate_ai_platform(api_token)
            
            if not success:
                await message.answer(
                    f"❌ {error_msg}\n\n"
                    f"Проверьте токен и попробуйте еще раз:"
                )
                return
            
            await state.update_data(api_token=api_token, platform=platform)
            
            if platform == 'chatforyou':
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
                
                # Обновляем настройки
                self.ai_assistant_id = api_token
                self.ai_assistant_settings = ai_settings
                
                # Безопасное обновление
                await self._safe_update_user_bot(
                    ai_assistant_id=api_token,
                    ai_assistant_settings=ai_settings
                )
                await self._safe_update_bot_manager(
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
        """Обработка ввода ID сотрудника для ChatForYou (существующая логика)"""
        if not self._is_owner(message.from_user.id):
            return
        
        if message.text == "/cancel":
            await self._cancel_and_show_ai(message, state)
            return
        
        bot_id_value = message.text.strip()
        
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
            data = await state.get_data()
            api_token = data.get('api_token')
            platform = data.get('platform')
            
            if not api_token or platform != 'chatforyou':
                await message.answer("❌ Ошибка: данные первого шага потеряны. Начните заново.")
                await state.clear()
                return
            
            await message.answer("🔍 Проверяем соединение с ChatForYou...")
            
            success, verified_platform, error_msg = await self.db.detect_and_validate_ai_platform(
                api_token, 
                test_bot_id=bot_id_value
            )
            
            if not success:
                await message.answer(
                    f"❌ <b>Ошибка подключения к ChatForYou</b>\n\n"
                    f"{error_msg}\n\n"
                    f"Проверьте данные и попробуйте еще раз:"
                )
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
            
            # Обновляем настройки
            self.ai_assistant_id = api_token
            self.ai_assistant_settings = ai_settings
            
            # Безопасное обновление
            await self._safe_update_user_bot(
                ai_assistant_id=api_token,
                ai_assistant_settings=ai_settings
            )
            await self._safe_update_bot_manager(
                ai_assistant_id=api_token,
                ai_assistant_settings=ai_settings
            )
            
            success_text = f"""
🎉 <b>ChatForYou полностью настроен и протестирован!</b>

<b>API Token:</b> <code>{api_token[:15]}...</code>
<b>ID сотрудника:</b> {bot_id_value}
<b>Платформа:</b> ChatForYou
<b>Статус:</b> ✅ Проверено реальным API запросом

Теперь ИИ агент готов к работе с пользователями!
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🧪 Тестировать ИИ", callback_data="ai_test")],
                [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
            ])
            
            await message.answer(success_text, reply_markup=keyboard)
            await state.clear()
            
        except Exception as e:
            logger.error("Failed to validate ChatForYou configuration", error=str(e))
            await message.answer("❌ Ошибка при проверке конфигурации ChatForYou")
            await state.clear()
    
    # Совместимость
    async def handle_ai_assistant_id_input(self, message: Message, state: FSMContext):
        """Обработчик для совместимости"""
        await self.handle_api_token_input(message, state)
    
    async def handle_ai_daily_limit_input(self, message: Message, state: FSMContext):
        """Обработка ввода дневного лимита (не используется для OpenAI)"""
        if not self._is_owner(message.from_user.id):
            return
        pass
    
    # ============ ОБЩИЕ ОБРАБОТЧИКИ ============
    
    async def handle_ai_conversation(self, message: Message, state: FSMContext):
        """Обработка диалога с ИИ (для обоих типов агентов)"""
        try:
            data = await state.get_data()
            is_test_mode = data.get('is_test_mode', False)
            agent_type = data.get('agent_type', self._get_agent_type())
            user_id = message.from_user.id
            
            # В тестовом режиме только владелец может тестировать
            if is_test_mode and not self._is_owner(user_id):
                return
            
            # Отправляем typing
            await message.bot.send_chat_action(message.chat.id, "typing")
            
            ai_response = None
            
            if agent_type == 'chatforyou':
                ai_response = await self._handle_chatforyou_conversation(message, data)
            elif agent_type == 'openai':
                ai_response = await self._handle_openai_conversation(message, data)
            
            if ai_response:
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
    
    async def _handle_chatforyou_conversation(self, message: Message, data: dict) -> str:
        """Обработка диалога с ChatForYou (существующая логика)"""
        try:
            platform = self.ai_assistant_settings.get('detected_platform')
            if not platform:
                return None
            
            bot_id_value = None
            if platform == 'chatforyou':
                bot_id_value = self.ai_assistant_settings.get('chatforyou_bot_id')
                if not bot_id_value:
                    return None
            
            context = {}
            if self.ai_assistant_settings.get('context_info', True):
                context = {
                    "user_name": message.from_user.first_name or "Пользователь",
                    "username": message.from_user.username,
                    "is_test": data.get('is_test_mode', False)
                }
            
            try:
                from services.ai_assistant import ai_client
                
                ai_response = await ai_client.send_message(
                    api_token=self.ai_assistant_id,
                    message=message.text,
                    user_id=message.from_user.id,
                    bot_id=bot_id_value,
                    platform=platform,
                    context=context
                )
                
                return ai_response
            except ImportError:
                logger.warning("AI assistant service not available")
                return "🤖 ИИ сервис временно недоступен."
            
        except Exception as e:
            logger.error("Error in ChatForYou conversation", error=str(e))
            return None
    
    async def _handle_openai_conversation(self, message: Message, data: dict) -> str:
        """Обработка диалога с OpenAI агентом"""
        try:
            # Пытаемся использовать OpenAI сервис
            try:
                from services.openai_assistant import openai_client
                from services.openai_assistant.models import OpenAIConversationContext
                
                openai_assistant_id = self.ai_assistant_settings.get('openai_assistant_id')
                if not openai_assistant_id:
                    return "❌ OpenAI агент не настроен."
                
                # Создаем контекст
                context = OpenAIConversationContext(
                    user_id=message.from_user.id,
                    user_name=message.from_user.first_name or "Пользователь",
                    username=message.from_user.username,
                    bot_id=self.bot_id,
                    chat_id=message.chat.id,
                    is_admin=data.get('is_test_mode', False)
                )
                
                # Отправляем сообщение
                response = await openai_client.send_message(
                    assistant_id=openai_assistant_id,
                    message=message.text,
                    user_id=message.from_user.id,
                    context=context
                )
                
                return response or "❌ Не удалось получить ответ от OpenAI."
                
            except ImportError:
                # Fallback для случая когда OpenAI сервис недоступен
                logger.warning("OpenAI service not available, using fallback")
                agent_name = self.ai_assistant_settings.get('agent_name', 'ИИ Агент')
                return f"🤖 {agent_name}: Получил ваше сообщение '{message.text}'. Это тестовый ответ, так как OpenAI сервис еще не подключен."
            
        except Exception as e:
            logger.error("Error in OpenAI conversation", error=str(e))
            return None
    
    async def handle_ai_button_click(self, message: Message, state: FSMContext):
        """Обработка нажатия кнопки вызова ИИ"""
        try:
            user = message.from_user
            agent_type = self._get_agent_type()
            
            # Проверяем что ИИ включен и настроен
            if not self.ai_assistant_enabled or agent_type == 'none':
                await message.answer(
                    "❌ ИИ агент временно недоступен.",
                    reply_markup=ReplyKeyboardRemove()
                )
                return
            
            logger.info("🤖 AI button clicked", 
                       bot_id=self.bot_id, 
                       user_id=user.id, 
                       agent_type=agent_type)
            
            # Переводим в режим общения с ИИ
            await state.set_state(AISettingsStates.in_ai_conversation)
            await state.update_data(agent_type=agent_type)
            
            agent_name = "ИИ агентом"
            if agent_type == 'openai':
                # Получаем имя OpenAI агента
                local_agent_id = self.ai_assistant_settings.get('local_agent_id')
                if local_agent_id:
                    # Здесь будем получать имя из БД
                    saved_name = self.ai_assistant_settings.get('agent_name')
                    if saved_name:
                        agent_name = f"агентом {saved_name}"
                    else:
                        agent_name = "собственным ИИ агентом"
            
            welcome_text = f"""
🤖 <b>Добро пожаловать в чат с {agent_name}!</b>

Задавайте любые вопросы, я постараюсь помочь.

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
    
    # ============ ЗАГЛУШКИ ДЛЯ OPENAI МЕТОДОВ ============
    
    async def _edit_openai_agent(self, callback: CallbackQuery, state: FSMContext):
        """Редактирование OpenAI агента (заглушка)"""
        await callback.answer("🚧 Функция в разработке", show_alert=True)
    
    async def _delete_openai_agent(self, callback: CallbackQuery):
        """Удаление OpenAI агента (заглушка)"""
        await callback.answer("🚧 Функция в разработке", show_alert=True)
