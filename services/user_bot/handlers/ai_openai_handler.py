"""
Обработчик OpenAI агентов с поддержкой Responses API
Управляет созданием, настройкой и удалением OpenAI агентов
Поддерживает встроенные инструменты OpenAI (веб-поиск, код, файлы)
✅ ИСПРАВЛЕНО: Упрощенный интерфейс только для OpenAI агентов
✅ ДОБАВЛЕНО: Полная навигация с обработчиками всех критичных кнопок
✅ ДОБАВЛЕНО: Списание токенов для ВСЕХ пользователей включая админов
✅ ИСПРАВЛЕНО: Убрано различие админ/пользователь в тестировании
✅ ИСПРАВЛЕНО: Проверки на голосовые сообщения (message.text может быть None)
✅ ИСПРАВЛЕНО: Возврат строки ошибки вместо None
✅ ДОБАВЛЕНО: Поддержка голосовых сообщений через handle_openai_conversation_with_text
✅ ДОБАВЛЕНО: Полная система управления файлами и векторными хранилищами
✅ ДОБАВЛЕНО: Улучшенные методы для сохранения и синхронизации vector stores
✅ НОВОЕ: Сохранение информации о файлах в БД для показа в меню "Мои файлы"
✅ НОВОЕ: Батчевая загрузка с показом общего размера и счетчика файлов
✅ НОВОЕ: Полная очистка файлов из БД при удалении базы знаний
✅ ОБНОВЛЕНО: Сохранение vector store при очистке файлов для повторного использования
"""

import structlog
import time
from datetime import datetime
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from ..states import AISettingsStates
from ..keyboards import AIKeyboards

logger = structlog.get_logger()


class OpenAIHandler:
    """Обработчик OpenAI агентов с поддержкой Responses API"""
    
    def __init__(self, db, bot_config: dict, ai_assistant, user_bot):
        self.db = db
        self.bot_config = bot_config
        self.bot_id = bot_config['bot_id']
        self.owner_user_id = bot_config['owner_user_id']
        self.bot_username = bot_config['bot_username']
        self.ai_assistant = ai_assistant
        self.user_bot = user_bot
        
        # Хранимые ссылки на основной обработчик (будут обновляться)
        self._ai_assistant_id = bot_config.get('ai_assistant_id')
        self._ai_assistant_settings = bot_config.get('ai_assistant_settings', {})
        
        # Временное хранилище для данных состояния
        self._current_state_data = {}
        
        logger.info("🎨 OpenAIHandler initialized", 
                   bot_id=self.bot_id,
                   has_openai_agent=bool(self._ai_assistant_id))

    # ===== СВОЙСТВА ДЛЯ ДОСТУПА К АКТУАЛЬНЫМ ДАННЫМ =====
    
    @property
    def ai_assistant_id(self):
        """Получение актуального ID агента"""
        return self._ai_assistant_id
    
    @ai_assistant_id.setter
    def ai_assistant_id(self, value):
        """Установка ID агента"""
        self._ai_assistant_id = value
    
    @property 
    def ai_assistant_settings(self):
        """Получение актуальных настроек агента"""
        return self._ai_assistant_settings
    
    @ai_assistant_settings.setter
    def ai_assistant_settings(self, value):
        """Установка настроек агента"""
        self._ai_assistant_settings = value

    # ===== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ =====
    
    def _get_message_text(self, message: Message) -> str:
        """✅ НОВЫЙ: Безопасное получение текста сообщения с обработкой голосовых"""
        if message.text:
            return message.text
        elif message.voice:
            return "[Голосовое сообщение]"
        elif message.video_note:
            return "[Видео-сообщение]"
        elif message.audio:
            return "[Аудио-файл]"
        elif message.document:
            return "[Документ]"
        elif message.photo:
            return "[Фото]"
        elif message.video:
            return "[Видео]"
        elif message.sticker:
            return "[Стикер]"
        else:
            return "[Неподдерживаемый тип сообщения]"
    
    def _is_text_message(self, message: Message) -> bool:
        """✅ НОВЫЙ: Проверка является ли сообщение текстовым"""
        return bool(message.text)

    # ===== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ СИНХРОНИЗАЦИИ =====
    
    async def _sync_with_db_state(self, force: bool = False) -> bool:
        """✅ НОВЫЙ: Синхронизация локального состояния с БД"""
        try:
            logger.info("🔄 Syncing local state with database", 
                       bot_id=self.bot_id,
                       force=force,
                       current_agent_id=self.ai_assistant_id)
            
            fresh_bot = await self.db.get_bot_by_id(self.bot_id, fresh=True)
            
            if fresh_bot:
                # Сохраняем старые значения для сравнения
                old_agent_id = self.ai_assistant_id
                old_ai_type = self.ai_assistant_settings.get('agent_type', 'none')
                
                # Синхронизируем с БД
                self.ai_assistant_id = fresh_bot.openai_agent_id
                
                if fresh_bot.openai_settings:
                    self.ai_assistant_settings = fresh_bot.openai_settings.copy()
                    # Убеждаемся что тип установлен правильно
                    if fresh_bot.ai_assistant_type == 'openai':
                        self.ai_assistant_settings['agent_type'] = 'openai'
                else:
                    # Если настроек нет, но тип есть
                    if fresh_bot.ai_assistant_type == 'openai' and fresh_bot.openai_agent_id:
                        self.ai_assistant_settings = {
                            'agent_type': 'openai',
                            'agent_name': fresh_bot.openai_agent_name or 'AI Агент',
                            'agent_role': fresh_bot.openai_agent_instructions or 'Полезный помощник'
                        }
                    else:
                        self.ai_assistant_settings = {'agent_type': 'none'}
                
                logger.info("✅ State synchronized with database", 
                           bot_id=self.bot_id,
                           old_agent_id=old_agent_id,
                           new_agent_id=self.ai_assistant_id,
                           old_ai_type=old_ai_type,
                           new_ai_type=self.ai_assistant_settings.get('agent_type'),
                           ai_enabled=fresh_bot.ai_assistant_enabled,
                           db_ai_type=fresh_bot.ai_assistant_type)
                
                return True
            else:
                logger.warning("⚠️ Could not get fresh bot data from DB")
                return False
                
        except Exception as e:
            logger.error("💥 Failed to sync with database state", 
                        bot_id=self.bot_id,
                        error=str(e),
                        error_type=type(e).__name__)
            return False

    # ===== ОСНОВНЫЕ МЕТОДЫ УПРАВЛЕНИЯ =====
    
    def _has_openai_agent(self) -> bool:
        """✅ ИСПРАВЛЕНО: Правильная проверка наличия OpenAI агента"""
        return (
            self.ai_assistant_settings.get('agent_type') == 'openai' and
            bool(self.ai_assistant_id) and
            self.ai_assistant_settings.get('creation_method') in ['responses_api', 'real_openai_api']
        )
    
    async def handle_openai_action(self, callback: CallbackQuery, state: FSMContext, is_owner_check):
        """✅ ИСПРАВЛЕНО: Обработка действий OpenAI + НОВЫЕ ОБРАБОТЧИКИ VECTOR STORES"""
        logger.info("🎯 OpenAI action callback", 
                   user_id=callback.from_user.id,
                   callback_data=callback.data)
        
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        action = callback.data.replace("openai_", "")
        
        # ✅ ЗАЩИТА: НЕ обрабатываем confirm_delete через общий хендлер
        if action == "confirm_delete":
            logger.warning("⚠️ confirm_delete reached general handler, ignoring")
            return
        
        logger.info("🔄 Processing OpenAI action", 
                   action=action,
                   bot_id=self.bot_id)
        
        # ===== ОСНОВНЫЕ ДЕЙСТВИЯ OPENAI =====
        if action == "create":
            await self._create_openai_agent(callback, state)
        elif action == "test":
            await self._test_openai_assistant(callback, state)
        elif action == "delete":
            await self._delete_openai_agent(callback)
        elif action == "tools_settings":
            await self.handle_tools_settings(callback, is_owner_check)
        elif action == "toggle_web_search":
            await self.handle_toggle_web_search(callback, is_owner_check)
        elif action == "toggle_code_interpreter":
            await self.handle_toggle_code_interpreter(callback, is_owner_check)
        elif action == "toggle_file_search":
            await self.handle_toggle_file_search(callback, is_owner_check)
        elif action == "upload_files":
            await self.handle_upload_files(callback, is_owner_check)
        elif action == "start_upload":
            await self.handle_start_upload(callback, state, is_owner_check)
        elif action == "finish_upload":
            await self.handle_finish_upload(callback, state, is_owner_check)
        elif action == "manage_files":
            await self.handle_manage_files(callback, is_owner_check)
        elif action == "clear_knowledge":
            await self.handle_clear_knowledge(callback, is_owner_check)
        elif action == "edit":
            await self.handle_edit_agent(callback, is_owner_check)
        elif action == "edit_name":
            await self.handle_edit_name(callback, state)
        elif action == "edit_prompt":
            await self.handle_edit_prompt(callback, state)
        elif action == "sync_data":
            await self.handle_sync_agent_data(callback, is_owner_check)
        # ✅ НОВЫЕ ОБРАБОТЧИКИ VECTOR STORES
        elif action == "verify_file_search":
            await self.handle_verify_file_search(callback, is_owner_check)
        elif action == "force_sync_vectors":
            await self.handle_force_sync_vectors(callback, is_owner_check)
        elif action == "confirm_clear_knowledge":
            await self.handle_confirm_clear_knowledge(callback, is_owner_check)
        else:
            logger.warning("⚠️ Unknown OpenAI action", action=action)
    
    async def handle_navigation_action(self, callback: CallbackQuery, state: FSMContext, is_owner_check):
        """✅ НОВЫЙ: Обработчик критичных кнопок навигации"""
        logger.info("🧭 Navigation action callback", 
                   user_id=callback.from_user.id,
                   callback_data=callback.data)
        
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        action = callback.data
        
        logger.info("🔄 Processing navigation action", 
                   action=action,
                   bot_id=self.bot_id)
        
        # ===== КРИТИЧНЫЕ ОБРАБОТЧИКИ НАВИГАЦИИ =====
        if action == "admin_panel":
            await self.handle_admin_panel(callback, state)
        elif action == "admin_ai":
            await self.handle_admin_ai(callback, state)
        elif action == "admin_main":
            await self.handle_admin_main(callback, state)
        else:
            logger.warning("⚠️ Unknown navigation action", action=action)

    # ===== КРИТИЧНЫЕ ОБРАБОТЧИКИ НАВИГАЦИИ =====
    
    async def handle_admin_panel(self, callback: CallbackQuery, state: FSMContext):
        """✅ НОВЫЙ: Возврат в главную админ панель"""
        logger.info("🏠 Returning to admin panel", 
                   user_id=callback.from_user.id,
                   bot_id=self.bot_id)
        
        await state.clear()
        
        text = f"""
🔧 <b>Админ панель бота @{self.bot_username}</b>

Управление вашим ботом:
"""
        
        # Импортируем клавиатуру админ панели
        try:
            from ..keyboards import AdminKeyboards
            keyboard = AdminKeyboards.main_menu()
        except Exception as e:
            logger.error("💥 Error importing AdminKeyboards", error=str(e))
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🤖 Настройки ИИ", callback_data="admin_ai")],
                [InlineKeyboardButton(text="⚙️ Настройки бота", callback_data="admin_settings")],
                [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")]
            ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def handle_exit_conversation(self, callback: CallbackQuery, state: FSMContext):
        """✅ НОВЫЙ: Завершение диалога с ИИ - переход в главное меню"""
        logger.info("🚪 Exiting AI conversation", 
                   user_id=callback.from_user.id,
                   bot_id=self.bot_id)
        
        await state.clear()
        
        # ✅ ИСПРАВЛЕНО: Возвращаемся в главное меню вместо настроек ИИ
        await self.handle_admin_ai(callback, state)
    
    async def handle_admin_ai(self, callback: CallbackQuery, state: FSMContext):
        """✅ НОВЫЙ: Переход к настройкам ИИ"""
        logger.info("🤖 Going to AI settings", 
                   user_id=callback.from_user.id,
                   bot_id=self.bot_id)
        
        await state.clear()
        
        # Проверяем наличие агента и показываем соответствующий интерфейс
        await self._sync_with_db_state()
        
        agent_type = self.ai_assistant_settings.get('agent_type', 'none')
        has_agent = bool(self.ai_assistant_id) and agent_type == 'openai'
        
        await self.show_settings(callback, has_ai_agent=has_agent)
    
    async def handle_admin_main(self, callback: CallbackQuery, state: FSMContext):
        """✅ НОВЫЙ: Возврат в главное меню"""
        logger.info("🏠 Returning to main menu", 
                   user_id=callback.from_user.id,
                   bot_id=self.bot_id)
        
        await state.clear()
        
        text = f"""
🤖 <b>Бот @{self.bot_username}</b>

Главное меню управления ботом.
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔧 Админ панель", callback_data="admin_panel")],
            [InlineKeyboardButton(text="🤖 Настройки ИИ", callback_data="admin_ai")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)

    async def show_settings(self, callback: CallbackQuery, has_ai_agent: bool):
        """✅ УПРОЩЕНО: Показ только OpenAI интерфейса"""
        logger.info("📋 Displaying OpenAI settings", 
                   bot_id=self.bot_id,
                   has_ai_agent=has_ai_agent)
        
        # ✅ Получаем свежие данные из БД
        await self._sync_with_db_state()
        
        # Проверяем наличие OpenAI агента
        agent_type = self.ai_assistant_settings.get('agent_type', 'none')
        openai_assistant_id = self.ai_assistant_id if agent_type == 'openai' else None
        has_real_agent = bool(openai_assistant_id)
        
        logger.info("🔍 OpenAI interface check", 
                   agent_type=agent_type,
                   openai_assistant_id=openai_assistant_id,
                   has_real_agent=has_real_agent)
        
        if not has_real_agent:
            # ✅ НОВОЕ: Показываем меню создания OpenAI агента
            await self._show_create_openai_menu(callback)
        else:
            # ✅ ИСПРАВЛЕНО: Показываем настройки существующего агента (БЕЗ кнопки смены типа)
            await self._show_existing_agent_settings(callback, openai_assistant_id)

    async def _show_create_openai_menu(self, callback: CallbackQuery):
        """✅ НОВОЕ: Меню создания OpenAI агента"""
        text = """
🎨 <b>Создание ИИ агента на базе OpenAI</b>

<b>🚀 OpenAI GPT-4o + Responses API</b>

<b>Возможности вашего агента:</b>
✨ Контекст сохраняется автоматически на серверах OpenAI
🧠 Самая продвинутая модель GPT-4o
🛠️ Встроенные инструменты (веб-поиск, код, файлы)
⚡ Быстрые ответы без задержек
📊 Не нужно отправлять всю историю чата
🎯 Настройка роли и поведения агента

<b>Как это работает:</b>
1. Вы придумываете имя и роль для агента
2. Агент создается на серверах OpenAI через Responses API
3. Пользователи общаются с агентом прямо в вашем боте
4. Контекст и история сохраняются автоматически

<b>Готовы создать своего ИИ агента?</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎨 Создать OpenAI агента", callback_data="openai_create")],
            [InlineKeyboardButton(text="◀️ Назад в админ панель", callback_data="admin_panel")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)

    async def _show_existing_agent_settings(self, callback: CallbackQuery, openai_assistant_id: str):
        """✅ ИСПРАВЛЕНО: Настройки существующего агента (БЕЗ кнопки смены типа)"""
        # Получаем информацию об агенте
        agent_name = self.ai_assistant_settings.get('agent_name')
        creation_method = self.ai_assistant_settings.get('creation_method', 'unknown')
        
        # Получаем информацию о включенных инструментах
        settings = self.ai_assistant_settings
        enabled_tools_count = sum([
            settings.get('enable_web_search', False),
            settings.get('enable_code_interpreter', False),
            settings.get('enable_file_search', False),
            settings.get('enable_image_generation', False)
        ])
        
        logger.info("🔍 OpenAI agent info", 
                   openai_assistant_id=openai_assistant_id,
                   agent_name=agent_name,
                   creation_method=creation_method,
                   enabled_tools_count=enabled_tools_count)
        
        agent_info = f"ID: {openai_assistant_id[:15]}..."
        agent_details = ""
        
        if agent_name:
            agent_info = f"{agent_name} (ID: {openai_assistant_id[:15]}...)"
        
        if creation_method == 'fallback_stub':
            agent_details += "\n⚠️ Режим: Тестовый (OpenAI недоступен)"
        elif creation_method == 'responses_api':
            agent_details += "\n✅ Режим: Responses API (Автоматический контекст)"
        elif creation_method == 'real_openai_api':
            agent_details += "\n✅ Режим: Реальный OpenAI"
        
        if enabled_tools_count > 0:
            agent_details += f"\n🧰 Инструменты: {enabled_tools_count} включено"
        
        text = f"""
🎨 <b>Собственный ИИ Агент</b>

<b>Текущие настройки:</b>
🎯 Агент: {agent_info}{agent_details}
🧠 Модель: GPT-4o (Responses API)
🔄 Контекст: Автоматическое управление
⚡ Лимиты: Управляются токенами

<b>Преимущества Responses API:</b>
- Контекст сохраняется автоматически на серверах OpenAI
- Встроенные инструменты (поиск, код, файлы)
- Не нужно отправлять всю историю с каждым сообщением
- Быстрые ответы и стабильная работа 24/7

<b>Управление агентом:</b>
"""
        
        # ✅ ИСПРАВЛЕНО: БЕЗ кнопки смены типа агента
        keyboard = AIKeyboards.openai_settings_menu(True)
        
        await callback.message.edit_text(text, reply_markup=keyboard)

    # ===== СОЗДАНИЕ АГЕНТА =====
    
    async def _create_openai_agent(self, callback: CallbackQuery, state: FSMContext):
        """✅ ИСПРАВЛЕНО: Начало создания OpenAI агента с синхронизацией"""
        logger.info("🎨 Starting OpenAI agent creation flow", 
                   user_id=callback.from_user.id,
                   bot_id=self.bot_id)
        
        # ✅ КРИТИЧНО: Принудительная синхронизация перед созданием
        logger.info("🔄 Pre-creation state sync check", 
                   current_agent_id=self.ai_assistant_id,
                   current_agent_type=self.ai_assistant_settings.get('agent_type'))
        
        sync_success = await self._sync_with_db_state(force=True)
        
        if sync_success:
            logger.info("✅ Pre-creation sync completed", 
                       synced_agent_id=self.ai_assistant_id,
                       synced_agent_type=self.ai_assistant_settings.get('agent_type'))
        else:
            logger.warning("⚠️ Pre-creation sync failed, continuing with fallback cleanup")
            # Fallback - принудительная очистка
            self.ai_assistant_id = None
            self.ai_assistant_settings = {'agent_type': 'openai'}
        
        await state.set_state(AISettingsStates.admin_waiting_for_openai_name)
        
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

    async def handle_name_input(self, message: Message, state: FSMContext, is_owner_check):
        """✅ ИСПРАВЛЕНО: Обработка ввода имени OpenAI агента с проверкой на голосовые сообщения"""
        logger.info("📝 OpenAI agent name input", 
                   user_id=message.from_user.id,
                   has_text=self._is_text_message(message),
                   message_type=type(message).__name__,
                   bot_id=self.bot_id)
        
        if not is_owner_check(message.from_user.id):
            return
        
        # ✅ ИСПРАВЛЕНО: Проверяем наличие текста в сообщении
        if not self._is_text_message(message):
            await message.answer("❌ Пожалуйста, отправьте текстовое сообщение с именем агента.")
            return
        
        message_text = message.text.strip()
        
        if message_text == "/cancel":
            await self._cancel_and_show_ai(message, state)
            return
        
        agent_name = message_text
        
        logger.info("🔍 Validating agent name", 
                   agent_name=agent_name,
                   name_length=len(agent_name))
        
        if len(agent_name) < 2:
            await message.answer("❌ Имя агента должно быть не менее 2 символов. Попробуйте еще раз:")
            return
        
        if len(agent_name) > 100:
            await message.answer("❌ Имя агента слишком длинное (максимум 100 символов). Попробуйте еще раз:")
            return
        
        # Сохраняем имя в состоянии
        await state.update_data(agent_name=agent_name)
        await state.set_state(AISettingsStates.admin_waiting_for_openai_role)
        
        logger.info("✅ Agent name accepted, moving to role input", 
                   agent_name=agent_name)
        
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

    async def handle_role_input(self, message: Message, state: FSMContext, is_owner_check):
        """✅ ИСПРАВЛЕНО: Обработка ввода роли OpenAI агента с улучшенным UX + проверка голосовых"""
        logger.info("📝 OpenAI agent role input", 
                   user_id=message.from_user.id,
                   has_text=self._is_text_message(message),
                   input_length=len(message.text) if message.text else 0,
                   bot_id=self.bot_id)
        
        if not is_owner_check(message.from_user.id):
            return
        
        # ✅ ИСПРАВЛЕНО: Проверяем наличие текста в сообщении
        if not self._is_text_message(message):
            await message.answer("❌ Пожалуйста, отправьте текстовое сообщение с описанием роли агента.")
            return
        
        message_text = message.text.strip()
        
        if message_text == "/cancel":
            await self._cancel_and_show_ai(message, state)
            return
        
        agent_role = message_text
        
        logger.info("🔍 Validating agent role", 
                   role_length=len(agent_role))
        
        if len(agent_role) < 10:
            await message.answer("❌ Описание роли слишком короткое (минимум 10 символов). Попробуйте еще раз:")
            return
        
        if len(agent_role) > 1000:
            await message.answer("❌ Описание роли слишком длинное (максимум 1000 символов). Попробуйте еще раз:")
            return
        
        try:
            # Сохраняем chat_id для токеновой системы
            admin_chat_id = message.chat.id
            await state.update_data(admin_chat_id=admin_chat_id)
            
            logger.info("📱 Admin chat ID captured for token tracking", 
                       admin_chat_id=admin_chat_id, user_id=message.from_user.id)
            
            # Получаем данные из состояния
            data = await state.get_data()
            agent_name = data.get('agent_name')
            
            logger.info("📊 Agent creation data", 
                       agent_name=agent_name,
                       agent_role=agent_role)
            
            if not agent_name:
                logger.error("❌ Agent name lost from state")
                await message.answer("❌ Ошибка: имя агента потеряно. Начните заново.")
                await state.clear()
                return
            
            # Показываем прогресс пользователю
            progress_message = await message.answer("🔄 Создаю агента через Responses API...")
            
            # Сохраняем состояние для передачи в _create_agent_in_openai
            self._current_state_data = data
            
            logger.info("🚀 Calling _create_agent_in_openai")
            success, response_data = await self._create_agent_in_openai(agent_name, agent_role)
            
            logger.info("📊 Agent creation result", 
                       success=success,
                       response_keys=list(response_data.keys()) if response_data else None)
            
            if success:
                creation_method = response_data.get('creation_method', 'unknown')
                duration = response_data.get('total_duration', 'unknown')
                
                success_message = f"🎉 <b>Агент успешно создан!</b>\n\n"
                success_message += f"<b>Имя:</b> {agent_name}\n"
                success_message += f"<b>Роль:</b> {agent_role[:100]}{'...' if len(agent_role) > 100 else ''}\n"
                
                if creation_method == 'responses_api':
                    success_message += f"\n✅ <b>Создан через Responses API</b> за {duration}\n"
                    success_message += f"• Автоматическое управление контекстом\n"
                    success_message += f"• Встроенные инструменты OpenAI\n"
                elif creation_method == 'fallback_stub':
                    success_message += f"\n⚠️ <b>Тестовый режим</b> (Responses API недоступен)\n"
                
                success_message += f"\nТеперь можете протестировать работу агента!"
                
                await progress_message.edit_text(
                    success_message,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🧪 Тестировать", callback_data="openai_test")],
                        [InlineKeyboardButton(text="🧰 Настроить инструменты", callback_data="openai_tools_settings")],
                        [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
                    ])
                )
            else:
                error_msg = response_data.get('error', 'Неизвестная ошибка')
                
                # Анализируем тип ошибки и даем понятное объяснение
                if "500" in error_msg or "server_error" in error_msg:
                    user_friendly_error = """
❌ <b>Временная проблема с OpenAI</b>

Серверы OpenAI сейчас перегружены. Это частая ситуация.

<b>Что делать:</b>
- Попробуйте через 2-3 минуты
- Или создайте агента позже
- Проблема решится автоматически

<b>Это НЕ ошибка вашего бота!</b>
"""
                elif "429" in error_msg or "rate" in error_msg:
                    user_friendly_error = """
❌ <b>Превышен лимит запросов</b>

OpenAI ограничивает количество запросов в минуту.

<b>Что делать:</b>
- Подождите 1-2 минуты
- Попробуйте создать агента снова
- Это временное ограничение
"""
                elif "401" in error_msg or "unauthorized" in error_msg:
                    user_friendly_error = """
❌ <b>Проблема с API ключом</b>

Возможно API ключ OpenAI неактивен.

<b>Обратитесь к администратору</b>
"""
                else:
                    user_friendly_error = f"""
❌ <b>Ошибка при создании агента</b>

{error_msg}

<b>Попробуйте еще раз через несколько минут</b>
"""
                
                logger.error("❌ Agent creation failed", error=error_msg)
                
                await progress_message.edit_text(
                    user_friendly_error,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="openai_create")],
                        [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
                    ])
                )
            
            await state.clear()
            
        except Exception as e:
            logger.error("💥 Failed to create OpenAI agent", 
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            await message.answer(
                "❌ Произошла ошибка при создании агента. Попробуйте еще раз.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
                ])
            )
            await state.clear()

    async def _create_agent_in_openai(self, name: str, role: str) -> tuple[bool, dict]:
        """Создание агента через Responses API"""
        logger.info("🎬 Starting OpenAI agent creation via Responses API", 
                   bot_id=self.bot_id,
                   owner_user_id=self.owner_user_id,
                   agent_name=name,
                   agent_role=role)
        
        overall_start_time = time.time()
        
        try:
            # Импорт обновленного сервиса
            logger.info("📦 Importing OpenAI Responses API service...")
            
            try:
                from services.openai_assistant import openai_client
                from services.openai_assistant.models import OpenAIResponsesRequest
                
                logger.info("✅ OpenAI Responses API service imported successfully", 
                           client_type=type(openai_client).__name__)
                
                # Проверка доступности клиента
                if not openai_client.is_available():
                    logger.warning("⚠️ OpenAI client reports not available")
                    return False, {"error": "OpenAI сервис недоступен"}
                
                # Получаем admin_chat_id из FSM состояния
                admin_chat_id = None
                try:
                    if hasattr(self, '_current_state_data'):
                        admin_chat_id = self._current_state_data.get('admin_chat_id')
                    
                    if not admin_chat_id:
                        admin_chat_id = self.owner_user_id
                        
                    logger.info("📱 Admin chat ID for Responses API", 
                               admin_chat_id=admin_chat_id)
                        
                except Exception as e:
                    logger.warning("⚠️ Could not determine admin_chat_id", error=str(e))
                    admin_chat_id = self.owner_user_id
                
                # Создание запроса для Responses API
                logger.info("📋 Creating Responses API agent request...")
                
                system_prompt = f"Ты - {role}. Твое имя {name}. Отвечай полезно и дружелюбно."
                
                request = OpenAIResponsesRequest(
                    bot_id=self.bot_id,
                    agent_name=name,
                    agent_role=role,
                    system_prompt=system_prompt,
                    model="gpt-4o",  # Используем лучшую модель для Responses API
                    temperature=0.7,
                    max_tokens=4000,
                    store_conversations=True,    # ВКЛЮЧАЕМ автоматическое хранение контекста
                    conversation_retention=30,   # Храним 30 дней
                    enable_streaming=True,       # Потоковые ответы
                    enable_web_search=False,     # Пока без дополнительных инструментов
                    enable_code_interpreter=False,
                    enable_file_search=False,
                    enable_image_generation=False
                )
                
                logger.info("✅ Responses API request created", 
                           agent_name=request.agent_name,
                           model=request.model,
                           store_conversations=request.store_conversations,
                           tools_enabled=sum([
                               request.enable_web_search,
                               request.enable_code_interpreter,
                               request.enable_file_search,
                               request.enable_image_generation
                           ]))
                
                # Валидация запроса
                logger.info("🔍 Validating Responses API request...")
                
                is_valid, error_msg = openai_client.validate_create_request(request)
                
                if not is_valid:
                    logger.error("❌ Responses API request validation failed", 
                               validation_error=error_msg)
                    return False, {"error": error_msg}
                
                logger.info("✅ Request validation passed")
                
                # Конвертация в агента
                agent = request.to_agent()
                
                logger.info("✅ Agent object created for Responses API", 
                           agent_name=agent.agent_name,
                           store_conversations=agent.store_conversations,
                           enable_streaming=agent.enable_streaming)
                
                # ОСНОВНОЙ ВЫЗОВ СОЗДАНИЯ ЧЕРЕЗ RESPONSES API
                logger.info("🚀 Calling OpenAI Responses API assistant creation...")
                
                creation_start_time = time.time()
                
                response = await openai_client.create_assistant(agent)
                
                creation_duration = time.time() - creation_start_time
                
                logger.info("📡 OpenAI Responses API call completed", 
                           duration=f"{creation_duration:.2f}s",
                           response_success=response.success,
                           response_text=response.output_text if response.success else None,
                           response_error=response.error if not response.success else None,
                           response_id=response.response_id if response.success else None)
                
                if response.success:
                    # УСПЕШНОЕ СОЗДАНИЕ ЧЕРЕЗ RESPONSES API
                    logger.info("🎉 OpenAI agent created successfully via Responses API")
                    
                    assistant_id = response.response_id  # Используем response_id как assistant_id
                    
                    # Сохраняем агента с Responses API настройками
                    save_success = await self._save_agent_with_responses_api(
                        assistant_id=assistant_id,
                        name=name,
                        role=role,
                        system_prompt=system_prompt,
                        agent=agent,
                        admin_chat_id=admin_chat_id
                    )
                    
                    if not save_success:
                        logger.error("❌ Failed to save Responses API agent")
                        return False, {"error": "Ошибка при сохранении агента"}
                    
                    logger.info("✅ Responses API agent created and saved")
                    
                    # ✅ ИСПРАВЛЕНО: Синхронизируем после создания
                    await self._sync_with_db_state(force=True)
                    
                    # Безопасное обновление других компонентов
                    try:
                        await self._safe_update_user_bot(
                            ai_assistant_id=assistant_id,
                            ai_assistant_settings=self.ai_assistant_settings
                        )
                        logger.info("✅ UserBot updated for Responses API")
                    except Exception as update_error:
                        logger.error("⚠️ UserBot update failed", error=str(update_error))
                    
                    try:
                        await self._safe_update_bot_manager(
                            ai_assistant_id=assistant_id,
                            ai_assistant_settings=self.ai_assistant_settings
                        )
                        logger.info("✅ BotManager updated for Responses API")
                    except Exception as update_error:
                        logger.error("⚠️ BotManager update failed", error=str(update_error))
                    
                    total_duration = time.time() - overall_start_time
                    
                    logger.info("🏁 Responses API agent creation completed successfully", 
                               bot_id=self.bot_id,
                               agent_name=name,
                               assistant_id=assistant_id,
                               total_duration=f"{total_duration:.2f}s",
                               creation_duration=f"{creation_duration:.2f}s")
                    
                    return True, {
                        "assistant_id": assistant_id,
                        "message": response.output_text,
                        "creation_method": "responses_api",
                        "creation_duration": creation_duration,
                        "total_duration": total_duration
                    }
                    
                else:
                    # ОШИБКА СОЗДАНИЯ
                    logger.error("💥 OpenAI Responses API creation failed", 
                               bot_id=self.bot_id,
                               agent_name=name,
                               error=response.error,
                               duration=f"{creation_duration:.2f}s")
                    
                    return False, {"error": response.error}
                    
            except ImportError as import_error:
                # FALLBACK ПРИ ОТСУТСТВИИ OPENAI СЕРВИСА
                logger.warning("📦 OpenAI Responses API service not available, using fallback", 
                              import_error=str(import_error))
                
                # Создание заглушки (если нужно для обратной совместимости)
                fake_assistant_id = f"asst_fallback_{int(datetime.now().timestamp())}"
                
                ai_settings = self.ai_assistant_settings.copy()
                ai_settings.update({
                    'agent_type': 'openai',
                    'agent_name': name,
                    'agent_role': role,
                    'created_at': datetime.now().isoformat(),
                    'status': 'stub_created',
                    'creation_method': 'fallback_stub',
                    'reason': 'responses_api_service_not_available',
                    'import_error': str(import_error)
                })
                
                try:
                    await self.db.update_ai_assistant(
                        self.bot_id, 
                        assistant_id=fake_assistant_id,
                        settings=ai_settings
                    )
                    
                    # ✅ ИСПРАВЛЕНО: Синхронизируем после создания fallback
                    await self._sync_with_db_state(force=True)
                    
                    total_duration = time.time() - overall_start_time
                    
                    logger.info("✅ Stub agent created (Responses API unavailable)", 
                               bot_id=self.bot_id,
                               agent_name=name,
                               fake_assistant_id=fake_assistant_id,
                               total_duration=f"{total_duration:.2f}s")
                    
                    return True, {
                        "message": "Агент создан (тестовый режим - Responses API недоступен)",
                        "assistant_id": fake_assistant_id,
                        "creation_method": "fallback_stub",
                        "total_duration": total_duration
                    }
                    
                except Exception as db_error:
                    logger.error("💥 Failed to save stub configuration", error=str(db_error))
                    return False, {"error": f"Fallback creation failed: {str(db_error)}"}
                    
        except Exception as e:
            # ОБЩАЯ ОБРАБОТКА ОШИБОК
            total_duration = time.time() - overall_start_time
            
            logger.error("💥 Exception in _create_agent_in_openai (Responses API)", 
                        bot_id=self.bot_id,
                        agent_name=name,
                        exception_type=type(e).__name__,
                        exception_message=str(e),
                        total_duration=f"{total_duration:.2f}s",
                        exc_info=True)
            
            return False, {"error": f"Внутренняя ошибка: {str(e)}"}

    async def _save_agent_with_responses_api(self, assistant_id: str, name: str, role: str, 
                                           system_prompt: str, agent: any, admin_chat_id: int) -> bool:
        """✅ ИСПРАВЛЕНО: Сохранение агента с правильной синхронизацией"""
        try:
            logger.info("💾 Saving OpenAI agent via new DatabaseManager architecture", 
                       assistant_id=assistant_id, 
                       admin_chat_id=admin_chat_id,
                       bot_id=self.bot_id)
            
            # ✅ ИСПРАВЛЕНО: Правильная структура данных с agent_type
            agent_settings = {
                'agent_type': 'openai',  # ✅ КРИТИЧНО: Устанавливаем тип агента
                'agent_name': name,
                'agent_role': role,
                'system_prompt': system_prompt,
                'model_used': agent.model,
                'model': agent.model,  # Дублируем для совместимости
                'admin_chat_id': admin_chat_id,
                'created_at': datetime.now().isoformat(),
                'creation_method': 'responses_api',
                
                # Responses API специфичные настройки
                'store_conversations': agent.store_conversations,
                'conversation_retention': agent.conversation_retention,
                'enable_streaming': getattr(agent, 'enable_streaming', True),
                'enable_web_search': False,
                'enable_code_interpreter': False,
                'enable_file_search': False,
                'enable_image_generation': False,
                
                # ✅ НОВОЕ: Настройки для синхронизации
                'openai_settings': {
                    'api_type': 'responses',
                    'store_conversations': agent.store_conversations,
                    'conversation_retention': agent.conversation_retention,
                    'enable_streaming': getattr(agent, 'enable_streaming', True),
                    'enable_web_search': False,
                    'enable_code_interpreter': False,
                    'enable_file_search': False,
                    'enable_image_generation': False,
                    'temperature': 0.7,
                    'max_tokens': 4000,
                    'top_p': 1.0,
                    'frequency_penalty': 0.0,
                    'presence_penalty': 0.0,
                    # ✅ НОВОЕ: Массив для хранения информации о файлах
                    'uploaded_files': [],
                    'files_last_updated': datetime.now().isoformat()
                }
            }
            
            logger.info("📊 Agent settings prepared", 
                       agent_type=agent_settings['agent_type'],
                       agent_name=agent_settings['agent_name'],
                       creation_method=agent_settings['creation_method'])
            
            # ✅ ИСПРАВЛЕНО: Инициализируем токеновый баланс
            try:
                # Проверяем существует ли метод
                if hasattr(self.db, 'create_or_update_user_with_tokens'):
                    user_data = {'id': self.owner_user_id}
                    await self.db.create_or_update_user_with_tokens(
                        user_data=user_data,
                        admin_chat_id=admin_chat_id
                    )
                    logger.info("✅ Token balance initialized")
                else:
                    logger.warning("⚠️ Token balance initialization method not available")
            except Exception as token_error:
                logger.warning("⚠️ Failed to initialize token balance", error=str(token_error))
            
            # ✅ ИСПРАВЛЕНО: Используем правильный метод синхронизации
            from database.managers.ai_manager import AIManager
            
            success = await AIManager.save_openai_agent_config_responses_api(
                bot_id=self.bot_id,
                agent_id=assistant_id,
                config=agent_settings
            )
            
            if success:
                logger.info("✅ OpenAI agent saved via new DatabaseManager")
                
                # ✅ ДОПОЛНИТЕЛЬНО: Обновляем кеш бота
                await self.db.expire_bot_cache(self.bot_id)
                
                return True
            else:
                logger.error("❌ Failed to save OpenAI agent via DatabaseManager")
                return False
                
        except Exception as e:
            logger.error("💥 Failed to save OpenAI agent", 
                        bot_id=self.bot_id,
                        assistant_id=assistant_id,
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            return False

    # ===== ТЕСТИРОВАНИЕ =====
    
    async def _test_openai_assistant(self, callback: CallbackQuery, state: FSMContext):
        """Тестирование OpenAI ассистента через Responses API"""
        logger.info("🧪 Starting OpenAI assistant test via Responses API", 
                   bot_id=self.bot_id)
        
        # ✅ ДОБАВЛЕНО: Синхронизация перед тестированием
        await self._sync_with_db_state()
        
        agent_type = self.ai_assistant_settings.get('agent_type', 'none')
        openai_assistant_id = self.ai_assistant_id if agent_type == 'openai' else None
        
        if not openai_assistant_id:
            logger.warning("❌ No OpenAI agent created for testing")
            await callback.answer("❌ Сначала создайте OpenAI агента", show_alert=True)
            return
        
        logger.info("✅ Starting OpenAI test mode via Responses API", 
                   openai_assistant_id=openai_assistant_id)
        
        await state.set_state(AISettingsStates.admin_in_ai_conversation)
        # ✅ ИЗМЕНЕНИЕ 5: Убираем различие админ/пользователь в тестировании
        await state.update_data(agent_type='openai', user_id=callback.from_user.id)
        
        # Получаем информацию о включенных инструментах
        settings = self.ai_assistant_settings.get('openai_settings', {})
        enabled_tools = []
        if settings.get('enable_web_search'):
            enabled_tools.append("🌐 Веб-поиск")
        if settings.get('enable_code_interpreter'):
            enabled_tools.append("🐍 Интерпретатор кода")
        if settings.get('enable_file_search'):
            enabled_tools.append("📁 Поиск по файлам")
        if settings.get('enable_image_generation'):
            enabled_tools.append("🎨 Генерация изображений")
        
        tools_text = ""
        if enabled_tools:
            tools_text = f"\n<b>Включенные инструменты:</b> {', '.join(enabled_tools)}"
        
        text = f"""
🧪 <b>Тестирование OpenAI агента (Responses API)</b>

<b>Агент ID:</b> {openai_assistant_id[:15]}...
<b>Модель:</b> GPT-4o (Responses API)
<b>Режим:</b> Автоматический контекст{tools_text}

✨ <b>Особенности Responses API:</b>
- Контекст сохраняется автоматически на серверах OpenAI
- Не нужно отправлять всю историю с каждым сообщением
- Поддержка встроенных инструментов

<b>Напишите ваш вопрос:</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚪 Завершить диалог", callback_data="ai_exit_conversation")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)

    # ===== УПРАВЛЕНИЕ ИНСТРУМЕНТАМИ =====
    
    async def handle_tools_settings(self, callback: CallbackQuery, is_owner_check):
        """Настройка встроенных инструментов Responses API"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Получаем текущие настройки инструментов
            settings = self.ai_assistant_settings.get('openai_settings', {})
            
            web_search = "✅" if settings.get('enable_web_search') else "❌"
            code_interpreter = "✅" if settings.get('enable_code_interpreter') else "❌"
            file_search = "✅" if settings.get('enable_file_search') else "❌"
            
            vector_stores_count = len(settings.get('vector_store_ids', []))
            file_search_info = f" ({vector_stores_count} хранилищ)" if vector_stores_count > 0 else ""
            
            text = f"""
🧰 <b>Встроенные инструменты Responses API</b>

<b>Текущие настройки:</b>
🌐 Веб-поиск: {web_search}
🐍 Интерпретатор кода: {code_interpreter}
📁 Поиск по файлам: {file_search}{file_search_info}

<b>Описание инструментов:</b>

🌐 <b>Веб-поиск</b>
- Поиск актуальной информации в интернете
- Автоматические цитаты и ссылки
- Стоимость: $25-50 за 1000 запросов

🐍 <b>Интерпретатор кода</b>
- Выполнение Python кода
- Анализ данных и построение графиков
- Математические вычисления

📁 <b>Поиск по файлам</b>
- Поиск в загруженных документах
- RAG на основе векторных хранилищ
- Стоимость: $2.50 за 1000 запросов
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🌐 Веб-поиск {web_search}", 
                                    callback_data="openai_toggle_web_search")],
                [InlineKeyboardButton(text=f"🐍 Код {code_interpreter}", 
                                    callback_data="openai_toggle_code_interpreter")],
                [InlineKeyboardButton(text=f"📁 Файлы {file_search}", 
                                    callback_data="openai_toggle_file_search")],
                [InlineKeyboardButton(text="🔧 Загрузить файлы", 
                                    callback_data="openai_upload_files")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_ai")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error("💥 Error showing tools settings", error=str(e))
            await callback.answer("Ошибка при загрузке настроек", show_alert=True)

    async def handle_toggle_web_search(self, callback: CallbackQuery, is_owner_check):
        """Переключение веб-поиска"""
        await self._toggle_openai_tool(callback, 'web_search', 'Веб-поиск', is_owner_check)

    async def handle_toggle_code_interpreter(self, callback: CallbackQuery, is_owner_check):
        """Переключение интерпретатора кода"""
        await self._toggle_openai_tool(callback, 'code_interpreter', 'Интерпретатор кода', is_owner_check)

    async def handle_toggle_file_search(self, callback: CallbackQuery, is_owner_check):
        """Переключение поиска по файлам"""
        await self._toggle_openai_tool(callback, 'file_search', 'Поиск по файлам', is_owner_check)

    async def _toggle_openai_tool(self, callback: CallbackQuery, tool_name: str, tool_display_name: str, is_owner_check):
        """Переключение встроенного инструмента"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Получаем текущие настройки
            settings = self.ai_assistant_settings.copy()
            openai_settings = settings.get('openai_settings', {})
            
            # Переключаем инструмент
            setting_key = f'enable_{tool_name}'
            current_value = openai_settings.get(setting_key, False)
            openai_settings[setting_key] = not current_value
            
            settings['openai_settings'] = openai_settings
            
            # Сохраняем в БД
            await self.db.update_ai_assistant(
                self.bot_id,
                settings=settings
            )
            
            # Обновляем локальные настройки
            self.ai_assistant_settings = settings
            
            status = "включен" if not current_value else "выключен"
            await callback.answer(f"{tool_display_name} {status}")
            
            logger.info("🔧 Tool toggled", 
                       tool_name=tool_name,
                       new_status=not current_value,
                       bot_id=self.bot_id)
            
            # Обновляем меню
            await self.handle_tools_settings(callback, is_owner_check)
            
        except Exception as e:
            logger.error("💥 Error toggling tool", tool=tool_name, error=str(e))
            await callback.answer("Ошибка при изменении настройки", show_alert=True)

    # ===== УПРАВЛЕНИЕ ФАЙЛАМИ И VECTOR STORES =====

    async def handle_upload_files(self, callback: CallbackQuery, is_owner_check):
        """✅ ИЗМЕНЕНИЕ 7: Управление загрузкой файлов для file_search с улучшенной кнопкой"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Получаем информацию о текущих vector stores
            from services.openai_assistant import openai_client
            
            success, vector_stores = await openai_client.list_vector_stores()
            
            # Ищем vector store для этого бота
            bot_vector_store = None
            vector_store_name = f"Bot_{self.bot_id}_Knowledge"
            
            if success:
                for store in vector_stores:
                    if store['name'] == vector_store_name:
                        bot_vector_store = store
                        break
            
            files_info = ""
            if bot_vector_store:
                # ✅ ИСПРАВЛЕНО: Безопасное извлечение данных из file_counts объекта
                file_counts = bot_vector_store.get('file_counts', {})
                
                # Проверяем является ли file_counts словарем или объектом
                if hasattr(file_counts, 'get'):
                    # Это словарь
                    total_files = file_counts.get('total', 0)
                    processed_files = file_counts.get('completed', 0)
                elif hasattr(file_counts, 'total'):
                    # Это объект с атрибутами
                    total_files = getattr(file_counts, 'total', 0)
                    processed_files = getattr(file_counts, 'completed', 0)
                else:
                    # Fallback для неизвестных типов
                    logger.warning("⚠️ Unknown file_counts type", 
                                 file_counts_type=type(file_counts).__name__,
                                 file_counts_value=file_counts)
                    
                    # Пытаемся получить значения разными способами
                    try:
                        if isinstance(file_counts, dict):
                            total_files = file_counts.get('total', 0)
                            processed_files = file_counts.get('completed', 0)
                        else:
                            # Попытка прямого доступа к атрибутам
                            total_files = getattr(file_counts, 'total', 
                                                getattr(file_counts, 'in_progress', 0) + 
                                                getattr(file_counts, 'completed', 0))
                            processed_files = getattr(file_counts, 'completed', 0)
                    except Exception as attr_error:
                        logger.error("💥 Could not extract file counts", 
                                   error=str(attr_error),
                                   file_counts=file_counts)
                        total_files = 0
                        processed_files = 0
                
                files_info = f"\n\n📊 <b>Текущая база знаний:</b>\n• Всего файлов: {total_files}\n• Обработано: {processed_files}"
                
                logger.info("📊 Vector store file counts", 
                           vector_store_id=bot_vector_store.get('id', 'unknown'),
                           total_files=total_files,
                           processed_files=processed_files)
            
            text = f"""
📁 <b>База знаний агента</b>

<b>🔍 File Search - поиск по документам</b>

Загрузите документы для создания базы знаний вашего агента. Поддерживаемые форматы:
- PDF документы
- Word файлы (.docx)
- Текстовые файлы (.txt)
- Markdown файлы (.md)

<b>Как это работает:</b>
1. Вы загружаете документы
2. OpenAI автоматически обрабатывает и индексирует их
3. Агент получает возможность искать информацию в документах
4. Пользователи могут задавать вопросы по содержимому файлов{files_info}

<b>Лимиты:</b>
- Максимум 512 МБ на файл  
- До 10,000 файлов в базе знаний
- Стоимость: $0.10/ГБ/день + $2.50 за 1000 запросов
"""
            
            keyboard_buttons = []
            
            # Кнопка загрузки файлов
            keyboard_buttons.append([
                InlineKeyboardButton(text="📤 Загрузить документы", callback_data="openai_start_upload")
            ])
            
            # ✅ ИЗМЕНЕНИЕ 7: Кнопка "Мои файлы" если есть загруженные файлы
            openai_settings = self.ai_assistant_settings.get('openai_settings', {})
            uploaded_files = openai_settings.get('uploaded_files', [])

            if bot_vector_store or uploaded_files:
                files_text = f"📁 Мои файлы ({len(uploaded_files)})" if uploaded_files else "📋 Управление файлами"
                keyboard_buttons.append([
                    InlineKeyboardButton(text=files_text, callback_data="openai_manage_files")
                ])
            
            keyboard_buttons.append([
                InlineKeyboardButton(text="◀️ Назад к инструментам", callback_data="openai_tools_settings")
            ])
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
            logger.info("✅ Upload files menu displayed successfully", 
                       bot_id=self.bot_id,
                       has_existing_store=bool(bot_vector_store))
            
        except Exception as e:
            logger.error("💥 Error showing upload files menu", 
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            await callback.answer("Ошибка при загрузке меню", show_alert=True)

    # ✅ ДОБАВИТЬ: Безопасный метод для извлечения file_counts
    def _safe_extract_file_counts(self, file_counts) -> tuple[int, int]:
        """✅ НОВЫЙ: Безопасное извлечение статистики файлов из разных типов объектов"""
        try:
            total_files = 0
            processed_files = 0
            
            if file_counts is None:
                return 0, 0
            
            # Тип 1: Словарь
            if isinstance(file_counts, dict):
                total_files = file_counts.get('total', 0)
                processed_files = file_counts.get('completed', 0)
                logger.debug("📊 File counts from dict", total=total_files, completed=processed_files)
                return total_files, processed_files
            
            # Тип 2: Объект с атрибутами
            if hasattr(file_counts, 'total'):
                total_files = getattr(file_counts, 'total', 0)
                processed_files = getattr(file_counts, 'completed', 0)
                logger.debug("📊 File counts from object attributes", total=total_files, completed=processed_files)
                return total_files, processed_files
            
            # Тип 3: Другие возможные названия атрибутов
            possible_total_attrs = ['total', 'count', 'total_count', 'size']
            possible_completed_attrs = ['completed', 'processed', 'done', 'finished']
            
            for attr in possible_total_attrs:
                if hasattr(file_counts, attr):
                    total_files = getattr(file_counts, attr, 0)
                    break
            
            for attr in possible_completed_attrs:
                if hasattr(file_counts, attr):
                    processed_files = getattr(file_counts, attr, 0)
                    break
            
            if total_files > 0 or processed_files > 0:
                logger.debug("📊 File counts from alternative attributes", 
                           total=total_files, completed=processed_files)
                return total_files, processed_files
            
            # Тип 4: Попытка преобразования в строку и парсинга
            file_counts_str = str(file_counts)
            logger.warning("⚠️ Unknown file_counts type, attempting string conversion", 
                         type_name=type(file_counts).__name__,
                         string_value=file_counts_str,
                         attributes=[attr for attr in dir(file_counts) if not attr.startswith('_')])
            
            return 0, 0
            
        except Exception as e:
            logger.error("💥 Error extracting file counts", 
                        error=str(e),
                        file_counts_type=type(file_counts).__name__ if file_counts else 'None')
            return 0, 0

    async def handle_start_upload(self, callback: CallbackQuery, state: FSMContext, is_owner_check):
        """Начало процесса загрузки файлов"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        await state.set_state(AISettingsStates.admin_uploading_documents)
        await state.update_data(uploaded_files=[])
        
        text = """
📤 <b>Загрузка документов</b>

Отправьте документы которые должны стать частью базы знаний агента.

<b>Поддерживаемые форматы:</b>
- PDF (.pdf)
- Word (.docx)  
- Текст (.txt)
- Markdown (.md)

<b>Инструкции:</b>
1. Отправьте файлы один за другим в этот чат
2. После загрузки всех файлов нажмите "✅ Завершить"
3. Система автоматически обработает документы

<b>Отправьте первый файл:</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Завершить загрузку", callback_data="openai_finish_upload")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="openai_upload_files")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)

    async def handle_document_upload(self, message: Message, state: FSMContext, is_owner_check):
        """✅ ИЗМЕНЕНИЕ 6: Обработка загруженного документа с улучшенной батчевой загрузкой"""
        if not is_owner_check(message.from_user.id):
            return
        
        if not message.document:
            await message.answer("❌ Пожалуйста, отправьте документ как файл")
            return
        
        document = message.document
        
        # Проверяем формат файла
        allowed_extensions = ['.pdf', '.docx', '.txt', '.md']
        file_extension = None
        
        if document.file_name:
            file_extension = '.' + document.file_name.split('.')[-1].lower()
        
        if not file_extension or file_extension not in allowed_extensions:
            await message.answer(f"❌ Неподдерживаемый формат файла. Поддерживаются: {', '.join(allowed_extensions)}")
            return
        
        # Проверяем размер файла (максимум 512 МБ)
        max_size = 512 * 1024 * 1024  # 512 МБ в байтах
        if document.file_size > max_size:
            await message.answer(f"❌ Файл слишком большой. Максимальный размер: 512 МБ")
            return
        
        try:
            progress_msg = await message.answer(f"🔄 Обрабатываю файл: {document.file_name}")
            
            # Скачиваем файл
            bot = message.bot
            file_info = await bot.get_file(document.file_id)
            
            import tempfile
            import os
            
            # Создаем временный файл
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
                temp_file_path = temp_file.name
            
            # Скачиваем файл от Telegram
            await bot.download_file(file_info.file_path, temp_file_path)
            
            # Загружаем в OpenAI
            from services.openai_assistant import openai_client
            
            success, file_data = await openai_client.upload_file_to_openai(
                temp_file_path, 
                document.file_name
            )
            
            # Удаляем временный файл
            try:
                os.unlink(temp_file_path)
            except:
                pass
            
            if success:
                # Сохраняем информацию о загруженном файле
                data = await state.get_data()
                uploaded_files = data.get('uploaded_files', [])
                
                uploaded_files.append({
                    'file_id': file_data['id'],
                    'filename': file_data['filename'],
                    'size': file_data['bytes']
                })
                
                await state.update_data(uploaded_files=uploaded_files)
                
                file_size_mb = round(file_data['bytes'] / (1024 * 1024), 2)
                
                # ✅ ИЗМЕНЕНИЕ 6: Улучшенная батчевая загрузка с показом общего размера
                await progress_msg.edit_text(
                    f"✅ Файл загружен: {document.file_name} ({file_size_mb} МБ)\n\n"
                    f"📊 Загружено файлов: {len(uploaded_files)}\n"
                    f"💾 Общий размер: {sum(f['size']/(1024*1024) for f in uploaded_files):.1f} МБ\n\n"
                    f"🔄 <b>Батчевая загрузка активна!</b>\n"
                    f"Отправьте еще файлы или нажмите \"✅ Завершить загрузку\"",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="✅ Завершить загрузку", callback_data="openai_finish_upload")],
                        [InlineKeyboardButton(text="❌ Отмена", callback_data="openai_upload_files")]
                    ])
                )
                
            else:
                error_msg = file_data.get('error', 'Неизвестная ошибка')
                await progress_msg.edit_text(f"❌ Ошибка загрузки файла: {error_msg}")
            
        except Exception as e:
            logger.error("💥 Error uploading document", error=str(e))
            await message.answer("❌ Произошла ошибка при загрузке файла")

    async def handle_finish_upload(self, callback: CallbackQuery, state: FSMContext, is_owner_check):
        """✅ ИЗМЕНЕНИЕ 1: Завершение загрузки с сохранением информации о файлах"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            data = await state.get_data()
            uploaded_files = data.get('uploaded_files', [])
            
            if not uploaded_files:
                await callback.answer("❌ Нет загруженных файлов", show_alert=True)
                return
            
            progress_msg = await callback.message.edit_text("🔄 Создаю базу знаний...")
            
            from services.openai_assistant import openai_client
            
            # Создаем или получаем vector store
            vector_store_name = f"Bot_{self.bot_id}_Knowledge"
            
            # Сначала проверяем, есть ли уже vector store
            success, vector_stores = await openai_client.list_vector_stores()
            existing_store = None
            
            if success:
                for store in vector_stores:
                    if store['name'] == vector_store_name:
                        existing_store = store
                        break
            
            if existing_store:
                # Используем существующий vector store
                vector_store_id = existing_store['id']
                logger.info("📁 Using existing vector store", vector_store_id=vector_store_id)
            else:
                # Создаем новый vector store
                success, store_data = await openai_client.create_vector_store(vector_store_name)
                
                if not success:
                    await progress_msg.edit_text(f"❌ Ошибка создания базы знаний: {store_data.get('error')}")
                    return
                
                vector_store_id = store_data['id']
                logger.info("✅ Created new vector store", vector_store_id=vector_store_id)
            
            # Добавляем файлы в vector store
            file_ids = [f['file_id'] for f in uploaded_files]
            
            success, result = await openai_client.add_files_to_vector_store(vector_store_id, file_ids)
            
            if success:
                # ✅ ИЗМЕНЕНИЕ 1: Сохраняем полную информацию о файлах в БД
                files_info = []
                for file_data in uploaded_files:
                    files_info.append({
                        "filename": file_data['filename'],
                        "openai_file_id": file_data['file_id'],
                        "uploaded_at": datetime.now().isoformat(),
                        "size_bytes": file_data['size'],
                        "size_mb": round(file_data['size'] / (1024 * 1024), 2)
                    })
                
                # Сохраняем vector store И информацию о файлах
                save_success = await self._save_vector_store_and_files(vector_store_id, files_info)
                
                if not save_success:
                    await progress_msg.edit_text(
                        "❌ Файлы загружены в OpenAI, но не удалось привязать к агенту. "
                        "Обратитесь к администратору."
                    )
                    return
                
                total_files = len(uploaded_files)
                total_size = sum(f['size'] for f in uploaded_files)
                total_size_mb = round(total_size / (1024 * 1024), 2)
                
                success_text = f"""
✅ <b>База знаний создана и привязана к агенту!</b>

📊 <b>Статистика:</b>
- Файлов загружено: {total_files}
- Общий размер: {total_size_mb} МБ
- Vector Store ID: {vector_store_id[:15]}...

🧰 <b>File Search включен и настроен!</b>
Ваш агент теперь может искать информацию в загруженных документах.

<b>Список файлов:</b>
"""
                
                for i, file_info in enumerate(uploaded_files, 1):
                    filename = file_info['filename']
                    size_mb = round(file_info['size'] / (1024 * 1024), 2)
                    success_text += f"{i}. {filename} ({size_mb} МБ)\n"
                
                await progress_msg.edit_text(
                    success_text,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🧪 Тестировать агента", callback_data="openai_test")],
                        [InlineKeyboardButton(text="🔍 Проверить настройки", callback_data="openai_verify_file_search")],
                        [InlineKeyboardButton(text="🧰 К инструментам", callback_data="openai_tools_settings")]
                    ])
                )
                
            else:
                error_msg = result.get('error', 'Неизвестная ошибка')
                await progress_msg.edit_text(f"❌ Ошибка добавления файлов в базу знаний: {error_msg}")
            
            await state.clear()
            
        except Exception as e:
            logger.error("💥 Error finishing upload", error=str(e), exc_info=True)
            await callback.message.edit_text("❌ Произошла ошибка при создании базы знаний")
            await state.clear()

    async def _save_vector_store_and_files(self, vector_store_id: str, files_info: list) -> bool:
        """✅ ИЗМЕНЕНИЕ 2: НОВЫЙ метод объединенного сохранения vector store + информация о файлах для меню"""
        try:
            logger.info("💾 Saving vector store with files info", 
                       vector_store_id=vector_store_id,
                       files_count=len(files_info),
                       bot_id=self.bot_id)
            
            # 1. Сохраняем vector store (как раньше)
            from database.managers.ai_manager import AIManager
            success = await AIManager.save_vector_store_ids(self.bot_id, [vector_store_id])
            
            if not success:
                logger.error("❌ Failed to save vector store")
                return False
            
            # 2. НОВОЕ: Сохраняем информацию о файлах в openai_settings
            settings = self.ai_assistant_settings.copy()
            openai_settings = settings.get('openai_settings', {})
            
            # Добавляем файлы к существующим (не перезаписываем)
            existing_files = openai_settings.get('uploaded_files', [])
            existing_files.extend(files_info)
            openai_settings['uploaded_files'] = existing_files
            openai_settings['files_last_updated'] = datetime.now().isoformat()
            
            settings['openai_settings'] = openai_settings
            
            # Обновляем в БД
            await self.db.update_ai_assistant(self.bot_id, settings=settings)
            
            # Обновляем локальное состояние
            self.ai_assistant_settings = settings
            
            logger.info("✅ Vector store and files info saved", 
                       total_files=len(existing_files),
                       new_files=len(files_info))
            
            return True
            
        except Exception as e:
            logger.error("💥 Failed to save vector store and files", 
                        error=str(e), exc_info=True)
            return False

    async def _save_and_enable_vector_store(self, vector_store_id: str) -> bool:
        """✅ ИСПРАВЛЕНО: Объединенное сохранение vector store ID и включение file_search"""
        try:
            logger.info("💾 Saving vector store and enabling file_search", 
                       vector_store_id=vector_store_id,
                       bot_id=self.bot_id)
            
            # ✅ ИСПОЛЬЗУЕМ СПЕЦИАЛИЗИРОВАННЫЙ МЕТОД ИЗ AI MANAGER
            from database.managers.ai_manager import AIManager
            
            # Сохраняем vector store IDs через правильный метод
            success = await AIManager.save_vector_store_ids(self.bot_id, [vector_store_id])
            
            if not success:
                logger.error("❌ Failed to save vector store via AIManager")
                return False
            
            logger.info("✅ Vector store saved via AIManager")
            
            # ✅ ПРИНУДИТЕЛЬНАЯ СИНХРОНИЗАЦИЯ ПОСЛЕ СОХРАНЕНИЯ
            sync_success = await self._sync_with_db_state(force=True)
            if sync_success:
                logger.info("✅ State synchronized after vector store save")
            else:
                logger.warning("⚠️ Failed to sync state after vector store save")
            
            # ✅ ДИАГНОСТИКА: Проверяем что сохранилось
            await self._diagnose_vector_store_save(vector_store_id)
            
            return True
            
        except Exception as e:
            logger.error("💥 Failed to save and enable vector store", 
                        vector_store_id=vector_store_id,
                        bot_id=self.bot_id,
                        error=str(e),
                        exc_info=True)
            return False

    async def _diagnose_vector_store_save(self, expected_vector_store_id: str):
        """🩺 Диагностика сохранения vector store"""
        try:
            logger.info("🩺 Diagnosing vector store save", 
                       expected_id=expected_vector_store_id)
            
            # 1. Проверяем локальное состояние
            local_openai_settings = self.ai_assistant_settings.get('openai_settings', {})
            local_vector_ids = local_openai_settings.get('vector_store_ids', [])
            local_file_search = local_openai_settings.get('enable_file_search', False)
            
            logger.info("📊 Local state check", 
                       local_vector_ids=local_vector_ids,
                       local_file_search=local_file_search,
                       expected_found_locally=expected_vector_store_id in local_vector_ids)
            
            # 2. Проверяем БД состояние через AIManager
            from database.managers.ai_manager import AIManager
            vector_info = await AIManager.get_vector_store_info(self.bot_id)
            
            db_vector_ids = vector_info.get('vector_store_ids', [])
            db_file_search = vector_info.get('file_search_enabled', False)
            
            logger.info("📊 Database state check", 
                       db_vector_ids=db_vector_ids,
                       db_file_search=db_file_search,
                       expected_found_in_db=expected_vector_store_id in db_vector_ids)
            
            # 3. Проверяем через прямой запрос к БД
            fresh_bot = await self.db.get_bot_by_id(self.bot_id, fresh=True)
            if fresh_bot and fresh_bot.openai_settings:
                raw_settings = fresh_bot.openai_settings
                raw_vector_ids = raw_settings.get('vector_store_ids', [])
                raw_file_search = raw_settings.get('enable_file_search', False)
                
                logger.info("📊 Raw database check", 
                           raw_vector_ids=raw_vector_ids,
                           raw_file_search=raw_file_search,
                           expected_found_raw=expected_vector_store_id in raw_vector_ids)
            else:
                logger.warning("⚠️ Could not get raw database state")
            
            # 4. Итоговая диагностика
            if expected_vector_store_id in db_vector_ids and db_file_search:
                logger.info("✅ DIAGNOSIS SUCCESS: Vector store properly saved and configured")
                return True
            else:
                logger.error("❌ DIAGNOSIS FAILED: Vector store not properly saved", 
                           expected_id=expected_vector_store_id,
                           found_in_db=expected_vector_store_id in db_vector_ids,
                           file_search_enabled=db_file_search)
                return False
                
        except Exception as e:
            logger.error("💥 Vector store diagnosis failed", error=str(e))
            return False

    async def handle_manage_files(self, callback: CallbackQuery, is_owner_check):
        """✅ ИЗМЕНЕНИЕ 3: Показ реальных загруженных файлов"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Получаем информацию о файлах из настроек
            openai_settings = self.ai_assistant_settings.get('openai_settings', {})
            uploaded_files = openai_settings.get('uploaded_files', [])
            vector_store_ids = openai_settings.get('vector_store_ids', [])
            
            logger.info("📁 Showing uploaded files", 
                       files_count=len(uploaded_files),
                       vector_stores=len(vector_store_ids))
            
            if not uploaded_files:
                # Нет файлов
                text = """
📁 <b>Мои файлы</b>

📋 <b>База знаний пуста</b>

Вы еще не загружали файлы для создания базы знаний.
Загрузите документы чтобы агент мог отвечать на вопросы по ним.
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📤 Загрузить файлы", callback_data="openai_start_upload")],
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="openai_upload_files")]
                ])
            else:
                # Есть файлы - показываем список
                text = f"""
📁 <b>Мои файлы ({len(uploaded_files)})</b>

📊 <b>Статистика:</b>
- Всего файлов: {len(uploaded_files)}
- Vector Stores: {len(vector_store_ids)}

📋 <b>Список файлов:</b>
"""
                
                total_size_mb = 0
                for i, file_info in enumerate(uploaded_files, 1):
                    filename = file_info.get('filename', 'Неизвестный файл')
                    size_mb = file_info.get('size_mb', 0)
                    uploaded_date = file_info.get('uploaded_at', '')
                    
                    # Форматируем дату
                    try:
                        if uploaded_date:
                            from datetime import datetime
                            date_obj = datetime.fromisoformat(uploaded_date.replace('Z', '+00:00'))
                            date_str = date_obj.strftime('%d.%m.%Y %H:%M')
                        else:
                            date_str = 'Неизвестно'
                    except:
                        date_str = 'Неизвестно'
                    
                    text += f"{i}. <b>{filename}</b>\n"
                    text += f"   📊 {size_mb} МБ • 📅 {date_str}\n\n"
                    total_size_mb += size_mb
                
                text += f"💾 <b>Общий размер:</b> {total_size_mb:.1f} МБ"
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📤 Добавить файлы", callback_data="openai_start_upload")],
                    [InlineKeyboardButton(text="🗑️ Удалить базу знаний", callback_data="openai_clear_knowledge")],
                    [InlineKeyboardButton(text="🔍 Проверить настройки", callback_data="openai_verify_file_search")],
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="openai_upload_files")]
                ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error("💥 Error showing files", error=str(e), exc_info=True)
            await callback.answer("Ошибка при загрузке списка файлов", show_alert=True)

    async def handle_clear_knowledge(self, callback: CallbackQuery, is_owner_check):
        """Очистка базы знаний"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        text = """
🗑️ <b>Очистка базы знаний</b>

⚠️ <b>Внимание!</b> Будут удалены все загруженные документы и векторное хранилище.

Это действие необратимо. Продолжить?
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, очистить", callback_data="openai_confirm_clear_knowledge")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="openai_manage_files")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)

    async def handle_verify_file_search(self, callback: CallbackQuery, is_owner_check):
        """✅ НОВЫЙ: Проверка настроек file search"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Принудительная синхронизация
            await self._sync_with_db_state(force=True)
            
            # Получаем информацию о vector stores через AIManager
            from database.managers.ai_manager import AIManager
            vector_info = await AIManager.get_vector_store_info(self.bot_id)
            
            vector_store_ids = vector_info.get('vector_store_ids', [])
            file_search_enabled = vector_info.get('file_search_enabled', False)
            vector_stores_count = vector_info.get('vector_stores_count', 0)
            last_updated = vector_info.get('last_updated', 'Неизвестно')
            
            # Проверяем локальное состояние
            local_settings = self.ai_assistant_settings.get('openai_settings', {})
            local_vector_ids = local_settings.get('vector_store_ids', [])
            local_file_search = local_settings.get('enable_file_search', False)
            
            status_icon = "✅" if file_search_enabled and vector_store_ids else "❌"
            sync_icon = "✅" if local_vector_ids == vector_store_ids else "⚠️"
            
            text = f"""
🔍 <b>Проверка настроек File Search</b>

{status_icon} <b>Статус:</b> {'Настроено' if file_search_enabled else 'Не настроено'}

📊 <b>База данных:</b>
• Vector Store IDs: {len(vector_store_ids)}
• File Search: {'Включен' if file_search_enabled else 'Выключен'}
• Последнее обновление: {last_updated}

🔄 <b>Локальное состояние:</b>
• Vector Store IDs: {len(local_vector_ids)} 
• File Search: {'Включен' if local_file_search else 'Выключен'}
• Синхронизация: {sync_icon}

<b>Список Vector Store IDs:</b>
"""
            
            for i, vs_id in enumerate(vector_store_ids, 1):
                text += f"{i}. {vs_id}\n"
                
            if not vector_store_ids:
                text += "Нет настроенных vector stores\n"
                
            text += f"\n<b>Рекомендации:</b>\n"
            
            if not file_search_enabled:
                text += "• Включите File Search в настройках инструментов\n"
            if not vector_store_ids:
                text += "• Загрузите файлы для создания базы знаний\n"
            if local_vector_ids != vector_store_ids:
                text += "• Требуется синхронизация локального состояния\n"
            
            if file_search_enabled and vector_store_ids and local_vector_ids == vector_store_ids:
                text += "✅ Все настроено корректно!"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Принудительная синхронизация", 
                                    callback_data="openai_force_sync_vectors")],
                [InlineKeyboardButton(text="📤 Загрузить еще файлы", 
                                    callback_data="openai_start_upload")],
                [InlineKeyboardButton(text="◀️ Назад к инструментам", 
                                    callback_data="openai_tools_settings")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error("💥 Error verifying file search", error=str(e))
            await callback.answer("Ошибка при проверке настроек", show_alert=True)

    async def handle_force_sync_vectors(self, callback: CallbackQuery, is_owner_check):
        """✅ НОВЫЙ: Принудительная синхронизация vector stores"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            progress_msg = await callback.message.edit_text("🔄 Принудительная синхронизация...")
            
            # Принудительно синхронизируем с БД
            sync_success = await self._sync_with_db_state(force=True)
            
            if sync_success:
                # Получаем актуальную информацию о vector stores
                from database.managers.ai_manager import AIManager
                vector_info = await AIManager.get_vector_store_info(self.bot_id)
                
                vector_store_ids = vector_info.get('vector_store_ids', [])
                
                await progress_msg.edit_text(
                    f"""✅ <b>Синхронизация выполнена!</b>

📊 Найдено vector stores: {len(vector_store_ids)}
🔄 Локальное состояние обновлено
✅ Агент готов к работе с файлами""",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🔍 Проверить снова", 
                                            callback_data="openai_verify_file_search")],
                        [InlineKeyboardButton(text="🧪 Тестировать агента", 
                                            callback_data="openai_test")]
                    ])
                )
            else:
                await progress_msg.edit_text(
                    "❌ Ошибка синхронизации. Обратитесь к администратору.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="◀️ Назад", 
                                            callback_data="openai_verify_file_search")]
                    ])
                )
            
        except Exception as e:
            logger.error("💥 Error in force sync vectors", error=str(e))
            await callback.answer("Ошибка синхронизации", show_alert=True)

    async def handle_confirm_clear_knowledge(self, callback: CallbackQuery, is_owner_check):
        """✅ ИЗМЕНЕНИЕ 4 и 5: Подтверждение очистки базы знаний с очисткой файлов ИЗ БД"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            progress_msg = await callback.message.edit_text("🔄 Очищаю базу знаний...")
            
            # Получаем информацию о файлах перед очисткой
            openai_settings = self.ai_assistant_settings.get('openai_settings', {})
            
            # ✅ ИСПРАВЛЕНО: Очищаем файлы но СОХРАНЯЕМ vector store
            clear_success = await self._clear_vector_store_files_only()
            
            if clear_success:
                # Синхронизируем локальное состояние
                await self._sync_with_db_state(force=True)
                
                await progress_msg.edit_text(
                    f"""✅ <b>База знаний очищена!</b>

🧹 Очищено файлов: {len(openai_settings.get('uploaded_files', []))}
📁 Файлы удалены из OpenAI Files
🔄 Vector Store готов к новым загрузкам
💡 При следующей загрузке файлы добавятся в тот же Vector Store

Можете загрузить новые файлы.""",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📤 Загрузить новые файлы", 
                                            callback_data="openai_start_upload")],
                        [InlineKeyboardButton(text="🧰 К инструментам", 
                                            callback_data="openai_tools_settings")]
                    ])
                )
            else:
                await progress_msg.edit_text("❌ Ошибка при очистке базы знаний")
                
        except Exception as e:
            logger.error("💥 Error clearing knowledge base", error=str(e))
            await callback.message.edit_text("❌ Произошла ошибка при очистке")

    async def _clear_vector_store_files_only(self) -> bool:
        """✅ НОВЫЙ: Очистка файлов но СОХРАНЕНИЕ vector store для повторного использования"""
        try:
            logger.info("🧹 Clearing vector store files (keeping store)", bot_id=self.bot_id)
            
            # Получаем информацию о файлах и vector stores
            openai_settings = self.ai_assistant_settings.get('openai_settings', {})
            uploaded_files = openai_settings.get('uploaded_files', [])
            vector_store_ids = openai_settings.get('vector_store_ids', [])
            
            if not vector_store_ids:
                logger.info("ℹ️ No vector stores to clear", bot_id=self.bot_id)
                # Все равно очищаем uploaded_files на всякий случай
                return await self._clear_uploaded_files_info()
            
            from services.openai_assistant import openai_client
            
            # У нас всегда один vector store на бота
            vector_store_id = vector_store_ids[0]
            
            logger.info("🔍 Processing vector store", 
                       vector_store_id=vector_store_id,
                       files_to_process=len(uploaded_files))
            
            # 1. ✅ ОЧИЩАЕМ файлы из vector store (НЕ удаляем сам store!)
            clear_success = False
            try:
                clear_success = await openai_client.clear_vector_store_files(vector_store_id)
                if clear_success:
                    logger.info("✅ Vector store files cleared successfully", 
                               vector_store_id=vector_store_id)
                else:
                    logger.warning("⚠️ Vector store files clearing returned False", 
                                  vector_store_id=vector_store_id)
            except Exception as e:
                logger.error("💥 Error clearing vector store files", 
                            vector_store_id=vector_store_id, error=str(e))
            
            # 2. ✅ УДАЛЯЕМ файлы из OpenAI Files storage (чтобы не платить за хранение)
            deleted_files = 0
            for file_info in uploaded_files:
                openai_file_id = file_info.get('openai_file_id')
                filename = file_info.get('filename', 'unknown')
                
                if openai_file_id:
                    try:
                        success, message = await openai_client.delete_file(openai_file_id)
                        if success:
                            deleted_files += 1
                            logger.info("✅ File deleted from OpenAI Files", 
                                       file_id=openai_file_id,
                                       filename=filename)
                        else:
                            logger.warning("⚠️ Failed to delete file from OpenAI Files", 
                                         file_id=openai_file_id, 
                                         filename=filename,
                                         error=message)
                    except Exception as e:
                        logger.error("💥 Error deleting file from OpenAI Files", 
                                   file_id=openai_file_id, 
                                   filename=filename,
                                   error=str(e))
            
            # 3. ✅ ОЧИЩАЕМ информацию о файлах в БД (НО СОХРАНЯЕМ vector_store_ids!)
            files_clear_success = await self._clear_uploaded_files_info()
            
            overall_success = (clear_success or len(uploaded_files) == 0) and files_clear_success
            
            logger.info("🎯 Vector store clearing completed", 
                       bot_id=self.bot_id,
                       vector_store_cleared=clear_success,
                       files_deleted_from_openai=deleted_files,
                       files_info_cleared=files_clear_success,
                       overall_success=overall_success,
                       vector_store_preserved=True)  # ✅ Store остается!
            
            return overall_success
            
        except Exception as e:
            logger.error("💥 Failed to clear vector store files", 
                        bot_id=self.bot_id,
                        error=str(e),
                        exc_info=True)
            return False

    async def _clear_uploaded_files_info(self) -> bool:
        """✅ НОВЫЙ: Очистка ТОЛЬКО информации о файлах в БД (vector stores остаются!)"""
        try:
            # Получаем настройки
            settings = self.ai_assistant_settings.copy()
            openai_settings = settings.get('openai_settings', {})
            
            # Сохраняем количество файлов для логирования
            files_count = len(openai_settings.get('uploaded_files', []))
            
            # ✅ КРИТИЧНО: Очищаем ТОЛЬКО uploaded_files, НЕ ТРОГАЕМ vector_store_ids!
            openai_settings['uploaded_files'] = []
            openai_settings['files_cleared_at'] = datetime.now().isoformat()
            # vector_store_ids ОСТАЕТСЯ как был!
            
            settings['openai_settings'] = openai_settings
            
            # Сохраняем в БД
            await self.db.update_ai_assistant(self.bot_id, settings=settings)
            
            # Обновляем локальное состояние
            self.ai_assistant_settings = settings
            
            logger.info("✅ Files info cleared from DB (vector stores preserved)", 
                       bot_id=self.bot_id,
                       cleared_files_count=files_count,
                       vector_stores_kept=len(settings.get('openai_settings', {}).get('vector_store_ids', [])))
            
            return True
            
        except Exception as e:
            logger.error("💥 Failed to clear uploaded files info", 
                        bot_id=self.bot_id, error=str(e))
            return False

    # ===== УДАЛЕНИЕ АГЕНТА =====
    
    async def _delete_openai_agent(self, callback: CallbackQuery):
        """✅ УПРОЩЕННОЕ: Показ подтверждения удаления"""
        logger.info("🗑️ Showing OpenAI agent deletion confirmation", 
                   bot_id=self.bot_id)
        
        agent_name = self.ai_assistant_settings.get('agent_name', 'ИИ агента')
        
        text = f"""
🗑️ <b>Удаление "{agent_name}"</b>

⚠️ <b>Внимание!</b> Агент будет удален из системы.
Все настройки будут потеряны.

Вы уверены?
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data="openai_confirm_delete")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_ai")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)

    async def handle_confirm_delete(self, callback: CallbackQuery, is_owner_check):
        """✅ УПРОЩЕННОЕ: Удаление - возврат в главное меню"""
        
        logger.info("🗑️ Simple OpenAI agent deletion", 
                   user_id=callback.from_user.id,
                   bot_id=self.bot_id)
        
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            agent_name = self.ai_assistant_settings.get('agent_name', 'агента')
            await callback.message.edit_text("🔄 Удаляем агента...")
            
            # Просто очищаем конфигурацию из БД
            await self.db.clear_ai_configuration(self.bot_id)
            
            # Локально тоже очищаем для синхронности
            self.ai_assistant_id = None
            self.ai_assistant_settings = {'agent_type': 'none'}
            
            # ✅ ИСПРАВЛЕНО: Возврат в правильное главное меню (admin_main)
            text = f"""
✅ <b>OpenAI агент "{agent_name}" удален!</b>

Конфигурация очищена из базы данных.
Возвращаемся в главное меню.
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_main")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
            logger.info("✅ OpenAI agent deleted successfully (simple method)")
            
        except Exception as e:
            logger.error("💥 Error in simple deletion", error=str(e))
            await callback.answer("Ошибка при удалении", show_alert=True)

    # ===== РЕДАКТИРОВАНИЕ АГЕНТА =====

    async def handle_edit_agent(self, callback: CallbackQuery, is_owner_check):
        """✅ ДОБАВИТЬ: Показ меню редактирования агента"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            agent_name = self.ai_assistant_settings.get('agent_name', 'AI Ассистент')
            agent_role = self.ai_assistant_settings.get('agent_role', 'Полезный помощник')
            system_prompt = self.ai_assistant_settings.get('system_prompt', '')
            
            text = f"""
✏️ <b>Редактирование агента "{agent_name}"</b>

<b>Текущие настройки:</b>
📝 <b>Имя:</b> {agent_name}
🎭 <b>Роль:</b> {agent_role}
📋 <b>Системный промпт:</b> {system_prompt[:100]}{'...' if len(system_prompt) > 100 else ''}

<b>Что хотите изменить?</b>

⚠️ <b>Внимание:</b> При изменении промпта агент будет пересоздан в OpenAI с новыми настройками.
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✏️ Изменить имя", callback_data="openai_edit_name")],
                [InlineKeyboardButton(text="🎭 Изменить роль и промпт", callback_data="openai_edit_prompt")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_ai")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error("💥 Error showing edit menu", error=str(e))
            await callback.answer("Ошибка при загрузке меню редактирования", show_alert=True)

    async def handle_edit_name(self, callback: CallbackQuery, state: FSMContext):
        """✅ ДОБАВИТЬ: Начало редактирования имени"""
        await callback.answer()
        await state.set_state(AISettingsStates.admin_editing_agent_name)
        
        current_name = self.ai_assistant_settings.get('agent_name', 'AI Ассистент')
        
        text = f"""
✏️ <b>Изменение имени агента</b>

<b>Текущее имя:</b> {current_name}

Введите новое имя для вашего агента:
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="openai_edit")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)

    async def handle_edit_prompt(self, callback: CallbackQuery, state: FSMContext):
        """✅ ДОБАВИТЬ: Начало редактирования промпта"""
        await callback.answer()
        await state.set_state(AISettingsStates.admin_editing_agent_prompt)
        
        current_role = self.ai_assistant_settings.get('agent_role', 'Полезный помощник')
        
        text = f"""
🎭 <b>Изменение роли и промпта агента</b>

<b>Текущая роль:</b> {current_role}

Введите новое описание роли и инструкции для агента:

<b>Примеры:</b>
- "Ты эксперт по фитнесу. Отвечай дружелюбно, давай практичные советы."
- "Ты консультант по продажам. Помогай клиентам выбрать товар."

⚠️ <b>Внимание:</b> После изменения агент будет пересоздан в OpenAI.
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="openai_edit")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)

    async def handle_name_edit_input(self, message: Message, state: FSMContext, is_owner_check):
        """✅ ИСПРАВЛЕНО: Обработка ввода нового имени с проверкой голосовых"""
        if not is_owner_check(message.from_user.id):
            return
        
        # ✅ ИСПРАВЛЕНО: Проверяем наличие текста в сообщении
        if not self._is_text_message(message):
            await message.answer("❌ Пожалуйста, отправьте текстовое сообщение с новым именем агента.")
            return
        
        message_text = message.text.strip()
        
        if message_text == "/cancel":
            await self._cancel_and_show_edit(message, state)
            return
        
        new_name = message_text
        
        if len(new_name) < 2 or len(new_name) > 100:
            await message.answer("❌ Имя должно быть от 2 до 100 символов. Попробуйте еще раз:")
            return
        
        try:
            # Обновляем только имя (без пересоздания агента)
            current_settings = self.ai_assistant_settings.copy()
            current_settings['agent_name'] = new_name
            
            await self.db.update_ai_assistant(
                self.bot_id,
                settings=current_settings
            )
            
            self.ai_assistant_settings = current_settings
            
            await message.answer(
                f"✅ Имя агента изменено на: {new_name}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✏️ Продолжить редактирование", callback_data="openai_edit")],
                    [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
                ])
            )
            
            await state.clear()
            
        except Exception as e:
            logger.error("💥 Error updating agent name", error=str(e))
            await message.answer("❌ Ошибка при обновлении имени")

    async def handle_prompt_edit_input(self, message: Message, state: FSMContext, is_owner_check):
        """✅ ИСПРАВЛЕНО: Обработка ввода нового промпта с пересозданием агента + проверка голосовых"""
        if not is_owner_check(message.from_user.id):
            return
        
        # ✅ ИСПРАВЛЕНО: Проверяем наличие текста в сообщении
        if not self._is_text_message(message):
            await message.answer("❌ Пожалуйста, отправьте текстовое сообщение с новой ролью агента.")
            return
        
        message_text = message.text.strip()
        
        if message_text == "/cancel":
            await self._cancel_and_show_edit(message, state)
            return
        
        new_role = message_text
        
        if len(new_role) < 10 or len(new_role) > 1000:
            await message.answer("❌ Описание роли должно быть от 10 до 1000 символов. Попробуйте еще раз:")
            return
        
        try:
            progress_message = await message.answer("🔄 Пересоздаем агента с новым промптом...")
            
            # Получаем текущие данные
            agent_name = self.ai_assistant_settings.get('agent_name', 'AI Ассистент')
            old_assistant_id = self.ai_assistant_id
            
            # Пересоздаем агента
            success, response_data = await self._recreate_agent_with_new_prompt(
                agent_name, new_role, old_assistant_id
            )
            
            if success:
                new_assistant_id = response_data.get('assistant_id')
                
                await progress_message.edit_text(
                    f"""✅ <b>Агент успешно обновлен!</b>

<b>Имя:</b> {agent_name}
<b>Новая роль:</b> {new_role[:100]}{'...' if len(new_role) > 100 else ''}
<b>Новый ID:</b> {new_assistant_id[:15]}...

Агент пересоздан в OpenAI с новыми настройками!""",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🧪 Тестировать", callback_data="openai_test")],
                        [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
                    ])
                )
            else:
                error_msg = response_data.get('error', 'Неизвестная ошибка')
                await progress_message.edit_text(
                    f"❌ Ошибка при пересоздании агента: {error_msg}",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="openai_edit_prompt")],
                        [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
                    ])
                )
            
            await state.clear()
            
        except Exception as e:
            logger.error("💥 Error updating agent prompt", error=str(e))
            await message.answer("❌ Ошибка при обновлении промпта")

    async def _recreate_agent_with_new_prompt(self, name: str, role: str, old_assistant_id: str) -> tuple[bool, dict]:
        """✅ ДОБАВИТЬ: Пересоздание агента с новым промптом"""
        try:
            # 1. Удаляем старого агента из OpenAI
            if old_assistant_id:
                try:
                    from services.openai_assistant import openai_client
                    await openai_client.delete_assistant(old_assistant_id)
                    logger.info("✅ Old agent deleted from OpenAI")
                except Exception as e:
                    logger.warning("⚠️ Could not delete old agent", error=str(e))
            
            # 2. Создаем нового агента
            success, response_data = await self._create_agent_in_openai(name, role)
            
            if success:
                new_assistant_id = response_data.get('assistant_id')
                
                # 3. Синхронизируем состояние
                await self._sync_with_db_state(force=True)
                
                # 4. Обновляем другие компоненты
                await self._safe_update_user_bot(
                    ai_assistant_id=new_assistant_id,
                    ai_assistant_settings=self.ai_assistant_settings
                )
                await self._safe_update_bot_manager(
                    ai_assistant_id=new_assistant_id,
                    ai_assistant_settings=self.ai_assistant_settings
                )
                
                logger.info("✅ Agent recreated successfully", 
                           old_id=old_assistant_id,
                           new_id=new_assistant_id)
                
                return True, response_data
            
            return False, response_data
            
        except Exception as e:
            logger.error("💥 Error recreating agent", error=str(e))
            return False, {"error": str(e)}

    async def _cancel_and_show_edit(self, message: Message, state: FSMContext):
        """✅ ДОБАВИТЬ: Отмена редактирования"""
        await state.clear()
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ К редактированию", callback_data="openai_edit")]
        ])
        await message.answer("Редактирование отменено", reply_markup=keyboard)

    # ===== СИНХРОНИЗАЦИЯ ДАННЫХ =====
    
    async def handle_sync_agent_data(self, callback: CallbackQuery, is_owner_check):
        """Ручная синхронизация данных агента"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            logger.info("🔄 Manual agent data sync requested", bot_id=self.bot_id)
            
            # Синхронизируем данные
            success = await self.db.sync_agent_data_fields(bot_id=self.bot_id)
            
            if success:
                # Проверяем результат
                validation = await self.db.validate_agent_data_consistency(self.bot_id)
                
                status = validation.get('overall_status', 'unknown')
                if status == 'consistent':
                    await callback.answer("✅ Данные агента синхронизированы")
                else:
                    recommendations = validation.get('recommendations', [])
                    await callback.answer(f"⚠️ Найдены проблемы: {', '.join(recommendations)}")
            else:
                await callback.answer("❌ Ошибка синхронизации", show_alert=True)
                
        except Exception as e:
            logger.error("💥 Error in manual sync", error=str(e))
            await callback.answer("❌ Ошибка синхронизации", show_alert=True)

    # ===== ДИАЛОГ С OPENAI =====
    
    async def handle_openai_conversation(self, message: Message, data: dict) -> str:
        """✅ ИСПРАВЛЕНО: Обработка диалога с правильной проверкой агента + списание токенов + проверка голосовых"""
        logger.info("🎨 OpenAI conversation processing via Responses API", 
                   user_id=message.from_user.id,
                   has_text=self._is_text_message(message),
                   message_length=len(message.text) if message.text else 0)
        
        try:
            # ✅ ИСПРАВЛЕНО: Проверяем тип сообщения
            if not self._is_text_message(message):
                # ✅ ДОБАВЛЕНО: Списание токенов даже для неподдерживаемых сообщений
                try:
                    await self.db.increment_ai_usage(self.bot_id, message.from_user.id)
                    logger.info("💰 Tokens charged for unsupported message", 
                               bot_id=self.bot_id, 
                               user_id=message.from_user.id)
                except Exception as stats_error:
                    logger.warning("⚠️ Failed to update token usage for unsupported message", error=str(stats_error))
                
                message_type_display = self._get_message_text(message)
                return f"❌ Извините, я могу обрабатывать только текстовые сообщения. Ваше сообщение: {message_type_display}"
            
            # ✅ ИСПРАВЛЕНО: Синхронизируем перед диалогом
            await self._sync_with_db_state()
            
            agent_type = self.ai_assistant_settings.get('agent_type', 'none')
            openai_assistant_id = self.ai_assistant_id if agent_type == 'openai' else None
            
            if not openai_assistant_id:
                logger.error("❌ No OpenAI assistant ID available",
                            cached_id=self.ai_assistant_id,
                            agent_type=agent_type)
                return "❌ OpenAI агент не настроен."
            
            logger.info("📊 OpenAI Responses API conversation parameters", 
                       openai_assistant_id=openai_assistant_id,
                       user_id=message.from_user.id)
            
            # Пытаемся использовать OpenAI Responses API сервис
            try:
                from services.openai_assistant import openai_client
                from services.openai_assistant.models import OpenAIResponsesContext
                
                # СОЗДАЕМ УПРОЩЕННЫЙ КОНТЕКСТ (БЕЗ previous_response_id)
                context = OpenAIResponsesContext(
                    user_id=message.from_user.id,
                    user_name=message.from_user.first_name or "Пользователь",
                    username=message.from_user.username,
                    bot_id=self.bot_id,
                    chat_id=message.chat.id,
                    is_admin=message.from_user.id == self.owner_user_id
                )
                
                logger.info("📝 Responses API context prepared", 
                           user_name=context.user_name,
                           is_admin=context.is_admin)
                
                # ОТПРАВЛЯЕМ СООБЩЕНИЕ ЧЕРЕЗ RESPONSES API
                # Контекст разговора управляется автоматически!
                logger.info("📡 Sending message to OpenAI Responses API service")
                
                response = await openai_client.send_message(
                    assistant_id=openai_assistant_id,
                    message=message.text,
                    user_id=message.from_user.id,
                    context=context
                )
                
                logger.info("✅ OpenAI Responses API response received", 
                           response_length=len(response) if response else 0)
                
                if response:
                    # ✅ ИЗМЕНЕНИЕ 4: Записываем использование токенов для ВСЕХ (включая админов)
                    try:
                        await self.db.increment_ai_usage(self.bot_id, message.from_user.id)
                        logger.info("💰 Tokens charged", 
                                   bot_id=self.bot_id, 
                                   user_id=message.from_user.id,
                                   is_admin=message.from_user.id == self.owner_user_id)
                    except Exception as stats_error:
                        logger.warning("⚠️ Failed to update token usage", error=str(stats_error))
                    
                    logger.info("📊 Responses API conversation completed successfully")
                    return response
                else:
                    return "❌ Не удалось получить ответ от OpenAI."
                    
            except ImportError:
                # Fallback для случая когда OpenAI сервис недоступен
                logger.warning("📦 OpenAI Responses API service not available, using fallback")
                agent_name = self.ai_assistant_settings.get('agent_name', 'ИИ Агент')
                
                # ✅ ДОБАВЛЕНО: Списание токенов даже для fallback ответов
                try:
                    await self.db.increment_ai_usage(self.bot_id, message.from_user.id)
                    logger.info("💰 Tokens charged (fallback)", 
                               bot_id=self.bot_id, 
                               user_id=message.from_user.id)
                except Exception as stats_error:
                    logger.warning("⚠️ Failed to update token usage (fallback)", error=str(stats_error))
                
                return f"🤖 {agent_name}: Получил ваше сообщение '{message.text}'. Responses API сервис временно недоступен."
            
        except Exception as e:
            logger.error("💥 Error in OpenAI Responses API conversation", 
                        error=str(e),
                        error_type=type(e).__name__)
            # ✅ ИСПРАВЛЕНО: Возвращаем строку с ошибкой вместо None
            return "❌ Произошла ошибка при общении с ИИ"

    async def handle_openai_conversation_with_text(self, message: Message, data: dict, text: str) -> str:
        """✅ НОВЫЙ: Обработка диалога с OpenAI с кастомным текстом (для голосовых сообщений)"""
        logger.info("🎨 OpenAI conversation processing with custom text", 
                   user_id=message.from_user.id,
                   text_length=len(text) if text else 0,
                   is_admin=message.from_user.id == self.owner_user_id)
        
        try:
            if not text:
                logger.warning("❌ Empty text provided to OpenAI handler")
                return "❌ Пустое сообщение"
            
            # ✅ ИСПРАВЛЕНО: Синхронизируем перед диалогом
            await self._sync_with_db_state()
            
            agent_type = self.ai_assistant_settings.get('agent_type', 'none')
            openai_assistant_id = self.ai_assistant_id if agent_type == 'openai' else None
            
            if not openai_assistant_id:
                logger.error("❌ No OpenAI assistant ID available",
                            cached_id=self.ai_assistant_id,
                            agent_type=agent_type)
                return "❌ OpenAI агент не настроен."
            
            logger.info("📊 OpenAI Responses API conversation parameters", 
                       openai_assistant_id=openai_assistant_id,
                       user_id=message.from_user.id,
                       text_preview=text[:50] if text else "EMPTY")
            
            # Пытаемся использовать OpenAI Responses API сервис
            try:
                from services.openai_assistant import openai_client
                from services.openai_assistant.models import OpenAIResponsesContext
                
                # СОЗДАЕМ УПРОЩЕННЫЙ КОНТЕКСТ
                context = OpenAIResponsesContext(
                    user_id=message.from_user.id,
                    user_name=message.from_user.first_name or "Пользователь",
                    username=message.from_user.username,
                    bot_id=self.bot_id,
                    chat_id=message.chat.id,
                    is_admin=message.from_user.id == self.owner_user_id
                )
                
                logger.info("📝 Responses API context prepared", 
                           user_name=context.user_name,
                           is_admin=context.is_admin)
                
                # ОТПРАВЛЯЕМ КАСТОМНЫЙ ТЕКСТ ЧЕРЕЗ RESPONSES API
                logger.info("📡 Sending custom text to OpenAI Responses API service")
                
                response = await openai_client.send_message(
                    assistant_id=openai_assistant_id,
                    message=text,  # ✅ ИСПОЛЬЗУЕМ ПЕРЕДАННЫЙ ТЕКСТ (транскрибированный или обычный)
                    user_id=message.from_user.id,
                    context=context
                )
                
                logger.info("✅ OpenAI Responses API response received", 
                           response_length=len(response) if response else 0)
                
                if response:
                    # ✅ Записываем использование токенов для ВСЕХ (включая админов)
                    try:
                        await self.db.increment_ai_usage(self.bot_id, message.from_user.id)
                        logger.info("💰 Tokens charged for admin", 
                                   bot_id=self.bot_id, 
                                   user_id=message.from_user.id,
                                   is_admin=context.is_admin)
                    except Exception as stats_error:
                        logger.warning("⚠️ Failed to update token usage for admin", error=str(stats_error))
                    
                    logger.info("📊 Admin Responses API conversation completed successfully")
                    return response
                else:
                    return "❌ Не удалось получить ответ от OpenAI."
                    
            except ImportError:
                # Fallback для случая когда OpenAI сервис недоступен
                logger.warning("📦 OpenAI Responses API service not available, using admin fallback")
                agent_name = self.ai_assistant_settings.get('agent_name', 'ИИ Агент')
                
                # ✅ Списание токенов даже для fallback ответов
                try:
                    await self.db.increment_ai_usage(self.bot_id, message.from_user.id)
                    logger.info("💰 Tokens charged (admin fallback)", 
                               bot_id=self.bot_id, 
                               user_id=message.from_user.id)
                except Exception as stats_error:
                    logger.warning("⚠️ Failed to update token usage (admin fallback)", error=str(stats_error))
                
                return f"🤖 {agent_name}: [АДМИН ТЕСТ] Получил сообщение '{text[:100]}{'...' if len(text) > 100 else ''}'. Responses API сервис временно недоступен."
            
        except Exception as e:
            logger.error("💥 Error in admin OpenAI conversation with custom text", 
                        error=str(e),
                        error_type=type(e).__name__)
            return "❌ Произошла ошибка при общении с ИИ"

    # ===== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ =====
    
    async def _cancel_and_show_ai(self, message: Message, state: FSMContext):
        """Отмена и показ настроек ИИ"""
        logger.info("❌ Cancelling OpenAI operation", 
                   user_id=message.from_user.id,
                   bot_id=self.bot_id)
        
        await state.clear()
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
        ])
        await message.answer("Настройка отменена", reply_markup=keyboard)
    
    async def _safe_update_user_bot(self, **kwargs):
        """Безопасное обновление настроек UserBot"""
        logger.info("🔄 Attempting UserBot update", 
                   bot_id=self.bot_id,
                   update_keys=list(kwargs.keys()))
        
        try:
            if self.user_bot and hasattr(self.user_bot, 'update_ai_settings'):
                await self.user_bot.update_ai_settings(**kwargs)
                logger.info("✅ UserBot update successful")
            else:
                logger.warning("⚠️ UserBot doesn't have update_ai_settings method", 
                             bot_id=self.bot_id,
                             has_user_bot=bool(self.user_bot),
                             has_method=hasattr(self.user_bot, 'update_ai_settings') if self.user_bot else False)
        except Exception as e:
            logger.error("💥 Failed to update UserBot settings", 
                        bot_id=self.bot_id,
                        error=str(e),
                        error_type=type(e).__name__)
    
    async def _safe_update_bot_manager(self, **kwargs):
        """Безопасное обновление через bot_manager"""
        logger.info("🔄 Attempting BotManager update", 
                   bot_id=self.bot_id,
                   update_keys=list(kwargs.keys()))
        
        try:
            bot_manager = self.bot_config.get('bot_manager')
            if bot_manager and hasattr(bot_manager, 'update_bot_config'):
                await bot_manager.update_bot_config(self.bot_id, **kwargs)
                logger.info("✅ BotManager update successful")
            else:
                logger.warning("⚠️ BotManager doesn't have update_bot_config method", 
                             bot_id=self.bot_id,
                             has_bot_manager=bool(bot_manager),
                             has_method=hasattr(bot_manager, 'update_bot_config') if bot_manager else False)
        except Exception as e:
            logger.error("💥 Failed to update BotManager config", 
                        bot_id=self.bot_id,
                        error=str(e),
                        error_type=type(e).__name__)
