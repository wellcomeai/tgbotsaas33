import asyncio
import signal
import sys
import os
from contextlib import asynccontextmanager
from aiohttp import web, web_runner
import aiohttp

import structlog
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from config import settings
from database import init_database, close_database
from bots import MasterBot
from services import BotManager

# ✅ ВСТРОЕННАЯ МИГРАЦИЯ - всегда доступна
async def run_auto_migrations():
    """
    Встроенная миграция для добавления отсутствующих колонок
    Выполняется перед инициализацией базы данных
    """
    logger = structlog.get_logger()
    logger.info("🔧 Starting automatic database migration...")
    
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool
        from sqlalchemy import text
        
        # Создаем временный движок для миграции
        migration_engine = create_async_engine(
            settings.database_url.replace("postgresql://", "postgresql+asyncpg://"),
            poolclass=NullPool,
            echo=False,  # Отключаем лишний вывод для миграции
            future=True
        )
        
        async with migration_engine.connect() as conn:
            # Проверяем существующие колонки
            logger.info("📋 Checking existing table structure...")
            
            result = await conn.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'user_bots'
                ORDER BY column_name
            """))
            
            existing_columns = {row[0] for row in result.fetchall()}
            logger.info("📋 Found existing columns", count=len(existing_columns))
            
            # Колонки, которые нужно добавить
            required_migrations = [
                ("openai_agent_id", "VARCHAR(255)"),
                ("openai_agent_name", "VARCHAR(255)"),
                ("openai_agent_instructions", "TEXT"),
                ("openai_model", "VARCHAR(100) DEFAULT 'gpt-4o'"),
                ("openai_settings", "JSONB"),
                ("external_api_token", "VARCHAR(255)"),
                ("external_bot_id", "VARCHAR(100)"),
                ("external_platform", "VARCHAR(50)"),
                ("external_settings", "JSONB"),
                
                # ✅ NEW: Referral program fields
                ("referral_code", "VARCHAR(20) UNIQUE"),
                ("referred_by", "BIGINT REFERENCES users(id)"),
                ("referral_earnings", "NUMERIC(10,2) DEFAULT 0.0 NOT NULL"),
                ("total_referrals", "INTEGER DEFAULT 0 NOT NULL"),
            ]
            
            added_count = 0
            skipped_count = 0
            
            for col_name, col_type in required_migrations:
                if col_name not in existing_columns:
                    try:
                        alter_sql = f"ALTER TABLE user_bots ADD COLUMN {col_name} {col_type}"
                        logger.info("🔧 Adding missing column", column=col_name, type=col_type)
                        
                        await conn.execute(text(alter_sql))
                        await conn.commit()
                        
                        logger.info("✅ Successfully added column", column=col_name)
                        added_count += 1
                        
                    except Exception as e:
                        logger.error("❌ Failed to add column", column=col_name, error=str(e))
                        # Не прерываем миграцию, продолжаем с остальными колонками
                        continue
                else:
                    logger.debug("⏭️ Column already exists", column=col_name)
                    skipped_count += 1
            
            # Закрываем временный движок
            await migration_engine.dispose()
            
            if added_count > 0:
                logger.info("🎉 Migration completed successfully", 
                           added=added_count, 
                           skipped=skipped_count,
                           total=len(required_migrations))
            else:
                logger.info("✅ Database schema is up to date", 
                           total_columns=len(required_migrations))
            
            return True
            
    except Exception as e:
        logger.error("💥 Migration failed", error=str(e), exc_info=True)
        return False


# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


class BotFactory:
    """Main Bot Factory application"""
    
    def __init__(self):
        self.master_bot = None
        self.bot_manager = None
        self.web_app = None
        self.web_runner = None
        self.running = False
        self.scheduler_task = None
        self.mass_broadcast_scheduler = None
        self.mass_broadcast_scheduler_task = None
    
    async def health_check(self, request):
        """Health check endpoint"""
        bot_statuses = {}
        if self.bot_manager:
            bot_statuses = self.bot_manager.get_all_bot_statuses()
        
        return web.json_response({
            "status": "healthy",
            "app": settings.app_name,
            "version": settings.app_version,
            "running": self.running,
            "master_bot_running": self.master_bot is not None,
            "user_bots_count": len(bot_statuses),
            "active_user_bots": sum(1 for status in bot_statuses.values() if status.get('running', False)),
            "migrations_available": True,
            "scheduler_running": self.scheduler_task is not None and not self.scheduler_task.done(),
            "mass_broadcast_scheduler_running": self.mass_broadcast_scheduler_task is not None and not self.mass_broadcast_scheduler_task.done(),
            "robokassa_configured": bool(settings.robokassa_merchant_login and settings.robokassa_password2)
        })
    
    async def robokassa_webhook(self, request):
        """✅ UPDATED: Robokassa webhook handler with token purchase support and referral commissions"""
        try:
            # Проверяем конфигурацию Robokassa
            if not settings.robokassa_merchant_login or not settings.robokassa_password2:
                logger.error("❌ Robokassa not properly configured", 
                           has_login=bool(settings.robokassa_merchant_login),
                           has_password2=bool(settings.robokassa_password2))
                return web.Response(text="ERROR: Payment system not configured", status=503)
            
            # Получаем данные от Робокассы
            data = await request.post()
            
            logger.info("💰 Robokassa webhook received", 
                       data=dict(data),
                       client_ip=request.remote,
                       user_agent=request.headers.get('User-Agent', 'Unknown'))
            
            # Извлекаем параметры включая Shp_user_id
            signature_value = data.get('SignatureValue', '').upper()
            out_sum = data.get('OutSum', '')
            inv_id = data.get('InvId', '')
            shp_user_id = data.get('Shp_user_id', '')  # ✅ НОВОЕ: user_id в отдельном параметре
            
            # ✅ НОВОЕ: Определяем тип покупки по окончанию user_id
            if shp_user_id.endswith('tokens'):
                item_type = 'tokens'
                user_id_str = shp_user_id[:-6]  # Убираем 'tokens'
            else:
                item_type = 'subscription'
                user_id_str = shp_user_id
            
            # Проверяем наличие обязательных параметров
            missing_params = []
            if not signature_value:
                missing_params.append('SignatureValue')
            if not out_sum:
                missing_params.append('OutSum')
            if not inv_id:
                missing_params.append('InvId')
            if not shp_user_id:
                missing_params.append('Shp_user_id')
            
            if missing_params:
                logger.error("❌ Missing required Robokassa parameters", 
                           missing=missing_params,
                           received_params=list(data.keys()))
                return web.Response(text=f"ERROR: Missing parameters: {', '.join(missing_params)}", status=400)
            
            # ✅ УПРОЩЕНО: Единая структура подписи для всех типов
            import hashlib
            signature_string = f"{out_sum}:{inv_id}:{settings.robokassa_password2}:Shp_user_id={shp_user_id}"
            expected_signature = hashlib.md5(signature_string.encode('utf-8')).hexdigest().upper()
            
            logger.info("🔍 Signature verification (simplified method)", 
                       signature_string=signature_string,
                       received_signature=signature_value,
                       expected_signature=expected_signature,
                       match=signature_value == expected_signature,
                       shp_user_id=shp_user_id,
                       item_type=item_type,
                       user_id_str=user_id_str)
            
            if signature_value != expected_signature:
                logger.error("❌ Invalid Robokassa signature", 
                           received=signature_value,
                           expected=expected_signature,
                           out_sum=out_sum,
                           inv_id=inv_id,
                           shp_user_id=shp_user_id,
                           item_type=item_type,
                           signature_string=signature_string)
                return web.Response(text="ERROR: Invalid signature", status=400)
            
            logger.info("✅ Robokassa signature verified successfully", 
                       out_sum=out_sum,
                       inv_id=inv_id,
                       shp_user_id=shp_user_id,
                       item_type=item_type)
            
            # ✅ ИСПРАВЛЕНО: Получаем user_id из параметра Shp_user_id
            try:
                user_id = int(user_id_str)
                
                logger.info("✅ User ID extracted from Shp_user_id", 
                           invoice_id=inv_id,
                           user_id=user_id,
                           item_type=item_type,
                           original_shp_user_id=shp_user_id)
            except ValueError as e:
                logger.error("❌ Failed to parse user_id from Shp_user_id", 
                           shp_user_id=shp_user_id,
                           error=str(e))
                return web.Response(text="ERROR: Invalid user_id format", status=400)
            
            # Получаем пользователя из БД
            try:
                from database import db
                from datetime import datetime, timedelta
                
                user = await db.get_user(user_id)
                if not user:
                    logger.error("❌ User not found for payment", 
                               user_id=user_id,
                               invoice_id=inv_id,
                               amount=out_sum,
                               item_type=item_type)
                    return web.Response(text="ERROR: User not found", status=400)
            
            except Exception as db_error:
                logger.error("💥 Database error getting user", 
                           user_id=user_id,
                           invoice_id=inv_id,
                           error=str(db_error),
                           exc_info=True)
                return web.Response(text="ERROR: Database error", status=500)
            
            # ✅ НОВОЕ: Обработка покупки токенов
            if item_type == 'tokens':
                try:
                    # Добавляем токены к балансу
                    tokens_to_add = settings.tokens_per_purchase
                    
                    # Обновляем баланс токенов
                    new_total = (user.tokens_limit_total or 500000) + tokens_to_add
                    
                    # Сохраняем в БД
                    await db.update_user_tokens_limit(user_id, new_total)
                    
                    logger.info("✅ Tokens added successfully", 
                               user_id=user_id,
                               username=user.username,
                               tokens_added=tokens_to_add,
                               old_balance=user.tokens_limit_total or 500000,
                               new_balance=new_total,
                               payment_amount=out_sum,
                               invoice_id=inv_id)
                    
                    # Отправляем уведомление о токенах
                    try:
                        if self.master_bot:
                            tokens_message = f"""
🎉 <b>Токены успешно пополнены!</b>

💰 <b>Оплачено:</b> {out_sum} ₽
🔋 <b>Получено токенов:</b> {tokens_to_add:,}
📊 <b>Новый баланс:</b> {new_total:,} токенов

🤖 <b>Теперь вы можете:</b>
- Создавать OpenAI ИИ агентов в ваших ботах
- Общаться с GPT-4o через ваших ботов
- Генерировать контент для пользователей

Спасибо за пополнение! 🚀
"""
                            await self.master_bot.bot.send_message(
                                chat_id=user_id,
                                text=tokens_message,
                                parse_mode="HTML"
                            )
                            logger.info("📩 Tokens notification sent to user", user_id=user_id)
                    except Exception as notification_error:
                        logger.warning("⚠️ Failed to send tokens notification", 
                                     user_id=user_id,
                                     error=str(notification_error))
                
                except Exception as tokens_error:
                    logger.error("💥 Database error during tokens update", 
                               user_id=user_id,
                               invoice_id=inv_id,
                               amount=out_sum,
                               error=str(tokens_error),
                               exc_info=True)
                    return web.Response(text="ERROR: Tokens update failed", status=500)
            
            # Обработка подписки (существующий код)
            elif item_type == 'subscription' or item_type is None:
                # Обновляем подписку пользователя
                try:
                    # Рассчитываем новую дату подписки
                    current_time = datetime.now()
                    if user.subscription_expires_at and user.subscription_expires_at > current_time:
                        # Продлеваем существующую подписку
                        new_expires_at = user.subscription_expires_at + timedelta(days=settings.subscription_days_per_payment)
                        action = "extended"
                    else:
                        # Активируем новую подписку
                        new_expires_at = current_time + timedelta(days=settings.subscription_days_per_payment)
                        action = "activated"
                    
                    # Обновляем подписку в БД
                    await db.update_user_subscription(
                        user_id=user_id,
                        plan="ai_admin",
                        expires_at=new_expires_at,
                        active=True
                    )
                    
                    logger.info("✅ Subscription updated successfully", 
                               user_id=user_id,
                               username=user.username,
                               plan="ai_admin",
                               expires_at=new_expires_at,
                               payment_amount=out_sum,
                               invoice_id=inv_id,
                               action=action)
                    
                    # Отправляем уведомление пользователю
                    try:
                        if self.master_bot:
                            success_message = f"""
🎉 <b>Оплата прошла успешно!</b>

💰 <b>Сумма:</b> {out_sum} ₽
📅 <b>Подписка AI ADMIN {action.replace('activated', 'активирована').replace('extended', 'продлена')} до:</b> {new_expires_at.strftime('%d.%m.%Y')}
🚀 <b>Статус:</b> Активна

✨ <b>Теперь вам доступны:</b>
• Безлимитные боты
• Расширенная статистика
• Приоритетная поддержка
• ИИ агенты без ограничений

Спасибо за использование Bot Factory! 🚀
"""
                            await self.master_bot.bot.send_message(
                                chat_id=user_id,
                                text=success_message,
                                parse_mode="HTML"
                            )
                            logger.info("📩 Payment notification sent to user", user_id=user_id)
                    except Exception as notification_error:
                        logger.warning("⚠️ Failed to send payment notification", 
                                     user_id=user_id,
                                     error=str(notification_error))
                    
                except Exception as subscription_error:
                    logger.error("💥 Database error during subscription update", 
                               user_id=user_id,
                               invoice_id=inv_id,
                               amount=out_sum,
                               error=str(subscription_error),
                               exc_info=True)
                    return web.Response(text="ERROR: Subscription update failed", status=500)
            
            else:
                logger.error("❌ Unknown item_type", 
                           item_type=item_type,
                           user_id=user_id,
                           invoice_id=inv_id)
                return web.Response(text="ERROR: Unknown item type", status=400)
            
            # ✅ НОВОЕ: Обработка партнерских комиссий после успешной оплаты
            try:
                from database.managers.user_manager import UserManager
                
                # Определяем тип транзакции
                transaction_type = "tokens" if item_type == 'tokens' else "subscription"
                
                # Обрабатываем партнерскую комиссию
                referral_result = await UserManager.process_referral_payment(
                    user_id=user_id,
                    payment_amount=float(out_sum),
                    transaction_type=transaction_type
                )
                
                if referral_result.get('success'):
                    referrer_id = referral_result['referrer_id']
                    commission_amount = referral_result['commission_amount']
                    
                    logger.info("✅ Referral commission processed", 
                               referrer_id=referrer_id,
                               commission_amount=commission_amount,
                               payment_type=transaction_type)
                    
                    # Уведомляем рефера о начислении комиссии
                    try:
                        if self.master_bot:
                            # Получаем информацию о рефере
                            from database import db
                            referrer = await db.get_user(referrer_id)
                            referrer_stats = await db.get_user_referral_stats(referrer_id)
                            
                            # Информация о том, кто оплатил
                            referred_user_info = f"@{user.username}" if user.username else user.first_name or f"ID: {user_id}"
                            
                            # Импортируем Messages из соответствующего модуля
                            from messages import Messages
                            
                            commission_message = Messages.REFERRAL_COMMISSION_EARNED.format(
                                commission_amount=f"{commission_amount:.2f}",
                                payment_amount=out_sum,
                                referred_user=referred_user_info,
                                total_earnings=f"{referrer_stats.get('total_earnings', 0):.2f}",
                                total_referrals=referrer_stats.get('total_referrals', 0)
                            )
                            
                            await self.master_bot.bot.send_message(
                                chat_id=referrer_id,
                                text=commission_message,
                                parse_mode="HTML"
                            )
                            
                            logger.info("📩 Referral commission notification sent", 
                                       referrer_id=referrer_id,
                                       commission_amount=commission_amount)
                            
                    except Exception as notification_error:
                        logger.warning("⚠️ Failed to send referral commission notification", 
                                     referrer_id=referrer_id,
                                     error=str(notification_error))
                
                else:
                    logger.info("❌ No referral commission (no referrer or error)", 
                               user_id=user_id,
                               reason=referral_result.get('reason', 'unknown'))
            
            except Exception as referral_error:
                logger.error("💥 Failed to process referral commission", 
                            user_id=user_id,
                            payment_amount=out_sum,
                            error=str(referral_error))
                # Не прерываем основной процесс оплаты
            
            # Возвращаем OK согласно требованиям Робокассы
            return web.Response(text=f"OK{inv_id}")
            
        except Exception as e:
            logger.error("💥 Robokassa webhook critical error", 
                       error=str(e), 
                       exc_info=True)
            return web.Response(text="ERROR", status=500)
    
    async def startup(self):
        """Application startup with automatic migrations"""
        try:
            logger.info("🚀 Starting Bot Factory", 
                       version=settings.app_version,
                       auto_migrations=True)
            
            # ✅ ВСЕГДА запускаем миграции перед инициализацией БД
            logger.info("🔄 Running automatic database migrations...")
            migration_success = await run_auto_migrations()
            
            if not migration_success:
                logger.error("💥 Database migrations failed! Application cannot start safely.")
                raise RuntimeError("Database migrations failed")
            
            logger.info("✅ Database migrations completed successfully")
            
            # Initialize database (this will create tables if they don't exist)
            logger.info("🔗 Initializing database connection...")
            await init_database()
            logger.info("✅ Database initialized successfully")
            
            # Initialize bot manager
            logger.info("🤖 Creating Bot Manager...")
            self.bot_manager = BotManager()
            logger.info("▶️ Starting Bot Manager...")
            await self.bot_manager.start()
            logger.info("✅ Bot Manager initialized successfully")
            
            # Initialize master bot
            logger.info("👑 Creating Master Bot...")
            self.master_bot = MasterBot(self.bot_manager)
            logger.info("✅ Master bot created successfully")
            
            # ✅ ИСПРАВЛЕНО: Запуск планировщика сброса лимитов ПОСЛЕ инициализации БД
            logger.info("⏰ Starting message limit scheduler...")
            try:
                from services.scheduler.message_limit_reset import message_limit_scheduler
                # Проверяем что планировщик готов к работе
                if hasattr(message_limit_scheduler, 'start'):
                    self.scheduler_task = asyncio.create_task(message_limit_scheduler.start())
                    logger.info("✅ Message limit scheduler started successfully")
                else:
                    logger.warning("⚠️ Message limit scheduler has no start method")
                    self.scheduler_task = None
            except ImportError as e:
                logger.error("💥 Failed to import message limit scheduler", error=str(e))
                self.scheduler_task = None
            except Exception as e:
                logger.error("💥 Failed to start message limit scheduler", error=str(e), exc_info=True)
                self.scheduler_task = None
            
            # ✅ ИСПРАВЛЕНО: Инициализация и запуск планировщика массовых рассылок с bot_manager
            logger.info("📨 Initializing Mass Broadcast Scheduler...")
            try:
                from database import db
                from services.mass_broadcast_scheduler import MassBroadcastScheduler
                
                # Проверяем что БД и bot_manager готовы
                if not db:
                    raise RuntimeError("Database not initialized")
                if not self.bot_manager:
                    raise RuntimeError("Bot manager not initialized")
                
                # ✅ ИСПРАВЛЕНО: Передаем bot_manager вместо master_bot.bot
                logger.info("✅ Initializing Mass Broadcast Scheduler with bot_manager...")
                self.mass_broadcast_scheduler = MassBroadcastScheduler(db, self.bot_manager)
                logger.info("✅ Mass Broadcast Scheduler initialized with bot_manager successfully")
                
                # Сразу запускаем планировщик
                logger.info("📨 Starting mass broadcast scheduler...")
                if hasattr(self.mass_broadcast_scheduler, 'start'):
                    self.mass_broadcast_scheduler_task = asyncio.create_task(
                        self.mass_broadcast_scheduler.start()
                    )
                    logger.info("✅ Mass broadcast scheduler started successfully")
                else:
                    logger.warning("⚠️ Mass broadcast scheduler has no start method")
                    self.mass_broadcast_scheduler = None
                    self.mass_broadcast_scheduler_task = None
                
            except ImportError as e:
                logger.warning("⚠️ Mass Broadcast Scheduler not available", error=str(e))
                self.mass_broadcast_scheduler = None
                self.mass_broadcast_scheduler_task = None
            except Exception as e:
                logger.error("💥 Failed to initialize/start Mass Broadcast Scheduler", 
                           error=str(e), exc_info=True)
                self.mass_broadcast_scheduler = None
                self.mass_broadcast_scheduler_task = None
            
            # Setup web server for health checks AND payments
            logger.info("🌐 Setting up web server with payment webhooks...")
            self.web_app = web.Application()
            
            # Health check routes
            self.web_app.router.add_get("/health", self.health_check)
            self.web_app.router.add_get("/", self.health_check)
            
            # Payment webhook routes
            self.web_app.router.add_post("/webhook/robokassa", self.robokassa_webhook)
            
            # Start web server
            self.web_runner = web_runner.AppRunner(self.web_app)
            await self.web_runner.setup()
            
            # Get port from environment or use default
            port = int(os.environ.get("PORT", 8080))
            site = web_runner.TCPSite(self.web_runner, "0.0.0.0", port)
            await site.start()
            
            logger.info("🌐 Web server started successfully with payment webhooks", 
                       port=port,
                       message_scheduler_running=self.scheduler_task is not None and not self.scheduler_task.done(),
                       mass_broadcast_scheduler_running=self.mass_broadcast_scheduler_task is not None and not self.mass_broadcast_scheduler_task.done(),
                       payment_amount=f"{settings.robokassa_payment_amount}₽",
                       subscription_days=settings.subscription_days_per_payment,
                       robokassa_production=not settings.robokassa_is_test,
                       robokassa_configured=bool(settings.robokassa_merchant_login and settings.robokassa_password2),
                       available_routes=[
                           "GET /health",
                           "GET /",
                           "POST /webhook/robokassa"
                       ])
            
            self.running = True
            logger.info("🎉 Bot Factory startup completed successfully!")
            
        except Exception as e:
            logger.error("💥 Failed to start Bot Factory", error=str(e), exc_info=True)
            await self.shutdown()
            raise
    
    async def shutdown(self):
        """Application shutdown"""
        logger.info("🛑 Shutting down Bot Factory")
        self.running = False
        
        try:
            # ✅ ИСПРАВЛЕНО: Остановка планировщика сброса лимитов
            if self.scheduler_task and not self.scheduler_task.done():
                logger.info("⏰ Stopping message limit scheduler...")
                self.scheduler_task.cancel()
                try:
                    await self.scheduler_task
                except asyncio.CancelledError:
                    logger.info("✅ Message limit scheduler stopped")
                except Exception as e:
                    logger.warning("⚠️ Error stopping scheduler", error=str(e))
            
            # ✅ ИСПРАВЛЕНО: Остановка планировщика массовых рассылок
            if self.mass_broadcast_scheduler_task and not self.mass_broadcast_scheduler_task.done():
                logger.info("📨 Stopping mass broadcast scheduler...")
                if self.mass_broadcast_scheduler and hasattr(self.mass_broadcast_scheduler, 'stop'):
                    try:
                        await self.mass_broadcast_scheduler.stop()
                    except Exception as e:
                        logger.warning("⚠️ Error stopping mass broadcast scheduler gracefully", error=str(e))
                
                self.mass_broadcast_scheduler_task.cancel()
                try:
                    await self.mass_broadcast_scheduler_task
                except asyncio.CancelledError:
                    logger.info("✅ Mass broadcast scheduler stopped")
                except Exception as e:
                    logger.warning("⚠️ Error stopping mass broadcast scheduler task", error=str(e))
            
            # ✅ ИСПРАВЛЕНО: Закрытие AI клиента
            try:
                from services.ai_assistant import ai_client
                if hasattr(ai_client, 'close'):
                    await ai_client.close()
                    logger.info("🤖 AI Assistant client closed")
            except ImportError:
                logger.debug("AI Assistant service not available, skipping client cleanup")
            except Exception as e:
                logger.warning("⚠️ Error closing AI client", error=str(e))
            
            # Stop master bot
            if self.master_bot:
                try:
                    await self.master_bot.stop()
                    logger.info("👑 Master bot stopped")
                except Exception as e:
                    logger.warning("⚠️ Error stopping master bot", error=str(e))
            
            # Stop bot manager
            if self.bot_manager:
                try:
                    await self.bot_manager.stop()
                    logger.info("🤖 Bot Manager stopped")
                except Exception as e:
                    logger.warning("⚠️ Error stopping bot manager", error=str(e))
            
            # Stop web server
            if self.web_runner:
                try:
                    await self.web_runner.cleanup()
                    logger.info("🌐 Web server stopped")
                except Exception as e:
                    logger.warning("⚠️ Error stopping web server", error=str(e))
            
            # Close database connections
            try:
                await close_database()
                logger.info("🔗 Database connections closed")
            except Exception as e:
                logger.warning("⚠️ Error closing database", error=str(e))
            
        except Exception as e:
            logger.error("💥 Error during shutdown", error=str(e), exc_info=True)
        
        logger.info("✅ Bot Factory shutdown completed")
    
    async def run(self):
        """Run the application"""
        try:
            await self.startup()
            
            if self.master_bot:
                # Run master bot
                await self.master_bot.start_polling()
            
        except (KeyboardInterrupt, SystemExit):
            logger.info("⚠️ Received exit signal")
        except Exception as e:
            logger.error("💥 Unexpected error", error=str(e), exc_info=True)
        finally:
            await self.shutdown()


def setup_signal_handlers(bot_factory: BotFactory):
    """Setup signal handlers for graceful shutdown"""
    
    def signal_handler(signum, frame):
        logger.info("📡 Received signal", signal=signum)
        # Create new event loop for shutdown if current one is closed
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            loop.create_task(bot_factory.shutdown())
        except Exception as e:
            logger.error("💥 Error in signal handler", error=str(e))
            sys.exit(1)
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


async def main():
    """Main application entry point"""
    
    # ✅ ИСПРАВЛЕНО: Валидация конфигурации с подробным логированием
    config_errors = []
    
    if not settings.master_bot_token:
        config_errors.append("MASTER_BOT_TOKEN is required")
    
    if not settings.database_url:
        config_errors.append("DATABASE_URL is required")
    
    if config_errors:
        for error in config_errors:
            logger.error(f"❌ {error}")
        sys.exit(1)
    
    # ✅ ИСПРАВЛЕНО: Подробное логирование среды
    logger.info("🚀 Starting Bot Factory Application", 
               environment="production" if not settings.debug else "development",
               database_host=settings.database_url.split('@')[-1].split('/')[0] if '@' in settings.database_url else "localhost",
               auto_migrations_enabled=True,
               payment_webhooks_enabled=True,
               robokassa_production=not settings.robokassa_is_test,
               robokassa_configured=bool(settings.robokassa_merchant_login and settings.robokassa_password2),
               payment_amount=f"{settings.robokassa_payment_amount}₽",
               subscription_days=settings.subscription_days_per_payment,
               tokens_per_purchase=settings.tokens_per_purchase if hasattr(settings, 'tokens_per_purchase') else "Not configured",
               python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
               platform=sys.platform)
    
    # Create and run bot factory
    bot_factory = BotFactory()
    setup_signal_handlers(bot_factory)
    
    try:
        await bot_factory.run()
    except Exception as e:
        logger.error("💥 Fatal error", error=str(e), exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    # ✅ ИСПРАВЛЕНО: Проверка версии Python с подробным сообщением
    if sys.version_info < (3, 8):
        print(f"❌ Python 3.8+ is required, current version: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
        sys.exit(1)
    
    # Set event loop policy for Windows
    if sys.platform.startswith('win'):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    # ✅ ИСПРАВЛЕНО: Запуск приложения с улучшенной обработкой ошибок
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⚠️ Application interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error("💥 Failed to run application", error=str(e), exc_info=True)
        sys.exit(1)
