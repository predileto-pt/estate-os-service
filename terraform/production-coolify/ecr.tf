module "ecr" {
  source = "../modules/ecr"

  repository_name      = "estate-os-service"
  image_tag_mutability = "MUTABLE"
  scan_on_push         = true

  encryption_configuration = {
    encryption_type = "AES256"
  }

  # Override the module's default lifecycle policy. The default keys the
  # "keep last 10" rule on `tagPrefixList = ["v"]`, which never matches
  # our tag scheme (`latest` + 7-char SHA). Replace with an any-tag count
  # rule + untagged-by-age cleanup.
  #
  # `latest` is reassigned on every push, so the rolling-20 window always
  # includes the most recent manifest. ~20 builds ≈ 1 week of pushes, fine
  # for rollback range.
  lifecycle_policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 20 image manifests"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 20
        }
        action = {
          type = "expire"
        }
      },
      {
        rulePriority = 2
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
      }
    ]
  })
}
