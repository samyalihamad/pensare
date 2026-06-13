# Pensare AWS deploy

Provision and operate the AWS side of pensare: **S3-native project storage** and the
**serverless online kanban board**. One shared bucket + one shared Lambda + one
Function URL serve every project, keyed by an S3 prefix per project.

```
Browser ──HTTPS──> Lambda Function URL ──boto3──> S3 (one bucket, contexts/<project>/…)
  serves the board HTML AND /api/board · /api/items/{id}
  auth: ?k=<per-project secret>  (hmac-checked in the Lambda)
```

## Files

| File | Purpose |
|------|---------|
| `bootstrap.sh` | **One-time.** Checks AWS CLI + creds, creates the bucket, IAM role, Lambda, and Function URL. Re-runnable (updates the Lambda code). Writes `.pensare-infra.json`. |
| `provision-project.sh <project> [--kanban]` | **Per project.** Generates the board secret, writes the stub `sources.json`, uploads it + seeds the journal manifest to S3. `--kanban` also prints the private board URL. |
| `lambda-build.sh` | Zips `lib/{storage,kanban_core,lambda_handler}.py` flat into `kanban-lambda.zip`. |
| `iam-policy.json` | Least-privilege S3 policy template (`__BUCKET__` substituted by bootstrap). |
| `.pensare-infra.json` | **Generated, gitignored.** Records bucket/region/function_url for `provision-project.sh`. |

## Prerequisites

- An AWS account, and the AWS CLI configured on this machine:
  ```bash
  pip3 install --user awscli boto3     # if not already installed
  aws configure                        # access key, secret, region (e.g. us-east-1)
  ```
- `boto3` available to your `python3` (the S3-backed pensare commands import it locally;
  the Lambda already has it).

## Usage

```bash
# 1) one-time shared infrastructure
deploy/bootstrap.sh

# 2) per project — usually run for you by `/pensare setup` (choose AWS S3)
deploy/provision-project.sh my-project --kanban
#   → prints:  https://<fn-url>/?project=my-project&k=<secret>
```

Region defaults to `us-east-1`; override with `AWS_REGION=eu-west-1 deploy/bootstrap.sh`.

## Security model (private-to-me)

The board is gated by a 256-bit secret embedded in the URL (`?k=…`) and re-sent by the
page's JS on every API call; the Lambda compares it in constant time against
`s3://<bucket>/contexts/<project>/.board-secret`. TLS protects it in transit. The secret
lives locally in `~/.claude/contexts/<project>/.board-secret` (gitignored) and in S3 for
comparison — never inside a committed file.

**Rotate** a board's secret: `deploy/provision-project.sh <project> --kanban` regenerates
nothing by default (it reuses the sidecar); to force a new secret, delete
`~/.claude/contexts/<project>/.board-secret` first, then re-run — the old URL then 403s.

## Cost

S3 text storage is cents/month; Lambda + Function URL idle is ~$0 (pay per request).
Realistic idle cost is well under $1/month. Don't leave the board tab open indefinitely
(it polls every 30s).

## Teardown

```bash
aws lambda delete-function --function-name pensare-kanban
aws lambda delete-function-url-config --function-name pensare-kanban   # if needed
aws iam delete-role-policy --role-name pensare-kanban-role --policy-name pensare-s3
aws iam detach-role-policy --role-name pensare-kanban-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam delete-role --role-name pensare-kanban-role
aws s3 rb s3://pensare-store-<account> --force      # deletes ALL project data
```
