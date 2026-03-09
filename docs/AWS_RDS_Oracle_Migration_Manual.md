# AWS RDS Oracle 数据迁移操作手册

## 1. 项目背景与目标

本项目旨在使用原生机制将 AWS 上的 RDS for Oracle 数据库进行一次性全量数据迁移。要求在 1 天的停机窗口内完成数据割接。
**核心底线**：必须保证目的端数据与源端 100% 一致，零数据丢失，且必须提前进行全量模拟测试。此手册仅针对数据迁移流转，不包含应用层代码迁移。

---

## 2. 环境信息确认与连接信息

> **⚠️ 注意**：目前为 POC 测试环境，生产割接前请务必仔细替换为真实的 Endpoint 与凭证信息。

- **源端实例**：`source.cxymymkmm5sd.ap-east-1.rds.amazonaws.com:1521/ORCL`
- **目标端实例**：`target.cxymymkmm5sd.ap-east-1.rds.amazonaws.com:1521/ORCL`
- **数据库凭证**：登录账号 `admin`，密码 `admin1234`
- **数据库版本**：`19.0.0.0.ru-2021-10.rur-2021-10.r1 Standard Edition` (要求源端与目标端必须保持一致)
- **字符集要求**：强制要求 `ZHS16GBK`
- **迁移规模**：数据文件约 343.73GB，14 个核心业务 Schema（含 140 个分区表，111 个 XMLDB 字段等）
- **S3 存储桶**：`oracle-backup666`
- **中转 EC2 系统节点**：`ec2-user@95.40.19.214` (平台: Amazon Linux 2023)

---

## 3. 核心迁移规范 (避坑指南)

1. **不使用 DMS 进行迁移**：
   鉴于此类工具之前出现“字符被截断致表迁移失败、主键索引不可用”等致命错误，具体参考docs/log-events-viewer-result.csv，本次迁移**使用 Oracle 原生 Data Pump (expdp/impdp) 进行逻辑迁移**。
2. **严禁将 dump 下载至本地中转**：
   为了保障 1 天内完成迁移，**必须**使用 AWS 原生 S3 集成功能 (`rdsadmin_s3_tasks`) 结合跨区 EC2 节点流转文件数据。
3. **关键前置权限检查**：
   - 源数据库、目标数据库必须提前配置开启 `S3_INTEGRATION` 选项并配置正确的 IAM S3 访问角色。

---

## 4. EC2 节点前置准备工作

连接至中转 EC2，安装相关的 Oracle 客户端、Data Pump 及 AWS CLI 工具。

### 4.1 安装基础命令行及 sqlplus
```bash
sudo dnf install -y libaio gcc make readline-devel tar gzip

# 安装 Oracle 21c 基础客户端
wget https://download.oracle.com/otn_software/linux/instantclient/2112000/oracle-instantclient-basic-21.12.0.0.0-1.el8.x86_64.rpm
wget https://download.oracle.com/otn_software/linux/instantclient/2112000/oracle-instantclient-sqlplus-21.12.0.0.0-1.el8.x86_64.rpm
sudo dnf install -y ./oracle-instantclient-basic-*.rpm ./oracle-instantclient-sqlplus-*.rpm

# 源码编译安装 rlwrap 以支持命令回退修改
wget https://github.com/hanslub42/rlwrap/releases/download/0.46.1/rlwrap-0.46.1.tar.gz
tar -zxvf rlwrap-0.46.1.tar.gz
cd rlwrap-0.46.1
./configure && make && sudo make install

# 加入全局环境变量
echo "alias sqlplus='rlwrap sqlplus'" >> ~/.bashrc
source ~/.bashrc
```

### 4.2 安装 expdp/impdp
```bash
wget https://download.oracle.com/otn_software/linux/instantclient/2112000/oracle-instantclient-tools-21.12.0.0.0-1.el8.x86_64.rpm
sudo yum install -y oracle-instantclient-tools-21.12.0.0.0-1.el8.x86_64.rpm
export PATH=$PATH:/usr/lib/oracle/21/client64/bin
echo "alias expdp='/usr/local/bin/rlwrap /usr/lib/oracle/21/client64/bin/expdp'" >> ~/.bashrc
echo "alias impdp='/usr/local/bin/rlwrap /usr/lib/oracle/21/client64/bin/impdp'" >> ~/.bashrc
source ~/.bashrc

# 验证安装是否成功，将出现帮助信息
expdp help=y
```

### 4.3 配置 AWS CLI 传输凭证
```bash
sudo yum install awscli

# 分别配置出源端与目标端需要的 profile 凭据，根据控制台指引输入 AK/SK 与 region (例如 cn-north-1 / ap-east-1 等)
aws configure --profile china-profile
aws configure --profile global-profile
```

### 4.4 检查源库元数据
登录数据库：
```bash
sqlplus admin/admin1234@source.cxymymkmm5sd.ap-east-1.rds.amazonaws.com:1521/ORCL
```

- **检查是否存在 DBA 权限：**
  `SELECT granted_role, admin_option, default_role FROM user_role_privs WHERE granted_role = 'DBA';`
- **检查当前数据库字符集（要求与目标一致）：**
  `SELECT * FROM nls_database_parameters WHERE parameter IN ('NLS_CHARACTERSET', 'NLS_NCHAR_CHARACTERSET');`
- **查询默认映射的逻辑备份导出目录：**
  `SELECT * FROM dba_directories WHERE directory_name = 'DATA_PUMP_DIR';`
- **筛选需要迁移的用户 Schema 以及空间大小评估：**
  ```sql
  SELECT owner AS schema_name, ROUND(SUM(bytes)/1024/1024/1024, 2) AS size_gb 
  FROM dba_segments 
  WHERE owner IN (SELECT username FROM dba_users WHERE oracle_maintained = 'N') 
  GROUP BY owner ORDER BY size_gb DESC;
  ```

---

## 5. 核心迁移流转工作流

### 第 1 步：源端全量导出 (Data Pump Export)

> 在导出前，请必须强制全量刷新业务物化视图以免数据或状态异常。

**PL/SQL 刷新脚本 (在源库执行),注意修改 schema_name：**
```sql
DECLARE
    v_mv_full_name  VARCHAR2(200);
BEGIN
    FOR cur IN (SELECT owner, mview_name FROM dba_mviews WHERE owner LIKE 'TEST_SCHEMA_%') LOOP
        v_mv_full_name := '"' || cur.owner || '"."' || cur.mview_name || '"';
        BEGIN
            DBMS_MVIEW.REFRESH(list => v_mv_full_name, method => 'C');
        EXCEPTION WHEN OTHERS THEN NULL;
        END;
    END LOOP;
END;
/
```

**分片并行导出 (在 EC2 终端执行)：**
人为划分为 3 个以上的 SSH 会话窗口执行命令，启用 `COMPRESSION=ALL`。

```bash
# 示例：窗口 A 执行 Schema _02,_10,_06 的导出
expdp admin/admin1234@source.cxymymkmm5sd.ap-east-1.rds.amazonaws.com:1521/ORCL \
DIRECTORY=DATA_PUMP_DIR \
SCHEMAS=TEST_SCHEMA_02,TEST_SCHEMA_10,TEST_SCHEMA_06 \
DUMPFILE=export_demo_part1_%U.dmp \
FILESIZE=20G \
LOGFILE=export_demo_part1.log \
COMPRESSION=ALL \
EXCLUDE=STATISTICS \
METRICS=YES \
LOGTIME=ALL
```
*(其它 Terminal 窗口请替换不同 Schema Name 分别执行)*

### 第 2 步：RDS 通过 S3 挂载上传文件至源侧 Bucket

由于 RDS 禁止直接下载底层物理文件，利用 AWS 原生包进行 RDS -> S3_bucket 的流转。

**注意修改 bucket_name, prefix, s3_prefix, directory_name**

```sql
SELECT rdsadmin.rdsadmin_s3_tasks.upload_to_s3(
      p_bucket_name    =>  'oracle-backup666',
      p_prefix         =>  'export_demo_',
      p_s3_prefix      =>  'dpump_export/',
      p_directory_name =>  'DATA_PUMP_DIR')
   AS TASK_ID FROM DUAL;

-- 根据返回的 TASK_ID，查询进度对应生成的 LOG
SELECT text FROM table(rdsadmin.rds_file_util.read_text_file('BDUMP','dbtask-<task-id>.log'));
```

### 第 3 步：EC2 中继拉取远端 S3 转移至本侧 S3 (跨大区流转)

在中转 EC2 使用已经配置好的 `awscli` 代理跨区域带宽同步。
```bash
aws s3 sync s3://源区-存储桶名/dpump_export/ s3://目标区-存储桶名/dpump_import/ \
--source-profile china-profile \
--profile global-profile
```
如果目标端和源端网络不通，则需要将源端的数据导出到本地，然后上传到目标端的 S3 存储桶。

### 第 4 步：目标端 RDS 拉取 S3 文件落盘

在准备好的**目标数据库**中，将文件通过内置包自 S3 剥回目标库主机 `DATA_PUMP_DIR` 目录等待导入。

**注意修改 bucket_name, s3_prefix, directory_name**

```sql
SELECT rdsadmin.rdsadmin_s3_tasks.download_from_s3(
      p_bucket_name    =>  'oracle-backup666',   -- 注意替换目标区存储桶名
      p_s3_prefix      =>  'dpump_import/',
      p_directory_name =>  'DATA_PUMP_DIR')
   AS TASK_ID FROM DUAL;
```

### 第 5 步：目标端全量导入 (Data Pump Import)

强烈建议挂起归档禁用参数，提升导入速度。目标端使用 `impdp`：

```bash
impdp admin/admin1234@target.cxymymkmm5sd.ap-east-1.rds.amazonaws.com:1521/ORCL \
DIRECTORY=DATA_PUMP_DIR \
DUMPFILE=export_demo_part%U.dmp \
LOGFILE=import_data.log \
TRANSFORM=DISABLE_ARCHIVE_LOGGING:Y \
METRICS=YES \
LOGTIME=ALL
```

查询导入日志，过滤ORA错误，查看上下文
```sql
SELECT text FROM table(rdsadmin.rds_file_util.read_text_file('DATA_PUMP_DIR','import_data.log')) where text like '%ORA-%';
```

---

## 6. 特殊问题与后置处理

### 物化视图 ORA-31685 权限失效导致建立失败拦截解决

*报错描述*：使用 `impdp` 若遭遇 `ORA-31685` 以及 `MATERIALIZED_VIEW` 对象建表失败（由于带着 USING 参数及部分权限控制等问题）。

**解决方案：通过以下 PL/SQL 在目标库暴力清洗、补充权限并自动重建：**

**注意修改 schema_name**

```sql
SET SERVEROUTPUT ON;
DECLARE
    v_obj_name   VARCHAR2(200);
    v_create_sql CLOB;
BEGIN
    -- 1. 前置补齐创建物化视图凭证 (示例为 SCHEMA_01 至 10，请依业务修正)
    FOR i IN 1..10 LOOP
        EXECUTE IMMEDIATE 'GRANT CREATE MATERIALIZED VIEW TO TEST_SCHEMA_' || LPAD(i, 2, '0');
    END LOOP;

    -- 2. 解析错误日志清理及修正语法
    FOR cur IN (
        SELECT text FROM table(rdsadmin.rds_file_util.read_text_file('DATA_PUMP_DIR', 'import_data.log')) 
        WHERE text LIKE '%CREATE MATERIALIZED VIEW%' AND text LIKE '% USING %' AND text LIKE '% REFRESH %'
    ) LOOP
        v_obj_name := SUBSTR(cur.text, INSTR(cur.text, 'VIEW "') + 5, INSTR(cur.text, '" (') - (INSTR(cur.text, 'VIEW "') + 5) + 1);
        v_create_sql := SUBSTR(cur.text, INSTR(cur.text, 'CREATE MATERIALIZED VIEW'), INSTR(cur.text, ' USING ') - INSTR(cur.text, 'CREATE MATERIALIZED VIEW')) || SUBSTR(cur.text, INSTR(cur.text, ' REFRESH '));
        
        -- 移除残余的空表和旧视图
        BEGIN EXECUTE IMMEDIATE 'DROP MATERIALIZED VIEW ' || v_obj_name; EXCEPTION WHEN OTHERS THEN NULL; END;
        BEGIN EXECUTE IMMEDIATE 'DROP TABLE ' || v_obj_name || ' CASCADE CONSTRAINTS'; EXCEPTION WHEN OTHERS THEN NULL; END;
        
        -- 重新运用无杂项环境建立
        BEGIN EXECUTE IMMEDIATE v_create_sql; EXCEPTION WHEN OTHERS THEN DBMS_OUTPUT.PUT_LINE('修复失败 ' || v_obj_name || ' : ' || SQLERRM); END;
    END LOOP;
    DBMS_OUTPUT.PUT_LINE('所有丢失的物化视图自动清理重建完毕！');
END;
/
```

### 收尾极速性能调优：强行分析并收集全库统计信息

不要继承并信赖源库过时的优化信息配置，全新环境应当重新采样。

```sql
-- 1. 先重置底层字典包
BEGIN DBMS_STATS.GATHER_DICTIONARY_STATS; END;
/

-- 2. 自动循环对所有业务 Schema 生成极速统计策略 (Standard版强制 Degree=1)
BEGIN
    FOR cur IN (SELECT username FROM dba_users WHERE oracle_maintained = 'N') LOOP
        DBMS_STATS.GATHER_SCHEMA_STATS(
            ownname          => cur.username,
            estimate_percent => DBMS_STATS.AUTO_SAMPLE_SIZE,
            method_opt       => 'FOR ALL COLUMNS SIZE AUTO',
            cascade          => TRUE, 
            degree           => 1     
        );
    END LOOP;
END;
/
```

### 交付核验与垃圾回收

成功迁移完毕后务必执行以下校验与空间清理。

- [ ] **交付比对**：使用 http://localhost:3000 对比核心业务下所有目标端与源端所有对象是否一致。
- [ ] **物理清理卸载**：
  在 RDS 内移除遗留下来的 .dmp 大尺寸数据包文件：
  `EXEC UTL_FILE.FREMOVE('DATA_PUMP_DIR', 'export_demo_part1_01.dmp');`
  通过 `awscli` 将 S3 Bucket 中的残留打包数据彻底删除：
  `aws s3 rm s3://oracle-backup666/dpump_import/ --recursive`

