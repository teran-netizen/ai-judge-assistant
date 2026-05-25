"""add ab_group and promo_price to users"""
revision = '018'
down_revision = '017'

from alembic import op
import sqlalchemy as sa

def upgrade():
    op.add_column('users', sa.Column('ab_group', sa.String(30), nullable=True))
    op.add_column('users', sa.Column('promo_price', sa.Boolean, nullable=False, server_default='true'))

def downgrade():
    op.drop_column('users', 'promo_price')
    op.drop_column('users', 'ab_group')
