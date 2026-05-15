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
