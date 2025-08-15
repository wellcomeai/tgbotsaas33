"""
Генераторы клавиатур для UserBot
"""

from typing import List, Optional
from aiogram.types import (
    InlineKeyboardMarkup, 
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from config import settings, Emoji


class AdminKeyboards:
    """Клавиатуры для администратора"""
    
    @staticmethod
    def main_menu(has_openai_bots: bool = False) -> InlineKeyboardMarkup:
        """✅ ОБНОВЛЕНО: Главное меню администратора с кнопкой контент-агента"""
        # Базовые кнопки
        keyboard = [
            [
                InlineKeyboardButton(
                    text="⚙️ Настройки сообщений", 
                    callback_data="admin_settings"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎯 Воронка продаж", 
                    callback_data="admin_funnel"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🤖 ИИ Агент", 
                    callback_data="admin_ai"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📝 Контент канала", 
                    callback_data="content_main"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Статистика", 
                    callback_data="admin_stats"
                )
            ]
        ]
        
        # Добавляем кнопку токенов только если есть OpenAI боты
        if has_openai_bots:
            keyboard.append([
                InlineKeyboardButton(
                    text="💰 Токены OpenAI", 
                    callback_data="admin_tokens"
                )
            ])
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    @staticmethod
    def settings_menu() -> InlineKeyboardMarkup:
        """Меню настроек сообщений"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👋 Приветственное сообщение", 
                    callback_data="settings_welcome"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔘 Кнопка приветствия", 
                    callback_data="settings_welcome_button"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ Сообщение подтверждения", 
                    callback_data="settings_confirmation"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👋 Прощальное сообщение", 
                    callback_data="settings_goodbye"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔗 Кнопка прощания", 
                    callback_data="settings_goodbye_button"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{Emoji.BACK} Назад", 
                    callback_data="admin_main"
                )
            ]
        ])
    
    # ===== CONTENT AGENT KEYBOARDS =====
    
    @staticmethod
    def content_main_menu_no_agent() -> InlineKeyboardMarkup:
        """✅ НОВОЕ: Главное меню контента без агента"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✨ Создать контент-агента", 
                    callback_data="content_create_agent"
                )
            ],
            [
                InlineKeyboardButton(
                    text="ℹ️ Что такое контент-агент?", 
                    callback_data="content_info"
                )
            ],
            [
                InlineKeyboardButton(
                    text="◀️ Назад", 
                    callback_data="admin_main"
                )
            ]
        ])
    
    @staticmethod
    def content_main_menu_with_agent() -> InlineKeyboardMarkup:
        """✅ НОВОЕ: Главное меню контента с агентом"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📝 Переписать пост", 
                    callback_data="content_rewrite"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚙️ Управление агентом", 
                    callback_data="content_manage"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Статистика", 
                    callback_data="content_stats"
                )
            ],
            [
                InlineKeyboardButton(
                    text="◀️ Назад", 
                    callback_data="admin_main"
                )
            ]
        ])
    
    @staticmethod
    def content_create_confirmation() -> InlineKeyboardMarkup:
        """✅ НОВОЕ: Подтверждение создания агента"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, создать агента", 
                    callback_data="content_confirm_create"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена", 
                    callback_data="content_main"
                )
            ]
        ])
    
    @staticmethod
    def content_manage_menu() -> InlineKeyboardMarkup:
        """✅ НОВОЕ: Меню управления агентом"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Настройки агента", 
                    callback_data="content_settings"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🧪 Тестировать", 
                    callback_data="content_test"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗑️ Удалить агента", 
                    callback_data="content_delete_agent"
                )
            ],
            [
                InlineKeyboardButton(
                    text="◀️ Назад", 
                    callback_data="content_main"
                )
            ]
        ])
    
    @staticmethod
    def content_settings_menu() -> InlineKeyboardMarkup:
        """✅ НОВОЕ: Настройки агента"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📝 Изменить имя", 
                    callback_data="content_edit_name"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📋 Изменить инструкции", 
                    callback_data="content_edit_instructions"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔗 OpenAI Agent ID", 
                    callback_data="content_edit_openai_id"
                )
            ],
            [
                InlineKeyboardButton(
                    text="◀️ Назад", 
                    callback_data="content_manage"
                )
            ]
        ])
    
    @staticmethod
    def content_delete_confirmation() -> InlineKeyboardMarkup:
        """✅ НОВОЕ: Подтверждение удаления агента"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑️ Да, удалить навсегда", 
                    callback_data="content_confirm_delete"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена", 
                    callback_data="content_manage"
                )
            ]
        ])
    
    @staticmethod
    def content_rewrite_mode() -> InlineKeyboardMarkup:
        """✅ НОВОЕ: Режим переписывания постов"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚪 Завершить переписывание", 
                    callback_data="content_exit_rewrite"
                )
            ]
        ])
    
    @staticmethod
    def content_post_actions() -> InlineKeyboardMarkup:
        """✅ НОВОЕ: Кнопки после рерайта поста"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Внести правки", 
                    callback_data="content_edit_post"
                ),
                InlineKeyboardButton(
                    text="📤 Опубликовать", 
                    callback_data="content_publish"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Режим рерайта", 
                    callback_data="content_rewrite"
                )
            ]
        ])
    
    @staticmethod  
    def content_back_to_rewrite() -> InlineKeyboardMarkup:
        """✅ НОВОЕ: Возврат к режиму рерайта"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="◀️ К рерайту", 
                    callback_data="content_rewrite"
                )
            ]
        ])
    
    @staticmethod
    def content_test_mode() -> InlineKeyboardMarkup:
        """✅ НОВОЕ: Режим тестирования агента"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚪 Завершить тестирование", 
                    callback_data="content_exit_test"
                )
            ]
        ])
    
    @staticmethod
    def content_back_to_main() -> InlineKeyboardMarkup:
        """✅ НОВОЕ: Назад к главному меню контента"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="◀️ Назад к контенту", 
                    callback_data="content_main"
                )
            ]
        ])
    
    @staticmethod
    def content_stats_menu() -> InlineKeyboardMarkup:
        """✅ НОВОЕ: Меню статистики контент-агента"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Обновить", 
                    callback_data="content_stats"
                )
            ],
            [
                InlineKeyboardButton(
                    text="◀️ Назад", 
                    callback_data="content_main"
                )
            ]
        ])
    
    @staticmethod
    def content_info_menu() -> InlineKeyboardMarkup:
        """✅ НОВОЕ: Информация о контент-агенте"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✨ Создать агента", 
                    callback_data="content_create_agent"
                )
            ],
            [
                InlineKeyboardButton(
                    text="◀️ Назад", 
                    callback_data="content_main"
                )
            ]
        ])


class FunnelKeyboards:
    """Клавиатуры для воронки продаж"""
    
    @staticmethod
    def main_menu() -> InlineKeyboardMarkup:
        """Главное меню воронки"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{Emoji.LIST} Сообщения воронки",
                    callback_data="funnel_messages"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{Emoji.PLUS} Добавить сообщение",
                    callback_data="funnel_add"
                ),
                InlineKeyboardButton(
                    text=f"{Emoji.STATISTICS} Статистика",
                    callback_data="funnel_stats"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{Emoji.SETTINGS} Настройки воронки",
                    callback_data="funnel_settings"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{Emoji.BACK} Назад",
                    callback_data="admin_main"
                )
            ]
        ])
    
    @staticmethod
    def message_menu(message_id: int) -> InlineKeyboardMarkup:
        """Меню управления сообщением"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{Emoji.PREVIEW} Предпросмотр",
                    callback_data=f"msg_preview_{message_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{Emoji.EDIT} Изменить текст",
                    callback_data=f"msg_edit_text_{message_id}"
                ),
                InlineKeyboardButton(
                    text=f"{Emoji.CLOCK} Изменить задержку",
                    callback_data=f"msg_edit_delay_{message_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{Emoji.MEDIA} Медиа",
                    callback_data=f"msg_media_{message_id}"
                ),
                InlineKeyboardButton(
                    text=f"{Emoji.BUTTON} Кнопки",
                    callback_data=f"msg_buttons_{message_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{Emoji.COPY} Дублировать",
                    callback_data=f"msg_duplicate_{message_id}"
                ),
                InlineKeyboardButton(
                    text=f"{Emoji.DELETE} Удалить",
                    callback_data=f"msg_delete_{message_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{Emoji.BACK} К воронке",
                    callback_data="funnel_messages"
                )
            ]
        ])
    
    @staticmethod
    def message_buttons_menu(message_id: int, buttons: list) -> InlineKeyboardMarkup:
        """Меню управления кнопками сообщения"""
        keyboard = []
        
        for i, button in enumerate(buttons, 1):
            button_text = button.button_text[:20] if button.button_text else 'Без названия'
            button_id = button.id
            keyboard.append([
                InlineKeyboardButton(
                    text=f"{i}. {button_text}...",
                    callback_data=f"btn_edit_{button_id}"
                ),
                InlineKeyboardButton(
                    text=f"{Emoji.DELETE}",
                    callback_data=f"btn_delete_{button_id}"
                )
            ])
        
        # Add button for adding new
        if len(buttons) < settings.max_buttons_per_message:
            keyboard.append([
                InlineKeyboardButton(
                    text=f"{Emoji.PLUS} Добавить кнопку",
                    callback_data=f"btn_add_{message_id}"
                )
            ])
        
        keyboard.append([
            InlineKeyboardButton(
                text=f"{Emoji.BACK} К сообщению",
                callback_data=f"msg_view_{message_id}"
            )
        ])
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard)


class AIKeyboards:
    """Клавиатуры для ИИ ассистента"""
    
    @staticmethod
    def settings_menu(ai_enabled: bool, is_configured: bool, platform: str = None, daily_limit: int = None) -> InlineKeyboardMarkup:
        """Меню настроек ИИ (универсальное, для совместимости) - УСТАРЕЛО"""
        # ИЗМЕНЕНО: Эта функция больше не используется, но оставляем для совместимости
        return AIKeyboards.chatforyou_settings_menu(is_configured, platform)
    
    @staticmethod
    def chatforyou_settings_menu(is_configured: bool, platform: str = None) -> InlineKeyboardMarkup:
        """Меню настроек ChatForYou агента - ИЗМЕНЕНО: убрана логика включен/выключен"""
        config_status = "✅ Настроен" if is_configured else "❌ Не настроен"
        
        platform_info = ""
        if platform:
            platform_names = {
                'chatforyou': 'ChatForYou',
                'protalk': 'ProTalk'
            }
            platform_info = f" ({platform_names.get(platform, platform)})"
        
        keyboard = [
            [
                InlineKeyboardButton(
                    text=f"🔑 Конфигурация: {config_status}{platform_info}",
                    callback_data="ai_set_id"
                )
            ]
        ]
        
        # Test button only if fully configured
        if is_configured:
            keyboard.extend([
                [
                    InlineKeyboardButton(
                        text="🧪 Тестировать ИИ",
                        callback_data="ai_test"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="📊 Лимит сообщений",
                        callback_data="ai_message_limit"
                    )
                ]
            ])
        
        # НОВОЕ: Кнопка удаления если агент настроен
        if is_configured:
            keyboard.append([
                InlineKeyboardButton(
                    text="🗑️ Удалить агента",
                    callback_data="ai_delete"
                )
            ])
        
        keyboard.append([
            InlineKeyboardButton(
                text="◀️ Назад",
                callback_data="admin_main"
            )
        ])
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    @staticmethod
    def openai_settings_menu(is_configured: bool) -> InlineKeyboardMarkup:
        """Меню настроек OpenAI агента - ИЗМЕНЕНО: убрана логика включен/выключен"""
        agent_status = "✅ Создан" if is_configured else "❌ Не создан"
        
        keyboard = [
            [
                InlineKeyboardButton(
                    text=f"🎯 Агент: {agent_status}",
                    callback_data="openai_view" if is_configured else "openai_create"
                )
            ]
        ]
        
        if is_configured:
            keyboard.extend([
                [
                    InlineKeyboardButton(
                        text="🧪 Тестировать",
                        callback_data="openai_test"
                    ),
                    InlineKeyboardButton(
                        text="✏️ Редактировать",
                        callback_data="openai_edit"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="📊 Лимит сообщений",
                        callback_data="ai_message_limit"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🗑️ Удалить агента",
                        callback_data="openai_delete"
                    )
                ]
            ])
        else:
            keyboard.append([
                InlineKeyboardButton(
                    text="🎨 Создать агента",
                    callback_data="openai_create"
                )
            ])
        
        keyboard.append([
            InlineKeyboardButton(
                text="◀️ Назад",
                callback_data="admin_main"
            )
        ])
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    @staticmethod
    def conversation_menu() -> ReplyKeyboardMarkup:
        """Клавиатура для диалога с ИИ (reply кнопки)"""
        return ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🚪 Завершить диалог с ИИ")]],
            resize_keyboard=True,
            input_field_placeholder="Ваш вопрос для ИИ..."
        )
    
    @staticmethod
    def conversation_menu_with_inline() -> ReplyKeyboardMarkup:
        """НОВОЕ: Клавиатура для диалога с ИИ с inline кнопкой завершения"""
        # Пока оставляем reply кнопку как основную, inline добавляется в ai_handlers
        return AIKeyboards.conversation_menu()
    
    @staticmethod
    def conversation_inline_only() -> InlineKeyboardMarkup:
        """НОВОЕ: Только inline кнопка завершения диалога"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚪 Завершить диалог", callback_data="ai_exit_conversation")]
        ])


class UserKeyboards:
    """Клавиатуры для пользователей"""
    
    @staticmethod
    def welcome_button(button_text: str) -> ReplyKeyboardMarkup:
        """Кнопка приветствия"""
        return ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=button_text)]],
            resize_keyboard=True,
            one_time_keyboard=True,
            input_field_placeholder="Нажмите кнопку ниже..."
        )
    
    @staticmethod
    def ai_button() -> ReplyKeyboardMarkup:
        """Кнопка вызова ИИ"""
        return ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🤖 Позвать ИИ")]],
            resize_keyboard=True,
            one_time_keyboard=False,
            input_field_placeholder="Выберите действие..."
        )
    
    @staticmethod
    def goodbye_button(button_text: str, button_url: str) -> InlineKeyboardMarkup:
        """Inline кнопка прощания"""
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text=button_text,
                    url=button_url
                )]
            ]
        )
