import asyncio
import signal
import sys
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
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
from services.scheduler.message_limit_reset import message_limit_scheduler

# ✅ БЕЗОПАСНЫЕ ИМПОРТЫ для платежной системы
try:
    from services.payments.robokassa_service import robokassa_service
    from services.payments.subscription_manager import subscription_manager
    PAYMENTS_AVAILABLE = True
except ImportError as e:
    robokassa_service = None
    subscription_manager = None
    PAYMENTS_AVAILABLE = False
    structlog.get_logger().warning("Payment services not available", error=str(e))

try:
    from services.notifications.payment_notifier import payment_notifier
    PAYMENT_NOTIFIER_AVAILABLE = True
except ImportError as e:
    payment_notifier = None
    PAYMENT_NOTIFIER_AVAILABLE = False
    structlog.get_logger().warning("Payment notifier not available", error=str(e))

try:
    from services.scheduler.subscription_checker import subscription_checker
    SUBSCRIPTION_CHECKER_AVAILABLE = True
except ImportError as e:
    subscription_checker = None
    SUBSCRIPTION_CHECKER_AVAILABLE = False
    structlog.get_logger().warning("Subscription checker not available", error=str(e))

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
                ("external_settings", "JSONB")
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
    """Main Bot Factory application with full Robokassa integration"""
    
    def __init__(self):
        self.master_bot = None
        self.bot_manager = None
        self.web_app = None
        self.web_runner = None
        self.running = False
        
        # ✅ СУЩЕСТВУЮЩИЙ планировщик сообщений
        self.message_scheduler_task = None
        
        # ✅ НОВЫЙ планировщик подписок (если доступен)
        self.subscription_checker_task: Optional[asyncio.Task] = None
    
    async def startup(self):
        """Application startup with full payments integration"""
        try:
            logger.info("🚀 Starting Bot Factory with enhanced integration", 
                       version=settings.app_version,
                       payments_available=PAYMENTS_AVAILABLE,
                       payment_notifier_available=PAYMENT_NOTIFIER_AVAILABLE,
                       subscription_checker_available=SUBSCRIPTION_CHECKER_AVAILABLE)
            
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
            
            # ✅ НОВОЕ: Настраиваем payment_notifier если доступен
            if PAYMENT_NOTIFIER_AVAILABLE and payment_notifier and self.master_bot:
                payment_notifier.set_bot(self.master_bot.bot)
                logger.info("💬 Payment notifier configured with master bot")
            
            logger.info("✅ Master bot created successfully")
            
            # Setup web server for health checks
            logger.info("🌐 Setting up web server...")
            self.web_app = web.Application()
            self.web_app.router.add_get("/health", self.health_check)
            self.web_app.router.add_get("/", self.health_check)
            
            # ✅ НОВОЕ: Добавляем роуты для платежей (если доступны)
            if PAYMENTS_AVAILABLE:
                logger.info("💳 Adding payment webhook routes...")
                self.web_app.router.add_post("/webhook/robokassa", self.handle_robokassa_webhook)
                self.web_app.router.add_get("/payment/success", self.payment_success_page)
                self.web_app.router.add_get("/payment/fail", self.payment_fail_page)
                logger.info("✅ Payment routes added successfully")
            
            # Start web server
            self.web_runner = web_runner.AppRunner(self.web_app)
            await self.web_runner.setup()
            
            # Get port from environment or use default
            port = int(os.environ.get("PORT", 8080))
            site = web_runner.TCPSite(self.web_runner, "0.0.0.0", port)
            await site.start()
            
            logger.info("🌐 Web server started successfully", port=port)
            
            # ✅ НОВОЕ: Запускаем планировщик проверки подписок
            if SUBSCRIPTION_CHECKER_AVAILABLE and subscription_checker:
                logger.info("⏰ Starting subscription checker...")
                self.subscription_checker_task = asyncio.create_task(
                    subscription_checker.start()
                )
                logger.info("✅ Subscription checker started successfully")
            else:
                logger.warning("⚠️ Subscription checker not available")
            
            self.running = True
            logger.info("🎉 Bot Factory with full payment integration started successfully!")
            
        except Exception as e:
            logger.error("💥 Failed to start Bot Factory", error=str(e), exc_info=True)
            await self.shutdown()
            raise
    
    async def shutdown(self):
        """Application shutdown with payment services cleanup"""
        logger.info("🛑 Shutting down Bot Factory with payment services")
        self.running = False
        
        try:
            # ✅ СУЩЕСТВУЮЩИЙ: Stop message limit scheduler
            if self.message_scheduler_task and not self.message_scheduler_task.done():
                logger.info("⏰ Stopping message limit scheduler...")
                message_limit_scheduler.stop()
                try:
                    await self.message_scheduler_task
                except asyncio.CancelledError:
                    logger.info("✅ Message limit scheduler stopped")
                except Exception as e:
                    logger.warning("⚠️ Error stopping message scheduler", error=str(e))
            
            # ✅ НОВОЕ: Stop subscription checker (если доступен)
            if (SUBSCRIPTION_CHECKER_AVAILABLE and 
                subscription_checker and 
                self.subscription_checker_task and 
                not self.subscription_checker_task.done()):
                
                logger.info("⏰ Stopping subscription checker...")
                await subscription_checker.stop()
                try:
                    await self.subscription_checker_task
                except asyncio.CancelledError:
                    logger.info("✅ Subscription checker stopped")
                except Exception as e:
                    logger.warning("⚠️ Error stopping subscription checker", error=str(e))
            
            # ✅ NEW: Close AI client
            try:
                from services.ai_assistant import ai_client
                await ai_client.close()
                logger.info("🤖 AI Assistant client closed")
            except ImportError:
                logger.debug("AI Assistant service not available, skipping client cleanup")
            except Exception as e:
                logger.warning("Error closing AI client", error=str(e))
            
            # Stop master bot
            if self.master_bot:
                await self.master_bot.stop()
                logger.info("👑 Master bot stopped")
            
            # Stop bot manager
            if self.bot_manager:
                await self.bot_manager.stop()
                logger.info("🤖 Bot Manager stopped")
            
            # Stop web server
            if self.web_runner:
                await self.web_runner.cleanup()
                logger.info("🌐 Web server stopped")
            
            # Close database connections
            await close_database()
            logger.info("🔗 Database connections closed")
            
        except Exception as e:
            logger.error("💥 Error during shutdown", error=str(e))
        
        logger.info("✅ Bot Factory with payment services shutdown completed")
    
    # ✅ НОВЫЕ методы платежей (только если PAYMENTS_AVAILABLE)
    
    async def handle_robokassa_webhook(self, request):
        """Обработка webhook от Robokassa (только если платежи доступны)"""
        if not PAYMENTS_AVAILABLE:
            return web.Response(text="Payments not available", status=503)
        
        logger.info("📥 Received Robokassa webhook")
        
        try:
            # Получаем данные из запроса
            form_data = await request.post()
            webhook_data = dict(form_data)
            
            logger.info("🔍 Processing webhook data", order_id=webhook_data.get('InvId'))
            
            # Проверяем подпись
            if not robokassa_service.verify_webhook_signature(webhook_data):
                logger.error("❌ Invalid webhook signature")
                return web.Response(text="Invalid signature", status=400)
            
            # Обрабатываем успешную оплату
            result = await subscription_manager.process_successful_payment(webhook_data)
            
            if result.get('success'):
                logger.info("✅ Payment processed successfully", order_id=webhook_data.get('InvId'))
                
                # Отправляем уведомление пользователю
                if result.get('payment_data') and result.get('subscription'):
                    await self._notify_user_about_payment(
                        result['payment_data'], 
                        result['subscription']
                    )
                
                return web.Response(text="OK", status=200)
            else:
                logger.error("❌ Failed to process payment", error=result.get('error'))
                return web.Response(text="Processing failed", status=500)
            
        except Exception as e:
            logger.error("💥 Error processing webhook", error=str(e), exc_info=True)
            return web.Response(text="Internal error", status=500)
    
    async def payment_success_page(self, request):
        """Страница успешной оплаты"""
        if not PAYMENTS_AVAILABLE:
            return web.Response(text="Payments not available", status=503)
            
        return web.Response(text="""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Оплата прошла успешно!</title>
            <meta charset="utf-8">
            <style>
                body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
                .success { color: green; font-size: 24px; margin: 20px 0; }
                .info { color: #666; font-size: 16px; }
            </style>
        </head>
        <body>
            <div class="success">✅ Оплата прошла успешно!</div>
            <div class="info">
                Подписка активирована автоматически.<br>
                Вернитесь в Bot Factory и наслаждайтесь всеми возможностями!
            </div>
        </body>
        </html>
        """, content_type='text/html')
    
    async def payment_fail_page(self, request):
        """Страница неудачной оплаты"""
        if not PAYMENTS_AVAILABLE:
            return web.Response(text="Payments not available", status=503)
            
        return web.Response(text="""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Ошибка оплаты</title>
            <meta charset="utf-8">
            <style>
                body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
                .error { color: red; font-size: 24px; margin: 20px 0; }
                .info { color: #666; font-size: 16px; }
            </style>
        </head>
        <body>
            <div class="error">❌ Ошибка оплаты</div>
            <div class="info">
                Оплата не была завершена.<br>
                Пожалуйста, попробуйте еще раз или обратитесь в поддержку.
            </div>
        </body>
        </html>
        """, content_type='text/html')
    
    # ✅ ОБНОВЛЕННЫЙ метод _notify_user_about_payment
    async def _notify_user_about_payment(self, payment_data: dict, subscription: dict):
        """Уведомление пользователя об успешной оплате через payment_notifier"""
        if not PAYMENT_NOTIFIER_AVAILABLE or not payment_notifier:
            logger.warning("Payment notifier not available, skipping notification")
            return
            
        try:
            # Используем centralized payment notifier
            await payment_notifier.send_payment_success_notification(
                user_id=payment_data['user_id'],
                subscription=subscription,
                payment_data=payment_data
            )
            
            # ✅ НОВОЕ: Отправляем уведомление администратору (если настроен admin_chat_id)
            admin_chat_id = getattr(settings, 'admin_chat_id', None)
            if admin_chat_id:
                await payment_notifier.send_admin_payment_notification(
                    admin_chat_id=admin_chat_id,
                    payment_data=payment_data,
                    subscription=subscription
                )
            
        except Exception as e:
            logger.error("❌ Failed to notify about payment via payment_notifier",
                        error=str(e),
                        user_id=payment_data.get('user_id'))
    
    async def health_check(self, request):
        """Enhanced health check with full payment system status"""
        bot_statuses = {}
        if self.bot_manager:
            bot_statuses = self.bot_manager.get_all_bot_statuses()
        
        # Payment system stats (только если доступны)
        payment_stats = {}
        subscription_checker_stats = {}
        
        if PAYMENTS_AVAILABLE and subscription_manager:
            try:
                payment_stats = await subscription_manager.get_subscription_stats()
            except Exception as e:
                logger.warning("Failed to get payment stats for health check", error=str(e))
                payment_stats = {"error": str(e)}
        
        if SUBSCRIPTION_CHECKER_AVAILABLE and subscription_checker:
            try:
                subscription_checker_stats = await subscription_checker.get_stats()
            except Exception as e:
                logger.warning("Failed to get subscription checker stats", error=str(e))
                subscription_checker_stats = {"error": str(e)}
        
        return web.json_response({
            "status": "healthy",
            "app": settings.app_name,
            "version": settings.app_version,
            "running": self.running,
            "timestamp": datetime.now().isoformat(),
            
            # Bot stats
            "master_bot_running": self.master_bot is not None,
            "user_bots_count": len(bot_statuses),
            "active_user_bots": sum(1 for status in bot_statuses.values() if status.get('running', False)),
            "migrations_available": True,  # ✅ Теперь всегда доступны
            "message_scheduler_running": self.message_scheduler_task is not None and not self.message_scheduler_task.done(),
            
            # Payment system (только если доступно)
            "payments_available": PAYMENTS_AVAILABLE,
            "payment_notifier_available": PAYMENT_NOTIFIER_AVAILABLE,
            "subscription_checker_available": SUBSCRIPTION_CHECKER_AVAILABLE,
            "robokassa_integration": PAYMENTS_AVAILABLE,
            "robokassa_test_mode": getattr(settings, 'robokassa_test_mode', None) if PAYMENTS_AVAILABLE else None,
            "payment_notifier_configured": PAYMENT_NOTIFIER_AVAILABLE and payment_notifier and payment_notifier.bot is not None,
            "subscription_checker_running": subscription_checker.running if (SUBSCRIPTION_CHECKER_AVAILABLE and subscription_checker) else False,
            
            # Stats
            "payment_stats": payment_stats,
            "subscription_checker_stats": subscription_checker_stats,
            
            # API endpoints (зависят от доступности сервисов)
            "webhook_endpoints": [
                "/webhook/robokassa",
                "/payment/success", 
                "/payment/fail"
            ] if PAYMENTS_AVAILABLE else [],
            
            # Configuration
            "features": {
                "robokassa_payments": PAYMENTS_AVAILABLE,
                "subscription_management": PAYMENTS_AVAILABLE,
                "payment_notifications": PAYMENT_NOTIFIER_AVAILABLE,
                "expiry_warnings": SUBSCRIPTION_CHECKER_AVAILABLE,
                "admin_notifications": hasattr(settings, 'admin_chat_id'),
                "message_limit_scheduler": True  # всегда доступен
            }
        })
    
    async def run(self):
        """Run the application with all schedulers"""
        try:
            await self.startup()
            
            # ✅ СУЩЕСТВУЮЩИЙ: Запускаем планировщик сброса лимитов сообщений
            logger.info("⏰ Starting message limit scheduler...")
            try:
                self.message_scheduler_task = asyncio.create_task(message_limit_scheduler.start())
                logger.info("✅ Message limit scheduler started successfully")
            except Exception as e:
                logger.error("💥 Failed to start message limit scheduler", error=str(e))
            
            # ✅ НОВОЕ: Запускаем планировщик проверки подписок (если доступен)
            if SUBSCRIPTION_CHECKER_AVAILABLE and subscription_checker:
                logger.info("⏰ Starting subscription checker...")
                try:
                    self.subscription_checker_task = asyncio.create_task(subscription_checker.start())
                    logger.info("✅ Subscription checker started successfully")
                except Exception as e:
                    logger.error("💥 Failed to start subscription checker", error=str(e))
            
            if self.master_bot:
                # Run master bot
                await self.master_bot.start_polling()
            
        except (KeyboardInterrupt, SystemExit):
            logger.info("⚠️ Received exit signal")
        except Exception as e:
            logger.error("💥 Unexpected error", error=str(e))
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
    """Main application entry point with payment integration"""
    
    # Validate configuration
    if not settings.master_bot_token:
        logger.error("❌ MASTER_BOT_TOKEN is required")
        sys.exit(1)
    
    if not settings.database_url:
        logger.error("❌ DATABASE_URL is required")
        sys.exit(1)
    
    # ✅ НОВОЕ: Проверяем настройки Robokassa (только если платежи доступны)
    if PAYMENTS_AVAILABLE:
        if not all([
            getattr(settings, 'robokassa_merchant_login', None),
            getattr(settings, 'robokassa_password1', None), 
            getattr(settings, 'robokassa_password2', None),
            getattr(settings, 'webhook_base_url', None)
        ]):
            logger.error("❌ Robokassa configuration incomplete")
            logger.error("Required: ROBOKASSA_MERCHANT_LOGIN, ROBOKASSA_PASSWORD1, ROBOKASSA_PASSWORD2, WEBHOOK_BASE_URL")
            logger.error("Payments will be disabled")
            # Не останавливаем приложение, просто отключаем платежи
        else:
            # ✅ НОВОЕ: Логируем конфигурацию платежей
            logger.info("💳 Robokassa configuration loaded", 
                       merchant=settings.robokassa_merchant_login,
                       test_mode=getattr(settings, 'robokassa_test_mode', True),
                       webhook_url=f"{settings.webhook_base_url}/webhook/robokassa",
                       plans_count=len(getattr(settings, 'subscription_plans', {})))
    else:
        logger.info("💳 Payment services not available, running without Robokassa integration")
    
    # ✅ NEW: Log environment info for debugging
    logger.info("🚀 Starting Bot Factory", 
               environment="production" if not settings.debug else "development",
               database_url_host=settings.database_url.split('@')[-1].split('/')[0] if '@' in settings.database_url else "localhost",
               auto_migrations_enabled=True)  # ✅ Теперь всегда True
    
    # Create and run bot factory
    bot_factory = BotFactory()
    setup_signal_handlers(bot_factory)
    
    try:
        await bot_factory.run()
    except Exception as e:
        logger.error("💥 Fatal error", error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    # Check Python version
    if sys.version_info < (3, 8):
        print("❌ Python 3.8+ is required")
        sys.exit(1)
    
    # Set event loop policy for Windows
    if sys.platform.startswith('win'):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    # Run application
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⚠️ Application interrupted by user")
    except Exception as e:
        logger.error("💥 Failed to run application", error=str(e))
        sys.exit(1)

# ✅ ДОБАВИТЬ в конец файла
logger.info("🎉 Bot Factory main module loaded",
           payments_available=PAYMENTS_AVAILABLE,
           payment_notifier_available=PAYMENT_NOTIFIER_AVAILABLE,
           subscription_checker_available=SUBSCRIPTION_CHECKER_AVAILABLE)
