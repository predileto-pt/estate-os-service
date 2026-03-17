variable "domain" {
  type        = string
  description = "Certificate Domain"
}

variable "subject_alternative_names" {
  type        = list(string)
  description = "(Optional) Set of domains that should be SANs in the issued certificate. To remove all elements of a previously configured list, set this value equal to an empty list ([]) or use the terraform taint command to trigger recreation."
  default     = []
}