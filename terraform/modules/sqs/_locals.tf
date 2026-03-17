locals {
  name     = "${try(trimsuffix(var.sqs_name, ".fifo"), "")}-${var.environment}"
  dlq_name = "${try(trimsuffix(var.sqs_name, ".fifo"), "")}-${var.environment}-dq"
}