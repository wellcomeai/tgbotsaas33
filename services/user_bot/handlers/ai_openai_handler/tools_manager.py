"""
Tools Manager Mixin для OpenAI Handler
Содержит логику управления встроенными инструментами OpenAI Responses API
(веб-поиск, интерпретатор кода, поиск по файлам, генерация изображений)
"""

import structlog
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

logger = structlog.get_logger()


class ToolsManagerMixin:
    """Миксин для управления встроенными инструментами OpenAI"""

    # ===== УПРАВЛЕНИЕ ИНСТРУМЕНТАМИ =====
    
    async def handle_tools_settings(self, callback: CallbackQuery, is_owner_check):
        """Настройка встроенных инструментов Responses API"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Получаем текущие настройки инструментов
            settings = self.ai_assistant_settings.get('openai_settings', {})
            
            web_search = "✅" if settings.get('enable_web_search') else "❌"
            code_interpreter = "✅" if settings.get('enable_code_interpreter') else "❌"
            file_search = "✅" if settings.get('enable_file_search') else "❌"
            
            vector_stores_count = len(settings.get('vector_store_ids', []))
            file_search_info = f" ({vector_stores_count} хранилищ)" if vector_stores_count > 0 else ""
            
            text = f"""
🧰 <b>Встроенные инструменты Responses API</b>

<b>Текущие настройки:</b>
🌐 Веб-поиск: {web_search}
🐍 Интерпретатор кода: {code_interpreter}
📁 Поиск по файлам: {file_search}{file_search_info}

<b>Описание инструментов:</b>

🌐 <b>Веб-поиск</b>
- Поиск актуальной информации в интернете
- Автоматические цитаты и ссылки
- Стоимость: $25-50 за 1000 запросов

🐍 <b>Интерпретатор кода</b>
- Выполнение Python кода
- Анализ данных и построение графиков
- Математические вычисления

📁 <b>Поиск по файлам</b>
- Поиск в загруженных документах
- RAG на основе векторных хранилищ
- Стоимость: $2.50 за 1000 запросов
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🌐 Веб-поиск {web_search}", 
                                    callback_data="openai_toggle_web_search")],
                [InlineKeyboardButton(text=f"🐍 Код {code_interpreter}", 
                                    callback_data="openai_toggle_code_interpreter")],
                [InlineKeyboardButton(text=f"📁 Файлы {file_search}", 
                                    callback_data="openai_toggle_file_search")],
                [InlineKeyboardButton(text="🔧 Загрузить файлы", 
                                    callback_data="openai_upload_files")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_ai")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error("💥 Error showing tools settings", error=str(e))
            await callback.answer("Ошибка при загрузке настроек", show_alert=True)

    async def handle_toggle_web_search(self, callback: CallbackQuery, is_owner_check):
        """Переключение веб-поиска"""
        await self._toggle_openai_tool(callback, 'web_search', 'Веб-поиск', is_owner_check)

    async def handle_toggle_code_interpreter(self, callback: CallbackQuery, is_owner_check):
        """Переключение интерпретатора кода"""
        await self._toggle_openai_tool(callback, 'code_interpreter', 'Интерпретатор кода', is_owner_check)

    async def handle_toggle_file_search(self, callback: CallbackQuery, is_owner_check):
        """Переключение поиска по файлам"""
        await self._toggle_openai_tool(callback, 'file_search', 'Поиск по файлам', is_owner_check)

    async def _toggle_openai_tool(self, callback: CallbackQuery, tool_name: str, tool_display_name: str, is_owner_check):
        """Переключение встроенного инструмента"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Получаем текущие настройки
            settings = self.ai_assistant_settings.copy()
            openai_settings = settings.get('openai_settings', {})
            
            # Переключаем инструмент
            setting_key = f'enable_{tool_name}'
            current_value = openai_settings.get(setting_key, False)
            openai_settings[setting_key] = not current_value
            
            settings['openai_settings'] = openai_settings
            
            # Сохраняем в БД
            await self.db.update_ai_assistant(
                self.bot_id,
                settings=settings
            )
            
            # Обновляем локальные настройки
            self.ai_assistant_settings = settings
            
            status = "включен" if not current_value else "выключен"
            await callback.answer(f"{tool_display_name} {status}")
            
            logger.info("🔧 Tool toggled", 
                       tool_name=tool_name,
                       new_status=not current_value,
                       bot_id=self.bot_id)
            
            # Обновляем меню
            await self.handle_tools_settings(callback, is_owner_check)
            
        except Exception as e:
            logger.error("💥 Error toggling tool", tool=tool_name, error=str(e))
            await callback.answer("Ошибка при изменении настройки", show_alert=True)
