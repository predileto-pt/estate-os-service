output "kms_key_id" {
  value = aws_kms_key.this.id
}

output "kms_key_arn" {
  value = aws_kms_key.this.arn
}