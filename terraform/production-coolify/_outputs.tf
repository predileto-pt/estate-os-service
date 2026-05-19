# Outputs are added here as each resource lands. Consumed by:
#   - Coolify UI (image source, AWS creds for app/host)
#   - GitHub Actions `production` environment secrets (role ARN, webhook)
#   - The VM's `/root/.aws/credentials` (Coolify ECR reader keys)

output "ecr_repository_url" {
  description = "Image source for the Coolify UI's per-service `image:` (used via the project-level $ECR_IMAGE env, see runbook section 6)."
  value       = module.ecr.repository_url
}

output "ecr_repository_arn" {
  description = "ARN of the ECR repo; referenced by IAM policies in github_oidc.tf and iam.tf."
  value       = module.ecr.repository_arn
}

output "documents_bucket_name" {
  description = "Set as the Coolify project-level `S3_BUCKET_NAME` env var (consumed by api + all 3 workers)."
  value       = module.documents_bucket.name
}

output "images_bucket_name" {
  description = "Set as the Coolify project-level `S3_IMAGES_BUCKET_NAME` env var. Public-read for objects; reads happen over https://images.predileto.pt (Cloudflare-proxied CNAME with Host header rewrite)."
  value       = module.images_bucket.name
}

output "images_bucket_s3_host" {
  description = "Bucket's S3 virtual-host hostname. Used as the Cloudflare CNAME target for `images.predileto.pt` AND as the Cloudflare Origin Rule's Host-header override value."
  value       = "${module.images_bucket.name}.s3.${var.aws_region}.amazonaws.com"
}

output "github_actions_role_arn" {
  description = "Save as the `AWS_GHA_ROLE_ARN` secret in the GitHub `production` environment."
  value       = aws_iam_role.github_actions.arn
}

output "coolify_ecr_reader_access_key_id" {
  description = "Access key id for the VM host's `/root/.aws/credentials` profile `coolify-ecr-reader` (used by the systemd timer to refresh `docker login`)."
  value       = aws_iam_access_key.coolify_ecr_reader.id
}

output "coolify_ecr_reader_secret_access_key" {
  description = "Secret for the VM host's `coolify-ecr-reader` profile. Retrieve with `terraform output -raw coolify_ecr_reader_secret_access_key`."
  value       = aws_iam_access_key.coolify_ecr_reader.secret
  sensitive   = true
}

output "app_s3_access_key_id" {
  description = "Access key id for the api/worker containers' AWS_ACCESS_KEY_ID env (set at the Coolify project level)."
  value       = aws_iam_access_key.app_s3.id
}

output "app_s3_secret_access_key" {
  description = "Secret for the api/worker containers' AWS_SECRET_ACCESS_KEY env. Retrieve with `terraform output -raw app_s3_secret_access_key`."
  value       = aws_iam_access_key.app_s3.secret
  sensitive   = true
}
