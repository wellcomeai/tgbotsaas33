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
    def main_menu() -> InlineKeyboardMarkup:
        """Главное меню администратора"""
        return InlineKeyboardMarkup(inline_keyboard=[
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
                    text="📊 Статистика", 
                    callback_data="admin_stats"
                )
            ]
        ])
    
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
        """Меню настроек ИИ"""
        ai_status = "✅ Включен" if ai_enabled else "❌ Выключен"
        ai_id_status = "✅ Настроен" if is_configured else "❌ Не настроен"
        
        # Platform info
        platform_info = ""
        if platform:
            platform_names = {
                'chatforyou': 'ChatForYou',
                'protalk': 'ProTalk'
            }
            platform_info = f" ({platform_names.get(platform, platform)})"
        
        limit_status = f"✅ {daily_limit}/день" if daily_limit else "♾️ Безлимит"
        
        keyboard = [
            [
                InlineKeyboardButton(
                    text=f"🤖 ИИ Агент: {ai_status}",
                    callback_data="ai_toggle"
                )
            ]
        ]
        
        if ai_enabled:
            keyboard.extend([
                [
                    InlineKeyboardButton(
                        text=f"🔑 Настройка: {ai_id_status}{platform_info}",
                        callback_data="ai_set_id"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=f"📊 Лимит сообщений: {limit_status}",
                        callback_data="ai_set_limit"
                    )
                ]
            ])
            
            # Test button only if fully configured
            if is_configured:
                keyboard.append([
                    InlineKeyboardButton(
                        text="🧪 Тестировать ИИ",
                        callback_data="ai_test"
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
        """Клавиатура для диалога с ИИ"""
        return ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🚪 Завершить диалог с ИИ")]],
            resize_keyboard=True,
            input_field_placeholder="Ваш вопрос для ИИ..."
        )


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
