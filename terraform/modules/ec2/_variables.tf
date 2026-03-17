variable "ami" {
  description = "The AMI to use for the EC2 instance."
  type        = string
}

variable "instance_type" {
  description = "The type of instance to start."
  type        = string
}

variable "key_name" {
  description = "The key name to use for the instance."
  type        = string
}

variable "volume_type" {
  description = "The volume type to use for the instance."
  type        = string
}

variable "volume_size" {
  description = "The volume size to use for the instance."
  type        = string
}
variable "associate_public_ip_address" {
  description = "The associate public ip address to use for the instance."
  type        = bool
  default     = false
}

variable "subnet_id" {
  description = "The ID of the subnet where the EC2 instance will be launched."
  type        = string
}

variable "security_groups" {
  description = "A list of security group names to associate with the EC2 instance."
  type        = list(string)
}

variable "instance_name" {
  description = "The name of the EC2 instance."
  type        = string
}

variable "source_dest_check" {
  description = "Whether to enable source/destination check for the instance."
  type        = bool
  default     = true
}

variable "user_data" {
  description = "Base64-encoded user data script to run on instance launch."
  type        = string
  default     = null
}

variable "iam_instance_profile" {
  description = "IAM instance profile name to attach to the instance."
  type        = string
  default     = null
}