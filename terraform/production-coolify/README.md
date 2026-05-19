# terraform/production-coolify

AWS surface for the **Coolify/Hetzner production runtime**. Sibling
to `terraform/production/`; they share no state.

## What this stack owns

- **ECR repo** `estate-os-service` — image source for Coolify
  (consumed via the project-level `ECR_IMAGE` env var). Lifecycle
  policy keeps the last 20 image manifests and expires untagged
  layers after 7 days.
- **S3 bucket** `estate-os-service-prod-property-documents` — AES256
  encrypted, public-access-block enforced, no bucket policy.
- **S3 bucket** `estate-os-service-prod-property-images` — public-read
  for objects, fronted by Cloudflare. AES256 encrypted, ACLs disabled
  (`BucketOwnerEnforced`). Bucket policy grants `s3:GetObject` to `*`
  on `bucket/*`; `s3:ListBucket` is NOT granted, so directory
  enumeration via the bucket root is blocked and the only way to read
  an object is to know its UUID-keyed path. CORS allows GET/PUT/HEAD
  from the production Vercel domains + localhost for dev.
- **Public hostname `https://images.predileto.pt`** — Cloudflare-
  proxied CNAME targeting the bucket's S3 virtual-host hostname.
  Cloudflare terminates TLS for browsers and rewrites the `Host`
  header to the bucket's S3 hostname (Origin Rule in the Cloudflare
  dashboard) so S3 virtual-host routing works. No AWS-side TLS / ACM
  cert needed.
- **GitHub OIDC role** `estate-os-service-prod-github-actions` —
  assumable by `repo:predileto-pt/estate-os-service` (env=production
  or ref=main), scoped to ECR push only.
- **IAM user** `estate-os-service-prod-coolify-ecr-reader` — the
  Hetzner VM host uses this user's static keys to refresh
  `docker login` against ECR every 8h via a systemd timer.
  Read-only ECR access.
- **IAM user** `estate-os-service-prod-app-s3` — the api container
  uses this user's static keys at runtime (via
  `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` env vars from the
  Coolify project) to read/write/delete objects in **both** the
  documents bucket and the images bucket. Same actions
  (`s3:GetObject` / `PutObject` / `DeleteObject`), no other AWS
  access.

## Single-region footprint

Everything lives in `eu-west-3` (Paris) — S3 buckets, ECR repo, IAM
principals. The previous CloudFront + us-east-1-ACM-cert
multi-region setup was retired 2026-05-19 in favour of letting
Cloudflare terminate TLS in front of the public-read bucket.

## What stays in `terraform/production/`

The dormant Lambda + EC2 + ALB + VPC + NAT + SNS + SQS + Secrets
Manager stack — emergency revert path per ADR-018 addendum
(2026-05-13). Its code remains in the repo; its AWS resources are
deleted. Don't reapply that stack unless you're rolling back away
from Coolify.

## Apply

No tfvars file needed — both variables (`aws_region`, `prefix_name`)
have safe defaults.

```bash
cd terraform/production-coolify
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

Bootstrap prereq: the state bucket
`estate-os-service-prod-terraform-state` in `eu-west-3` must exist
before `terraform init`. The companion runbook (`docs/runbooks/coolify-first-deploy.md`)
covers the one-shot create command.

## Outputs

| Output | Goes to |
|---|---|
| `ecr_repository_url` | Coolify project-level env `ECR_IMAGE=<url>:latest` |
| `ecr_repository_arn` | Internal — referenced by IAM policies |
| `github_actions_role_arn` | GitHub repo `production` env secret `AWS_GHA_ROLE_ARN` |
| `documents_bucket_name` | Coolify project-level env `S3_BUCKET_NAME` |
| `images_bucket_name` | Coolify project-level env `S3_IMAGES_BUCKET_NAME` |
| `images_bucket_s3_host` | Cloudflare DNS: CNAME target for `images.predileto.pt` + Origin Rule `Host` header value |
| `coolify_ecr_reader_access_key_id` | VM `/root/.aws/credentials`, profile `coolify-ecr-reader` |
| `coolify_ecr_reader_secret_access_key` (sensitive) | Same — fetch via `terraform output -raw …` |
| `app_s3_access_key_id` | Coolify project-level env `AWS_ACCESS_KEY_ID` |
| `app_s3_secret_access_key` (sensitive) | Coolify project-level env `AWS_SECRET_ACCESS_KEY` |

## Rotation

Manual, both IAM users:

```bash
# Rotate Coolify ECR reader keys (host pull):
terraform taint aws_iam_access_key.coolify_ecr_reader
terraform apply
# Then re-do runbook section 2a on the VM.

# Rotate app S3 keys (api container):
terraform taint aws_iam_access_key.app_s3
terraform apply
# Then update the two project-level Coolify env vars.
```

## Operator step-by-step

See `docs/runbooks/coolify-first-deploy.md` for the sequenced bring-up
checklist.
