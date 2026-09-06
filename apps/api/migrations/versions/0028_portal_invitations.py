"""Portal invitations: inviting someone into a department by e-mail.

A pending invitation is a row holding a SHA-256 digest of a single-use,
24-hour token — never the plaintext. Accepting one creates the ``PortalUser``;
until then no such row exists. ``department_id`` uses CASCADE here, unlike the
SET NULL used by ``portal_users.department_id`` and
``conversations.department_id`` (0027_departments): those columns mean
"supervisor, sees everything" for a real row with history, but SET NULL on a
*pending* invitation would silently widen a department-scoped invite into a
client-wide one the moment the department is deleted — a privilege escalation
caused by an unrelated delete. CASCADE fails closed; the invite is cheap to
re-issue.

Revision ID: 0028_portal_invitations
Revises: 0027_departments
"""

from alembic import op
import sqlalchemy as sa


revision = "0028_portal_invitations"
down_revision = "0027_departments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portal_invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        # CASCADE, not SET NULL: see the module docstring above (D5).
        sa.Column("department_id", sa.Uuid(), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_error", sa.String(length=200), nullable=True),
        # Deleting the admin who sent the invite must not delete the invite.
        sa.Column("invited_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_portal_invitations_client_id", "portal_invitations", ["client_id"])
    op.create_index("ix_portal_invitations_department_id", "portal_invitations", ["department_id"])
    # Lookup index for the accept endpoint and the structural single-row
    # guarantee a hash collision would otherwise only be a convention.
    op.create_index(
        "uq_portal_invitations_token_hash", "portal_invitations", ["token_hash"], unique=True
    )
    # Re-inviting the same address updates this same row (see
    # services/invitations.py), so only one pending invitation per e-mail per
    # client can ever exist; accepted rows are kept as an audit trail and are
    # excluded here on purpose.
    op.create_index(
        "uq_portal_invitations_client_email_pending",
        "portal_invitations",
        ["client_id", "email"],
        unique=True,
        postgresql_where=sa.text("accepted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_portal_invitations_client_email_pending", table_name="portal_invitations")
    op.drop_index("uq_portal_invitations_token_hash", table_name="portal_invitations")
    op.drop_index("ix_portal_invitations_department_id", table_name="portal_invitations")
    op.drop_index("ix_portal_invitations_client_id", table_name="portal_invitations")
    op.drop_table("portal_invitations")
