# --> VPC
output "vpc_id" {
  value       = aws_vpc.this.id
  description = "VPC id"
}

# --> Subnets ids
output "presentation_subnets_ids" {
  value       = local.presentation_subnets_ids
  description = "List of public subnets IDs"
}

output "logic_subnets_ids" {
  value       = local.logic_subnets_ids
  description = "List of private subnets IDs"
}

output "data_subnets_ids" {
  value       = local.data_subnets_ids
  description = "List of private subnets IDs"
}

# --> Subnets cidrs
output "presentation_subnets_cidrs" {
  value       = local.presentation_subnets_cidrs
  description = "List of public subnets CIDRs"
}

output "logic_subnets_cidrs" {
  value       = local.logic_subnets_cidrs
  description = "List of private subnets CIDRs"
}

output "data_subnets_cidrs" {
  value       = local.data_subnets_cidrs
  description = "List of private subnets CIDRs"
}

# --> Subnets ids
output "subnet_ids" {
  value       = local.subnet_ids
  description = "List of public and private subnets IDs"
}

# --> Subnets cidrs
output "subnet_cidrs" {
  value       = local.subnet_cidrs
  description = "List of public and private subnets CIDRs"
}