"""Error events: one append-only row per captured failure.

Native site-health and error tracking — no external provider, no SDK, no
forwarding seam. ``agency_id`` is nullable on purpose: a failure that cannot
be tied to a tenant (pre-auth, startup, a background sweep) is stored anyway,
with ``agency_id IS NULL``, and is visible to every authenticated agency user
instead of vanishing silently.

Only two indexes exist, and both are named to match ``ErrorEvent.__table_args__``
in ``app/models.py`` exactly: a drifted name between the two is precisely the
W1 defect found verifying ``agent-invitation-email`` (the test schema comes
from ``Base.metadata.create_all``, the production schema from here, so a name
present in one and absent from the other makes CI structurally unable to
catch the difference). No column carries ``index=True`` for the same reason:
that would synthesize a third index this migration never creates.

``ix_error_events_agency_id_occurred_at`` has ``agency_id`` as its leftmost
column, so it serves both the agency-scoped read (Spec: Agency Scoping) and
the ``ON DELETE CASCADE`` scan from ``agencies`` — a separate single-column
index on ``agency_id`` alone would be redundant *and* would be the drift this
migration exists to avoid.

``occurred_at`` has no ``server_default``, mirroring the ``portal_invitations
.created_at`` precedent (0028_portal_invitations): the Python-side
``default=now_utc`` on the model is the only source of the value, so there is
nothing for the two sides to disagree about.

Revision ID: 0029_error_events
Revises: 0028_portal_invitations
"""

from alembic import op
import sqlalchemy as sa


revision = "0029_error_events"
down_revision = "0028_portal_invitations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "error_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        # Nullable: not every failure can be tied to a tenant (pre-auth,
        # startup, a background sweep). NULL is visible to every agency.
        sa.Column("agency_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.String(length=60), nullable=False),
        sa.Column("capture_kind", sa.String(length=20), nullable=False),
        sa.Column("exception_type", sa.String(length=120), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("traceback", sa.Text(), nullable=True),
        sa.Column("request_method", sa.String(length=10), nullable=True),
        sa.Column("request_path", sa.String(length=300), nullable=True),
        sa.Column("subject_ref", sa.String(length=120), nullable=True),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_error_events_occurred_at", "error_events", ["occurred_at"])
    op.create_index(
        "ix_error_events_agency_id_occurred_at", "error_events", ["agency_id", "occurred_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_error_events_agency_id_occurred_at", table_name="error_events")
    op.drop_index("ix_error_events_occurred_at", table_name="error_events")
    op.drop_table("error_events")
