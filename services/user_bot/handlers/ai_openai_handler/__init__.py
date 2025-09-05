"""
OpenAI Handler Package
Обработчик OpenAI агентов с поддержкой Responses API
Разбит на модули для лучшей организации кода
"""

from .base import OpenAIHandlerBase
from .agent_creator import AgentCreatorMixin  
from .tools_manager import ToolsManagerMixin
from .files_manager import FilesManagerMixin
from .agent_editor import AgentEditorMixin
from .conversation import ConversationMixin
from .navigation import NavigationMixin

class OpenAIHandler(
    OpenAIHandlerBase,
    AgentCreatorMixin,
    ToolsManagerMixin, 
    FilesManagerMixin,
    AgentEditorMixin,
    ConversationMixin,
    NavigationMixin
):
    """
    Главный обработчик OpenAI агентов с поддержкой Responses API
    
    Композиция из нескольких миксинов:
    - OpenAIHandlerBase: Базовая функциональность и синхронизация
    - AgentCreatorMixin: Создание и настройка агентов
    - ToolsManagerMixin: Управление встроенными инструментами OpenAI
    - FilesManagerMixin: Управление файлами и Vector Stores
    - AgentEditorMixin: Редактирование существующих агентов
    - ConversationMixin: Диалоги и общение с агентами
    - NavigationMixin: Навигация между меню
    """
    pass

__all__ = ['OpenAIHandler']
