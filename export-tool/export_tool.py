#!/usr/bin/env python3
"""
Oracle Source Database Export Tool
===================================
Standalone script to export all schema metadata and data statistics from
a source Oracle database. Outputs a JSON snapshot file that can be imported
into the Migration Management web application for comparison.

Requirements: pip install oracledb

Usage:
    python3 export_tool.py \
        --host <host> --port 1521 --service ORCL \
        --user admin --password <pwd> \
        --schemas TEST_SCHEMA_01,TEST_SCHEMA_02 \
        --output snapshot.json

    # Export all non-system schemas:
    python3 export_tool.py \
        --host <host> --port 1521 --service ORCL \
        --user admin --password <pwd> \
        --output snapshot.json
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional

import oracledb

SNAPSHOT_VERSION = "1.1"

SYSTEM_USERS = {
    'SYS', 'SYSTEM', 'DBSNMP', 'OUTLN', 'XDB', 'WMSYS', 'CTXSYS',
    'ANONYMOUS', 'MDSYS', 'OLAPSYS', 'ORDDATA', 'ORDPLUGINS', 'ORDSYS',
    'SI_INFORMTN_SCHEMA', 'APEX_PUBLIC_USER', 'APPQOSSYS', 'DVSYS', 'LBACSYS',
    'RDSADMIN', 'GSMADMIN_INTERNAL', 'DIP', 'ORACLE_OCM', 'XS$NULL',
    'REMOTE_SCHEDULER_AGENT', 'GGSYS', 'DBSFWUSER', 'GSMCATUSER',
    'SYSBACKUP', 'SYSDG', 'SYSKM', 'SYSRAC', 'SYS$UMF', 'AUDSYS', 'ADMIN',
}


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _make_conn(dsn, user, password):
    return oracledb.connect(user=user, password=password, dsn=dsn)


def fetch_all(cur, sql: str, params: dict = None) -> list[dict]:
    cur.execute(sql, params or {})
    cols = [d[0].lower() for d in cur.description]
    return [dict(zip(cols, row)) for row in cur]


def export_tables(cur, schema: str) -> list[dict]:
    return fetch_all(cur, """
        SELECT table_name, tablespace_name, num_rows, blocks, avg_row_len, last_analyzed
        FROM all_tables WHERE owner = :s ORDER BY table_name
    """, {"s": schema})


def export_columns(cur, schema: str) -> list[dict]:
    return fetch_all(cur, """
        SELECT table_name, column_name, data_type, data_length, data_precision,
               data_scale, nullable, column_id, data_default
        FROM all_tab_columns WHERE owner = :s ORDER BY table_name, column_id
    """, {"s": schema})


def export_constraints(cur, schema: str) -> list[dict]:
    return fetch_all(cur, """
        SELECT table_name, constraint_name, constraint_type, search_condition,
               r_constraint_name, status, validated
        FROM all_constraints WHERE owner = :s AND constraint_name NOT LIKE 'SYS_%'
        ORDER BY table_name, constraint_name
    """, {"s": schema})


def export_indexes(cur, schema: str) -> list[dict]:
    return fetch_all(cur, """
        SELECT index_name, table_name, index_type, uniqueness, tablespace_name, status
        FROM all_indexes WHERE owner = :s AND index_name NOT LIKE 'SYS_%'
        ORDER BY index_name
    """, {"s": schema})


def export_index_columns(cur, schema: str) -> list[dict]:
    return fetch_all(cur, """
        SELECT index_name, table_name, column_name, column_position
        FROM all_ind_columns WHERE index_owner = :s
        ORDER BY index_name, column_position
    """, {"s": schema})


def export_views(cur, schema: str) -> list[dict]:
    return fetch_all(cur, """
        SELECT view_name, text_length, text FROM all_views WHERE owner = :s ORDER BY view_name
    """, {"s": schema})


def export_sequences(cur, schema: str) -> list[dict]:
    return fetch_all(cur, """
        SELECT sequence_name, min_value, max_value, increment_by,
               cycle_flag, order_flag, cache_size, last_number
        FROM all_sequences WHERE sequence_owner = :s AND sequence_name NOT LIKE 'ISEQ$$_%' ORDER BY sequence_name
    """, {"s": schema})


def export_source_code(cur, schema: str, obj_type: str) -> list[dict]:
    rows = fetch_all(cur, """
        SELECT name, line, text FROM all_source
        WHERE owner = :s AND type = :t ORDER BY name, line
    """, {"s": schema, "t": obj_type})
    grouped = {}
    for r in rows:
        grouped.setdefault(r["name"], []).append(r["text"])
    return [{"name": name, "source": "".join(lines).strip()} for name, lines in grouped.items()]


def export_triggers(cur, schema: str) -> list[dict]:
    return fetch_all(cur, """
        SELECT trigger_name, trigger_type, triggering_event, table_name,
               status, description, trigger_body
        FROM all_triggers WHERE owner = :s ORDER BY trigger_name
    """, {"s": schema})


def export_types(cur, schema: str) -> list[dict]:
    return fetch_all(cur, """
        SELECT type_name, typecode, attributes, methods
        FROM all_types WHERE owner = :s AND type_name NOT LIKE 'SYS_%' ORDER BY type_name
    """, {"s": schema})


def export_synonyms(cur, schema: str) -> list[dict]:
    return fetch_all(cur, """
        SELECT synonym_name, table_owner, table_name, db_link
        FROM all_synonyms WHERE owner = :s ORDER BY synonym_name
    """, {"s": schema})


def export_mviews(cur, schema: str) -> list[dict]:
    return fetch_all(cur, """
        SELECT mview_name, container_name, query, refresh_mode, refresh_method, last_refresh_date
        FROM all_mviews WHERE owner = :s ORDER BY mview_name
    """, {"s": schema})


def export_db_links(cur, schema: str) -> list[dict]:
    return fetch_all(cur, """
        SELECT db_link, username, host, created FROM all_db_links WHERE owner = :s ORDER BY db_link
    """, {"s": schema})


# ─── Parallelized data stats ───

def _get_columns_for_table(conn, schema: str, table: str) -> list[str]:
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name FROM all_tab_columns
        WHERE owner = :s AND table_name = :t ORDER BY column_id
    """, {"s": schema, "t": table})
    cols = [r[0] for r in cur]
    cur.close()
    return cols


def _single_table_stats(dsn: str, user: str, password: str,
                         schema: str, table: str,
                         sample_limit: int, skip_checksum: bool) -> tuple:
    """Compute row count + server-side ORA_HASH checksum for one table.
    Each call uses its own connection for thread safety."""
    conn = oracledb.connect(user=user, password=password, dsn=dsn)
    cur = conn.cursor()
    count = -1
    checksum = None
    try:
        cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"')
        count = cur.fetchone()[0]
    except Exception:
        pass

    if not skip_checksum:
        try:
            cur.execute("""
                SELECT column_name FROM all_tab_columns
                WHERE owner = :s AND table_name = :t ORDER BY column_id
            """, {"s": schema, "t": table})
            cols = [r[0] for r in cur]

            if cols:
                ora_expr = " || '|' || ".join(
                    f'NVL(TO_CHAR("{c}"), \'\')'  for c in cols
                )
                sql = (
                    f'SELECT SUM(ORA_HASH({ora_expr})), COUNT(*) '
                    f'FROM (SELECT * FROM "{schema}"."{table}" '
                )
                cur.execute(sql)
                row = cur.fetchone()
                hash_sum = row[0] if row else None
                sample_cnt = row[1] if row else 0
                checksum = f"{hash_sum}:{sample_cnt}" if hash_sum is not None else None
        except Exception:
            checksum = None

    cur.close()
    conn.close()
    return table, count, checksum


def export_data_stats_parallel(dsn: str, user: str, password: str,
                                schema: str, tables: list[str],
                                sample_limit: int, skip_checksum: bool,
                                workers: int = 8) -> tuple[dict, dict]:
    """Compute row counts and checksums in parallel using a thread pool."""
    counts = {}
    checksums = {}
    done = 0
    total = len(tables)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_single_table_stats, dsn, user, password,
                        schema, t, sample_limit, skip_checksum): t
            for t in tables
        }
        for future in as_completed(futures):
            tbl, cnt, cksum = future.result()
            counts[tbl] = cnt
            checksums[tbl] = cksum
            done += 1
            if done % 50 == 0 or done == total:
                log(f"    [{schema}] Data stats: {done}/{total} tables done")

    return counts, checksums


def export_schema(conn, dsn, user, password, schema: str, args) -> dict:
    """Export all metadata for a single schema."""
    cur = conn.cursor()

    log(f"  [{schema}] Exporting tables & columns...")
    tables = export_tables(cur, schema)
    table_names = [t["table_name"] for t in tables]
    columns = export_columns(cur, schema)
    constraints = export_constraints(cur, schema)

    log(f"  [{schema}] Exporting indexes...")
    indexes = export_indexes(cur, schema)
    index_columns = export_index_columns(cur, schema)

    log(f"  [{schema}] Exporting views, sequences...")
    views = export_views(cur, schema)
    sequences = export_sequences(cur, schema)

    log(f"  [{schema}] Exporting functions, procedures, packages...")
    functions = export_source_code(cur, schema, "FUNCTION")
    procedures = export_source_code(cur, schema, "PROCEDURE")
    packages = export_source_code(cur, schema, "PACKAGE")
    package_bodies = export_source_code(cur, schema, "PACKAGE BODY")

    log(f"  [{schema}] Exporting triggers, types, synonyms, mviews, db_links...")
    triggers = export_triggers(cur, schema)
    types = export_types(cur, schema)
    synonyms = export_synonyms(cur, schema)
    mviews = export_mviews(cur, schema)
    db_links = export_db_links(cur, schema)

    cur.close()

    log(f"  [{schema}] Computing data stats ({len(table_names)} tables, {args.parallel} workers, sample={args.checksum_sample})...")
    row_counts, checksums = export_data_stats_parallel(
        dsn, user, password, schema, table_names,
        args.checksum_sample, args.skip_checksums, args.parallel,
    )
    if args.skip_checksums:
        checksums = {}

    object_count = (len(tables) + len(indexes) + len(views) + len(sequences) +
                    len(functions) + len(procedures) + len(packages) +
                    len(triggers) + len(types) + len(synonyms) + len(mviews) + len(db_links))

    log(f"  [{schema}] Done: {len(tables)} tables, {object_count} total objects, {sum(v for v in row_counts.values() if v > 0):,} rows")

    return {
        "tables": tables,
        "columns": columns,
        "constraints": constraints,
        "indexes": indexes,
        "index_columns": index_columns,
        "views": [_clean(v) for v in views],
        "sequences": sequences,
        "functions": functions,
        "procedures": procedures,
        "packages": packages,
        "package_bodies": package_bodies,
        "triggers": [_clean(t) for t in triggers],
        "types": types,
        "synonyms": synonyms,
        "mviews": [_clean(m) for m in mviews],
        "db_links": db_links,
        "row_counts": row_counts,
        "checksums": checksums,
        "stats": {
            "table_count": len(tables),
            "object_count": object_count,
            "total_rows": sum(v for v in row_counts.values() if v > 0),
        },
    }


def _clean(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if hasattr(v, 'read'):
            out[k] = v.read() if v else None
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def main():
    parser = argparse.ArgumentParser(description="Oracle Source Database Export Tool")
    parser.add_argument("--host", required=True, help="Database host")
    parser.add_argument("--port", type=int, default=1521, help="Database port")
    parser.add_argument("--service", required=True, help="Service name / SID")
    parser.add_argument("--user", required=True, help="Database username")
    parser.add_argument("--password", required=True, help="Database password")
    parser.add_argument("--schemas", default=None, help="Comma-separated schema names (default: all non-system)")
    parser.add_argument("--output", default=None, help="Output file path (default: snapshot_<timestamp>.json)")
    parser.add_argument("--skip-checksums", action="store_true", help="Skip data checksum computation")
    parser.add_argument("--checksum-sample", type=int, default=1000, help="Number of rows to sample for checksums")
    parser.add_argument("--parallel", type=int, default=8, help="Number of parallel workers for data stats (default: 8)")
    args = parser.parse_args()

    if not args.output:
        args.output = f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    log("Oracle Source Database Export Tool v1.1")
    log(f"Connecting to {args.host}:{args.port}/{args.service} ...")

    dsn = f"{args.host}:{args.port}/{args.service}"
    conn = oracledb.connect(user=args.user, password=args.password, dsn=dsn)

    cur = conn.cursor()
    cur.execute("SELECT banner FROM v$version WHERE ROWNUM = 1")
    banner = cur.fetchone()[0]
    cur.execute("SELECT sys_context('USERENV', 'DB_NAME') FROM dual")
    db_name = cur.fetchone()[0]
    version = conn.version
    cur.close()

    log(f"Connected: {banner}")
    log(f"Parallel workers: {args.parallel}")

    if args.schemas:
        schemas = [s.strip().upper() for s in args.schemas.split(",")]
    else:
        cur = conn.cursor()
        cur.execute("SELECT username FROM all_users ORDER BY username")
        schemas = [r[0] for r in cur if r[0] not in SYSTEM_USERS]
        cur.close()
        log(f"Auto-detected {len(schemas)} schemas: {', '.join(schemas)}")

    snapshot = {
        "snapshot_version": SNAPSHOT_VERSION,
        "export_time": datetime.now().isoformat(),
        "db_info": {
            "host": args.host,
            "port": args.port,
            "service_name": args.service,
            "version": version,
            "banner": banner,
            "db_name": db_name,
        },
        "schemas": {},
    }

    t0 = time.time()
    for idx, schema in enumerate(schemas, 1):
        log(f"Exporting schema {schema} ({idx}/{len(schemas)}) ...")
        try:
            snapshot["schemas"][schema] = export_schema(
                conn, dsn, args.user, args.password, schema, args,
            )
        except Exception as e:
            log(f"  [{schema}] ERROR: {e}")
            snapshot["schemas"][schema] = {"error": str(e)}

    conn.close()
    elapsed = time.time() - t0

    total_tables = sum(s.get("stats", {}).get("table_count", 0) for s in snapshot["schemas"].values())
    total_objects = sum(s.get("stats", {}).get("object_count", 0) for s in snapshot["schemas"].values())
    total_rows = sum(s.get("stats", {}).get("total_rows", 0) for s in snapshot["schemas"].values())

    snapshot["summary"] = {
        "schema_count": len(schemas),
        "total_tables": total_tables,
        "total_objects": total_objects,
        "total_rows": total_rows,
        "elapsed_seconds": round(elapsed, 1),
    }

    class DateTimeEncoder(json.JSONEncoder):
        def default(self, o):
            if isinstance(o, datetime):
                return o.isoformat()
            return super().default(o)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2, cls=DateTimeEncoder, default=str)

    size_mb = round(len(open(args.output, "rb").read()) / 1024 / 1024, 1)
    log(f"Export complete in {elapsed:.1f}s")
    log(f"  Schemas: {len(schemas)}, Tables: {total_tables}, Objects: {total_objects}, Rows: {total_rows:,}")
    log(f"  Output: {args.output} ({size_mb} MB)")
    log("Done!")


if __name__ == "__main__":
    main()
