"""
Voice Handlers для обработки голосовых сообщений
Интеграция с Whisper для транскрипции голоса в текст + передача в ИИ агенты
✅ ИНТЕГРАЦИЯ: Полная совместимость с существующей системой ИИ
✅ FSM ПОДДЕРЖКА: Работа со всеми состояниями диалогов
✅ АРХИТЕКТУРА: Следует паттернам проекта
"""

import structlog
from typing import Optional
from aiogram import Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from services.whisper_service import whisper_service, WhisperServiceError
from ..states import AISettingsStates

logger = structlog.get_logger()


def register_voice_handlers(dp: Dispatcher, **kwargs):
    """
    Регистрация обработчиков голосовых сообщений
    ✅ ПРИОРИТЕТ: Регистрируется ПЕРЕД ai_handlers для перехвата голоса
    """
    
    logger = structlog.get_logger()
    logger.info("🎤 Registering voice handlers with Whisper integration")
    
    db = kwargs['db']
    bot_config = kwargs['bot_config']
    user_bot = kwargs.get('user_bot')
    
    logger.info("🎤 Voice handler registration parameters", 
               bot_id=bot_config.get('bot_id', 'unknown'),
               has_db=bool(db),
               has_user_bot=bool(user_bot),
               whisper_available=whisper_service.is_available())
    
    try:
        # Создаем обработчик
        handler = VoiceHandler(db, bot_config, user_bot)
        
        # ===== ОСНОВНОЙ ОБРАБОТЧИК ГОЛОСОВЫХ СООБЩЕНИЙ =====
        
        # 🎤 Голосовые сообщения (высший приоритет для перехвата)
        dp.message.register(
            handler.handle_voice_message,
            F.voice,  # ✅ ТОЛЬКО голосовые сообщения
            F.chat.type == "private"  # Только в приватных чатах
        )
        
        logger.info("✅ Voice handlers registered successfully", 
                   bot_id=bot_config['bot_id'],
                   total_handlers=1,
                   whisper_integration=True,
                   ai_integration=True)
        
    except Exception as e:
        logger.error("💥 Failed to register voice handlers", 
                    bot_id=kwargs.get('bot_config', {}).get('bot_id', 'unknown'),
                    error=str(e), exc_info=True)
        raise


class VoiceHandler:
    """Обработчик голосовых сообщений с интеграцией Whisper + ИИ агенты"""
    
    def __init__(self, db, bot_config: dict, user_bot):
        self.db = db
        self.bot_config = bot_config
        self.bot_id = bot_config['bot_id']
        self.owner_user_id = bot_config['owner_user_id']
        self.bot_username = bot_config['bot_username']
        self.user_bot = user_bot
        self.logger = structlog.get_logger()
        
        self.logger.info("🎤 VoiceHandler initialized with AI integration", 
                        bot_id=self.bot_id,
                        bot_username=self.bot_username,
                        owner_user_id=self.owner_user_id,
                        whisper_available=whisper_service.is_available())
    
    def _is_owner(self, user_id: int) -> bool:
        """Проверка владельца бота"""
        is_owner = user_id == self.owner_user_id
        self.logger.debug("👤 Owner check for voice", 
                         bot_id=self.bot_id,
                         user_id=user_id,
                         owner_user_id=self.owner_user_id,
                         is_owner=is_owner)
        return is_owner
    
    async def handle_voice_message(self, message: Message, state: FSMContext):
        """
        🎤 ГЛАВНЫЙ ОБРАБОТЧИК голосовых сообщений
        Транскрибирует голос → передает в соответствующий ИИ обработчик
        """
        user_id = message.from_user.id
        voice_file_id = message.voice.file_id
        voice_duration = message.voice.duration
        
        self.logger.info("🎤 Voice message received", 
                        user_id=user_id,
                        bot_id=self.bot_id,
                        voice_duration=voice_duration,
                        file_id=voice_file_id,
                        is_owner=self._is_owner(user_id))
        
        # Проверяем доступность Whisper
        if not whisper_service.is_available():
            self.logger.warning("🎤 Whisper service unavailable", 
                              bot_id=self.bot_id,
                              user_id=user_id)
            await message.answer(
                "🎤 <b>Голосовые сообщения временно недоступны</b>\n\n"
                "Whisper API не настроен. Отправьте текстовое сообщение."
            )
            return
        
        # Проверяем длительность (ограничиваем разумными пределами)
        if voice_duration > 300:  # 5 минут
            await message.answer(
                "🎤 <b>Голосовое сообщение слишком длинное</b>\n\n"
                f"Максимальная длительность: 5 минут\n"
                f"Ваше сообщение: {voice_duration // 60}:{voice_duration % 60:02d}\n\n"
                "Отправьте более короткое сообщение или разбейте на части."
            )
            return
        
        # Показываем индикатор обработки
        processing_msg = await message.answer(
            f"🎤 <b>Обрабатываю голосовое сообщение...</b>\n\n"
            f"⏱️ Длительность: {voice_duration}с\n"
            f"🤖 Транскрибирую через Whisper...\n\n"
            f"<i>Это может занять 5-15 секунд</i>"
        )
        
        try:
            # Транскрибируем голосовое сообщение
            transcription_result = await whisper_service.transcribe_voice_message(
                bot=message.bot,
                file_id=voice_file_id,
                language="ru"  # Русский по умолчанию
            )
            
            # Удаляем сообщение о процессе
            try:
                await processing_msg.delete()
            except:
                pass
            
            if not transcription_result['success']:
                # Ошибка транскрипции
                error_message = transcription_result.get('error', 'Неизвестная ошибка')
                
                await message.answer(
                    f"🎤 <b>Ошибка распознавания голоса</b>\n\n"
                    f"<b>Причина:</b> {error_message}\n\n"
                    f"💡 <b>Попробуйте:</b>\n"
                    f"• Говорить четче и громче\n"
                    f"• Уменьшить фоновый шум\n"
                    f"• Отправить текстовое сообщение"
                )
                
                self.logger.error("🎤 Voice transcription failed", 
                                bot_id=self.bot_id,
                                user_id=user_id,
                                error=error_message,
                                voice_duration=voice_duration)
                return
            
            transcribed_text = transcription_result['transcription']
            
            if not transcribed_text or len(transcribed_text.strip()) < 2:
                await message.answer(
                    "🎤 <b>Не удалось распознать речь</b>\n\n"
                    "Голосовое сообщение слишком тихое или неразборчивое.\n"
                    "Попробуйте записать заново или отправить текст."
                )
                return
            
            # ✅ КЛЮЧЕВОЙ МОМЕНТ: Подменяем текст в сообщении
            original_text = message.text
            message.text = transcribed_text.strip()
            
            self.logger.info("🎤 ✅ Voice transcribed successfully", 
                           bot_id=self.bot_id,
                           user_id=user_id,
                           voice_duration=voice_duration,
                           transcription_length=len(transcribed_text),
                           transcription_time=transcription_result['timing']['total_time'])
            
            # Показываем результат транскрипции пользователю
            await message.answer(
                f"🎤 <b>Распознано:</b>\n\n"
                f"<i>«{transcribed_text}»</i>\n\n"
                f"⏱️ Время обработки: {transcription_result['timing']['total_time']}с\n"
                f"🤖 Отправляю ИИ агенту..."
            )
            
            # ===== ИНТЕГРАЦИЯ С СУЩЕСТВУЮЩЕЙ СИСТЕМОЙ ИИ =====
            
            # Получаем текущее FSM состояние для определения куда передать
            current_state = await state.get_state()
            
            # Импортируем ИИ обработчик для делегирования
            from .ai_handlers import AIHandler
            
            ai_handler = AIHandler(
                db=self.db,
                bot_config=self.bot_config,
                user_bot=self.user_bot
            )
            
            # Определяем тип обработки в зависимости от состояния и пользователя
            if current_state == AISettingsStates.admin_in_ai_conversation:
                # Админ в режиме тестирования ИИ
                self.logger.info("🎤 → 🤖 Delegating to ADMIN AI conversation", 
                               user_id=user_id, bot_id=self.bot_id)
                await ai_handler.handle_admin_ai_conversation(message, state)
                
            elif current_state == AISettingsStates.user_in_ai_conversation:
                # Пользователь в диалоге с ИИ
                self.logger.info("🎤 → 🤖 Delegating to USER AI conversation", 
                               user_id=user_id, bot_id=self.bot_id)
                await ai_handler.handle_user_ai_conversation(message, state)
                
            elif self._is_owner(user_id):
                # Владелец бота вне диалога - может захотеть админские команды
                self.logger.info("🎤 → 🤖 Delegating to OWNER (no active conversation)", 
                               user_id=user_id, bot_id=self.bot_id)
                
                # Отправляем как обычное сообщение (может сработать admin команды)
                await message.answer(
                    f"🎤 ➡️ 📝 <b>Голос преобразован в текст</b>\n\n"
                    f"Если нужно обратиться к ИИ агенту - используйте админ панель."
                )
                
            else:
                # Обычный пользователь вне диалога - предлагаем начать диалог
                self.logger.info("🎤 → 🤖 User outside conversation, offering to start", 
                               user_id=user_id, bot_id=self.bot_id)
                
                # Проверяем есть ли ИИ агент у бота
                try:
                    fresh_ai_config = await self.db.get_ai_config(self.bot_id)
                    has_ai_agent = bool(fresh_ai_config and fresh_ai_config.get('enabled'))
                    
                    if has_ai_agent:
                        keyboard = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="🤖 Обратиться к ИИ агенту", callback_data="start_ai_conversation")]
                        ])
                        
                        await message.answer(
                            f"🎤 ➡️ 📝 <b>Голос преобразован в текст:</b>\n\n"
                            f"<i>«{transcribed_text}»</i>\n\n"
                            f"Хотите обратиться с этим вопросом к ИИ агенту?",
                            reply_markup=keyboard
                        )
                    else:
                        await message.answer(
                            f"🎤 ➡️ 📝 <b>Голос преобразован в текст:</b>\n\n"
                            f"<i>«{transcribed_text}»</i>\n\n"
                            f"ИИ агент не настроен для этого бота."
                        )
                        
                except Exception as db_error:
                    self.logger.error("Error checking AI config", error=str(db_error))
                    await message.answer(
                        f"🎤 ➡️ 📝 <b>Голос преобразован в текст:</b>\n\n"
                        f"<i>«{transcribed_text}»</i>"
                    )
            
            # Восстанавливаем оригинальный текст сообщения (хотя это и не обязательно)
            message.text = original_text
            
        except WhisperServiceError as e:
            # Whisper-специфичные ошибки
            try:
                await processing_msg.delete()
            except:
                pass
            
            await message.answer(
                f"🎤 <b>Ошибка Whisper сервиса</b>\n\n"
                f"<b>Причина:</b> {str(e)}\n\n"
                f"Попробуйте отправить текстовое сообщение."
            )
            
            self.logger.error("🎤 Whisper service error", 
                            bot_id=self.bot_id,
                            user_id=user_id,
                            error=str(e))
            
        except Exception as e:
            # Общие ошибки
            try:
                await processing_msg.delete()
            except:
                pass
            
            await message.answer(
                f"🎤 <b>Неожиданная ошибка при обработке голоса</b>\n\n"
                f"Попробуйте еще раз или отправьте текстовое сообщение."
            )
            
            self.logger.error("🎤 Unexpected voice processing error", 
                            bot_id=self.bot_id,
                            user_id=user_id,
                            error=str(e),
                            error_type=type(e).__name__,
                            exc_info=True)


# ===== ДОПОЛНИТЕЛЬНЫЕ CALLBACK ОБРАБОТЧИКИ =====

async def handle_start_ai_conversation_callback(callback_query, **kwargs):
    """
    Callback для кнопки "Обратиться к ИИ агенту" после транскрипции
    Можно зарегистрировать отдельно если нужно
    """
    # Эта функция может быть зарегистрирована отдельно в ai_handlers.py
    # или здесь, если потребуется специальная логика для голосовых сообщений
    pass
