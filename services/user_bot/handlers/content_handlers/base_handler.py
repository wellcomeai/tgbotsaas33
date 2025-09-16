"""
Базовый класс ContentHandler с полной функциональностью через миксины.

✅ ПОЛНАЯ ФУНКЦИОНАЛЬНОСТЬ:
1. 🎤 Транскрипция голосовых сообщений через OpenAI Whisper API
2. 🔧 Утилиты форматирования и валидации данных
3. 🛡️ Безопасные методы работы с сообщениями
4. 🔒 Проверка прав доступа владельца
5. ⌨️ Генерация всех клавиатур интерфейса
6. 📊 Форматирование чисел, дат, текста
7. 🎯 Извлечение данных из результатов
8. ✨ Создание агентов с голосовыми инструкциями
9. ⚙️ Управление и редактирование агентов
10. 📝 Рерайт постов всех типов контента
11. 📸 Работа с медиа и альбомами
12. 📤 Публикация в каналы
"""

import structlog
from services.content_agent import content_agent_service

# Импортируем все миксины
from .agent_creation import AgentCreationMixin
from .agent_management import AgentManagementMixin
from .rewrite_handlers import RewriteHandlersMixin
from .media_handlers import MediaHandlersMixin
from .voice_handlers import VoiceHandlersMixin
from .channel_handlers import ChannelHandlersMixin
from .utils import ContentUtilsMixin


class ContentHandler(
    AgentCreationMixin,
    AgentManagementMixin, 
    RewriteHandlersMixin,
    MediaHandlersMixin,
    VoiceHandlersMixin,
    ChannelHandlersMixin,
    ContentUtilsMixin
):
    """✅ Полный обработчик контент-агентов с модульной архитектурой
    
    Наследует функциональность от всех миксинов:
    - AgentCreationMixin: создание агентов с голосовыми инструкциями
    - AgentManagementMixin: управление и редактирование агентов
    - RewriteHandlersMixin: рерайт постов всех типов
    - MediaHandlersMixin: работа с медиа и альбомами
    - VoiceHandlersMixin: транскрипция голосовых сообщений
    - ChannelHandlersMixin: публикация в каналы
    - ContentUtilsMixin: вспомогательные функции и утилиты
    """
    
    def __init__(self, db, bot_config: dict, user_bot):
        self.db = db
        self.bot_config = bot_config
        self.bot_id = bot_config['bot_id']
        self.owner_user_id = bot_config['owner_user_id']
        self.bot_username = bot_config['bot_username']
        self.user_bot = user_bot
        self.logger = structlog.get_logger()
        
        self.logger.info("🔧 ContentHandler initialized with complete modular architecture", 
                        bot_id=self.bot_id,
                        bot_username=self.bot_username,
                        owner_user_id=self.owner_user_id,
                        voice_support=True,
                        mixins=[
                            'AgentCreationMixin',
                            'AgentManagementMixin', 
                            'RewriteHandlersMixin',
                            'MediaHandlersMixin',
                            'VoiceHandlersMixin',
                            'ChannelHandlersMixin',
                            'ContentUtilsMixin'
                        ])
    
    # ===== ГЛАВНОЕ МЕНЮ =====
    
    async def cb_content_main(self, callback_query):
        """✅ Главное меню контент-агентов с детальным логированием + голосовая поддержка"""
        self.logger.info("📝 Content main menu accessed", 
                        user_id=callback_query.from_user.id,
                        bot_id=self.bot_id,
                        callback_data=callback_query.data)
        
        await callback_query.answer()
        
        if not self._is_owner(callback_query.from_user.id):
            self.logger.warning("🚫 Access denied for non-owner", 
                               user_id=callback_query.from_user.id,
                               bot_id=self.bot_id)
            await callback_query.answer("❌ Доступ запрещен", show_alert=True)
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
• 📝 Переписывает текст согласно вашим инструкциям
• 📷 Создает описания для фото без подписи
• 🎥 Создает описания для видео без подписи
• 📄 Обрабатывает любые типы файлов
• ✨ Обрабатывает альбомы (медиагруппы)
• 🔗 Извлекает и сохраняет ссылки
• ✏️ Позволяет редактировать и вносить правки
• 📤 Публикует готовые посты в каналы
• 🎤 <b>Поддерживает голосовые сообщения для всех операций</b>
• 🤖 Интегрирован с единой токеновой системой

{self._get_supported_content_types()}

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
                text = f"""
📝 <b>Контент канала @{self.bot_username}</b>

❌ <b>Агент не создан</b>

Для рерайта контента нужно создать ИИ агента:

🎯 <b>Что такое контент-агент:</b>
• Специальный ИИ для переписывания постов
• Работает на базе OpenAI GPT-4o
• Следует вашим инструкциям по стилю
• 📷 Работает с ЛЮБЫМИ медиа файлами
• 🎥 Поддерживает все форматы (фото, видео, GIF, аудио, документы, стикеры)
• ✨ Поддерживает альбомы (медиагруппы)
• 🔗 Извлекает и сохраняет ссылки
• ✏️ Позволяет редактировать готовые посты
• 📤 Публикует готовые посты в каналы
• 🎤 <b>Работает с голосовыми сообщениями</b>

📋 <b>Как создать:</b>
1. Нажмите "Создать агента" 
2. Укажите канал для публикации
3. Введите имя агента
4. Опишите как переписывать тексты (текстом или голосом)
5. Агент готов к работе!

🎯 <b>Что агент умеет обрабатывать:</b>
• 📝 Текст → переписывает согласно инструкциям
• 📷 Фото без подписи → создает описание
• 🎥 Видео без подписи → создает описание  
• 📄 Любые файлы → создает описание или рерайт подписи
• 🎤 Голос → транскрибирует и переписывает
• ✨ Альбомы → групповая обработка

🔧 <b>Статус системы:</b>
{self._format_system_capabilities()}

<b>Создать агента сейчас?</b>
"""
                keyboard = keyboards['main_menu_no_agent']
                self.logger.info("📋 No agent found, showing creation menu", bot_id=self.bot_id)
            
            await self._safe_edit_or_answer(callback_query, text, keyboard)
            
            self.logger.info("✅ Content main menu displayed successfully with voice support", 
                           bot_id=self.bot_id,
                           has_agent=has_agent)
            
        except Exception as e:
            self.logger.error("💥 Failed to show content main menu", 
                            bot_id=self.bot_id,
                            error=str(e),
                            error_type=type(e).__name__,
                            exc_info=True)
            
            await callback_query.answer("Ошибка при загрузке меню контента", show_alert=True)
