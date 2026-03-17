variable "repository_name" {
  description = "Name of the ECR repository"
  type        = string
}

variable "image_tag_mutability" {
  description = "The tag mutability setting for the repository"
  type        = string
  default     = "MUTABLE"
  validation {
    condition     = contains(["MUTABLE", "IMMUTABLE"], var.image_tag_mutability)
    error_message = "Image tag mutability must be either MUTABLE or IMMUTABLE."
  }
}

variable "scan_on_push" {
  description = "Indicates whether images are scanned after being pushed to the repository"
  type        = bool
  default     = true
}

variable "encryption_configuration" {
  description = "Encryption configuration for the repository"
  type = object({
    encryption_type = string
    kms_key         = optional(string)
  })
  default = {
    encryption_type = "AES256"
  }
}

variable "lifecycle_policy" {
  description = "The policy document for the repository lifecycle policy"
  type        = string
  default     = null
}

variable "repository_policy" {
  description = "The policy document for the repository"
  type        = string
  default     = null
}

variable "tags" {
  description = "A map of tags to assign to the resource"
  type        = map(string)
  default     = {}
}

variable "force_delete" {
  description = "If true, will delete the repository even if it contains images"
  type        = bool
  default     = false
} 