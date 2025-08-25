"""
OpenAI Responses API Models
✅ ОБНОВЛЕНО: Полная поддержка OpenAI Responses API
✅ НОВОЕ: Встроенные инструменты, автоматическое управление контекстом
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Union
from datetime import datetime


@dataclass
class OpenAIResponsesRequest:
    """✅ ОБНОВЛЕНО: Запрос для Responses API"""
    bot_id: str
    agent_name: str
    agent_role: str
    system_prompt: Optional[str] = None
    model: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 4000
    
    # ✅ НОВЫЕ ПОЛЯ ДЛЯ RESPONSES API
    store_conversations: bool = True           # Хранить контекст на сервере OpenAI
    conversation_retention: int = 30           # Дни хранения (1-90)
    enable_streaming: bool = True              # Потоковые ответы
    
    # ✅ ВСТРОЕННЫЕ ИНСТРУМЕНТЫ RESPONSES API
    enable_web_search: bool = False            # Встроенный веб-поиск OpenAI
    enable_code_interpreter: bool = False      # Интерпретатор кода
    enable_file_search: bool = False           # Поиск по файлам
    enable_image_generation: bool = False      # Генерация изображений
    vector_store_ids: Optional[List[str]] = None  # ID векторных хранилищ для file_search
    
    # ✅ НОВЫЕ ВОЗМОЖНОСТИ
    computer_use_enabled: bool = False         # Computer use (экспериментально)
    reasoning_effort: str = 'medium'           # Для o-series моделей (low/medium/high)
    
    def to_agent(self) -> 'OpenAIResponsesAgent':
        """Конвертация в OpenAIResponsesAgent"""
        # Формируем список инструментов
        tools = []
        if self.enable_web_search:
            tools.append('web_search_preview')
        if self.enable_code_interpreter:
            tools.append('code_interpreter')
        if self.enable_file_search:
            tools.append('file_search')
        if self.enable_image_generation:
            tools.append('image_generation')
        if self.computer_use_enabled:
            tools.append('computer_use_preview')
        
        return OpenAIResponsesAgent(
            bot_id=self.bot_id,
            agent_name=self.agent_name,
            agent_role=self.agent_role,
            system_prompt=self.system_prompt or f"Ты - {self.agent_role}. Твое имя {self.agent_name}. Отвечай полезно и дружелюбно.",
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            store_conversations=self.store_conversations,
            conversation_retention=self.conversation_retention,
            enable_streaming=self.enable_streaming,
            tools=tools,
            vector_store_ids=self.vector_store_ids or [],
            reasoning_effort=self.reasoning_effort
        )


@dataclass 
class OpenAIResponsesAgent:
    """✅ ОБНОВЛЕНО: Модель агента для Responses API"""
    id: Optional[int] = None
    bot_id: Optional[str] = None
    agent_name: str = ""
    agent_role: str = ""
    system_prompt: str = ""
    model: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 4000
    is_active: bool = True
    
    # ✅ RESPONSES API CORE SETTINGS
    store_conversations: bool = True           # Хранить контекст на сервере
    conversation_retention: int = 30           # Дни хранения (1-90)
    enable_streaming: bool = True              # Потоковые ответы
    tools: List[str] = None                    # Включенные инструменты
    
    # ✅ НОВЫЕ ПОЛЯ ДЛЯ RESPONSES API
    vector_store_ids: List[str] = None         # ID векторных хранилищ для file_search
    reasoning_effort: str = 'medium'           # Уровень рассуждений для o-series моделей
    computer_use_enabled: bool = False         # Computer use (экспериментально)
    
    # Метаданные
    openai_assistant_id: Optional[str] = None  # Локальный ID агента (не OpenAI Assistant)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    def __post_init__(self):
        if self.tools is None:
            self.tools = []
        if self.vector_store_ids is None:
            self.vector_store_ids = []
    
    def to_responses_config(self) -> Dict[str, Any]:
        """✅ ОБНОВЛЕНО: Конвертация в конфигурацию для Responses API"""
        config = {
            "model": self.model,
            "store": self.store_conversations,
            "stream": self.enable_streaming,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        
        # ✅ ДОБАВЛЯЕМ ВСТРОЕННЫЕ ИНСТРУМЕНТЫ RESPONSES API
        if self.tools:
            tools_config = []
            for tool in self.tools:
                if tool == 'web_search_preview':
                    tools_config.append({"type": "web_search_preview"})
                elif tool == 'code_interpreter':
                    tools_config.append({
                        "type": "code_interpreter",
                        "container": {"type": "auto"}
                    })
                elif tool == 'file_search':
                    if self.vector_store_ids:
                        tools_config.append({
                            "type": "file_search",
                            "vector_store_ids": self.vector_store_ids
                        })
                elif tool == 'image_generation':
                    tools_config.append({"type": "image_generation"})
                elif tool == 'computer_use_preview':
                    tools_config.append({"type": "computer_use_preview"})
            
            if tools_config:
                config["tools"] = tools_config
        
        # ✅ ДОБАВЛЯЕМ REASONING EFFORT ДЛЯ O-SERIES МОДЕЛЕЙ
        if self.model.startswith('o1'):
            config["reasoning_effort"] = self.reasoning_effort
        
        return config
    
    def get_system_instructions(self) -> str:
        """✅ НОВОЕ: Получить системные инструкции для Responses API"""
        return self.system_prompt
    
    def has_tool(self, tool_name: str) -> bool:
        """✅ НОВОЕ: Проверить включен ли инструмент"""
        # Нормализуем названия инструментов
        tool_mapping = {
            'web_search': 'web_search_preview',
            'web_search_preview': 'web_search_preview',
            'code_interpreter': 'code_interpreter',
            'file_search': 'file_search',
            'image_generation': 'image_generation',
            'computer_use': 'computer_use_preview',
            'computer_use_preview': 'computer_use_preview'
        }
        
        normalized_tool = tool_mapping.get(tool_name, tool_name)
        return normalized_tool in self.tools
    
    def add_tool(self, tool_name: str, vector_store_ids: List[str] = None) -> bool:
        """✅ НОВОЕ: Добавить инструмент"""
        valid_tools = ['web_search_preview', 'code_interpreter', 'file_search', 'image_generation', 'computer_use_preview']
        
        if tool_name not in valid_tools:
            return False
        
        if tool_name not in self.tools:
            self.tools.append(tool_name)
        
        # Для file_search добавляем vector_store_ids
        if tool_name == 'file_search' and vector_store_ids:
            self.vector_store_ids.extend(vector_store_ids)
            # Убираем дубликаты
            self.vector_store_ids = list(set(self.vector_store_ids))
        
        return True
    
    def remove_tool(self, tool_name: str) -> bool:
        """✅ НОВОЕ: Удалить инструмент"""
        if tool_name in self.tools:
            self.tools.remove(tool_name)
            
            # Если удаляем file_search, очищаем vector_store_ids
            if tool_name == 'file_search':
                self.vector_store_ids = []
            
            return True
        return False
    
    def validate_tools(self) -> tuple[bool, str]:
        """✅ ОБНОВЛЕНО: Валидация списка инструментов"""
        valid_tools = ['web_search_preview', 'code_interpreter', 'file_search', 'image_generation', 'computer_use_preview']
        
        for tool in self.tools:
            if tool not in valid_tools:
                return False, f"Неподдерживаемый инструмент: {tool}"
        
        # Проверяем что для file_search есть vector_store_ids
        if 'file_search' in self.tools and not self.vector_store_ids:
            return False, "Для инструмента file_search необходимо указать vector_store_ids"
        
        return True, ""
    
    def validate_retention(self) -> tuple[bool, str]:
        """Валидация времени хранения разговоров"""
        if not 1 <= self.conversation_retention <= 90:
            return False, "Время хранения должно быть от 1 до 90 дней"
        return True, ""
    
    def validate_reasoning_effort(self) -> tuple[bool, str]:
        """✅ НОВОЕ: Валидация уровня рассуждений"""
        valid_efforts = ['low', 'medium', 'high']
        if self.reasoning_effort not in valid_efforts:
            return False, f"Уровень рассуждений должен быть одним из: {', '.join(valid_efforts)}"
        return True, ""
    
    @classmethod
    def from_db_row(cls, row) -> 'OpenAIResponsesAgent':
        """✅ ОБНОВЛЕНО: Создание из строки БД"""
        tools = []
        vector_store_ids = []
        
        if hasattr(row, 'openai_settings') and row.openai_settings:
            settings = row.openai_settings
            
            # ✅ ОБНОВЛЕННОЕ ИЗВЛЕЧЕНИЕ ИНСТРУМЕНТОВ
            if settings.get('enable_web_search'):
                tools.append('web_search_preview')
            if settings.get('enable_code_interpreter'):
                tools.append('code_interpreter')
            if settings.get('enable_file_search'):
                tools.append('file_search')
                vector_store_ids = settings.get('vector_store_ids', [])
            if settings.get('enable_image_generation'):
                tools.append('image_generation')
            if settings.get('computer_use_enabled'):
                tools.append('computer_use_preview')
        
        # Извлекаем agent_role из настроек или используем по умолчанию
        agent_role = "AI Ассистент"
        if hasattr(row, 'openai_settings') and row.openai_settings:
            agent_role = row.openai_settings.get('agent_role', agent_role)
        
        return cls(
            id=row.id,
            bot_id=row.bot_id,
            agent_name=row.openai_agent_name or "",
            agent_role=agent_role,
            system_prompt=row.openai_agent_instructions or f"Ты - {row.openai_agent_name or 'AI Ассистент'}. Отвечай полезно и дружелюбно.",
            model=row.openai_model or "gpt-4o",
            temperature=float(row.openai_settings.get('temperature', 0.7)) if row.openai_settings else 0.7,
            max_tokens=row.openai_settings.get('max_tokens', 4000) if row.openai_settings else 4000,
            is_active=row.ai_assistant_enabled,
            store_conversations=getattr(row, 'openai_store_conversations', True),
            conversation_retention=getattr(row, 'openai_conversation_retention_days', 30),
            enable_streaming=row.openai_settings.get('enable_streaming', True) if row.openai_settings else True,
            tools=tools,
            vector_store_ids=vector_store_ids,
            reasoning_effort=row.openai_settings.get('reasoning_effort', 'medium') if row.openai_settings else 'medium',
            computer_use_enabled=row.openai_settings.get('computer_use_enabled', False) if row.openai_settings else False,
            openai_assistant_id=row.openai_agent_id,
            created_at=row.created_at,
            updated_at=row.updated_at
        )


@dataclass
class OpenAIResponsesContext:
    """✅ ОБНОВЛЕНО: Контекст диалога для Responses API"""
    user_id: int
    user_name: str
    username: Optional[str] = None
    bot_id: Optional[str] = None
    chat_id: Optional[int] = None
    is_admin: bool = False
    
    # ✅ УБИРАЕМ previous_response_id отсюда - он теперь управляется автоматически
    
    def to_context_string(self) -> str:
        """Конвертация в строку контекста для системных инструкций"""
        context_parts = [f"Пользователь: {self.user_name}"]
        
        if self.username:
            context_parts.append(f"Username: @{self.username}")
        
        if self.is_admin:
            context_parts.append("Статус: Администратор")
        
        return ". ".join(context_parts)
    
    def prepare_instructions_with_context(self, base_instructions: str) -> str:
        """✅ НОВОЕ: Подготовить инструкции с контекстом для Responses API"""
        context_info = self.to_context_string()
        return f"{base_instructions}\n\nКонтекст текущего диалога: {context_info}"


@dataclass
class OpenAIResponsesResult:
    """✅ ОБНОВЛЕНО: Результат от Responses API"""
    success: bool
    response_id: Optional[str] = None      # ID ответа для продолжения разговора
    output_text: Optional[str] = None      # Текст ответа
    error: Optional[str] = None
    
    # ✅ НОВЫЕ ПОЛЯ ДЛЯ RESPONSES API
    input_tokens: Optional[int] = None     # Входящие токены  
    output_tokens: Optional[int] = None    # Исходящие токены
    total_tokens: Optional[int] = None     # Общие токены
    response_time: Optional[float] = None  # Время ответа в секундах
    finish_reason: Optional[str] = None    # Причина завершения
    model_used: Optional[str] = None       # Использованная модель
    tools_used: Optional[List[str]] = None # Использованные инструменты
    
    # ✅ НОВОЕ: Информация о встроенных инструментах
    web_search_results: Optional[List[dict]] = None  # Результаты веб-поиска
    code_executions: Optional[List[dict]] = None     # Выполненный код
    files_searched: Optional[List[str]] = None       # Найденные файлы
    images_generated: Optional[List[str]] = None     # Сгенерированные изображения
    computer_actions: Optional[List[dict]] = None    # Действия Computer Use
    
    # ✅ НОВОЕ: Метаданные ответа
    reasoning_tokens: Optional[int] = None            # Токены рассуждений (для o-series)
    reasoning_effort_used: Optional[str] = None       # Использованный уровень рассуждений
    
    @classmethod
    def success_result(
        cls, 
        response_id: str,
        output_text: str, 
        input_tokens: int = None,
        output_tokens: int = None,
        total_tokens: int = None,
        response_time: float = None,
        finish_reason: str = None,
        model_used: str = None,
        tools_used: List[str] = None,
        **kwargs
    ) -> 'OpenAIResponsesResult':
        """✅ ОБНОВЛЕНО: Создание успешного результата"""
        return cls(
            success=True,
            response_id=response_id,
            output_text=output_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens or (input_tokens or 0) + (output_tokens or 0),
            response_time=response_time,
            finish_reason=finish_reason,
            model_used=model_used,
            tools_used=tools_used or [],
            **kwargs
        )
    
    @classmethod
    def error_result(cls, error: str) -> 'OpenAIResponsesResult':
        """Создание результата с ошибкой"""
        return cls(success=False, error=error)
    
    def to_dict(self) -> Dict[str, Any]:
        """✅ ОБНОВЛЕНО: Конвертация в словарь"""
        return {
            'success': self.success,
            'response_id': self.response_id,
            'output_text': self.output_text,
            'error': self.error,
            'input_tokens': self.input_tokens,
            'output_tokens': self.output_tokens,
            'total_tokens': self.total_tokens,
            'response_time': self.response_time,
            'finish_reason': self.finish_reason,
            'model_used': self.model_used,
            'tools_used': self.tools_used,
            'web_search_results': self.web_search_results,
            'code_executions': self.code_executions,
            'files_searched': self.files_searched,
            'images_generated': self.images_generated,
            'computer_actions': self.computer_actions,
            'reasoning_tokens': self.reasoning_tokens,
            'reasoning_effort_used': self.reasoning_effort_used
        }


class OpenAIResponsesConstants:
    """✅ ОБНОВЛЕНО: Константы для работы с Responses API"""
    
    # ✅ ПОДДЕРЖИВАЕМЫЕ МОДЕЛИ ДЛЯ RESPONSES API
    MODELS = {
        'gpt-4o': 'GPT-4o (рекомендуется для Responses API)',
        'gpt-4o-mini': 'GPT-4o Mini (быстрая и дешевая)',
        'o1-preview': 'o1 Preview (рассуждения)',
        'o1-mini': 'o1 Mini (быстрые рассуждения)',
        'gpt-4.1': 'GPT-4.1 (новейшая модель)'
    }
    
    DEFAULT_MODEL = 'gpt-4o'
    DEFAULT_TEMPERATURE = 0.7
    DEFAULT_MAX_TOKENS = 4000
    
    # ✅ ВСТРОЕННЫЕ ИНСТРУМЕНТЫ RESPONSES API
    AVAILABLE_TOOLS = {
        'web_search_preview': {
            'name': 'Веб-поиск',
            'description': 'Поиск актуальной информации в интернете',
            'pricing': '$25-50 за 1000 запросов'
        },
        'code_interpreter': {
            'name': 'Интерпретатор кода', 
            'description': 'Выполнение Python кода, анализ данных, графики',
            'pricing': 'Включено в стоимость модели'
        },
        'file_search': {
            'name': 'Поиск по файлам',
            'description': 'Поиск информации в загруженных документах',
            'pricing': '$2.50 за 1000 запросов + $0.10/ГБ/день'
        },
        'image_generation': {
            'name': 'Генерация изображений',
            'description': 'Создание изображений по текстовому описанию',
            'pricing': 'В разработке'
        },
        'computer_use_preview': {
            'name': 'Computer Use',
            'description': 'Взаимодействие с компьютерными интерфейсами',
            'pricing': 'В разработке'
        }
    }
    
    # ✅ НОВЫЕ ПАРАМЕТРЫ RESPONSES API
    MAX_CONVERSATION_RETENTION_DAYS = 90
    MIN_CONVERSATION_RETENTION_DAYS = 1
    DEFAULT_CONVERSATION_RETENTION_DAYS = 30
    
    # ✅ REASONING EFFORT ДЛЯ O-SERIES МОДЕЛЕЙ
    REASONING_EFFORTS = {
        'low': 'Низкий (быстро)',
        'medium': 'Средний (рекомендуется)',
        'high': 'Высокий (глубокие рассуждения)'
    }
    
    DEFAULT_REASONING_EFFORT = 'medium'
    
    # Лимиты
    MAX_AGENT_NAME_LENGTH = 255
    MAX_AGENT_ROLE_LENGTH = 500
    MAX_SYSTEM_PROMPT_LENGTH = 8000
    MAX_VECTOR_STORES = 10
    
    # Таймауты
    RESPONSE_TIMEOUT = 60
    STREAM_TIMEOUT = 120


class OpenAIResponsesValidator:
    """✅ ОБНОВЛЕНО: Валидация данных для Responses API"""
    
    @staticmethod
    def validate_agent_name(name: str) -> tuple[bool, str]:
        """Валидация имени агента"""
        if not name or len(name.strip()) == 0:
            return False, "Имя агента не может быть пустым"
        
        if len(name) > OpenAIResponsesConstants.MAX_AGENT_NAME_LENGTH:
            return False, f"Имя агента слишком длинное (максимум {OpenAIResponsesConstants.MAX_AGENT_NAME_LENGTH} символов)"
        
        return True, ""
    
    @staticmethod
    def validate_agent_role(role: str) -> tuple[bool, str]:
        """Валидация роли агента"""
        if not role or len(role.strip()) == 0:
            return False, "Роль агента не может быть пустой"
        
        if len(role) > OpenAIResponsesConstants.MAX_AGENT_ROLE_LENGTH:
            return False, f"Роль агента слишком длинная (максимум {OpenAIResponsesConstants.MAX_AGENT_ROLE_LENGTH} символов)"
        
        return True, ""
    
    @staticmethod
    def validate_system_prompt(prompt: str) -> tuple[bool, str]:
        """Валидация системного промпта"""
        if prompt and len(prompt) > OpenAIResponsesConstants.MAX_SYSTEM_PROMPT_LENGTH:
            return False, f"Системный промпт слишком длинный (максимум {OpenAIResponsesConstants.MAX_SYSTEM_PROMPT_LENGTH} символов)"
        
        return True, ""
    
    @staticmethod
    def validate_model(model: str) -> tuple[bool, str]:
        """Валидация модели"""
        if model not in OpenAIResponsesConstants.MODELS:
            return False, f"Неподдерживаемая модель: {model}"
        
        return True, ""
    
    @staticmethod
    def validate_tools(tools: List[str]) -> tuple[bool, str]:
        """✅ ОБНОВЛЕНО: Валидация инструментов"""
        for tool in tools:
            if tool not in OpenAIResponsesConstants.AVAILABLE_TOOLS:
                return False, f"Неподдерживаемый инструмент: {tool}"
        
        return True, ""
    
    @staticmethod
    def validate_vector_store_ids(vector_store_ids: List[str]) -> tuple[bool, str]:
        """✅ НОВОЕ: Валидация векторных хранилищ"""
        if len(vector_store_ids) > OpenAIResponsesConstants.MAX_VECTOR_STORES:
            return False, f"Слишком много векторных хранилищ (максимум {OpenAIResponsesConstants.MAX_VECTOR_STORES})"
        
        for vs_id in vector_store_ids:
            if not vs_id or not isinstance(vs_id, str):
                return False, "Некорректный ID векторного хранилища"
        
        return True, ""
    
    @staticmethod
    def validate_reasoning_effort(effort: str) -> tuple[bool, str]:
        """✅ НОВОЕ: Валидация уровня рассуждений"""
        if effort not in OpenAIResponsesConstants.REASONING_EFFORTS:
            return False, f"Некорректный уровень рассуждений: {effort}"
        
        return True, ""
    
    @staticmethod
    def validate_retention_days(days: int) -> tuple[bool, str]:
        """Валидация времени хранения"""
        if not OpenAIResponsesConstants.MIN_CONVERSATION_RETENTION_DAYS <= days <= OpenAIResponsesConstants.MAX_CONVERSATION_RETENTION_DAYS:
            return False, f"Время хранения должно быть от {OpenAIResponsesConstants.MIN_CONVERSATION_RETENTION_DAYS} до {OpenAIResponsesConstants.MAX_CONVERSATION_RETENTION_DAYS} дней"
        
        return True, ""
    
    @staticmethod
    def validate_create_request(request: OpenAIResponsesRequest) -> tuple[bool, str]:
        """✅ ОБНОВЛЕНО: Валидация запроса на создание агента"""
        # Проверяем имя
        valid, error = OpenAIResponsesValidator.validate_agent_name(request.agent_name)
        if not valid:
            return False, error
        
        # Проверяем роль
        valid, error = OpenAIResponsesValidator.validate_agent_role(request.agent_role)
        if not valid:
            return False, error
        
        # Проверяем системный промпт
        if request.system_prompt:
            valid, error = OpenAIResponsesValidator.validate_system_prompt(request.system_prompt)
            if not valid:
                return False, error
        
        # Проверяем модель
        valid, error = OpenAIResponsesValidator.validate_model(request.model)
        if not valid:
            return False, error
        
        # ✅ ПРОВЕРЯЕМ REASONING EFFORT
        valid, error = OpenAIResponsesValidator.validate_reasoning_effort(request.reasoning_effort)
        if not valid:
            return False, error
        
        # ✅ ПРОВЕРЯЕМ VECTOR STORE IDS
        if request.vector_store_ids:
            valid, error = OpenAIResponsesValidator.validate_vector_store_ids(request.vector_store_ids)
            if not valid:
                return False, error
        
        # Проверяем время хранения
        valid, error = OpenAIResponsesValidator.validate_retention_days(request.conversation_retention)
        if not valid:
            return False, error
        
        # Проверяем температуру
        if not 0 <= request.temperature <= 2:
            return False, "Температура должна быть от 0 до 2"
        
        # Проверяем max_tokens
        if not 1 <= request.max_tokens <= 16000:
            return False, "max_tokens должно быть от 1 до 16000"
        
        # ✅ ПРОВЕРЯЕМ LOGIC CONSISTENCY
        if request.enable_file_search and not request.vector_store_ids:
            return False, "Для file_search необходимо указать vector_store_ids"
        
        return True, ""
