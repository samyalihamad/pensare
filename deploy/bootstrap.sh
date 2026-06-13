#!/usr/bin/env bash
#
# Pensare AWS bootstrap — ONE-TIME shared infrastructure for S3 storage and the
# online kanban board. Idempotent: safe to re-run (updates the Lambda code).
#
# Creates, in your AWS account:
#   - S3 bucket  pensare-store-<account>   (private, versioned, encrypted)
#   - IAM role   pensare-kanban-role       (Lambda exec + least-privilege S3)
#   - Lambda     pensare-kanban            (serves board HTML + /api, from S3)
#   - a Lambda Function URL (auth NONE; the per-project secret is the gate)
#
# Writes deploy/.pensare-infra.json (bucket, region, function_url) for
# provision-project.sh to consume. That file is gitignored.
#
# Prereq: an AWS account. This script checks for the AWS CLI + credentials and
# tells you how to set them up if missing.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGION="${AWS_REGION:-us-east-1}"
ROLE_NAME="pensare-kanban-role"
FUNC_NAME="pensare-kanban"

say() { printf '\033[1m%s\033[0m\n' "$*"; }

# ── Preflight ────────────────────────────────────────────────────────────────
if ! command -v aws >/dev/null 2>&1; then
  cat <<EOF
AWS CLI not found. Install it, then re-run this script:
  macOS:  brew install awscli
  other:  https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html
EOF
  exit 1
fi

if ! aws sts get-caller-identity >/dev/null 2>&1; then
  cat <<EOF
AWS credentials are not configured (aws sts get-caller-identity failed).
Configure them, then re-run:
  aws configure        # enter Access Key, Secret Key, region (e.g. $REGION)
EOF
  exit 1
fi

if ! python3 -c 'import boto3' >/dev/null 2>&1; then
  say "Note: boto3 not installed locally. S3-backed pensare commands need it:"
  echo "  pip3 install boto3"
  echo "  (the Lambda has boto3 built in; this is only for your local machine)"
fi

ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="pensare-store-${ACCOUNT}"
say "Account: ${ACCOUNT}   Region: ${REGION}   Bucket: ${BUCKET}"

# ── S3 bucket ────────────────────────────────────────────────────────────────
if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  echo "  bucket exists"
else
  say "Creating bucket ${BUCKET}"
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"
  else
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
      --create-bucket-configuration LocationConstraint="$REGION"
  fi
fi

aws s3api put-public-access-block --bucket "$BUCKET" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-versioning --bucket "$BUCKET" \
  --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --bucket "$BUCKET" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
echo "  bucket hardened (block-public, versioning, SSE-S3)"

# ── IAM role ─────────────────────────────────────────────────────────────────
POLICY_DOC="$(sed "s/__BUCKET__/${BUCKET}/g" "$HERE/iam-policy.json")"
TRUST='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  echo "  role exists"
else
  say "Creating IAM role ${ROLE_NAME}"
  aws iam create-role --role-name "$ROLE_NAME" \
    --assume-role-policy-document "$TRUST" >/dev/null
  aws iam attach-role-policy --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
  echo "  waiting for role to propagate..."; sleep 10
fi
aws iam put-role-policy --role-name "$ROLE_NAME" \
  --policy-name pensare-s3 --policy-document "$POLICY_DOC"
ROLE_ARN="$(aws iam get-role --role-name "$ROLE_NAME" --query Role.Arn --output text)"

# ── Lambda ───────────────────────────────────────────────────────────────────
say "Building Lambda bundle"
bash "$HERE/lambda-build.sh"
ZIP="$HERE/kanban-lambda.zip"

if aws lambda get-function --function-name "$FUNC_NAME" --region "$REGION" >/dev/null 2>&1; then
  say "Updating Lambda ${FUNC_NAME}"
  aws lambda update-function-code --function-name "$FUNC_NAME" --region "$REGION" \
    --zip-file "fileb://$ZIP" >/dev/null
  aws lambda wait function-updated --function-name "$FUNC_NAME" --region "$REGION"
  aws lambda update-function-configuration --function-name "$FUNC_NAME" --region "$REGION" \
    --environment "Variables={BUCKET=$BUCKET,REGION=$REGION}" >/dev/null
else
  say "Creating Lambda ${FUNC_NAME}"
  aws lambda create-function --function-name "$FUNC_NAME" --region "$REGION" \
    --runtime python3.12 --role "$ROLE_ARN" --handler lambda_handler.handler \
    --timeout 10 --memory-size 256 \
    --environment "Variables={BUCKET=$BUCKET,REGION=$REGION}" \
    --zip-file "fileb://$ZIP" >/dev/null
  aws lambda wait function-active --function-name "$FUNC_NAME" --region "$REGION"
fi

# ── Function URL (auth NONE; secret is the gate) ─────────────────────────────
if aws lambda get-function-url-config --function-name "$FUNC_NAME" --region "$REGION" >/dev/null 2>&1; then
  aws lambda update-function-url-config --function-name "$FUNC_NAME" --region "$REGION" \
    --auth-type NONE >/dev/null
else
  say "Creating Function URL"
  aws lambda create-function-url-config --function-name "$FUNC_NAME" --region "$REGION" \
    --auth-type NONE >/dev/null
fi

# Public (NONE-auth) function URLs require BOTH permissions since Oct 2025:
#   lambda:InvokeFunctionUrl  AND  lambda:InvokeFunction (invoked-via-function-url).
# add-permission errors if the statement-id already exists — ignore that.
aws lambda add-permission --function-name "$FUNC_NAME" --region "$REGION" \
  --statement-id FunctionURLAllowPublicAccess \
  --action lambda:InvokeFunctionUrl --principal '*' \
  --function-url-auth-type NONE >/dev/null 2>&1 || true
aws lambda add-permission --function-name "$FUNC_NAME" --region "$REGION" \
  --statement-id FunctionURLInvokeFunction \
  --action lambda:InvokeFunction --principal '*' \
  --invoked-via-function-url >/dev/null 2>&1 || true

FUNCTION_URL="$(aws lambda get-function-url-config --function-name "$FUNC_NAME" \
  --region "$REGION" --query FunctionUrl --output text)"

# ── Record shared infra ──────────────────────────────────────────────────────
cat > "$HERE/.pensare-infra.json" <<EOF
{
  "account": "${ACCOUNT}",
  "region": "${REGION}",
  "bucket": "${BUCKET}",
  "function_url": "${FUNCTION_URL}"
}
EOF

say "Done. Shared infra ready."
echo "  bucket:       ${BUCKET}"
echo "  function url: ${FUNCTION_URL}"
echo "  recorded in:  ${HERE}/.pensare-infra.json"
echo ""
echo "Next: create an S3-backed project with  /pensare setup  (choose AWS S3),"
echo "or provision an existing one:  deploy/provision-project.sh <project> --kanban"
