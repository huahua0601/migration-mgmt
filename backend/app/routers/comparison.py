from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models import User, ComparisonTask, ComparisonResult, Snapshot
from app.schemas import ComparisonTaskCreate, ComparisonTaskOut, ComparisonResultOut
from app.utils.auth import get_current_user
from app.services.comparison import run_comparison
import threading

router = APIRouter(prefix="/api/comparisons", tags=["Comparisons"])


@router.get("", response_model=list[ComparisonTaskOut])
def list_tasks(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    tasks = (
        db.query(ComparisonTask)
        .options(
            joinedload(ComparisonTask.source_snapshot),
            joinedload(ComparisonTask.source_db),
            joinedload(ComparisonTask.target_db),
        )
        .order_by(ComparisonTask.id.desc())
        .all()
    )
    return tasks


@router.post("", response_model=ComparisonTaskOut, status_code=201)
def create_task(req: ComparisonTaskCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = ComparisonTask(
        name=req.name,
        mode=req.mode,
        source_snapshot_id=req.source_snapshot_id,
        source_db_id=req.source_db_id,
        target_db_id=req.target_db_id,
        status="pending",
        created_by=user.id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    thread = threading.Thread(target=run_comparison, args=(task.id, req.schemas), daemon=True)
    thread.start()
    return task


@router.get("/{tid}", response_model=ComparisonTaskOut)
def get_task(tid: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    task = (
        db.query(ComparisonTask)
        .options(
            joinedload(ComparisonTask.source_snapshot),
            joinedload(ComparisonTask.source_db),
            joinedload(ComparisonTask.target_db),
        )
        .filter(ComparisonTask.id == tid)
        .first()
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/{tid}/results", response_model=list[ComparisonResultOut])
def get_results(
    tid: int,
    schema_name: str = Query(None),
    object_type: str = Query(None),
    match_status: str = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(ComparisonResult).filter(ComparisonResult.task_id == tid)
    if schema_name:
        q = q.filter(ComparisonResult.schema_name == schema_name)
    if object_type:
        q = q.filter(ComparisonResult.object_type == object_type)
    if match_status:
        q = q.filter(ComparisonResult.match_status == match_status)
    return q.order_by(ComparisonResult.schema_name, ComparisonResult.object_type, ComparisonResult.object_name).all()


@router.get("/{tid}/summary")
def get_summary(tid: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    task = db.query(ComparisonTask).get(tid)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    results = db.query(ComparisonResult).filter(ComparisonResult.task_id == tid).all()

    by_schema = {}
    for r in results:
        s = by_schema.setdefault(r.schema_name, {"match": 0, "mismatch": 0, "source_only": 0, "target_only": 0, "by_type": {}})
        s[r.match_status] = s.get(r.match_status, 0) + 1
        t = s["by_type"].setdefault(r.object_type, {"match": 0, "mismatch": 0, "source_only": 0, "target_only": 0})
        t[r.match_status] = t.get(r.match_status, 0) + 1

    total = {"match": 0, "mismatch": 0, "source_only": 0, "target_only": 0}
    for s in by_schema.values():
        for k in total:
            total[k] += s.get(k, 0)

    return {"task_id": tid, "status": task.status, "progress": task.progress, "total": total, "by_schema": by_schema}


@router.delete("/{tid}")
def delete_task(tid: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    task = db.query(ComparisonTask).get(tid)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    db.delete(task)
    db.commit()
    return {"msg": "deleted"}
