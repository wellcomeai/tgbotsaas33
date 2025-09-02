"""Add button fields to user_bots table

Revision ID: 001
Revises: 
Create Date: 2025-01-04 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add button-related fields to user_bots table"""
    
    # Add new columns for button functionality
    op.add_column('user_bots', sa.Column('welcome_button_text', sa.String(255), nullable=True))
    op.add_column('user_bots', sa.Column('confirmation_message', sa.Text(), nullable=True))
    op.add_column('user_bots', sa.Column('goodbye_button_text', sa.String(255), nullable=True))
    op.add_column('user_bots', sa.Column('goodbye_button_url', sa.String(500), nullable=True))
    
    # Add indexes for better performance (optional but recommended)
    op.create_index(
        'idx_user_bots_welcome_button', 
        'user_bots', 
        ['welcome_button_text'], 
        postgresql_where=sa.text('welcome_button_text IS NOT NULL')
    )
    op.create_index(
        'idx_user_bots_goodbye_button', 
        'user_bots', 
        ['goodbye_button_text'], 
        postgresql_where=sa.text('goodbye_button_text IS NOT NULL')
    )


def downgrade() -> None:
    """Remove button-related fields from user_bots table"""
    
    # Drop indexes first
    op.drop_index('idx_user_bots_goodbye_button', table_name='user_bots')
    op.drop_index('idx_user_bots_welcome_button', table_name='user_bots')
    
    # Drop columns
    op.drop_column('user_bots', 'goodbye_button_url')
    op.drop_column('user_bots', 'goodbye_button_text')
    op.drop_column('user_bots', 'confirmation_message')
    op.drop_column('user_bots', 'welcome_button_text')
