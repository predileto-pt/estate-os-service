output "instance_id" {
  value = aws_instance.this.id
}

output "primary_network_interface_id" {
  description = "ENI id used by the VPC's private route table to route 0.0.0.0/0 through this NAT."
  value       = aws_instance.this.primary_network_interface_id
}

output "public_ip" {
  value = aws_instance.this.public_ip
}

output "security_group_id" {
  value = aws_security_group.this.id
}
