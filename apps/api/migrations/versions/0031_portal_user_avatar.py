"""Portal user avatar: the face behind a human reply.

A thread showed a name and nothing else, so a reply from a person and a reply
from the bot looked the same. The photo is what tells them apart at a glance —
the person's face when a human answers, the robot icon when the agent does.

Stored the same way as the client and agency logos: bytes in Postgres, next to
the row they belong to, with the column deferred on the model so an ordinary
query never drags them along.

No index: this is only ever read through a portal user already loaded by id.

Revision ID: 0031_portal_user_avatar
Revises: 0030_audit_log
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0031_portal_user_avatar"
down_revision: str | None = "0030_audit_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("portal_users", sa.Column("avatar_data", sa.LargeBinary(), nullable=True))
    op.add_column("portal_users", sa.Column("avatar_mime", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("portal_users", "avatar_mime")
    op.drop_column("portal_users", "avatar_data")
