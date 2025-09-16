"""
Files Manager Mixin для OpenAI Handler
Содержит логику управления файлами и Vector Stores для OpenAI агентов
Включает загрузку, управление, диагностику и очистку файлов
✅ ИСПРАВЛЕНО: Восстановлена оригинальная логика сохранения Vector Store
"""

import structlog
from datetime import datetime
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from ...states import AISettingsStates

logger = structlog.get_logger()


class FilesManagerMixin:
    """Миксин для управления файлами и Vector Stores"""

    # ===== УПРАВЛЕНИЕ ФАЙЛАМИ И VECTOR STORES =====

    async def handle_upload_files(self, callback: CallbackQuery, is_owner_check):
        """✅ ИЗМЕНЕНИЕ 7: Управление загрузкой файлов для file_search с улучшенной кнопкой"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Получаем информацию о текущих vector stores
            from services.openai_assistant import openai_client
            
            success, vector_stores = await openai_client.list_vector_stores()
            
            # Ищем vector store для этого бота
            bot_vector_store = None
            vector_store_name = f"Bot_{self.bot_id}_Knowledge"
            
            if success:
                for store in vector_stores:
                    if store['name'] == vector_store_name:
                        bot_vector_store = store
                        break
            
            files_info = ""
            if bot_vector_store:
                # ✅ ИСПРАВЛЕНО: Безопасное извлечение данных из file_counts объекта
                file_counts = bot_vector_store.get('file_counts', {})
                
                # Используем безопасный метод извлечения file_counts
                total_files, processed_files = self._safe_extract_file_counts(file_counts)
                
                files_info = f"\n\n📊 <b>Текущая база знаний:</b>\n• Всего файлов: {total_files}\n• Обработано: {processed_files}"
                
                logger.info("📊 Vector store file counts", 
                           vector_store_id=bot_vector_store.get('id', 'unknown'),
                           total_files=total_files,
                           processed_files=processed_files)
            
            text = f"""
📁 <b>База знаний агента</b>

<b>🔍 File Search - поиск по документам</b>

Загрузите документы для создания базы знаний вашего агента. Поддерживаемые форматы:
- PDF документы
- Word файлы (.docx)
- Текстовые файлы (.txt)
- Markdown файлы (.md)

<b>Как это работает:</b>
1. Вы загружаете документы
2. OpenAI автоматически обрабатывает и индексирует их
3. Агент получает возможность искать информацию в документах
4. Пользователи могут задавать вопросы по содержимому файлов{files_info}

<b>Лимиты:</b>
- Максимум 512 МБ на файл  
- До 10,000 файлов в базе знаний
- Стоимость: $0.10/ГБ/день + $2.50 за 1000 запросов
"""
            
            keyboard_buttons = []
            
            # Кнопка загрузки файлов
            keyboard_buttons.append([
                InlineKeyboardButton(text="📤 Загрузить документы", callback_data="openai_start_upload")
            ])
            
            # ✅ ИЗМЕНЕНИЕ 7: Кнопка "Мои файлы" если есть загруженные файлы
            openai_settings = self.ai_assistant_settings.get('openai_settings', {})
            uploaded_files = openai_settings.get('uploaded_files', [])

            if bot_vector_store or uploaded_files:
                files_text = f"📁 Мои файлы ({len(uploaded_files)})" if uploaded_files else "📋 Управление файлами"
                keyboard_buttons.append([
                    InlineKeyboardButton(text=files_text, callback_data="openai_manage_files")
                ])
            
            keyboard_buttons.append([
                InlineKeyboardButton(text="◀️ Назад", callback_data="admin_main")
            ])
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
            logger.info("✅ Upload files menu displayed successfully", 
                       bot_id=self.bot_id,
                       has_existing_store=bool(bot_vector_store))
            
        except Exception as e:
            logger.error("💥 Error showing upload files menu", 
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True)
            await callback.answer("Ошибка при загрузке меню", show_alert=True)

    async def handle_start_upload(self, callback: CallbackQuery, state: FSMContext, is_owner_check):
        """Начало процесса загрузки файлов"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        await state.set_state(AISettingsStates.admin_uploading_documents)
        await state.update_data(uploaded_files=[])
        
        text = """
📤 <b>Загрузка документов</b>

Отправьте документы которые должны стать частью базы знаний агента.

<b>Поддерживаемые форматы:</b>
- PDF (.pdf)
- Word (.docx)  
- Текст (.txt)
- Markdown (.md)

<b>Инструкции:</b>
1. Отправьте файлы один за другим в этот чат
2. После загрузки всех файлов нажмите "✅ Завершить"
3. Система автоматически обработает документы

<b>Отправьте первый файл:</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Завершить загрузку", callback_data="openai_finish_upload")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="openai_upload_files")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)

    async def handle_document_upload(self, message: Message, state: FSMContext, is_owner_check):
        """✅ ИЗМЕНЕНИЕ 6: Обработка загруженного документа с улучшенной батчевой загрузкой"""
        if not is_owner_check(message.from_user.id):
            return
        
        if not message.document:
            await message.answer("❌ Пожалуйста, отправьте документ как файл")
            return
        
        document = message.document
        
        # Проверяем формат файла
        allowed_extensions = ['.pdf', '.docx', '.txt', '.md']
        file_extension = None
        
        if document.file_name:
            file_extension = '.' + document.file_name.split('.')[-1].lower()
        
        if not file_extension or file_extension not in allowed_extensions:
            await message.answer(f"❌ Неподдерживаемый формат файла. Поддерживаются: {', '.join(allowed_extensions)}")
            return
        
        # Проверяем размер файла (максимум 512 МБ)
        max_size = 512 * 1024 * 1024  # 512 МБ в байтах
        if document.file_size > max_size:
            await message.answer(f"❌ Файл слишком большой. Максимальный размер: 512 МБ")
            return
        
        try:
            progress_msg = await message.answer(f"🔄 Обрабатываю файл: {document.file_name}")
            
            # Скачиваем файл
            bot = message.bot
            file_info = await bot.get_file(document.file_id)
            
            import tempfile
            import os
            
            # Создаем временный файл
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
                temp_file_path = temp_file.name
            
            # Скачиваем файл от Telegram
            await bot.download_file(file_info.file_path, temp_file_path)
            
            # Загружаем в OpenAI
            from services.openai_assistant import openai_client
            
            success, file_data = await openai_client.upload_file_to_openai(
                temp_file_path, 
                document.file_name
            )
            
            # Удаляем временный файл
            try:
                os.unlink(temp_file_path)
            except:
                pass
            
            if success:
                # Сохраняем информацию о загруженном файле
                data = await state.get_data()
                uploaded_files = data.get('uploaded_files', [])
                
                uploaded_files.append({
                    'file_id': file_data['id'],
                    'filename': file_data['filename'],
                    'size': file_data['bytes']
                })
                
                await state.update_data(uploaded_files=uploaded_files)
                
                file_size_mb = round(file_data['bytes'] / (1024 * 1024), 2)
                
                # ✅ ИЗМЕНЕНИЕ 6: Улучшенная батчевая загрузка с показом общего размера
                await progress_msg.edit_text(
                    f"✅ Файл загружен: {document.file_name} ({file_size_mb} МБ)\n\n"
                    f"📊 Загружено файлов: {len(uploaded_files)}\n"
                    f"💾 Общий размер: {sum(f['size']/(1024*1024) for f in uploaded_files):.1f} МБ\n\n"
                    f"🔄 <b>Батчевая загрузка активна!</b>\n"
                    f"Отправьте еще файлы или нажмите \"✅ Завершить загрузку\"",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="✅ Завершить загрузку", callback_data="openai_finish_upload")],
                        [InlineKeyboardButton(text="❌ Отмена", callback_data="openai_upload_files")]
                    ])
                )
                
            else:
                error_msg = file_data.get('error', 'Неизвестная ошибка')
                await progress_msg.edit_text(f"❌ Ошибка загрузки файла: {error_msg}")
            
        except Exception as e:
            logger.error("💥 Error uploading document", error=str(e))
            await message.answer("❌ Произошла ошибка при загрузке файла")

    async def handle_finish_upload(self, callback: CallbackQuery, state: FSMContext, is_owner_check):
        """✅ ИЗМЕНЕНИЕ 1: Завершение загрузки с сохранением информации о файлах"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            data = await state.get_data()
            uploaded_files = data.get('uploaded_files', [])
            
            if not uploaded_files:
                await callback.answer("❌ Нет загруженных файлов", show_alert=True)
                return
            
            progress_msg = await callback.message.edit_text("🔄 Создаю базу знаний...")
            
            from services.openai_assistant import openai_client
            
            # Создаем или получаем vector store
            vector_store_name = f"Bot_{self.bot_id}_Knowledge"
            
            # Сначала проверяем, есть ли уже vector store
            success, vector_stores = await openai_client.list_vector_stores()
            existing_store = None
            
            if success:
                for store in vector_stores:
                    if store['name'] == vector_store_name:
                        existing_store = store
                        break
            
            if existing_store:
                # Используем существующий vector store
                vector_store_id = existing_store['id']
                logger.info("📁 Using existing vector store", vector_store_id=vector_store_id)
            else:
                # Создаем новый vector store
                success, store_data = await openai_client.create_vector_store(vector_store_name)
                
                if not success:
                    await progress_msg.edit_text(f"❌ Ошибка создания базы знаний: {store_data.get('error')}")
                    return
                
                vector_store_id = store_data['id']
                logger.info("✅ Created new vector store", vector_store_id=vector_store_id)
            
            # Добавляем файлы в vector store
            file_ids = [f['file_id'] for f in uploaded_files]
            
            success, result = await openai_client.add_files_to_vector_store(vector_store_id, file_ids)
            
            if success:
                # ✅ ИЗМЕНЕНИЕ 1: Сохраняем полную информацию о файлах в БД
                files_info = []
                for file_data in uploaded_files:
                    files_info.append({
                        "filename": file_data['filename'],
                        "openai_file_id": file_data['file_id'],
                        "uploaded_at": datetime.now().isoformat(),
                        "size_bytes": file_data['size'],
                        "size_mb": round(file_data['size'] / (1024 * 1024), 2)
                    })
                
                # Сохраняем vector store И информацию о файлах
                save_success = await self._save_vector_store_and_files(vector_store_id, files_info)
                
                if not save_success:
                    await progress_msg.edit_text(
                        "❌ Файлы загружены в OpenAI, но не удалось привязать к агенту. "
                        "Обратитесь к администратору."
                    )
                    return
                
                total_files = len(uploaded_files)
                total_size = sum(f['size'] for f in uploaded_files)
                total_size_mb = round(total_size / (1024 * 1024), 2)
                
                success_text = f"""
✅ <b>База знаний создана и привязана к агенту!</b>

📊 <b>Статистика:</b>
- Файлов загружено: {total_files}
- Общий размер: {total_size_mb} МБ
- Vector Store ID: {vector_store_id[:15]}...

🧰 <b>File Search включен и настроен!</b>
Ваш агент теперь может искать информацию в загруженных документах.

<b>Список файлов:</b>
"""
                
                for i, file_info in enumerate(uploaded_files, 1):
                    filename = file_info['filename']
                    size_mb = round(file_info['size'] / (1024 * 1024), 2)
                    success_text += f"{i}. {filename} ({size_mb} МБ)\n"
                
                await progress_msg.edit_text(
                    success_text,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🧪 Тестировать агента", callback_data="openai_test")],
                        [InlineKeyboardButton(text="📁 К базе знаний", callback_data="openai_upload_files")]
                    ])
                )
                
            else:
                error_msg = result.get('error', 'Неизвестная ошибка')
                await progress_msg.edit_text(f"❌ Ошибка добавления файлов в базу знаний: {error_msg}")
            
            await state.clear()
            
        except Exception as e:
            logger.error("💥 Error finishing upload", error=str(e), exc_info=True)
            await callback.message.edit_text("❌ Произошла ошибка при создании базы знаний")
            await state.clear()

    async def _save_vector_store_and_files(self, vector_store_id: str, files_info: list) -> bool:
        """✅ ИЗМЕНЕНИЕ 2: НОВЫЙ метод объединенного сохранения vector store + информация о файлах для меню"""
        try:
            logger.info("💾 Saving vector store with files info", 
                       vector_store_id=vector_store_id,
                       files_count=len(files_info),
                       bot_id=self.bot_id)
            
            # 1. Сохраняем vector store (как раньше)
            from database.managers.ai_manager import AIManager
            success = await AIManager.save_vector_store_ids(self.bot_id, [vector_store_id])
            
            if not success:
                logger.error("❌ Failed to save vector store")
                return False
            
            # 2. НОВОЕ: Сохраняем информацию о файлах в openai_settings
            settings = self.ai_assistant_settings.copy()
            openai_settings = settings.get('openai_settings', {})
            
            # Добавляем файлы к существующим (не перезаписываем)
            existing_files = openai_settings.get('uploaded_files', [])
            existing_files.extend(files_info)
            openai_settings['uploaded_files'] = existing_files
            openai_settings['files_last_updated'] = datetime.now().isoformat()
            
            settings['openai_settings'] = openai_settings
            
            # Обновляем в БД
            await self.db.update_ai_assistant(self.bot_id, settings=settings)
            
            # Обновляем локальное состояние
            self.ai_assistant_settings = settings
            
            logger.info("✅ Vector store and files info saved", 
                       total_files=len(existing_files),
                       new_files=len(files_info))
            
            return True
            
        except Exception as e:
            logger.error("💥 Failed to save vector store and files", 
                        error=str(e), exc_info=True)
            return False

    async def _save_and_enable_vector_store(self, vector_store_id: str) -> bool:
        """✅ ИСПРАВЛЕНО: Объединенное сохранение vector store ID и включение file_search"""
        try:
            logger.info("💾 Saving vector store and enabling file_search", 
                       vector_store_id=vector_store_id,
                       bot_id=self.bot_id)
            
            # ✅ ИСПОЛЬЗУЕМ СПЕЦИАЛИЗИРОВАННЫЙ МЕТОД ИЗ AI MANAGER
            from database.managers.ai_manager import AIManager
            
            # Сохраняем vector store IDs через правильный метод
            success = await AIManager.save_vector_store_ids(self.bot_id, [vector_store_id])
            
            if not success:
                logger.error("❌ Failed to save vector store via AIManager")
                return False
            
            logger.info("✅ Vector store saved via AIManager")
            
            # ✅ ПРИНУДИТЕЛЬНАЯ СИНХРОНИЗАЦИЯ ПОСЛЕ СОХРАНЕНИЯ
            sync_success = await self._sync_with_db_state(force=True)
            if sync_success:
                logger.info("✅ State synchronized after vector store save")
            else:
                logger.warning("⚠️ Failed to sync state after vector store save")
            
            # ✅ ДИАГНОСТИКА: Проверяем что сохранилось
            await self._diagnose_vector_store_save(vector_store_id)
            
            return True
            
        except Exception as e:
            logger.error("💥 Failed to save and enable vector store", 
                        vector_store_id=vector_store_id,
                        bot_id=self.bot_id,
                        error=str(e),
                        exc_info=True)
            return False

    async def _diagnose_vector_store_save(self, expected_vector_store_id: str):
        """🩺 Диагностика сохранения vector store"""
        try:
            logger.info("🩺 Diagnosing vector store save", 
                       expected_id=expected_vector_store_id)
            
            # 1. Проверяем локальное состояние
            local_openai_settings = self.ai_assistant_settings.get('openai_settings', {})
            local_vector_ids = local_openai_settings.get('vector_store_ids', [])
            local_file_search = local_openai_settings.get('enable_file_search', False)
            
            logger.info("📊 Local state check", 
                       local_vector_ids=local_vector_ids,
                       local_file_search=local_file_search,
                       expected_found_locally=expected_vector_store_id in local_vector_ids)
            
            # 2. Проверяем БД состояние через AIManager
            from database.managers.ai_manager import AIManager
            vector_info = await AIManager.get_vector_store_info(self.bot_id)
            
            db_vector_ids = vector_info.get('vector_store_ids', [])
            db_file_search = vector_info.get('file_search_enabled', False)
            
            logger.info("📊 Database state check", 
                       db_vector_ids=db_vector_ids,
                       db_file_search=db_file_search,
                       expected_found_in_db=expected_vector_store_id in db_vector_ids)
            
            # 3. Проверяем через прямой запрос к БД
            fresh_bot = await self.db.get_bot_by_id(self.bot_id, fresh=True)
            if fresh_bot and fresh_bot.openai_settings:
                raw_settings = fresh_bot.openai_settings
                raw_vector_ids = raw_settings.get('vector_store_ids', [])
                raw_file_search = raw_settings.get('enable_file_search', False)
                
                logger.info("📊 Raw database check", 
                           raw_vector_ids=raw_vector_ids,
                           raw_file_search=raw_file_search,
                           expected_found_raw=expected_vector_store_id in raw_vector_ids)
            else:
                logger.warning("⚠️ Could not get raw database state")
            
            # 4. Итоговая диагностика
            if expected_vector_store_id in db_vector_ids and db_file_search:
                logger.info("✅ DIAGNOSIS SUCCESS: Vector store properly saved and configured")
                return True
            else:
                logger.error("❌ DIAGNOSIS FAILED: Vector store not properly saved", 
                           expected_id=expected_vector_store_id,
                           found_in_db=expected_vector_store_id in db_vector_ids,
                           file_search_enabled=db_file_search)
                return False
                
        except Exception as e:
            logger.error("💥 Vector store diagnosis failed", error=str(e))
            return False

    async def handle_manage_files(self, callback: CallbackQuery, is_owner_check):
        """✅ ИЗМЕНЕНИЕ 3: Показ реальных загруженных файлов"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Получаем информацию о файлах из настроек
            openai_settings = self.ai_assistant_settings.get('openai_settings', {})
            uploaded_files = openai_settings.get('uploaded_files', [])
            vector_store_ids = openai_settings.get('vector_store_ids', [])
            
            logger.info("📁 Showing uploaded files", 
                       files_count=len(uploaded_files),
                       vector_stores=len(vector_store_ids))
            
            if not uploaded_files:
                # Нет файлов
                text = """
📁 <b>Мои файлы</b>

📋 <b>База знаний пуста</b>

Вы еще не загружали файлы для создания базы знаний.
Загрузите документы чтобы агент мог отвечать на вопросы по ним.
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📤 Загрузить файлы", callback_data="openai_start_upload")],
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="openai_upload_files")]
                ])
            else:
                # Есть файлы - показываем список
                text = f"""
📁 <b>Мои файлы ({len(uploaded_files)})</b>

📊 <b>Статистика:</b>
- Всего файлов: {len(uploaded_files)}
- Vector Stores: {len(vector_store_ids)}

📋 <b>Список файлов:</b>
"""
                
                total_size_mb = 0
                for i, file_info in enumerate(uploaded_files, 1):
                    filename = file_info.get('filename', 'Неизвестный файл')
                    size_mb = file_info.get('size_mb', 0)
                    uploaded_date = file_info.get('uploaded_at', '')
                    
                    # Форматируем дату
                    try:
                        if uploaded_date:
                            from datetime import datetime
                            date_obj = datetime.fromisoformat(uploaded_date.replace('Z', '+00:00'))
                            date_str = date_obj.strftime('%d.%m.%Y %H:%M')
                        else:
                            date_str = 'Неизвестно'
                    except:
                        date_str = 'Неизвестно'
                    
                    text += f"{i}. <b>{filename}</b>\n"
                    text += f"   📊 {size_mb} МБ • 📅 {date_str}\n\n"
                    total_size_mb += size_mb
                
                text += f"💾 <b>Общий размер:</b> {total_size_mb:.1f} МБ"
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📤 Добавить файлы", callback_data="openai_start_upload")],
                    [InlineKeyboardButton(text="🗑️ Удалить базу знаний", callback_data="openai_clear_knowledge")],
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="openai_upload_files")]
                ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error("💥 Error showing files", error=str(e), exc_info=True)
            await callback.answer("Ошибка при загрузке списка файлов", show_alert=True)

    async def handle_clear_knowledge(self, callback: CallbackQuery, is_owner_check):
        """Очистка базы знаний"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        text = """
🗑️ <b>Очистка базы знаний</b>

⚠️ <b>Внимание!</b> Будут удалены все загруженные документы и векторное хранилище.

Это действие необратимо. Продолжить?
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, очистить", callback_data="openai_confirm_clear_knowledge")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="openai_manage_files")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)

    async def handle_verify_file_search(self, callback: CallbackQuery, is_owner_check):
        """✅ НОВЫЙ: Проверка настроек file search"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            # Принудительная синхронизация
            await self._sync_with_db_state(force=True)
            
            # Получаем информацию о vector stores через AIManager
            from database.managers.ai_manager import AIManager
            vector_info = await AIManager.get_vector_store_info(self.bot_id)
            
            vector_store_ids = vector_info.get('vector_store_ids', [])
            file_search_enabled = vector_info.get('file_search_enabled', False)
            vector_stores_count = vector_info.get('vector_stores_count', 0)
            last_updated = vector_info.get('last_updated', 'Неизвестно')
            
            # Проверяем локальное состояние
            local_settings = self.ai_assistant_settings.get('openai_settings', {})
            local_vector_ids = local_settings.get('vector_store_ids', [])
            local_file_search = local_settings.get('enable_file_search', False)
            
            status_icon = "✅" if file_search_enabled and vector_store_ids else "❌"
            sync_icon = "✅" if local_vector_ids == vector_store_ids else "⚠️"
            
            text = f"""
🔍 <b>Проверка настроек File Search</b>

{status_icon} <b>Статус:</b> {'Настроено' if file_search_enabled else 'Не настроено'}

📊 <b>База данных:</b>
• Vector Store IDs: {len(vector_store_ids)}
• File Search: {'Включен' if file_search_enabled else 'Выключен'}
• Последнее обновление: {last_updated}

🔄 <b>Локальное состояние:</b>
• Vector Store IDs: {len(local_vector_ids)} 
• File Search: {'Включен' if local_file_search else 'Выключен'}
• Синхронизация: {sync_icon}

<b>Список Vector Store IDs:</b>
"""
            
            for i, vs_id in enumerate(vector_store_ids, 1):
                text += f"{i}. {vs_id}\n"
                
            if not vector_store_ids:
                text += "Нет настроенных vector stores\n"
                
            text += f"\n<b>Рекомендации:</b>\n"
            
            if not file_search_enabled:
                text += "• Включите File Search в настройках инструментов\n"
            if not vector_store_ids:
                text += "• Загрузите файлы для создания базы знаний\n"
            if local_vector_ids != vector_store_ids:
                text += "• Требуется синхронизация локального состояния\n"
            
            if file_search_enabled and vector_store_ids and local_vector_ids == vector_store_ids:
                text += "✅ Все настроено корректно!"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Принудительная синхронизация", 
                                    callback_data="openai_force_sync_vectors")],
                [InlineKeyboardButton(text="📤 Загрузить еще файлы", 
                                    callback_data="openai_start_upload")],
                [InlineKeyboardButton(text="◀️ Назад к инструментам", 
                                    callback_data="openai_tools_settings")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error("💥 Error verifying file search", error=str(e))
            await callback.answer("Ошибка при проверке настроек", show_alert=True)

    async def handle_force_sync_vectors(self, callback: CallbackQuery, is_owner_check):
        """✅ НОВЫЙ: Принудительная синхронизация vector stores"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            progress_msg = await callback.message.edit_text("🔄 Принудительная синхронизация...")
            
            # Принудительно синхронизируем с БД
            sync_success = await self._sync_with_db_state(force=True)
            
            if sync_success:
                # Получаем актуальную информацию о vector stores
                from database.managers.ai_manager import AIManager
                vector_info = await AIManager.get_vector_store_info(self.bot_id)
                
                vector_store_ids = vector_info.get('vector_store_ids', [])
                
                await progress_msg.edit_text(
                    f"""✅ <b>Синхронизация выполнена!</b>

📊 Найдено vector stores: {len(vector_store_ids)}
🔄 Локальное состояние обновлено
✅ Агент готов к работе с файлами""",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                         [InlineKeyboardButton(text="🧪 Тестировать агента", 
                                            callback_data="openai_test")]
                    ])
                )
            else:
                await progress_msg.edit_text(
                    "❌ Ошибка синхронизации. Обратитесь к администратору.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="◀️ Назад", 
                                            callback_data="openai_verify_file_search")]
                    ])
                )
            
        except Exception as e:
            logger.error("💥 Error in force sync vectors", error=str(e))
            await callback.answer("Ошибка синхронизации", show_alert=True)

    async def handle_confirm_clear_knowledge(self, callback: CallbackQuery, is_owner_check):
        """✅ ИСПРАВЛЕНО: Подтверждение очистки базы знаний с сохранением vector store"""
        await callback.answer()
        
        if not is_owner_check(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        try:
            progress_msg = await callback.message.edit_text("🔄 Очищаю базу знаний...")
            
            # Получаем информацию о файлах перед очисткой
            openai_settings = self.ai_assistant_settings.get('openai_settings', {})
            
            # ✅ ИСПРАВЛЕНО: Очищаем файлы но СОХРАНЯЕМ vector store
            clear_success = await self._clear_vector_store_files_only()
            
            if clear_success:
                # Синхронизируем локальное состояние
                await self._sync_with_db_state(force=True)
                
                await progress_msg.edit_text(
                    f"""✅ <b>База знаний очищена!</b>

🧹 Очищено файлов: {len(openai_settings.get('uploaded_files', []))}
📁 Файлы удалены из OpenAI Files
🔄 Vector Store готов к новым загрузкам
💡 При следующей загрузке файлы добавятся в тот же Vector Store

Можете загрузить новые файлы.""",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📤 Загрузить новые файлы", 
                                            callback_data="openai_start_upload")],
                        [InlineKeyboardButton(text="📁 К базе знаний", 
                                            callback_data="openai_upload_files")]
                    ])
                )
            else:
                await progress_msg.edit_text("❌ Ошибка при очистке базы знаний")
                
        except Exception as e:
            logger.error("💥 Error clearing knowledge base", error=str(e))
            await callback.message.edit_text("❌ Произошла ошибка при очистке")

    # ===== ✅ ВОССТАНОВЛЕННЫЕ МЕТОДЫ ИЗ ОРИГИНАЛА =====

    async def _clear_vector_store_files_only(self) -> bool:
        """✅ ВОССТАНОВЛЕНО: Очистка файлов но СОХРАНЕНИЕ vector store для повторного использования"""
        try:
            logger.info("🧹 Clearing vector store files (keeping store)", bot_id=self.bot_id)
            
            # Получаем информацию о файлах и vector stores
            openai_settings = self.ai_assistant_settings.get('openai_settings', {})
            uploaded_files = openai_settings.get('uploaded_files', [])
            vector_store_ids = openai_settings.get('vector_store_ids', [])
            
            if not vector_store_ids:
                logger.info("ℹ️ No vector stores to clear", bot_id=self.bot_id)
                # Все равно очищаем uploaded_files на всякий случай
                return await self._clear_uploaded_files_info()
            
            from services.openai_assistant import openai_client
            
            # У нас всегда один vector store на бота
            vector_store_id = vector_store_ids[0]
            
            logger.info("🔍 Processing vector store", 
                       vector_store_id=vector_store_id,
                       files_to_process=len(uploaded_files))
            
            # 1. ✅ ОЧИЩАЕМ файлы из vector store (НЕ удаляем сам store!)
            clear_success = False
            try:
                clear_success = await openai_client.clear_vector_store_files(vector_store_id)
                if clear_success:
                    logger.info("✅ Vector store files cleared successfully", 
                               vector_store_id=vector_store_id)
                else:
                    logger.warning("⚠️ Vector store files clearing returned False", 
                                  vector_store_id=vector_store_id)
            except Exception as e:
                logger.error("💥 Error clearing vector store files", 
                            vector_store_id=vector_store_id, error=str(e))
            
            # 2. ✅ УДАЛЯЕМ файлы из OpenAI Files storage (чтобы не платить за хранение)
            deleted_files = 0
            for file_info in uploaded_files:
                openai_file_id = file_info.get('openai_file_id')
                filename = file_info.get('filename', 'unknown')
                
                if openai_file_id:
                    try:
                        success, message = await openai_client.delete_file(openai_file_id)
                        if success:
                            deleted_files += 1
                            logger.info("✅ File deleted from OpenAI Files", 
                                       file_id=openai_file_id,
                                       filename=filename)
                        else:
                            logger.warning("⚠️ Failed to delete file from OpenAI Files", 
                                         file_id=openai_file_id, 
                                         filename=filename,
                                         error=message)
                    except Exception as e:
                        logger.error("💥 Error deleting file from OpenAI Files", 
                                   file_id=openai_file_id, 
                                   filename=filename,
                                   error=str(e))
            
            # 3. ✅ ОЧИЩАЕМ информацию о файлах в БД (НО СОХРАНЯЕМ vector_store_ids!)
            files_clear_success = await self._clear_uploaded_files_info()
            
            overall_success = (clear_success or len(uploaded_files) == 0) and files_clear_success
            
            logger.info("🎯 Vector store clearing completed", 
                       bot_id=self.bot_id,
                       vector_store_cleared=clear_success,
                       files_deleted_from_openai=deleted_files,
                       files_info_cleared=files_clear_success,
                       overall_success=overall_success,
                       vector_store_preserved=True)  # ✅ Store остается!
            
            return overall_success
            
        except Exception as e:
            logger.error("💥 Failed to clear vector store files", 
                        bot_id=self.bot_id,
                        error=str(e),
                        exc_info=True)
            return False

    async def _clear_uploaded_files_info(self) -> bool:
        """✅ ВОССТАНОВЛЕНО: Очистка ТОЛЬКО информации о файлах в БД (vector stores остаются!)"""
        try:
            # Получаем настройки
            settings = self.ai_assistant_settings.copy()
            openai_settings = settings.get('openai_settings', {})
            
            # Сохраняем количество файлов для логирования
            files_count = len(openai_settings.get('uploaded_files', []))
            
            # ✅ КРИТИЧНО: Очищаем ТОЛЬКО uploaded_files, НЕ ТРОГАЕМ vector_store_ids!
            openai_settings['uploaded_files'] = []
            openai_settings['files_cleared_at'] = datetime.now().isoformat()
            # vector_store_ids ОСТАЕТСЯ как был!
            
            settings['openai_settings'] = openai_settings
            
            # Сохраняем в БД
            await self.db.update_ai_assistant(self.bot_id, settings=settings)
            
            # Обновляем локальное состояние
            self.ai_assistant_settings = settings
            
            logger.info("✅ Files info cleared from DB (vector stores preserved)", 
                       bot_id=self.bot_id,
                       cleared_files_count=files_count,
                       vector_stores_kept=len(settings.get('openai_settings', {}).get('vector_store_ids', [])))
            
            return True
            
        except Exception as e:
            logger.error("💥 Failed to clear uploaded files info", 
                        bot_id=self.bot_id, error=str(e))
            return False

    # ===== ДОПОЛНИТЕЛЬНЫЙ МЕТОД ДЛЯ ПОЛНОЙ ОЧИСТКИ =====

    async def _clear_vector_stores_completely(self) -> bool:
        """✅ ДОПОЛНИТЕЛЬНЫЙ: Полная очистка vector stores + информации о файлах (для особых случаев)"""
        try:
            logger.info("🗑️ Complete vector stores clearing", bot_id=self.bot_id)
            
            # Получаем vector store IDs для удаления
            from database.managers.ai_manager import AIManager
            vector_info = await AIManager.get_vector_store_info(self.bot_id)
            vector_store_ids = vector_info.get('vector_store_ids', [])
            
            if vector_store_ids:
                from services.openai_assistant import openai_client
                
                # Удаляем vector stores из OpenAI
                for vs_id in vector_store_ids:
                    try:
                        success, message = await openai_client.delete_vector_store(vs_id)
                        if success:
                            logger.info("✅ Vector store deleted", vector_store_id=vs_id)
                        else:
                            logger.warning("⚠️ Failed to delete vector store", 
                                         vector_store_id=vs_id, error=message)
                    except Exception as e:
                        logger.error("💥 Error deleting vector store", 
                                   vector_store_id=vs_id, error=str(e))
                
                # Очищаем из БД И удаляем информацию о файлах
                clear_success = await AIManager.clear_vector_stores(self.bot_id)
                
                if clear_success:
                    # Очищаем информацию о файлах в settings
                    settings = self.ai_assistant_settings.copy()
                    openai_settings = settings.get('openai_settings', {})
                    
                    files_count = len(openai_settings.get('uploaded_files', []))
                    openai_settings['uploaded_files'] = []
                    openai_settings['files_cleared_at'] = datetime.now().isoformat()
                    
                    settings['openai_settings'] = openai_settings
                    
                    await self.db.update_ai_assistant(self.bot_id, settings=settings)
                    self.ai_assistant_settings = settings
                    
                    logger.info("✅ Vector stores and files completely cleared", 
                               cleared_files_count=files_count)
                    
                    return True
            
            return False
            
        except Exception as e:
            logger.error("💥 Failed to clear vector stores completely", 
                        error=str(e), exc_info=True)
            return False

    # ===== ОБРАТНАЯ СОВМЕСТИМОСТЬ =====

    async def _clear_vector_stores_and_files(self) -> bool:
        """✅ ОБРАТНАЯ СОВМЕСТИМОСТЬ: Алиас для полной очистки (старый метод)"""
        logger.warning("⚠️ Using deprecated _clear_vector_stores_and_files, consider using _clear_vector_store_files_only for better UX")
        return await self._clear_vector_stores_completely()
