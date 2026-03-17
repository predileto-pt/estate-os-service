resource "aws_sqs_queue" "this_deadletter" {
  count = var.create && var.create_dlq ? 1 : 0

  content_based_deduplication = try(coalesce(var.sqs_dq_content_based_deduplication, var.sqs_content_based_deduplication), null)
  deduplication_scope         = try(coalesce(var.sqs_dq_deduplication_scope, var.sqs_deduplication_scope), null)
  delay_seconds               = try(coalesce(var.sqs_dq_delay_seconds, var.sqs_delay_seconds), null)
  fifo_queue                  = var.sqs_fifo_queue
  fifo_throughput_limit       = var.sqs_fifo_throughput_limit
  max_message_size            = var.sqs_max_message_size
  message_retention_seconds   = try(coalesce(var.sqs_dq_message_retention_seconds, var.sqs_message_retention_seconds), null)
  name                        = var.sqs_fifo_queue ? "${local.dlq_name}.fifo" : local.dlq_name
  receive_wait_time_seconds   = try(coalesce(var.sqs_dq_receive_wait_time_seconds, var.sqs_receive_wait_time_seconds), null)
  visibility_timeout_seconds  = try(coalesce(var.sqs_dq_visibility_timeout_seconds, var.sqs_visibility_timeout_seconds), null)
}

resource "aws_sqs_queue" "this" {
  count = var.create ? 1 : 0

  name                        = var.sqs_fifo_queue ? "${local.name}.fifo" : local.name
  fifo_queue                  = var.sqs_fifo_queue
  deduplication_scope         = var.sqs_deduplication_scope
  fifo_throughput_limit       = var.sqs_fifo_throughput_limit
  content_based_deduplication = var.sqs_content_based_deduplication
  delay_seconds               = var.sqs_delay_seconds
  visibility_timeout_seconds  = var.sqs_visibility_timeout_seconds
  max_message_size            = var.sqs_max_message_size
  message_retention_seconds   = var.sqs_message_retention_seconds
  receive_wait_time_seconds   = var.sqs_receive_wait_time_seconds

  sqs_managed_sse_enabled = true

}

resource "aws_sqs_queue_redrive_policy" "this" {
  count = var.create && !var.create_dlq && length(var.sqs_redrive_policy) > 0 ? 1 : 0

  queue_url      = aws_sqs_queue.this[0].url
  redrive_policy = jsonencode(var.sqs_redrive_policy)
}

resource "aws_sqs_queue_redrive_policy" "dlq" {
  count = var.create && var.create_dlq ? 1 : 0

  queue_url = aws_sqs_queue.this[0].url
  redrive_policy = jsonencode(
    merge(
      {
        deadLetterTargetArn = aws_sqs_queue.this_deadletter[0].arn
        maxReceiveCount     = 5
      },
      var.sqs_redrive_policy
    )
  )
}