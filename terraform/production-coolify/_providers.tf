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

# CloudFront's custom-domain TLS requires the ACM cert to live in
# us-east-1, regardless of where the origin bucket sits. Aliased
# provider used only by `acm.tf`; everything else continues to use the
# default eu-west-3 provider.
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
