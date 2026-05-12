output "alb_dns_name" {
  description = "ALB hostname. CNAME `api.predileto.pt` to this in Vercel DNS."
  value       = module.alb.dns_name
}

# Vercel manages DNS for predileto.pt. To wire `api.predileto.pt` →
# ALB, create the following records in Vercel:
#
# 1. ACM cert validation (one-shot, needed before the cert turns
#    `ISSUED`):
#       CNAME `acm_validation_record_name`  →  `acm_validation_record_value`
#
# 2. API host:
#       CNAME `api.predileto.pt`  →  `alb_dns_name`
#
# Once both are in place, the ALB serves HTTPS for `api.predileto.pt`
# using the ACM cert.
output "acm_validation_record_name" {
  description = "DNS record name to add to Vercel to validate the ACM cert."
  value       = module.acm.resource_record_name
}

output "acm_validation_record_value" {
  description = "DNS record value to add to Vercel to validate the ACM cert."
  value       = module.acm.resource_record_value
}

output "acm_validation_record_type" {
  description = "DNS record type for the ACM validation (always CNAME for DNS-validated certs)."
  value       = module.acm.resource_record_type
}

output "nat_instance_id" {
  value = module.nat_instance.instance_id
}

output "nat_public_ip" {
  description = "Public IP of the NAT EC2. Outbound traffic from private subnets exits via this IP."
  value       = module.nat_instance.public_ip
}

output "ec2_instance_id" {
  value = module.ec2.instance_id
}

output "bastion_public_ip" {
  description = "SSH to this with the private key matching var.bastion_public_key; then ProxyJump to the API EC2's private IP."
  value       = aws_eip.bastion.public_ip
}

output "ecr_repository_url" {
  value = module.ecr.repository_url
}

output "extraction_queue_url" {
  description = "URL for SQS_PROPERTY_EXTRACTION_QUEUE_URL in the EC2 .env."
  value       = module.extraction_queue.id
}

output "enrichment_queue_url" {
  description = "URL for SQS_PROPERTY_ENRICHMENT_QUEUE_URL in the EC2 .env."
  value       = module.enrichment_queue.id
}

output "listings_events_queue_url" {
  description = "URL for SQS_LISTINGS_EVENTS_QUEUE_URL in the EC2 .env."
  value       = module.listings_events_queue.id
}

output "s3_bucket_name" {
  value = module.documents_bucket.name
}

output "github_actions_role_arn" {
  description = "ARN to set as the `AWS_GHA_ROLE_ARN` secret in the GitHub `production` environment."
  value       = aws_iam_role.github_actions.arn
}
