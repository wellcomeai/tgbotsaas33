"""
OpenAI Assistant Models
Модели данных для работы с OpenAI Assistants API
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from datetime import datetime


@dataclass
class OpenAIAgent:
    """Модель OpenAI агента"""
    id: Optional[int] = None
    bot_id: Optional[str] = None
    agent_name: str = ""
    agent_role: str = ""
    system_prompt: str = ""
    model: str = "gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int = 2000
    context_window: int = 10
    is_active: bool = True
    openai_assistant_id: Optional[str] = None  # ID из OpenAI API
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    def to_openai_config(self) -> Dict[str, Any]:
        """Конвертация в конфигурацию для OpenAI API"""
        instructions = self.system_prompt or f"Ты - {self.agent_role}. {self.agent_name}"
        
        return {
            "name": self.agent_name,
            "instructions": instructions,
            "model": self.model,
            "tools": [],  # Пока без дополнительных инструментов
            "metadata": {
                "bot_id": self.bot_id,
                "local_agent_id": str(self.id) if self.id else None,
                "created_by": "bot_factory"
            }
        }
    
    @classmethod
    def from_db_row(cls, row) -> 'OpenAIAgent':
        """Создание из строки БД"""
        return cls(
            id=row.id,
            bot_id=row.bot_id,
            agent_name=row.agent_name,
            agent_role=row.agent_role,
            system_prompt=row.system_prompt,
            model=row.model,
            temperature=float(row.temperature),
            max_tokens=row.max_tokens,
            context_window=row.context_window,
            is_active=row.is_active,
            openai_assistant_id=getattr(row, 'openai_assistant_id', None),
            created_at=row.created_at,
            updated_at=row.updated_at
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь"""
        return {
            'id': self.id,
            'bot_id': self.bot_id,
            'agent_name': self.agent_name,
            'agent_role': self.agent_role,
            'system_prompt': self.system_prompt,
            'model': self.model,
            'temperature': self.temperature,
            'max_tokens': self.max_tokens,
            'context_window': self.context_window,
            'is_active': self.is_active,
            'openai_assistant_id': self.openai_assistant_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


@dataclass
class OpenAIThread:
    """Модель треда OpenAI"""
    thread_id: str
    user_id: int
    bot_id: str
    agent_id: int
    created_at: datetime
    last_message_at: Optional[datetime] = None
    message_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь"""
        return {
            'thread_id': self.thread_id,
            'user_id': self.user_id,
            'bot_id': self.bot_id,
            'agent_id': self.agent_id,
            'created_at': self.created_at.isoformat(),
            'last_message_at': self.last_message_at.isoformat() if self.last_message_at else None,
            'message_count': self.message_count
        }


@dataclass
class OpenAIResponse:
    """Модель ответа от OpenAI"""
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None
    thread_id: Optional[str] = None
    run_id: Optional[str] = None
    assistant_id: Optional[str] = None
    tokens_used: Optional[int] = None
    response_time: Optional[float] = None
    
    @classmethod
    def success_response(
        cls, 
        message: str, 
        thread_id: str = None, 
        run_id: str = None,
        assistant_id: str = None,
        tokens_used: int = None,
        response_time: float = None
    ) -> 'OpenAIResponse':
        """Создание успешного ответа"""
        return cls(
            success=True,
            message=message,
            thread_id=thread_id,
            run_id=run_id,
            assistant_id=assistant_id,
            tokens_used=tokens_used,
            response_time=response_time
        )
    
    @classmethod
    def error_response(cls, error: str) -> 'OpenAIResponse':
        """Создание ответа с ошибкой"""
        return cls(success=False, error=error)
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь"""
        return {
            'success': self.success,
            'message': self.message,
            'error': self.error,
            'thread_id': self.thread_id,
            'run_id': self.run_id,
            'assistant_id': self.assistant_id,
            'tokens_used': self.tokens_used,
            'response_time': self.response_time
        }


@dataclass
class OpenAICreateAgentRequest:
    """Запрос на создание агента"""
    bot_id: str
    agent_name: str
    agent_role: str
    system_prompt: Optional[str] = None
    model: str = "gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int = 2000
    
    def to_agent(self) -> OpenAIAgent:
        """Конвертация в OpenAIAgent"""
        return OpenAIAgent(
            bot_id=self.bot_id,
            agent_name=self.agent_name,
            agent_role=self.agent_role,
            system_prompt=self.system_prompt or f"Ты - {self.agent_role}.",
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens
        )


@dataclass
class OpenAIConversationContext:
    """Контекст диалога с пользователем"""
    user_id: int
    user_name: str
    username: Optional[str] = None
    bot_id: Optional[str] = None
    chat_id: Optional[int] = None
    is_admin: bool = False
    
    def to_context_string(self) -> str:
        """Конвертация в строку контекста для ИИ"""
        context_parts = [f"Пользователь: {self.user_name}"]
        
        if self.username:
            context_parts.append(f"Username: @{self.username}")
        
        if self.is_admin:
            context_parts.append("Статус: Администратор")
        
        return ". ".join(context_parts)


# Константы для OpenAI
class OpenAIConstants:
    """Константы для работы с OpenAI"""
    
    # Поддерживаемые модели
    MODELS = {
        'gpt-4o-mini': 'GPT-4o Mini (рекомендуется)',
        'gpt-4o': 'GPT-4o (более мощная)',
        'gpt-3.5-turbo': 'GPT-3.5 Turbo (быстрая)'
    }
    
    DEFAULT_MODEL = 'gpt-4o-mini'
    DEFAULT_TEMPERATURE = 0.7
    DEFAULT_MAX_TOKENS = 2000
    DEFAULT_CONTEXT_WINDOW = 10
    
    # Лимиты
    MAX_AGENT_NAME_LENGTH = 255
    MAX_AGENT_ROLE_LENGTH = 500
    MAX_SYSTEM_PROMPT_LENGTH = 8000
    
    # Статусы выполнения
    RUN_STATUS = {
        'queued': 'В очереди',
        'in_progress': 'Выполняется', 
        'requires_action': 'Требует действия',
        'cancelling': 'Отменяется',
        'cancelled': 'Отменено',
        'failed': 'Ошибка',
        'completed': 'Завершено',
        'expired': 'Истекло'
    }
    
    # Таймауты
    RUN_TIMEOUT = 30  # секунд
    POLLING_INTERVAL = 1  # секунд
    MAX_POLLING_ATTEMPTS = 30


# Утилиты для валидации
class OpenAIValidator:
    """Валидация данных для OpenAI"""
    
    @staticmethod
    def validate_agent_name(name: str) -> tuple[bool, str]:
        """Валидация имени агента"""
        if not name or len(name.strip()) == 0:
            return False, "Имя агента не может быть пустым"
        
        if len(name) > OpenAIConstants.MAX_AGENT_NAME_LENGTH:
            return False, f"Имя агента слишком длинное (максимум {OpenAIConstants.MAX_AGENT_NAME_LENGTH} символов)"
        
        return True, ""
    
    @staticmethod
    def validate_agent_role(role: str) -> tuple[bool, str]:
        """Валидация роли агента"""
        if not role or len(role.strip()) == 0:
            return False, "Роль агента не может быть пустой"
        
        if len(role) > OpenAIConstants.MAX_AGENT_ROLE_LENGTH:
            return False, f"Роль агента слишком длинная (максимум {OpenAIConstants.MAX_AGENT_ROLE_LENGTH} символов)"
        
        return True, ""
    
    @staticmethod
    def validate_system_prompt(prompt: str) -> tuple[bool, str]:
        """Валидация системного промпта"""
        if prompt and len(prompt) > OpenAIConstants.MAX_SYSTEM_PROMPT_LENGTH:
            return False, f"Системный промпт слишком длинный (максимум {OpenAIConstants.MAX_SYSTEM_PROMPT_LENGTH} символов)"
        
        return True, ""
    
    @staticmethod
    def validate_create_request(request: OpenAICreateAgentRequest) -> tuple[bool, str]:
        """Валидация запроса на создание агента"""
        # Проверяем имя
        valid, error = OpenAIValidator.validate_agent_name(request.agent_name)
        if not valid:
            return False, error
        
        # Проверяем роль
        valid, error = OpenAIValidator.validate_agent_role(request.agent_role)
        if not valid:
            return False, error
        
        # Проверяем системный промпт
        if request.system_prompt:
            valid, error = OpenAIValidator.validate_system_prompt(request.system_prompt)
            if not valid:
                return False, error
        
        # Проверяем модель
        if request.model not in OpenAIConstants.MODELS:
            return False, f"Неподдерживаемая модель: {request.model}"
        
        # Проверяем температуру
        if not 0 <= request.temperature <= 2:
            return False, "Температура должна быть от 0 до 2"
        
        # Проверяем max_tokens
        if not 1 <= request.max_tokens <= 4000:
            return False, "max_tokens должно быть от 1 до 4000"
        
        return True, ""
