#!/usr/bin/env python3
"""
RDS Oracle Data Pump Export & Upload to S3
============================================
自动化完成：Data Pump 导出 → 监控进度 → 上传 S3 → 清理

Requirements: pip install oracledb

Usage:
    python3 rds_dump.py --help
    python3 rds_dump.py --schemas TEST_SCHEMA_01,TEST_SCHEMA_02
    python3 rds_dump.py --full
"""

import argparse
import sys
import time
from datetime import datetime

import oracledb


SYSTEM_SCHEMAS = {
    'SYS', 'SYSTEM', 'DBSNMP', 'OUTLN', 'XDB', 'WMSYS', 'CTXSYS',
    'ANONYMOUS', 'MDSYS', 'OLAPSYS', 'ORDDATA', 'ORDPLUGINS', 'ORDSYS',
    'SI_INFORMTN_SCHEMA', 'APEX_PUBLIC_USER', 'APPQOSSYS', 'DVSYS', 'LBACSYS',
    'RDSADMIN', 'GSMADMIN_INTERNAL', 'DIP', 'ORACLE_OCM', 'XS$NULL',
    'REMOTE_SCHEDULER_AGENT', 'GGSYS', 'DBSFWUSER', 'GSMCATUSER',
    'SYSBACKUP', 'SYSDG', 'SYSKM', 'SYSRAC', 'SYS$UMF', 'AUDSYS',
    'GSMUSER', 'ADMIN',
}


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def connect(args):
    dsn = f"{args.host}:{args.port}/{args.service}"
    log(f"Connecting to {dsn} ...")
    conn = oracledb.connect(user=args.user, password=args.password, dsn=dsn)
    log(f"Connected: {conn.version}")
    return conn


def get_schemas(conn, args):
    if args.schemas:
        return [s.strip().upper() for s in args.schemas.split(",")]
    cur = conn.cursor()
    cur.execute("SELECT username FROM all_users ORDER BY username")
    schemas = [r[0] for r in cur if r[0] not in SYSTEM_SCHEMAS]
    cur.close()
    log(f"Auto-detected {len(schemas)} schemas: {', '.join(schemas)}")
    return schemas


def check_prerequisites(conn, args):
    """Check DATA_PUMP_DIR and S3 integration."""
    cur = conn.cursor()

    cur.execute("SELECT directory_path FROM dba_directories WHERE directory_name = 'DATA_PUMP_DIR'")
    row = cur.fetchone()
    if row:
        log(f"DATA_PUMP_DIR: {row[0]}")
    else:
        log("ERROR: DATA_PUMP_DIR not found")
        sys.exit(1)

    if not args.skip_s3:
        try:
            cur.execute("""
                SELECT object_name FROM all_objects
                WHERE owner = 'RDSADMIN' AND object_name = 'RDSADMIN_S3_TASKS'
            """)
            if cur.fetchone():
                log("S3 Integration: available")
            else:
                log("WARNING: RDSADMIN_S3_TASKS not found. S3 upload may fail.")
                log("  Please ensure S3_INTEGRATION is enabled in the RDS Option Group.")
        except Exception as e:
            log(f"WARNING: Cannot check S3 integration: {e}")

    cur.close()


def list_dump_dir(conn):
    """List files in DATA_PUMP_DIR."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM TABLE(rdsadmin.rds_file_util.listdir('DATA_PUMP_DIR')) ORDER BY mtime DESC")
        files = []
        for row in cur:
            files.append({"name": row[0], "size": row[1], "mtime": row[2]})
        return files
    except Exception:
        return []
    finally:
        cur.close()


def cleanup_old_dumps(conn, prefix):
    """Remove old dump files with the given prefix."""
    files = list_dump_dir(conn)
    cur = conn.cursor()
    removed = 0
    for f in files:
        name = f["name"]
        if name.startswith(prefix) and (name.endswith(".dmp") or name.endswith(".log")):
            try:
                cur.execute("BEGIN UTL_FILE.FREMOVE('DATA_PUMP_DIR', :f); END;", {"f": name})
                removed += 1
            except Exception:
                pass
    cur.close()
    if removed:
        log(f"Cleaned up {removed} old files with prefix '{prefix}'")


def run_datapump_export(conn, schemas, args):
    """Run Data Pump export via DBMS_DATAPUMP."""
    prefix = args.prefix
    job_name = f"{prefix}JOB"
    parallel = args.parallel

    cleanup_old_dumps(conn, prefix)

    schema_list = ",".join(f"'{s}'" for s in schemas)

    plsql = f"""
    DECLARE
        h NUMBER;
    BEGIN
        h := DBMS_DATAPUMP.OPEN('EXPORT', 'SCHEMA', NULL, '{job_name}', 'COMPATIBLE');
        DBMS_DATAPUMP.ADD_FILE(h, '{prefix}%U.dmp', 'DATA_PUMP_DIR', NULL, DBMS_DATAPUMP.KU$_FILE_TYPE_DUMP_FILE);
        DBMS_DATAPUMP.ADD_FILE(h, '{prefix}export.log', 'DATA_PUMP_DIR', NULL, DBMS_DATAPUMP.KU$_FILE_TYPE_LOG_FILE);
        DBMS_DATAPUMP.METADATA_FILTER(h, 'SCHEMA_LIST', '{schema_list}');
        DBMS_DATAPUMP.SET_PARALLEL(h, {parallel});
        DBMS_DATAPUMP.START_JOB(h);
        DBMS_DATAPUMP.DETACH(h);
    END;
    """

    log(f"Starting Data Pump export: job={job_name}, schemas={len(schemas)}, parallel={parallel}")
    cur = conn.cursor()
    try:
        cur.execute(plsql)
        conn.commit()
        log("Data Pump job submitted successfully")
    except oracledb.DatabaseError as e:
        err = str(e)
        if "ORA-31634" in err or "already exists" in err.lower():
            log(f"Job {job_name} already exists, attempting to clean up...")
            try:
                cur.execute(f"""
                    BEGIN
                        DBMS_DATAPUMP.ATTACH('{job_name}', 'ADMIN');
                        DBMS_DATAPUMP.STOP_JOB(DBMS_DATAPUMP.ATTACH('{job_name}', 'ADMIN'));
                    EXCEPTION WHEN OTHERS THEN NULL;
                    END;
                """)
            except Exception:
                pass
            try:
                cur.execute(f"DROP TABLE ADMIN.{job_name} PURGE")
                conn.commit()
            except Exception:
                pass
            log("Retrying...")
            cur.execute(plsql)
            conn.commit()
            log("Data Pump job submitted successfully (retry)")
        else:
            raise
    finally:
        cur.close()

    return job_name


def monitor_datapump(conn, job_name):
    """Monitor Data Pump job until completion."""
    cur = conn.cursor()
    log("Monitoring Data Pump progress...")

    while True:
        time.sleep(10)
        cur.execute("""
            SELECT job_name, state, attached_sessions
            FROM dba_datapump_jobs
            WHERE job_name = :j AND owner_name = 'ADMIN'
        """, {"j": job_name})
        row = cur.fetchone()

        if not row:
            log("Job finished (no longer in dba_datapump_jobs)")
            break

        state = row[1]
        log(f"  Job: {row[0]}, State: {state}, Sessions: {row[2]}")

        if state in ("COMPLETED", "STOPPED", "NOT RUNNING"):
            break

    cur.close()


def show_export_log(conn, prefix):
    """Display the export log file."""
    log_file = f"{prefix}export.log"
    log(f"--- Export Log ({log_file}) ---")
    cur = conn.cursor()
    try:
        cur.execute(f"""
            SELECT text FROM TABLE(
                rdsadmin.rds_file_util.read_text_file('DATA_PUMP_DIR', '{log_file}')
            )
        """)
        for row in cur:
            print(f"  {row[0]}", end="")
        print()
    except Exception as e:
        log(f"Cannot read log: {e}")
    finally:
        cur.close()


def show_dump_files(conn, prefix):
    """Show dump files and their sizes."""
    files = list_dump_dir(conn)
    dump_files = [f for f in files if f["name"].startswith(prefix)]
    total_size = 0
    log("Dump files in DATA_PUMP_DIR:")
    for f in dump_files:
        size_mb = f["size"] / 1024 / 1024
        total_size += f["size"]
        log(f"  {f['name']:40s}  {size_mb:>10.1f} MB")
    log(f"  {'TOTAL':40s}  {total_size / 1024 / 1024:>10.1f} MB")
    return dump_files


def upload_to_s3(conn, args):
    """Upload dump files from DATA_PUMP_DIR to S3."""
    bucket = args.s3_bucket
    s3_prefix = args.s3_prefix

    log(f"Uploading to s3://{bucket}/{s3_prefix} ...")

    cur = conn.cursor()
    cur.execute("""
        SELECT rdsadmin.rdsadmin_s3_tasks.upload_to_s3(
            p_bucket_name    => :bucket,
            p_prefix         => :prefix,
            p_s3_prefix      => :s3prefix,
            p_directory_name => 'DATA_PUMP_DIR'
        ) AS task_id FROM DUAL
    """, {"bucket": bucket, "prefix": args.prefix, "s3prefix": s3_prefix})
    task_id = cur.fetchone()[0]
    cur.close()

    log(f"S3 upload task started: {task_id}")
    monitor_s3_task(conn, task_id)
    return task_id


def monitor_s3_task(conn, task_id):
    """Monitor S3 upload task."""
    log("Monitoring S3 upload progress...")
    last_line_count = 0

    while True:
        time.sleep(10)
        cur = conn.cursor()
        try:
            cur.execute(f"""
                SELECT text FROM TABLE(
                    rdsadmin.rds_file_util.read_text_file('BDUMP', 'dbtask-{task_id}.log')
                )
            """)
            lines = [r[0] for r in cur]
            cur.close()

            if len(lines) > last_line_count:
                for line in lines[last_line_count:]:
                    print(f"  {line}", end="" if line.endswith("\n") else "\n")
                last_line_count = len(lines)

            full_text = "".join(lines)
            if "finished successfully" in full_text.lower() or "the task finished successfully" in full_text.lower():
                log("S3 upload completed successfully!")
                break
            if "error" in full_text.lower() and "finished" in full_text.lower():
                log("S3 upload finished with errors!")
                break
        except Exception as e:
            log(f"  Waiting for upload log... ({e})")
            cur.close()


def cleanup_dump_files(conn, prefix):
    """Remove dump files from DATA_PUMP_DIR after upload."""
    log("Cleaning up dump files from DATA_PUMP_DIR...")
    cleanup_old_dumps(conn, prefix)
    log("Cleanup done")


def main():
    parser = argparse.ArgumentParser(description="RDS Oracle Data Pump Export & S3 Upload")
    parser.add_argument("--host", default="source.cxymymkmm5sd.ap-east-1.rds.amazonaws.com")
    parser.add_argument("--port", type=int, default=1521)
    parser.add_argument("--service", default="ORCL")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--password", default="admin1234")
    parser.add_argument("--schemas", default=None, help="Comma-separated schemas (default: auto-detect)")
    parser.add_argument("--prefix", default="DUMP_", help="Dump file prefix (default: DUMP_)")
    parser.add_argument("--parallel", type=int, default=4, help="Data Pump parallelism (default: 4)")
    parser.add_argument("--s3-bucket", default="oracle-backup666")
    parser.add_argument("--s3-prefix", default="dump/", help="S3 key prefix (default: dump/)")
    parser.add_argument("--skip-s3", action="store_true", help="Skip S3 upload, only export")
    parser.add_argument("--skip-export", action="store_true", help="Skip export, only upload existing files")
    parser.add_argument("--no-cleanup", action="store_true", help="Don't delete dump files after upload")
    parser.add_argument("--list-files", action="store_true", help="Just list files in DATA_PUMP_DIR")
    args = parser.parse_args()

    conn = connect(args)

    if args.list_files:
        files = list_dump_dir(conn)
        if files:
            for f in files:
                print(f"  {f['name']:40s}  {f['size'] / 1024 / 1024:>10.1f} MB  {f['mtime']}")
        else:
            log("No files found or cannot list directory")
        conn.close()
        return

    check_prerequisites(conn, args)

    t0 = time.time()

    if not args.skip_export:
        schemas = get_schemas(conn, args)
        if not schemas:
            log("No schemas to export")
            conn.close()
            return

        log(f"=== Phase 1: Data Pump Export ({len(schemas)} schemas) ===")
        job_name = run_datapump_export(conn, schemas, args)
        monitor_datapump(conn, job_name)
        show_export_log(conn, args.prefix)

    log("=== Dump Files ===")
    show_dump_files(conn, args.prefix)

    if not args.skip_s3:
        log(f"=== Phase 2: Upload to S3 (s3://{args.s3_bucket}/{args.s3_prefix}) ===")
        upload_to_s3(conn, args)

        if not args.no_cleanup:
            log("=== Phase 3: Cleanup ===")
            cleanup_dump_files(conn, args.prefix)

    elapsed = time.time() - t0
    log(f"All done in {elapsed:.0f}s ({elapsed / 60:.1f} min)")
    conn.close()


if __name__ == "__main__":
    main()
