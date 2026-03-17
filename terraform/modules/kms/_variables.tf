variable "kms_name" {
  description = "The name of the KMS key"
}

variable "kms_description" {
  description = "The description of the KMS key"
}

variable "kms_enable_key_rotation" {
  description = "Whether to enable key rotation"
  type        = bool
  default     = true
}

variable "account_id" {
  description = "The account ID"
}