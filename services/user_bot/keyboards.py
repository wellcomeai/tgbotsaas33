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
        """✅ ИСПРАВЛЕНО: Главное меню администратора с кнопкой массовых рассылок"""
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
                    text="📨 Массовые рассылки", 
                    callback_data="mass_broadcast_main"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔒 Проверка подписки", 
                    callback_data="admin_subscription"
                )
            ]
        ]
        
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
    
    # ===== SUBSCRIPTION SETTINGS KEYBOARDS =====
    
    @staticmethod
    def subscription_settings_menu(enabled: bool) -> InlineKeyboardMarkup:
        """✅ НОВОЕ: Меню настроек проверки подписки"""
        toggle_text = "❌ Выключить" if enabled else "✅ Включить"
        
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{toggle_text} проверку", callback_data="toggle_subscription")],
            [InlineKeyboardButton(text="📺 Настроить канал", callback_data="set_subscription_channel")],
            [InlineKeyboardButton(text="✏️ Изменить сообщение", callback_data="edit_subscription_message")],
            [InlineKeyboardButton(text=f"{Emoji.BACK} Главное меню", callback_data="admin_main")]
        ])
    
    @staticmethod
    def subscription_cancel() -> InlineKeyboardMarkup:
        """✅ НОВОЕ: Кнопка отмены настройки канала"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="admin_subscription")]
        ])
    
    @staticmethod
    def subscription_channel_configured() -> InlineKeyboardMarkup:
        """✅ НОВОЕ: Кнопки после настройки канала"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Включить проверку", callback_data="toggle_subscription")],
            [InlineKeyboardButton(text="⚙️ Настройки подписки", callback_data="admin_subscription")],
            [InlineKeyboardButton(text=f"{Emoji.BACK} Главное меню", callback_data="admin_main")]
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

    # ===== MASS BROADCAST KEYBOARDS =====

    @staticmethod
    def mass_broadcast_main_menu() -> InlineKeyboardMarkup:
        """Главное меню массовых рассылок - ОБНОВЛЕНО: убраны кнопки запланированных рассылок"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 Мгновенная рассылка", 
                    callback_data="mass_broadcast_instant"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Статистика рассылок", 
                    callback_data="mass_broadcast_stats"
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
    def mass_broadcast_creation_menu(broadcast_type: str, has_text: bool = False, has_media: bool = False, has_button: bool = False) -> InlineKeyboardMarkup:
        """Меню создания рассылки"""
        keyboard = []
        
        # Текст
        text_icon = "✅" if has_text else "📝"
        keyboard.append([
            InlineKeyboardButton(
                text=f"{text_icon} Текст рассылки",
                callback_data=f"mass_broadcast_{broadcast_type}_text"
            )
        ])
        
        # Медиа
        media_icon = "✅" if has_media else "📎"
        keyboard.append([
            InlineKeyboardButton(
                text=f"{media_icon} Медиа (опционально)",
                callback_data=f"mass_broadcast_{broadcast_type}_media"
            )
        ])
        
        # Кнопка
        button_icon = "✅" if has_button else "🔘"
        keyboard.append([
            InlineKeyboardButton(
                text=f"{button_icon} Inline кнопка (опционально)",
                callback_data=f"mass_broadcast_{broadcast_type}_button"
            )
        ])
        
        # Предпросмотр (только если есть текст)
        if has_text:
            keyboard.append([
                InlineKeyboardButton(
                    text="👁️ Предпросмотр",
                    callback_data=f"mass_broadcast_{broadcast_type}_preview"
                )
            ])
        
        # Кнопки действий
        if broadcast_type == "instant" and has_text:
            keyboard.append([
                InlineKeyboardButton(
                    text="🚀 Отправить сейчас",
                    callback_data=f"mass_broadcast_instant_send"
                )
            ])
        elif broadcast_type == "scheduled" and has_text:
            keyboard.append([
                InlineKeyboardButton(
                    text="⏰ Указать время отправки",
                    callback_data=f"mass_broadcast_scheduled_datetime"
                )
            ])
        
        # Отмена
        keyboard.append([
            InlineKeyboardButton(
                text="❌ Отменить",
                callback_data="mass_broadcast_main"
            )
        ])
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def mass_broadcast_preview_menu(broadcast_type: str, broadcast_id: int = None) -> InlineKeyboardMarkup:
        """Меню предпросмотра рассылки"""
        keyboard = []
        
        if broadcast_type == "instant":
            keyboard.append([
                InlineKeyboardButton(
                    text="🚀 Отправить сейчас",
                    callback_data=f"mass_broadcast_send_instant_{broadcast_id}" if broadcast_id else "mass_broadcast_instant_send"
                )
            ])
        elif broadcast_type == "scheduled":
            keyboard.append([
                InlineKeyboardButton(
                    text="⏰ Указать время отправки",
                    callback_data=f"mass_broadcast_scheduled_datetime"
                )
            ])
        
        keyboard.extend([
            [
                InlineKeyboardButton(
                    text="✏️ Редактировать",
                    callback_data=f"mass_broadcast_{broadcast_type}_edit"
                )
            ],
            [
                InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data="mass_broadcast_main"
                )
            ]
        ])
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def mass_broadcast_button_setup_menu(broadcast_type: str) -> InlineKeyboardMarkup:
        """Меню настройки кнопки"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑️ Убрать кнопку",
                    callback_data=f"mass_broadcast_{broadcast_type}_remove_button"
                )
            ],
            [
                InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data=f"mass_broadcast_{broadcast_type}_menu"
                )
            ]
        ])

    @staticmethod
    def mass_broadcast_media_setup_menu(broadcast_type: str) -> InlineKeyboardMarkup:
        """Меню настройки медиа"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑️ Убрать медиа",
                    callback_data=f"mass_broadcast_{broadcast_type}_remove_media"
                )
            ],
            [
                InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data=f"mass_broadcast_{broadcast_type}_menu"
                )
            ]
        ])

    @staticmethod
    def mass_broadcast_scheduled_list(broadcasts: list) -> InlineKeyboardMarkup:
        """Список запланированных рассылок"""
        keyboard = []
        
        for broadcast in broadcasts:
            scheduled_time = broadcast.scheduled_at.strftime("%d.%m %H:%M")
            preview = broadcast.get_preview_text(30)
            
            keyboard.append([
                InlineKeyboardButton(
                    text=f"{scheduled_time} - {preview}",
                    callback_data=f"mass_broadcast_scheduled_view_{broadcast.id}"
                )
            ])
        
        if not broadcasts:
            keyboard.append([
                InlineKeyboardButton(
                    text="📝 Нет запланированных рассылок",
                    callback_data="mass_broadcast_scheduled"
                )
            ])
        
        keyboard.append([
            InlineKeyboardButton(
                text="◀️ Назад",
                callback_data="mass_broadcast_main"
            )
        ])
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def mass_broadcast_scheduled_view_menu(broadcast_id: int) -> InlineKeyboardMarkup:
        """Меню просмотра запланированной рассылки"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑️ Отменить рассылку",
                    callback_data=f"mass_broadcast_cancel_{broadcast_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="◀️ К списку",
                    callback_data="mass_broadcast_list_scheduled"
                )
            ]
        ])

    @staticmethod
    def mass_broadcast_confirm_send(broadcast_id: int) -> InlineKeyboardMarkup:
        """Подтверждение отправки"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, отправить",
                    callback_data=f"mass_broadcast_confirm_send_{broadcast_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отменить",
                    callback_data=f"mass_broadcast_instant_preview_{broadcast_id}"
                )
            ]
        ])

    @staticmethod
    def mass_broadcast_stats_menu() -> InlineKeyboardMarkup:
        """Меню статистики рассылок"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Обновить",
                    callback_data="mass_broadcast_stats"
                )
            ],
            [
                InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data="mass_broadcast_main"
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
    def openai_settings_menu(has_agent: bool) -> InlineKeyboardMarkup:
        """✅ ИСПРАВЛЕНО: Меню настроек OpenAI агента"""
        if has_agent:
            keyboard = [
                [InlineKeyboardButton(text="🧪 Тестировать ИИ", callback_data="openai_test")],
                [InlineKeyboardButton(text="✏️ Редактировать", callback_data="openai_edit")],
                [InlineKeyboardButton(text="🗑️ Удалить агента", callback_data="openai_delete")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
            ]
        else:
            keyboard = [
                [InlineKeyboardButton(text="🎨 Создать агента", callback_data="openai_create")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
            ]
        
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
