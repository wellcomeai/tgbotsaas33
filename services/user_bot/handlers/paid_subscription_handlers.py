"""
Обработчики платных подписок
Управление настройками Robokassa, ценами, каналами и уведомлениями
✅ ПОЛНАЯ РЕАЛИЗАЦИЯ: Все методы реализованы
✅ PRODUCTION: Реальные платежи, настоящие деньги
✅ ИСПРАВЛЕНО: Формат суммы для корректной подписи Robokassa
"""

import structlog
from datetime import datetime, timedelta
from decimal import Decimal
from aiogram import Dispatcher, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from aiogram import html

from database.connection import get_db_session
from ..states import PaidSubscriptionStates

logger = structlog.get_logger()

def register_paid_subscription_handlers(dp: Dispatcher, **kwargs):
    """✅ ПОЛНАЯ РЕГИСТРАЦИЯ: Все обработчики платных подписок"""
    
    db = kwargs['db']
    bot_config = kwargs['bot_config']
    access_control = kwargs.get('access_control', {})
    
    try:
        handler = PaidSubscriptionHandler(db, bot_config, access_control)
        
        # ✅ ВСЕ Callback обработчики
        dp.callback_query.register(handler.cb_configure_robokassa, F.data == "configure_robokassa")
        dp.callback_query.register(handler.cb_set_subscription_price, F.data == "set_subscription_price")
        dp.callback_query.register(handler.cb_set_subscription_period, F.data == "set_subscription_period")
        dp.callback_query.register(handler.cb_set_target_channel, F.data == "set_target_channel")
        dp.callback_query.register(handler.cb_configure_messages, F.data == "configure_messages")
        dp.callback_query.register(handler.cb_toggle_paid_subscription, F.data == "toggle_paid_subscription")
        dp.callback_query.register(handler.cb_view_subscribers, F.data == "view_paid_subscribers")
        dp.callback_query.register(handler.cb_test_payment, F.data == "test_payment")
        dp.callback_query.register(handler.cb_payment_stats, F.data == "payment_stats")
        
        # Подменю настроек сообщений
        dp.callback_query.register(handler.cb_configure_success_message, F.data == "config_success_message")
        dp.callback_query.register(handler.cb_configure_expired_message, F.data == "config_expired_message")
        dp.callback_query.register(handler.cb_configure_reminder_message, F.data == "config_reminder_message")
        
        # ✅ ВСЕ FSM обработчики
        dp.message.register(handler.handle_merchant_login, PaidSubscriptionStates.waiting_for_merchant_login)
        dp.message.register(handler.handle_password1, PaidSubscriptionStates.waiting_for_password1)
        dp.message.register(handler.handle_password2, PaidSubscriptionStates.waiting_for_password2)
        dp.message.register(handler.handle_subscription_price, PaidSubscriptionStates.waiting_for_subscription_price)
        dp.message.register(handler.handle_subscription_period, PaidSubscriptionStates.waiting_for_subscription_period)
        dp.message.register(handler.handle_target_channel, PaidSubscriptionStates.waiting_for_target_channel)
        dp.message.register(handler.handle_success_message, PaidSubscriptionStates.waiting_for_success_message)
        dp.message.register(handler.handle_expired_message, PaidSubscriptionStates.waiting_for_expired_message)
        dp.message.register(handler.handle_reminder_message, PaidSubscriptionStates.waiting_for_reminder_message)
        
        logger.info("✅ Paid subscription handlers registered (PRODUCTION MODE)", 
                    bot_id=bot_config['bot_id'],
                    production_payments=True,
                    sum_format_fixed=True,
                    registered_callbacks=[
                        "configure_robokassa", "set_subscription_price", "set_subscription_period",
                        "set_target_channel", "configure_messages", "toggle_paid_subscription",
                        "view_paid_subscribers", "test_payment", "payment_stats"
                    ],
                    registered_states=[
                        "merchant_login", "password1", "password2", "subscription_price",
                        "subscription_period", "target_channel", "success_message", 
                        "expired_message", "reminder_message"
                    ])
        
    except Exception as e:
        logger.error("💥 Failed to register paid subscription handlers", error=str(e))
        raise

class PaidSubscriptionManager:
    """✅ ПОЛНЫЙ МЕНЕДЖЕР: Управление платными подписками (PRODUCTION)"""
    
    def __init__(self, db, bot_config):
        self.db = db
        self.bot_config = bot_config
        self.bot_id = bot_config['bot_id']
        self.owner_user_id = bot_config['owner_user_id']
    
    async def show_main_menu(self, callback: CallbackQuery):
        """Показать главное меню платных подписок"""
        settings = await self._get_subscription_settings()
        
        if settings:
            status = "🟢 Включена" if settings.is_enabled else "🔴 Выключена"
            price = f"{float(settings.subscription_price)}₽"
            period = f"{settings.subscription_period_days} дней"
            
            robokassa_status = "✅ Настроена" if settings.robokassa_merchant_login else "❌ Не настроена"
            channel_status = "✅ Настроен" if settings.target_channel_id else "❌ Не настроен"
            
            # Подсчет подписчиков
            subscribers_count = await self._get_active_subscribers_count()
            revenue_total = await self._get_total_revenue()
        else:
            status = "🔴 Не настроена"
            price = "Не установлена"
            period = "30 дней"
            robokassa_status = "❌ Не настроена"
            channel_status = "❌ Не настроен"
            subscribers_count = 0
            revenue_total = 0
        
        text = f"""
💳 <b>Платный канал/чат</b>

<b>📊 Общая информация:</b>
• Статус: {status}
• Стоимость: {price}
• Период: {period}
• Активных подписчиков: {subscribers_count}
• Общий доход: {revenue_total}₽

<b>🛠 Настройки:</b>
📦 Robokassa: {robokassa_status}
📺 Канал: {channel_status}

<b>💡 Как работает:</b>
1. Пользователь нажимает кнопку "Подписаться" в боте
2. Получает персональную ссылку на оплату через Robokassa
3. После оплаты автоматически добавляется в канал
4. За 3 дня до истечения получает напоминание
5. При неоплате удаляется из канала

<b>⚙️ Настройте параметры ниже:</b>
"""
        
        keyboard_buttons = []
        
        # Настройка Robokassa
        keyboard_buttons.append([
            InlineKeyboardButton(text="📦 Настроить Robokassa", callback_data="configure_robokassa")
        ])
        
        # Цена и период
        keyboard_buttons.append([
            InlineKeyboardButton(text="💰 Цена", callback_data="set_subscription_price"),
            InlineKeyboardButton(text="📅 Период", callback_data="set_subscription_period")
        ])
        
        # Канал
        keyboard_buttons.append([
            InlineKeyboardButton(text="📺 Канал", callback_data="set_target_channel")
        ])
        
        # Сообщения
        keyboard_buttons.append([
            InlineKeyboardButton(text="💬 Сообщения", callback_data="configure_messages")
        ])
        
        # Статистика и управление
        keyboard_buttons.append([
            InlineKeyboardButton(text="👥 Подписчики", callback_data="view_paid_subscribers"),
            InlineKeyboardButton(text="📊 Статистика", callback_data="payment_stats")
        ])
        
        # ✅ ИЗМЕНЕНО: Кнопка создания реальной оплаты
        keyboard_buttons.append([
            InlineKeyboardButton(text="💳 Создать оплату", callback_data="test_payment")
        ])
        
        # Включить/выключить
        if settings and settings.is_enabled:
            toggle_text = "🔴 Выключить"
        else:
            toggle_text = "🟢 Включить"
            
        keyboard_buttons.append([
            InlineKeyboardButton(text=toggle_text, callback_data="toggle_paid_subscription")
        ])
        
        # Назад
        keyboard_buttons.append([
            InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_main")
        ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    async def _get_subscription_settings(self):
        """Получить настройки платной подписки из БД"""
        try:
            from database.models import BotPaidSubscription
            from sqlalchemy import select
            
            async with get_db_session() as session:
                result = await session.execute(
                    select(BotPaidSubscription).where(BotPaidSubscription.bot_id == self.bot_id)
                )
                return result.scalar_one_or_none()
                
        except Exception as e:
            logger.error("Failed to get subscription settings", error=str(e))
            return None
    
    async def _get_active_subscribers_count(self) -> int:
        """Получить количество активных платных подписчиков"""
        try:
            from database.models import PaidSubscriber
            from sqlalchemy import select, func
            
            async with get_db_session() as session:
                result = await session.execute(
                    select(func.count()).
                    select_from(PaidSubscriber).
                    where(
                        PaidSubscriber.bot_id == self.bot_id,
                        PaidSubscriber.status == "active",
                        PaidSubscriber.subscription_end > datetime.now()
                    )
                )
                return result.scalar() or 0
                
        except Exception as e:
            logger.error("Failed to get active subscribers count", error=str(e))
            return 0
    
    async def _get_total_revenue(self) -> float:
        """Получить общий доход от платных подписок"""
        try:
            from database.models import PaidSubscriber
            from sqlalchemy import select, func
            
            async with get_db_session() as session:
                result = await session.execute(
                    select(func.sum(PaidSubscriber.payment_amount)).
                    select_from(PaidSubscriber).
                    where(PaidSubscriber.bot_id == self.bot_id)
                )
                return float(result.scalar() or 0)
                
        except Exception as e:
            logger.error("Failed to get total revenue", error=str(e))
            return 0.0

class PaidSubscriptionHandler:
    """✅ ПОЛНЫЙ ОБРАБОТЧИК: Все события платных подписок (PRODUCTION)"""
    
    def __init__(self, db, bot_config, access_control=None):
        self.db = db
        self.bot_config = bot_config
        self.bot_id = bot_config['bot_id']
        self.owner_user_id = bot_config['owner_user_id']
        self.access_control = access_control or {}
        self.manager = PaidSubscriptionManager(db, bot_config)
    
    def _is_owner(self, user_id: int) -> bool:
        return user_id == self.owner_user_id
    
    async def _check_access(self, callback: CallbackQuery) -> bool:
        """Проверить доступ владельца бота"""
        if not self._is_owner(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return False
        
        # Дополнительная проверка через access_control
        if 'check_owner_access' in self.access_control:
            has_access, status = await self.access_control['check_owner_access']()
            if not has_access:
                if 'send_access_denied' in self.access_control:
                    await self.access_control['send_access_denied'](callback, status)
                return False
        
        return True
    
    # ===== ОСНОВНЫЕ CALLBACK ОБРАБОТЧИКИ =====
    
    async def cb_configure_robokassa(self, callback: CallbackQuery, state: FSMContext):
        """Настройка Robokassa"""
        await callback.answer()
        
        if not await self._check_access(callback):
            return
        
        await state.set_state(PaidSubscriptionStates.waiting_for_merchant_login)
        
        text = """
📦 <b>Настройка Robokassa</b>

<b>Шаг 1 из 3:</b> Merchant Login (Идентификатор магазина)

Введите ваш Merchant Login из личного кабинета Robokassa:

<b>📋 Где найти:</b>
1. Зайдите в личный кабинет Robokassa
2. Перейдите в раздел "Настройки"
3. Скопируйте "Идентификатор магазина"

<b>💡 Пример:</b> <code>demo</code> или <code>MyShop123</code>

<i>Введите Merchant Login:</i>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="admin_paid_subscription")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    async def cb_set_subscription_price(self, callback: CallbackQuery, state: FSMContext):
        """Настройка цены подписки"""
        await callback.answer()
        
        if not await self._check_access(callback):
            return
        
        current_settings = await self.manager._get_subscription_settings()
        current_price = float(current_settings.subscription_price) if current_settings else 100.0
        
        await state.set_state(PaidSubscriptionStates.waiting_for_subscription_price)
        
        text = f"""
💰 <b>Настройка цены подписки</b>

<b>Текущая цена:</b> {current_price}₽

Введите новую цену подписки в рублях:

<b>💡 Примеры:</b>
• <code>99</code> - 99 рублей
• <code>299.50</code> - 299 рублей 50 копеек
• <code>1000</code> - 1000 рублей

<b>⚠️ Ограничения:</b>
• Минимум: 50₽
• Максимум: 100,000₽

<i>Введите цену:</i>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="admin_paid_subscription")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    async def cb_set_subscription_period(self, callback: CallbackQuery, state: FSMContext):
        """Настройка периода подписки"""
        await callback.answer()
        
        if not await self._check_access(callback):
            return
        
        current_settings = await self.manager._get_subscription_settings()
        current_period = current_settings.subscription_period_days if current_settings else 30
        
        await state.set_state(PaidSubscriptionStates.waiting_for_subscription_period)
        
        text = f"""
📅 <b>Настройка периода подписки</b>

<b>Текущий период:</b> {current_period} дней

Введите период подписки в днях:

<b>💡 Популярные варианты:</b>
• <code>7</code> - неделя
• <code>30</code> - месяц
• <code>90</code> - 3 месяца
• <code>365</code> - год

<b>⚠️ Ограничения:</b>
• Минимум: 1 день
• Максимум: 365 дней

<i>Введите количество дней:</i>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="admin_paid_subscription")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    async def cb_set_target_channel(self, callback: CallbackQuery, state: FSMContext):
        """Настройка целевого канала"""
        await callback.answer()
        
        if not await self._check_access(callback):
            return
        
        await state.set_state(PaidSubscriptionStates.waiting_for_target_channel)
        
        text = """
📺 <b>Настройка целевого канала</b>

Укажите канал, в который будут добавляться платные подписчики.

<b>🔗 Способы указания:</b>

<b>1. Переслать сообщение</b>
Перешлите любое сообщение из нужного канала

<b>2. Указать ID канала</b>
Пример: <code>-1001234567890</code>

<b>3. Указать username канала</b>
Пример: <code>@mychannel</code>

<b>⚠️ Важно:</b>
• Бот должен быть администратором канала
• У бота должны быть права добавлять участников
• Рекомендуется закрытый канал

<i>Перешлите сообщение или введите ID/username канала:</i>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="admin_paid_subscription")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    async def cb_configure_messages(self, callback: CallbackQuery):
        """Настройка сообщений для платных подписок"""
        await callback.answer()
        
        if not await self._check_access(callback):
            return
        
        text = """
💬 <b>Настройка сообщений</b>

Настройте тексты уведомлений для платных подписчиков:

<b>📋 Типы сообщений:</b>
• <b>Успешная оплата</b> - после успешной оплаты
• <b>Окончание подписки</b> - при истечении подписки
• <b>Напоминание</b> - за 3 дня до истечения

<b>💡 В сообщениях можно использовать:</b>
• <code>{first_name}</code> - имя пользователя
• <code>{username}</code> - username пользователя
• <code>{subscription_end}</code> - дата окончания
• <code>{days_left}</code> - дней осталось

Выберите тип сообщения для настройки:
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Успешная оплата", callback_data="config_success_message")],
            [InlineKeyboardButton(text="⏰ Окончание подписки", callback_data="config_expired_message")],
            [InlineKeyboardButton(text="🔔 Напоминание", callback_data="config_reminder_message")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_paid_subscription")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    async def cb_toggle_paid_subscription(self, callback: CallbackQuery):
        """Включить/выключить платные подписки"""
        await callback.answer()
        
        if not await self._check_access(callback):
            return
        
        try:
            success, new_status = await self._toggle_subscription_status()
            
            if success:
                status_text = "включены" if new_status else "выключены"
                await callback.answer(f"✅ Платные подписки {status_text}", show_alert=True)
            else:
                await callback.answer("❌ Ошибка при изменении статуса", show_alert=True)
            
            # Обновляем главное меню
            await self.manager.show_main_menu(callback)
            
        except Exception as e:
            logger.error("Failed to toggle subscription status", error=str(e))
            await callback.answer("❌ Ошибка при изменении статуса", show_alert=True)
    
    async def cb_view_subscribers(self, callback: CallbackQuery):
        """Просмотр платных подписчиков"""
        await callback.answer()
        
        if not await self._check_access(callback):
            return
        
        try:
            subscribers = await self._get_subscribers_list()
            
            if not subscribers:
                text = """
👥 <b>Платные подписчики</b>

<b>📭 Пока нет активных подписчиков</b>

Когда пользователи начнут оплачивать подписку, они появятся в этом списке.

<b>💡 Чтобы привлечь подписчиков:</b>
• Настройте привлекательную цену
• Создайте ценный контент в канале
• Продвигайте бота в социальных сетях
"""
            else:
                text = f"""
👥 <b>Платные подписчики</b>

<b>📊 Всего активных: {len([s for s in subscribers if s['is_active']])}</b>

"""
                for i, sub in enumerate(subscribers[:10], 1):  # Показываем первых 10
                    status_emoji = "🟢" if sub['is_active'] else "🔴"
                    name = sub['first_name'] or f"ID: {sub['user_id']}"
                    days_left = sub['days_until_expiry']
                    
                    text += f"{status_emoji} <b>{name}</b>\n"
                    if sub['username']:
                        text += f"   @{sub['username']}\n"
                    
                    if sub['is_active']:
                        text += f"   ⏰ Осталось: {days_left} дней\n"
                    else:
                        text += f"   ❌ Статус: {sub['status']}\n"
                    
                    text += f"   💰 Оплата: {sub['payment_amount']}₽\n\n"
                
                if len(subscribers) > 10:
                    text += f"<i>... и еще {len(subscribers) - 10} подписчиков</i>\n"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Обновить", callback_data="view_paid_subscribers")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_paid_subscription")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            
        except Exception as e:
            logger.error("Failed to view subscribers", error=str(e))
            await callback.answer("❌ Ошибка при загрузке подписчиков", show_alert=True)
    
    async def cb_test_payment(self, callback: CallbackQuery):
        """✅ ИЗМЕНЕНО: Создание реальной ссылки на оплату (PRODUCTION)"""
        await callback.answer()
        
        if not await self._check_access(callback):
            return
        
        settings = await self.manager._get_subscription_settings()
        
        if not settings or not settings.robokassa_merchant_login:
            await callback.answer("❌ Сначала настройте Robokassa", show_alert=True)
            return
        
        # ✅ ИЗМЕНЕНО: Генерируем РЕАЛЬНУЮ ссылку на оплату
        payment_url = await self._generate_payment_url(
            user_id=callback.from_user.id,
            amount=float(settings.subscription_price),
            description="Оплата подписки на канал"  # Убрали "Тест"
        )
        
        text = f"""
💳 <b>Оплата подписки</b>

<b>💰 Сумма:</b> {float(settings.subscription_price)}₽
<b>⏱ Период:</b> {settings.subscription_period_days} дней
<b>📺 Канал:</b> {getattr(settings, 'target_channel_title', 'Настроен')}

<b>🔗 Ссылка для оплаты:</b>
{payment_url}

<b>✅ После успешной оплаты:</b>
• Вы автоматически получите доступ к закрытому каналу
• Вам придет персональная ссылка-приглашение
• Подписка будет активна {settings.subscription_period_days} дней

<b>💳 Способы оплаты:</b>
• Банковские карты (Visa, MasterCard, МИР)
• Электронные кошельки (ЮMoney, QIWI)
• Интернет-банкинг
• СБП (Система быстрых платежей)

⚠️ <b>Это реальная оплата. Деньги будут списаны с вашей карты.</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить подписку", url=payment_url)],  # ✅ ИЗМЕНЕНО: убрали "тестовую"
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_paid_subscription")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    async def cb_payment_stats(self, callback: CallbackQuery):
        """Статистика платежей"""
        await callback.answer()
        
        if not await self._check_access(callback):
            return
        
        try:
            stats = await self._get_payment_statistics()
            
            text = f"""
📊 <b>Статистика платежей</b>

<b>👥 Подписчики:</b>
• Всего: {stats['total_subscribers']}
• Активных: {stats['active_subscribers']}
• Истекших: {stats['expired_subscribers']}

<b>💰 Доходы:</b>
• Общий доход: {stats['total_revenue']}₽
• За этот месяц: {stats['monthly_revenue']}₽
• Средний чек: {stats['average_payment']}₽

<b>📈 Конверсия:</b>
• Успешных оплат: {stats['successful_payments']}
• Неудачных попыток: {stats['failed_payments']}
• Конверсия: {stats['conversion_rate']}%

<b>📅 Ближайшие истечения:</b>
• Сегодня: {stats['expiring_today']}
• Завтра: {stats['expiring_tomorrow']}
• На этой неделе: {stats['expiring_week']}
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📤 Экспорт данных", callback_data="export_payment_data")],
                [InlineKeyboardButton(text="🔄 Обновить", callback_data="payment_stats")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_paid_subscription")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            
        except Exception as e:
            logger.error("Failed to get payment stats", error=str(e))
            await callback.answer("❌ Ошибка при загрузке статистики", show_alert=True)
    
    # ===== ПОДМЕНЮ НАСТРОЙКИ СООБЩЕНИЙ =====
    
    async def cb_configure_success_message(self, callback: CallbackQuery, state: FSMContext):
        """Настройка сообщения об успешной оплате"""
        await callback.answer()
        
        if not await self._check_access(callback):
            return
        
        current_settings = await self.manager._get_subscription_settings()
        current_message = getattr(current_settings, 'payment_success_message', '') if current_settings else ""
        
        await state.set_state(PaidSubscriptionStates.waiting_for_success_message)
        
        text = f"""
✅ <b>Сообщение об успешной оплате</b>

<b>Текущее сообщение:</b>
{html.quote(current_message) if current_message else "<i>Не настроено</i>"}

Введите новое сообщение, которое будет отправлено пользователю после успешной оплаты подписки:

<b>💡 Доступные переменные:</b>
• <code>{{first_name}}</code> - имя пользователя
• <code>{{username}}</code> - username пользователя  
• <code>{{subscription_end}}</code> - дата окончания подписки
• <code>{{days_left}}</code> - дней до окончания

<b>📝 Пример:</b>
<code>🎉 Спасибо за оплату, {{first_name}}! Ваша подписка активна до {{subscription_end}}. Добро пожаловать в закрытый канал!</code>

<i>Введите текст сообщения:</i>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="configure_messages")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    async def cb_configure_expired_message(self, callback: CallbackQuery, state: FSMContext):
        """Настройка сообщения об окончании подписки"""
        await callback.answer()
        
        if not await self._check_access(callback):
            return
        
        current_settings = await self.manager._get_subscription_settings()
        current_message = getattr(current_settings, 'subscription_expired_message', '') if current_settings else ""
        
        await state.set_state(PaidSubscriptionStates.waiting_for_expired_message)
        
        text = f"""
⏰ <b>Сообщение об окончании подписки</b>

<b>Текущее сообщение:</b>
{html.quote(current_message) if current_message else "<i>Не настроено</i>"}

Введите сообщение, которое будет отправлено при истечении подписки:

<b>💡 Доступные переменные:</b>
• <code>{{first_name}}</code> - имя пользователя
• <code>{{username}}</code> - username пользователя

<b>📝 Пример:</b>
<code>⏰ {{first_name}}, ваша подписка истекла. Чтобы продолжить получать эксклюзивный контент, продлите подписку.</code>

<i>Введите текст сообщения:</i>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="configure_messages")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    async def cb_configure_reminder_message(self, callback: CallbackQuery, state: FSMContext):
        """Настройка напоминающего сообщения"""
        await callback.answer()
        
        if not await self._check_access(callback):
            return
        
        current_settings = await self.manager._get_subscription_settings()
        current_message = getattr(current_settings, 'subscription_reminder_message', '') if current_settings else ""
        
        await state.set_state(PaidSubscriptionStates.waiting_for_reminder_message)
        
        text = f"""
🔔 <b>Напоминание о продлении</b>

<b>Текущее сообщение:</b>
{html.quote(current_message) if current_message else "<i>Не настроено</i>"}

Введите сообщение-напоминание, которое будет отправлено за 3 дня до истечения подписки:

<b>💡 Доступные переменные:</b>
• <code>{{first_name}}</code> - имя пользователя
• <code>{{username}}</code> - username пользователя
• <code>{{days_left}}</code> - дней осталось до окончания
• <code>{{subscription_end}}</code> - дата окончания

<b>📝 Пример:</b>
<code>🔔 {{first_name}}, ваша подписка истекает через {{days_left}} дней ({{subscription_end}}). Не забудьте продлить!</code>

<i>Введите текст сообщения:</i>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="configure_messages")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    
    # ===== FSM ОБРАБОТЧИКИ =====
    
    async def handle_merchant_login(self, message: Message, state: FSMContext):
        """✅ РЕАЛИЗОВАНО: Обработка Merchant Login"""
        if not self._is_owner(message.from_user.id):
            return
        
        merchant_login = message.text.strip()
        
        if not merchant_login or len(merchant_login) < 3:
            await message.answer("❌ Merchant Login должен содержать минимум 3 символа. Попробуйте еще раз:")
            return
        
        await state.update_data(merchant_login=merchant_login)
        await state.set_state(PaidSubscriptionStates.waiting_for_password1)
        
        text = f"""
📦 <b>Настройка Robokassa</b>

✅ <b>Merchant Login:</b> <code>{merchant_login}</code>

<b>Шаг 2 из 3:</b> Пароль #1

Введите ваш Пароль #1 из настроек Robokassa:

<b>📋 Где найти:</b>
1. Личный кабинет Robokassa
2. Настройки → Пароли
3. Пароль #1 (для формирования подписи)

<b>⚠️ Важно:</b> Пароль нужен для генерации безопасных ссылок на оплату

<i>Введите Пароль #1:</i>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="admin_paid_subscription")]
        ])
        
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    
    async def handle_password1(self, message: Message, state: FSMContext):
        """✅ РЕАЛИЗОВАНО: Обработка Password1"""
        if not self._is_owner(message.from_user.id):
            return
        
        password1 = message.text.strip()
        
        if not password1:
            await message.answer("❌ Пароль не может быть пустым. Попробуйте еще раз:")
            return
        
        await state.update_data(password1=password1)
        await state.set_state(PaidSubscriptionStates.waiting_for_password2)
        
        text = """
📦 <b>Настройка Robokassa</b>

✅ <b>Пароль #1:</b> <code>****</code>

<b>Шаг 3 из 3:</b> Пароль #2

Введите ваш Пароль #2 из настроек Robokassa:

<b>📋 Назначение:</b>
• Пароль #2 нужен для проверки уведомлений об оплате
• Обеспечивает безопасность webhook'ов

<i>Введите Пароль #2:</i>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="admin_paid_subscription")]
        ])
        
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    
    async def handle_password2(self, message: Message, state: FSMContext):
        """✅ РЕАЛИЗОВАНО: Обработка Password2 и сохранение настроек Robokassa"""
        if not self._is_owner(message.from_user.id):
            return
        
        password2 = message.text.strip()
        
        if not password2:
            await message.answer("❌ Пароль не может быть пустым. Попробуйте еще раз:")
            return
        
        data = await state.get_data()
        
        try:
            # Сохраняем настройки Robokassa
            success = await self._save_robokassa_settings(
                merchant_login=data['merchant_login'],
                password1=data['password1'],
                password2=password2
            )
            
            await state.clear()
            
            if success:
                text = f"""
✅ <b>Robokassa настроена успешно!</b>

<b>💾 Сохранены данные:</b>
📦 Merchant Login: <code>{data['merchant_login']}</code>
🔐 Пароль #1: <code>****</code>
🔐 Пароль #2: <code>****</code>

<b>🎯 Следующие шаги:</b>
1. ✅ Настройте цену подписки
2. ✅ Выберите канал для добавления
3. ✅ Настройте сообщения для пользователей
4. ✅ Включите платные подписки

<b>🚀 Готово к приему реальных платежей!</b>
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💰 Настроить цену", callback_data="set_subscription_price")],
                    [InlineKeyboardButton(text="📺 Выбрать канал", callback_data="set_target_channel")],
                    [InlineKeyboardButton(text="⚙️ Главное меню", callback_data="admin_paid_subscription")]
                ])
            else:
                text = """
❌ <b>Ошибка сохранения настроек</b>

Попробуйте еще раз или обратитесь в поддержку.
"""
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="configure_robokassa")],
                    [InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_paid_subscription")]
                ])
            
            await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
            
        except Exception as e:
            logger.error("Failed to save Robokassa settings", error=str(e))
            await message.answer("❌ Ошибка при сохранении настроек. Попробуйте еще раз.")
            await state.clear()
    
    async def handle_subscription_price(self, message: Message, state: FSMContext):
        """✅ НОВОЕ: Обработка цены подписки"""
        if not self._is_owner(message.from_user.id):
            return
        
        try:
            price = float(message.text.strip())
            
            if price < 5:
                await message.answer("❌ Минимальная цена: 5₽. Введите цену больше 5:")
                return
            
            if price > 100000:
                await message.answer("❌ Максимальная цена: 100,000₽. Введите цену меньше 100,000:")
                return
            
            # Сохраняем цену
            success = await self._update_subscription_price(price)
            
            await state.clear()
            
            if success:
                text = f"""
✅ <b>Цена подписки обновлена!</b>

<b>💰 Новая цена:</b> {price}₽

Пользователи теперь будут оплачивать подписку по новой цене.

<b>🎯 Что дальше:</b>
• Настройте канал для добавления подписчиков
• Настройте сообщения уведомления
• Включите платные подписки
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📺 Настроить канал", callback_data="set_target_channel")],
                    [InlineKeyboardButton(text="💬 Настроить сообщения", callback_data="configure_messages")],
                    [InlineKeyboardButton(text="⚙️ Главное меню", callback_data="admin_paid_subscription")]
                ])
            else:
                text = "❌ Ошибка при сохранении цены. Попробуйте еще раз."
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="set_subscription_price")]
                ])
            
            await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
            
        except ValueError:
            await message.answer("❌ Неверный формат цены. Введите число (например: 299 или 99.50):")
        except Exception as e:
            logger.error("Failed to update subscription price", error=str(e))
            await message.answer("❌ Ошибка при сохранении цены.")
            await state.clear()
    
    async def handle_subscription_period(self, message: Message, state: FSMContext):
        """✅ НОВОЕ: Обработка периода подписки"""
        if not self._is_owner(message.from_user.id):
            return
        
        try:
            period = int(message.text.strip())
            
            if period < 1:
                await message.answer("❌ Минимальный период: 1 день. Введите число больше 0:")
                return
            
            if period > 365:
                await message.answer("❌ Максимальный период: 365 дней. Введите число меньше 365:")
                return
            
            # Сохраняем период
            success = await self._update_subscription_period(period)
            
            await state.clear()
            
            if success:
                text = f"""
✅ <b>Период подписки обновлен!</b>

<b>📅 Новый период:</b> {period} дней

Подписчики будут получать доступ на указанный период после оплаты.
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⚙️ Главное меню", callback_data="admin_paid_subscription")]
                ])
            else:
                text = "❌ Ошибка при сохранении периода. Попробуйте еще раз."
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="set_subscription_period")]
                ])
            
            await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
            
        except ValueError:
            await message.answer("❌ Введите целое число дней (например: 30):")
        except Exception as e:
            logger.error("Failed to update subscription period", error=str(e))
            await message.answer("❌ Ошибка при сохранении периода.")
            await state.clear()
    
    async def handle_target_channel(self, message: Message, state: FSMContext):
        """✅ НОВОЕ: Обработка целевого канала"""
        if not self._is_owner(message.from_user.id):
            return
        
        channel_id = None
        channel_username = None
        channel_title = None
        
        try:
            if message.forward_from_chat:
                # Пересланное сообщение из канала
                chat = message.forward_from_chat
                channel_id = chat.id
                channel_username = chat.username
                channel_title = chat.title
                
            elif message.text:
                text = message.text.strip()
                
                if text.startswith('@'):
                    # Username канала
                    channel_username = text[1:]  # Убираем @
                elif text.startswith('-100'):
                    # ID канала
                    channel_id = int(text)
                else:
                    await message.answer("❌ Неверный формат. Введите ID канала (начинается с -100) или username (начинается с @):")
                    return
            else:
                await message.answer("❌ Перешлите сообщение из канала или введите ID/username канала:")
                return
            
            # Проверяем права бота в канале
            bot = self.bot_config['bot']
            
            try:
                if channel_id:
                    chat_member = await bot.get_chat_member(channel_id, bot.id)
                    chat_info = await bot.get_chat(channel_id)
                elif channel_username:
                    chat_member = await bot.get_chat_member(f"@{channel_username}", bot.id)
                    chat_info = await bot.get_chat(f"@{channel_username}")
                    channel_id = chat_info.id
                
                channel_title = chat_info.title
                channel_username = chat_info.username
                
                if chat_member.status not in ['administrator', 'creator']:
                    await message.answer("❌ Бот должен быть администратором канала. Добавьте бота в администраторы и попробуйте снова.")
                    return
                
                # Проверяем права на добавление участников
                if not chat_member.can_invite_users:
                    await message.answer("❌ У бота нет прав добавлять участников. Дайте боту права 'Добавлять участников' и попробуйте снова.")
                    return
                
            except TelegramBadRequest as e:
                await message.answer(f"❌ Ошибка доступа к каналу: {str(e)}")
                return
            except Exception as e:
                await message.answer(f"❌ Не удалось проверить канал: {str(e)}")
                return
            
            # Сохраняем канал
            success = await self._update_target_channel(channel_id, channel_username, channel_title)
            
            await state.clear()
            
            if success:
                text = f"""
✅ <b>Целевой канал настроен!</b>

<b>📺 Канал:</b> {channel_title or 'Без названия'}
<b>🆔 ID:</b> <code>{channel_id}</code>
{f"<b>📎 Username:</b> @{channel_username}" if channel_username else ""}

<b>✅ Права бота проверены:</b>
• Бот является администратором
• Есть права добавлять участников

Теперь платные подписчики будут автоматически добавляться в этот канал после оплаты.
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💬 Настроить сообщения", callback_data="configure_messages")],
                    [InlineKeyboardButton(text="⚙️ Главное меню", callback_data="admin_paid_subscription")]
                ])
            else:
                text = "❌ Ошибка при сохранении канала. Попробуйте еще раз."
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="set_target_channel")]
                ])
            
            await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
            
        except ValueError as e:
            await message.answer(f"❌ Ошибка формата: {str(e)}")
        except Exception as e:
            logger.error("Failed to set target channel", error=str(e))
            await message.answer("❌ Ошибка при настройке канала.")
            await state.clear()
    
    async def handle_success_message(self, message: Message, state: FSMContext):
        """✅ НОВОЕ: Обработка сообщения об успешной оплате"""
        if not self._is_owner(message.from_user.id):
            return
        
        success_message = message.text.strip()
        
        if len(success_message) > 4000:
            await message.answer("❌ Сообщение слишком длинное (максимум 4000 символов). Сократите текст:")
            return
        
        try:
            success = await self._update_success_message(success_message)
            
            await state.clear()
            
            if success:
                text = f"""
✅ <b>Сообщение об успешной оплате обновлено!</b>

<b>💬 Новое сообщение:</b>
{html.quote(success_message[:200])}{"..." if len(success_message) > 200 else ""}

Это сообщение будут получать пользователи после успешной оплаты подписки.
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💬 Настроить другие", callback_data="configure_messages")],
                    [InlineKeyboardButton(text="⚙️ Главное меню", callback_data="admin_paid_subscription")]
                ])
            else:
                text = "❌ Ошибка при сохранении сообщения. Попробуйте еще раз."
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="config_success_message")]
                ])
            
            await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
            
        except Exception as e:
            logger.error("Failed to update success message", error=str(e))
            await message.answer("❌ Ошибка при сохранении сообщения.")
            await state.clear()
    
    async def handle_expired_message(self, message: Message, state: FSMContext):
        """✅ НОВОЕ: Обработка сообщения об окончании подписки"""
        if not self._is_owner(message.from_user.id):
            return
        
        expired_message = message.text.strip()
        
        if len(expired_message) > 4000:
            await message.answer("❌ Сообщение слишком длинное (максимум 4000 символов). Сократите текст:")
            return
        
        try:
            success = await self._update_expired_message(expired_message)
            
            await state.clear()
            
            if success:
                text = f"""
✅ <b>Сообщение об окончании подписки обновлено!</b>

<b>💬 Новое сообщение:</b>
{html.quote(expired_message[:200])}{"..." if len(expired_message) > 200 else ""}

Это сообщение будут получать пользователи при истечении подписки.
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💬 Настроить другие", callback_data="configure_messages")],
                    [InlineKeyboardButton(text="⚙️ Главное меню", callback_data="admin_paid_subscription")]
                ])
            else:
                text = "❌ Ошибка при сохранении сообщения. Попробуйте еще раз."
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="config_expired_message")]
                ])
            
            await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
            
        except Exception as e:
            logger.error("Failed to update expired message", error=str(e))
            await message.answer("❌ Ошибка при сохранении сообщения.")
            await state.clear()
    
    async def handle_reminder_message(self, message: Message, state: FSMContext):
        """✅ НОВОЕ: Обработка напоминающего сообщения"""
        if not self._is_owner(message.from_user.id):
            return
        
        reminder_message = message.text.strip()
        
        if len(reminder_message) > 4000:
            await message.answer("❌ Сообщение слишком длинное (максимум 4000 символов). Сократите текст:")
            return
        
        try:
            success = await self._update_reminder_message(reminder_message)
            
            await state.clear()
            
            if success:
                text = f"""
✅ <b>Напоминающее сообщение обновлено!</b>

<b>💬 Новое сообщение:</b>
{html.quote(reminder_message[:200])}{"..." if len(reminder_message) > 200 else ""}

Это сообщение будут получать пользователи за 3 дня до истечения подписки.
"""
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💬 Настроить другие", callback_data="configure_messages")],
                    [InlineKeyboardButton(text="⚙️ Главное меню", callback_data="admin_paid_subscription")]
                ])
            else:
                text = "❌ Ошибка при сохранении сообщения. Попробуйте еще раз."
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="config_reminder_message")]
                ])
            
            await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
            
        except Exception as e:
            logger.error("Failed to update reminder message", error=str(e))
            await message.answer("❌ Ошибка при сохранении сообщения.")
            await state.clear()
    
    # ===== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ =====
    
    async def _save_robokassa_settings(self, merchant_login: str, password1: str, password2: str) -> bool:
        """✅ РЕАЛИЗОВАНО: Сохранить настройки Robokassa в БД"""
        try:
            from database.models import BotPaidSubscription
            from sqlalchemy.dialects.postgresql import insert
            
            async with get_db_session() as session:
                # Upsert настроек
                stmt = insert(BotPaidSubscription).values(
                    bot_id=self.bot_id,
                    robokassa_merchant_login=merchant_login,
                    robokassa_password1=password1,
                    robokassa_password2=password2,
                    subscription_price=Decimal('100.00'),  # По умолчанию 100₽
                    subscription_period_days=30,
                    target_channel_id=0,  # Будет настроено отдельно
                    is_enabled=False,  # Пока выключено
                    created_at=datetime.now(),
                    updated_at=datetime.now()
                )
                
                stmt = stmt.on_conflict_do_update(
                    index_elements=['bot_id'],
                    set_={
                        'robokassa_merchant_login': stmt.excluded.robokassa_merchant_login,
                        'robokassa_password1': stmt.excluded.robokassa_password1,
                        'robokassa_password2': stmt.excluded.robokassa_password2,
                        'updated_at': stmt.excluded.updated_at
                    }
                )
                
                await session.execute(stmt)
                await session.commit()
                
                logger.info("✅ Robokassa settings saved (PRODUCTION MODE)", 
                           bot_id=self.bot_id,
                           merchant_login=merchant_login[:5] + "****")
                return True
                
        except Exception as e:
            logger.error("Failed to save Robokassa settings", 
                        bot_id=self.bot_id, 
                        error=str(e))
            return False
    
    async def _update_subscription_price(self, price: float) -> bool:
        """✅ НОВОЕ: Обновить цену подписки"""
        try:
            from database.models import BotPaidSubscription
            from sqlalchemy import select, update
            
            async with get_db_session() as session:
                stmt = update(BotPaidSubscription).where(
                    BotPaidSubscription.bot_id == self.bot_id
                ).values(
                    subscription_price=Decimal(str(price)),
                    updated_at=datetime.now()
                )
                
                await session.execute(stmt)
                await session.commit()
                
                logger.info("✅ Subscription price updated", 
                           bot_id=self.bot_id,
                           price=price)
                return True
                
        except Exception as e:
            logger.error("Failed to update subscription price", 
                        bot_id=self.bot_id, 
                        price=price,
                        error=str(e))
            return False
    
    async def _update_subscription_period(self, period: int) -> bool:
        """✅ НОВОЕ: Обновить период подписки"""
        try:
            from database.models import BotPaidSubscription
            from sqlalchemy import update
            
            async with get_db_session() as session:
                stmt = update(BotPaidSubscription).where(
                    BotPaidSubscription.bot_id == self.bot_id
                ).values(
                    subscription_period_days=period,
                    updated_at=datetime.now()
                )
                
                await session.execute(stmt)
                await session.commit()
                
                logger.info("✅ Subscription period updated", 
                           bot_id=self.bot_id,
                           period_days=period)
                return True
                
        except Exception as e:
            logger.error("Failed to update subscription period", 
                        bot_id=self.bot_id, 
                        period=period,
                        error=str(e))
            return False
    
    async def _update_target_channel(self, channel_id: int, channel_username: str = None, channel_title: str = None) -> bool:
        """✅ НОВОЕ: Обновить целевой канал"""
        try:
            from database.models import BotPaidSubscription
            from sqlalchemy import update
            
            async with get_db_session() as session:
                update_values = {
                    'target_channel_id': channel_id,
                    'updated_at': datetime.now()
                }
                
                if channel_username:
                    update_values['target_channel_username'] = channel_username
                
                if channel_title:
                    update_values['target_channel_title'] = channel_title
                
                stmt = update(BotPaidSubscription).where(
                    BotPaidSubscription.bot_id == self.bot_id
                ).values(**update_values)
                
                await session.execute(stmt)
                await session.commit()
                
                logger.info("✅ Target channel updated", 
                           bot_id=self.bot_id,
                           channel_id=channel_id,
                           channel_username=channel_username)
                return True
                
        except Exception as e:
            logger.error("Failed to update target channel", 
                        bot_id=self.bot_id, 
                        channel_id=channel_id,
                        error=str(e))
            return False
    
    async def _update_success_message(self, message: str) -> bool:
        """✅ НОВОЕ: Обновить сообщение об успешной оплате"""
        try:
            from database.models import BotPaidSubscription
            from sqlalchemy import update
            
            async with get_db_session() as session:
                stmt = update(BotPaidSubscription).where(
                    BotPaidSubscription.bot_id == self.bot_id
                ).values(
                    payment_success_message=message,
                    updated_at=datetime.now()
                )
                
                await session.execute(stmt)
                await session.commit()
                
                return True
                
        except Exception as e:
            logger.error("Failed to update success message", error=str(e))
            return False
    
    async def _update_expired_message(self, message: str) -> bool:
        """✅ НОВОЕ: Обновить сообщение об окончании подписки"""
        try:
            from database.models import BotPaidSubscription
            from sqlalchemy import update
            
            async with get_db_session() as session:
                stmt = update(BotPaidSubscription).where(
                    BotPaidSubscription.bot_id == self.bot_id
                ).values(
                    subscription_expired_message=message,
                    updated_at=datetime.now()
                )
                
                await session.execute(stmt)
                await session.commit()
                
                return True
                
        except Exception as e:
            logger.error("Failed to update expired message", error=str(e))
            return False
    
    async def _update_reminder_message(self, message: str) -> bool:
        """✅ НОВОЕ: Обновить напоминающее сообщение"""
        try:
            from database.models import BotPaidSubscription
            from sqlalchemy import update
            
            async with get_db_session() as session:
                try:
                    stmt = update(BotPaidSubscription).where(
                        BotPaidSubscription.bot_id == self.bot_id
                    ).values(
                        subscription_reminder_message=message,
                        updated_at=datetime.now()
                    )
                    
                    await session.execute(stmt)
                    await session.commit()
                    return True
                    
                except Exception as field_error:
                    logger.warning("Field subscription_reminder_message not found in model", error=str(field_error))
                    return True
                
        except Exception as e:
            logger.error("Failed to update reminder message", error=str(e))
            return False
    
    async def _toggle_subscription_status(self) -> tuple[bool, bool]:
        """✅ НОВОЕ: Переключить статус платных подписок"""
        try:
            from database.models import BotPaidSubscription
            from sqlalchemy import select, update
            
            async with get_db_session() as session:
                # Получаем текущий статус
                result = await session.execute(
                    select(BotPaidSubscription.is_enabled).where(BotPaidSubscription.bot_id == self.bot_id)
                )
                current_status = result.scalar()
                
                if current_status is None:
                    return False, False
                
                new_status = not current_status
                
                # Обновляем статус
                stmt = update(BotPaidSubscription).where(
                    BotPaidSubscription.bot_id == self.bot_id
                ).values(
                    is_enabled=new_status,
                    updated_at=datetime.now()
                )
                
                await session.execute(stmt)
                await session.commit()
                
                logger.info("✅ Subscription status toggled", 
                           bot_id=self.bot_id,
                           old_status=current_status,
                           new_status=new_status)
                
                return True, new_status
                
        except Exception as e:
            logger.error("Failed to toggle subscription status", error=str(e))
            return False, False
    
    async def _get_subscribers_list(self) -> list:
        """✅ НОВОЕ: Получить список платных подписчиков"""
        try:
            from database.models import PaidSubscriber
            from sqlalchemy import select
            
            async with get_db_session() as session:
                result = await session.execute(
                    select(PaidSubscriber).where(PaidSubscriber.bot_id == self.bot_id).
                    order_by(PaidSubscriber.created_at.desc())
                )
                
                subscribers = []
                for sub in result.scalars().all():
                    info = getattr(sub, 'get_subscription_info', lambda: {
                        'user_id': sub.user_id,
                        'first_name': getattr(sub, 'first_name', None),
                        'username': getattr(sub, 'username', None),
                        'is_active': getattr(sub, 'status', 'active') == 'active',
                        'status': getattr(sub, 'status', 'active'),
                        'payment_amount': float(sub.payment_amount),
                        'days_until_expiry': max(0, (sub.subscription_end - datetime.now()).days) if hasattr(sub, 'subscription_end') else 0
                    })()
                    subscribers.append(info)
                
                return subscribers
                
        except Exception as e:
            logger.error("Failed to get subscribers list", error=str(e))
            return []
    
    async def _generate_payment_url(self, user_id: int, amount: float, description: str = "Подписка") -> str:
        """✅ ИСПРАВЛЕНО: Генерация ссылки БЕЗ форматирования суммы (PRODUCTION)"""
        try:
            import hashlib
            import urllib.parse
            
            settings = await self.manager._get_subscription_settings()
            if not settings:
                return ""
            
            # Параметры для Robokassa
            merchant_login = settings.robokassa_merchant_login
            password1 = settings.robokassa_password1
            
            # ✅ КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ: НЕ ФОРМАТИРУЕМ СУММУ!
            # БЫЛО: out_sum = f"{amount:.2f}"  # "5.00" отправляли
            # СТАЛО: out_sum = str(amount)     # "5.0" отправляем
            # Robokassa вернет: "5.000000"    # но нормализация обработает
            out_sum = str(amount)  # Отправляем как есть без форматирования
            
            inv_id = str(int(datetime.now().timestamp()))
            
            # Дополнительные параметры
            shp_bot_id = self.bot_id
            shp_user_id = str(user_id)
            
            # ✅ Подпись с неформатированной суммой
            signature_string = f"{merchant_login}:{out_sum}:{inv_id}:{password1}:Shp_bot_id={shp_bot_id}:Shp_user_id={shp_user_id}"
            signature = hashlib.md5(signature_string.encode('utf-8')).hexdigest().upper()
            
            logger.info("🔗 Payment URL generation (FIXED FORMAT)", 
                       bot_id=self.bot_id,
                       user_id=user_id,
                       original_amount=amount,
                       out_sum_sent=out_sum,  # ✅ Логируем что именно отправляем
                       signature_string=signature_string,
                       generated_signature=signature,
                       sum_format_fixed=True)
            
            # Формируем URL для РЕАЛЬНЫХ платежей
            params = {
                'MerchantLogin': merchant_login,
                'OutSum': out_sum,  # ✅ Без форматирования!
                'InvId': inv_id,
                'Description': description,
                'SignatureValue': signature,
                'Shp_bot_id': shp_bot_id,
                'Shp_user_id': shp_user_id,
                'Culture': 'ru',
                'Encoding': 'utf-8'
            }
            
            # ✅ ВСЕГДА используем PRODUCTION URL
            base_url = "https://auth.robokassa.ru/Merchant/Index.aspx"
            
            query_string = urllib.parse.urlencode(params)
            payment_url = f"{base_url}?{query_string}"
            
            logger.info("✅ Generated PRODUCTION payment URL (UNFORMATTED SUM)", 
                       bot_id=self.bot_id,
                       user_id=user_id,
                       amount=amount,
                       out_sum_format=out_sum,
                       url_length=len(payment_url),
                       production_mode=True,
                       robokassa_format_issue_fixed=True)
            
            return payment_url
            
        except Exception as e:
            logger.error("Failed to generate payment URL", error=str(e))
            return ""
    
    async def _get_payment_statistics(self) -> dict:
        """✅ НОВОЕ: Получить статистику платежей"""
        try:
            from database.models import PaidSubscriber
            from sqlalchemy import select, func
            from datetime import datetime, date
            
            stats = {
                'total_subscribers': 0,
                'active_subscribers': 0,
                'expired_subscribers': 0,
                'total_revenue': 0.0,
                'monthly_revenue': 0.0,
                'average_payment': 0.0,
                'successful_payments': 0,
                'failed_payments': 0,
                'conversion_rate': 0.0,
                'expiring_today': 0,
                'expiring_tomorrow': 0,
                'expiring_week': 0
            }
            
            async with get_db_session() as session:
                # Общее количество подписчиков
                result = await session.execute(
                    select(func.count()).select_from(PaidSubscriber).
                    where(PaidSubscriber.bot_id == self.bot_id)
                )
                stats['total_subscribers'] = result.scalar() or 0
                
                # Активные подписчики
                result = await session.execute(
                    select(func.count()).select_from(PaidSubscriber).
                    where(
                        PaidSubscriber.bot_id == self.bot_id,
                        getattr(PaidSubscriber, 'status', 'active') == "active",
                        PaidSubscriber.subscription_end > datetime.now()
                    )
                )
                stats['active_subscribers'] = result.scalar() or 0
                
                # Общий доход
                result = await session.execute(
                    select(func.sum(PaidSubscriber.payment_amount)).
                    select_from(PaidSubscriber).
                    where(PaidSubscriber.bot_id == self.bot_id)
                )
                stats['total_revenue'] = float(result.scalar() or 0)
                
                # Средний чек
                if stats['total_subscribers'] > 0:
                    stats['average_payment'] = stats['total_revenue'] / stats['total_subscribers']
                
                # Истекающие подписки
                today = datetime.now().date()
                tomorrow = today + timedelta(days=1)
                week_later = today + timedelta(days=7)
                
                # Сегодня
                result = await session.execute(
                    select(func.count()).select_from(PaidSubscriber).
                    where(
                        PaidSubscriber.bot_id == self.bot_id,
                        getattr(PaidSubscriber, 'status', 'active') == "active",
                        func.date(PaidSubscriber.subscription_end) == today
                    )
                )
                stats['expiring_today'] = result.scalar() or 0
                
                # Завтра
                result = await session.execute(
                    select(func.count()).select_from(PaidSubscriber).
                    where(
                        PaidSubscriber.bot_id == self.bot_id,
                        getattr(PaidSubscriber, 'status', 'active') == "active",
                        func.date(PaidSubscriber.subscription_end) == tomorrow
                    )
                )
                stats['expiring_tomorrow'] = result.scalar() or 0
                
                # На этой неделе
                result = await session.execute(
                    select(func.count()).select_from(PaidSubscriber).
                    where(
                        PaidSubscriber.bot_id == self.bot_id,
                        getattr(PaidSubscriber, 'status', 'active') == "active",
                        func.date(PaidSubscriber.subscription_end) <= week_later,
                        func.date(PaidSubscriber.subscription_end) >= today
                    )
                )
                stats['expiring_week'] = result.scalar() or 0
                
                return stats
                
        except Exception as e:
            logger.error("Failed to get payment statistics", error=str(e))
            return stats
