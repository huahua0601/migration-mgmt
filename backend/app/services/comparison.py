"""
Comparison engine: supports snapshot-vs-db and db-vs-db modes.

Snapshot-vs-DB: reads source metadata from an imported JSON snapshot file,
connects to the target DB live, and compares all objects and data.
"""

import json
import logging
import traceback
from datetime import datetime
from typing import Optional

import oracledb
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import DbConfig, Snapshot, ComparisonTask, ComparisonResult

logger = logging.getLogger(__name__)


def _connect(cfg: DbConfig):
    dsn = f"{cfg.host}:{cfg.port}/{cfg.service_name}"
    return oracledb.connect(user=cfg.username, password=cfg.password, dsn=dsn)


def _save(db: Session, task_id: int, schema: str, obj_type: str, obj_name: str,
          status: str, src_val: str = None, tgt_val: str = None, details: dict = None):
    db.add(ComparisonResult(
        task_id=task_id, schema_name=schema, object_type=obj_type, object_name=obj_name,
        match_status=status, source_value=src_val, target_value=tgt_val, details=details,
    ))


# ─── Target DB live query helpers ───

def _tgt_tables(conn, schema: str) -> dict:
    cur = conn.cursor()
    cur.execute("SELECT table_name FROM all_tables WHERE owner=:s ORDER BY table_name", {"s": schema})
    result = {r[0]: True for r in cur}
    cur.close()
    return result


def _tgt_columns(conn, schema: str) -> list[dict]:
    cur = conn.cursor()
    cur.execute("""
        SELECT table_name, column_name, data_type, data_length, data_precision, data_scale, nullable, column_id
        FROM all_tab_columns WHERE owner=:s ORDER BY table_name, column_id
    """, {"s": schema})
    result = [{"table_name": r[0], "column_name": r[1], "data_type": r[2], "data_length": r[3],
               "data_precision": r[4], "data_scale": r[5], "nullable": r[6], "column_id": r[7]} for r in cur]
    cur.close()
    return result


def _tgt_constraints(conn, schema: str) -> list[dict]:
    cur = conn.cursor()
    cur.execute("""
        SELECT table_name, constraint_name, constraint_type, search_condition, r_constraint_name, status, validated
        FROM all_constraints WHERE owner=:s AND constraint_name NOT LIKE 'SYS_%' ORDER BY table_name, constraint_name
    """, {"s": schema})
    result = [{"table_name": r[0], "constraint_name": r[1], "constraint_type": r[2],
               "search_condition": str(r[3]) if r[3] else None, 
               "r_constraint_name": r[4], "status": r[5], "validated": r[6]} for r in cur]
    cur.close()
    return result


def _tgt_objects(conn, schema: str, obj_type: str, sql: str) -> dict:
    cur = conn.cursor()
    cur.execute(sql, {"s": schema})
    cols = [d[0].lower() for d in cur.description]
    result = {}
    for row in cur:
        d = dict(zip(cols, row))
        name_key = cols[0]
        result[d[name_key]] = d
    cur.close()
    return result


def _tgt_source_code(conn, schema: str, name: str, obj_type: str) -> str:
    cur = conn.cursor()
    cur.execute("SELECT text FROM all_source WHERE owner=:s AND name=:n AND type=:t ORDER BY line",
                {"s": schema, "n": name, "t": obj_type})
    lines = [r[0] for r in cur]
    cur.close()
    return "".join(lines).strip()


def _tgt_row_count(conn, schema: str, table: str) -> int:
    cur = conn.cursor()
    try:
        cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"')
        return cur.fetchone()[0]
    except Exception:
        return -1
    finally:
        cur.close()


def _tgt_checksum(conn, schema: str, table: str, limit: int = 1000) -> Optional[str]:
    """Server-side ORA_HASH checksum matching the export tool's algorithm."""
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT column_name FROM all_tab_columns
            WHERE owner = :s AND table_name = :t ORDER BY column_id
        """, {"s": schema, "t": table})
        cols = [r[0] for r in cur]
        if not cols:
            return None
        ora_expr = " || '|' || ".join(
            f'NVL(TO_CHAR("{c}"), \'\')'  for c in cols
        )
        sql = (
            f'SELECT SUM(ORA_HASH({ora_expr})), COUNT(*) '
            f'FROM (SELECT * FROM "{schema}"."{table}" '
            f'WHERE ROWNUM <= {limit})'
        )
        cur.execute(sql)
        row = cur.fetchone()
        hash_sum = row[0] if row else None
        sample_cnt = row[1] if row else 0
        return f"{hash_sum}:{sample_cnt}" if hash_sum is not None else None
    except Exception:
        return None
    finally:
        cur.close()


# ─── Group helpers ───

def _group_by(items: list[dict], key: str) -> dict[str, list[dict]]:
    grouped = {}
    for item in items:
        grouped.setdefault(item.get(key), []).append(item)
    return grouped


# ─── Compare: snapshot schema vs live target ───

def _compare_simple_objects(db, task_id, schema, obj_type, src_items, tgt_items, name_key, ignore_keys=None):
    """Compare simple objects by name; items are lists of dicts."""
    _ignore = set(ignore_keys or [])

    def _normalize(d, skip_name_key=True):
        out = {}
        for k, v in d.items():
            if (skip_name_key and k == name_key) or k in _ignore or v is None:
                continue
            if hasattr(v, 'read'):
                v = v.read()
            if isinstance(v, str):
                v = v.strip()
            out[k] = v
        return out

    src_map = {item[name_key]: item for item in src_items}
    tgt_map = {item[name_key]: item for item in tgt_items}
    all_names = sorted(set(src_map) | set(tgt_map))
    for name in all_names:
        s, t = src_map.get(name), tgt_map.get(name)
        if s and t:
            s_clean = _normalize(s)
            t_clean = _normalize(t)
            status = "match" if s_clean == t_clean else "mismatch"
            _save(db, task_id, schema, obj_type, name, status,
                  json.dumps(s_clean, default=str)[:2000],
                  json.dumps(t_clean, default=str)[:2000])
        elif s:
            _save(db, task_id, schema, obj_type, name, "source_only",
                  src_val=json.dumps(s, default=str)[:2000])
        else:
            _save(db, task_id, schema, obj_type, name, "target_only",
                  tgt_val=json.dumps(t, default=str)[:2000])


def _is_sys_name(name: str) -> bool:
    """判断是否为 Oracle 系统自动生成的约束名（如 SYS_C0017605）。"""
    return name is not None and name.upper().startswith("SYS_")


def _normalize_constraint(c: dict) -> dict:
    """
    标准化约束记录用于比较。
    对 r_constraint_name 字段：若为系统命名（SYS_*），替换为占位符 '__SYS_NAMED__'，
    避免迁移后系统约束名变更导致误报 mismatch。
    """
    result = {}
    for k, v in c.items():
        if k == "constraint_name":
            continue  # 主键，不作为值参与比较
        if v is None:
            continue
        if hasattr(v, 'read'):
            v = v.read()
        if isinstance(v, str):
            v = v.strip()
        if k == "r_constraint_name" and _is_sys_name(v):
            v = "__SYS_NAMED__"
        result[k] = v
    return result


def _compare_constraints(db: Session, task_id: int, schema: str,
                         src_items: list[dict], tgt_items: list[dict]):
    """
    专用约束比较函数，解决迁移后 r_constraint_name（被引用主键约束名）
    由 Oracle 自动重命名（SYS_C*）导致误报 mismatch 的问题。

    规则：若源/目标的 r_constraint_name 都以 SYS_ 开头，视为等价，
    只比较其余字段（table_name, constraint_type, status, validated 等）。
    """
    src_map = {item["constraint_name"]: item for item in src_items}
    tgt_map = {item["constraint_name"]: item for item in tgt_items}
    all_names = sorted(set(src_map) | set(tgt_map))
    for name in all_names:
        s, t = src_map.get(name), tgt_map.get(name)
        if s and t:
            s_clean = _normalize_constraint(s)
            t_clean = _normalize_constraint(t)
            status = "match" if s_clean == t_clean else "mismatch"
            _save(db, task_id, schema, "CONSTRAINT", name, status,
                  json.dumps(s_clean, default=str)[:2000],
                  json.dumps(t_clean, default=str)[:2000])
        elif s:
            _save(db, task_id, schema, "CONSTRAINT", name, "source_only",
                  src_val=json.dumps(s, default=str)[:2000])
        else:
            _save(db, task_id, schema, "CONSTRAINT", name, "target_only",
                  tgt_val=json.dumps(t, default=str)[:2000])


def _compare_schema_snapshot_vs_db(db: Session, task_id: int, schema: str,
                                    src_data: dict, tgt_conn):
    """Compare a single schema: snapshot (source) vs live DB (target)."""

    # ── Tables ──
    src_tables = {t["table_name"]: t for t in src_data.get("tables", [])}
    tgt_tables = _tgt_tables(tgt_conn, schema)
    all_table_names = sorted(set(src_tables) | set(tgt_tables))

    for tbl in all_table_names:
        if tbl not in tgt_tables:
            _save(db, task_id, schema, "TABLE", tbl, "source_only")
            continue
        if tbl not in src_tables:
            _save(db, task_id, schema, "TABLE", tbl, "target_only")
            continue
        _save(db, task_id, schema, "TABLE", tbl, "match")

    # ── Columns ──
    src_cols_by_table = _group_by(src_data.get("columns", []), "table_name")
    tgt_cols = _tgt_columns(tgt_conn, schema)
    tgt_cols_by_table = _group_by(tgt_cols, "table_name")

    for tbl in sorted(set(src_cols_by_table) | set(tgt_cols_by_table)):
        sc = src_cols_by_table.get(tbl, [])
        tc = tgt_cols_by_table.get(tbl, [])
        normalize = lambda lst: [
            {k: v for k, v in c.items() if k != "table_name" and k != "data_default" and v is not None}
            for c in lst
        ]
        if normalize(sc) == normalize(tc):
            _save(db, task_id, schema, "COLUMN", tbl, "match", f"{len(sc)} cols", f"{len(tc)} cols")
        else:
            _save(db, task_id, schema, "COLUMN", tbl, "mismatch",
                  f"{len(sc)} cols", f"{len(tc)} cols",
                  {"source_cols": [c.get("column_name") for c in sc],
                   "target_cols": [c.get("column_name") for c in tc]})

    # ── Constraints ──
    src_con = src_data.get("constraints", [])
    tgt_con_raw = _tgt_constraints(tgt_conn, schema)
    _compare_constraints(db, task_id, schema, src_con, tgt_con_raw)

    # ── Indexes ──
    src_idx = src_data.get("indexes", [])
    cur = tgt_conn.cursor()
    cur.execute("""SELECT index_name, table_name, index_type, uniqueness, tablespace_name, status
                   FROM all_indexes WHERE owner=:s AND index_name NOT LIKE 'SYS_%' ORDER BY index_name""", {"s": schema})
    tgt_idx = [dict(zip(["index_name", "table_name", "index_type", "uniqueness", "tablespace_name", "status"], r)) for r in cur]
    cur.close()
    _compare_simple_objects(db, task_id, schema, "INDEX", src_idx, tgt_idx, "index_name")

    # ── Views ──
    src_views = {v["view_name"]: v for v in src_data.get("views", [])}
    cur = tgt_conn.cursor()
    cur.execute("SELECT view_name, text FROM all_views WHERE owner=:s ORDER BY view_name", {"s": schema})
    tgt_views = {r[0]: {"view_name": r[0], "text": r[1]} for r in cur}
    cur.close()
    for name in sorted(set(src_views) | set(tgt_views)):
        s, t = src_views.get(name), tgt_views.get(name)
        if s and t:
            s_text = (s.get("text") or "").strip()
            t_text = (t.get("text") or "").strip()
            status = "match" if s_text == t_text else "mismatch"
            _save(db, task_id, schema, "VIEW", name, status, s_text[:2000], t_text[:2000])
        elif s:
            _save(db, task_id, schema, "VIEW", name, "source_only")
        else:
            _save(db, task_id, schema, "VIEW", name, "target_only")

    # ── Sequences (exclude dynamic field: last_number) ──
    SEQUENCE_IGNORE = {"last_number"}
    src_seq = [
        {k: v for k, v in s.items() if k not in SEQUENCE_IGNORE}
        for s in src_data.get("sequences", [])
    ]
    cur = tgt_conn.cursor()
    cur.execute("""SELECT sequence_name, min_value, max_value, increment_by, cycle_flag, order_flag, cache_size
                   FROM all_sequences WHERE sequence_owner=:s AND sequence_name NOT LIKE 'ISEQ$$_%' ORDER BY sequence_name""", {"s": schema})
    tgt_seq = [dict(zip(["sequence_name", "min_value", "max_value", "increment_by", "cycle_flag", "order_flag", "cache_size"], r)) for r in cur]
    cur.close()
    _compare_simple_objects(db, task_id, schema, "SEQUENCE", src_seq, tgt_seq, "sequence_name")

    # ── Code objects: FUNCTION, PROCEDURE, PACKAGE ──
    for obj_type, src_key in [("FUNCTION", "functions"), ("PROCEDURE", "procedures"), ("PACKAGE", "packages")]:
        src_code = {item["name"]: item["source"] for item in src_data.get(src_key, [])}
        cur = tgt_conn.cursor()
        cur.execute("SELECT DISTINCT name FROM all_source WHERE owner=:s AND type=:t ORDER BY name", {"s": schema, "t": obj_type})
        tgt_names = [r[0] for r in cur]
        cur.close()
        all_names = sorted(set(src_code) | set(tgt_names))
        for name in all_names:
            s = src_code.get(name)
            if name in tgt_names:
                t = _tgt_source_code(tgt_conn, schema, name, obj_type)
            else:
                t = None
            if s is not None and t is not None:
                status = "match" if s.strip() == t.strip() else "mismatch"
                _save(db, task_id, schema, obj_type, name, status, s[:2000], t[:2000])
            elif s is not None:
                _save(db, task_id, schema, obj_type, name, "source_only", src_val=s[:2000])
            else:
                _save(db, task_id, schema, obj_type, name, "target_only", tgt_val=t[:2000] if t else None)

    # ── Triggers ──
    src_trg = {t["trigger_name"]: t for t in src_data.get("triggers", [])}
    cur = tgt_conn.cursor()
    cur.execute("SELECT trigger_name, trigger_type, triggering_event, table_name, status FROM all_triggers WHERE owner=:s ORDER BY trigger_name", {"s": schema})
    tgt_trg = {r[0]: {"trigger_name": r[0], "trigger_type": r[1], "triggering_event": r[2], "table_name": r[3], "status": r[4]} for r in cur}
    cur.close()
    for name in sorted(set(src_trg) | set(tgt_trg)):
        s, t = src_trg.get(name), tgt_trg.get(name)
        if s and t:
            _save(db, task_id, schema, "TRIGGER", name,
                  "match" if s.get("trigger_type") == t.get("trigger_type") and s.get("triggering_event") == t.get("triggering_event") else "mismatch",
                  json.dumps(s, default=str)[:2000], json.dumps(t, default=str)[:2000])
        elif s:
            _save(db, task_id, schema, "TRIGGER", name, "source_only")
        else:
            _save(db, task_id, schema, "TRIGGER", name, "target_only")

    # ── Types, Synonyms, MVIEWs, DB Links ──
    for obj_type, src_key, name_key, tgt_sql in [
        ("TYPE", "types", "type_name",
         "SELECT type_name, typecode, attributes, methods FROM all_types WHERE owner=:s AND type_name NOT LIKE 'SYS_%' ORDER BY type_name"),
        ("SYNONYM", "synonyms", "synonym_name",
         "SELECT synonym_name, table_owner, table_name, db_link FROM all_synonyms WHERE owner=:s ORDER BY synonym_name"),
        ("MVIEW", "mviews", "mview_name",
         "SELECT mview_name, container_name, query, refresh_mode, refresh_method FROM all_mviews WHERE owner=:s ORDER BY mview_name"),
        ("DB_LINK", "db_links", "db_link",
         "SELECT db_link, username, host FROM all_db_links WHERE owner=:s ORDER BY db_link"),
    ]:
        ignore = {"last_refresh_date"} if obj_type == "MVIEW" else None
        src_items = src_data.get(src_key, [])
        cur = tgt_conn.cursor()
        cur.execute(tgt_sql, {"s": schema})
        cols = [d[0].lower() for d in cur.description]
        tgt_items = [dict(zip(cols, r)) for r in cur]
        cur.close()
        _compare_simple_objects(db, task_id, schema, obj_type, src_items, tgt_items, name_key, ignore_keys=ignore)

    # ── Row Counts ──
    src_counts = src_data.get("row_counts", {})
    for tbl in sorted(set(src_tables) & set(tgt_tables)):
        src_cnt = src_counts.get(tbl, -1)
        tgt_cnt = _tgt_row_count(tgt_conn, schema, tbl)
        status = "match" if src_cnt == tgt_cnt else "mismatch"
        _save(db, task_id, schema, "DATA_COUNT", tbl, status,
              str(src_cnt), str(tgt_cnt),
              {"diff": abs(src_cnt - tgt_cnt)} if src_cnt != tgt_cnt else None)

    # ── Checksums ──
    src_checksums = src_data.get("checksums", {})
    if src_checksums:
        for tbl in sorted(set(src_tables) & set(tgt_tables)):
            src_hash = src_checksums.get(tbl)
            tgt_hash = _tgt_checksum(tgt_conn, schema, tbl)
            if src_hash and tgt_hash:
                status = "match" if src_hash == tgt_hash else "mismatch"
                _save(db, task_id, schema, "DATA_CHECKSUM", tbl, status, src_hash, tgt_hash)

    db.commit()


# ─── Main entry point ───

def run_comparison(task_id: int, schemas: Optional[list[str]] = None):
    """Run comparison in a background thread."""
    db = SessionLocal()
    try:
        task = db.query(ComparisonTask).get(task_id)
        if not task:
            return

        task.status = "running"
        task.started_at = datetime.utcnow()
        db.commit()

        tgt_cfg = db.query(DbConfig).get(task.target_db_id)
        tgt_conn = _connect(tgt_cfg)

        if task.mode == "snapshot_vs_db":
            snap = db.query(Snapshot).get(task.source_snapshot_id)
            with open(snap.file_path, "r") as f:
                snap_data = json.load(f)

            available_schemas = list(snap_data.get("schemas", {}).keys())
            if schemas:
                compare_schemas = [s for s in schemas if s in available_schemas]
            else:
                compare_schemas = available_schemas

            total = len(compare_schemas)
            for idx, schema in enumerate(compare_schemas):
                logger.info("Comparing schema %s (%d/%d) - snapshot vs db", schema, idx + 1, total)
                try:
                    src_schema_data = snap_data["schemas"][schema]
                    if "error" in src_schema_data:
                        _save(db, task_id, schema, "ERROR", "SCHEMA", "mismatch",
                              details={"error": src_schema_data["error"]})
                        db.commit()
                        continue
                    _compare_schema_snapshot_vs_db(db, task_id, schema, src_schema_data, tgt_conn)
                except Exception as e:
                    logger.error("Error comparing schema %s: %s", schema, e)
                    _save(db, task_id, schema, "ERROR", "SCHEMA", "mismatch", details={"error": str(e)})
                    db.commit()
                task.progress = int((idx + 1) / total * 100)
                db.commit()

        else:
            logger.warning("Mode %s not yet fully supported in new engine", task.mode)

        tgt_conn.close()

        results = db.query(ComparisonResult).filter(ComparisonResult.task_id == task_id).all()
        summary = {"total": 0, "match": 0, "mismatch": 0, "source_only": 0, "target_only": 0}
        for r in results:
            summary["total"] += 1
            summary[r.match_status] = summary.get(r.match_status, 0) + 1

        task.status = "completed"
        task.progress = 100
        task.summary = summary
        task.finished_at = datetime.utcnow()
        db.commit()
        logger.info("Comparison task %d completed: %s", task_id, summary)

    except Exception as e:
        logger.error("Comparison task %d failed: %s\n%s", task_id, e, traceback.format_exc())
        task = db.query(ComparisonTask).get(task_id)
        if task:
            task.status = "failed"
            task.summary = {"error": str(e)}
            task.finished_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()
