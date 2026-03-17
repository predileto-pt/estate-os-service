locals {
  account_id = data.aws_caller_identity.current.account_id
  ecr_image  = "${local.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com/${module.ecr.repository_name}:${var.ecr_image_tag}"
}
