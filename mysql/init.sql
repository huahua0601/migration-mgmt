CREATE DATABASE IF NOT EXISTS migration_mgmt CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE migration_mgmt;

CREATE TABLE users (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    username    VARCHAR(64)  NOT NULL UNIQUE,
    password    VARCHAR(256) NOT NULL,
    email       VARCHAR(128) DEFAULT NULL,
    role        VARCHAR(20)  NOT NULL DEFAULT 'user',
    is_active   TINYINT(1)   NOT NULL DEFAULT 1,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE db_configs (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(128) NOT NULL,
    db_type     VARCHAR(20)  NOT NULL COMMENT 'oracle / mysql / postgresql',
    host        VARCHAR(256) NOT NULL,
    port        INT          NOT NULL DEFAULT 1521,
    service_name VARCHAR(128) DEFAULT NULL,
    username    VARCHAR(128) NOT NULL,
    password    VARCHAR(256) NOT NULL,
    description TEXT         DEFAULT NULL,
    created_by  BIGINT       DEFAULT NULL,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE snapshots (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(256) NOT NULL,
    db_info     JSON         DEFAULT NULL COMMENT 'host, version, banner, db_name',
    summary     JSON         DEFAULT NULL COMMENT 'schema_count, total_tables, total_objects, total_rows',
    schema_list JSON         DEFAULT NULL COMMENT 'list of schema names',
    file_path   VARCHAR(512) NOT NULL,
    file_size   BIGINT       DEFAULT 0,
    uploaded_by BIGINT       DEFAULT NULL,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE comparison_tasks (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(256) NOT NULL,
    mode        VARCHAR(20)  NOT NULL DEFAULT 'snapshot_vs_db' COMMENT 'snapshot_vs_db / db_vs_db',
    source_snapshot_id BIGINT DEFAULT NULL,
    source_db_id BIGINT      DEFAULT NULL,
    target_db_id BIGINT      DEFAULT NULL,
    status      VARCHAR(20)  NOT NULL DEFAULT 'pending' COMMENT 'pending/running/completed/failed',
    progress    INT          NOT NULL DEFAULT 0,
    summary     JSON         DEFAULT NULL,
    created_by  BIGINT       DEFAULT NULL,
    started_at  DATETIME     DEFAULT NULL,
    finished_at DATETIME     DEFAULT NULL,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (source_snapshot_id) REFERENCES snapshots(id),
    FOREIGN KEY (source_db_id) REFERENCES db_configs(id),
    FOREIGN KEY (target_db_id) REFERENCES db_configs(id),
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE comparison_results (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    task_id     BIGINT       NOT NULL,
    schema_name VARCHAR(128) NOT NULL,
    object_type VARCHAR(50)  NOT NULL,
    object_name VARCHAR(256) NOT NULL,
    match_status VARCHAR(20) NOT NULL COMMENT 'match/mismatch/source_only/target_only',
    source_value TEXT         DEFAULT NULL,
    target_value TEXT         DEFAULT NULL,
    details     JSON         DEFAULT NULL,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES comparison_tasks(id) ON DELETE CASCADE,
    INDEX idx_task_schema (task_id, schema_name),
    INDEX idx_task_status (task_id, match_status)
);

-- Default admin user (password: admin123)
INSERT INTO users (username, password, email, role)
VALUES ('admin', '$2b$12$G6o9VzGo.uZcDMReBgoPBeiqCjt/K6bf3OExolXbm5.tXEmj3K8C6', 'admin@example.com', 'admin');
