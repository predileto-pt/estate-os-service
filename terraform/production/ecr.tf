module "ecr" {
  source = "../modules/ecr"

  repository_name      = "estate-os-service"
  image_tag_mutability = "MUTABLE"
  scan_on_push         = true

  encryption_configuration = {
    encryption_type = "AES256"
  }
}
