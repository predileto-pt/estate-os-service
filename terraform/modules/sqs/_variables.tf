variable "create" {
  description = "Whether to create SQS queue"
  type        = bool
  default     = true
}

variable "create_dlq" {
  description = "To create a dead letter queue"
  type        = string
  default     = false
}

variable "sqs_name" {
  type        = string
  description = "SQS Name"
  default     = null
}

variable "environment" {
  type        = string
  description = "Environment"
}

# SQS DeadLetter
variable "sqs_dq_delay_seconds" {
  type        = number
  description = "SQS Delay Second"
  default     = 0
}

variable "sqs_dq_visibility_timeout_seconds" {
  type        = number
  description = "SQS Visibility Timeout"
  default     = 30
}

variable "sqs_dq_max_message_size" {
  type        = number
  description = "SQS Max Message Size 262144 (256 KiB)"
  default     = 262144
}

variable "sqs_dq_message_retention_seconds" {
  type        = number
  description = "SQS Message Retention Seconds 345600 (4 days)"
  default     = 345600
}

variable "sqs_dq_receive_wait_time_seconds" {
  type        = number
  description = "SQS Receive Wait Time Seconds"
  default     = 0
}

variable "sqs_dq_content_based_deduplication" {
  description = "Enables content-based deduplication for FIFO queues"
  type        = bool
  default     = null
}

variable "sqs_dq_deduplication_scope" {
  description = "Specifies whether message deduplication occurs at the message group or queue level"
  type        = string
  default     = null
}

variable "sqs_redrive_policy" {
  description = "The JSON policy to set up the Dead Letter Queue"
  type        = any
  default     = {}
}

# SQS
variable "sqs_delay_seconds" {
  type        = number
  description = "SQS Delay Second"
  default     = 0
}

variable "sqs_visibility_timeout_seconds" {
  type        = number
  description = "SQS Visibility Timeout"
  default     = 30
}

variable "sqs_max_message_size" {
  type        = number
  description = "SQS Max Message Size 262144 (256 KiB)"
  default     = 262144
}

variable "sqs_message_retention_seconds" {
  type        = number
  description = "SQS Message Retention Seconds 345600 (4 days)"
  default     = 345600
}

variable "sqs_receive_wait_time_seconds" {
  type        = number
  description = "SQS Receive Wait Time Seconds"
  default     = 0
}

variable "sqs_max_receive_count" {
  type        = number
  description = "SQS Max Receibe Count in DeadLetter"
  default     = 4
}

variable "sqs_fifo_queue" {
  type        = bool
  description = "Boolean designating a FIFO queue"
  default     = false
}

variable "sqs_deduplication_scope" {
  type        = string
  description = "Specifies whether message deduplication occurs at the message group or queue level"
  default     = null
}

variable "sqs_content_based_deduplication" {
  description = "Enables content-based deduplication for FIFO queues"
  type        = bool
  default     = null
}

variable "sqs_fifo_throughput_limit" {
  description = "Specifies whether the FIFO queue throughput quota applies to the entire queue or per message group"
  type        = string
  default     = null
}