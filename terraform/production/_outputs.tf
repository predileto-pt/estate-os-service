output "alb_dns_name" {
  value = module.alb.dns_name
}

output "ec2_instance_id" {
  value = module.ec2.instance_id
}

output "ecr_repository_url" {
  value = module.ecr.repository_url
}

output "extraction_queue_url" {
  value = module.extraction_queue.id
}

output "events_queue_url" {
  value = module.events_queue.id
}

output "s3_bucket_name" {
  value = module.documents_bucket.name
}

output "github_actions_role_arn" {
  value = aws_iam_role.github_actions.arn
}

output "extraction_worker_lambda_arn" {
  value = aws_lambda_function.extraction_worker.arn
}

output "events_worker_lambda_arn" {
  value = aws_lambda_function.events_worker.arn
}
