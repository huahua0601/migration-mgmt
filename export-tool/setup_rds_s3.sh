#!/usr/bin/env bash
#
# 配置 RDS Oracle S3 集成
#
# 此脚本需要有 IAM 和 RDS 管理权限的 AWS CLI 环境中执行
# （如 AWS CloudShell、管理员 IAM 用户等）
#
# 用法:
#   chmod +x setup_rds_s3.sh
#   ./setup_rds_s3.sh
#
set -euo pipefail

# ============ 请根据实际情况修改以下变量 ============
REGION="ap-east-1"
ACCOUNT_ID="410751716398"
S3_BUCKET="oracle-backup666"
RDS_INSTANCES=("source" "target")                 # ← 需要开启 S3_INTEGRATION 的实例列表
ROLE_NAME="rds-oracle-s3-integration"
POLICY_NAME="rds-oracle-s3-access"
# ===================================================

echo "=========================================="
echo " RDS Oracle S3 集成配置"
echo "=========================================="
echo " Region:       $REGION"
echo " Account:      $ACCOUNT_ID"
echo " RDS Instances: ${RDS_INSTANCES[*]}"
echo " S3 Bucket:    $S3_BUCKET"
echo " IAM Role:     $ROLE_NAME"
echo "=========================================="
echo

# ---------- Step 1: 创建 IAM Role ----------
echo "[Step 1/5] 创建 IAM Role: $ROLE_NAME"

TRUST_POLICY=$(cat <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "rds.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF
)

if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
    echo "  Role 已存在，跳过创建"
else
    aws iam create-role \
        --role-name "$ROLE_NAME" \
        --assume-role-policy-document "$TRUST_POLICY" \
        --description "Allow RDS Oracle to access S3 for Data Pump" \
        --output text --query 'Role.Arn'
    echo "  Role 创建成功"
fi

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
echo "  Role ARN: $ROLE_ARN"
echo

# ---------- Step 2: 附加 S3 访问策略 ----------
echo "[Step 2/5] 附加 S3 访问策略"

S3_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket",
        "s3:GetBucketLocation",
        "s3:AbortMultipartUpload",
        "s3:ListMultipartUploadParts"
      ],
      "Resource": [
        "arn:aws:s3:::${S3_BUCKET}",
        "arn:aws:s3:::${S3_BUCKET}/*"
      ]
    }
  ]
}
EOF
)

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "$POLICY_NAME" \
    --policy-document "$S3_POLICY"
echo "  策略已附加"
echo

# ============================================================
# setup_instance: 为单个 RDS 实例配置 Option Group + S3 Role
# 参数: $1 = RDS 实例标识符
# ============================================================
setup_instance() {
    local INST="$1"
    echo "------------------------------------------"
    echo " 配置实例: $INST"
    echo "------------------------------------------"

    # --- 查找当前 Option Group ---
    echo "  [a] 查找 Option Group"

    local OG
    OG=$(aws rds describe-db-instances \
        --region "$REGION" \
        --db-instance-identifier "$INST" \
        --query 'DBInstances[0].OptionGroupMemberships[0].OptionGroupName' \
        --output text)

    local EV
    EV=$(aws rds describe-db-instances \
        --region "$REGION" \
        --db-instance-identifier "$INST" \
        --query 'DBInstances[0].EngineVersion' \
        --output text)

    local MV
    MV=$(echo "$EV" | cut -d. -f1)

    echo "      当前 Option Group: $OG"
    echo "      Engine Version:    $EV  (Major: $MV)"

    if [[ "$OG" == default:* ]]; then
        local NEW_OG="oracle-s3-og-${MV}"
        echo "      默认 Option Group 不可修改，使用: $NEW_OG"

        if aws rds describe-option-groups --region "$REGION" \
            --option-group-name "$NEW_OG" >/dev/null 2>&1; then
            echo "      Option Group $NEW_OG 已存在"
        else
            aws rds create-option-group \
                --region "$REGION" \
                --option-group-name "$NEW_OG" \
                --engine-name "oracle-ee" \
                --major-engine-version "$MV" \
                --option-group-description "Oracle with S3 integration" \
                --output text --query 'OptionGroup.OptionGroupName'
            echo "      Option Group $NEW_OG 创建成功"
        fi
        OG="$NEW_OG"
    fi

    # --- 添加 S3_INTEGRATION ---
    echo "  [b] 添加 S3_INTEGRATION 到 Option Group: $OG"

    local EXISTING
    EXISTING=$(aws rds describe-option-groups \
        --region "$REGION" \
        --option-group-name "$OG" \
        --query 'OptionGroupsList[0].Options[*].OptionName' \
        --output text)

    if echo "$EXISTING" | grep -q "S3_INTEGRATION"; then
        echo "      S3_INTEGRATION 已存在，跳过"
    else
        aws rds add-option-to-option-group \
            --region "$REGION" \
            --option-group-name "$OG" \
            --options "OptionName=S3_INTEGRATION,OptionVersion=1.0,OptionSettings=[]" \
            --apply-immediately \
            --output text --query 'OptionGroup.OptionGroupName'
        echo "      S3_INTEGRATION 添加成功"
    fi

    # --- 应用 Option Group 到实例 ---
    echo "  [c] 应用 Option Group 到实例"

    local CUR_OG
    CUR_OG=$(aws rds describe-db-instances \
        --region "$REGION" \
        --db-instance-identifier "$INST" \
        --query 'DBInstances[0].OptionGroupMemberships[0].OptionGroupName' \
        --output text)

    if [[ "$CUR_OG" != "$OG" ]]; then
        echo "      更新: $CUR_OG -> $OG"
        aws rds modify-db-instance \
            --region "$REGION" \
            --db-instance-identifier "$INST" \
            --option-group-name "$OG" \
            --apply-immediately \
            --output text --query 'DBInstance.DBInstanceStatus'
        echo "      Option Group 已更新（需要等待 in-sync）"
    else
        echo "      Option Group 已是最新"
    fi

    # --- 关联 IAM Role ---
    echo "  [d] 关联 IAM Role"

    local ROLES
    ROLES=$(aws rds describe-db-instances \
        --region "$REGION" \
        --db-instance-identifier "$INST" \
        --query 'DBInstances[0].AssociatedRoles[*].RoleArn' \
        --output text)

    if echo "$ROLES" | grep -q "$ROLE_NAME"; then
        echo "      IAM Role 已关联，跳过"
    else
        aws rds add-role-to-db-instance \
            --region "$REGION" \
            --db-instance-identifier "$INST" \
            --feature-name "S3_INTEGRATION" \
            --role-arn "$ROLE_ARN"
        echo "      IAM Role 关联成功"
    fi

    echo "  ✓ 实例 $INST 配置完成"
    echo
}

# ---------- Step 3: 为每个 RDS 实例配置 S3 集成 ----------
TOTAL=${#RDS_INSTANCES[@]}
IDX=0
for INST in "${RDS_INSTANCES[@]}"; do
    IDX=$((IDX + 1))
    echo "[Step 3/$TOTAL] 配置实例 $IDX/$TOTAL: $INST"
    setup_instance "$INST"
done

echo "=========================================="
echo " 全部配置完成！"
echo "=========================================="
echo
echo " 如果修改了 Option Group，请等待实例状态变为 'available' 且 Option Group 为 'in-sync'"
echo " 监控命令:"
for INST in "${RDS_INSTANCES[@]}"; do
    echo "   aws rds describe-db-instances --region $REGION \\"
    echo "     --db-instance-identifier $INST \\"
    echo "     --query 'DBInstances[0].{Status:DBInstanceStatus,OG:OptionGroupMemberships,Roles:AssociatedRoles}'"
    echo
done
echo " 实例就绪后，运行 Data Pump 导出:"
echo "   python3 rds_dump.py"
echo
