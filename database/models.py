from sqlalchemy import Column, Integer, BigInteger, String, DateTime, Boolean, Text, ForeignKey, UniqueConstraint, Numeric, Date
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime, timedelta
from typing import Optional, List
import string
import secrets

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
    plan = Column(String(50), default="free")  # free, pro, trial
    tokens_limit_total = Column(BigInteger, default=500000, nullable=True)
    tokens_used_total = Column(BigInteger, default=0, nullable=False)
    tokens_admin_chat_id = Column(BigInteger, nullable=True)
    tokens_initialized_at = Column(DateTime, nullable=True)
    
    # ✅ Система оплаты
    subscription_expires_at = Column(DateTime, nullable=True)
    subscription_active = Column(Boolean, default=False, nullable=False)
    last_payment_date = Column(DateTime, nullable=True)
    
    # ✅ НОВЫЕ ПОЛЯ: Пробный период
    trial_started_at = Column(DateTime, nullable=True)
    trial_expires_at = Column(DateTime, nullable=True)
    is_trial_user = Column(Boolean, default=False, nullable=False)
    trial_converted = Column(Boolean, default=False, nullable=False)  # Купил ли после триала
    
    # ✅ НОВЫЕ ПОЛЯ: Реферальная программа
    referral_code = Column(String(20), unique=True, nullable=True)  # REF_ABC123
    referred_by = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    referral_earnings = Column(Numeric(precision=10, scale=2), default=0.0, nullable=False)
    total_referrals = Column(Integer, default=0, nullable=False)
    
    # Relationships
    bots = relationship("UserBot", back_populates="owner", cascade="all, delete-orphan")
    referrer = relationship("User", remote_side=[id], backref="referrals")
    sent_referral_transactions = relationship("ReferralTransaction", foreign_keys="[ReferralTransaction.referrer_id]", back_populates="referrer")
    received_referral_transactions = relationship("ReferralTransaction", foreign_keys="[ReferralTransaction.referred_id]", back_populates="referred_user")
    
    def get_subscription_status(self) -> dict:
        """Получить полный статус подписки включая триал"""
        now = datetime.now()
        
        # Проверяем активную платную подписку
        has_paid_subscription = (
            self.subscription_active and 
            self.subscription_expires_at and 
            self.subscription_expires_at > now
        )
        
        # Проверяем активный триал
        has_active_trial = (
            self.is_trial_user and 
            self.trial_expires_at and 
            self.trial_expires_at > now and
            not self.trial_converted
        )
        
        # Определяем статус
        if has_paid_subscription:
            status = "paid"
            expires_at = self.subscription_expires_at
            days_left = (expires_at - now).days + 1
        elif has_active_trial:
            status = "trial"
            expires_at = self.trial_expires_at
            days_left = (expires_at - now).days + 1
        else:
            status = "expired"
            expires_at = self.trial_expires_at or self.subscription_expires_at
            days_left = 0
        
        return {
            'status': status,  # 'paid', 'trial', 'expired'
            'has_access': has_paid_subscription or has_active_trial,
            'expires_at': expires_at,
            'days_left': days_left,
            'is_trial': has_active_trial,
            'trial_expired': self.is_trial_user and not has_active_trial,
            'plan': self.plan or 'free'
        }

    def start_trial(self) -> bool:
        """Запустить триал для пользователя"""
        if self.is_trial_user or self.trial_converted:
            return False  # Уже был триал
        
        # Импорт settings здесь чтобы избежать циклических импортов
        try:
            from config import settings
            trial_days = getattr(settings, 'trial_days', 3)  # По умолчанию 3 дня
        except ImportError:
            trial_days = 3  # Fallback значение
        
        now = datetime.now()
        
        self.is_trial_user = True
        self.trial_started_at = now
        self.trial_expires_at = now + timedelta(days=trial_days)
        self.plan = 'trial'
        
        return True
    
    # ✅ НОВЫЕ МЕТОДЫ: Реферальная система
    
    def generate_referral_code(self) -> str:
        """Генерировать уникальный реферальный код"""
        if self.referral_code:
            return self.referral_code
        
        # Генерируем код вида REF_ABC123 (7 символов после REF_)
        alphabet = string.ascii_uppercase + string.digits
        while True:
            code = "REF_" + ''.join(secrets.choice(alphabet) for _ in range(6))
            # В реальном приложении нужно проверить уникальность в БД
            self.referral_code = code
            return code
    
    def get_referral_code(self) -> Optional[str]:
        """Получить реферальный код пользователя"""
        if not self.referral_code:
            return self.generate_referral_code()
        return self.referral_code
    
    def set_referrer(self, referrer_id: int) -> bool:
        """Установить кто пригласил пользователя"""
        if self.referred_by or referrer_id == self.id:
            return False  # Уже есть реферер или это самореферал
        
        self.referred_by = referrer_id
        return True
    
    def get_referrer(self) -> Optional['User']:
        """Получить объект пользователя который пригласил"""
        return self.referrer
    
    def get_referrals_count(self) -> int:
        """Получить количество приглашенных пользователей"""
        return self.total_referrals or 0
    
    def increment_referrals_count(self) -> None:
        """Увеличить счетчик приглашенных пользователей"""
        self.total_referrals = (self.total_referrals or 0) + 1
    
    def get_referral_earnings(self) -> float:
        """Получить общую сумму заработанных комиссий"""
        return float(self.referral_earnings or 0.0)
    
    def add_referral_earnings(self, amount: float) -> bool:
        """Добавить заработок от реферальной комиссии"""
        if amount <= 0:
            return False
        
        self.referral_earnings = (self.referral_earnings or 0.0) + amount
        return True
    
    def get_referral_stats(self) -> dict:
        """Получить статистику реферальной программы"""
        return {
            'referral_code': self.get_referral_code(),
            'referred_by': self.referred_by,
            'total_referrals': self.get_referrals_count(),
            'total_earnings': self.get_referral_earnings(),
            'has_referrer': bool(self.referred_by),
            'is_active_referrer': self.get_referrals_count() > 0
        }
    
    def is_eligible_for_referral_bonus(self) -> bool:
        """Проверить может ли пользователь получать реферальные бонусы"""
        # Можно добавить дополнительные условия
        return self.is_active and self.referral_code is not None
    
    def __repr__(self):
        return f"<User(id={self.id}, username={self.username}, plan={self.plan})>"


class UserBot(Base):
    __tablename__ = "user_bots"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(String(100), unique=True, nullable=False)  # Generated unique ID
    
    # ✅ Owner and admin management
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)  # Primary owner
    admin_users = Column(JSONB, nullable=True)  # Additional admins [user_id1, user_id2, ...]
    
    # Bot info
    token = Column(String(255), nullable=False)
    bot_username = Column(String(255), nullable=False)
    bot_name = Column(String(255), nullable=True)
    
    # Status and settings
    status = Column(String(50), default="active")  # active, inactive, error
    is_running = Column(Boolean, default=False)
    
    # ✅ НОВОЕ: Subscription check settings
    subscription_check_enabled = Column(Boolean, default=False, nullable=False)
    subscription_channel_id = Column(BigInteger, nullable=True)  # ID канала для проверки подписки
    subscription_channel_username = Column(String(255), nullable=True)  # Username канала (@channel)
    subscription_deny_message = Column(Text, nullable=True, default="Для доступа к ИИ агенту необходимо подписаться на наш канал.")
    
    # ✅ Admin panel settings
    admin_panel_enabled = Column(Boolean, default=True, nullable=False)  # Enable admin commands in bot
    admin_welcome_message = Column(Text, nullable=True)  # Custom admin welcome message
    
    # Messages
    welcome_message = Column(Text, nullable=True)
    welcome_button_text = Column(String(255), nullable=True)  # Текст Reply кнопки
    confirmation_message = Column(Text, nullable=True)        # Сообщение подтверждения
    goodbye_message = Column(Text, nullable=True)
    goodbye_button_text = Column(String(255), nullable=True)  # Текст Inline кнопки
    goodbye_button_url = Column(String(500), nullable=True)   # Ссылка для Inline кнопки
    
    # ✅ ОБНОВЛЕНО: ИИ Ассистент с поддержкой Responses API
    # === ОБЩИЕ ПОЛЯ ===
    ai_assistant_enabled = Column(Boolean, default=False, nullable=False)
    ai_assistant_type = Column(String(50), nullable=True)  # 'openai', 'chatforyou', 'protalk'
    
    # ✅ === OPENAI RESPONSES API ПОЛЯ ===
    openai_agent_id = Column(String(255), nullable=True)           # Локальный ID агента  
    openai_agent_name = Column(String(255), nullable=True)         # Имя агента
    openai_agent_instructions = Column(Text, nullable=True)        # Инструкции агента
    openai_model = Column(String(100), default="gpt-4o")          # Модель OpenAI
    openai_admin_chat_id = Column(BigInteger, nullable=True)       # Chat ID админа для уведомлений
    openai_token_notification_sent = Column(Boolean, default=False, nullable=False)
    openai_last_usage_at = Column(DateTime, nullable=True)
    
    # ✅ ОБНОВЛЕНО: Новая структура для Responses API
    openai_use_responses_api = Column(Boolean, default=True, nullable=False)           # Всегда True для новых агентов
    openai_store_conversations = Column(Boolean, default=True, nullable=False)        # Хранить контекст на сервере
    openai_conversation_retention_days = Column(Integer, default=30, nullable=False)  # Дни хранения контекста (1-90)
    openai_conversation_contexts = Column(JSONB, nullable=True, default=lambda: {})    # ✅ ПЕРЕИМЕНОВАНО: {user_id: response_id}
    
    # ✅ ОБНОВЛЕНО: Настройки с полной поддержкой Responses API
    openai_settings = Column(JSONB, nullable=True, default=lambda: {
        # ✅ RESPONSES API CORE SETTINGS
        'api_type': 'responses',              # Всегда responses для новых агентов
        'store_conversations': True,          # Хранить контекст на сервере OpenAI
        'conversation_retention': 30,         # Дни хранения (1-90)
        'enable_streaming': True,             # Потоковые ответы
        
        # ✅ ВСТРОЕННЫЕ ИНСТРУМЕНТЫ RESPONSES API
        'enable_web_search': False,           # Встроенный веб-поиск OpenAI
        'enable_code_interpreter': False,     # Интерпретатор кода
        'enable_file_search': False,          # Поиск по файлам
        'enable_image_generation': False,     # Генерация изображений (пока не доступно)
        
        # Основные параметры модели
        'temperature': 0.7,
        'max_tokens': 4000,
        'top_p': 1.0,
        'frequency_penalty': 0.0,
        'presence_penalty': 0.0,
        
        # Ограничения и безопасность
        'daily_limit': None,
        'context_info': True,                 # Передавать контекст пользователя
        'moderation_enabled': True,
        
        # Производительность
        'response_timeout': 60,
        'async_processing': True,
        
        # Статистика
        'total_requests': 0,
        'successful_requests': 0,
        'failed_requests': 0,
        'last_request_at': None,
        
        # Логирование
        'log_conversations': True,
        'log_errors': True,
        'log_performance': False,
        
        # ✅ НОВЫЕ ПОЛЯ ДЛЯ RESPONSES API
        'vector_store_ids': [],               # ID векторных хранилищ для file_search
        'computer_use_enabled': False,        # Computer use (пока экспериментально)
        'reasoning_effort': 'medium'          # Для o-series моделей
    })
    
    # === ВНЕШНИЕ ПЛАТФОРМЫ (CHATFORYOU/PROTALK) ===
    external_api_token = Column(String(255), nullable=True)       # API токен внешней платформы
    external_bot_id = Column(String(100), nullable=True)          # bot_id для внешней платформы
    external_platform = Column(String(50), nullable=True)         # 'chatforyou' или 'protalk'
    external_settings = Column(JSONB, nullable=True, default=lambda: {
        # Основные настройки внешних платформ
        'daily_limit': None,          # Лимит запросов в день
        'channel_id': None,           # ID канала для проверки подписки
        'context_info': True,         # Передавать контекст пользователя
        
        # Настройки API
        'api_version': 'v1.0',        # Версия API
        'auto_detect_platform': True, # Автоопределение платформы
        
        # Настройки производительности
        'response_timeout': 30,       # Таймаут ответа в секундах
        'max_retries': 3,            # Максимальные повторные попытки
        'retry_delay': 1.0,          # Задержка между попытками
        
        # Статистика использования
        'total_requests': 0,
        'successful_requests': 0,
        'failed_requests': 0,
        'last_request_at': None,
        
        # Информация о платформе
        'detected_platform': None,
        'platform_detected_at': None,
        'platform_detection_attempts': 0,
        'supported_platforms': ['chatforyou', 'protalk'],
        
        # Настройки безопасности
        'rate_limit_enabled': True,
        'rate_limit_requests': 60,
        'block_inappropriate': True,
        
        # Экспериментальные функции
        'auto_platform_switch': False,
        'fallback_enabled': True,
        'debug_mode': False,
        
        # Настройки логирования
        'log_conversations': True,
        'log_errors': True,
        'log_performance': False
    })
    
    # ✅ Token tracking fields
    tokens_used_total = Column(BigInteger, default=0, nullable=False)      # Общее количество использованных токенов
    tokens_used_input = Column(BigInteger, default=0, nullable=False)      # Входящие токены
    tokens_used_output = Column(BigInteger, default=0, nullable=False)     # Исходящие токены
    tokens_used_today = Column(BigInteger, default=0, nullable=False)      # Токены использованные сегодня
    tokens_used_this_month = Column(BigInteger, default=0, nullable=False) # Токены использованные в этом месяце
    
    # Token limits
    tokens_limit_daily = Column(BigInteger, nullable=True)                 # Дневной лимит токенов
    tokens_limit_monthly = Column(BigInteger, nullable=True)               # Месячный лимит токенов
    tokens_limit_total = Column(BigInteger, nullable=True)                 # Общий лимит токенов
    
    # Token reset tracking
    tokens_reset_daily_at = Column(DateTime, nullable=True)                # Когда сбрасывать дневной счетчик
    tokens_reset_monthly_at = Column(DateTime, nullable=True)              # Когда сбрасывать месячный счетчик
    
    # Token statistics
    tokens_avg_per_request = Column(Numeric(precision=10, scale=2), nullable=True)  # Среднее количество токенов на запрос
    tokens_peak_daily_usage = Column(BigInteger, default=0, nullable=False)         # Пиковое дневное использование
    tokens_last_reset_daily = Column(DateTime, nullable=True)                       # Последний сброс дневного счетчика
    tokens_last_reset_monthly = Column(DateTime, nullable=True)                     # Последний сброс месячного счетчика
    
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
    content_agents = relationship("ContentAgent", back_populates="bot", cascade="all, delete-orphan")
    admin_channels = relationship("BotAdminChannel", back_populates="bot", cascade="all, delete-orphan")
    
    # ✅ Relationships для рассылок
    broadcast_sequence = relationship("BroadcastSequence", back_populates="bot", uselist=False, cascade="all, delete-orphan")
    scheduled_messages = relationship("ScheduledMessage", back_populates="bot", cascade="all, delete-orphan")
    
    # ✅ НОВОЕ: Relationship для массовых рассылок
    mass_broadcasts = relationship("MassBroadcast", back_populates="bot", cascade="all, delete-orphan")
    
    # ✅ AI Usage relationship
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

    # ✅ НОВЫЕ МЕТОДЫ: Subscription management
    
    def is_subscription_check_enabled(self) -> bool:
        """Check if subscription verification is enabled"""
        return self.subscription_check_enabled or False
    
    def get_subscription_channel_info(self) -> Optional[dict]:
        """Get subscription channel information"""
        if not self.subscription_check_enabled:
            return None
        
        return {
            'channel_id': self.subscription_channel_id,
            'channel_username': self.subscription_channel_username,
            'enabled': self.subscription_check_enabled
        }
    
    def set_subscription_settings(self, enabled: bool = False, channel_id: int = None, 
                                 channel_username: str = None, deny_message: str = None) -> bool:
        """Configure subscription verification settings"""
        self.subscription_check_enabled = enabled
        self.subscription_channel_id = channel_id
        self.subscription_channel_username = channel_username
        
        if deny_message:
            self.subscription_deny_message = deny_message
        elif not self.subscription_deny_message:
            self.subscription_deny_message = "Для доступа к ИИ агенту необходимо подписаться на наш канал."
        
        return True
    
    def clear_subscription_settings(self) -> bool:
        """Clear all subscription verification settings"""
        self.subscription_check_enabled = False
        self.subscription_channel_id = None
        self.subscription_channel_username = None
        self.subscription_deny_message = None
        return True
    
    def get_subscription_deny_message(self) -> str:
        """Get subscription denial message"""
        return self.subscription_deny_message or "Для доступа к ИИ агенту необходимо подписаться на наш канал."
    
    def validate_subscription_config(self) -> dict:
        """Validate subscription configuration"""
        validation = {
            'valid': True,
            'issues': [],
            'warnings': []
        }
        
        if self.subscription_check_enabled:
            if not self.subscription_channel_id and not self.subscription_channel_username:
                validation['valid'] = False
                validation['issues'].append("Channel ID or username required when subscription check is enabled")
            
            if self.subscription_channel_id and self.subscription_channel_username:
                validation['warnings'].append("Both channel ID and username specified - ID will be used")
            
            if not self.subscription_deny_message:
                validation['warnings'].append("No custom deny message specified - using default")
        
        return validation
    
    # ✅ ОБНОВЛЕНО: Управление AI ассистентом
    
    def get_ai_type(self) -> Optional[str]:
        """Get AI assistant type"""
        return self.ai_assistant_type
    
    def set_ai_type(self, ai_type: str) -> bool:
        """Set AI assistant type"""
        if ai_type in ['openai', 'chatforyou', 'protalk']:
            self.ai_assistant_type = ai_type
            return True
        return False
    
    def is_ai_enabled(self) -> bool:
        """Check if AI assistant is enabled and configured"""
        if not self.ai_assistant_enabled or not self.ai_assistant_type:
            return False
        
        if self.ai_assistant_type == 'openai':
            return self.openai_agent_id is not None
        elif self.ai_assistant_type in ['chatforyou', 'protalk']:
            return (self.external_api_token is not None and 
                   self.external_bot_id is not None and
                   self.external_platform is not None)
        
        return False
    
    # ✅ === ОБНОВЛЕНО: OPENAI RESPONSES API МЕТОДЫ ===
    
    def is_using_responses_api(self) -> bool:
        """Всегда True для OpenAI агентов в новой архитектуре"""
        return self.ai_assistant_type == 'openai' and self.openai_use_responses_api
    
    def get_conversation_response_id(self, user_id: int) -> Optional[str]:
        """✅ ОБНОВЛЕНО: Получить response_id активного разговора с пользователем"""
        if not self.openai_conversation_contexts:
            return None
        return self.openai_conversation_contexts.get(str(user_id))
    
    def set_conversation_response_id(self, user_id: int, response_id: str) -> bool:
        """✅ ОБНОВЛЕНО: Сохранить response_id для продолжения разговора"""
        if not self.openai_conversation_contexts:
            self.openai_conversation_contexts = {}
        
        self.openai_conversation_contexts[str(user_id)] = response_id
        return True
    
    def clear_conversation_response_id(self, user_id: int) -> bool:
        """✅ ОБНОВЛЕНО: Очистить активный разговор с пользователем"""
        if not self.openai_conversation_contexts:
            return False
        
        user_key = str(user_id)
        if user_key in self.openai_conversation_contexts:
            del self.openai_conversation_contexts[user_key]
            return True
        return False
    
    def clear_all_conversations(self) -> bool:
        """✅ ОБНОВЛЕНО: Очистить все активные разговоры"""
        self.openai_conversation_contexts = {}
        return True
    
    def get_active_conversations_count(self) -> int:
        """✅ ОБНОВЛЕНО: Получить количество активных разговоров"""
        if not self.openai_conversation_contexts:
            return 0
        return len(self.openai_conversation_contexts)
    
    def get_responses_api_config(self) -> dict:
        """✅ ОБНОВЛЕНО: Получить конфигурацию для Responses API"""
        settings = self.openai_settings or {}
        
        config = {
            'model': self.openai_model or 'gpt-4o',
            'store': settings.get('store_conversations', True),
            'stream': settings.get('enable_streaming', True),
            'temperature': settings.get('temperature', 0.7),
            'max_tokens': settings.get('max_tokens', 4000),
            'top_p': settings.get('top_p', 1.0),
            'frequency_penalty': settings.get('frequency_penalty', 0.0),
            'presence_penalty': settings.get('presence_penalty', 0.0),
        }
        
        # ✅ ОБНОВЛЕНО: Добавляем встроенные инструменты Responses API
        tools = []
        if settings.get('enable_web_search'):
            tools.append({"type": "web_search_preview"})
        if settings.get('enable_code_interpreter'):
            tools.append({
                "type": "code_interpreter",
                "container": {"type": "auto"}
            })
        if settings.get('enable_file_search'):
            vector_store_ids = settings.get('vector_store_ids', [])
            if vector_store_ids:
                tools.append({
                    "type": "file_search",
                    "vector_store_ids": vector_store_ids
                })
        if settings.get('enable_image_generation'):
            tools.append({"type": "image_generation"})
        
        if tools:
            config['tools'] = tools
        
        return config
    
    def get_system_prompt(self) -> str:
        """Получить системный промпт для агента"""
        if self.openai_agent_instructions:
            return self.openai_agent_instructions
        
        name = self.openai_agent_name or "AI Ассистент"
        return f"Ты - {name}. Отвечай полезно и дружелюбно."
    
    def enable_responses_tool(self, tool_name: str, enabled: bool = True) -> bool:
        """✅ НОВОЕ: Включить/выключить встроенный инструмент Responses API"""
        valid_tools = ['web_search', 'code_interpreter', 'file_search', 'image_generation']
        
        if tool_name not in valid_tools:
            return False
        
        if not self.openai_settings:
            self.openai_settings = {}
        
        self.openai_settings[f'enable_{tool_name}'] = enabled
        return True
    
    def get_enabled_tools(self) -> List[str]:
        """✅ ОБНОВЛЕНО: Получить список включенных инструментов"""
        if not self.openai_settings:
            return []
        
        enabled_tools = []
        tools_map = {
            'enable_web_search': 'web_search_preview',
            'enable_code_interpreter': 'code_interpreter', 
            'enable_file_search': 'file_search',
            'enable_image_generation': 'image_generation'
        }
        
        for setting_key, tool_name in tools_map.items():
            if self.openai_settings.get(setting_key):
                enabled_tools.append(tool_name)
        
        return enabled_tools
    
    def update_conversation_settings(self, store: bool = True, retention_days: int = 30) -> bool:
        """✅ НОВОЕ: Обновить настройки хранения разговоров"""
        if retention_days < 1 or retention_days > 90:
            return False
        
        self.openai_store_conversations = store
        self.openai_conversation_retention_days = retention_days
        
        if not self.openai_settings:
            self.openai_settings = {}
        
        self.openai_settings.update({
            'store_conversations': store,
            'conversation_retention': retention_days
        })
        
        return True
    
    def setup_openai_assistant(self, agent_id: str, agent_name: str = None, 
                              instructions: str = None, model: str = "gpt-4o") -> bool:
        """✅ ОБНОВЛЕНО: Setup OpenAI Responses API assistant"""
        self.ai_assistant_type = 'openai'
        self.openai_agent_id = agent_id
        self.openai_agent_name = agent_name
        self.openai_agent_instructions = instructions
        self.openai_model = model
        self.openai_use_responses_api = True
        
        if not self.openai_settings:
            self.openai_settings = {}
        
        # ✅ Устанавливаем настройки по умолчанию для Responses API
        self.openai_settings.update({
            'api_type': 'responses',
            'store_conversations': True,
            'conversation_retention': 30,
            'enable_streaming': True,
            'enable_web_search': False,
            'enable_code_interpreter': False,
            'enable_file_search': False,
            'enable_image_generation': False,
            'vector_store_ids': [],
            'computer_use_enabled': False,
            'reasoning_effort': 'medium'
        })
        
        return True
    
    def get_openai_agent_id(self) -> Optional[str]:
        """Get OpenAI agent ID"""
        return self.openai_agent_id if self.ai_assistant_type == 'openai' else None
    
    def get_openai_settings(self) -> dict:
        """Get OpenAI specific settings"""
        if self.ai_assistant_type == 'openai' and self.openai_settings:
            return self.openai_settings
        return {}
    
    def update_openai_settings(self, settings: dict) -> bool:
        """✅ ОБНОВЛЕНО: Update OpenAI settings (Responses API)"""
        if self.ai_assistant_type != 'openai':
            return False
        
        if not self.openai_settings:
            self.openai_settings = {
                'api_type': 'responses',
                'store_conversations': True,
                'conversation_retention': 30,
                'enable_streaming': True,
                'enable_web_search': False,
                'enable_code_interpreter': False,
                'enable_file_search': False,
                'enable_image_generation': False,
                'vector_store_ids': [],
                'computer_use_enabled': False,
                'reasoning_effort': 'medium'
            }
        
        self.openai_settings.update(settings)
        return True
    
    def get_openai_model(self) -> str:
        """Get OpenAI model"""
        return self.openai_model or "gpt-4o"
    
    def set_openai_model(self, model: str) -> bool:
        """Set OpenAI model"""
        if self.ai_assistant_type == 'openai':
            self.openai_model = model
            return True
        return False
    
    # ✅ НОВЫЕ МЕТОДЫ: Специфичные для Responses API
    
    def set_vector_store_ids(self, vector_store_ids: List[str]) -> bool:
        """✅ НОВОЕ: Установить ID векторных хранилищ для file_search"""
        if not self.openai_settings:
            self.openai_settings = {}
        
        self.openai_settings['vector_store_ids'] = vector_store_ids
        
        # Автоматически включаем file_search если есть векторные хранилища
        if vector_store_ids:
            self.openai_settings['enable_file_search'] = True
        
        return True
    
    def get_vector_store_ids(self) -> List[str]:
        """✅ НОВОЕ: Получить список ID векторных хранилищ"""
        if not self.openai_settings:
            return []
        return self.openai_settings.get('vector_store_ids', [])
    
    def set_reasoning_effort(self, effort: str) -> bool:
        """✅ НОВОЕ: Установить уровень рассуждений для o-series моделей"""
        if effort not in ['low', 'medium', 'high']:
            return False
        
        if not self.openai_settings:
            self.openai_settings = {}
        
        self.openai_settings['reasoning_effort'] = effort
        return True
    
    def get_reasoning_effort(self) -> str:
        """✅ НОВОЕ: Получить уровень рассуждений"""
        if not self.openai_settings:
            return 'medium'
        return self.openai_settings.get('reasoning_effort', 'medium')
    
    def enable_computer_use(self, enabled: bool = True) -> bool:
        """✅ НОВОЕ: Включить/выключить Computer Use (экспериментально)"""
        if not self.openai_settings:
            self.openai_settings = {}
        
        self.openai_settings['computer_use_enabled'] = enabled
        return True
    
    def is_computer_use_enabled(self) -> bool:
        """✅ НОВОЕ: Проверить включен ли Computer Use"""
        if not self.openai_settings:
            return False
        return self.openai_settings.get('computer_use_enabled', False)
    
    # ===== УСТАРЕВШИЕ МЕТОДЫ ДЛЯ СОВМЕСТИМОСТИ =====
    # (сохраняем для backward compatibility)
    
    def get_conversation_id(self, user_id: int) -> Optional[str]:
        """⚠️ УСТАРЕЛО: Используйте get_conversation_response_id"""
        return self.get_conversation_response_id(user_id)
    
    def set_conversation_id(self, user_id: int, response_id: str) -> bool:
        """⚠️ УСТАРЕЛО: Используйте set_conversation_response_id"""
        return self.set_conversation_response_id(user_id, response_id)
    
    def clear_conversation(self, user_id: int) -> bool:
        """⚠️ УСТАРЕЛО: Используйте clear_conversation_response_id"""
        return self.clear_conversation_response_id(user_id)
    
    # === ВНЕШНИЕ ПЛАТФОРМЫ МЕТОДЫ ===
    
    def setup_external_assistant(self, api_token: str, bot_id: str, platform: str) -> bool:
        """Setup external AI platform (ChatForYou/ProTalk)"""
        if platform not in ['chatforyou', 'protalk']:
            return False
        
        self.ai_assistant_type = platform
        self.external_api_token = api_token
        self.external_bot_id = bot_id
        self.external_platform = platform
        
        if not self.external_settings:
            self.external_settings = {}
        
        self.external_settings.update({
            'detected_platform': platform,
            'platform_detected_at': datetime.now().isoformat()
        })
        
        return True
    
    def get_external_api_token(self) -> Optional[str]:
        """Get external platform API token"""
        return self.external_api_token if self.ai_assistant_type in ['chatforyou', 'protalk'] else None
    
    def get_external_bot_id(self) -> Optional[str]:
        """Get external platform bot ID"""
        return self.external_bot_id if self.ai_assistant_type in ['chatforyou', 'protalk'] else None
    
    def get_external_platform(self) -> Optional[str]:
        """Get external platform name"""
        return self.external_platform if self.ai_assistant_type in ['chatforyou', 'protalk'] else None
    
    def get_external_settings(self) -> dict:
        """Get external platform settings"""
        if self.ai_assistant_type in ['chatforyou', 'protalk'] and self.external_settings:
            return self.external_settings
        return {}
    
    def update_external_settings(self, settings: dict) -> bool:
        """Update external platform settings"""
        if self.ai_assistant_type not in ['chatforyou', 'protalk']:
            return False
        
        if not self.external_settings:
            self.external_settings = {}
        
        self.external_settings.update(settings)
        return True
    
    def get_external_credentials(self) -> dict:
        """Get external platform credentials"""
        if self.ai_assistant_type in ['chatforyou', 'protalk']:
            return {
                'api_token': self.external_api_token,
                'bot_id': self.external_bot_id,
                'platform': self.external_platform
            }
        return {}
    
    # === ОБЩИЕ AI МЕТОДЫ ===
    
    def get_ai_daily_limit(self) -> Optional[int]:
        """Get AI daily message limit"""
        if self.ai_assistant_type == 'openai' and self.openai_settings:
            return self.openai_settings.get('daily_limit')
        elif self.ai_assistant_type in ['chatforyou', 'protalk'] and self.external_settings:
            return self.external_settings.get('daily_limit')
        return None
    
    def set_ai_daily_limit(self, limit: Optional[int]) -> bool:
        """Set AI daily message limit"""
        if self.ai_assistant_type == 'openai':
            if not self.openai_settings:
                self.openai_settings = {}
            self.openai_settings['daily_limit'] = limit
            return True
        elif self.ai_assistant_type in ['chatforyou', 'protalk']:
            if not self.external_settings:
                self.external_settings = {}
            self.external_settings['daily_limit'] = limit
            return True
        return False
    
    def get_ai_stats(self) -> dict:
        """Get AI usage statistics"""
        stats = {
            'type': self.ai_assistant_type,
            'enabled': self.ai_assistant_enabled,
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'success_rate': 0.0,
            'last_request_at': None
        }
        
        if self.ai_assistant_type == 'openai' and self.openai_settings:
            settings = self.openai_settings
        elif self.ai_assistant_type in ['chatforyou', 'protalk'] and self.external_settings:
            settings = self.external_settings
        else:
            return stats
        
        stats.update({
            'total_requests': settings.get('total_requests', 0),
            'successful_requests': settings.get('successful_requests', 0),
            'failed_requests': settings.get('failed_requests', 0),
            'last_request_at': settings.get('last_request_at')
        })
        
        # Calculate success rate
        total = stats['total_requests']
        if total > 0:
            stats['success_rate'] = (stats['successful_requests'] / total) * 100
        
        return stats
    
    def increment_ai_request_stats(self, success: bool = True) -> None:
        """Increment AI request statistics"""
        current_time = datetime.now().isoformat()
        
        if self.ai_assistant_type == 'openai':
            if not self.openai_settings:
                self.openai_settings = {}
            settings = self.openai_settings
        elif self.ai_assistant_type in ['chatforyou', 'protalk']:
            if not self.external_settings:
                self.external_settings = {}
            settings = self.external_settings
        else:
            return
        
        settings['total_requests'] = settings.get('total_requests', 0) + 1
        settings['last_request_at'] = current_time
        
        if success:
            settings['successful_requests'] = settings.get('successful_requests', 0) + 1
        else:
            settings['failed_requests'] = settings.get('failed_requests', 0) + 1
    
    def clear_ai_configuration(self) -> bool:
        """Clear AI assistant configuration"""
        self.ai_assistant_enabled = False
        self.ai_assistant_type = None
        
        # Clear OpenAI fields
        self.openai_agent_id = None
        self.openai_agent_name = None
        self.openai_agent_instructions = None
        self.openai_model = "gpt-4o"
        self.openai_use_responses_api = True
        self.openai_store_conversations = True
        self.openai_conversation_retention_days = 30
        self.openai_conversation_contexts = {}  # ✅ ОБНОВЛЕНО
        self.openai_settings = None
        
        # Clear external platform fields
        self.external_api_token = None
        self.external_bot_id = None
        self.external_platform = None
        self.external_settings = None
        
        return True
    
    def get_ai_configuration_summary(self) -> dict:
        """✅ ОБНОВЛЕНО: Get summary of AI configuration"""
        summary = {
            'enabled': self.ai_assistant_enabled,
            'type': self.ai_assistant_type,
            'configured': self.is_ai_enabled(),
            'subscription_check': {
                'enabled': self.is_subscription_check_enabled(),
                'channel_info': self.get_subscription_channel_info(),
                'validation': self.validate_subscription_config()
            }
        }
        
        if self.ai_assistant_type == 'openai':
            summary.update({
                'agent_id': self.openai_agent_id,
                'agent_name': self.openai_agent_name,
                'model': self.openai_model,
                'has_instructions': bool(self.openai_agent_instructions),
                'using_responses_api': self.is_using_responses_api(),
                'active_conversations': self.get_active_conversations_count(),
                'enabled_tools': self.get_enabled_tools(),
                'vector_stores': len(self.get_vector_store_ids()),
                'reasoning_effort': self.get_reasoning_effort(),
                'computer_use': self.is_computer_use_enabled()
            })
        elif self.ai_assistant_type in ['chatforyou', 'protalk']:
            summary.update({
                'platform': self.external_platform,
                'has_token': bool(self.external_api_token),
                'has_bot_id': bool(self.external_bot_id)
            })
        
        return summary
    
    # ✅ Token management methods (без изменений)
    
    def _check_token_reset_needed(self) -> None:
        """Check if token counters need to be reset"""
        now = datetime.now()
        
        # Check daily reset
        if (self.tokens_reset_daily_at is None or 
            now >= self.tokens_reset_daily_at):
            self.tokens_used_today = 0
            self.tokens_last_reset_daily = now
            # Set next reset to midnight
            next_day = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            self.tokens_reset_daily_at = next_day
        
        # Check monthly reset
        if (self.tokens_reset_monthly_at is None or 
            now >= self.tokens_reset_monthly_at):
            self.tokens_used_this_month = 0
            self.tokens_last_reset_monthly = now
            # Set next reset to first day of next month
            if now.month == 12:
                next_month = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            else:
                next_month = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
            self.tokens_reset_monthly_at = next_month
    
    def get_total_tokens_used(self) -> int:
        """Get total number of tokens used"""
        return self.tokens_used_total or 0
    
    def get_input_tokens_used(self) -> int:
        """Get total input tokens used"""
        return self.tokens_used_input or 0
    
    def get_output_tokens_used(self) -> int:
        """Get total output tokens used"""
        return self.tokens_used_output or 0
    
    def get_tokens_used_today(self) -> int:
        """Get tokens used today"""
        self._check_token_reset_needed()
        return self.tokens_used_today or 0
    
    def get_tokens_used_this_month(self) -> int:
        """Get tokens used this month"""
        self._check_token_reset_needed()
        return self.tokens_used_this_month or 0
    
    def get_remaining_tokens_daily(self) -> Optional[int]:
        """Get remaining daily tokens"""
        if self.tokens_limit_daily is None:
            return None
        
        used_today = self.get_tokens_used_today()
        return max(0, self.tokens_limit_daily - used_today)
    
    def get_remaining_tokens_monthly(self) -> Optional[int]:
        """Get remaining monthly tokens"""
        if self.tokens_limit_monthly is None:
            return None
        
        used_this_month = self.get_tokens_used_this_month()
        return max(0, self.tokens_limit_monthly - used_this_month)
    
    def get_remaining_tokens_total(self) -> Optional[int]:
        """Get remaining total tokens"""
        if self.tokens_limit_total is None:
            return None
        
        total_used = self.get_total_tokens_used()
        return max(0, self.tokens_limit_total - total_used)
    
    def get_remaining_tokens(self) -> Optional[int]:
        """Get minimum remaining tokens from all limits"""
        daily_remaining = self.get_remaining_tokens_daily()
        monthly_remaining = self.get_remaining_tokens_monthly()
        total_remaining = self.get_remaining_tokens_total()
        
        # Get minimum of all non-None limits
        remaining_values = [r for r in [daily_remaining, monthly_remaining, total_remaining] if r is not None]
        
        if not remaining_values:
            return None  # No limits set
        
        return min(remaining_values)
    
    def is_tokens_exhausted(self) -> bool:
        """Check if tokens are exhausted"""
        remaining = self.get_remaining_tokens()
        return remaining is not None and remaining <= 0
    
    def is_daily_tokens_exhausted(self) -> bool:
        """Check if daily tokens are exhausted"""
        remaining = self.get_remaining_tokens_daily()
        return remaining is not None and remaining <= 0
    
    def is_monthly_tokens_exhausted(self) -> bool:
        """Check if monthly tokens are exhausted"""
        remaining = self.get_remaining_tokens_monthly()
        return remaining is not None and remaining <= 0
    
    def is_total_tokens_exhausted(self) -> bool:
        """Check if total tokens are exhausted"""
        remaining = self.get_remaining_tokens_total()
        return remaining is not None and remaining <= 0
    
    def add_token_usage(self, input_tokens: int, output_tokens: int) -> bool:
        """Add token usage and update statistics"""
        if input_tokens < 0 or output_tokens < 0:
            return False
        
        # Check if we have enough tokens before adding
        total_new_tokens = input_tokens + output_tokens
        remaining = self.get_remaining_tokens()
        
        if remaining is not None and total_new_tokens > remaining:
            return False  # Would exceed limit
        
        # Update token counters
        self._check_token_reset_needed()
        
        self.tokens_used_total = (self.tokens_used_total or 0) + total_new_tokens
        self.tokens_used_input = (self.tokens_used_input or 0) + input_tokens
        self.tokens_used_output = (self.tokens_used_output or 0) + output_tokens
        self.tokens_used_today = (self.tokens_used_today or 0) + total_new_tokens
        self.tokens_used_this_month = (self.tokens_used_this_month or 0) + total_new_tokens
        
        # Update peak daily usage
        if self.tokens_used_today > (self.tokens_peak_daily_usage or 0):
            self.tokens_peak_daily_usage = self.tokens_used_today
        
        # Update average tokens per request
        total_requests = 0
        if self.ai_assistant_type == 'openai' and self.openai_settings:
            total_requests = self.openai_settings.get('total_requests', 0)
        elif self.ai_assistant_type in ['chatforyou', 'protalk'] and self.external_settings:
            total_requests = self.external_settings.get('total_requests', 0)
        
        if total_requests > 0:
            self.tokens_avg_per_request = float(self.tokens_used_total) / total_requests
        
        return True
    
    def set_token_limits(self, daily: Optional[int] = None, monthly: Optional[int] = None, 
                        total: Optional[int] = None) -> bool:
        """Set token limits"""
        if daily is not None and daily < 0:
            return False
        if monthly is not None and monthly < 0:
            return False
        if total is not None and total < 0:
            return False
        
        self.tokens_limit_daily = daily
        self.tokens_limit_monthly = monthly
        self.tokens_limit_total = total
        
        return True
    
    def get_token_limits(self) -> dict:
        """Get all token limits"""
        return {
            'daily': self.tokens_limit_daily,
            'monthly': self.tokens_limit_monthly,
            'total': self.tokens_limit_total
        }
    
    def get_token_usage_stats(self) -> dict:
        """Get comprehensive token usage statistics"""
        self._check_token_reset_needed()
        
        return {
            'total_used': self.get_total_tokens_used(),
            'input_used': self.get_input_tokens_used(),
            'output_used': self.get_output_tokens_used(),
            'used_today': self.get_tokens_used_today(),
            'used_this_month': self.get_tokens_used_this_month(),
            'peak_daily': self.tokens_peak_daily_usage or 0,
            'avg_per_request': float(self.tokens_avg_per_request) if self.tokens_avg_per_request else 0.0,
            'limits': self.get_token_limits(),
            'remaining': {
                'daily': self.get_remaining_tokens_daily(),
                'monthly': self.get_remaining_tokens_monthly(),
                'total': self.get_remaining_tokens_total(),
                'minimum': self.get_remaining_tokens()
            },
            'exhausted': {
                'daily': self.is_daily_tokens_exhausted(),
                'monthly': self.is_monthly_tokens_exhausted(),
                'total': self.is_total_tokens_exhausted(),
                'any': self.is_tokens_exhausted()
            },
            'reset_info': {
                'daily_reset_at': self.tokens_reset_daily_at,
                'monthly_reset_at': self.tokens_reset_monthly_at,
                'last_daily_reset': self.tokens_last_reset_daily,
                'last_monthly_reset': self.tokens_last_reset_monthly
            }
        }
    
    def reset_token_counters(self, reset_daily: bool = False, reset_monthly: bool = False, 
                           reset_total: bool = False) -> bool:
        """Reset token counters manually"""
        now = datetime.now()
        
        if reset_daily:
            self.tokens_used_today = 0
            self.tokens_last_reset_daily = now
            # Set next reset to tomorrow
            next_day = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            self.tokens_reset_daily_at = next_day
        
        if reset_monthly:
            self.tokens_used_this_month = 0
            self.tokens_last_reset_monthly = now
            # Set next reset to next month
            if now.month == 12:
                next_month = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            else:
                next_month = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
            self.tokens_reset_monthly_at = next_month
        
        if reset_total:
            self.tokens_used_total = 0
            self.tokens_used_input = 0
            self.tokens_used_output = 0
            self.tokens_peak_daily_usage = 0
            self.tokens_avg_per_request = None
        
        return True
    
    def __repr__(self):
        return f"<UserBot(id={self.id}, username={self.bot_username}, status={self.status}, ai_type={self.ai_assistant_type})>"


class BotAdminChannel(Base):
    """Каналы для контент-агентов ботов"""
    __tablename__ = "bot_admin_channels"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(String(255), ForeignKey("user_bots.bot_id", ondelete="CASCADE"), nullable=False)
    chat_id = Column(BigInteger, nullable=False)  # ID канала в Telegram
    chat_title = Column(String(255), nullable=True)
    chat_username = Column(String(255), nullable=True)
    chat_type = Column(String(50), default="channel", nullable=True)
    added_at = Column(DateTime, default=func.now())
    is_active = Column(Boolean, default=True)
    can_post_messages = Column(Boolean, default=True)
    last_rerait = Column(JSONB, nullable=True)  # Последний результат рерайта
    
    # Relationships
    bot = relationship("UserBot", back_populates="admin_channels")
    
    def __repr__(self):
        return f"<BotAdminChannel(id={self.id}, bot_id={self.bot_id}, chat_id={self.chat_id})>"


class ContentAgent(Base):
    __tablename__ = "content_agents"
    
    id = Column(Integer, primary_key=True)
    bot_id = Column(String(255), ForeignKey("user_bots.bot_id", ondelete="CASCADE"))
    agent_name = Column(String(255), nullable=False)
    instructions = Column(Text, nullable=False)  # Пользовательский промпт
    openai_agent_id = Column(String(255))
    is_active = Column(Boolean, default=True)
    
    # ✅ ДОБАВИТЬ: Недостающие поля времени
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relationships
    bot = relationship("UserBot", back_populates="content_agents")
    
    def __repr__(self):
        return f"<ContentAgent(id={self.id}, bot_id={self.bot_id}, agent_name={self.agent_name}, is_active={self.is_active})>"


class Broadcast(Base):
    __tablename__ = "broadcasts"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(String(100), ForeignKey("user_bots.bot_id", ondelete="CASCADE"), nullable=False)
    
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
    
    # ✅ Creator tracking
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
    bot_id = Column(String(100), ForeignKey("user_bots.bot_id", ondelete="CASCADE"), nullable=False)
    
    # Daily metrics
    date = Column(DateTime, default=func.current_date())
    new_subscribers = Column(Integer, default=0)
    left_subscribers = Column(Integer, default=0)
    messages_sent = Column(Integer, default=0)
    commands_used = Column(Integer, default=0)
    
    # ✅ Admin activity tracking
    admin_actions = Column(Integer, default=0)  # Admin commands used
    
    # ✅ AI usage analytics
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
    bot_id = Column(String(100), ForeignKey("user_bots.bot_id", ondelete="CASCADE"), nullable=False)
    user_id = Column(BigInteger, nullable=False)
    chat_id = Column(BigInteger, nullable=True, index=True)
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
    
    # ✅ AI interaction tracking
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
    
    # ✅ Creator tracking
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
    
    # ✅ Creator tracking
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
    
    # ✅ Creator tracking
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


# ✅ Admin activity logging table
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


# ✅ FIXED: AI Usage tracking table with timezone fix
class AIUsageLog(Base):
    """Лог использования ИИ для отслеживания лимитов с поддержкой платформ"""
    __tablename__ = "ai_usage_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(String(100), ForeignKey("user_bots.bot_id", ondelete="CASCADE"), nullable=False)
    user_id = Column(BigInteger, nullable=False)  # Telegram user ID
    messages_count = Column(Integer, default=0, nullable=False)
    date = Column(Date, default=func.current_date(), nullable=False)  # ✅ ИСПРАВЛЕНО: Date вместо DateTime
    
    # ✅ Platform-specific tracking
    platform_used = Column(String(50), nullable=True)    # 'openai', 'chatforyou' или 'protalk'
    successful_requests = Column(Integer, default=0, nullable=False)  # Успешные запросы
    failed_requests = Column(Integer, default=0, nullable=False)      # Неудачные запросы
    average_response_time = Column(Numeric(precision=10, scale=3), nullable=True)  # Среднее время ответа в секундах
    
    # ✅ Usage statistics
    total_tokens_used = Column(Integer, default=0, nullable=True)     # Использовано токенов (если доступно)
    longest_conversation = Column(Integer, default=0, nullable=False) # Самый длинный диалог в сообщениях
    
    # ✅ Error tracking
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
            'openai': 'OpenAI',
            'chatforyou': 'ChatForYou',
            'protalk': 'ProTalk'
        }
        return platform_names.get(self.platform_used, self.platform_used or 'Unknown')
    
    def __repr__(self):
        return f"<AIUsageLog(id={self.id}, bot_id={self.bot_id}, user_id={self.user_id}, date={self.date}, count={self.messages_count}, platform={self.platform_used})>"


# ✅ AI Platform Status tracking table
class AIPlatformStatus(Base):
    """Статус доступности AI платформ"""
    __tablename__ = "ai_platform_status"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    platform_name = Column(String(50), nullable=False, unique=True)  # 'openai', 'chatforyou' или 'protalk'
    
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


# ✅ НОВЫЕ МОДЕЛИ: Массовые рассылки
class MassBroadcast(Base):
    """Массовые рассылки для ботов"""
    __tablename__ = "mass_broadcasts"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(String(100), ForeignKey("user_bots.bot_id", ondelete="CASCADE"), nullable=False)
    
    # Основная информация
    title = Column(String(255), nullable=True)  # Название для админа
    message_text = Column(Text, nullable=False)
    
    # Медиа (опционально)
    media_file_id = Column(String(255), nullable=True)        # Telegram file_id
    media_file_unique_id = Column(String(255), nullable=True) # Telegram file_unique_id  
    media_file_size = Column(Integer, nullable=True)          # Размер файла в байтах
    media_filename = Column(String(255), nullable=True)       # Оригинальное имя файла
    media_type = Column(String(50), nullable=True)            # 'photo', 'video', etc.
    
    # Inline кнопка (опционально)
    button_text = Column(String(255), nullable=True)          # Текст кнопки
    button_url = Column(String(500), nullable=True)           # URL кнопки
    
    # Планирование
    broadcast_type = Column(String(20), nullable=False, default="instant")  # 'instant' или 'scheduled'
    scheduled_at = Column(DateTime, nullable=True)            # Время отправки (для scheduled)
    
    # Статус
    status = Column(String(20), nullable=False, default="draft")  # 'draft', 'sending', 'completed', 'failed', 'cancelled'
    
    # Статистика
    total_recipients = Column(Integer, default=0, nullable=False)
    sent_count = Column(Integer, default=0, nullable=False)
    delivered_count = Column(Integer, default=0, nullable=False)
    failed_count = Column(Integer, default=0, nullable=False)
    
    # Метаданные
    created_by = Column(BigInteger, nullable=False)           # Telegram ID админа
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    started_at = Column(DateTime, nullable=True)              # Когда началась отправка
    completed_at = Column(DateTime, nullable=True)            # Когда завершилась отправка
    
    # Relationships
    bot = relationship("UserBot", foreign_keys=[bot_id])
    deliveries = relationship("BroadcastDelivery", back_populates="broadcast", cascade="all, delete-orphan")
    
    def has_media(self) -> bool:
        """Проверить наличие медиа"""
        return bool(self.media_file_id)
    
    def has_button(self) -> bool:
        """Проверить наличие кнопки"""
        return bool(self.button_text and self.button_url)
    
    def is_scheduled(self) -> bool:
        """Проверить является ли рассылка запланированной"""
        return self.broadcast_type == "scheduled" and self.scheduled_at is not None
    
    def is_ready_to_send(self) -> bool:
        """Проверить готовность к отправке"""
        if self.broadcast_type == "instant":
            return self.status == "draft"
        elif self.broadcast_type == "scheduled":
            return self.status == "draft" and self.scheduled_at and self.scheduled_at <= datetime.now()
        return False
    
    def get_success_rate(self) -> float:
        """Получить процент успешной доставки"""
        if self.total_recipients == 0:
            return 0.0
        return (self.sent_count / self.total_recipients) * 100
    
    def get_preview_text(self, max_length: int = 100) -> str:
        """Получить превью текста"""
        if len(self.message_text) <= max_length:
            return self.message_text
        return self.message_text[:max_length] + "..."
    
    def __repr__(self):
        return f"<MassBroadcast(id={self.id}, bot_id={self.bot_id}, type={self.broadcast_type}, status={self.status})>"


class BroadcastDelivery(Base):
    """Доставка массовых рассылок"""
    __tablename__ = "broadcast_deliveries"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    broadcast_id = Column(Integer, ForeignKey("mass_broadcasts.id", ondelete="CASCADE"), nullable=False)
    bot_id = Column(String(100), ForeignKey("user_bots.bot_id", ondelete="CASCADE"), nullable=False)
    user_id = Column(BigInteger, nullable=False)              # Telegram user_id получателя
    
    # Статус доставки
    status = Column(String(20), nullable=False, default="pending")  # 'pending', 'sent', 'delivered', 'failed', 'blocked'
    
    # Информация о доставке
    sent_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    telegram_message_id = Column(Integer, nullable=True)      # ID отправленного сообщения в Telegram
    
    # Метаданные
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    
    # Unique constraint
    __table_args__ = (
        UniqueConstraint('broadcast_id', 'user_id', name='uq_broadcast_delivery_user'),
    )
    
    # Relationships
    broadcast = relationship("MassBroadcast", back_populates="deliveries")
    bot = relationship("UserBot", foreign_keys=[bot_id])
    
    def mark_sent(self, telegram_message_id: int = None):
        """Отметить как отправленное"""
        self.status = "sent"
        self.sent_at = datetime.now()
        if telegram_message_id:
            self.telegram_message_id = telegram_message_id
    
    def mark_delivered(self):
        """Отметить как доставленное"""
        self.status = "delivered"
        self.delivered_at = datetime.now()
    
    def mark_failed(self, error_message: str):
        """Отметить как неудачное"""
        self.status = "failed"
        self.error_message = error_message
    
    def __repr__(self):
        return f"<BroadcastDelivery(id={self.id}, broadcast_id={self.broadcast_id}, user_id={self.user_id}, status={self.status})>"


# ✅ НОВАЯ МОДЕЛЬ: Реферальные транзакции
class ReferralTransaction(Base):
    """Транзакции партнерских комиссий"""
    __tablename__ = "referral_transactions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    referrer_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)  # Кто пригласил
    referred_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)  # Кого пригласил
    payment_amount = Column(Numeric(precision=10, scale=2), nullable=False)   # Сумма оплаты
    commission_amount = Column(Numeric(precision=10, scale=2), nullable=False) # 15% комиссия
    commission_rate = Column(Numeric(precision=5, scale=2), default=15.0, nullable=False) # %
    status = Column(String(20), default="pending", nullable=False)  # pending/paid/cancelled
    transaction_type = Column(String(20), default="subscription", nullable=False) # subscription/tokens
    
    # Metadata
    created_at = Column(DateTime, default=func.now(), nullable=False)
    paid_at = Column(DateTime, nullable=True)
    
    # Relationships
    referrer = relationship("User", foreign_keys=[referrer_id])
    referred_user = relationship("User", foreign_keys=[referred_id])
    
    def mark_paid(self):
        """Mark commission as paid"""
        self.status = "paid"
        self.paid_at = datetime.now()
    
    def get_commission_percentage(self) -> float:
        """Get commission rate as percentage"""
        return float(self.commission_rate)
    
    def calculate_commission(self, payment_amount: float, rate: float = 15.0) -> float:
        """Calculate commission amount"""
        return (payment_amount * rate) / 100
    
    def is_paid(self) -> bool:
        """Check if commission is paid"""
        return self.status == "paid"
    
    def is_pending(self) -> bool:
        """Check if commission is pending"""
        return self.status == "pending"
    
    def cancel_transaction(self) -> bool:
        """Cancel the referral transaction"""
        if self.status == "pending":
            self.status = "cancelled"
            return True
        return False
    
    def get_transaction_details(self) -> dict:
        """Get transaction details as dictionary"""
        return {
            'id': self.id,
            'referrer_id': self.referrer_id,
            'referred_id': self.referred_id,
            'payment_amount': float(self.payment_amount),
            'commission_amount': float(self.commission_amount),
            'commission_rate': float(self.commission_rate),
            'status': self.status,
            'transaction_type': self.transaction_type,
            'created_at': self.created_at,
            'paid_at': self.paid_at,
            'is_paid': self.is_paid(),
            'is_pending': self.is_pending()
        }
    
    def __repr__(self):
        return f"<ReferralTransaction(id={self.id}, referrer={self.referrer_id}, amount={self.commission_amount})>"


# ✅ Экспорт всех моделей
__all__ = [
    "User", "UserBot", "BotAdminChannel", "ContentAgent", "Broadcast", "BotAnalytics", 
    "BotSubscriber", "BroadcastSequence", "BroadcastMessage", "MessageButton", 
    "ScheduledMessage", "BotAdminLog", "AIUsageLog", "AIPlatformStatus",
    "MassBroadcast", "BroadcastDelivery", "ReferralTransaction"
]
