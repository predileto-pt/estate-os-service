variable "name_prefix" {
  description = "Resource name prefix (e.g. `estate-os-service-prod`)."
  type        = string
}

variable "vpc_id" {
  description = "VPC where the NAT EC2 lives."
  type        = string
}

variable "public_subnet_id" {
  description = "ID of the **public** subnet for the NAT EC2. Must have a route to the IGW."
  type        = string
}

variable "private_subnet_cidrs" {
  description = "CIDRs of the private subnets that send outbound traffic through this NAT. Used for the inbound security group rule."
  type        = list(string)
}

variable "ami_id" {
  description = "AMI for the NAT EC2. Default is Amazon Linux 2023 ARM; pass an x86 AMI if `instance_type` is x86."
  type        = string
}

variable "instance_type" {
  description = "NAT EC2 size. `t4g.nano` (~$3.50/mo) is enough for tens of Mbps. Bump to `t4g.micro` if you see sustained outbound bandwidth saturation."
  type        = string
  default     = "t4g.nano"
}

variable "key_name" {
  description = "SSH key pair name (for emergency shell access)."
  type        = string
}

variable "tags" {
  description = "Extra tags merged into all resources."
  type        = map(string)
  default     = {}
}
