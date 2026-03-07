#!/usr/bin/env bash
#
# Oracle 源库快照导出工具
#
# 用法:
#   ./export.sh                        # 交互式输入连接信息
#   ./export.sh -h host -s ORCL ...    # 命令行参数模式
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOL="$SCRIPT_DIR/export_tool.py"

# ---------- 默认值 ----------
HOST=""
PORT="1521"
SERVICE=""
USER=""
PASSWORD=""
SCHEMAS=""
OUTPUT=""
SKIP_CHECKSUMS=""
CHECKSUM_SAMPLE="1000"
PARALLEL="8"

usage() {
    cat <<EOF
Oracle 源库快照导出工具

用法: $(basename "$0") [选项]

选项:
  -h, --host HOST           源库地址 (必填)
  -P, --port PORT           端口 (默认: 1521)
  -s, --service SERVICE     Service Name (必填)
  -u, --user USER           数据库用户名 (必填)
  -p, --password PASSWORD   数据库密码 (不填则交互输入)
  -S, --schemas SCHEMAS     要导出的 schema，逗号分隔 (不填则导出所有非系统 schema)
  -o, --output FILE         输出文件路径 (默认: snapshot_<时间戳>.json)
  --skip-checksums          跳过数据校验和计算
  --checksum-sample N       校验和采样行数 (默认: 1000)
  -w, --parallel N          并行工作线程数 (默认: 8)
  --help                    显示帮助

示例:
  $(basename "$0") -h 10.0.1.100 -s ORCL -u admin -p mypass
  $(basename "$0") -h 10.0.1.100 -s ORCL -u admin -S SCHEMA1,SCHEMA2 -o backup.json
  $(basename "$0")   # 交互式模式
EOF
    exit 0
}

# ---------- 解析参数 ----------
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--host)       HOST="$2";             shift 2;;
        -P|--port)       PORT="$2";             shift 2;;
        -s|--service)    SERVICE="$2";          shift 2;;
        -u|--user)       USER="$2";             shift 2;;
        -p|--password)   PASSWORD="$2";         shift 2;;
        -S|--schemas)    SCHEMAS="$2";          shift 2;;
        -o|--output)     OUTPUT="$2";           shift 2;;
        --skip-checksums) SKIP_CHECKSUMS="yes"; shift;;
        --checksum-sample) CHECKSUM_SAMPLE="$2"; shift 2;;
        -w|--parallel) PARALLEL="$2"; shift 2;;
        --help)          usage;;
        *) echo "未知参数: $1"; usage;;
    esac
done

# ---------- 交互式补全 ----------
if [[ -z "$HOST" ]]; then
    read -rp "源库地址 (host): " HOST
fi
if [[ -z "$SERVICE" ]]; then
    read -rp "Service Name: " SERVICE
fi
if [[ -z "$USER" ]]; then
    read -rp "数据库用户名: " USER
fi
if [[ -z "$PASSWORD" ]]; then
    read -rsp "数据库密码: " PASSWORD
    echo
fi

if [[ -z "$HOST" || -z "$SERVICE" || -z "$USER" || -z "$PASSWORD" ]]; then
    echo "错误: host、service、user、password 均为必填项"
    exit 1
fi

# ---------- 检查依赖 ----------
if ! python3 -c "import oracledb" 2>/dev/null; then
    echo "正在安装 oracledb 模块..."
    pip3 install --quiet oracledb
fi

# ---------- 构造参数 ----------
ARGS=(
    --host "$HOST"
    --port "$PORT"
    --service "$SERVICE"
    --user "$USER"
    --password "$PASSWORD"
    --checksum-sample "$CHECKSUM_SAMPLE"
    --parallel "$PARALLEL"
)

[[ -n "$SCHEMAS" ]]        && ARGS+=(--schemas "$SCHEMAS")
[[ -n "$OUTPUT" ]]         && ARGS+=(--output "$OUTPUT")
[[ -n "$SKIP_CHECKSUMS" ]] && ARGS+=(--skip-checksums)

# ---------- 执行导出 ----------
echo "=========================================="
echo " Oracle 源库快照导出"
echo "=========================================="
echo " 目标: ${USER}@${HOST}:${PORT}/${SERVICE}"
[[ -n "$SCHEMAS" ]] && echo " Schemas: $SCHEMAS" || echo " Schemas: 自动检测"
echo " 并行线程: $PARALLEL"
echo "=========================================="
echo

python3 "$TOOL" "${ARGS[@]}"
