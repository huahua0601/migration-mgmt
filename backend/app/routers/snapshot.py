import json
import os
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, Snapshot
from app.schemas import SnapshotOut
from app.utils.auth import get_current_user

UPLOAD_DIR = "/app/data/snapshots"
router = APIRouter(prefix="/api/snapshots", tags=["Snapshots"])


@router.get("", response_model=list[SnapshotOut])
def list_snapshots(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Snapshot).order_by(Snapshot.id.desc()).all()


@router.post("", response_model=SnapshotOut, status_code=201)
async def upload_snapshot(
    file: UploadFile = File(...),
    name: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Upload a snapshot JSON file exported by export_tool.py."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    content = await file.read()
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON file")

    if "snapshot_version" not in data or "schemas" not in data:
        raise HTTPException(status_code=400, detail="Not a valid snapshot file (missing snapshot_version or schemas)")

    file_path = os.path.join(UPLOAD_DIR, f"snapshot_{user.id}_{file.filename}")
    with open(file_path, "wb") as f:
        f.write(content)

    snap = Snapshot(
        name=name,
        db_info=data.get("db_info"),
        summary=data.get("summary"),
        schema_list=list(data.get("schemas", {}).keys()),
        file_path=file_path,
        file_size=len(content),
        uploaded_by=user.id,
    )
    db.add(snap)
    db.commit()
    db.refresh(snap)
    return snap


@router.get("/{sid}", response_model=SnapshotOut)
def get_snapshot(sid: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    snap = db.query(Snapshot).get(sid)
    if not snap:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return snap


@router.get("/{sid}/schemas")
def get_snapshot_schemas(sid: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    snap = db.query(Snapshot).get(sid)
    if not snap:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return {"schemas": snap.schema_list or []}


@router.get("/{sid}/detail")
def get_snapshot_detail(sid: int, schema: str = None, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Return parsed snapshot data. Optionally filter by schema."""
    snap = db.query(Snapshot).get(sid)
    if not snap:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    with open(snap.file_path, "r") as f:
        data = json.load(f)
    if schema:
        s = data.get("schemas", {}).get(schema)
        if not s:
            raise HTTPException(status_code=404, detail=f"Schema {schema} not in snapshot")
        return {"schema": schema, "data": {k: v for k, v in s.items() if k != "checksums"}, "stats": s.get("stats")}
    return {
        "db_info": data.get("db_info"),
        "summary": data.get("summary"),
        "schemas": {k: v.get("stats", {}) for k, v in data.get("schemas", {}).items()},
    }


@router.delete("/{sid}")
def delete_snapshot(sid: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    snap = db.query(Snapshot).get(sid)
    if not snap:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    from app.models import ComparisonTask, ComparisonResult
    tasks = db.query(ComparisonTask).filter(ComparisonTask.source_snapshot_id == sid).all()
    for t in tasks:
        db.query(ComparisonResult).filter(ComparisonResult.task_id == t.id).delete()
        db.delete(t)

    try:
        os.remove(snap.file_path)
    except FileNotFoundError:
        pass
    db.delete(snap)
    db.commit()
    return {"msg": "deleted"}
