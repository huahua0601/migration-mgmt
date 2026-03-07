# Migration Management System

数据库迁移一致性校验平台，用于验证 Oracle 数据库迁移后源库与目标库之间的数据和结构一致性。

## 架构

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Frontend   │────▶│   Backend    │────▶│    MySQL     │
│  React/Nginx │     │   FastAPI    │     │   8.0        │
│  :3000       │     │   :8000      │     │   :3307      │
└──────────────┘     └──────┬───────┘     └──────────────┘
                            │
                     ┌──────▼───────┐
                     │  Oracle DB   │
                     │  (目标库)     │
                     └──────────────┘

┌──────────────────────────────────────────────┐
│  Export Tool (独立运行在源库所在网络)            │
│  export_tool.py → snapshot.json              │
│  支持网络隔离场景：导出快照 → 上传到 Web 系统   │
└──────────────────────────────────────────────┘
```

| 服务 | 技术栈 | 说明 |
|------|--------|------|
| Frontend | React + Vite + Ant Design | 中文界面，Nginx 反向代理 |
| Backend | FastAPI + SQLAlchemy + Alembic | RESTful API，JWT 认证 |
| Database | MySQL 8.0 | 存储用户、配置、任务、比对结果 |
| Export Tool | Python + oracledb | 独立 CLI 工具，支持离线导出 |

## 功能

### 用户管理
- JWT 认证登录
- 管理员可创建、编辑、删除用户
- 角色区分 (admin / user)

### 数据库配置
- 管理目标数据库连接信息（Oracle）
- 支持连接测试（保存前/保存后均可测试）
- 自动获取数据库 Schema 列表

### 源库快照
- 使用 Export Tool 从源库导出元数据快照 (JSON)
- 上传快照到系统，支持查看详情
- 适用于**源库与目标库不在同一网络**的场景

### 数据比对
- **快照 vs 在线库** — 离线快照与目标库实时比较
- 比对覆盖范围：

| 对象类型 | 比较方式 |
|----------|----------|
| TABLE | 存在性 |
| COLUMN | 字段名、类型、长度、精度、可空性 |
| CONSTRAINT | 约束名、类型、状态 |
| INDEX | 索引名、类型、唯一性 |
| VIEW | 视图定义文本 |
| SEQUENCE | 属性（排除动态字段 last_number） |
| FUNCTION / PROCEDURE / PACKAGE | PL/SQL 源代码 |
| TRIGGER | 类型、触发事件 |
| TYPE / SYNONYM / MVIEW / DB_LINK | 属性对比 |
| DATA_COUNT | 表行数 |
| DATA_CHECKSUM | ORA_HASH 采样校验 (前 1000 行) |

- 后台线程异步执行，进度实时显示
- 结果支持按 Schema / 对象类型 / 状态筛选

## 快速开始

### 前置条件
- Docker & Docker Compose
- Python 3.10+（仅 Export Tool 需要）

### 部署

```bash
cd migration-mgmt

# 启动所有服务
docker compose up -d

# 等待 MySQL 健康检查通过后，Backend 自动运行 Alembic 迁移
# 默认管理员账号: admin / admin123
```

服务地址：
- Web 界面: `http://<IP>:3000`
- API: `http://<IP>:8000`
- MySQL: `<IP>:3307` (user: mgmt / mgmt123456)

### 环境变量

Backend 通过环境变量配置，在 `docker-compose.yml` 中设置：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| DB_HOST | mysql | MySQL 地址 |
| DB_PORT | 3306 | MySQL 端口 |
| DB_USER | mgmt | MySQL 用户 |
| DB_PASSWORD | mgmt123456 | MySQL 密码 |
| DB_NAME | migration_mgmt | 数据库名 |
| JWT_SECRET | migration-mgmt-secret-key-2026 | JWT 签名密钥 |

## 使用 Export Tool 导出源库快照

Export Tool 是独立脚本，可在源库所在网络中运行。

### 安装依赖

```bash
cd export-tool
pip3 install oracledb
```

### 导出

```bash
# Shell 包装脚本（推荐，支持交互式输入）
./export.sh -h <源库地址> -s <Service Name> -u <用户名> -p <密码> -o snapshot.json

# 指定 Schema
./export.sh -h 10.0.1.100 -s ORCL -u admin -p mypass -S SCHEMA1,SCHEMA2 -o snapshot.json

# 交互式模式（密码不回显）
./export.sh

# 直接使用 Python 脚本
python3 export_tool.py --host 10.0.1.100 --service ORCL --user admin --password mypass --output snapshot.json
```

### 导出参数

| 参数 | 说明 |
|------|------|
| `-h, --host` | 源库地址（必填） |
| `-P, --port` | 端口（默认 1521） |
| `-s, --service` | Oracle Service Name（必填） |
| `-u, --user` | 数据库用户名（必填） |
| `-p, --password` | 数据库密码 |
| `-S, --schemas` | 指定 Schema，逗号分隔（默认导出所有非系统 Schema） |
| `-o, --output` | 输出文件路径 |
| `-w, --parallel` | 并行线程数（默认 8） |
| `--skip-checksums` | 跳过数据校验和计算 |
| `--checksum-sample` | 校验和采样行数（默认 1000） |

### 工作流程

```
1. 在源库网络运行 Export Tool → 生成 snapshot.json
2. 将 snapshot.json 传输到可访问 Web 系统的环境
3. Web 系统 → 源库快照 → 上传快照
4. Web 系统 → 数据比对 → 新建比对 → 快照 vs 在线库
5. 查看比对结果
```

## 数据库迁移管理 (Alembic)

使用 Alembic 管理数据库 Schema 版本。Backend 启动时自动执行 `alembic upgrade head`。

```bash
# 进入后端容器
docker exec -it mgmt-backend bash

# 查看当前版本
alembic current

# 自动生成迁移（根据 models 变化）
alembic revision --autogenerate -m "描述信息"

# 手动执行迁移
alembic upgrade head

# 回滚一个版本
alembic downgrade -1
```

## 项目结构

```
migration-mgmt/
├── docker-compose.yml              # 服务编排
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── entrypoint.py               # 启动入口（迁移 + uvicorn）
│   ├── alembic.ini                 # Alembic 配置
│   ├── alembic/                    # 数据库迁移
│   │   ├── env.py
│   │   └── versions/
│   └── app/
│       ├── main.py                 # FastAPI 应用入口
│       ├── config.py               # 环境变量配置
│       ├── database.py             # SQLAlchemy 连接
│       ├── models/                 # ORM 模型
│       ├── schemas/                # Pydantic 请求/响应
│       ├── routers/                # API 路由
│       │   ├── auth.py             # 认证
│       │   ├── db_config.py        # 数据库配置
│       │   ├── snapshot.py         # 快照管理
│       │   └── comparison.py       # 比对任务
│       ├── services/
│       │   └── comparison.py       # 比对引擎核心逻辑
│       └── utils/
│           └── auth.py             # JWT 工具
├── frontend/
│   ├── Dockerfile
│   ├── nginx.conf                  # Nginx 反向代理
│   ├── package.json
│   └── src/
│       ├── App.jsx                 # 路由 & 布局
│       ├── api/index.js            # API 客户端
│       └── pages/                  # 页面组件
├── export-tool/
│   ├── export.sh                   # Shell 包装脚本
│   └── export_tool.py              # 源库导出工具
└── mysql/
    └── init.sql                    # 初始 Schema（已由 Alembic 接管）
```

## API 概览

| 路径 | 说明 |
|------|------|
| `POST /api/auth/login` | 登录，返回 JWT |
| `GET /api/auth/me` | 获取当前用户 |
| `GET/POST /api/users` | 用户管理 (Admin) |
| `GET/POST /api/db-configs` | 数据库配置 CRUD |
| `POST /api/db-configs/test-connection` | 测试数据库连接（免保存） |
| `GET/POST /api/snapshots` | 快照上传/列表 |
| `GET /api/snapshots/{id}/detail` | 快照详情 |
| `GET/POST /api/comparisons` | 比对任务管理 |
| `GET /api/comparisons/{id}/results` | 比对结果（支持筛选） |
| `GET /api/comparisons/{id}/summary` | 比对汇总统计 |
