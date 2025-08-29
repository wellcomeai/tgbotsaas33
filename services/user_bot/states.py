"""
FSM состояния для UserBot
Все состояния конечного автомата в одном месте
✅ ОБНОВЛЕНО: Добавлены все недостающие состояния для ИИ
✅ ОБНОВЛЕНО: Добавлены состояния для массовых рассылок
✅ ОБНОВЛЕНО: Разделены админские и пользовательские состояния ИИ
"""

from aiogram.fsm.state import State, StatesGroup


class ContentStates(StatesGroup):
    """Состояния для работы с контент-агентами"""
    waiting_for_agent_name = State()
    waiting_for_agent_instructions = State()
    waiting_for_rewrite_post = State()
    in_rewrite_mode = State()
    editing_agent_name = State()
    editing_agent_instructions = State()
    waiting_for_channel_post = State()         # Ожидание поста из канала
    waiting_for_edit_instructions = State()    # Ожидание инструкций для правок


class BotSettingsStates(StatesGroup):
    """Состояния настроек бота"""
    # Welcome settings
    waiting_for_welcome_message = State()
    waiting_for_welcome_button = State()
    waiting_for_confirmation_message = State()
    
    # Goodbye settings
    waiting_for_goodbye_message = State()
    waiting_for_goodbye_button_text = State()
    waiting_for_goodbye_button_url = State()


class FunnelStates(StatesGroup):
    """Состояния воронки продаж"""
    # Message creation/editing
    waiting_for_message_text = State()
    waiting_for_message_delay = State()
    waiting_for_media_upload = State()
    waiting_for_media_file = State()
    
    # Message editing
    waiting_for_edit_text = State()
    waiting_for_edit_delay = State()
    
    # Button management
    waiting_for_button_text = State()
    waiting_for_button_url = State()
    waiting_for_edit_button_text = State()
    waiting_for_edit_button_url = State()


class AISettingsStates(StatesGroup):
    """✅ ОБНОВЛЕНО: Состояния настроек ИИ ассистента
    
    ВАЖНО: Разделены состояния для админов (admin_*) и пользователей (user_*)
    Старые состояния сохранены для обратной совместимости на переходный период.
    
    АРХИТЕКТУРА:
    - admin_* состояния - только для владельца бота (настройка, тестирование)
    - user_* состояния - только для обычных пользователей (диалог с ИИ)
    - Старые состояния - deprecated, будут удалены в будущих версиях
    """
    
    # ===== CHATFORYOU/PROTALK СОСТОЯНИЯ =====
    waiting_for_api_token = State()           # API токен (шаг 1)
    waiting_for_bot_id = State()              # ID сотрудника (шаг 2)
    waiting_for_assistant_id = State()        # Совместимость (алиас для api_token)
    waiting_for_daily_limit = State()         # Дневной лимит сообщений
    
    # ===== ЛИМИТЫ СООБЩЕНИЙ =====
    waiting_for_message_limit = State()       # Настройка лимита сообщений в день
    
    # ===== ✅ НОВЫЕ: АДМИНСКИЕ OPENAI СОСТОЯНИЯ =====
    admin_waiting_for_openai_name = State()   # Админ: Имя OpenAI агента
    admin_waiting_for_openai_role = State()   # Админ: Роль и инструкции OpenAI агента
    admin_editing_agent_name = State()        # Админ: Редактирование имени агента
    admin_editing_agent_prompt = State()      # Админ: Редактирование промпта агента
    admin_in_ai_conversation = State()        # Админ: Активный диалог с ИИ агентом (тестирование)
    admin_uploading_documents = State()
    admin_managing_vector_stores = State()
    # ===== ✅ НОВЫЕ: ПОЛЬЗОВАТЕЛЬСКИЕ СОСТОЯНИЯ =====
    user_in_ai_conversation = State()         # Пользователь: Активный диалог с ИИ агентом
    user_ai_waiting_input = State()           # Пользователь: Ожидание ввода от ИИ
    user_ai_blocked = State()                 # Пользователь: Заблокирован (превышены лимиты)
    
    # ===== DEPRECATED: СТАРЫЕ OPENAI СОСТОЯНИЯ (для обратной совместимости) =====
    # TODO: Удалить после полного перехода на admin_*/user_* состояния
    waiting_for_openai_name = State()         # DEPRECATED: Имя OpenAI агента
    waiting_for_openai_role = State()         # DEPRECATED: Роль и инструкции OpenAI агента
    editing_agent_name = State()              # DEPRECATED: Редактирование имени агента
    editing_agent_prompt = State()            # DEPRECATED: Редактирование промпта агента
    in_ai_conversation = State()              # DEPRECATED: Активный диалог с ИИ агентом
    waiting_for_message_limit = State()
class AdminStates(StatesGroup):
    """Основные административные состояния"""
    
    # ===== УПРАВЛЕНИЕ ПОДПИСЧИКАМИ =====
    waiting_for_user_id_to_ban = State()      # Ожидание ID пользователя для бана
    waiting_for_user_id_to_unban = State()    # Ожидание ID пользователя для разбана
    waiting_for_broadcast_message = State()   # Ожидание сообщения для рассылки
    
    # ===== НАСТРОЙКИ КАНАЛОВ =====
    waiting_for_channel_id = State()          # Ожидание ID канала
    waiting_for_channel_username = State()    # Ожидание username канала
    
    # ===== ОБЩИЕ АДМИНСКИЕ ОПЕРАЦИИ =====
    waiting_for_admin_input = State()         # Общий ввод админа
    confirming_action = State()               # Подтверждение действия


class BroadcastStates(StatesGroup):
    """Состояния для системы рассылок"""
    
    # ===== СОЗДАНИЕ СООБЩЕНИЙ =====
    creating_message = State()                # Создание нового сообщения
    waiting_for_message_text = State()        # Ожидание текста сообщения
    waiting_for_schedule_time = State()       # Ожидание времени отправки
    waiting_for_delay = State()               # Ожидание задержки между сообщениями
    
    # ===== КНОПКИ =====
    waiting_for_button_text = State()         # Ожидание текста кнопки
    waiting_for_button_url = State()          # Ожидание URL кнопки
    
    # ===== МЕДИА =====
    selecting_media_type = State()            # Выбор типа медиа
    waiting_for_media = State()               # Ожидание медиа файла
    
    # ===== РЕДАКТИРОВАНИЕ =====
    editing_message = State()                 # Редактирование сообщения
    editing_delay = State()                   # Редактирование задержки
    editing_button = State()                  # Редактирование кнопки
    
    # ===== УПРАВЛЕНИЕ ПОСЛЕДОВАТЕЛЬНОСТЬЮ =====
    managing_sequence = State()               # Управление последовательностью сообщений
    waiting_for_sequence_name = State()       # Ожидание названия последовательности


class ChannelStates(StatesGroup):
    """Состояния для работы с каналами"""
    
    # ===== НАСТРОЙКА ПОДПИСКИ =====
    waiting_for_subscription_channel = State()    # Ожидание пересланного сообщения для настройки подписки
    
    # ===== ДОБАВЛЕНИЕ КАНАЛОВ =====
    waiting_for_channel_link = State()        # Ожидание ссылки на канал
    waiting_for_channel_invite = State()      # Ожидание инвайт-ссылки
    
    # ===== НАСТРОЙКА КАНАЛОВ =====
    configuring_channel = State()             # Настройка канала
    waiting_for_channel_description = State() # Ожидание описания канала
    
    # ===== МОДЕРАЦИЯ =====
    moderating_posts = State()                # Модерация постов
    waiting_for_moderation_decision = State() # Ожидание решения по модерации


class TokenStates(StatesGroup):
    """Состояния для управления токенами"""
    
    # ===== ПОПОЛНЕНИЕ ТОКЕНОВ =====
    requesting_topup = State()                # Запрос пополнения токенов
    waiting_for_topup_amount = State()        # Ожидание суммы пополнения
    
    # ===== НАСТРОЙКА ЛИМИТОВ =====
    setting_token_limits = State()            # Настройка лимитов токенов
    waiting_for_daily_token_limit = State()   # Дневной лимит токенов
    waiting_for_monthly_token_limit = State() # Месячный лимит токенов
    
    # ===== МОНИТОРИНГ =====
    viewing_token_stats = State()             # Просмотр статистики токенов


class AnalyticsStates(StatesGroup):
    """Состояния для аналитики"""
    
    # ===== ПРОСМОТР СТАТИСТИКИ =====
    viewing_stats = State()                   # Просмотр общей статистики
    viewing_user_stats = State()              # Статистика пользователей
    viewing_ai_stats = State()                # Статистика ИИ
    
    # ===== ЭКСПОРТ ДАННЫХ =====
    exporting_data = State()                  # Экспорт данных
    waiting_for_export_format = State()       # Выбор формата экспорта
    
    # ===== НАСТРОЙКА ОТЧЕТОВ =====
    configuring_reports = State()             # Настройка отчетов
    waiting_for_report_schedule = State()     # Расписание отчетов


class DebugStates(StatesGroup):
    """Состояния для отладки (только для разработки)"""
    
    # ===== ДИАГНОСТИКА =====
    running_diagnostics = State()             # Запуск диагностики
    viewing_logs = State()                    # Просмотр логов
    
    # ===== ТЕСТИРОВАНИЕ =====
    testing_features = State()               # Тестирование функций
    simulating_events = State()              # Симуляция событий
    
    # ===== СИСТЕМНЫЕ ОПЕРАЦИИ =====
    performing_maintenance = State()         # Выполнение обслуживания
    waiting_for_system_command = State()     # Ожидание системной команды


class MassBroadcastStates(StatesGroup):
    """Состояния для массовых рассылок"""
    
    # ===== СОЗДАНИЕ МГНОВЕННОЙ РАССЫЛКИ =====
    instant_waiting_for_text = State()          # Ожидание текста мгновенной рассылки
    instant_waiting_for_media = State()         # Ожидание медиа мгновенной рассылки  
    instant_waiting_for_button_text = State()   # Ожидание текста кнопки мгновенной рассылки
    instant_waiting_for_button_url = State()    # Ожидание URL кнопки мгновенной рассылки
    
    # ===== СОЗДАНИЕ ЗАПЛАНИРОВАННОЙ РАССЫЛКИ =====
    scheduled_waiting_for_text = State()        # Ожидание текста запланированной рассылки
    scheduled_waiting_for_media = State()       # Ожидание медиа запланированной рассылки
    scheduled_waiting_for_button_text = State() # Ожидание текста кнопки запланированной рассылки  
    scheduled_waiting_for_button_url = State()  # Ожидание URL кнопки запланированной рассылки
    scheduled_waiting_for_datetime = State()    # Ожидание даты и времени отправки
    
    # ===== ОБЩИЕ СОСТОЯНИЯ =====
    in_preview_mode = State()                   # Режим предпросмотра рассылки
    confirming_send = State()                   # Подтверждение отправки


# ===== ВСПОМОГАТЕЛЬНЫЕ ГРУППЫ =====

class TemporaryStates(StatesGroup):
    """Временные состояния для кратковременных операций"""
    
    waiting_for_confirmation = State()        # Ожидание подтверждения
    waiting_for_input = State()              # Общее ожидание ввода
    processing_request = State()             # Обработка запроса
    uploading_file = State()                 # Загрузка файла


class ErrorStates(StatesGroup):
    """Состояния для обработки ошибок"""
    
    handling_error = State()                 # Обработка ошибки
    waiting_for_retry = State()              # Ожидание повтора
    reporting_bug = State()                  # Отчет об ошибке


# ===== ЭКСПОРТ ВСЕХ СОСТОЯНИЙ =====

__all__ = [
    'ContentStates',
    'BotSettingsStates', 
    'FunnelStates',
    'AISettingsStates',        # ✅ ОБНОВЛЕНО: теперь с разделением админ/пользователь
    'AdminStates',
    'BroadcastStates',
    'ChannelStates',
    'TokenStates',
    'AnalyticsStates',
    'DebugStates',
    'TemporaryStates',
    'ErrorStates',
    'MassBroadcastStates'
]


# ===== МИГРАЦИОННЫЕ ЗАМЕТКИ =====
"""
МИГРАЦИЯ СОСТОЯНИЙ ИИ:

СТАРЫЕ → НОВЫЕ (для админов):
waiting_for_openai_name    → admin_waiting_for_openai_name
waiting_for_openai_role    → admin_waiting_for_openai_role
editing_agent_name         → admin_editing_agent_name
editing_agent_prompt       → admin_editing_agent_prompt
in_ai_conversation         → admin_in_ai_conversation

СТАРЫЕ → НОВЫЕ (для пользователей):
in_ai_conversation         → user_in_ai_conversation

ПЛАН УДАЛЕНИЯ DEPRECATED СОСТОЯНИЙ:
1. Версия 1.1: Добавить новые состояния (✅ СДЕЛАНО)
2. Версия 1.2: Мигрировать код на новые состояния
3. Версия 1.3: Добавить warnings для deprecated состояний
4. Версия 1.4: Удалить deprecated состояния

ПРЕИМУЩЕСТВА НОВОГО ПОДХОДА:
✅ Четкое разделение админ/пользователь
✅ Предотвращение конфликтов состояний
✅ Улучшенная безопасность
✅ Более понятная архитектура
✅ Легче отладка и мониторинг
"""
