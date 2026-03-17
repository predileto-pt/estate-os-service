module "kms" {
  source = "../modules/kms"

  kms_name                = "${var.prefix_name}-secrets-key"
  kms_description         = "KMS key for Secrets Manager encryption"
  kms_enable_key_rotation = true
  account_id              = local.account_id
}

resource "aws_secretsmanager_secret" "app_secrets" {
  name       = var.prefix_name
  kms_key_id = module.kms.kms_key_id
}
