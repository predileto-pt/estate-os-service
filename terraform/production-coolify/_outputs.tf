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

output "github_actions_role_arn" {
  description = "Save as the `AWS_GHA_ROLE_ARN` secret in the GitHub `production` environment."
  value       = aws_iam_role.github_actions.arn
}
