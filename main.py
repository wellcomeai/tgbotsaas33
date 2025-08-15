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
from services.scheduler.message_limit_reset import message_limit_scheduler

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
    """Main Bot Factory application"""
    
    def __init__(self):
        self.master_bot = None
        self.bot_manager = None
        self.web_app = None
        self.web_runner = None
        self.running = False
        self.scheduler_task = None
    
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
            "migrations_available": True,  # ✅ Теперь всегда доступны
            "scheduler_running": self.scheduler_task is not None and not self.scheduler_task.done()
        })
    
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
            
            # Setup web server for health checks
            logger.info("🌐 Setting up web server...")
            self.web_app = web.Application()
            self.web_app.router.add_get("/health", self.health_check)
            self.web_app.router.add_get("/", self.health_check)
            
            # Start web server
            self.web_runner = web_runner.AppRunner(self.web_app)
            await self.web_runner.setup()
            
            # Get port from environment or use default
            port = int(os.environ.get("PORT", 8080))
            site = web_runner.TCPSite(self.web_runner, "0.0.0.0", port)
            await site.start()
            
            logger.info("🌐 Web server started successfully", port=port)
            
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
            # ✅ NEW: Stop message limit scheduler
            if self.scheduler_task and not self.scheduler_task.done():
                logger.info("⏰ Stopping message limit scheduler...")
                self.scheduler_task.cancel()
                try:
                    await self.scheduler_task
                except asyncio.CancelledError:
                    logger.info("✅ Message limit scheduler stopped")
                except Exception as e:
                    logger.warning("⚠️ Error stopping scheduler", error=str(e))
            
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
    """Main application entry point"""
    
    # Validate configuration
    if not settings.master_bot_token:
        logger.error("❌ MASTER_BOT_TOKEN is required")
        sys.exit(1)
    
    if not settings.database_url:
        logger.error("❌ DATABASE_URL is required")
        sys.exit(1)
    
    # ✅ NEW: Log environment info for debugging
    logger.info("🚀 Starting Bot Factory", 
               environment="production" if not settings.debug else "development",
               database_url_host=settings.database_url.split('@')[-1].split('/')[0] if '@' in settings.database_url else "localhost",
               auto_migrations_enabled=True)  # ✅ Теперь всегда True
    
    # Create and run bot factory
    bot_factory = BotFactory()
    setup_signal_handlers(bot_factory)
    
    # ✅ NEW: Запускаем планировщик сброса лимитов
    logger.info("⏰ Starting message limit scheduler...")
    try:
        bot_factory.scheduler_task = asyncio.create_task(message_limit_scheduler.start())
        logger.info("✅ Message limit scheduler started successfully")
    except Exception as e:
        logger.error("💥 Failed to start message limit scheduler", error=str(e))
        # Продолжаем работу даже если планировщик не запустился
    
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
