output "db_instance_identifier" {
  value = aws_db_instance.this.identifier
}

output "db_instance_arn" {
  value = aws_db_instance.this.arn
}

output "db_instance_address" {
  value = aws_db_instance.this.address
}

output "db_password" {
  value     = random_password.this.result
  sensitive = true
}