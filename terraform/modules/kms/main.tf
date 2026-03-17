resource "aws_kms_key" "this" {
  description             = var.kms_description
  key_usage               = "ENCRYPT_DECRYPT"
  enable_key_rotation     = var.kms_enable_key_rotation
  deletion_window_in_days = 20
}

resource "aws_kms_key_policy" "this" {
  key_id = aws_kms_key.this.id
  policy = jsonencode({
    Version = "2012-10-17"
    Id      = "key-default-${var.kms_name}"
    Statement = [
      {
        Sid    = "Enable IAM User Permissions"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${var.account_id}:root"
        },
        Action   = "kms:*"
        Resource = "*"
      }
    ]
  })
}