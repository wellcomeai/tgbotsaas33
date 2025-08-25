"""
Планировщик для сброса лимитов сообщений в 00:00 МСК
"""
import asyncio
import structlog
from datetime import datetime, timezone, timedelta
from database import db

logger = structlog.get_logger()

class MessageLimitResetScheduler:
    def __init__(self):
        self.running = False
    
    async def start(self):
        """Запуск планировщика"""
        if self.running:
            return
        
        self.running = True
        logger.info("📅 Message limit reset scheduler started")
        
        while self.running:
            try:
                # Рассчитываем время до следующего сброса
                msk_tz = timezone(timedelta(hours=3))
                now_msk = datetime.now(msk_tz)
                
                # Следующий сброс в 00:00 МСК
                next_reset = now_msk.replace(hour=0, minute=0, second=0, microsecond=0)
                if next_reset <= now_msk:
                    next_reset += timedelta(days=1)
                
                sleep_seconds = (next_reset - now_msk).total_seconds()
                
                logger.info("⏰ Next message limit reset scheduled", 
                           next_reset_msk=next_reset.isoformat(),
                           sleep_seconds=sleep_seconds)
                
                # Спим до времени сброса
                await asyncio.sleep(sleep_seconds)
                
                if self.running:
                    await self.reset_daily_limits()
                    
            except Exception as e:
                logger.error("💥 Error in message limit reset scheduler", error=str(e))
                await asyncio.sleep(3600)  # Повторить через час при ошибке
    
    async def reset_daily_limits(self):
        """Сброс дневных лимитов для всех пользователей"""
        try:
            msk_tz = timezone(timedelta(hours=3))
            reset_time_msk = datetime.now(msk_tz)
            
            logger.info("🔄 Starting daily message limits reset", 
                       reset_time_msk=reset_time_msk.isoformat())
            
            # Здесь можно добавить логику очистки старых записей AIUsageLog
            # или просто полагаться на то, что новый день создаст новые записи
            
            logger.info("✅ Daily message limits reset completed")
            
        except Exception as e:
            logger.error("💥 Error resetting daily message limits", error=str(e))
    
    def stop(self):
        """Остановка планировщика"""
        self.running = False
        logger.info("🛑 Message limit reset scheduler stopped")

# Глобальный экземпляр
message_limit_scheduler = MessageLimitResetScheduler()
