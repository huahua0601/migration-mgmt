"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-03-06
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(64), unique=True, nullable=False),
        sa.Column("password", sa.String(256), nullable=False),
        sa.Column("email", sa.String(128)),
        sa.Column("role", sa.String(20), nullable=False, server_default="user"),
        sa.Column("is_active", sa.SmallInteger, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "db_configs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("db_type", sa.String(20), nullable=False, comment="oracle / mysql / postgresql"),
        sa.Column("host", sa.String(256), nullable=False),
        sa.Column("port", sa.Integer, nullable=False, server_default="1521"),
        sa.Column("service_name", sa.String(128)),
        sa.Column("username", sa.String(128), nullable=False),
        sa.Column("password", sa.String(256), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("created_by", sa.BigInteger, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "snapshots",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("db_info", sa.JSON, comment="host, version, banner, db_name"),
        sa.Column("summary", sa.JSON, comment="schema_count, total_tables, total_objects, total_rows"),
        sa.Column("schema_list", sa.JSON, comment="list of schema names"),
        sa.Column("file_path", sa.String(512), nullable=False),
        sa.Column("file_size", sa.BigInteger, server_default="0"),
        sa.Column("uploaded_by", sa.BigInteger, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "comparison_tasks",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False, server_default="snapshot_vs_db", comment="snapshot_vs_db / db_vs_db"),
        sa.Column("source_snapshot_id", sa.BigInteger, sa.ForeignKey("snapshots.id")),
        sa.Column("source_db_id", sa.BigInteger, sa.ForeignKey("db_configs.id")),
        sa.Column("target_db_id", sa.BigInteger, sa.ForeignKey("db_configs.id")),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending", comment="pending/running/completed/failed"),
        sa.Column("progress", sa.Integer, nullable=False, server_default="0"),
        sa.Column("summary", sa.JSON),
        sa.Column("created_by", sa.BigInteger, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("started_at", sa.DateTime),
        sa.Column("finished_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "comparison_results",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.BigInteger, sa.ForeignKey("comparison_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("schema_name", sa.String(128), nullable=False),
        sa.Column("object_type", sa.String(50), nullable=False),
        sa.Column("object_name", sa.String(256), nullable=False),
        sa.Column("match_status", sa.String(20), nullable=False, comment="match/mismatch/source_only/target_only"),
        sa.Column("source_value", sa.Text),
        sa.Column("target_value", sa.Text),
        sa.Column("details", sa.JSON),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("idx_task_schema", "comparison_results", ["task_id", "schema_name"])
    op.create_index("idx_task_status", "comparison_results", ["task_id", "match_status"])

    op.execute(
        "INSERT INTO users (username, password, email, role) "
        "VALUES ('admin', '$2b$12$G6o9VzGo.uZcDMReBgoPBeiqCjt/K6bf3OExolXbm5.tXEmj3K8C6', "
        "'admin@example.com', 'admin')"
    )


def downgrade() -> None:
    op.drop_table("comparison_results")
    op.drop_table("comparison_tasks")
    op.drop_table("snapshots")
    op.drop_table("db_configs")
    op.drop_table("users")
