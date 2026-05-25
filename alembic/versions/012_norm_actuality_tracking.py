"""Add norm actuality tracking fields + norm_history table

Adds per-article actuality tracking to legal_norms:
- content_hash: MD5 of text for change detection during re-parsing
- edition_date: when the norm text was last updated from source
- is_active: whether this norm is still in force (article-level)
- inactive_reason: why it was deactivated (e.g. "Утратила силу ФЗ от ...")
- replaced_by_id: FK to replacement norm if exists

Creates norm_history table for tracking changes over time.

Revision ID: 012
Revises: 011
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '012'
down_revision = '011'


def upgrade():
    # --- legal_norms: actuality fields ---
    op.add_column('legal_norms', sa.Column(
        'content_hash', sa.String(32), nullable=True,
        comment='MD5 hash of text for change detection',
    ))
    op.add_column('legal_norms', sa.Column(
        'edition_date', sa.DateTime, nullable=True,
        comment='When text was last updated from source',
    ))
    op.add_column('legal_norms', sa.Column(
        'is_active', sa.Boolean, server_default='true', nullable=False,
        comment='Whether this norm is still in force',
    ))
    op.add_column('legal_norms', sa.Column(
        'inactive_reason', sa.Text, nullable=True,
        comment='Why deactivated (e.g. Утратила силу ФЗ от ...)',
    ))
    op.add_column('legal_norms', sa.Column(
        'replaced_by_id', UUID(as_uuid=True), nullable=True,
    ))
    op.create_foreign_key(
        'fk_legal_norms_replaced_by',
        'legal_norms', 'legal_norms',
        ['replaced_by_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_index('ix_legal_norms_is_active', 'legal_norms', ['is_active'])
    op.create_index('ix_legal_norms_content_hash', 'legal_norms', ['content_hash'])

    # --- norm_history: change log ---
    op.create_table(
        'norm_history',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('norm_id', UUID(as_uuid=True), sa.ForeignKey('legal_norms.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('old_text', sa.Text, nullable=True),
        sa.Column('new_text', sa.Text, nullable=True),
        sa.Column('old_hash', sa.String(32), nullable=True),
        sa.Column('new_hash', sa.String(32), nullable=True),
        sa.Column('change_type', sa.String(30), nullable=False, comment='updated | deactivated | reactivated | created'),
        sa.Column('reason', sa.Text, nullable=True),
        sa.Column('changed_at', sa.DateTime, server_default=sa.text('NOW()'), nullable=False),
    )

    # Backfill content_hash for existing norms
    op.execute("""
        UPDATE legal_norms SET content_hash = md5(text)
        WHERE content_hash IS NULL AND text IS NOT NULL
    """)


def downgrade():
    op.drop_table('norm_history')
    op.drop_index('ix_legal_norms_content_hash', 'legal_norms')
    op.drop_index('ix_legal_norms_is_active', 'legal_norms')
    op.drop_constraint('fk_legal_norms_replaced_by', 'legal_norms', type_='foreignkey')
    op.drop_column('legal_norms', 'replaced_by_id')
    op.drop_column('legal_norms', 'inactive_reason')
    op.drop_column('legal_norms', 'is_active')
    op.drop_column('legal_norms', 'edition_date')
    op.drop_column('legal_norms', 'content_hash')
