###############################################################################
# NAT instance — single EC2 acting as the egress NAT for private subnets.
#
# Why an EC2 instead of `aws_nat_gateway`? Cost. A managed NAT Gateway is
# ~$32/mo fixed + data + per-hour; a `t4g.nano` is ~$3.50/mo with the same
# functional outcome for low-throughput workloads (background workers
# making HTTPS calls, DB egress to public endpoints).
#
# Operational trade-off: a single NAT EC2 in one AZ is a single point of
# failure. For v1 that's acceptable; if AZ-a goes down, the workers in
# private subnets lose outbound egress (they don't serve user traffic).
# Upgrade path: add a second NAT EC2 in AZ-b + per-subnet route tables.
#
# How it works:
#   1. `source_dest_check = false` lets the instance forward traffic that
#      isn't destined for its own IP.
#   2. `user_data` enables IPv4 forwarding + iptables MASQUERADE so
#      packets from private subnets get NAT'd to the instance's public IP.
#   3. The instance's primary ENI is exported; the VPC module's
#      private route table points 0.0.0.0/0 at this ENI.
###############################################################################

resource "aws_security_group" "this" {
  name        = "${var.name_prefix}-nat-sg"
  description = "Egress NAT - accepts traffic from private subnets, allows all outbound."
  vpc_id      = var.vpc_id

  ingress {
    description = "Allow outbound traffic from private subnets (any protocol)."
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = var.private_subnet_cidrs
  }

  ingress {
    description = "SSH for emergency access."
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-nat-sg" })
}

resource "aws_instance" "this" {
  ami                         = var.ami_id
  instance_type               = var.instance_type
  key_name                    = var.key_name
  subnet_id                   = var.public_subnet_id
  associate_public_ip_address = true
  source_dest_check           = false
  vpc_security_group_ids      = [aws_security_group.this.id]

  # Re-create the instance whenever user_data changes. Without this,
  # Terraform marks user_data updates as "in-place" but the script
  # only runs on first boot - meaning a fixed script in code never
  # actually executes on the running NAT. Forcing replacement makes
  # `terraform apply` a real fix path.
  user_data_replace_on_change = true

  user_data = base64encode(<<-EOT
    #!/bin/bash
    set -euo pipefail

    # Persist IPv4 forwarding across reboots.
    echo "net.ipv4.ip_forward = 1" > /etc/sysctl.d/99-nat.conf
    sysctl -p /etc/sysctl.d/99-nat.conf

    # Detect the primary egress interface. AL2023 uses systemd
    # predictable interface names (e.g. `ens5`), not the legacy
    # `eth0`. Hardcoding `eth0` here silently breaks NAT - the
    # MASQUERADE rule never matches and the private subnet's
    # outbound packets exit with their original 10.0.x.x source,
    # which the VPC drops as unroutable. Reading the default
    # route's interface keeps this robust across AMI changes.
    PRIMARY_IF=$(ip route show default | awk '/^default/ {print $5}')

    # iptables MASQUERADE on the detected primary ENI.
    yum install -y iptables-services
    iptables -t nat -A POSTROUTING -o "$PRIMARY_IF" -j MASQUERADE
    iptables -F FORWARD
    /usr/sbin/iptables-save > /etc/sysconfig/iptables
    systemctl enable iptables
    systemctl start iptables
  EOT
  )

  root_block_device {
    volume_type = "gp3"
    volume_size = 8
    encrypted   = true
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-nat" })
}
