# ECR Terraform Module

This module creates an Amazon Elastic Container Registry (ECR) repository with configurable settings for image scanning, lifecycle policies, and access control.

## Features

- ✅ ECR repository creation
- ✅ Image vulnerability scanning
- ✅ Lifecycle policy management
- ✅ Repository access policies
- ✅ KMS encryption support
- ✅ Default lifecycle policy (keeps last 10 tagged images)

## Usage

### Basic Usage

```hcl
module "ecr" {
  source = "./modules/ecr"

  repository_name = "my-application"
  
  tags = {
    Environment = "production"
    Project     = "my-project"
  }
}
```

### Advanced Usage

```hcl
module "ecr" {
  source = "./modules/ecr"

  repository_name      = "my-application"
  image_tag_mutability = "IMMUTABLE"
  scan_on_push         = true
  force_delete         = true

  encryption_configuration = {
    encryption_type = "KMS"
    kms_key        = "alias/my-ecr-key"
  }

  lifecycle_policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 5 production images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["prod-"]
          countType     = "imageCountMoreThan"
          countNumber   = 5
        }
        action = {
          type = "expire"
        }
      }
    ]
  })

  repository_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::123456789012:role/ECSTaskRole"
        }
        Action = [
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:BatchCheckLayerAvailability"
        ]
      }
    ]
  })

  tags = {
    Environment = "production"
    Project     = "my-project"
  }
}
```

## Requirements

| Name | Version |
|------|---------|
| terraform | >= 1.0 |
| aws | ~> 5.0 |

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| repository_name | Name of the ECR repository | `string` | n/a | yes |
| image_tag_mutability | The tag mutability setting for the repository | `string` | `"MUTABLE"` | no |
| scan_on_push | Indicates whether images are scanned after being pushed | `bool` | `true` | no |
| encryption_configuration | Encryption configuration for the repository | `object` | `{encryption_type = "AES256"}` | no |
| lifecycle_policy | The policy document for the repository lifecycle policy | `string` | `null` | no |
| repository_policy | The policy document for the repository | `string` | `null` | no |
| force_delete | If true, will delete the repository even if it contains images | `bool` | `false` | no |
| tags | A map of tags to assign to the resource | `map(string)` | `{}` | no |

## Outputs

| Name | Description |
|------|-------------|
| repository_arn | Full ARN of the repository |
| repository_name | Name of the repository |
| repository_url | The URL of the repository |
| repository_uri | The URI of the repository |
| registry_id | The registry ID where the repository was created |

## Examples

See the `examples.tf` file for comprehensive usage examples.

## Default Lifecycle Policy

If no custom lifecycle policy is provided, the module applies a default policy that:
- Keeps the last 10 tagged images (with "v" prefix)
- Keeps the last 5 untagged images
- Expires older images automatically

## License

This module is released under the MIT License. 