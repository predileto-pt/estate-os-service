output "id" {
  value = aws_sqs_queue.this[0].id
}

output "arn" {
  value = aws_sqs_queue.this[0].arn
}

output "name" {
  value = aws_sqs_queue.this[0].name
}

output "dq_id" {
  value = try(aws_sqs_queue.this_deadletter[0].id, null)
}

output "dq_arn" {
  value = try(aws_sqs_queue.this_deadletter[0].arn, null)
}

output "dq_name" {
  value = try(aws_sqs_queue.this_deadletter[0].name, null)
}