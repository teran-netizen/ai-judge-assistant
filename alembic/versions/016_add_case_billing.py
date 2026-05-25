"""Add case-based billing fields (A/B test)"""

revision = '016'
down_revision = '015'

from alembic import op
import sqlalchemy as sa


def upgrade():
    # User: billing model (A/B group)
    op.add_column('users', sa.Column('billing_model', sa.String(20), nullable=False, server_default='tokens'))
    # User: paid case credits
    op.add_column('users', sa.Column('paid_cases_left', sa.Integer(), nullable=False, server_default='0'))
    # User: subscription end date
    op.add_column('users', sa.Column('subscription_until', sa.DateTime(timezone=True), nullable=True))

    # Case: how it was paid for
    op.add_column('cases', sa.Column('billing_method', sa.String(30), nullable=True))

    # Transaction: purchase type for analytics
    op.add_column('transactions', sa.Column('purchase_type', sa.String(50), nullable=True))


def downgrade():
    op.drop_column('transactions', 'purchase_type')
    op.drop_column('cases', 'billing_method')
    op.drop_column('users', 'subscription_until')
    op.drop_column('users', 'paid_cases_left')
    op.drop_column('users', 'billing_model')
