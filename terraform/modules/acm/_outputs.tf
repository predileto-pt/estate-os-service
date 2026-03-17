output "arn" {
  value       = aws_acm_certificate.this.arn
  description = "ARN of the certificate"
}

output "domain_name" {
  value       = tolist(aws_acm_certificate.this.domain_validation_options)[0].domain_name
  description = "Domain to be validated"
}

output "resource_record_name" {
  value       = tolist(aws_acm_certificate.this.domain_validation_options)[0].resource_record_name
  description = "The name of the DNS record to create to validate the certificate"
}

output "resource_record_type" {
  value       = tolist(aws_acm_certificate.this.domain_validation_options)[0].resource_record_type
  description = "The type of DNS record to create"
}

output "resource_record_value" {
  value       = tolist(aws_acm_certificate.this.domain_validation_options)[0].resource_record_value
  description = "The value the DNS record needs to have"
}