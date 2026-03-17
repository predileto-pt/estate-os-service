terraform {
  required_version = "~> 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.32"
    }
  }

  backend "s3" {
    bucket         = "customers-dashboard-service-prod-terraform-state"
    key            = "terraform.tfstate"
    region         = "eu-west-3"
    dynamodb_table = "customers-dashboard-service-prod-terraform-locks"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "customers-dashboard-service"
      ManagedBy   = "terraform"
      Owner       = "predileto"
      Environment = "production"
    }
  }
}
