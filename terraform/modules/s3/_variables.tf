variable bucket_name {
  type        = string
  default     = "Bucket Name"
}

variable "enable_cors" {
  description = "Flag to enable cors rule"
  type        = bool
  default     = false
}

variable "cors_rules" {
  description = "CORS rules for the S3 bucket"
  type        = list(object({
    allowed_headers = list(string)
    allowed_methods = list(string)
    allowed_origins = list(string)
    expose_headers  = list(string)
    max_age_seconds = optional(number)
  }))
  default = []
}

variable "enable_encryption_and_policy" {
  description = "Flag to enable server side encryption and bucket policy"
  type        = bool
  default     = true
}

variable "enable_lifecycle_rules" {
  description = "Flag to enable lifecycle rules"
  type        = bool
  default     = false
}

variable "lifecycle_rules" {
  description = "List of lifecycle rules to apply to the bucket"
  type = list(object({
    id                                              = string
    enabled                                         = bool
    prefix                                          = optional(string)
    expiration_days                                 = optional(number)
    transition_days                                 = optional(number)
    transition_storage_class                        = optional(string)
    noncurrent_version_transition_days              = optional(number)
    noncurrent_version_transition_storage_class     = optional(string)
    noncurrent_version_expiration_days              = optional(number)
    abort_incomplete_multipart_upload_days          = optional(number)
  }))
  default = []
}
// -> s3 bucket website
variable "s3_website_configuration_enable" {
  type = bool
  default = false
}

variable "index_document" {
  type = string
  description = "(Optional, Required if redirect_all_requests_to is not specified) Name of the index document for the website. See below."
  default = "index.html"
}

variable "error_document" {
  type = string
  description = "(Optional, Conflicts with redirect_all_requests_to) Name of the error document for the website. See below."
  default = "200.html"
}

variable "event_notification" {
  type        = bool
  description = "Create Event Notification?"
  default     = false
}

variable "sqs_notifications" {
  description = "Map of S3 bucket notifications to SQS queue"
  type        = any
  default     = {}
}

variable "sns_notifications" {
  description = "Map of S3 bucket notifications to SNS topic"
  type        = any
  default     = {}
}

variable "lambda_notifications" {
  description = "Map of S3 bucket notifications to Lambda function"
  type        = any
  default     = {}
}

variable "enable_bucket_policy" {
  description = "Flag to enable bucket policy"
  type        = bool
  default     = false
}

variable "bucket_policy" {
  description = "Bucket policy for the S3 bucket"
  type        = string
  default     = ""
}