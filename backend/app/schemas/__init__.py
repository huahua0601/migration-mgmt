from pydantic import BaseModel
from typing import Optional
from datetime import datetime


# ── Auth ──
class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

# ── User ──
class UserCreate(BaseModel):
    username: str
    password: str
    email: Optional[str] = None
    role: str = "user"

class UserUpdate(BaseModel):
    email: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[int] = None

class UserPasswordUpdate(BaseModel):
    old_password: str
    new_password: str

class UserOut(BaseModel):
    id: int
    username: str
    email: Optional[str]
    role: str
    is_active: int
    created_at: datetime
    model_config = {"from_attributes": True}

# ── DbConfig ──
class DbTestRequest(BaseModel):
    db_type: str = "oracle"
    host: str
    port: int = 1521
    service_name: Optional[str] = None
    username: str
    password: str

class DbConfigCreate(BaseModel):
    name: str
    db_type: str = "oracle"
    host: str
    port: int = 1521
    service_name: Optional[str] = None
    username: str
    password: str
    description: Optional[str] = None

class DbConfigUpdate(BaseModel):
    name: Optional[str] = None
    db_type: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    service_name: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    description: Optional[str] = None

class DbConfigOut(BaseModel):
    id: int
    name: str
    db_type: str
    host: str
    port: int
    service_name: Optional[str]
    username: str
    description: Optional[str]
    created_by: Optional[int]
    created_at: datetime
    model_config = {"from_attributes": True}

# ── Snapshot ──
class SnapshotOut(BaseModel):
    id: int
    name: str
    db_info: Optional[dict]
    summary: Optional[dict]
    schema_list: Optional[list]
    file_size: int
    uploaded_by: Optional[int]
    created_at: datetime
    model_config = {"from_attributes": True}

# ── Comparison ──
class ComparisonTaskCreate(BaseModel):
    name: str
    mode: str = "snapshot_vs_db"
    source_snapshot_id: Optional[int] = None
    source_db_id: Optional[int] = None
    target_db_id: int
    schemas: Optional[list[str]] = None

class ComparisonTaskOut(BaseModel):
    id: int
    name: str
    mode: str
    source_snapshot_id: Optional[int] = None
    source_db_id: Optional[int] = None
    target_db_id: Optional[int]
    status: str
    progress: int
    summary: Optional[dict]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    created_at: datetime
    source_snapshot: Optional[SnapshotOut] = None
    source_db: Optional[DbConfigOut] = None
    target_db: Optional[DbConfigOut] = None
    model_config = {"from_attributes": True}

class ComparisonResultOut(BaseModel):
    id: int
    task_id: int
    schema_name: str
    object_type: str
    object_name: str
    match_status: str
    source_value: Optional[str]
    target_value: Optional[str]
    details: Optional[dict]
    created_at: datetime
    model_config = {"from_attributes": True}
