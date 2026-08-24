"""baseline: existing schema

Revision ID: 5e7b59f171ba
Revises: 
Create Date: 2026-08-20 07:37:39.206994

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5e7b59f171ba'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Originally a no-op: on the DB this was authored against, `documents`
    # and `document_ai_analyses` already existed via a pre-Alembic
    # Base.metadata.create_all() call, so there was nothing to generate here.
    # That assumption breaks a genuinely fresh database (e.g. a new Docker
    # deploy that runs `alembic upgrade head` before the app ever calls
    # create_all()): 5a6af93ccaa3's batch_alter_table('documents', ...) then
    # fails with NoSuchTableError because this revision never created it.
    # This recreates that original (pre-owner_id, pre-Document-Intelligence)
    # schema so the full chain applies cleanly from empty. Existing databases
    # already stamped past this revision are unaffected - Alembic never
    # re-runs a revision's upgrade() once a DB is past it.
    op.create_table('documents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('filename', sa.String(), nullable=False),
    sa.Column('filepath', sa.String(), nullable=False),
    sa.Column('uploaded_at', sa.DateTime(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('text', sa.Text(), nullable=True),
    sa.Column('character_count', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_documents_id'), 'documents', ['id'], unique=False)
    op.create_index(op.f('ix_documents_filename'), 'documents', ['filename'], unique=False)
    op.create_table('document_ai_analyses',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('document_id', sa.Integer(), nullable=False),
    sa.Column('provider', sa.String(), nullable=False),
    sa.Column('model', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('document_type', sa.String(), nullable=True),
    sa.Column('language', sa.String(), nullable=True),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('turkish_explanation', sa.Text(), nullable=True),
    sa.Column('important_dates', sa.Text(), nullable=True),
    sa.Column('extracted_entities', sa.Text(), nullable=True),
    sa.Column('raw_response', sa.Text(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_document_ai_analyses_id'), 'document_ai_analyses', ['id'], unique=False)
    op.create_index(op.f('ix_document_ai_analyses_document_id'), 'document_ai_analyses', ['document_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_document_ai_analyses_document_id'), table_name='document_ai_analyses')
    op.drop_index(op.f('ix_document_ai_analyses_id'), table_name='document_ai_analyses')
    op.drop_table('document_ai_analyses')
    op.drop_index(op.f('ix_documents_filename'), table_name='documents')
    op.drop_index(op.f('ix_documents_id'), table_name='documents')
    op.drop_table('documents')
