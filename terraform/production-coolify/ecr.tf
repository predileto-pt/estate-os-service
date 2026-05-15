module "ecr" {
  source = "../modules/ecr"

  repository_name      = "estate-os-service"
  image_tag_mutability = "MUTABLE"
  scan_on_push         = true

  encryption_configuration = {
    encryption_type = "AES256"
  }

  # Override the module's default lifecycle policy. The default keys the
  # "keep last N" rule on `tagPrefixList = ["v"]`, which never matches
  # our tag scheme (`latest` + 7-char SHA).
  #
  # **ECR rule-ordering constraint**: a `tagStatus = "any"` rule must
  # have the LOWEST priority per storage class — meaning the HIGHEST
  # priority number (ECR processes rules in ascending priority and the
  # "any" catch-all runs last). So untagged-cleanup is priority 1; the
  # any-tag-count catch-all is priority 2.
  #
  # `latest` is reassigned on every push, so the rolling-20 window
  # always includes the most recent manifest. ~20 builds ≈ 1 week of
  # pushes, fine for rollback range.
  lifecycle_policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged manifests after 7 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = {
          type = "expire"
        }
      },
      {
        rulePriority = 2
        description  = "Keep last 20 image manifests"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 20
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}
