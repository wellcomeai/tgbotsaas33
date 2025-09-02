"""
Agent Editor Mixin для OpenAI Handler
Содержит логику редактирования и удаления существующих OpenAI агентов
"""

import structlog
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from ...states import AISettingsStates

logger = structlog.get_logger()


class AgentEditorMixin:
    """Миксин для редактирования OpenAI агентов"""

    # ===== РЕДАКТИРОВАНИЕ АГЕНТА =====

    async def handle_edit_agent(self, callback: CallbackQuery, is_owner_check):
        """✅ ДОБАВИТЬ: Показ меню редактирования агента"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            agent_name = self.ai_assistant_settings.get('agent_name', 'AI Ассистент')
            agent_role = self.ai_assistant_settings.get('agent_role', 'Полезный помощник')
            system_prompt = self.ai_assistant_settings.get('system_prompt', '')
            
            text = f"""
✏️ <b>Редактирование агента "{agent_name}"</b>

<b>Текущие настройки:</b>
📝 <b>Имя:</b> {agent_name}
🎭 <b>Роль:</b> {agent_role}
📋 <b>Системный промпт:</b> {system_prompt[:100]}{'...' if len(system_prompt) > 100 else ''}

<b>Что хотите изменить?</b>

⚠️ <b>Внимание:</b> При изменении промпта агент будет пересоздан в OpenAI с новыми настройками.
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✏️ Изменить имя", callback_data="openai_edit_name")],
                [InlineKeyboardButton(text="🎭 Изменить роль и промпт", callback_data="openai_edit_prompt")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_ai")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error("💥 Error showing edit menu", error=str(e))
            await callback.answer("Ошибка при загрузке меню редактирования", show_alert=True)

    async def handle_edit_name(self, callback: CallbackQuery, state: FSMContext):
        """✅ ДОБАВИТЬ: Начало редактирования имени"""
        await callback.answer()
        await state.set_state(AISettingsStates.admin_editing_agent_name)
        
        current_name = self.ai_assistant_settings.get('agent_name', 'AI Ассистент')
        
        text = f"""
✏️ <b>Изменение имени агента</b>

<b>Текущее имя:</b> {current_name}

Введите новое имя для вашего агента:
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="openai_edit")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)

    async def handle_edit_prompt(self, callback: CallbackQuery, state: FSMContext):
        """✅ ДОБАВИТЬ: Начало редактирования промпта"""
        await callback.answer()
        await state.set_state(AISettingsStates.admin_editing_agent_prompt)
        
        current_role = self.ai_assistant_settings.get('agent_role', 'Полезный помощник')
        
        text = f"""
🎭 <b>Изменение роли и промпта агента</b>

<b>Текущая роль:</b> {current_role}

Введите новое описание роли и инструкции для агента:

<b>Примеры:</b>
- "Ты эксперт по фитнесу. Отвечай дружелюбно, давай практичные советы."
- "Ты консультант по продажам. Помогай клиентам выбрать товар."

⚠️ <b>Внимание:</b> После изменения агент будет пересоздан в OpenAI.
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="openai_edit")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)

    async def handle_name_edit_input(self, message: Message, state: FSMContext, is_owner_check):
        """✅ ИСПРАВЛЕНО: Обработка ввода нового имени с проверкой голосовых"""
        if not is_owner_check(message.from_user.id):
            return
        
        # ✅ ИСПРАВЛЕНО: Проверяем наличие текста в сообщении
        if not self._is_text_message(message):
            await message.answer("❌ Пожалуйста, отправьте текстовое сообщение с новым именем агента.")
            return
        
        message_text = message.text.strip()
        
        if message_text == "/cancel":
            await self._cancel_and_show_edit(message, state)
            return
        
        new_name = message_text
        
        if len(new_name) < 2 or len(new_name) > 100:
            await message.answer("❌ Имя должно быть от 2 до 100 символов. Попробуйте еще раз:")
            return
        
        try:
            # Обновляем только имя (без пересоздания агента)
            current_settings = self.ai_assistant_settings.copy()
            current_settings['agent_name'] = new_name
            
            await self.db.update_ai_assistant(
                self.bot_id,
                settings=current_settings
            )
            
            self.ai_assistant_settings = current_settings
            
            await message.answer(
                f"✅ Имя агента изменено на: {new_name}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✏️ Продолжить редактирование", callback_data="openai_edit")],
                    [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
                ])
            )
            
            await state.clear()
            
        except Exception as e:
            logger.error("💥 Error updating agent name", error=str(e))
            await message.answer("❌ Ошибка при обновлении имени")

    async def handle_prompt_edit_input(self, message: Message, state: FSMContext, is_owner_check):
        """✅ ИСПРАВЛЕНО: Обработка ввода нового промпта с пересозданием агента + проверка голосовых"""
        if not is_owner_check(message.from_user.id):
            return
        
        # ✅ ИСПРАВЛЕНО: Проверяем наличие текста в сообщении
        if not self._is_text_message(message):
            await message.answer("❌ Пожалуйста, отправьте текстовое сообщение с новой ролью агента.")
            return
        
        message_text = message.text.strip()
        
        if message_text == "/cancel":
            await self._cancel_and_show_edit(message, state)
            return
        
        new_role = message_text
        
        if len(new_role) < 10 or len(new_role) > 1000:
            await message.answer("❌ Описание роли должно быть от 10 до 1000 символов. Попробуйте еще раз:")
            return
        
        try:
            progress_message = await message.answer("🔄 Пересоздаем агента с новым промптом...")
            
            # Получаем текущие данные
            agent_name = self.ai_assistant_settings.get('agent_name', 'AI Ассистент')
            old_assistant_id = self.ai_assistant_id
            
            # Пересоздаем агента
            success, response_data = await self._recreate_agent_with_new_prompt(
                agent_name, new_role, old_assistant_id
            )
            
            if success:
                new_assistant_id = response_data.get('assistant_id')
                
                await progress_message.edit_text(
                    f"""✅ <b>Агент успешно обновлен!</b>

<b>Имя:</b> {agent_name}
<b>Новая роль:</b> {new_role[:100]}{'...' if len(new_role) > 100 else ''}
<b>Новый ID:</b> {new_assistant_id[:15]}...

Агент пересоздан в OpenAI с новыми настройками!""",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🧪 Тестировать", callback_data="openai_test")],
                        [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
                    ])
                )
            else:
                error_msg = response_data.get('error', 'Неизвестная ошибка')
                await progress_message.edit_text(
                    f"❌ Ошибка при пересоздании агента: {error_msg}",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="openai_edit_prompt")],
                        [InlineKeyboardButton(text="🤖 К настройкам ИИ", callback_data="admin_ai")]
                    ])
                )
            
            await state.clear()
            
        except Exception as e:
            logger.error("💥 Error updating agent prompt", error=str(e))
            await message.answer("❌ Ошибка при обновлении промпта")

    async def _recreate_agent_with_new_prompt(self, name: str, role: str, old_assistant_id: str) -> tuple[bool, dict]:
        """✅ ДОБАВИТЬ: Пересоздание агента с новым промптом"""
        try:
            # 1. Удаляем старого агента из OpenAI
            if old_assistant_id:
                try:
                    from services.openai_assistant import openai_client
                    await openai_client.delete_assistant(old_assistant_id)
                    logger.info("✅ Old agent deleted from OpenAI")
                except Exception as e:
                    logger.warning("⚠️ Could not delete old agent", error=str(e))
            
            # 2. Создаем нового агента
            success, response_data = await self._create_agent_in_openai(name, role)
            
            if success:
                new_assistant_id = response_data.get('assistant_id')
                
                # 3. Синхронизируем состояние
                await self._sync_with_db_state(force=True)
                
                # 4. Обновляем другие компоненты
                await self._safe_update_user_bot(
                    ai_assistant_id=new_assistant_id,
                    ai_assistant_settings=self.ai_assistant_settings
                )
                await self._safe_update_bot_manager(
                    ai_assistant_id=new_assistant_id,
                    ai_assistant_settings=self.ai_assistant_settings
                )
                
                logger.info("✅ Agent recreated successfully", 
                           old_id=old_assistant_id,
                           new_id=new_assistant_id)
                
                return True, response_data
            
            return False, response_data
            
        except Exception as e:
            logger.error("💥 Error recreating agent", error=str(e))
            return False, {"error": str(e)}

    async def _cancel_and_show_edit(self, message: Message, state: FSMContext):
        """✅ ДОБАВИТЬ: Отмена редактирования"""
        await state.clear()
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ К редактированию", callback_data="openai_edit")]
        ])
        await message.answer("Редактирование отменено", reply_markup=keyboard)

    # ===== УДАЛЕНИЕ АГЕНТА =====
    
    async def _delete_openai_agent(self, callback: CallbackQuery):
        """✅ УПРОЩЕННОЕ: Показ подтверждения удаления"""
        logger.info("🗑️ Showing OpenAI agent deletion confirmation", 
                   bot_id=self.bot_id)
        
        agent_name = self.ai_assistant_settings.get('agent_name', 'ИИ агента')
        
        text = f"""
🗑️ <b>Удаление "{agent_name}"</b>

⚠️ <b>Внимание!</b> Агент будет удален из системы.
Все настройки будут потеряны.

Вы уверены?
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data="openai_confirm_delete")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_ai")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)

    async def handle_confirm_delete(self, callback: CallbackQuery, is_owner_check):
        """✅ УПРОЩЕННОЕ: Удаление - возврат в главное меню"""
        
        logger.info("🗑️ Simple OpenAI agent deletion", 
                   user_id=callback.from_user.id,
                   bot_id=self.bot_id)
        
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            agent_name = self.ai_assistant_settings.get('agent_name', 'агента')
            await callback.message.edit_text("🔄 Удаляем агента...")
            
            # Просто очищаем конфигурацию из БД
            await self.db.clear_ai_configuration(self.bot_id)
            
            # Локально тоже очищаем для синхронности
            self.ai_assistant_id = None
            self.ai_assistant_settings = {'agent_type': 'none'}
            
            # ✅ ИСПРАВЛЕНО: Возврат в правильное главное меню (admin_main)
            text = f"""
✅ <b>OpenAI агент "{agent_name}" удален!</b>

Конфигурация очищена из базы данных.
Возвращаемся в главное меню.
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_main")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
            logger.info("✅ OpenAI agent deleted successfully (simple method)")
            
        except Exception as e:
            logger.error("💥 Error in simple deletion", error=str(e))
            await callback.answer("Ошибка при удалении", show_alert=True)

    # ===== СИНХРОНИЗАЦИЯ ДАННЫХ =====
    
    async def handle_sync_agent_data(self, callback: CallbackQuery, is_owner_check):
        """Ручная синхронизация данных агента"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            logger.info("🔄 Manual agent data sync requested", bot_id=self.bot_id)
            
            # Синхронизируем данные
            success = await self.db.sync_agent_data_fields(bot_id=self.bot_id)
            
            if success:
                # Проверяем результат
                validation = await self.db.validate_agent_data_consistency(self.bot_id)
                
                status = validation.get('overall_status', 'unknown')
                if status == 'consistent':
                    await callback.answer("✅ Данные агента синхронизированы")
                else:
                    recommendations = validation.get('recommendations', [])
                    await callback.answer(f"⚠️ Найдены проблемы: {', '.join(recommendations)}")
            else:
                await callback.answer("❌ Ошибка синхронизации", show_alert=True)
                
        except Exception as e:
            logger.error("💥 Error in manual sync", error=str(e))
            await callback.answer("❌ Ошибка синхронизации", show_alert=True)
