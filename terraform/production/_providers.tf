terraform {
  required_version = ">= 1.10, < 2.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.50"
    }
    # Used by `lambda.tf` to build a placeholder zip at plan time. The
    # placeholder satisfies the `aws_lambda_function.filename` requirement
    # at first apply; CI overwrites the function code (and publishes the
    # deps layer) via `aws lambda update-function-code` /
    # `publish-layer-version` on every push to main.
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }

  # S3-native locking (AWS provider 5.50+ / TF 1.10+). Replaces the
  # deprecated `dynamodb_table` lock — the DynamoDB table can be deleted
  # once every operator's local state has been re-locked under `.tflock`.
  backend "s3" {
    bucket       = "estate-os-service-prod-terraform-state"
    key          = "terraform.tfstate"
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
    }
  }
}
