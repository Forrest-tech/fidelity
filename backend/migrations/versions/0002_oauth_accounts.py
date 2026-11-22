"""oauth accounts (sign in with Google, Microsoft, GitHub or a company OpenID Connect provider)

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa
import fastapi_users_db_sqlalchemy


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('oauth_account',
    sa.Column('id', fastapi_users_db_sqlalchemy.generics.GUID(), nullable=False),
    sa.Column('oauth_name', sa.String(length=100), nullable=False),
    sa.Column('access_token', sa.String(length=1024), nullable=False),
    sa.Column('expires_at', sa.Integer(), nullable=True),
    sa.Column('refresh_token', sa.String(length=1024), nullable=True),
    sa.Column('account_id', sa.String(length=320), nullable=False),
    sa.Column('account_email', sa.String(length=320), nullable=False),
    sa.Column('user_id', fastapi_users_db_sqlalchemy.generics.GUID(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='cascade'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('oauth_account', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_oauth_account_oauth_name'), ['oauth_name'], unique=False)
        batch_op.create_index(batch_op.f('ix_oauth_account_account_id'), ['account_id'], unique=False)


def downgrade():
    with op.batch_alter_table('oauth_account', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_oauth_account_account_id'))
        batch_op.drop_index(batch_op.f('ix_oauth_account_oauth_name'))
    op.drop_table('oauth_account')
