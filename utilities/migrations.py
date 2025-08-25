"""
Utilities for automatic database migrations on deployment
"""
import asyncio
import os
import sys
from pathlib import Path
from alembic.config import Config
from alembic import command
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine
import structlog

from config import settings

logger = structlog.get_logger()


class MigrationManager:
    """Manager for database migrations"""
    
    def __init__(self):
        self.project_root = Path(__file__).parent.parent
        self.alembic_cfg_path = self.project_root / "alembic.ini"
        
    def get_alembic_config(self) -> Config:
        """Get Alembic configuration"""
        if not self.alembic_cfg_path.exists():
            raise FileNotFoundError(f"Alembic config not found at {self.alembic_cfg_path}")
        
        # Create Alembic config
        alembic_cfg = Config(str(self.alembic_cfg_path))
        
        # Set database URL
        database_url = settings.database_url
        if database_url.startswith("postgresql://"):
            # For sync operations, use psycopg2
            sync_url = database_url.replace("postgresql://", "postgresql+psycopg2://")
        else:
            sync_url = database_url
        
        alembic_cfg.set_main_option("sqlalchemy.url", sync_url)
        
        return alembic_cfg
    
    async def check_database_connection(self) -> bool:
        """Check if database is accessible"""
        try:
            database_url = settings.database_url
            if database_url.startswith("postgresql://"):
                database_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
            
            engine = create_async_engine(database_url)
            
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            
            await engine.dispose()
            logger.info("Database connection successful")
            return True
            
        except Exception as e:
            logger.error("Database connection failed", error=str(e))
            return False
    
    def get_current_revision(self) -> str:
        """Get current database revision"""
        try:
            alembic_cfg = self.get_alembic_config()
            
            # Create sync engine for migration checks
            database_url = settings.database_url
            if database_url.startswith("postgresql://"):
                sync_url = database_url.replace("postgresql://", "postgresql+psycopg2://")
            else:
                sync_url = database_url
            
            engine = create_engine(sync_url)
            
            with engine.connect() as connection:
                context = MigrationContext.configure(connection)
                current_rev = context.get_current_revision()
            
            engine.dispose()
            return current_rev
            
        except Exception as e:
            logger.warning("Could not get current revision", error=str(e))
            return None
    
    def get_head_revision(self) -> str:
        """Get head revision from migration scripts"""
        try:
            alembic_cfg = self.get_alembic_config()
            script = ScriptDirectory.from_config(alembic_cfg)
            head_rev = script.get_current_head()
            return head_rev
            
        except Exception as e:
            logger.error("Could not get head revision", error=str(e))
            return None
    
    def needs_migration(self) -> bool:
        """Check if migration is needed"""
        try:
            current = self.get_current_revision()
            head = self.get_head_revision()
            
            logger.info("Migration status", 
                       current_revision=current, 
                       head_revision=head)
            
            if current is None and head is not None:
                logger.info("Database not initialized, migration needed")
                return True
            
            if current != head:
                logger.info("Database migration needed")
                return True
            
            logger.info("Database is up to date")
            return False
            
        except Exception as e:
            logger.error("Error checking migration status", error=str(e))
            return True  # Be safe and assume migration is needed
    
    def run_migrations(self) -> bool:
        """Run database migrations"""
        try:
            logger.info("Starting database migrations...")
            
            alembic_cfg = self.get_alembic_config()
            
            # Check if we need to create alembic_version table
            current_rev = self.get_current_revision()
            
            if current_rev is None:
                logger.info("Initializing database with Alembic...")
                # Stamp with base revision first, then upgrade
                command.stamp(alembic_cfg, "base")
            
            # Run migrations
            logger.info("Applying migrations...")
            command.upgrade(alembic_cfg, "head")
            
            # Verify migration success
            new_rev = self.get_current_revision()
            head_rev = self.get_head_revision()
            
            if new_rev == head_rev:
                logger.info("Migrations completed successfully", 
                           revision=new_rev)
                return True
            else:
                logger.error("Migration verification failed", 
                           current=new_rev, 
                           expected=head_rev)
                return False
                
        except Exception as e:
            logger.error("Migration failed", error=str(e), exc_info=True)
            return False
    
    async def auto_migrate(self) -> bool:
        """Automatically run migrations if needed"""
        logger.info("Checking for database migrations...")
        
        # Check database connection first
        if not await self.check_database_connection():
            logger.error("Cannot connect to database, skipping migrations")
            return False
        
        try:
            # Check if migration is needed
            if not self.needs_migration():
                logger.info("No migrations needed")
                return True
            
            # Run migrations
            logger.info("Running automatic migrations...")
            success = self.run_migrations()
            
            if success:
                logger.info("Automatic migrations completed successfully")
            else:
                logger.error("Automatic migrations failed")
            
            return success
            
        except Exception as e:
            logger.error("Auto migration error", error=str(e), exc_info=True)
            return False


# Global migration manager instance
migration_manager = MigrationManager()


async def run_auto_migrations() -> bool:
    """
    Run automatic migrations on application startup
    Returns True if successful or no migrations needed
    """
    return await migration_manager.auto_migrate()


def create_migration(message: str, autogenerate: bool = True) -> bool:
    """
    Create a new migration (for development use)
    """
    try:
        alembic_cfg = migration_manager.get_alembic_config()
        
        if autogenerate:
            command.revision(alembic_cfg, message=message, autogenerate=True)
        else:
            command.revision(alembic_cfg, message=message)
        
        logger.info("Migration created", message=message)
        return True
        
    except Exception as e:
        logger.error("Failed to create migration", error=str(e))
        return False


if __name__ == "__main__":
    """
    CLI interface for migrations
    Usage:
        python utilities/migrations.py migrate
        python utilities/migrations.py create "Add new field"
    """
    if len(sys.argv) < 2:
        print("Usage: python utilities/migrations.py [migrate|create] [message]")
        sys.exit(1)
    
    command_arg = sys.argv[1]
    
    if command_arg == "migrate":
        success = asyncio.run(run_auto_migrations())
        sys.exit(0 if success else 1)
    
    elif command_arg == "create":
        if len(sys.argv) < 3:
            print("Usage: python utilities/migrations.py create 'Migration message'")
            sys.exit(1)
        
        message = sys.argv[2]
        success = create_migration(message)
        sys.exit(0 if success else 1)
    
    else:
        print(f"Unknown command: {command_arg}")
        print("Available commands: migrate, create")
        sys.exit(1)
