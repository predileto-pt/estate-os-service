terraform {
  required_version = ">= 1.10, < 2.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.50"
    }
  }

  # Separate state file from `terraform/production/` (which owns the dormant
  # Lambda/EC2 revert path) — same state bucket, distinct key. S3-native
  # locking via `use_lockfile` (AWS provider 5.50+ / TF 1.10+).
  backend "s3" {
    bucket       = "estate-os-service-prod-terraform-state"
    key          = "coolify/terraform.tfstate"
    region       = "eu-west-3"
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "estate-os-service"
      ManagedBy   = "terraform"
      Owner       = "predileto"
      Environment = "production"
      Stack       = "coolify"
    }
  }
}

# Kept around solely so terraform can destroy the lingering
# `aws_acm_certificate.images` + `aws_acm_certificate_validation.images`
# state entries that this PR's apply removes. Once the apply completes
# and `terraform state list` no longer shows any `us_east_1`-bound
# resources, this block can be deleted in a follow-up commit. No
# AWS-side cost — provider blocks are pure config.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {
    tags = {
      Project     = "estate-os-service"
      ManagedBy   = "terraform"
      Owner       = "predileto"
      Environment = "production"
      Stack       = "coolify"
    }
  }
}
