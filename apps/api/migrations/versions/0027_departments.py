"""Departments: the WhatsApp entry menu and who owns a conversation.

A client's business is split into departments (treasury, accounting,
collections). The contact picks one from a menu on their first message, and
that department answers with its own agent. Portal users belong to one
department and only see its conversations; a user without one keeps seeing
everything, which is what every account created before this migration does.

Revision ID: 0027_departments
Revises: 0026_message_delivery
"""

from alembic import op
import sqlalchemy as sa


revision = "0027_departments"
down_revision = "0026_message_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=60), nullable=False),
        sa.Column("description", sa.String(length=72), nullable=False, server_default=""),
        sa.Column("is_entry", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "slug", name="uq_departments_client_slug"),
    )
    op.create_index("ix_departments_client_id", "departments", ["client_id"])
    op.create_index("ix_departments_agent_id", "departments", ["agent_id"])
    # One reception per client, enforced by the database: two entry departments
    # would leave the fallback route depending on row order.
    op.create_index(
        "uq_departments_client_entry",
        "departments",
        ["client_id"],
        unique=True,
        postgresql_where=sa.text("is_entry"),
    )

    op.add_column("portal_users", sa.Column("department_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_portal_users_department_id",
        "portal_users",
        "departments",
        ["department_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_portal_users_department_id", "portal_users", ["department_id"])

    op.add_column("conversations", sa.Column("department_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_conversations_department_id",
        "conversations",
        "departments",
        ["department_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_conversations_department_id", "conversations", ["department_id"])
    op.add_column("conversations", sa.Column("menu_sent_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "menu_sent_at")
    op.drop_index("ix_conversations_department_id", table_name="conversations")
    op.drop_constraint("fk_conversations_department_id", "conversations", type_="foreignkey")
    op.drop_column("conversations", "department_id")

    op.drop_index("ix_portal_users_department_id", table_name="portal_users")
    op.drop_constraint("fk_portal_users_department_id", "portal_users", type_="foreignkey")
    op.drop_column("portal_users", "department_id")

    op.drop_index("uq_departments_client_entry", table_name="departments")
    op.drop_index("ix_departments_agent_id", table_name="departments")
    op.drop_index("ix_departments_client_id", table_name="departments")
    op.drop_table("departments")
