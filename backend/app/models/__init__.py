from sqlalchemy import Column, BigInteger, String, Text, Integer, DateTime, SmallInteger, JSON, ForeignKey, func
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False)
    password = Column(String(256), nullable=False)
    email = Column(String(128))
    role = Column(String(20), nullable=False, default="user")
    is_active = Column(SmallInteger, nullable=False, default=1)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class DbConfig(Base):
    __tablename__ = "db_configs"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    db_type = Column(String(20), nullable=False)
    host = Column(String(256), nullable=False)
    port = Column(Integer, nullable=False, default=1521)
    service_name = Column(String(128))
    username = Column(String(128), nullable=False)
    password = Column(String(256), nullable=False)
    description = Column(Text)
    created_by = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    creator = relationship("User", foreign_keys=[created_by])


class Snapshot(Base):
    __tablename__ = "snapshots"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(256), nullable=False)
    db_info = Column(JSON, comment="host, version, banner, db_name from export")
    summary = Column(JSON, comment="schema_count, total_tables, total_objects, total_rows")
    schema_list = Column(JSON, comment="list of schema names")
    file_path = Column(String(512), nullable=False)
    file_size = Column(BigInteger, default=0)
    uploaded_by = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime, server_default=func.now())
    uploader = relationship("User", foreign_keys=[uploaded_by])


class ComparisonTask(Base):
    __tablename__ = "comparison_tasks"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(256), nullable=False)
    mode = Column(String(20), nullable=False, default="snapshot_vs_db", comment="snapshot_vs_db / db_vs_db / snapshot_vs_snapshot")
    source_snapshot_id = Column(BigInteger, ForeignKey("snapshots.id"), nullable=True)
    source_db_id = Column(BigInteger, ForeignKey("db_configs.id"), nullable=True)
    target_db_id = Column(BigInteger, ForeignKey("db_configs.id"), nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    progress = Column(Integer, nullable=False, default=0)
    summary = Column(JSON)
    created_by = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    source_snapshot = relationship("Snapshot", foreign_keys=[source_snapshot_id])
    source_db = relationship("DbConfig", foreign_keys=[source_db_id])
    target_db = relationship("DbConfig", foreign_keys=[target_db_id])
    creator = relationship("User", foreign_keys=[created_by])
    results = relationship("ComparisonResult", back_populates="task", cascade="all, delete-orphan")


class ComparisonResult(Base):
    __tablename__ = "comparison_results"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    task_id = Column(BigInteger, ForeignKey("comparison_tasks.id", ondelete="CASCADE"), nullable=False)
    schema_name = Column(String(128), nullable=False)
    object_type = Column(String(50), nullable=False)
    object_name = Column(String(256), nullable=False)
    match_status = Column(String(20), nullable=False)
    source_value = Column(Text)
    target_value = Column(Text)
    details = Column(JSON)
    created_at = Column(DateTime, server_default=func.now())
    task = relationship("ComparisonTask", back_populates="results")
