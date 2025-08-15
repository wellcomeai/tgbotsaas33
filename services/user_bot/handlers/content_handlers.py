"""
Обработчики контент-агентов для рерайта постов.

✅ ОБНОВЛЕНО В ЭТОЙ ВЕРСИИ:
1. 🔧 ИСПРАВЛЕНА критическая ошибка в _send_media_group_rewrite_result
2. 🛡️ Улучшена обработка ошибок и валидация данных
3. 🚀 Оптимизирована работа с медиагруппами
4. 📊 Добавлено детальное логирование для отладки
5. 🔒 Усилена безопасность работы с переменными
6. ✨ НОВОЕ: Упрощенный вывод для пользователей (без технической информации)
7. 🔗 НОВОЕ: Поддержка извлечения ссылок из медиагрупп
8. 📺 НОВОЕ: Интеграция с каналами для публикации
9. ✏️ НОВОЕ: Редактирование постов с правками
10. 📤 НОВОЕ: Публикация в каналы

✅ ПОЛНАЯ ФУНКЦИОНАЛЬНОСТЬ:
1. Поддержка медиагрупп (альбомов) через aiogram-media-group
2. Обработка альбомов фото/видео с рерайтом
3. Сохранение медиафайлов через MediaGroupBuilder
4. Улучшенная обработка различных типов контента
5. Правильный порядок регистрации handlers (специфичные ПЕРЕД общими)
6. Безопасный импорт ContentStates с fallback
7. Полная обработка всех FSM состояний
8. Завершенная логика создания, редактирования и удаления агентов
9. Полный функционал рерайта постов с медиа
10. ✨ УПРОЩЕННЫЙ вывод результатов для пользователей
11. 🔗 Извлечение и обработка ссылок
12. 📺 Работа с каналами для публикации
13. ✏️ Редактирование и правки постов
14. 📤 Публикация готовых постов в каналы

Функционал:
- Создание ИИ агентов для контента (только OpenAI)
- Управление агентами (настройки, удаление)
- Рерайт постов через OpenAI Responses API
- Обработка медиа (фото, видео) с сохранением file_id
- ✨ Обработка медиагрупп (альбомов) с рерайтом
- 🔗 Извлечение ссылок из сообщений
- 📺 Подключение каналов для публикации
- ✏️ Редактирование и правки постов
- 📤 Публикация в каналы
- Интеграция с токеновой системой
- FSM диалоги для создания агентов и рерайта
- ✨ Чистый пользовательский интерфейс без технической информации
"""

import structlog
from typing import Dict, Any, List, Optional
from aiogram import Dispatcher, F
from aiogram.types import Message, CallbackQuery, InputMediaPhoto, InputMediaVideo, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.utils.media_group import MediaGroupBuilder

# ✅ Импорт для работы с медиагруппами
try:
    from aiogram_media_group import media_group_handler
    MEDIA_GROUP_AVAILABLE = True
except ImportError:
    logger = structlog.get_logger()
    logger.warning("⚠️ aiogram-media-group not installed. Media group functionality will be limited.")
    MEDIA_GROUP_AVAILABLE = False
    # Создаем пустой декоратор для совместимости
    def media_group_handler(func):
        return func

from services.content_agent import content_agent_service
from config import Emoji
from ..formatters import MessageFormatter

# ✅ Безопасный импорт состояний с fallback
try:
    from ..states import ContentStates
    CONTENT_STATES_AVAILABLE = True
    logger = structlog.get_logger()
    logger.info("✅ ContentStates imported successfully")
except ImportError as e:
    logger = structlog.get_logger()
    logger.warning("⚠️ ContentStates not found, creating temporary states", error=str(e))
    from aiogram.fsm.state import State, StatesGroup
    
    class ContentStates(StatesGroup):
        waiting_for_agent_name = State()
        waiting_for_agent_instructions = State()
        editing_agent_name = State()
        editing_agent_instructions = State()
        waiting_for_rewrite_post = State()
        waiting_for_channel_post = State()
        waiting_for_edit_instructions = State()
    
    CONTENT_STATES_AVAILABLE = False


def register_content_handlers(dp: Dispatcher, **kwargs):
    """✅ Регистрация обработчиков контент-агентов с полной поддержкой медиагрупп и каналов"""
    
    logger = structlog.get_logger()
    logger.info("📝 Registering content handlers with media group support, links extraction and channel integration")
    
    db = kwargs['db']
    bot_config = kwargs['bot_config']
    user_bot = kwargs.get('user_bot')
    
    logger.info("📋 Content handler registration parameters", 
               bot_id=bot_config.get('bot_id', 'unknown'),
               has_db=bool(db),
               has_user_bot=bool(user_bot),
               states_available=CONTENT_STATES_AVAILABLE,
               media_group_available=MEDIA_GROUP_AVAILABLE)
    
    try:
        # Создаем обработчик
        handler = ContentHandler(db, bot_config, user_bot)
        
        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: ПРАВИЛЬНЫЙ ПОРЯДОК - специфичные обработчики ПЕРВЫЕ!
        
        # ✅ Обработчик медиагрупп (должен быть ПЕРВЫМ среди обработчиков сообщений)
        if MEDIA_GROUP_AVAILABLE and CONTENT_STATES_AVAILABLE:
            @dp.message(F.media_group_id, F.content_type.in_({'photo', 'video'}))
            @media_group_handler
            async def handle_media_group_rewrite(messages: List[Message], state: FSMContext):
                """✅ Обработка альбомов для рерайта через aiogram-media-group"""
                
                # Проверяем, что мы в режиме рерайта
                current_state = await state.get_state()
                if current_state != ContentStates.waiting_for_rewrite_post:
                    return
                
                logger.info("📸 Media group received for rewrite", 
                           user_id=messages[0].from_user.id,
                           media_count=len(messages),
                           media_group_id=messages[0].media_group_id,
                           bot_id=handler.bot_id)
                
                if not handler._is_owner(messages[0].from_user.id):
                    await messages[0].answer("❌ Доступ запрещен")
                    return
                
                try:
                    # Обрабатываем альбом
                    await handler.handle_media_group_rewrite_input(messages, state)
                    
                except Exception as e:
                    logger.error("💥 Failed to handle media group rewrite", 
                                media_group_id=messages[0].media_group_id,
                                bot_id=handler.bot_id,
                                error=str(e))
                    await messages[0].answer("Ошибка при обработке альбома")
            
            logger.info("✅ Media group handler registered successfully")
        else:
            logger.warning("⚠️ Media group handler not registered - missing dependencies")
        
        # 1. Главное меню контента
        dp.callback_query.register(handler.cb_content_main, F.data == "content_main")
        
        # 2. Создание агента (полный цикл)
        dp.callback_query.register(handler.cb_create_agent, F.data == "content_create_agent")
        dp.callback_query.register(handler.cb_confirm_create_agent, F.data == "content_confirm_create")
        
        # 3. Управление агентом
        dp.callback_query.register(handler.cb_manage_agent, F.data == "content_manage")
        dp.callback_query.register(handler.cb_agent_settings, F.data == "content_settings")
        
        # 4. Редактирование агента
        dp.callback_query.register(handler.cb_edit_agent_name, F.data == "content_edit_name")
        dp.callback_query.register(handler.cb_edit_agent_instructions, F.data == "content_edit_instructions")
        dp.callback_query.register(handler.cb_confirm_instructions_update, F.data == "content_confirm_instructions_update")
        
        # 5. Удаление агента
        dp.callback_query.register(handler.cb_delete_agent, F.data == "content_delete_agent")
        dp.callback_query.register(handler.cb_confirm_delete_agent, F.data == "content_confirm_delete")
        
        # 6. Рерайт постов
        dp.callback_query.register(handler.cb_rewrite_post, F.data == "content_rewrite")
        dp.callback_query.register(handler.cb_exit_rewrite_mode, F.data == "content_exit_rewrite")
        
        # 7. Новые обработчики для каналов
        dp.callback_query.register(handler.cb_edit_post, F.data == "content_edit_post")
        dp.callback_query.register(handler.cb_publish_post, F.data == "content_publish")
        
        # 8. FSM обработчики сообщений
        if CONTENT_STATES_AVAILABLE:
            dp.message.register(
                handler.handle_agent_name_input,
                ContentStates.waiting_for_agent_name
            )
            dp.message.register(
                handler.handle_agent_instructions_input,
                ContentStates.waiting_for_agent_instructions
            )
            dp.message.register(
                handler.handle_edit_agent_name_input,
                ContentStates.editing_agent_name
            )
            dp.message.register(
                handler.handle_edit_agent_instructions_input,
                ContentStates.editing_agent_instructions
            )
            dp.message.register(
                handler.handle_rewrite_post_input,
                ContentStates.waiting_for_rewrite_post
            )
            # Новые FSM обработчики
            dp.message.register(
                handler.handle_channel_post_input,
                ContentStates.waiting_for_channel_post
            )
            dp.message.register(
                handler.handle_edit_instructions_input,
                ContentStates.waiting_for_edit_instructions
            )
            
            logger.info("✅ All FSM message handlers registered successfully")
        else:
            logger.warning("⚠️ FSM states unavailable, some functionality will be limited")
        
        total_handlers = 14 + (7 if CONTENT_STATES_AVAILABLE else 0) + (1 if MEDIA_GROUP_AVAILABLE else 0)
        
        logger.info("✅ Content handlers registered successfully", 
                   bot_id=bot_config['bot_id'],
                   callback_handlers=14,
                   fsm_handlers=7 if CONTENT_STATES_AVAILABLE else 0,
                   media_group_handlers=1 if MEDIA_GROUP_AVAILABLE else 0,
                   total_handlers=total_handlers)
        
    except Exception as e:
        logger.error("💥 Failed to register content handlers", 
                    bot_id=kwargs.get('bot_config', {}).get('bot_id', 'unknown'),
                    error=str(e),
                    error_type=type(e).__name__,
                    exc_info=True)
        raise


class ContentHandler:
    """✅ Обработчик контент-агентов с полной функциональностью + медиагруппы + упрощенный вывод + каналы"""
    
    def __init__(self, db, bot_config: dict, user_bot):
        self.db = db
        self.bot_config = bot_config
        self.bot_id = bot_config['bot_id']
        self.owner_user_id = bot_config['owner_user_id']
        self.bot_username = bot_config['bot_username']
        self.user_bot = user_bot
        self.formatter = MessageFormatter()
        self.logger = structlog.get_logger()
        
        self.logger.info("🔧 ContentHandler initialized with channels and editing support", 
                        bot_id=self.bot_id,
                        bot_username=self.bot_username,
                        owner_user_id=self.owner_user_id)
    
    # ===== UTILITY METHODS =====
    
    def _is_owner(self, user_id: int) -> bool:
        """Проверка владельца"""
        is_owner = user_id == self.owner_user_id
        self.logger.debug("👤 Owner check", 
                         bot_id=self.bot_id,
                         user_id=user_id,
                         owner_user_id=self.owner_user_id,
                         is_owner=is_owner)
        return is_owner
    
    async def _get_content_keyboards(self):
        """Получение клавиатур для контент-агентов с поддержкой каналов"""
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        
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
            ])
        }
        
        return keyboards
    
    def _format_number(self, number: int) -> str:
        """Форматирование чисел с разделителями"""
        return f"{number:,}".replace(",", " ")
    
    def _format_date(self, date_str: str = None) -> str:
        """Форматирование даты"""
        if not date_str:
            # Возвращаем текущую дату
            from datetime import datetime
            return datetime.now().strftime("%d.%m.%Y %H:%M")
        
        try:
            from datetime import datetime
            if isinstance(date_str, str):
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            else:
                dt = date_str
            return dt.strftime("%d.%m.%Y %H:%M")
        except:
            return "Ошибка формата"
    
    def _truncate_text(self, text: str, max_length: int) -> str:
        """Обрезка текста с добавлением многоточия"""
        if not text:
            return "Не указано"
        
        if len(text) <= max_length:
            return text
        
        return text[:max_length-3] + "..."
    
    def _safe_get_from_result(self, result: Dict, key: str, default=None):
        """🔧 НОВОЕ: Безопасное извлечение данных из result словаря"""
        try:
            return result.get(key, default)
        except (AttributeError, TypeError):
            self.logger.warning(f"⚠️ Failed to get key '{key}' from result", 
                               result_type=type(result).__name__)
            return default
    
    # ===== MAIN MENU =====
    
    async def cb_content_main(self, callback: CallbackQuery):
        """✅ Главное меню контент-агентов с детальным логированием"""
        self.logger.info("📝 Content main menu accessed", 
                        user_id=callback.from_user.id,
                        bot_id=self.bot_id,
                        callback_data=callback.data)
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            self.logger.warning("🚫 Access denied for non-owner", 
                               user_id=callback.from_user.id,
                               bot_id=self.bot_id)
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Проверяем наличие агента
            self.logger.debug("🔍 Checking for existing content agent", bot_id=self.bot_id)
            has_agent = await content_agent_service.has_content_agent(self.bot_id)
            self.logger.info("📊 Content agent check result", bot_id=self.bot_id, has_agent=has_agent)
            
            keyboards = await self._get_content_keyboards()
            
            if has_agent:
                # Получаем информацию об агенте
                self.logger.debug("📋 Loading agent info", bot_id=self.bot_id)
                agent_info = await content_agent_service.get_agent_info(self.bot_id)
                
                if agent_info:
                    stats = agent_info.get('stats', {})
                    
                    text = f"""
📝 <b>Контент канала @{self.bot_username}</b>

✅ <b>Агент создан:</b> {agent_info['name']}
🤖 <b>OpenAI интеграция:</b> {'✅ Подключена' if stats.get('has_openai_id') else '❌ Ошибка'}
💰 <b>Токенов использовано:</b> {self._format_number(stats.get('tokens_used', 0))}

📋 <b>Инструкции агента:</b>
<i>{self._truncate_text(agent_info['instructions'], 200)}</i>

🎯 <b>Что умеет агент:</b>
• Переписывает текст согласно вашим инструкциям
• Сохраняет смысл, меняет форму подачи  
• Работает с фото и видео (file_id сохраняется)
• ✨ Обрабатывает альбомы (медиагруппы)
• 🔗 Извлекает и сохраняет ссылки
• ✏️ Позволяет редактировать и вносить правки
• 📤 Публикует готовые посты в каналы
• Интегрирован с токеновой системой

<b>Выберите действие:</b>
"""
                    keyboard = keyboards['main_menu_with_agent']
                    self.logger.info("📋 Agent info loaded successfully", 
                                   bot_id=self.bot_id,
                                   agent_name=agent_info['name'])
                else:
                    text = f"""
📝 <b>Контент канала @{self.bot_username}</b>

⚠️ <b>Ошибка загрузки агента</b>

Агент существует в базе данных, но не удалось загрузить его информацию. Попробуйте пересоздать агента.

<b>Выберите действие:</b>
"""
                    keyboard = keyboards['main_menu_with_agent']
                    self.logger.warning("⚠️ Agent exists but failed to load info", bot_id=self.bot_id)
            else:
                media_group_status = "✅ Доступна" if MEDIA_GROUP_AVAILABLE else "❌ Не установлена"
                
                text = f"""
📝 <b>Контент канала @{self.bot_username}</b>

❌ <b>Агент не создан</b>

Для рерайта контента нужно создать ИИ агента:

🎯 <b>Что такое контент-агент:</b>
• Специальный ИИ для переписывания постов
• Работает на базе OpenAI GPT-4o
• Следует вашим инструкциям по стилю
• Сохраняет медиа файлы (фото, видео)
• Поддерживает альбомы (медиагруппы)
• 🔗 Извлекает и сохраняет ссылки
• ✏️ Позволяет редактировать готовые посты
• 📤 Публикует готовые посты в каналы

📋 <b>Как создать:</b>
1. Нажмите "Создать агента" 
2. Укажите канал для публикации
3. Введите имя агента
4. Опишите как переписывать тексты
5. Агент готов к работе!

🔧 <b>Статус системы:</b>
• Медиагруппы: {media_group_status}
• FSM состояния: {'✅ Доступны' if CONTENT_STATES_AVAILABLE else '❌ Недоступны'}

<b>Создать агента сейчас?</b>
"""
                keyboard = keyboards['main_menu_no_agent']
                self.logger.info("📋 No agent found, showing creation menu", bot_id=self.bot_id)
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
            self.logger.info("✅ Content main menu displayed successfully", 
                           bot_id=self.bot_id,
                           has_agent=has_agent)
            
        except Exception as e:
            self.logger.error("💥 Failed to show content main menu", 
                            bot_id=self.bot_id,
                            error=str(e),
                            error_type=type(e).__name__,
                            exc_info=True)
            
            await callback.answer("Ошибка при загрузке меню контента", show_alert=True)
    
    # ===== AGENT CREATION =====
    
    async def cb_create_agent(self, callback: CallbackQuery, state: FSMContext):
        """ИЗМЕНЕНО: Начало создания агента - сначала канал"""
        self.logger.info("✨ Create agent button pressed", 
                        user_id=callback.from_user.id,
                        bot_id=self.bot_id,
                        callback_data=callback.data)
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            self.logger.warning("🚫 Non-owner tried to create agent", 
                               user_id=callback.from_user.id,
                               bot_id=self.bot_id)
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Проверяем, не существует ли уже агент
            self.logger.debug("🔍 Checking existing agent before creation", bot_id=self.bot_id)
            has_agent = await content_agent_service.has_content_agent(self.bot_id)
            
            if has_agent:
                self.logger.warning("⚠️ Agent already exists, creation blocked", bot_id=self.bot_id)
                await callback.answer("Агент уже создан", show_alert=True)
                return
            
            text = f"""
✨ <b>Создание контент-агента</b>

<b>Шаг 1 из 3: Канал для публикации</b>

Для работы с контент-агентом нужно указать канал, куда будут публиковаться посты.

📝 <b>Как добавить канал:</b>
1. Перешлите любой пост из вашего канала
2. Бот автоматически определит канал
3. Убедитесь что бот добавлен в канал как администратор

⚠️ <b>Важно:</b> Бот должен иметь права на публикацию в канале.

<b>Перешлите пост из канала:</b>
"""
            
            keyboards = await self._get_content_keyboards()
            
            await callback.message.edit_text(text, reply_markup=keyboards['back_to_main'])
            
            if CONTENT_STATES_AVAILABLE:
                await state.set_state(ContentStates.waiting_for_channel_post)
                self.logger.info("✅ FSM state set for channel post input", bot_id=self.bot_id)
            else:
                self.logger.warning("⚠️ FSM states not available, using fallback", bot_id=self.bot_id)
            
            self.logger.info("✅ Agent creation flow started successfully", 
                           bot_id=self.bot_id,
                           user_id=callback.from_user.id)
            
        except Exception as e:
            self.logger.error("💥 Failed to start agent creation", 
                            bot_id=self.bot_id,
                            error=str(e),
                            error_type=type(e).__name__,
                            exc_info=True)
            await callback.answer("Ошибка при создании агента", show_alert=True)
    
    async def handle_channel_post_input(self, message: Message, state: FSMContext):
        """Обработка пересланного поста из канала"""
        self.logger.info("📺 Channel post input received", 
                        user_id=message.from_user.id,
                        bot_id=self.bot_id)
        
        if not self._is_owner(message.from_user.id):
            await message.answer("❌ Доступ запрещен")
            return
        
        try:
            # Проверяем что это пересланное сообщение из канала
            if not message.forward_from_chat:
                await message.answer("❌ Пришлите переслaнный пост из канала")
                return
            
            if message.forward_from_chat.type != "channel":
                await message.answer("❌ Сообщение должно быть из канала")
                return
            
            channel_id = message.forward_from_chat.id
            channel_title = message.forward_from_chat.title
            channel_username = message.forward_from_chat.username
            
            # Сохраняем информацию о канале
            channel_data = {
                'chat_id': channel_id,
                'chat_title': channel_title,
                'chat_username': channel_username,
                'chat_type': 'channel'
            }
            
            success = await content_agent_service.content_manager.save_channel_info(
                self.bot_id, channel_data
            )
            
            if not success:
                await message.answer("❌ Ошибка сохранения канала")
                return
            
            # Переходим к следующему шагу - имя агента
            text = f"""
✅ <b>Канал добавлен успешно!</b>

📺 <b>Канал:</b> {channel_title}
🆔 <b>ID:</b> <code>{channel_id}</code>
👤 <b>Username:</b> @{channel_username or 'не указан'}

<b>Шаг 2 из 3: Имя агента</b>

Придумайте имя для вашего ИИ агента:

📝 <b>Примеры:</b>
- "Редактор канала {channel_title}"
- "Копирайтер"
- "SMM помощник"

<b>Введите имя агента:</b>
"""
            
            await message.answer(text)
            await state.set_state(ContentStates.waiting_for_agent_name)
            
            self.logger.info("✅ Channel saved successfully", 
                           bot_id=self.bot_id,
                           channel_id=channel_id,
                           channel_title=channel_title)
            
        except Exception as e:
            self.logger.error("💥 Error processing channel post", 
                            bot_id=self.bot_id,
                            error=str(e))
            await message.answer("Ошибка при обработке канала")
    
    async def handle_agent_name_input(self, message: Message, state: FSMContext):
        """✅ Обработка ввода имени агента с валидацией"""
        self.logger.info("📝 Agent name input received", 
                        user_id=message.from_user.id,
                        bot_id=self.bot_id,
                        message_length=len(message.text or ""))
        
        if not self._is_owner(message.from_user.id):
            self.logger.warning("🚫 Non-owner tried to input agent name", 
                               user_id=message.from_user.id)
            await message.answer("❌ Доступ запрещен")
            return
        
        try:
            agent_name = message.text.strip()
            
            # Валидация имени
            if not agent_name:
                self.logger.debug("❌ Empty agent name provided", bot_id=self.bot_id)
                await message.answer("❌ Имя не может быть пустым. Попробуйте еще раз:")
                return
            
            if len(agent_name) < 3:
                self.logger.debug("❌ Agent name too short", bot_id=self.bot_id, length=len(agent_name))
                await message.answer("❌ Имя слишком короткое (минимум 3 символа). Попробуйте еще раз:")
                return
            
            if len(agent_name) > 100:
                self.logger.debug("❌ Agent name too long", bot_id=self.bot_id, length=len(agent_name))
                await message.answer("❌ Имя слишком длинное (максимум 100 символов). Попробуйте еще раз:")
                return
            
            # Сохраняем имя в состоянии
            await state.update_data(agent_name=agent_name)
            
            text = f"""
✨ <b>Создание контент-агента</b>

<b>Шаг 3 из 3: Инструкции для рерайта</b>

👤 <b>Имя агента:</b> {agent_name}

Теперь опишите, КАК агент должен переписывать тексты. Эти инструкции будут использоваться для всех рерайтов.

📝 <b>Примеры инструкций:</b>

<b>Дружелюбный стиль:</b>
"Переписывай тексты в дружелюбном, теплом тоне. Используй эмоджи и обращения к читателю. Делай текст более живым и близким."

<b>Деловой стиль:</b>  
"Переписывай в официально-деловом стиле. Убирай лишние эмоции, делай текст четким и структурированным. Фокус на фактах."

<b>Креативный подход:</b>
"Делай тексты более яркими и запоминающимися. Используй метафоры, интересные сравнения. Привлекай внимание необычными формулировками."

<b>Введите ваши инструкции:</b>
"""
            
            keyboards = await self._get_content_keyboards()
            
            await message.answer(
                text,
                reply_markup=keyboards['back_to_main']
            )
            
            if CONTENT_STATES_AVAILABLE:
                await state.set_state(ContentStates.waiting_for_agent_instructions)
            
            self.logger.info("✅ Agent name validated and saved", 
                           bot_id=self.bot_id,
                           agent_name=agent_name,
                           name_length=len(agent_name))
            
        except Exception as e:
            self.logger.error("💥 Failed to process agent name input", 
                            bot_id=self.bot_id,
                            error=str(e),
                            error_type=type(e).__name__,
                            exc_info=True)
            await message.answer("❌ Ошибка при обработке имени. Попробуйте еще раз:")
    
    async def handle_agent_instructions_input(self, message: Message, state: FSMContext):
        """Обработка ввода инструкций агента"""
        self.logger.info("📋 Agent instructions input received", 
                        user_id=message.from_user.id,
                        bot_id=self.bot_id,
                        instructions_length=len(message.text or ""))
        
        if not self._is_owner(message.from_user.id):
            await message.answer("❌ Доступ запрещен")
            return
        
        try:
            instructions = message.text.strip()
            
            # Валидация инструкций
            if not instructions:
                await message.answer("❌ Инструкции не могут быть пустыми. Попробуйте еще раз:")
                return
            
            if len(instructions) < 10:
                await message.answer("❌ Инструкции слишком короткие (минимум 10 символов). Опишите подробнее:")
                return
            
            if len(instructions) > 2000:
                await message.answer("❌ Инструкции слишком длинные (максимум 2000 символов). Сократите:")
                return
            
            # Получаем сохраненное имя
            data = await state.get_data()
            agent_name = data.get('agent_name')
            
            if not agent_name:
                await message.answer("❌ Ошибка: потеряно имя агента. Начните заново:")
                await state.clear()
                return
            
            # Показываем предпросмотр
            text = f"""
✨ <b>Подтверждение создания агента</b>

👤 <b>Имя агента:</b> {agent_name}

📋 <b>Инструкции:</b>
{instructions}

📊 <b>Параметры:</b>
• Модель: OpenAI GPT-4o
• Тип: Responses API  
• Токены: из общего лимита
• Медиа: фото, видео (file_id сохраняется)
• Альбомы: {'✅ Поддерживаются' if MEDIA_GROUP_AVAILABLE else '❌ Недоступны'}
• 🔗 Ссылки: автоматическое извлечение и сохранение
• ✏️ Редактирование: внесение правок в готовые посты
• 📤 Публикация: прямая отправка в каналы

⚠️ <b>После создания агента изменить можно будет только имя и инструкции. OpenAI интеграция пересоздается полностью.</b>

<b>Создать агента с этими настройками?</b>
"""
            
            # Сохраняем инструкции в состоянии
            await state.update_data(
                agent_name=agent_name,
                instructions=instructions
            )
            
            keyboards = await self._get_content_keyboards()
            
            await message.answer(
                text,
                reply_markup=keyboards['create_confirmation']
            )
            
            self.logger.info("✅ Agent instructions validated and preview shown", 
                           bot_id=self.bot_id,
                           agent_name=agent_name,
                           instructions_length=len(instructions))
            
        except Exception as e:
            self.logger.error("💥 Failed to process agent instructions input", 
                            bot_id=self.bot_id,
                            error=str(e))
            await message.answer("❌ Ошибка при обработке инструкций. Попробуйте еще раз:")
    
    async def cb_confirm_create_agent(self, callback: CallbackQuery, state: FSMContext):
        """✅ Подтверждение создания агента"""
        self.logger.info("✅ Agent creation confirmation received", 
                        user_id=callback.from_user.id,
                        bot_id=self.bot_id)
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Получаем данные из состояния
            data = await state.get_data()
            agent_name = data.get('agent_name')
            instructions = data.get('instructions')
            
            if not agent_name or not instructions:
                await callback.answer("Ошибка: данные агента потеряны", show_alert=True)
                await state.clear()
                return
            
            # Показываем процесс создания
            await callback.message.edit_text(
                f"⏳ <b>Создание агента '{agent_name}'...</b>\n\n"
                f"🤖 Настройка OpenAI интеграции...\n"
                f"💾 Сохранение в базу данных...\n\n"
                f"<i>Это может занять несколько секунд</i>"
            )
            
            # Создаем агента через сервис
            self.logger.info("🎨 Creating content agent via service", 
                           bot_id=self.bot_id,
                           agent_name=agent_name,
                           instructions_length=len(instructions),
                           user_id=callback.from_user.id)
            
            result = await content_agent_service.create_content_agent(
                bot_id=self.bot_id,
                agent_name=agent_name,
                instructions=instructions,
                user_id=callback.from_user.id
            )
            
            keyboards = await self._get_content_keyboards()
            
            if result['success']:
                # Успешное создание
                agent_data = result.get('agent', {})
                
                text = f"""
✅ <b>Агент создан успешно!</b>

👤 <b>Имя:</b> {agent_data.get('name', agent_name)}
🤖 <b>OpenAI ID:</b> {agent_data.get('openai_agent_id', 'Не указан')[:20]}...
💾 <b>Сохранен в БД:</b> ID {agent_data.get('id', 'Unknown')}

🎯 <b>Агент готов к работе!</b>

📝 Теперь вы можете:
• Отправлять посты для рерайта
• Отправлять альбомы для рерайта {'✅' if MEDIA_GROUP_AVAILABLE else '❌ (недоступно)'}
• 🔗 Использовать ссылки в постах (автоматически сохраняются)
• ✏️ Редактировать готовые посты
• 📤 Публиковать готовые посты в каналы
• Управлять настройками агента  
• Просматривать статистику использования

<b>Перейти к рерайту постов?</b>
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📝 Рерайт постов", callback_data="content_rewrite")],
                    [InlineKeyboardButton(text="📊 Главное меню", callback_data="content_main")]
                ])
                
                await callback.message.edit_text(text, reply_markup=keyboard)
                
                self.logger.info("✅ Content agent created successfully", 
                               bot_id=self.bot_id,
                               agent_name=agent_name,
                               agent_id=agent_data.get('id'),
                               openai_agent_id=agent_data.get('openai_agent_id'))
            else:
                # Ошибка создания
                error_message = result.get('message', 'Неизвестная ошибка')
                
                text = f"""
❌ <b>Ошибка создания агента</b>

<b>Причина:</b> {error_message}

🔧 <b>Что можно попробовать:</b>
• Проверить токеновый лимит
• Попробовать другое имя агента
• Проверить подключение к OpenAI
• Обратиться к администратору

<b>Попробовать еще раз?</b>
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="content_create_agent")],
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="content_main")]
                ])
                
                await callback.message.edit_text(text, reply_markup=keyboard)
                
                self.logger.error("❌ Content agent creation failed", 
                               bot_id=self.bot_id,
                               agent_name=agent_name,
                               error=result.get('error'),
                               message=error_message)
            
            # Очищаем состояние
            await state.clear()
            
        except Exception as e:
            self.logger.error("💥 Failed to confirm agent creation", 
                            bot_id=self.bot_id,
                            error=str(e),
                            error_type=type(e).__name__,
                            exc_info=True)
            
            await callback.message.edit_text(
                f"💥 <b>Критическая ошибка создания агента</b>\n\n"
                f"<b>Ошибка:</b> {str(e)}\n\n"
                f"Обратитесь к администратору."
            )
            
            await state.clear()
    
    # ===== AGENT MANAGEMENT =====
    
    async def cb_manage_agent(self, callback: CallbackQuery):
        """Управление агентом"""
        self.logger.info("⚙️ Agent management accessed", 
                        user_id=callback.from_user.id,
                        bot_id=self.bot_id)
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Получаем информацию об агенте
            agent_info = await content_agent_service.get_agent_info(self.bot_id)
            
            if not agent_info:
                await callback.answer("Агент не найден", show_alert=True)
                return
            
            stats = agent_info.get('stats', {})
            
            text = f"""
⚙️ <b>Управление агентом</b>

👤 <b>Имя:</b> {agent_info['name']}
🤖 <b>OpenAI интеграция:</b> {'✅ Активна' if stats.get('has_openai_id') else '❌ Ошибка'}
📅 <b>Создан:</b> {self._format_date(agent_info.get('created_at'))}
🔄 <b>Обновлен:</b> {self._format_date(agent_info.get('updated_at'))}

📊 <b>Статистика:</b>
• Токенов использовано: {self._format_number(stats.get('tokens_used', 0))}
• Последнее использование: {self._format_date(stats.get('last_usage_at')) or 'Не использовался'}

📋 <b>Инструкции агента:</b>
<i>{self._truncate_text(agent_info['instructions'], 300)}</i>

🔧 <b>Возможности:</b>
• Альбомы: {'✅ Поддерживаются' if MEDIA_GROUP_AVAILABLE else '❌ Недоступны'}
• FSM состояния: {'✅ Доступны' if CONTENT_STATES_AVAILABLE else '❌ Недоступны'}
• 🔗 Ссылки: ✅ Автоматическое извлечение
• ✏️ Редактирование: ✅ Внесение правок
• 📤 Публикация: ✅ Отправка в каналы

<b>Выберите действие:</b>
"""
            
            keyboards = await self._get_content_keyboards()
            
            await callback.message.edit_text(
                text,
                reply_markup=keyboards['manage_menu']
            )
            
            self.logger.info("✅ Agent management menu displayed", 
                           bot_id=self.bot_id,
                           agent_name=agent_info['name'])
            
        except Exception as e:
            self.logger.error("💥 Failed to show agent management", 
                            bot_id=self.bot_id,
                            error=str(e))
            await callback.answer("Ошибка при загрузке управления агентом", show_alert=True)
    
    async def cb_agent_settings(self, callback: CallbackQuery):
        """Настройки агента"""
        self.logger.info("⚙️ Agent settings accessed", 
                        user_id=callback.from_user.id,
                        bot_id=self.bot_id)
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Получаем информацию об агенте
            agent_info = await content_agent_service.get_agent_info(self.bot_id)
            
            if not agent_info:
                await callback.answer("Агент не найден", show_alert=True)
                return
            
            stats = agent_info.get('stats', {})
            
            text = f"""
⚙️ <b>Настройки агента</b>

👤 <b>Текущее имя:</b> {agent_info['name']}
🔗 <b>OpenAI Agent ID:</b> <code>{agent_info.get('openai_agent_id', 'Не указан')}</code>
📅 <b>Создан:</b> {self._format_date(agent_info.get('created_at'))}
🔄 <b>Последнее изменение:</b> {self._format_date(agent_info.get('updated_at'))}

📋 <b>Текущие инструкции:</b>
<i>{self._truncate_text(agent_info['instructions'], 400)}</i>

📊 <b>Статистика использования:</b>
• Токенов потрачено: {self._format_number(stats.get('tokens_used', 0))}
• Последняя активность: {self._format_date(stats.get('last_usage_at')) or 'Не использовался'}
• OpenAI интеграция: {'✅ Активна' if stats.get('has_openai_id') else '❌ Ошибка'}

🔧 <b>Системные возможности:</b>
• Альбомы: {'✅ Поддерживаются' if MEDIA_GROUP_AVAILABLE else '❌ Недоступны'}
• FSM состояния: {'✅ Доступны' if CONTENT_STATES_AVAILABLE else '❌ Недоступны'}
• 🔗 Ссылки: ✅ Автоматическое извлечение и сохранение
• ✏️ Редактирование: ✅ Внесение правок в готовые посты
• 📤 Публикация: ✅ Прямая отправка в каналы

<b>Что можно изменить:</b>
• Имя агента (отображается в интерфейсе)
• Инструкции рерайта (влияет на стиль обработки)

<b>Выберите что изменить:</b>
"""
            
            keyboards = await self._get_content_keyboards()
            
            await callback.message.edit_text(
                text,
                reply_markup=keyboards['settings_menu']
            )
            
            self.logger.info("✅ Agent settings menu displayed", 
                           bot_id=self.bot_id,
                           agent_name=agent_info['name'])
            
        except Exception as e:
            self.logger.error("💥 Failed to show agent settings", 
                            bot_id=self.bot_id,
                            error=str(e))
            await callback.answer("Ошибка при загрузке настроек агента", show_alert=True)
    
    # ===== AGENT EDITING =====
    
    async def cb_edit_agent_name(self, callback: CallbackQuery, state: FSMContext):
        """Начало редактирования имени агента"""
        self.logger.info("📝 Edit agent name started", 
                        user_id=callback.from_user.id,
                        bot_id=self.bot_id)
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Получаем текущую информацию об агенте
            agent_info = await content_agent_service.get_agent_info(self.bot_id)
            
            if not agent_info:
                await callback.answer("Агент не найден", show_alert=True)
                return
            
            text = f"""
📝 <b>Изменение имени агента</b>

👤 <b>Текущее имя:</b> {agent_info['name']}

Введите новое имя для агента. Имя должно быть:
• От 3 до 100 символов
• Понятным и описательным
• Уникальным для ваших задач

📝 <b>Примеры хороших имен:</b>
• "Креативный копирайтер"
• "Деловой редактор"
• "SMM помощник Pro"
• "Дружелюбный рерайтер"

⚠️ <b>Внимание:</b> Имя изменится только в интерфейсе бота. OpenAI агент останется тем же, инструкции не изменятся.

<b>Введите новое имя агента:</b>
"""
            
            keyboards = await self._get_content_keyboards()
            
            await callback.message.edit_text(
                text,
                reply_markup=keyboards['back_to_settings']
            )
            
            # Сохраняем текущие данные в состоянии для сравнения
            await state.update_data(
                current_agent_name=agent_info['name'],
                agent_id=agent_info.get('id')
            )
            
            if CONTENT_STATES_AVAILABLE:
                await state.set_state(ContentStates.editing_agent_name)
            
            self.logger.info("✅ Agent name editing flow started", 
                           bot_id=self.bot_id,
                           current_name=agent_info['name'],
                           user_id=callback.from_user.id)
            
        except Exception as e:
            self.logger.error("💥 Failed to start agent name editing", 
                            bot_id=self.bot_id,
                            error=str(e))
            await callback.answer("Ошибка при запуске редактирования имени", show_alert=True)
    
    async def handle_edit_agent_name_input(self, message: Message, state: FSMContext):
        """Обработка нового имени агента"""
        self.logger.info("📝 Edit agent name input received", 
                        user_id=message.from_user.id,
                        bot_id=self.bot_id)
        
        if not self._is_owner(message.from_user.id):
            await message.answer("❌ Доступ запрещен")
            return
        
        try:
            new_name = message.text.strip()
            
            # Валидация нового имени
            if not new_name:
                await message.answer("❌ Имя не может быть пустым. Попробуйте еще раз:")
                return
            
            if len(new_name) < 3:
                await message.answer("❌ Имя слишком короткое (минимум 3 символа). Попробуйте еще раз:")
                return
            
            if len(new_name) > 100:
                await message.answer("❌ Имя слишком длинное (максимум 100 символов). Попробуйте еще раз:")
                return
            
            # Получаем данные из состояния
            data = await state.get_data()
            current_name = data.get('current_agent_name')
            
            if not current_name:
                await message.answer("❌ Ошибка: потеряны данные агента. Попробуйте заново:")
                await state.clear()
                return
            
            # Проверяем, отличается ли новое имя от текущего
            if new_name == current_name:
                await message.answer("❌ Новое имя совпадает с текущим. Введите другое имя:")
                return
            
            # Показываем процесс изменения
            processing_msg = await message.answer(
                f"⏳ <b>Изменение имени агента...</b>\n\n"
                f"📝 Старое имя: {current_name}\n"
                f"✨ Новое имя: {new_name}\n\n"
                f"💾 Обновление базы данных..."
            )
            
            # Обновляем имя через сервис
            result = await content_agent_service.update_agent(
                bot_id=self.bot_id,
                agent_name=new_name
            )
            
            # Удаляем сообщение о процессе
            try:
                await processing_msg.delete()
            except:
                pass
            
            if result['success']:
                # Успешное обновление
                text = f"""
✅ <b>Имя агента изменено!</b>

📝 <b>Старое имя:</b> {current_name}
✨ <b>Новое имя:</b> {new_name}
🔄 <b>Изменено:</b> {self._format_date()}

🎯 <b>Что изменилось:</b>
• Имя в интерфейсе бота обновлено
• Статистика сохранена под новым именем
• OpenAI агент остался тем же

<b>Что дальше?</b>
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📋 Изменить инструкции", callback_data="content_edit_instructions")],
                    [InlineKeyboardButton(text="⚙️ К настройкам", callback_data="content_settings")],
                    [InlineKeyboardButton(text="📊 Главное меню", callback_data="content_main")]
                ])
                
                await message.answer(text, reply_markup=keyboard)
                
                self.logger.info("✅ Agent name updated successfully", 
                               bot_id=self.bot_id,
                               old_name=current_name,
                               new_name=new_name)
            else:
                # Ошибка обновления
                error_message = result.get('message', 'Неизвестная ошибка')
                
                text = f"""
❌ <b>Ошибка изменения имени</b>

<b>Причина:</b> {error_message}

🔧 <b>Что можно попробовать:</b>
• Попробовать другое имя
• Проверить подключение к базе данных
• Попробовать позже
• Обратиться к администратору

<b>Текущее имя остается:</b> {current_name}
"""
                
                keyboards = await self._get_content_keyboards()
                
                await message.answer(
                    text,
                    reply_markup=keyboards['back_to_settings']
                )
                
                self.logger.error("❌ Agent name update failed", 
                               bot_id=self.bot_id,
                               old_name=current_name,
                               new_name=new_name,
                               error=result.get('error'),
                               message=error_message)
            
            # Очищаем состояние
            await state.clear()
            
        except Exception as e:
            self.logger.error("💥 Failed to handle agent name edit input", 
                            bot_id=self.bot_id,
                            error=str(e))
            await message.answer("❌ Ошибка при обработке нового имени. Попробуйте еще раз:")
    
    async def cb_edit_agent_instructions(self, callback: CallbackQuery, state: FSMContext):
        """Начало редактирования инструкций агента"""
        self.logger.info("📋 Edit agent instructions started", 
                        user_id=callback.from_user.id,
                        bot_id=self.bot_id)
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Получаем текущую информацию об агенте
            agent_info = await content_agent_service.get_agent_info(self.bot_id)
            
            if not agent_info:
                await callback.answer("Агент не найден", show_alert=True)
                return
            
            text = f"""
📋 <b>Изменение инструкций агента</b>

👤 <b>Агент:</b> {agent_info['name']}

📝 <b>Текущие инструкции:</b>
<i>{agent_info['instructions']}</i>

Введите новые инструкции для рерайта. Инструкции должны быть:
• От 10 до 2000 символов
• Четкими и понятными для ИИ
• Описывать желаемый стиль обработки

📋 <b>Примеры хороших инструкций:</b>

<b>Для соцсетей:</b>
"Переписывай в легком, дружелюбном тоне. Добавляй эмоджи, делай текст более живым и привлекательным для аудитории соцсетей."

<b>Для бизнеса:</b>
"Преобразуй в профессиональный деловой стиль. Структурируй информацию, убирай лишние эмоции, фокусируйся на фактах и выгодах."

⚠️ <b>ВАЖНО:</b> Изменение инструкций повлияет на все будущие рерайты. OpenAI агент будет обновлен с новыми инструкциями.

<b>Введите новые инструкции:</b>
"""
            
            keyboards = await self._get_content_keyboards()
            
            await callback.message.edit_text(
                text,
                reply_markup=keyboards['back_to_settings']
            )
            
            # Сохраняем текущие данные в состоянии
            await state.update_data(
                current_instructions=agent_info['instructions'],
                agent_id=agent_info.get('id'),
                agent_name=agent_info['name']
            )
            
            if CONTENT_STATES_AVAILABLE:
                await state.set_state(ContentStates.editing_agent_instructions)
            
            self.logger.info("✅ Agent instructions editing flow started", 
                           bot_id=self.bot_id,
                           agent_name=agent_info['name'],
                           current_instructions_length=len(agent_info['instructions']),
                           user_id=callback.from_user.id)
            
        except Exception as e:
            self.logger.error("💥 Failed to start agent instructions editing", 
                            bot_id=self.bot_id,
                            error=str(e))
            await callback.answer("Ошибка при запуске редактирования инструкций", show_alert=True)
    
    async def handle_edit_agent_instructions_input(self, message: Message, state: FSMContext):
        """Обработка новых инструкций агента"""
        self.logger.info("📋 Edit agent instructions input received", 
                        user_id=message.from_user.id,
                        bot_id=self.bot_id,
                        instructions_length=len(message.text or ""))
        
        if not self._is_owner(message.from_user.id):
            await message.answer("❌ Доступ запрещен")
            return
        
        try:
            new_instructions = message.text.strip()
            
            # Валидация новых инструкций
            if not new_instructions:
                await message.answer("❌ Инструкции не могут быть пустыми. Попробуйте еще раз:")
                return
            
            if len(new_instructions) < 10:
                await message.answer("❌ Инструкции слишком короткие (минимум 10 символов). Опишите подробнее:")
                return
            
            if len(new_instructions) > 2000:
                await message.answer("❌ Инструкции слишком длинные (максимум 2000 символов). Сократите:")
                return
            
            # Получаем данные из состояния
            data = await state.get_data()
            current_instructions = data.get('current_instructions')
            agent_name = data.get('agent_name')
            
            if not current_instructions or not agent_name:
                await message.answer("❌ Ошибка: потеряны данные агента. Попробуйте заново:")
                await state.clear()
                return
            
            # Проверяем, отличаются ли новые инструкции от текущих
            if new_instructions == current_instructions:
                await message.answer("❌ Новые инструкции совпадают с текущими. Введите другие инструкции:")
                return
            
            # Показываем предпросмотр изменений
            text = f"""
📋 <b>Подтверждение изменения инструкций</b>

👤 <b>Агент:</b> {agent_name}

📝 <b>Старые инструкции:</b>
<i>{self._truncate_text(current_instructions, 300)}</i>

✨ <b>Новые инструкции:</b>
<i>{self._truncate_text(new_instructions, 300)}</i>

📊 <b>Изменения:</b>
• Длина: {len(current_instructions)} → {len(new_instructions)} символов
• Изменение: {'+' if len(new_instructions) > len(current_instructions) else ''}{len(new_instructions) - len(current_instructions)} символов

⚠️ <b>ВНИМАНИЕ:</b>
• OpenAI агент будет обновлен новыми инструкциями
• Это повлияет на все будущие рерайты
• Изменение нельзя отменить (но можно изменить заново)

<b>Применить новые инструкции?</b>
"""
            
            # Сохраняем новые инструкции в состоянии
            await state.update_data(
                current_instructions=current_instructions,
                new_instructions=new_instructions,
                agent_name=agent_name
            )
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Применить изменения", callback_data="content_confirm_instructions_update")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="content_settings")]
            ])
            
            await message.answer(text, reply_markup=keyboard)
            
            self.logger.info("✅ Agent instructions change preview shown", 
                           bot_id=self.bot_id,
                           agent_name=agent_name,
                           old_length=len(current_instructions),
                           new_length=len(new_instructions))
            
        except Exception as e:
            self.logger.error("💥 Failed to handle agent instructions edit input", 
                            bot_id=self.bot_id,
                            error=str(e))
            await message.answer("❌ Ошибка при обработке новых инструкций. Попробуйте еще раз:")
    
    async def cb_confirm_instructions_update(self, callback: CallbackQuery, state: FSMContext):
        """✅ Подтверждение обновления инструкций агента"""
        self.logger.info("✅ Instructions update confirmation received", 
                        user_id=callback.from_user.id,
                        bot_id=self.bot_id)
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Получаем данные из состояния
            data = await state.get_data()
            current_instructions = data.get('current_instructions')
            new_instructions = data.get('new_instructions')
            agent_name = data.get('agent_name')
            
            if not all([current_instructions, new_instructions, agent_name]):
                await callback.answer("Ошибка: данные потеряны", show_alert=True)
                await state.clear()
                return
            
            # Показываем процесс обновления
            await callback.message.edit_text(
                f"⏳ <b>Обновление инструкций агента '{agent_name}'...</b>\n\n"
                f"🤖 Обновление OpenAI агента...\n"
                f"💾 Сохранение в базу данных...\n"
                f"🔄 Синхронизация изменений...\n\n"
                f"<i>Это может занять несколько секунд</i>"
            )
            
            # Обновляем инструкции через сервис
            result = await content_agent_service.update_agent(
                bot_id=self.bot_id,
                instructions=new_instructions
            )
            
            if result['success']:
                # Успешное обновление
                text = f"""
✅ <b>Инструкции агента обновлены!</b>

👤 <b>Агент:</b> {agent_name}
🔄 <b>Изменено:</b> {self._format_date()}
📊 <b>Изменение длины:</b> {'+' if len(new_instructions) > len(current_instructions) else ''}{len(new_instructions) - len(current_instructions)} символов

📋 <b>Новые инструкции:</b>
<i>{self._truncate_text(new_instructions, 400)}</i>

🎯 <b>Что изменилось:</b>
• OpenAI агент обновлен новыми инструкциями
• Все будущие рерайты будут использовать новый стиль
• Изменения вступили в силу немедленно

<b>Протестировать новые инструкции?</b>
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📝 Тест рерайта", callback_data="content_rewrite")],
                    [InlineKeyboardButton(text="⚙️ К настройкам", callback_data="content_settings")],
                    [InlineKeyboardButton(text="📊 Главное меню", callback_data="content_main")]
                ])
                
                await callback.message.edit_text(text, reply_markup=keyboard)
                
                self.logger.info("✅ Agent instructions updated successfully", 
                               bot_id=self.bot_id,
                               agent_name=agent_name,
                               old_length=len(current_instructions),
                               new_length=len(new_instructions))
            else:
                # Ошибка обновления
                error_message = result.get('message', 'Неизвестная ошибка')
                
                text = f"""
❌ <b>Ошибка обновления инструкций</b>

<b>Причина:</b> {error_message}

🔧 <b>Что можно попробовать:</b>
• Попробовать еще раз
• Проверить подключение к OpenAI
• Попробовать другие инструкции
• Обратиться к администратору

<b>Текущие инструкции остаются без изменений.</b>

<b>Попробовать снова?</b>
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="content_edit_instructions")],
                    [InlineKeyboardButton(text="⚙️ К настройкам", callback_data="content_settings")],
                    [InlineKeyboardButton(text="📊 Главное меню", callback_data="content_main")]
                ])
                
                await callback.message.edit_text(text, reply_markup=keyboard)
                
                self.logger.error("❌ Agent instructions update failed", 
                               bot_id=self.bot_id,
                               agent_name=agent_name,
                               error=result.get('error'),
                               message=error_message)
            
            # Очищаем состояние
            await state.clear()
            
        except Exception as e:
            self.logger.error("💥 Failed to confirm instructions update", 
                            bot_id=self.bot_id,
                            error=str(e),
                            error_type=type(e).__name__,
                            exc_info=True)
            
            await callback.message.edit_text(
                f"💥 <b>Критическая ошибка обновления инструкций</b>\n\n"
                f"<b>Ошибка:</b> {str(e)}\n\n"
                f"Обратитесь к администратору."
            )
            
            await state.clear()
    
    # ===== AGENT DELETION =====
    
    async def cb_delete_agent(self, callback: CallbackQuery):
        """Подтверждение удаления агента"""
        self.logger.info("🗑️ Delete agent confirmation requested", 
                        user_id=callback.from_user.id,
                        bot_id=self.bot_id)
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            agent_info = await content_agent_service.get_agent_info(self.bot_id)
            
            if not agent_info:
                await callback.answer("Агент не найден", show_alert=True)
                return
            
            stats = agent_info.get('stats', {})
            
            text = f"""
🗑️ <b>Удаление агента</b>

👤 <b>Агент:</b> {agent_info['name']}
💰 <b>Токенов использовано:</b> {self._format_number(stats.get('tokens_used', 0))}

⚠️ <b>ВНИМАНИЕ!</b>
При удалении агента:
• Агент будет удален из OpenAI
• Данные в базе будут помечены как неактивные
• Статистика использования сохранится
• Рерайт постов станет недоступен
• Обработка альбомов станет недоступна
• Редактирование постов станет недоступно
• Публикация в каналы станет недоступна

❓ <b>Вы уверены что хотите удалить агента?</b>

Это действие нельзя отменить.
"""
            
            keyboards = await self._get_content_keyboards()
            
            await callback.message.edit_text(
                text,
                reply_markup=keyboards['delete_confirmation']
            )
            
            self.logger.info("🗑️ Agent deletion confirmation shown", 
                           bot_id=self.bot_id,
                           agent_name=agent_info['name'])
            
        except Exception as e:
            self.logger.error("💥 Failed to show agent deletion confirmation", 
                            bot_id=self.bot_id,
                            error=str(e))
            await callback.answer("Ошибка при подготовке удаления", show_alert=True)
    
    async def cb_confirm_delete_agent(self, callback: CallbackQuery):
        """✅ Окончательное подтверждение удаления агента"""
        self.logger.info("🗑️ Agent deletion confirmed", 
                        user_id=callback.from_user.id,
                        bot_id=self.bot_id)
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Показываем процесс удаления
            await callback.message.edit_text(
                "⏳ <b>Удаление агента...</b>\n\n"
                "🤖 Удаление из OpenAI...\n"
                "💾 Обновление базы данных...\n\n"
                "<i>Это может занять несколько секунд</i>"
            )
            
            # Удаляем агента через сервис
            result = await content_agent_service.delete_agent(self.bot_id)
            
            if result['success']:
                deleted_agent = result.get('deleted_agent', {})
                
                text = f"""
✅ <b>Агент удален успешно</b>

👤 <b>Удаленный агент:</b> {deleted_agent.get('name', 'Неизвестен')}
🤖 <b>OpenAI очищен:</b> {'✅' if deleted_agent.get('had_openai_integration') else 'Не требовался'}

📊 <b>Что сохранилось:</b>
• Статистика использования токенов
• Записи в логах системы
• История активности бота

💡 <b>Вы можете создать нового агента в любое время.</b>

<b>Создать нового агента?</b>
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✨ Создать нового агента", callback_data="content_create_agent")],
                    [InlineKeyboardButton(text="📊 Главное меню", callback_data="content_main")]
                ])
                
                await callback.message.edit_text(text, reply_markup=keyboard)
                
                self.logger.info("✅ Content agent deleted successfully", 
                               bot_id=self.bot_id,
                               deleted_agent_name=deleted_agent.get('name'))
                               
            else:
                error_message = result.get('message', 'Неизвестная ошибка')
                
                text = f"""
❌ <b>Ошибка удаления агента</b>

<b>Причина:</b> {error_message}

🔧 <b>Что можно попробовать:</b>
• Попробовать еще раз
• Проверить подключение к OpenAI
• Обратиться к администратору

Агент может быть частично удален. Проверьте главное меню.
"""
                
                keyboards = await self._get_content_keyboards()
                
                await callback.message.edit_text(
                    text,
                    reply_markup=keyboards['back_to_main']
                )
                
                self.logger.error("❌ Content agent deletion failed", 
                               bot_id=self.bot_id,
                               error=result.get('error'),
                               message=error_message)
            
        except Exception as e:
            self.logger.error("💥 Failed to confirm agent deletion", 
                            bot_id=self.bot_id,
                            error=str(e),
                            error_type=type(e).__name__,
                            exc_info=True)
            
            await callback.message.edit_text(
                f"💥 <b>Критическая ошибка удаления</b>\n\n"
                f"<b>Ошибка:</b> {str(e)}\n\n"
                f"Обратитесь к администратору."
            )
    
    # ===== REWRITE FUNCTIONALITY =====
    
    async def cb_rewrite_post(self, callback: CallbackQuery, state: FSMContext):
        """Начало режима рерайта постов"""
        self.logger.info("📝 Rewrite mode requested", 
                        user_id=callback.from_user.id,
                        bot_id=self.bot_id)
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Проверяем наличие агента
            agent_info = await content_agent_service.get_agent_info(self.bot_id)
            
            if not agent_info:
                await callback.answer("Агент не найден. Создайте агента сначала.", show_alert=True)
                return
            
            stats = agent_info.get('stats', {})
            
            if not stats.get('has_openai_id'):
                await callback.answer("Ошибка OpenAI интеграции. Пересоздайте агента.", show_alert=True)
                return
            
            text = f"""
📝 <b>Рерайт постов</b>

👤 <b>Активный агент:</b> {agent_info['name']}
💰 <b>Токенов использовано:</b> {self._format_number(stats.get('tokens_used', 0))}

📋 <b>Инструкции агента:</b>
<i>{self._truncate_text(agent_info['instructions'], 200)}</i>

📎 <b>Поддерживаемый контент:</b>
• Текст с фото
• Текст с видео  
• Только текст
• GIF/анимации
• ✨ Альбомы (медиагруппы) {'✅' if MEDIA_GROUP_AVAILABLE else '❌ недоступно'}
• 🔗 Ссылки (автоматически извлекаются и сохраняются)

🎯 <b>Как использовать:</b>
1. Пришлите пост для рерайта (фото/видео + текст или только текст)
2. ✨ Отправьте альбом с подписью для группового рерайта
3. 🔗 Используйте ссылки - они автоматически сохранятся
4. Агент переписывает текст согласно инструкциям
5. Получаете результат с кнопками ✏️ правки и 📤 публикации

⚠️ <b>Внимание:</b>
• Каждый рерайт тратит токены из общего лимита
• Минимальная длина текста: 3 символа
• Медиа файлы остаются без изменений (сохраняется file_id)
• Альбомы обрабатываются как единое целое
• Ссылки извлекаются и передаются агенту для сохранения
• После рерайта доступны правки и публикация

<b>Пришлите пост для рерайта:</b>
"""
            
            keyboards = await self._get_content_keyboards()
            
            await callback.message.edit_text(
                text,
                reply_markup=keyboards['rewrite_mode']
            )
            
            # Устанавливаем состояние ожидания поста
            if CONTENT_STATES_AVAILABLE:
                await state.set_state(ContentStates.waiting_for_rewrite_post)
            
            self.logger.info("✅ Rewrite mode activated successfully", 
                           bot_id=self.bot_id,
                           agent_name=agent_info['name'],
                           user_id=callback.from_user.id)
            
        except Exception as e:
            self.logger.error("💥 Failed to start rewrite mode", 
                            bot_id=self.bot_id,
                            error=str(e))
            await callback.answer("Ошибка при запуске режима рерайта", show_alert=True)
    
    async def handle_rewrite_post_input(self, message: Message, state: FSMContext):
        """✅ Обработка поста для рерайта с полной поддержкой медиа"""
        self.logger.info("📝 Rewrite post input received", 
                        user_id=message.from_user.id,
                        bot_id=self.bot_id,
                        message_id=message.message_id,
                        has_photo=bool(message.photo),
                        has_video=bool(message.video),
                        has_text=bool(message.text),
                        has_caption=bool(message.caption))
        
        if not self._is_owner(message.from_user.id):
            await message.answer("❌ Доступ запрещен")
            return
        
        try:
            # Показываем процесс обработки
            processing_msg = await message.answer(
                "⏳ <b>Обрабатываю пост...</b>\n\n"
                "🔍 Анализ контента...\n"
                "🔗 Извлечение ссылок...\n"
                "🤖 Отправка агенту...\n"
                "💰 Подсчет токенов...\n\n"
                "<i>Это может занять 5-15 секунд</i>"
            )
            
            # Выполняем рерайт через сервис
            result = await content_agent_service.rewrite_post(
                bot_id=self.bot_id,
                message=message,
                user_id=message.from_user.id
            )
            
            # Удаляем сообщение о процессе
            try:
                await processing_msg.delete()
            except:
                pass
            
            if result['success']:
                # Успешный рерайт
                await self._send_rewrite_result(message, result)
                
                self.logger.info("✅ Post rewritten successfully", 
                               bot_id=self.bot_id,
                               original_length=len(result['content']['original_text']),
                               rewritten_length=len(result['content']['rewritten_text']),
                               tokens_used=result['tokens']['total_tokens'],
                               has_media=result['has_media'],
                               has_links=result.get('has_links', False))
            else:
                # Ошибка рерайта
                await self._send_rewrite_error(message, result)
                
                self.logger.error("❌ Post rewrite failed", 
                               bot_id=self.bot_id,
                               error=result.get('error'),
                               message=result.get('message'))
            
        except Exception as e:
            self.logger.error("💥 Failed to handle rewrite post input", 
                            bot_id=self.bot_id,
                            message_id=message.message_id,
                            error=str(e),
                            error_type=type(e).__name__,
                            exc_info=True)
            
            await message.answer(
                f"💥 <b>Ошибка обработки поста</b>\n\n"
                f"<b>Ошибка:</b> {str(e)}\n\n"
                f"Попробуйте еще раз или обратитесь к администратору."
            )
    
    # ===== ✨ MEDIA GROUP HANDLERS =====
    
    async def handle_media_group_rewrite_input(self, messages: List[Message], state: FSMContext):
        """✅ Обработка альбома для рерайта с поддержкой ссылок"""
        
        self.logger.info("📸 Processing media group for rewrite with links support", 
                        bot_id=self.bot_id,
                        media_count=len(messages),
                        media_group_id=messages[0].media_group_id)
        
        try:
            # Показываем процесс обработки
            processing_msg = await messages[0].answer(
                f"⏳ <b>Обрабатываю альбом ({len(messages)} файлов)...</b>\n\n"
                f"🔍 Анализ медиафайлов...\n"
                f"📝 Извлечение текста...\n"
                f"🔗 Извлечение ссылок...\n"
                f"🤖 Отправка агенту...\n\n"
                f"<i>Это может занять 10-20 секунд</i>"
            )
            
            # Извлекаем текст из первого сообщения (только оно может содержать caption)
            original_text = ""
            for message in messages:
                text = message.text or message.caption or ""
                if text:
                    original_text = text.strip()
                    break
            
            if not original_text:
                await processing_msg.delete()
                await messages[0].answer(
                    "❌ <b>Текст не найден в альбоме</b>\n\n"
                    "Добавьте подпись к альбому для рерайта."
                )
                return
            
            if len(original_text) < 3:
                await processing_msg.delete()
                await messages[0].answer(
                    "❌ <b>Текст слишком короткий</b>\n\n"
                    "Минимальная длина текста: 3 символа."
                )
                return
            
            # Извлекаем информацию о всех медиафайлах
            media_group_info = []
            for i, message in enumerate(messages):
                media_info = content_agent_service.extract_media_info(message)
                if media_info:
                    media_info['position'] = i
                    media_info['message_id'] = message.message_id
                    media_group_info.append(media_info)
            
            # ✨ НОВОЕ: Извлекаем ссылки из первого сообщения альбома
            links_info = {'has_links': False, 'links': {}, 'total_links': 0}
            try:
                # Используем функцию извлечения ссылок из content_agent_service
                links_info = content_agent_service.extract_links_from_message(messages[0])
            except Exception as e:
                self.logger.warning("⚠️ Failed to extract links from media group", error=str(e))
            
            self.logger.info("📊 Media group analysis completed with links", 
                           bot_id=self.bot_id,
                           text_length=len(original_text),
                           media_files=len(media_group_info),
                           has_links=links_info['has_links'],
                           total_links=links_info['total_links'])
            
            # Выполняем рерайт через ContentManager
            rewrite_result = await content_agent_service.content_manager.process_content_rewrite(
                bot_id=self.bot_id,
                original_text=original_text,
                media_info={
                    'type': 'media_group',
                    'count': len(messages),
                    'files': media_group_info,
                    'media_group_id': messages[0].media_group_id
                },
                links_info=links_info,  # ✨ НОВОЕ
                user_id=messages[0].from_user.id
            )
            
            # Удаляем сообщение о процессе
            try:
                await processing_msg.delete()
            except:
                pass
            
            if rewrite_result and rewrite_result.get('success'):
                # Успешный рерайт альбома
                await self._send_media_group_rewrite_result(messages, rewrite_result)
                
                self.logger.info("✅ Media group rewritten successfully with links", 
                               bot_id=self.bot_id,
                               media_count=len(messages),
                               tokens_used=rewrite_result.get('tokens', {}).get('total_tokens', 0),
                               has_links=links_info['has_links'])
            else:
                # Ошибка рерайта
                await self._send_rewrite_error(messages[0], rewrite_result or {'error': 'unknown'})
                
        except Exception as e:
            self.logger.error("💥 Failed to process media group rewrite with links", 
                            bot_id=self.bot_id,
                            media_group_id=messages[0].media_group_id,
                            error=str(e))
            await messages[0].answer("Ошибка при обработке альбома")
    
    async def _send_media_group_rewrite_result(self, original_messages: List[Message], result: Dict):
        """🔧 ИЗМЕНЕНО: Отправка результата рерайта альбома с кнопками действий"""
        
        # 🔧 Безопасное извлечение данных из result
        content = self._safe_get_from_result(result, 'content', {})
        tokens = self._safe_get_from_result(result, 'tokens', {})
        media_info = self._safe_get_from_result(result, 'media_info', {})
        agent_info = self._safe_get_from_result(result, 'agent', {})
        
        # Проверяем, что основные данные получены
        if not content or not isinstance(content, dict):
            self.logger.error("❌ No content in media group result", 
                             bot_id=self.bot_id,
                             result_keys=list(result.keys()) if isinstance(result, dict) else 'not_dict')
            await original_messages[0].answer(
                "❌ <b>Ошибка: не получен результат рерайта</b>\n\n"
                "Попробуйте еще раз или обратитесь к администратору."
            )
            return
        
        rewritten_text = content.get('rewritten_text', 'Ошибка: текст не получен')
        
        try:
            # Сохраняем результат рерайта
            save_success = await content_agent_service.content_manager.save_rewrite_result(
                self.bot_id, result
            )
            
            # ✨ УПРОЩЕНО: Формируем caption только с переписанным текстом
            result_caption = rewritten_text
            
            # Создаем медиагруппу для ответа с помощью MediaGroupBuilder
            media_builder = MediaGroupBuilder(caption=result_caption)
            
            # Добавляем файлы в медиагруппу, используя file_id из оригинальных сообщений
            media_added = 0
            for message in original_messages:
                try:
                    if message.photo:
                        # Берем фото наибольшего размера
                        largest_photo = max(message.photo, key=lambda x: x.width * x.height)
                        media_builder.add_photo(media=largest_photo.file_id)
                        media_added += 1
                    elif message.video:
                        media_builder.add_video(media=message.video.file_id)
                        media_added += 1
                    elif message.animation:
                        # Для GIF используем add_video (Telegram ограничение)
                        media_builder.add_video(media=message.animation.file_id)
                        media_added += 1
                except Exception as media_error:
                    self.logger.warning("⚠️ Failed to add media to group", 
                                       bot_id=self.bot_id,
                                       message_id=message.message_id,
                                       error=str(media_error))
            
            if media_added == 0:
                # Если медиа не добавилось, отправляем только текст
                keyboards = await self._get_content_keyboards()
                await original_messages[0].answer(
                    result_caption, 
                    reply_markup=keyboards['post_actions']
                )
                self.logger.warning("⚠️ No media added to group, sent text only", 
                                   bot_id=self.bot_id)
            else:
                # Отправляем медиагруппу
                media_group = media_builder.build()
                sent_messages = await original_messages[0].answer_media_group(
                    media=media_group
                )
                
                # Добавляем кнопки управления после медиагруппы
                keyboards = await self._get_content_keyboards()
                await original_messages[0].answer(
                    "✨ <b>Рерайт готов!</b>",
                    reply_markup=keyboards['post_actions']
                )
                
                self.logger.info("✅ Clean media group sent successfully with action buttons", 
                               bot_id=self.bot_id,
                               media_files=media_added)
            
            # Логируем техническую информацию, но не показываем пользователю
            self.logger.info("✅ Clean media group rewrite result sent", 
                           bot_id=self.bot_id,
                           agent_name=agent_info.get('name', 'Unknown'),
                           media_files=len(original_messages),
                           tokens_used=tokens.get('total_tokens', 0),
                           original_length=len(content.get('original_text', '')),
                           rewritten_length=len(rewritten_text))
            
        except Exception as e:
            self.logger.error("💥 Failed to send clean media group rewrite result", 
                            bot_id=self.bot_id,
                            error=str(e),
                            error_type=type(e).__name__)
            
            # 🔧 ИСПРАВЛЕНО: Безопасный fallback
            fallback_text = rewritten_text
            
            if len(fallback_text) > 4096:
                fallback_text = fallback_text[:4093] + "..."
            
            keyboards = await self._get_content_keyboards()
            await original_messages[0].answer(
                f"{fallback_text}\n\n⚠️ Ошибка отправки медиа: {str(e)}",
                reply_markup=keyboards['post_actions']
            )
    
    # ===== RESULT SENDING =====
    
    async def _send_rewrite_result(self, original_message: Message, result: Dict):
        """ИЗМЕНЕНО: Добавить кнопки после рерайта"""
        try:
            content = result['content']
            media_info = result.get('media')
            
            # Сохраняем результат рерайта
            save_success = await content_agent_service.content_manager.save_rewrite_result(
                self.bot_id, result
            )
            
            # ✨ УПРОЩЕНО: Отправляем только переписанный текст
            rewritten_text = content['rewritten_text']
            
            # Получаем правильные кнопки
            keyboards = await self._get_content_keyboards()
            post_actions_keyboard = keyboards.get('post_actions', keyboards['rewrite_mode'])
            
            # Отправляем результат с медиа или без
            if media_info:
                await self._send_media_with_text(
                    original_message,
                    rewritten_text,  # ✨ Только текст, без технической информации
                    media_info,
                    post_actions_keyboard  # Новые кнопки
                )
            else:
                await original_message.answer(
                    rewritten_text,  # ✨ Только текст, без технической информации
                    reply_markup=post_actions_keyboard  # Новые кнопки
                )
            
            # Логируем техническую информацию, но не показываем пользователю
            tokens = result['tokens']
            agent_info = result['agent']
            
            self.logger.info("✅ Clean rewrite result sent with action buttons", 
                           bot_id=self.bot_id,
                           agent_name=agent_info['name'],
                           has_media=bool(media_info),
                           tokens_used=tokens['total_tokens'],
                           original_length=len(content['original_text']),
                           rewritten_length=len(content['rewritten_text']))
            
        except Exception as e:
            self.logger.error("💥 Failed to send clean rewrite result", 
                            bot_id=self.bot_id,
                            error=str(e))
            await original_message.answer("Ошибка при отправке результата рерайта")
    
    async def _send_rewrite_error(self, original_message: Message, result: Dict):
        """Отправка ошибки рерайта с детализацией"""
        try:
            error_type = result.get('error', 'unknown')
            error_message = result.get('message', 'Неизвестная ошибка')
            
            # Формируем текст ошибки в зависимости от типа
            if error_type == 'no_content_agent':
                text = """
❌ <b>Агент не найден</b>

Контент-агент не настроен. Создайте агента в настройках перед использованием рерайта.
"""
            elif error_type == 'no_text':
                text = """
❌ <b>Текст не найден</b>

В сообщении нет текста для рерайта. Пришлите:
• Фото с подписью
• Видео с подписью  
• Текстовое сообщение
• Альбом с подписью
"""
            elif error_type == 'text_too_short':
                text = """
❌ <b>Текст слишком короткий</b>

Минимальная длина текста для рерайта: 3 символа.
Пришлите более содержательный текст.
"""
            elif error_type == 'token_limit_exceeded':
                tokens_info = result.get('tokens_used', 0)
                tokens_limit = result.get('tokens_limit', 0)
                
                text = f"""
🚫 <b>Лимит токенов исчерпан</b>

Использовано: {self._format_number(tokens_info)} / {self._format_number(tokens_limit)}

Для продолжения работы:
• Обратитесь к администратору для увеличения лимита
• Используйте более короткие тексты
• Дождитесь пополнения токенов
"""
            else:
                text = f"""
❌ <b>Ошибка рерайта</b>

<b>Причина:</b> {error_message}

🔧 <b>Что можно попробовать:</b>
• Попробовать другой пост
• Проверить подключение к интернету
• Попробовать позже
• Обратиться к администратору
"""
            
            keyboards = await self._get_content_keyboards()
            
            await original_message.answer(
                text,
                reply_markup=keyboards['rewrite_mode']
            )
            
            self.logger.info("✅ Rewrite error sent", 
                           bot_id=self.bot_id,
                           error_type=error_type)
            
        except Exception as e:
            self.logger.error("💥 Failed to send rewrite error", 
                            bot_id=self.bot_id,
                            error=str(e))
            await original_message.answer("Критическая ошибка при обработке ошибки рерайта")
    
    async def _send_media_with_text(self, message: Message, text: str, media_info: Dict, keyboard):
        """✅ УПРОЩЕНО: Отправка медиа с переписанным текстом (без технической информации)"""
        try:
            media_type = media_info['type']
            file_id = media_info['file_id']
            
            if media_type == 'photo':
                await message.answer_photo(
                    photo=file_id,
                    caption=text,  # ✨ Только переписанный текст
                    reply_markup=keyboard
                )
                self.logger.debug("📷 Photo sent with clean rewrite result", bot_id=self.bot_id)
                
            elif media_type == 'video':
                await message.answer_video(
                    video=file_id,
                    caption=text,  # ✨ Только переписанный текст
                    reply_markup=keyboard
                )
                self.logger.debug("🎥 Video sent with clean rewrite result", bot_id=self.bot_id)
                
            elif media_type == 'animation':
                await message.answer_animation(
                    animation=file_id,
                    caption=text,  # ✨ Только переписанный текст
                    reply_markup=keyboard
                )
                self.logger.debug("🎬 Animation sent with clean rewrite result", bot_id=self.bot_id)
                
            else:
                # Fallback для других типов медиа
                await message.answer(text, reply_markup=keyboard)
                self.logger.debug("📄 Fallback text sent (unsupported media)", 
                                bot_id=self.bot_id, media_type=media_type)
                
        except Exception as e:
            self.logger.error("💥 Failed to send media with clean text", 
                            media_type=media_info.get('type'),
                            error=str(e))
            # Fallback - отправляем только текст
            await message.answer(text, reply_markup=keyboard)
    
    # ===== НОВЫЕ МЕТОДЫ ДЛЯ КАНАЛОВ И РЕДАКТИРОВАНИЯ =====
    
    async def cb_edit_post(self, callback: CallbackQuery, state: FSMContext):
        """Начало редактирования поста"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Проверяем есть ли последний рерайт
            last_rewrite = await content_agent_service.content_manager.get_last_rewrite(self.bot_id)
            
            if not last_rewrite:
                await callback.answer("Нет данных для редактирования", show_alert=True)
                return
            
            text = """
✏️ <b>Внесение правок в пост</b>

<b>Что нужно изменить?</b>

Опишите какие правки внести:
- "Сделать тон более дружелюбным"
- "Добавить призыв к действию"
- "Убрать лишние эмоджи"
- "Сократить текст вдвое"

<b>Введите инструкции для правок:</b>
"""
            
            keyboards = await self._get_content_keyboards()
            
            await callback.message.answer(
                text, 
                reply_markup=keyboards['back_to_rewrite']
            )
            
            if CONTENT_STATES_AVAILABLE:
                await state.set_state(ContentStates.waiting_for_edit_instructions)
                
        except Exception as e:
            self.logger.error("💥 Error starting post edit", error=str(e))
            await callback.answer("Ошибка начала редактирования", show_alert=True)
    
    async def handle_edit_instructions_input(self, message: Message, state: FSMContext):
        """Обработка инструкций для правок"""
        if not self._is_owner(message.from_user.id):
            await message.answer("❌ Доступ запрещен")
            return
        
        try:
            edit_instructions = message.text.strip()
            
            if not edit_instructions or len(edit_instructions) < 5:
                await message.answer("❌ Инструкции слишком короткие")
                return
            
            # Получаем последний рерайт
            last_rewrite = await content_agent_service.content_manager.get_last_rewrite(self.bot_id)
            
            if not last_rewrite:
                await message.answer("❌ Нет данных для редактирования")
                return
            
            # Показываем процесс
            processing_msg = await message.answer("⏳ Применяю правки...")
            
            # Формируем новый промпт для правок
            edit_prompt = f"""
Внеси следующие правки в текст:

ПРАВКИ: {edit_instructions}

ИСХОДНЫЙ ТЕКСТ:
{last_rewrite['content']['rewritten_text']}

Примени только указанные правки, сохрани остальное содержание.
"""
            
            # Выполняем рерайт с правками
            edit_result = await content_agent_service.content_manager.process_content_rewrite(
                bot_id=self.bot_id,
                original_text=edit_prompt,
                media_info=last_rewrite.get('media_info'),
                links_info=last_rewrite.get('links_info'),
                user_id=message.from_user.id
            )
            
            try:
                await processing_msg.delete()
            except:
                pass
            
            if edit_result and edit_result.get('success'):
                # Обновляем сохраненный рерайт
                await content_agent_service.content_manager.save_rewrite_result(
                    self.bot_id, edit_result
                )
                
                # Отправляем результат с кнопками
                keyboards = await self._get_content_keyboards()
                
                if edit_result.get('media'):
                    await self._send_media_with_text(
                        message,
                        edit_result['content']['rewritten_text'],
                        edit_result['media'],
                        keyboards['post_actions']
                    )
                else:
                    await message.answer(
                        edit_result['content']['rewritten_text'],
                        reply_markup=keyboards['post_actions']
                    )
            else:
                await message.answer("❌ Ошибка применения правок")
            
            await state.clear()
            
        except Exception as e:
            self.logger.error("💥 Error processing edit instructions", error=str(e))
            await message.answer("Ошибка обработки правок")
    
    async def cb_publish_post(self, callback: CallbackQuery):
        """Публикация поста в канал"""
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Получаем данные канала и последний рерайт
            channel_info = await content_agent_service.content_manager.get_channel_info(self.bot_id)
            last_rewrite = await content_agent_service.content_manager.get_last_rewrite(self.bot_id)
            
            if not channel_info or not last_rewrite:
                await callback.answer("Нет данных для публикации", show_alert=True)
                return
            
            channel_id = channel_info['chat_id']
            rewritten_text = last_rewrite['content']['rewritten_text']
            media_info = last_rewrite.get('media')
            
            # Показываем процесс через answer вместо edit_text
            await callback.answer("⏳ Публикую в канал...", show_alert=True)
            
            # Публикуем в канал
            if media_info:
                await self._publish_media_to_channel(channel_id, rewritten_text, media_info)
            else:
                await self.bot_config['bot'].send_message(channel_id, rewritten_text)
            
            # Создаем клавиатуру для результата
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📝 Новый рерайт", callback_data="content_rewrite")],
                [InlineKeyboardButton(text="📊 Главное меню", callback_data="content_main")]
            ])
            
            # Успешная публикация
            try:
                text = f"""
✅ <b>Пост опубликован!</b>

📺 <b>Канал:</b> {channel_info['chat_title']}
📝 <b>Текст:</b> {self._truncate_text(rewritten_text, 150)}

<b>Что дальше?</b>
"""
                await callback.message.answer(text, reply_markup=keyboard)
            except Exception as parse_error:
                # Упрощенный вариант без проблемного текста
                simple_text = f"""
✅ <b>Пост опубликован в канал!</b>

📺 <b>Канал:</b> {channel_info['chat_title']}

<b>Что дальше?</b>
"""
                await callback.message.answer(simple_text, reply_markup=keyboard)
                self.logger.info("✅ Post published but used simplified result message due to HTML parsing error")
            
        except Exception as e:
            self.logger.error("💥 Error publishing post", error=str(e))
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📝 Попробовать снова", callback_data="content_rewrite")],
                [InlineKeyboardButton(text="📊 Главное меню", callback_data="content_main")]
            ])
            await callback.message.answer("❌ Ошибка публикации в канал", reply_markup=keyboard)
    
    async def _publish_media_to_channel(self, channel_id: int, text: str, media_info: Dict):
        """Публикация медиа в канал"""
        try:
            media_type = media_info['type']
            file_id = media_info['file_id']
            bot = self.bot_config['bot']
            
            if media_type == 'photo':
                await bot.send_photo(channel_id, photo=file_id, caption=text)
            elif media_type == 'video':
                await bot.send_video(channel_id, video=file_id, caption=text)
            elif media_type == 'animation':
                await bot.send_animation(channel_id, animation=file_id, caption=text)
            else:
                await bot.send_message(channel_id, text)
                
        except Exception as e:
            self.logger.error("💥 Error publishing media to channel", error=str(e))
            raise
    
    async def cb_exit_rewrite_mode(self, callback: CallbackQuery, state: FSMContext):
        """✅ Выход из режима рерайта"""
        self.logger.info("🚪 Exit rewrite mode requested", 
                        user_id=callback.from_user.id,
                        bot_id=self.bot_id)
        
        await callback.answer()
        
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            await state.clear()
            
            text = f"""
🚪 <b>Режим рерайта завершен</b>

Спасибо за использование контент-агента!

📊 <b>Что вы можете сделать:</b>
• Посмотреть статистику использования
• Изменить настройки агента
• Начать новую сессию рерайта
• Вернуться в главное меню админки

<b>Куда перейти?</b>
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📝 Новая сессия рерайта", callback_data="content_rewrite")],
                [InlineKeyboardButton(text="⚙️ Управление агентом", callback_data="content_manage")],
                [InlineKeyboardButton(text="📊 Контент-меню", callback_data="content_main")],
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_main")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
            self.logger.info("✅ Rewrite mode exited successfully", 
                           bot_id=self.bot_id,
                           user_id=callback.from_user.id)
            
        except Exception as e:
            self.logger.error("💥 Failed to exit rewrite mode", 
                            bot_id=self.bot_id,
                            error=str(e))
            await callback.answer("Ошибка при выходе из режима рерайта", show_alert=True)
