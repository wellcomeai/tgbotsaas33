"""
Базовый класс для OpenAI Handler
Содержит основную инициализацию, свойства, синхронизацию и общие методы
"""

import structlog
from datetime import datetime
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

logger = structlog.get_logger()


class OpenAIHandlerBase:
    """Базовый класс OpenAI обработчика с общей функциональностью"""
    
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
        from ..keyboards import AIKeyboards
        keyboard = AIKeyboards.openai_settings_menu(True)
        
        await callback.message.edit_text(text, reply_markup=keyboard)

    # ===== ОСНОВНЫЕ ОБРАБОТЧИКИ ДЕЙСТВИЙ =====

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

    # ===== БЕЗОПАСНЫЕ МЕТОДЫ ОБНОВЛЕНИЯ =====
    
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

    # ===== ДИАГНОСТИЧЕСКИЕ МЕТОДЫ =====

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
