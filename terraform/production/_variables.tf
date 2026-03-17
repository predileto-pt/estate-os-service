variable "prefix_name" {
  type    = string
  default = "customers-dashboard-service-prod"
}

variable "aws_region" {
  type    = string
  default = "eu-west-3"
}

variable "ecr_image_tag" {
  type    = string
  default = "latest"
}

variable "instance_type" {
  type    = string
  default = "t3.small"
}

variable "volume_size" {
  type    = string
  default = "20"
}

variable "key_name" {
  type        = string
  description = "SSH key pair name for the EC2 instance"
}

variable "domain_name" {
  type    = string
  default = "api.predileto.pt"
}

variable "lambda_extraction_memory" {
  type    = number
  default = 1024
}

variable "lambda_extraction_timeout" {
  type    = number
  default = 900
}

variable "lambda_events_memory" {
  type    = number
  default = 1024
}

variable "lambda_events_timeout" {
  type    = number
  default = 120
}
