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
  description = "Set as the Coolify project-level `S3_IMAGES_BUCKET_NAME` env var. Bucket is private; reads go through CloudFront only."
  value       = module.images_bucket.name
}

# ACM DNS validation record. Operator adds this CNAME in Vercel for the
# `predileto.pt` zone — `acm_validation_record_name` → `acm_validation_record_value`.
# Once propagated (~1-10 min), `aws_acm_certificate_validation.images` flips
# to ISSUED and CloudFront can attach the cert.
output "acm_validation_record_name" {
  description = "Vercel DNS: CNAME name to add for ACM validation of cdn_domain_name."
  value       = tolist(aws_acm_certificate.images.domain_validation_options)[0].resource_record_name
}

output "acm_validation_record_value" {
  description = "Vercel DNS: CNAME value for the ACM validation record."
  value       = tolist(aws_acm_certificate.images.domain_validation_options)[0].resource_record_value
}

output "acm_validation_record_type" {
  description = "Vercel DNS: record type for the ACM validation (always CNAME for DNS-validated certs)."
  value       = tolist(aws_acm_certificate.images.domain_validation_options)[0].resource_record_type
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
