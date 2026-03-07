from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, DbConfig
from app.schemas import DbConfigCreate, DbConfigUpdate, DbConfigOut, DbTestRequest
from app.utils.auth import get_current_user
import oracledb

router = APIRouter(prefix="/api/db-configs", tags=["Database Configs"])


@router.post("/test-connection")
def test_connection_direct(req: DbTestRequest, _: User = Depends(get_current_user)):
    """Test database connectivity without saving the config first."""
    try:
        if req.db_type == "oracle":
            dsn = f"{req.host}:{req.port}/{req.service_name}"
            conn = oracledb.connect(user=req.username, password=req.password, dsn=dsn)
            cur = conn.cursor()
            cur.execute("SELECT banner FROM v$version WHERE ROWNUM = 1")
            banner = cur.fetchone()[0]
            cur.execute("SELECT sys_context('USERENV', 'DB_NAME') FROM dual")
            db_name = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM all_users")
            user_count = cur.fetchone()[0]
            version = conn.version
            cur.close()
            conn.close()
            return {
                "status": "ok",
                "version": version,
                "banner": banner,
                "db_name": db_name,
                "user_count": user_count,
            }
        else:
            return {"status": "error", "detail": f"暂不支持 {req.db_type} 类型"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@router.get("", response_model=list[DbConfigOut])
def list_configs(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(DbConfig).order_by(DbConfig.id).all()


@router.post("", response_model=DbConfigOut, status_code=201)
def create_config(req: DbConfigCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    cfg = DbConfig(**req.model_dump(), created_by=user.id)
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg


@router.get("/{cid}", response_model=DbConfigOut)
def get_config(cid: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    cfg = db.query(DbConfig).get(cid)
    if not cfg:
        raise HTTPException(status_code=404, detail="Config not found")
    return cfg


@router.put("/{cid}", response_model=DbConfigOut)
def update_config(cid: int, req: DbConfigUpdate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    cfg = db.query(DbConfig).get(cid)
    if not cfg:
        raise HTTPException(status_code=404, detail="Config not found")
    for k, v in req.model_dump(exclude_unset=True).items():
        setattr(cfg, k, v)
    db.commit()
    db.refresh(cfg)
    return cfg


@router.delete("/{cid}")
def delete_config(cid: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    cfg = db.query(DbConfig).get(cid)
    if not cfg:
        raise HTTPException(status_code=404, detail="Config not found")
    db.delete(cfg)
    db.commit()
    return {"msg": "deleted"}


@router.post("/{cid}/test")
def test_connection(cid: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    cfg = db.query(DbConfig).get(cid)
    if not cfg:
        raise HTTPException(status_code=404, detail="Config not found")
    try:
        if cfg.db_type == "oracle":
            dsn = f"{cfg.host}:{cfg.port}/{cfg.service_name}"
            conn = oracledb.connect(user=cfg.username, password=cfg.password, dsn=dsn)
            version = conn.version
            conn.close()
            return {"status": "ok", "version": version}
        else:
            return {"status": "error", "detail": f"Unsupported db_type: {cfg.db_type}"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@router.get("/{cid}/schemas")
def list_schemas(cid: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """List available schemas/users from the database."""
    cfg = db.query(DbConfig).get(cid)
    if not cfg:
        raise HTTPException(status_code=404, detail="Config not found")
    try:
        dsn = f"{cfg.host}:{cfg.port}/{cfg.service_name}"
        conn = oracledb.connect(user=cfg.username, password=cfg.password, dsn=dsn)
        cur = conn.cursor()
        cur.execute("""
            SELECT username FROM all_users
            WHERE username NOT IN ('SYS','SYSTEM','DBSNMP','OUTLN','XDB','WMSYS','CTXSYS',
                'ANONYMOUS','MDSYS','OLAPSYS','ORDDATA','ORDPLUGINS','ORDSYS','SI_INFORMTN_SCHEMA',
                'APEX_PUBLIC_USER','APPQOSSYS','DVSYS','LBACSYS','RDSADMIN','GSMADMIN_INTERNAL',
                'DIP','ORACLE_OCM','XS$NULL','REMOTE_SCHEDULER_AGENT','GGSYS','DBSFWUSER',
                'GSMCATUSER','SYSBACKUP','SYSDG','SYSKM','SYSRAC','SYS$UMF','AUDSYS')
            ORDER BY username
        """)
        schemas = [r[0] for r in cur]
        cur.close()
        conn.close()
        return {"schemas": schemas}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
