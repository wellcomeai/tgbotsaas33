"""
Главная функция регистрации обработчиков контент-агентов.

✅ ОБНОВЛЕНО В ЭТОЙ ВЕРСИИ:
1. 🎤 НОВОЕ: Поддержка голосовых сообщений через OpenAI Whisper API
2. 🔧 ИСПРАВЛЕНА критическая ошибка в _send_media_group_rewrite_result
3. 🛡️ Улучшена обработка ошибок и валидация данных
4. 🚀 Оптимизирована работа с медиагруппами
5. 📊 Добавлено детальное логирование для отладки
6. 🔒 Усилена безопасность работы с переменными
7. ✨ НОВОЕ: Упрощенный вывод для пользователей
8. 🔗 НОВОЕ: Поддержка извлечения ссылок из медиагрупп
9. 📺 НОВОЕ: Интеграция с каналами для публикации
10. ✏️ НОВОЕ: Редактирование постов с правками
11. 📤 НОВОЕ: Публикация в каналы
12. 🎤 НОВОЕ: Голосовые сообщения для всех типов ввода
13. 🏗️ НОВОЕ: Модульная архитектура с миксинами
"""

import structlog
from typing import List
from aiogram import Dispatcher, F
from aiogram.types import Message

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

# ✅ Безопасный импорт состояний с fallback
try:
    from ...states import ContentStates
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

# ✅ Импорт модульного ContentHandler
from .base_handler import ContentHandler


def register_content_handlers(dp: Dispatcher, **kwargs):
    """✅ Регистрация обработчиков контент-агентов с полной поддержкой медиагрупп, каналов и голосовых сообщений"""
    
    logger = structlog.get_logger()
    logger.info("📝 Registering content handlers with complete modular architecture", 
                media_group_support=MEDIA_GROUP_AVAILABLE,
                voice_messages_support=True,
                channel_integration=True,
                modular_architecture=True)
    
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
        # Создаем обработчик с модульной архитектурой
        handler = ContentHandler(db, bot_config, user_bot)
        
        logger.info("✅ ContentHandler created with modular architecture", 
                   bot_id=handler.bot_id,
                   mixins_loaded=[
                       'AgentCreationMixin',
                       'AgentManagementMixin', 
                       'RewriteHandlersMixin',
                       'MediaHandlersMixin',
                       'VoiceHandlersMixin',
                       'ChannelHandlersMixin',
                       'ContentUtilsMixin'
                   ])
        
        # ===== РЕГИСТРАЦИЯ ОБРАБОТЧИКОВ =====
        
        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: ПРАВИЛЬНЫЙ ПОРЯДОК - специфичные обработчики ПЕРВЫЕ!
        
        # ✅ Обработчик медиагрупп (должен быть ПЕРВЫМ среди обработчиков сообщений)
        if MEDIA_GROUP_AVAILABLE and CONTENT_STATES_AVAILABLE:
            @dp.message(F.media_group_id, F.content_type.in_({'photo', 'video'}))
            @media_group_handler
            async def handle_media_group_rewrite(messages: List[Message], state):
                """✅ Обработка альбомов для рерайта через aiogram-media-group"""
                
                # Проверяем, что мы в режиме рерайта
                from aiogram.fsm.context import FSMContext
                if isinstance(state, FSMContext):
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
                    # Обрабатываем альбом через миксин
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
        
        # ===== CALLBACK QUERY ОБРАБОТЧИКИ =====
        
        # 1. Главное меню контента
        dp.callback_query.register(handler.cb_content_main, F.data == "content_main")
        
        # 2. Создание агента (полный цикл) - методы из AgentCreationMixin
        dp.callback_query.register(handler.cb_create_agent, F.data == "content_create_agent")
        dp.callback_query.register(handler.cb_confirm_create_agent, F.data == "content_confirm_create")
        
        # 3. Управление агентом - методы из AgentManagementMixin
        dp.callback_query.register(handler.cb_manage_agent, F.data == "content_manage")
        dp.callback_query.register(handler.cb_agent_settings, F.data == "content_settings")
        
        # 4. Редактирование агента - методы из AgentManagementMixin
        dp.callback_query.register(handler.cb_edit_agent_name, F.data == "content_edit_name")
        dp.callback_query.register(handler.cb_edit_agent_instructions, F.data == "content_edit_instructions")
        dp.callback_query.register(handler.cb_confirm_instructions_update, F.data == "content_confirm_instructions_update")
        
        # 5. Удаление агента - методы из AgentManagementMixin
        dp.callback_query.register(handler.cb_delete_agent, F.data == "content_delete_agent")
        dp.callback_query.register(handler.cb_confirm_delete_agent, F.data == "content_confirm_delete")
        
        # 6. Рерайт постов - методы из RewriteHandlersMixin
        dp.callback_query.register(handler.cb_rewrite_post, F.data == "content_rewrite")
        dp.callback_query.register(handler.cb_exit_rewrite_mode, F.data == "content_exit_rewrite")
        
        # 7. Каналы - методы из ChannelHandlersMixin
        dp.callback_query.register(handler.cb_edit_post, F.data == "content_edit_post")
        dp.callback_query.register(handler.cb_publish_post, F.data == "content_publish")
        
        callback_handlers_count = 14
        
        # ===== FSM MESSAGE ОБРАБОТЧИКИ =====
        
        fsm_handlers_registered = 0
        
        if CONTENT_STATES_AVAILABLE:
            # Обработчики только для текстового ввода (имена агентов) - AgentCreationMixin + AgentManagementMixin
            dp.message.register(
                handler.handle_agent_name_input,
                ContentStates.waiting_for_agent_name,
                F.text
            )
            dp.message.register(
                handler.handle_edit_agent_name_input,
                ContentStates.editing_agent_name,
                F.text
            )
            dp.message.register(
                handler.handle_channel_post_input,
                ContentStates.waiting_for_channel_post
            )
            text_only_handlers = 3
            
            # Обработчики для инструкций агента (текст + голос) - AgentCreationMixin + AgentManagementMixin + VoiceHandlersMixin
            dp.message.register(
                handler.handle_agent_instructions_input,
                ContentStates.waiting_for_agent_instructions,
                F.text
            )
            dp.message.register(
                handler.handle_agent_instructions_input,
                ContentStates.waiting_for_agent_instructions,
                F.voice
            )
            dp.message.register(
                handler.handle_edit_agent_instructions_input,
                ContentStates.editing_agent_instructions,
                F.text
            )
            dp.message.register(
                handler.handle_edit_agent_instructions_input,
                ContentStates.editing_agent_instructions,
                F.voice
            )
            voice_text_handlers = 4
            
            # 🎯 ИСПРАВЛЕНО: Обработчики для рерайта постов (ВСЕ ТИПЫ КОНТЕНТА) - RewriteHandlersMixin
            # Текстовые сообщения
            dp.message.register(
                handler.handle_rewrite_post_input,
                ContentStates.waiting_for_rewrite_post,
                F.text
            )
            # Голосовые сообщения
            dp.message.register(
                handler.handle_rewrite_post_input,
                ContentStates.waiting_for_rewrite_post,
                F.voice
            )
            # 📷 ФОТО (с подписью или без)
            dp.message.register(
                handler.handle_rewrite_post_input,
                ContentStates.waiting_for_rewrite_post,
                F.photo
            )
            # 🎥 ВИДЕО (с подписью или без)  
            dp.message.register(
                handler.handle_rewrite_post_input,
                ContentStates.waiting_for_rewrite_post,
                F.video
            )
            # 🎬 GIF/АНИМАЦИИ
            dp.message.register(
                handler.handle_rewrite_post_input,
                ContentStates.waiting_for_rewrite_post,
                F.animation
            )
            # 🎵 АУДИО
            dp.message.register(
                handler.handle_rewrite_post_input,
                ContentStates.waiting_for_rewrite_post,
                F.audio
            )
            # 📄 ДОКУМЕНТЫ
            dp.message.register(
                handler.handle_rewrite_post_input,
                ContentStates.waiting_for_rewrite_post,
                F.document
            )
            # 🎭 СТИКЕРЫ
            dp.message.register(
                handler.handle_rewrite_post_input,
                ContentStates.waiting_for_rewrite_post,
                F.sticker
            )
            media_handlers = 8
            
            # Обработчики для правок постов (текст + голос) - ChannelHandlersMixin + VoiceHandlersMixin
            dp.message.register(
                handler.handle_edit_instructions_input,
                ContentStates.waiting_for_edit_instructions,
                F.text
            )
            dp.message.register(
                handler.handle_edit_instructions_input,
                ContentStates.waiting_for_edit_instructions,
                F.voice
            )
            edit_handlers = 2
            
            fsm_handlers_registered = text_only_handlers + voice_text_handlers + media_handlers + edit_handlers
            
            logger.info("✅ All FSM message handlers with modular architecture registered successfully")
        else:
            text_only_handlers = 0
            voice_text_handlers = 0
            media_handlers = 0
            edit_handlers = 0
            logger.warning("⚠️ FSM states unavailable, some functionality will be limited")
        
        # Подсчет обработчиков
        media_group_handlers = 1 if MEDIA_GROUP_AVAILABLE and CONTENT_STATES_AVAILABLE else 0
        total_handlers = callback_handlers_count + fsm_handlers_registered + media_group_handlers
        
        logger.info("✅ Content handlers registered successfully with COMPLETE MODULAR ARCHITECTURE", 
                   bot_id=bot_config['bot_id'],
                   callback_handlers=callback_handlers_count,
                   text_only_handlers=text_only_handlers,
                   voice_text_handlers=voice_text_handlers, 
                   media_handlers=media_handlers,
                   edit_handlers=edit_handlers,
                   media_group_handlers=media_group_handlers,
                   total_handlers=total_handlers,
                   voice_support_enabled=True,
                   supported_media_types=['photo', 'video', 'animation', 'audio', 'document', 'sticker'],
                   modular_architecture="✅ All mixins integrated successfully",
                   mixins_used=[
                       'AgentCreationMixin',
                       'AgentManagementMixin', 
                       'RewriteHandlersMixin',
                       'MediaHandlersMixin',
                       'VoiceHandlersMixin',
                       'ChannelHandlersMixin',
                       'ContentUtilsMixin'
                   ])
        
    except Exception as e:
        logger.error("💥 Failed to register content handlers with modular architecture", 
                    bot_id=kwargs.get('bot_config', {}).get('bot_id', 'unknown'),
                    error=str(e),
                    error_type=type(e).__name__,
                    exc_info=True)
        raise
