"""Audit log: one append-only row per sensitive action.

Answers the question asked after an incident — who changed that credential,
who created that account, who edited those instructions. The business tables
hold the current state, never how it was reached.

``actor_label`` and ``target_label`` are denormalised on purpose: an audit row
that becomes unreadable once the account that produced it is deleted is
useless, and a deleted account is exactly the case someone will be reading it
for.

There is no column holding the detail of a change. Recording "what changed" on
a credential change means recording the credential.

The single index is named to match ``AuditLog.__table_args__`` in
``app/models.py`` exactly, and no column carries ``index=True`` — the test
schema comes from ``Base.metadata.create_all`` and the production schema comes
from here, so a name present in one and absent from the other is a divergence
CI is structurally unable to catch.

``agency_id`` is leftmost, so the same index serves both the agency-scoped read
and the ``ON DELETE CASCADE`` scan from ``agencies``.

Revision ID: 0030_audit_log
Revises: 0029_error_events
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0030_audit_log"
down_revision: str | None = "0029_error_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("actor_type", sa.String(length=20), nullable=False),
        # Null when the system itself acted, or when the account is long gone.
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_label", sa.String(length=180), nullable=False),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("target_label", sa.String(length=180), nullable=False),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_log_agency_id_created_at", "audit_log", ["agency_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_agency_id_created_at", table_name="audit_log")
    op.drop_table("audit_log")
