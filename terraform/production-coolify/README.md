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
- **S3 bucket** `estate-os-service-prod-property-images` — private,
  fronted by CloudFront. Same AES256 + public-access-block posture
  as documents. Ownership controls `BucketOwnerEnforced` (ACLs
  disabled). Bucket policy locks `s3:GetObject` to the CloudFront
  distribution via `AWS:SourceArn` condition; direct
  `<bucket>.s3.amazonaws.com` URLs return 403.
- **CloudFront distribution** for `images.predileto.pt` — Origin
  Access Control (OAC sigv4) reads from the images bucket;
  response-headers policy stamps
  `Cache-Control: public, max-age=31536000, immutable` on every
  response (image keys are UUID-stamped → immutable forever).
- **ACM certificate** for `images.predileto.pt` — DNS-validated, in
  `us-east-1` (CloudFront requirement). Operator adds the validation
  CNAME at Vercel during section 10 of the runbook.
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

## Multi-region footprint

The default provider region is `eu-west-3` (Paris) — where the S3
buckets, ECR repo, and IAM principals live. The ACM certificate for
the CDN is in `us-east-1` via the `aws.us_east_1` aliased provider
in `_providers.tf`; this is mandatory for CloudFront custom-domain
TLS, regardless of where the origin sits.

The CloudFront distribution itself is a global AWS resource — it
accepts the us-east-1 cert ARN even though the rest of the stack
is in eu-west-3.

**`terraform destroy` ordering caveat.** CloudFront blocks cert
deletion while the distribution is associated. To tear down cleanly:

1. `aws cloudfront update-distribution --id <id> --distribution-config ...`
   with `Enabled=false`, then wait for `Status = Deployed`.
2. `aws cloudfront delete-distribution --id <id> --if-match <ETag>`
   (only works once disabled-and-deployed has propagated).
3. Then `terraform destroy` can remove the cert.

Terraform v5+ AWS provider handles step 1+2 automatically when you
`terraform destroy` the distribution — but it takes 15–30 minutes.
Don't `^C` mid-destroy.

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
| `images_cdn_distribution_id` | `aws cloudfront create-invalidation` / status checks |
| `images_cdn_domain` | Vercel DNS: CNAME target for `images.predileto.pt` |
| `acm_validation_record_name` | Vercel DNS: CNAME name for ACM validation |
| `acm_validation_record_value` | Vercel DNS: CNAME value for ACM validation |
| `acm_validation_record_type` | Vercel DNS: record type (always `CNAME`) |
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
