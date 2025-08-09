from sqlalchemy import Column, Integer, BigInteger, String, DateTime, Boolean, Text, ForeignKey, UniqueConstraint, Numeric
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime
from typing import Optional, List

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    
    id = Column(BigInteger, primary_key=True)  # Telegram user_id
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    is_active = Column(Boolean, default=True)
    plan = Column(String(50), default="free")  # free, pro
    
    # ✅ Система оплаты
    subscription_expires_at = Column(DateTime, nullable=True)
    subscription_active = Column(Boolean, default=False, nullable=False)
    last_payment_date = Column(DateTime, nullable=True)
    
    # Relationships
    bots = relationship("UserBot", back_populates="owner", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<User(id={self.id}, username={self.username}, plan={self.plan})>"


class UserBot(Base):
    __tablename__ = "user_bots"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(String(100), unique=True, nullable=False)  # Generated unique ID
    
    # ✅ UPDATED: Owner and admin management
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)  # Primary owner
    admin_users = Column(JSONB, nullable=True)  # Additional admins [user_id1, user_id2, ...]
    
    # Bot info
    token = Column(String(255), nullable=False)
    bot_username = Column(String(255), nullable=False)
    bot_name = Column(String(255), nullable=True)
    
    # Status and settings
    status = Column(String(50), default="active")  # active, inactive, error
    is_running = Column(Boolean, default=False)
    
    # ✅ NEW: Admin panel settings
    admin_panel_enabled = Column(Boolean, default=True, nullable=False)  # Enable admin commands in bot
    admin_welcome_message = Column(Text, nullable=True)  # Custom admin welcome message
    
    # Messages
    welcome_message = Column(Text, nullable=True)
    welcome_button_text = Column(String(255), nullable=True)  # Текст Reply кнопки
    confirmation_message = Column(Text, nullable=True)        # Сообщение подтверждения
    goodbye_message = Column(Text, nullable=True)
    goodbye_button_text = Column(String(255), nullable=True)  # Текст Inline кнопки
    goodbye_button_url = Column(String(500), nullable=True)   # Ссылка для Inline кнопки
    
    # ✅ UPDATED: ИИ Ассистент с поддержкой двух платформ и раздельным хранением токенов
    ai_assistant_id = Column(String(255), nullable=True)       # API_TOKEN
    ai_assistant_bot_id = Column(Integer, nullable=True)       # ✅ ИСПРАВЛЕНО: bot_id как число для ChatForYou/ProTalk
    ai_assistant_enabled = Column(Boolean, default=False, nullable=False)
    ai_assistant_settings = Column(JSONB, nullable=True, default=lambda: {
        # Основные настройки
        'daily_limit': None,  # None = безлимит, число = лимит сообщений в день
        'channel_id': None,   # ID канала для проверки подписки
        'context_info': True, # Передавать ли контекст пользователя
        
        # ✅ NEW: Настройки платформы
        'api_service': None,  # Будет определено автоматически: 'chatforyou' или 'protalk'
        'api_version': 'v1.0', # Версия API
        
        # ✅ UPDATED: Отдельное хранение токенов и bot_id
        'api_token': None,          # ✅ НОВОЕ: дублирование API_TOKEN для удобства
        'chatforyou_bot_id': None,  # ✅ ИСПРАВЛЕНО: ID сотрудника ChatForYou как число
        'protalk_bot_id': None,     # ✅ ИСПРАВЛЕНО: для ProTalk если нужно как число
        
        # ✅ NEW: Информация об определенной платформе
        'detected_platform': None,  # 'chatforyou' или 'protalk'
        'platform_detected_at': None,  # ISO дата/время определения платформы
        'platform_detection_attempts': 0,  # Количество попыток определения
        
        # ✅ NEW: Поддерживаемые платформы
        'supported_platforms': ['chatforyou', 'protalk'],  # Список поддерживаемых платформ
        
        # ✅ NEW: Настройки производительности
        'response_timeout': 30,  # Таймаут ответа в секундах
        'max_retries': 3,        # Максимальное количество повторных попыток
        'retry_delay': 1.0,      # Задержка между попытками в секундах
        
        # ✅ NEW: Статистика использования
        'total_requests': 0,     # Общее количество запросов к ИИ
        'successful_requests': 0, # Успешные запросы
        'failed_requests': 0,    # Неудачные запросы
        'last_request_at': None, # Дата/время последнего запроса
        
        # ✅ NEW: Настройки безопасности
        'rate_limit_enabled': True,   # Включить ограничение скорости запросов
        'rate_limit_requests': 60,    # Максимум запросов в минуту
        'block_inappropriate': True,  # Блокировать неподходящий контент
        
        # ✅ NEW: Экспериментальные настройки
        'auto_platform_switch': False,  # Автоматическое переключение при сбоях
        'fallback_enabled': True,       # Включить резервную платформу
        'debug_mode': False,            # Режим отладки
        
        # ✅ NEW: Настройки логирования
        'log_conversations': True,      # Логировать диалоги
        'log_errors': True,            # Логировать ошибки
        'log_performance': False       # Логировать производительность
    })
    
    # Analytics
    total_subscribers = Column(Integer, default=0)
    total_messages_sent = Column(Integer, default=0)
    
    # Timestamps
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    last_activity = Column(DateTime, nullable=True)
    
    # Relationships
    owner = relationship("User", back_populates="bots")
    broadcasts = relationship("Broadcast", back_populates="bot", cascade="all, delete-orphan")
    analytics = relationship("BotAnalytics", back_populates="bot", cascade="all, delete-orphan")
    subscribers = relationship("BotSubscriber", back_populates="bot", cascade="all, delete-orphan")
    
    # ✅ Relationships для рассылок
    broadcast_sequence = relationship("BroadcastSequence", back_populates="bot", uselist=False, cascade="all, delete-orphan")
    scheduled_messages = relationship("ScheduledMessage", back_populates="bot", cascade="all, delete-orphan")
    
    # ✅ NEW: AI Usage relationship
    ai_usage_logs = relationship("AIUsageLog", back_populates="bot", cascade="all, delete-orphan")
    
    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin of this bot"""
        # Owner is always admin
        if user_id == self.user_id:
            return True
        
        # Check additional admins
        if self.admin_users and isinstance(self.admin_users, list):
            return user_id in self.admin_users
        
        return False
    
    def add_admin(self, user_id: int) -> bool:
        """Add admin to bot"""
        if user_id == self.user_id:
            return True  # Owner is already admin
        
        if not self.admin_users:
            self.admin_users = []
        
        if user_id not in self.admin_users:
            self.admin_users.append(user_id)
            return True
        
        return False
    
    def remove_admin(self, user_id: int) -> bool:
        """Remove admin from bot"""
        if user_id == self.user_id:
            return False  # Cannot remove owner
        
        if self.admin_users and user_id in self.admin_users:
            self.admin_users.remove(user_id)
            return True
        
        return False
    
    def get_all_admins(self) -> List[int]:
        """Get list of all admin user IDs"""
        admins = [self.user_id]  # Owner first
        if self.admin_users:
            admins.extend([uid for uid in self.admin_users if uid != self.user_id])
        return admins
    
    # ✅ UPDATED: AI Platform management methods with separate token/bot_id handling
    def get_ai_platform(self) -> Optional[str]:
        """Get detected AI platform"""
        if self.ai_assistant_settings:
            return self.ai_assistant_settings.get('detected_platform')
        return None
    
    def set_ai_platform(self, platform: str) -> None:
        """Set AI platform with timestamp"""
        if not self.ai_assistant_settings:
            self.ai_assistant_settings = {}
        
        self.ai_assistant_settings.update({
            'detected_platform': platform,
            'platform_detected_at': datetime.now().isoformat(),
            'api_service': platform.lower()
        })
    
    def get_ai_api_token(self) -> Optional[str]:
        """Get AI API token from either column or settings"""
        # Приоритет: колонка ai_assistant_id, затем настройки
        if self.ai_assistant_id:
            return self.ai_assistant_id
        
        if self.ai_assistant_settings:
            return self.ai_assistant_settings.get('api_token')
        
        return None
    
    def set_ai_api_token(self, token: str) -> None:
        """Set AI API token in both column and settings"""
        self.ai_assistant_id = token
        
        if not self.ai_assistant_settings:
            self.ai_assistant_settings = {}
        
        self.ai_assistant_settings['api_token'] = token
    
    def get_ai_bot_id(self, platform: str = None) -> Optional[int]:
        """Get AI bot_id for specific platform (returns integer)"""
        # Если платформа не указана, пытаемся определить автоматически
        if not platform:
            platform = self.get_ai_platform()
        
        if not platform:
            return self.ai_assistant_bot_id  # Fallback to column value
        
        # Возвращаем bot_id для конкретной платформы
        if platform.lower() == 'chatforyou':
            if self.ai_assistant_settings:
                bot_id = self.ai_assistant_settings.get('chatforyou_bot_id')
                if bot_id is not None:
                    return int(bot_id) if not isinstance(bot_id, int) else bot_id
            return self.ai_assistant_bot_id
        
        elif platform.lower() == 'protalk':
            if self.ai_assistant_settings:
                bot_id = self.ai_assistant_settings.get('protalk_bot_id')
                if bot_id is not None:
                    return int(bot_id) if not isinstance(bot_id, int) else bot_id
            return self.ai_assistant_bot_id
        
        return self.ai_assistant_bot_id
    
    def set_ai_bot_id(self, bot_id: int, platform: str = None) -> None:
        """Set AI bot_id for specific platform (accepts integer)"""
        # Конвертируем в int если передана строка
        if isinstance(bot_id, str):
            bot_id = int(bot_id)
        
        # Всегда сохраняем в основную колонку
        self.ai_assistant_bot_id = bot_id
        
        if not self.ai_assistant_settings:
            self.ai_assistant_settings = {}
        
        # Если платформа указана, сохраняем в соответствующее поле
        if platform:
            if platform.lower() == 'chatforyou':
                self.ai_assistant_settings['chatforyou_bot_id'] = bot_id
            elif platform.lower() == 'protalk':
                self.ai_assistant_settings['protalk_bot_id'] = bot_id
    
    def get_ai_credentials(self, platform: str = None) -> dict:
        """Get AI credentials (token + bot_id) for platform"""
        return {
            'api_token': self.get_ai_api_token(),
            'bot_id': self.get_ai_bot_id(platform),
            'platform': platform or self.get_ai_platform()
        }
    
    def set_ai_credentials(self, api_token: str, bot_id: int = None, platform: str = None) -> None:
        """Set AI credentials for platform"""
        self.set_ai_api_token(api_token)
        
        if bot_id is not None:
            self.set_ai_bot_id(bot_id, platform)
        
        if platform:
            self.set_ai_platform(platform)
    
    def get_ai_stats(self) -> dict:
        """Get AI usage statistics"""
        if not self.ai_assistant_settings:
            return {}
        
        return {
            'total_requests': self.ai_assistant_settings.get('total_requests', 0),
            'successful_requests': self.ai_assistant_settings.get('successful_requests', 0),
            'failed_requests': self.ai_assistant_settings.get('failed_requests', 0),
            'success_rate': self._calculate_ai_success_rate(),
            'last_request_at': self.ai_assistant_settings.get('last_request_at'),
            'platform': self.ai_assistant_settings.get('detected_platform')
        }
    
    def _calculate_ai_success_rate(self) -> float:
        """Calculate AI request success rate"""
        if not self.ai_assistant_settings:
            return 0.0
        
        total = self.ai_assistant_settings.get('total_requests', 0)
        successful = self.ai_assistant_settings.get('successful_requests', 0)
        
        if total == 0:
            return 0.0
        
        return (successful / total) * 100
    
    def increment_ai_request_stats(self, success: bool = True) -> None:
        """Increment AI request statistics"""
        if not self.ai_assistant_settings:
            self.ai_assistant_settings = {}
        
        self.ai_assistant_settings['total_requests'] = self.ai_assistant_settings.get('total_requests', 0) + 1
        self.ai_assistant_settings['last_request_at'] = datetime.now().isoformat()
        
        if success:
            self.ai_assistant_settings['successful_requests'] = self.ai_assistant_settings.get('successful_requests', 0) + 1
        else:
            self.ai_assistant_settings['failed_requests'] = self.ai_assistant_settings.get('failed_requests', 0) + 1
    
    def is_ai_enabled(self) -> bool:
        """Check if AI assistant is properly configured and enabled"""
        return (
            self.ai_assistant_enabled and 
            self.get_ai_api_token() is not None and 
            self.ai_assistant_settings is not None and
            self.ai_assistant_settings.get('detected_platform') is not None
        )
    
    def get_ai_daily_limit(self) -> Optional[int]:
        """Get AI daily message limit"""
        if self.ai_assistant_settings:
            return self.ai_assistant_settings.get('daily_limit')
        return None
    
    def __repr__(self):
        return f"<UserBot(id={self.id}, username={self.bot_username}, status={self.status})>"


class Broadcast(Base):
    __tablename__ = "broadcasts"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(String(100), ForeignKey("user_bots.bot_id"), nullable=False)
    
    # Message content
    message_text = Column(Text, nullable=False)
    message_type = Column(String(50), default="text")  # text, photo, video, etc.
    media_url = Column(String(500), nullable=True)
    
    # Targeting
    target_all = Column(Boolean, default=True)
    target_count = Column(Integer, default=0)
    
    # Results
    sent_count = Column(Integer, default=0)
    delivered_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    
    # Status
    status = Column(String(50), default="pending")  # pending, sending, completed, failed
    
    # ✅ NEW: Creator tracking
    created_by = Column(BigInteger, nullable=True)  # Admin who created broadcast
    
    # Timestamps
    created_at = Column(DateTime, default=func.now())
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # Relationships
    bot = relationship("UserBot", back_populates="broadcasts")
    
    def __repr__(self):
        return f"<Broadcast(id={self.id}, bot_id={self.bot_id}, status={self.status})>"


class BotAnalytics(Base):
    __tablename__ = "bot_analytics"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(String(100), ForeignKey("user_bots.bot_id"), nullable=False)
    
    # Daily metrics
    date = Column(DateTime, default=func.current_date())
    new_subscribers = Column(Integer, default=0)
    left_subscribers = Column(Integer, default=0)
    messages_sent = Column(Integer, default=0)
    commands_used = Column(Integer, default=0)
    
    # ✅ NEW: Admin activity tracking
    admin_actions = Column(Integer, default=0)  # Admin commands used
    
    # ✅ NEW: AI usage analytics
    ai_requests = Column(Integer, default=0)      # AI requests made
    ai_successful = Column(Integer, default=0)    # Successful AI responses
    ai_failed = Column(Integer, default=0)        # Failed AI requests
    
    # Relationships
    bot = relationship("UserBot", back_populates="analytics")
    
    def __repr__(self):
        return f"<BotAnalytics(bot_id={self.bot_id}, date={self.date})>"


class BotSubscriber(Base):
    __tablename__ = "bot_subscribers"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(String(100), ForeignKey("user_bots.bot_id"), nullable=False)
    user_id = Column(BigInteger, nullable=False)
    
    # User info
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    
    # Status
    is_active = Column(Boolean, default=True)
    is_banned = Column(Boolean, default=False)
    
    # ✅ Поля для рассылок и воронок
    accepts_broadcasts = Column(Boolean, default=True, nullable=False)
    broadcast_started_at = Column(DateTime, nullable=True)
    last_broadcast_message = Column(Integer, default=0, nullable=False)  # номер последнего отправленного сообщения
    funnel_enabled = Column(Boolean, default=True, nullable=False)  # управление воронкой для пользователя
    funnel_started_at = Column(DateTime, nullable=True)  # когда запущена воронка
    last_funnel_message = Column(Integer, default=0, nullable=False)  # последнее сообщение воронки
    
    # ✅ NEW: AI interaction tracking
    ai_enabled = Column(Boolean, default=True, nullable=False)        # Доступ к ИИ агенту
    ai_first_interaction = Column(DateTime, nullable=True)           # Первое обращение к ИИ
    ai_last_interaction = Column(DateTime, nullable=True)            # Последнее обращение к ИИ
    ai_total_messages = Column(Integer, default=0, nullable=False)   # Общее количество сообщений ИИ
    ai_preferred_platform = Column(String(50), nullable=True)       # Предпочитаемая платформа
    
    # Timestamps
    joined_at = Column(DateTime, default=func.now())
    left_at = Column(DateTime, nullable=True)
    last_activity = Column(DateTime, nullable=True)
    
    # Relationships
    bot = relationship("UserBot", back_populates="subscribers")
    
    def __repr__(self):
        return f"<BotSubscriber(bot_id={self.bot_id}, user_id={self.user_id})>"


# ✅ Таблицы для автоматической рассылки

class BroadcastSequence(Base):
    """Настройки рассылки для бота"""
    __tablename__ = "broadcast_sequences"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(String(100), ForeignKey("user_bots.bot_id", ondelete="CASCADE"), nullable=False)
    is_enabled = Column(Boolean, default=True, nullable=False)
    
    # ✅ NEW: Creator tracking
    created_by = Column(BigInteger, nullable=True)  # Admin who created sequence
    last_modified_by = Column(BigInteger, nullable=True)  # Admin who last modified
    
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    bot = relationship("UserBot", back_populates="broadcast_sequence")
    messages = relationship("BroadcastMessage", back_populates="sequence", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<BroadcastSequence(id={self.id}, bot_id={self.bot_id}, enabled={self.is_enabled})>"


class BroadcastMessage(Base):
    """Сообщения в последовательности рассылки"""
    __tablename__ = "broadcast_messages"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    sequence_id = Column(Integer, ForeignKey("broadcast_sequences.id", ondelete="CASCADE"), nullable=False)
    message_number = Column(Integer, nullable=False)
    message_text = Column(Text, nullable=False)
    delay_hours = Column(Numeric(precision=10, scale=6), nullable=False)  # поддержка дробных часов
    media_url = Column(String(500), nullable=True)
    media_type = Column(String(50), nullable=True)  # 'photo', 'video', etc.
    
    # ✅ Дополнительные поля для медиа файлов
    media_file_id = Column(String(255), nullable=True)        # Telegram file_id
    media_file_unique_id = Column(String(255), nullable=True) # Telegram file_unique_id  
    media_file_size = Column(Integer, nullable=True)          # Размер файла в байтах
    media_filename = Column(String(255), nullable=True)       # Оригинальное имя файла
    
    is_active = Column(Boolean, default=True, nullable=False)
    
    # ✅ UTM поля для аналитики
    utm_campaign = Column(String(255), nullable=True)  # Кампания для отслеживания
    utm_content = Column(String(255), nullable=True)   # Контент для отслеживания
    
    # ✅ NEW: Creator tracking
    created_by = Column(BigInteger, nullable=True)  # Admin who created message
    last_modified_by = Column(BigInteger, nullable=True)  # Admin who last modified
    
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    
    # Unique constraint
    __table_args__ = (
        UniqueConstraint('sequence_id', 'message_number', name='uq_sequence_message_number'),
    )
    
    # Relationships
    sequence = relationship("BroadcastSequence", back_populates="messages")
    buttons = relationship("MessageButton", back_populates="message", cascade="all, delete-orphan")
    scheduled_messages = relationship("ScheduledMessage", back_populates="message", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<BroadcastMessage(id={self.id}, sequence_id={self.sequence_id}, number={self.message_number})>"


class MessageButton(Base):
    """Кнопки для сообщений рассылки"""
    __tablename__ = "message_buttons"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(Integer, ForeignKey("broadcast_messages.id", ondelete="CASCADE"), nullable=False)
    button_text = Column(String(255), nullable=False)
    button_url = Column(String(500), nullable=False)
    position = Column(Integer, nullable=False)  # порядок кнопки (1-3)
    
    # ✅ NEW: Creator tracking
    created_by = Column(BigInteger, nullable=True)  # Admin who created button
    
    created_at = Column(DateTime, default=func.now(), nullable=False)
    
    # Unique constraint
    __table_args__ = (
        UniqueConstraint('message_id', 'position', name='uq_message_button_position'),
    )
    
    # Relationships
    message = relationship("BroadcastMessage", back_populates="buttons")
    
    def __repr__(self):
        return f"<MessageButton(id={self.id}, message_id={self.message_id}, text={self.button_text[:20]})>"


class ScheduledMessage(Base):
    """Запланированные отправки сообщений"""
    __tablename__ = "scheduled_messages"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(String(100), ForeignKey("user_bots.bot_id", ondelete="CASCADE"), nullable=False)
    subscriber_id = Column(BigInteger, nullable=False)  # telegram user_id
    message_id = Column(Integer, ForeignKey("broadcast_messages.id", ondelete="CASCADE"), nullable=False)
    scheduled_at = Column(DateTime, nullable=False)
    status = Column(String(50), default='pending', nullable=False)  # 'pending', 'sent', 'failed', 'cancelled'
    sent_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    
    # Relationships
    bot = relationship("UserBot", back_populates="scheduled_messages")
    message = relationship("BroadcastMessage", back_populates="scheduled_messages")
    
    def __repr__(self):
        return f"<ScheduledMessage(id={self.id}, bot_id={self.bot_id}, subscriber_id={self.subscriber_id}, status={self.status})>"


# ✅ NEW: Admin activity logging table
class BotAdminLog(Base):
    """Лог действий администраторов ботов"""
    __tablename__ = "bot_admin_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(String(100), ForeignKey("user_bots.bot_id", ondelete="CASCADE"), nullable=False)
    admin_user_id = Column(BigInteger, nullable=False)  # Telegram ID admin
    
    # Action details
    action_type = Column(String(100), nullable=False)  # 'settings_update', 'funnel_create', etc.
    action_description = Column(Text, nullable=True)   # Human-readable description
    action_data = Column(JSONB, nullable=True)         # JSON data about the action
    
    # Context
    chat_id = Column(BigInteger, nullable=True)        # Chat where action was performed
    message_id = Column(Integer, nullable=True)        # Associated message ID
    
    # Status
    success = Column(Boolean, default=True, nullable=False)
    error_message = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=func.now(), nullable=False)
    
    def __repr__(self):
        return f"<BotAdminLog(id={self.id}, bot_id={self.bot_id}, action={self.action_type})>"


# ✅ UPDATED: AI Usage tracking table with platform support
class AIUsageLog(Base):
    """Лог использования ИИ для отслеживания лимитов с поддержкой платформ"""
    __tablename__ = "ai_usage_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(String(100), ForeignKey("user_bots.bot_id", ondelete="CASCADE"), nullable=False)
    user_id = Column(BigInteger, nullable=False)  # Telegram user ID
    messages_count = Column(Integer, default=0, nullable=False)
    date = Column(DateTime, default=func.current_date(), nullable=False)  # Дата (без времени)
    
    # ✅ NEW: Platform-specific tracking
    platform_used = Column(String(50), nullable=True)    # 'chatforyou' или 'protalk'
    successful_requests = Column(Integer, default=0, nullable=False)  # Успешные запросы
    failed_requests = Column(Integer, default=0, nullable=False)      # Неудачные запросы
    average_response_time = Column(Numeric(precision=10, scale=3), nullable=True)  # Среднее время ответа в секундах
    
    # ✅ NEW: Usage statistics
    total_tokens_used = Column(Integer, default=0, nullable=True)     # Использовано токенов (если доступно)
    longest_conversation = Column(Integer, default=0, nullable=False) # Самый длинный диалог в сообщениях
    
    # ✅ NEW: Error tracking
    error_types = Column(JSONB, nullable=True, default=lambda: {})    # Типы ошибок и их количество
    last_error_at = Column(DateTime, nullable=True)                   # Время последней ошибки
    last_success_at = Column(DateTime, nullable=True)                 # Время последнего успеха
    
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    
    # Unique constraint для одного пользователя в день
    __table_args__ = (
        UniqueConstraint('bot_id', 'user_id', 'date', name='uq_bot_user_date'),
    )
    
    # Relationships
    bot = relationship("UserBot", back_populates="ai_usage_logs")
    
    def update_success_stats(self, platform: str, response_time: float = None) -> None:
        """Update statistics for successful request"""
        self.successful_requests += 1
        self.messages_count += 1
        self.platform_used = platform
        self.last_success_at = datetime.now()
        
        if response_time:
            # Update average response time
            if self.average_response_time:
                total_requests = self.successful_requests + self.failed_requests
                current_total = float(self.average_response_time) * (total_requests - 1)
                self.average_response_time = (current_total + response_time) / total_requests
            else:
                self.average_response_time = response_time
    
    def update_failure_stats(self, platform: str, error_type: str = "unknown") -> None:
        """Update statistics for failed request"""
        self.failed_requests += 1
        self.platform_used = platform
        self.last_error_at = datetime.now()
        
        # Track error types
        if not self.error_types:
            self.error_types = {}
        
        if error_type in self.error_types:
            self.error_types[error_type] += 1
        else:
            self.error_types[error_type] = 1
    
    def get_success_rate(self) -> float:
        """Calculate success rate percentage"""
        total_requests = self.successful_requests + self.failed_requests
        if total_requests == 0:
            return 0.0
        return (self.successful_requests / total_requests) * 100
    
    def get_platform_display_name(self) -> str:
        """Get user-friendly platform name"""
        platform_names = {
            'chatforyou': 'ChatForYou',
            'protalk': 'ProTalk'
        }
        return platform_names.get(self.platform_used, self.platform_used or 'Unknown')
    
    def __repr__(self):
        return f"<AIUsageLog(id={self.id}, bot_id={self.bot_id}, user_id={self.user_id}, date={self.date}, count={self.messages_count}, platform={self.platform_used})>"


# ✅ NEW: AI Platform Status tracking table
class AIPlatformStatus(Base):
    """Статус доступности AI платформ"""
    __tablename__ = "ai_platform_status"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    platform_name = Column(String(50), nullable=False, unique=True)  # 'chatforyou' или 'protalk'
    
    # Status tracking
    is_available = Column(Boolean, default=True, nullable=False)
    last_check_at = Column(DateTime, default=func.now(), nullable=False)
    last_success_at = Column(DateTime, nullable=True)
    last_failure_at = Column(DateTime, nullable=True)
    
    # Performance metrics
    average_response_time = Column(Numeric(precision=10, scale=3), nullable=True)
    success_rate_24h = Column(Numeric(precision=5, scale=2), nullable=True)  # Percentage
    total_requests_24h = Column(Integer, default=0, nullable=False)
    failed_requests_24h = Column(Integer, default=0, nullable=False)
    
    # Error information
    last_error_message = Column(Text, nullable=True)
    consecutive_failures = Column(Integer, default=0, nullable=False)
    
    # Additional info
    api_version = Column(String(20), nullable=True)
    maintenance_mode = Column(Boolean, default=False, nullable=False)
    notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    
    def mark_success(self, response_time: float = None) -> None:
        """Mark platform as working correctly"""
        self.is_available = True
        self.last_success_at = datetime.now()
        self.consecutive_failures = 0
        
        if response_time:
            if self.average_response_time:
                # Simple moving average
                self.average_response_time = (float(self.average_response_time) + response_time) / 2
            else:
                self.average_response_time = response_time
    
    def mark_failure(self, error_message: str = None) -> None:
        """Mark platform as having issues"""
        self.is_available = False
        self.last_failure_at = datetime.now()
        self.consecutive_failures += 1
        self.failed_requests_24h += 1
        
        if error_message:
            self.last_error_message = error_message[:1000]  # Limit error message length
    
    def __repr__(self):
        return f"<AIPlatformStatus(platform={self.platform_name}, available={self.is_available}, last_check={self.last_check_at})>"
