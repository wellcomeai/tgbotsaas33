import os
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # Telegram Bot Settings
    master_bot_token: str = Field(..., env="MASTER_BOT_TOKEN")
    
    # Database Settings
    database_url: str = Field(..., env="DATABASE_URL")
    
    # App Settings
    app_name: str = "Bot Factory"
    app_version: str = "1.0.0"
    debug: bool = Field(default=False, env="DEBUG")
    
    # Rate Limiting
    broadcast_rate_limit: int = 20  # messages per second
    max_bots_per_user: int = 5
    
    # Free Plan Limits
    free_plan_subscribers_limit: int = 100
    
    # ✅ UPDATED: Убираем ограничения на воронку
    # max_funnel_messages: int = 7  # УБРАЛИ ОГРАНИЧЕНИЕ
    funnel_check_interval: int = 30  # seconds
    max_funnel_message_length: int = 4096
    max_buttons_per_message: int = 10  # Увеличили до 10 кнопок
    
    # ✅ NEW: Настройки статистики
    stats_retention_days: int = 365  # Храним статистику год
    max_preview_length: int = 100    # Длина превью сообщения
    
    # ✅ NEW: Media settings
    max_media_file_size: int = 50 * 1024 * 1024  # 50MB in bytes
    supported_media_types: list = [
        'photo', 'video', 'document', 'audio', 
        'voice', 'video_note'
    ]
    media_upload_timeout: int = 300  # 5 minutes
    
    # ✅ NEW: AI Platform settings
    ai_platform_timeout: int = 10  # seconds for platform detection
    ai_detection_retries: int = 3   # max retries for each platform
    supported_ai_platforms: list = ['chatforyou', 'protalk']
    
    # ✅ НОВОЕ: Настройки Robokassa
    robokassa_merchant_login: str = Field(..., env="ROBOKASSA_MERCHANT_LOGIN")
    robokassa_password1: str = Field(..., env="ROBOKASSA_PASSWORD1")  # Для создания ссылок
    robokassa_password2: str = Field(..., env="ROBOKASSA_PASSWORD2")  # Для webhook
    robokassa_test_mode: bool = Field(default=True, env="ROBOKASSA_TEST_MODE")
    
    # Webhook настройки
    webhook_base_url: str = Field(..., env="WEBHOOK_BASE_URL")  # https://yourdomain.com
    webhook_secret: str = Field(default="", env="WEBHOOK_SECRET")  # Опциональный секрет
    
    # Тарифные планы
    subscription_plans: dict = {
        "1m": {
            "title": "AI ADMIN - 1 месяц",
            "price": 299.0,
            "duration_days": 30,
            "description": "Безлимитные боты и ИИ агенты на 1 месяц"
        },
        "3m": {
            "title": "AI ADMIN - 3 месяца", 
            "price": 749.0,
            "duration_days": 90,
            "description": "Безлимитные боты и ИИ агенты на 3 месяца (экономия 150₽)"
        },
        "6m": {
            "title": "AI ADMIN - 6 месяцев",
            "price": 1499.0, 
            "duration_days": 180,
            "description": "Безлимитные боты и ИИ агенты на 6 месяцев (экономия 295₽)"
        },
        "12m": {
            "title": "AI ADMIN - 12 месяцев",
            "price": 2490.0,
            "duration_days": 365, 
            "description": "Безлимитные боты и ИИ агенты на 12 месяцев (экономия 1,098₽)"
        }
    }
    
    # Pro лимиты
    pro_max_bots: int = 999
    pro_max_subscribers: int = 999999
    pro_max_funnel_messages: int = 999
    
    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()

# ✅ COMPLETE: Emoji constants for consistent UI
class Emoji:
    # Basic emojis
    ROBOT = "🤖"
    FACTORY = "🏭"
    ROCKET = "🚀"
    CHART = "📊"
    BROADCAST = "📢"
    SETTINGS = "⚙️"
    USERS = "👥"
    PLUS = "➕"
    LIST = "📋"
    HELP = "❓"
    BACK = "◀️"
    SUCCESS = "✅"
    ERROR = "❌"
    WARNING = "⚠️"
    INFO = "ℹ️"
    FIRE = "🔥"
    STAR = "⭐"
    DIAMOND = "💎"
    CROWN = "👑"
    
    # ✅ FIXED: Missing emojis from master_bot.py
    NEW = "🆕"
    RESTART = "🔄"
    REFRESH = "🔄"
    NOTIFICATION = "🔔"
    BELL = "🔔"
    CHECK = "✅"
    CROSS = "❌"
    GEAR = "⚙️"
    TOOLS = "🔧"
    WRENCH = "🔧"
    HAMMER = "🔨"
    
    # ✅ UPDATED: Расширенные эмодзи для воронки
    FUNNEL = "🎯"
    MESSAGE = "📝"
    CLOCK = "⏰"
    MEDIA = "🖼"
    BUTTON = "🔘"
    SEQUENCE = "📬"
    TIMER = "⏱"
    STATISTICS = "📈"
    PLAY = "▶️"
    PAUSE = "⏸"
    STOP = "⏹"
    EDIT = "✏️"
    DELETE = "🗑"
    ADD = "➕"
    PREVIEW = "👁"
    COPY = "📋"
    MOVE_UP = "⬆️"
    MOVE_DOWN = "⬇️"
    
    # ✅ NEW: Эмодзи для медиа
    UPLOAD = "📤"
    DOWNLOAD = "📥" 
    FILE = "📄"
    AUDIO = "🎵"
    VOICE = "🎤"
    VIDEO_NOTE = "📹"
    
    # ✅ NEW: Additional emojis for user_bot.py
    ADMIN = "👨‍💼"
    PANEL = "🎛"
    CONFIG = "📝"
    STATS = "📊"
    CONTROL = "🎮"
    DASHBOARD = "📊"
    MONITOR = "📺"
    ANALYTICS = "📈"
    REPORT = "📋"
    EXPORT = "📤"
    IMPORT = "📥"
    SYNC = "🔄"
    UPDATE = "🔄"
    RELOAD = "🔄"
    POWER = "⚡"
    ONLINE = "🟢"
    OFFLINE = "🔴"
    PENDING = "🟡"
    ACTIVE = "✅"
    INACTIVE = "❌"
    ENABLED = "✅"
    DISABLED = "❌"
    
    # ✅ NEW: Status and action emojis
    LOADING = "⏳"
    PROCESSING = "⚙️"
    COMPLETED = "✅"
    FAILED = "❌"
    CANCELLED = "🚫"
    SCHEDULED = "📅"
    SENT = "📤"
    DELIVERED = "📬"
    READ = "👁‍🗨"
    CLICKED = "👆"
    
    # ✅ NEW: User interaction emojis
    WELCOME = "👋"
    GOODBYE = "👋"
    THANKS = "🙏"
    APPLAUSE = "👏"
    THUMBS_UP = "👍"
    THUMBS_DOWN = "👎"
    HEART = "❤️"
    LIKE = "👍"
    DISLIKE = "👎"
    
    # ✅ NEW: Navigation emojis
    HOME = "🏠"
    MENU = "☰"
    PREVIOUS = "⏮"
    NEXT = "⏭"
    FIRST = "⏪"
    LAST = "⏩"
    UP = "⬆️"
    DOWN = "⬇️"
    LEFT = "⬅️"
    RIGHT = "➡️"
    
    # ✅ NEW: Communication emojis
    MAIL = "📧"
    ENVELOPE = "✉️"
    INBOX = "📥"
    OUTBOX = "📤"
    CHAT = "💬"
    COMMENT = "💭"
    BUBBLE = "💬"
    PHONE = "📞"
    MOBILE = "📱"
    
    # ✅ NEW: Time and calendar emojis
    CALENDAR = "📅"
    DATE = "📅"
    TIME = "🕐"
    DEADLINE = "⏰"
    SCHEDULE = "📅"
    REMINDER = "⏰"
    ALARM = "⏰"
    STOPWATCH = "⏱"
    
    # ✅ NEW: File and document emojis
    FOLDER = "📁"
    DOCUMENT = "📄"
    PDF = "📄"
    IMAGE = "🖼"
    VIDEO = "🎥"
    MUSIC = "🎵"
    ARCHIVE = "🗃"
    ATTACHMENT = "📎"
    
    # ✅ NEW: Network and connection emojis
    LINK = "🔗"
    CHAIN = "⛓"
    UNLINK = "⛓‍💥"
    CONNECT = "🔗"
    DISCONNECT = "⛓‍💥"
    NETWORK = "🌐"
    WIFI = "📶"
    SIGNAL = "📶"
    
    # ✅ NEW: Security and privacy emojis
    LOCK = "🔒"
    UNLOCK = "🔓"
    KEY = "🔑"
    SHIELD = "🛡"
    SECURE = "🔐"
    PRIVATE = "🔒"
    PUBLIC = "🔓"
    HIDDEN = "👁‍🗨"
    VISIBLE = "👁"
    
    # ✅ NEW: Money and business emojis
    MONEY = "💰"
    COIN = "🪙"
    DOLLAR = "💲"
    EURO = "💶"
    PAYMENT = "💳"
    BANK = "🏦"
    INVOICE = "🧾"
    RECEIPT = "🧾"
    PROFIT = "📈"
    LOSS = "📉"
    
    # ✅ NEW: Development and technical emojis
    CODE = "💻"
    TERMINAL = "⌨️"
    DATABASE = "🗄"
    SERVER = "🖥"
    API = "🔌"
    WEBHOOK = "🪝"
    BOT = "🤖"
    AUTOMATION = "🔄"
    SCRIPT = "📜"
    
    # ✅ NEW: Quality and rating emojis
    QUALITY = "💎"
    PREMIUM = "⭐"
    VIP = "👑"
    BASIC = "📋"
    STANDARD = "📊"
    ADVANCED = "🚀"
    PRO = "💎"
    ENTERPRISE = "🏢"
    
    # ✅ NEW: Mood and reaction emojis
    HAPPY = "😊"
    SAD = "😢"
    EXCITED = "🤩"
    WORRIED = "😰"
    CONFUSED = "😕"
    THINKING = "🤔"
    SURPRISED = "😲"
    CALM = "😌"
    
    # ✅ NEW: AI Platform emojis
    DETECT = "🔍"
    PLATFORM = "🌐"
    TOKEN = "🔑"
    INTEGRATION = "🔗"
    AUTOMATIC = "⚡"
    
    # ✅ FIXED: Added missing platform check emojis
    CHATFORYOU_CHECKED = "🔍"
    PROTALK_CHECKED = "🔍"


# Message templates
class Messages:
    WELCOME = f"""
{Emoji.FACTORY} <b>Добро пожаловать в Bot Factory!</b>

Создавайте мощных Telegram-ботов для ваших каналов за считанные секунды!

{Emoji.ROCKET} <b>Что умеет платформа:</b>
• Безлимитные воронки продаж
• Массовые рассылки с аналитикой
• Автоматическое управление участниками
• Подробная статистика и аналитика
• Настраиваемые приветственные сообщения
• ИИ Агенты с поддержкой двух платформ
• Админ-панель прямо в Telegram

{Emoji.FIRE} <b>Создайте своего первого бота прямо сейчас!</b>
"""

    HOW_TO_CREATE_BOT = f"""
{Emoji.INFO} <b>Как создать своего бота:</b>

1️⃣ Перейдите к @BotFather
2️⃣ Отправьте команду /newbot
3️⃣ Придумайте имя и username для бота
4️⃣ Скопируйте полученный токен
5️⃣ Вернитесь сюда и нажмите "Создать бота"

{Emoji.WARNING} <b>Важно:</b> Токен выглядит как:
<code>123456789:ABCdefGHIjklMNOpqrSTUvwxYZ</code>
"""

    NO_BOTS_YET = f"""
{Emoji.ROBOT} <b>У вас пока нет ботов</b>

Создайте своего первого бота и откройте мир автоматизации Telegram-каналов!

{Emoji.STAR} Это займет всего 2 минуты
"""

    # ✅ UPDATED: Обновленные сообщения воронки
    FUNNEL_WELCOME = f"""
{Emoji.FUNNEL} <b>Воронка продаж</b>

Настройте автоматическую последовательность сообщений, которые будут отправляться новым пользователям через заданные интервалы времени.

{Emoji.ROCKET} <b>Возможности:</b>
• Безлимитное количество сообщений
• Персонализированные сообщения с переменными
• Медиа-контент (фото, видео)
• До {settings.max_buttons_per_message} кнопок на сообщение
• Гибкая настройка задержек
• Предпросмотр сообщений
• Подробная статистика по каждому этапу

{Emoji.INFO} <b>Воронка запускается после нажатия пользователем на кнопку приветствия.</b>
"""

    FUNNEL_NO_MESSAGES = f"""
{Emoji.INFO} <b>Воронка пуста</b>

Создайте первое сообщение воронки, чтобы начать автоматизировать общение с новыми пользователями.

{Emoji.CLOCK} <b>Пример последовательности:</b>
• Сообщение 1: через 5 минут - знакомство
• Сообщение 2: через 4 часа - полезный контент
• Сообщение 3: через 1 день - предложение
• Сообщение 4: через 3 дня - напоминание
• И так далее...

{Emoji.ROCKET} <b>Количество сообщений не ограничено!</b>
"""
    
    # ✅ NEW: Новые сообщения для управления
    FUNNEL_MESSAGE_CREATED = f"{Emoji.SUCCESS} <b>Сообщение воронки создано!</b>"
    FUNNEL_MESSAGE_UPDATED = f"{Emoji.SUCCESS} <b>Сообщение обновлено!</b>"
    FUNNEL_MESSAGE_DELETED = f"{Emoji.SUCCESS} <b>Сообщение удалено!</b>"
    
    PREVIEW_HEADER = f"{Emoji.PREVIEW} <b>Предпросмотр сообщения</b>"
    STATS_HEADER = f"{Emoji.STATISTICS} <b>Статистика воронки</b>"
    
    # ✅ NEW: Сообщения для медиа
    MEDIA_UPLOAD_START = f"""
{Emoji.UPLOAD} <b>Загрузка медиа</b>

Отправьте файл, который хотите добавить к сообщению:

{Emoji.MEDIA} <b>Поддерживаемые типы:</b>
- Фото (до 20MB)
- Видео (до 50MB) 
- Документы (до 50MB)
- Аудио (до 50MB)
- Голосовые сообщения
- Видеокружки

{Emoji.WARNING} <b>После отправки файла он сохранится в сообщении воронки.</b>
"""

    MEDIA_UPLOAD_SUCCESS = f"{Emoji.SUCCESS} <b>Медиа файл добавлен к сообщению!</b>"
    MEDIA_UPLOAD_ERROR = f"{Emoji.ERROR} <b>Ошибка загрузки медиа!</b>"
    
    # ✅ NEW: Admin panel messages
    ADMIN_WELCOME = f"""
{Emoji.ADMIN} <b>Панель администратора</b>

Добро пожаловать в админ-панель вашего бота!

{Emoji.SETTINGS} <b>Доступные функции:</b>
• Настройка сообщений
• Управление воронкой продаж
• ИИ Агент с автоопределением платформы
• Просмотр статистики
• Конфигурация кнопок

{Emoji.INFO} Выберите раздел для настройки
"""
    
    ACCESS_DENIED = f"{Emoji.ERROR} <b>Доступ запрещен</b>\n\nТолько владелец бота может использовать эту команду."
    
    OPERATION_CANCELLED = f"{Emoji.INFO} Операция отменена"
    
    SETTINGS_SAVED = f"{Emoji.SUCCESS} <b>Настройки сохранены!</b>"
    
    SOMETHING_WENT_WRONG = f"{Emoji.ERROR} <b>Что-то пошло не так</b>\n\nПопробуйте еще раз или обратитесь в поддержку."

    # ✅ NEW: Сообщения для ИИ агента (ОБНОВЛЕННЫЕ для двух платформ)
    AI_WELCOME = f"""
{Emoji.ROBOT} <b>Добро пожаловать в чат с ИИ агентом!</b>

Задавайте любые вопросы, я постараюсь помочь через современные AI платформы.

{Emoji.FIRE} <b>Поддерживается автоматическое определение наилучшей платформы!</b>

<b>Напишите ваш вопрос:</b>
"""

    # ✅ NEW: Информация о двух поддерживаемых платформах
    AI_DUAL_PLATFORM_INFO = f"""
{Emoji.PLATFORM} <b>Поддержка двух AI платформ</b>

{Emoji.AUTOMATIC} <b>Автоматическое определение:</b>
1. ChatForYou (api.chatforyou.ru)
2. ProTalk (api.pro-talk.ru)

{Emoji.ROCKET} <b>Как работает:</b>
• Введите токен от любой из платформ
• Система автоматически определит подходящую
• Настроит оптимальные параметры подключения  
• Уведомит о результате подключения

{Emoji.FIRE} <b>Преимущества:</b>
• Не нужно знать различия между платформами
• Автоматический выбор лучшего API
• Единый интерфейс для всех платформ
• Резервное подключение при сбоях

{Emoji.INFO} Просто введите токен - система сама найдет нужную платформу!
"""

    # ✅ NEW: Сообщение об успешном определении платформы
    AI_PLATFORM_DETECTED = f"""
{Emoji.SUCCESS} <b>Платформа успешно определена!</b>

{Emoji.PLATFORM} <b>Подключено:</b> {{platform_name}}
{Emoji.TOKEN} <b>API Token:</b> {{token_preview}}
{Emoji.INTEGRATION} <b>Статус:</b> Готов к работе

{Emoji.SETTINGS} <b>Настройки применены автоматически:</b>
• Оптимальные параметры подключения
• Подходящий алгоритм обработки сообщений
• Настройки тайм-аутов и повторных попыток

{Emoji.FIRE} <b>Теперь можете начинать тестирование ИИ агента!</b>
"""

    # ✅ NEW: Сообщение об ошибке определения платформы
    AI_PLATFORM_DETECTION_FAILED = f"""
{Emoji.ERROR} <b>Не удалось определить платформу</b>

Токен не подходит ни для одной из поддерживаемых AI платформ:

{Emoji.CROSS} <b>Проверены:</b>
• ChatForYou (api.chatforyou.ru)
• ProTalk (api.pro-talk.ru)

{Emoji.INFO} <b>Возможные причины:</b>
• Неправильный формат токена
• Токен неактивен или заблокирован
• Отсутствуют права доступа к API
• Временные проблемы с платформой

{Emoji.ROCKET} <b>Рекомендации:</b>
1. Проверьте корректность скопированного токена
2. Убедитесь что аккаунт активен на платформе
3. Проверьте права доступа к API в настройках
4. Попробуйте получить новый токен

{Emoji.HELP} <b>Нужна помощь?</b> Обратитесь в поддержку с указанием используемой платформы.
"""

    # ✅ NEW: Детальная информация о настройке ИИ
    AI_SETUP_INSTRUCTIONS = f"""
{Emoji.GEAR} <b>Настройка ИИ Агента</b>

{Emoji.PLATFORM} <b>Поддерживаемые платформы:</b>
• <b>ChatForYou</b> - api.chatforyou.ru
• <b>ProTalk</b> - api.pro-talk.ru

{Emoji.ROCKET} <b>Пошаговая инструкция:</b>

<b>1️⃣ Получите токен:</b>
• Зайдите на одну из платформ
• Создайте или выберите ИИ бота
• Скопируйте API Token

<b>2️⃣ Настройте в Bot Factory:</b>
• Включите ИИ агента
• Вставьте API Token
• Система автоматически определит платформу

<b>3️⃣ Дополнительные настройки:</b>
• Настройте лимиты сообщений (опционально)
• Укажите канал для проверки подписки
• Протестируйте работу

{Emoji.AUTOMATIC} <b>Автоматические настройки:</b>
✅ Определение платформы
✅ Оптимизация параметров подключения  
✅ Настройка алгоритмов обработки
✅ Конфигурация системы повторных попыток

{Emoji.FIRE} <b>Готово!</b> ИИ агент будет доступен пользователям через кнопку "🤖 Позвать ИИ"
"""

    # ✅ NEW: Сообщения о статусе работы с разными платформами
    AI_CHATFORYOU_STATUS = f"""
{Emoji.SUCCESS} <b>ChatForYou подключен</b>

{Emoji.PLATFORM} Платформа: ChatForYou
{Emoji.LINK} API: api.chatforyou.ru
{Emoji.ROCKET} Режим: Быстрые ответы (одноэтапный API)
"""

    AI_PROTALK_STATUS = f"""
{Emoji.SUCCESS} <b>ProTalk подключен</b>

{Emoji.PLATFORM} Платформа: ProTalk  
{Emoji.LINK} API: api.pro-talk.ru
{Emoji.ROCKET} Режим: Расширенные диалоги (двухэтапный API)
"""

    # ✅ NEW: Специальные сообщения для пользователей
    AI_LIMIT_REACHED = f"""
{Emoji.WARNING} <b>Лимит сообщений исчерпан!</b>

Вы достигли максимального количества сообщений ИИ агенту на сегодня.

{Emoji.CLOCK} <b>Что делать:</b>
• Попробуйте завтра
• Обратитесь к администратору канала
• Возможно, лимит будет увеличен

{Emoji.INFO} Лимиты помогают обеспечить стабильную работу для всех пользователей.
"""

    AI_CHANNEL_SUBSCRIPTION_REQUIRED = f"""
{Emoji.WARNING} <b>Требуется подписка на канал</b>

ИИ агент доступен только подписчикам канала.

{Emoji.ROCKET} <b>Что делать:</b>
1. Подпишитесь на канал
2. Вернитесь и попробуйте снова
3. ИИ агент станет доступен автоматически

{Emoji.INFO} Это помогает поддерживать активное сообщество!
"""

    AI_TEMPORARILY_UNAVAILABLE = f"""
{Emoji.ERROR} <b>ИИ агент временно недоступен</b>

{Emoji.GEAR} <b>Возможные причины:</b>
• Технические работы на AI платформе
• Превышен лимит запросов
• Временные проблемы с подключением
• Обслуживание системы

{Emoji.CLOCK} <b>Что делать:</b>
• Попробуйте через несколько минут
• Обратитесь к администратору
• Проверьте новости в канале

{Emoji.FIRE} Мы работаем над восстановлением сервиса!
"""

    # ✅ NEW: Сообщения для процесса определения платформы
    AI_PLATFORM_DETECTING = f"""
{Emoji.DETECT} <b>Определяем платформу...</b>

{Emoji.LOADING} Проверяем подключение:
1. ChatForYou API → проверка...
2. ProTalk API → ожидание...

{Emoji.INFO} Это займет несколько секунд
"""

    # ✅ FIXED: Используем существующие эмодзи вместо отсутствующих
    AI_PLATFORM_DETECTION_PROGRESS = f"""
{Emoji.PROCESSING} <b>Анализируем API токен...</b>

{Emoji.CHATFORYOU_CHECKED} ChatForYou: {{chatforyou_status}}
{Emoji.PROTALK_CHECKED} ProTalk: {{protalk_status}}

{Emoji.CLOCK} Определение платформы...
"""

    # ✅ NEW: Технические сообщения
    AI_TECHNICAL_ERROR = f"""
{Emoji.ERROR} <b>Техническая ошибка ИИ агента</b>

Произошла ошибка при обращении к AI платформе.

{Emoji.GEAR} <b>Детали переданы в техническую поддержку</b>

{Emoji.CLOCK} Попробуйте через несколько минут или обратитесь к администратору.
"""

    AI_INVALID_RESPONSE = f"""
{Emoji.WARNING} <b>Получен некорректный ответ от ИИ</b>

AI платформа вернула ответ в неожиданном формате.

{Emoji.GEAR} Система автоматически уведомила техподдержку.
{Emoji.CLOCK} Попробуйте переформулировать вопрос.
"""

    # ✅ NEW: Сообщения для администраторов о настройке
    AI_ADMIN_SETUP_COMPLETE = f"""
{Emoji.SUCCESS} <b>ИИ агент полностью настроен!</b>

{Emoji.PLATFORM} Платформа: {{platform_name}}
{Emoji.USERS} Доступен для: Подписчиков канала
{Emoji.CLOCK} Лимит: {{daily_limit}}
{Emoji.BUTTON} Активация: Кнопка "🤖 Позвать ИИ"

{Emoji.FIRE} <b>ИИ агент готов к использованию!</b>

{Emoji.INFO} <b>Пользователи смогут:</b>
• Задавать вопросы в режиме диалога
• Получать персонализированные ответы
• Использовать контекстную информацию

{Emoji.ROCKET} Протестируйте работу через кнопку "🧪 Тестировать ИИ"
"""

    # ✅ NEW: Инструкции для пользователей (будут показаны в боте)
    AI_USER_INSTRUCTIONS = f"""
{Emoji.ROBOT} <b>Как пользоваться ИИ агентом</b>

{Emoji.BUTTON} <b>Для начала:</b>
Нажмите кнопку "🤖 Позвать ИИ" внизу экрана

{Emoji.CHAT} <b>В диалоге:</b>
• Задавайте любые вопросы
• Описывайте проблемы подробно
• ИИ понимает контекст беседы

{Emoji.CLOCK} <b>Завершение:</b>
Нажмите "🚪 Завершить диалог с ИИ" когда закончите

{Emoji.INFO} <b>Особенности:</b>
• ИИ работает через современные AI платформы
• Качественные и быстрые ответы
• Сохраняется контекст диалога
• Доступен только подписчикам канала

{Emoji.FIRE} Начните диалог прямо сейчас!
"""
