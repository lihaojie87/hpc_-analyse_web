"""${message}"""
revision = '${up_revision}'
down_revision = ${repr(down_revision)}
from alembic import op
import sqlalchemy as sa

def upgrade():
    ${upgrades or 'return None'}

def downgrade():
    ${downgrades or 'return None'}
