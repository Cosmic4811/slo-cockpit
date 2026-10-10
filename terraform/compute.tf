# The server: one small EC2 instance with NO inbound ports open.

resource "aws_security_group" "instance" {
  name_prefix = "${var.project}-"
  description = "SLO cockpit: no inbound traffic at all; outbound HTTP/HTTPS only"
  vpc_id      = data.aws_vpc.default.id

  lifecycle {
    create_before_destroy = true
  }
}

# Deliberately NO ingress rules. Nobody on the internet can even try to connect.
# We reach the server through AWS Systems Manager, which the server dials out to.

resource "aws_vpc_security_group_egress_rule" "https" {
  security_group_id = aws_security_group.instance.id
  description       = "HTTPS: AWS APIs (SSM, S3, SNS), container registries, Docker package repo"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "http" {
  security_group_id = aws_security_group.instance.id
  description       = "HTTP: Ubuntu package mirrors (packages are signature-checked)"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = "0.0.0.0/0"
}

locals {
  # First-boot script. Line endings are forced to Linux style, in case Windows added "\r".
  user_data = replace(templatefile("${path.module}/user_data.sh.tftpl", {
    aws_region        = var.aws_region
    bundle_bucket     = aws_s3_bucket.artifacts.id
    bundle_key        = aws_s3_object.stack.key
    bundle_sha256     = data.archive_file.stack.output_sha256
    deploy_script_b64 = base64encode(replace(file("${path.module}/files/slo-deploy.sh"), "\r\n", "\n"))
    ansible_vars_json = jsonencode({
      aws_region                 = var.aws_region
      sns_topic_arn              = aws_sns_topic.alerts.arn
      grafana_password_parameter = aws_ssm_parameter.grafana_admin_password.name
      admin_token_parameter      = aws_ssm_parameter.shop_api_admin_token.name
      swap_size_mb               = var.swap_size_mb
    })
  }), "\r\n", "\n")
}

resource "aws_instance" "cockpit" {
  ami                         = data.aws_ami.ubuntu.id
  instance_type               = var.instance_type
  subnet_id                   = local.subnet_id
  vpc_security_group_ids      = [aws_security_group.instance.id]
  iam_instance_profile        = aws_iam_instance_profile.instance.name
  associate_public_ip_address = true  # to reach the internet without a paid NAT gateway (inbound stays blocked)
  monitoring                  = false # detailed CloudWatch monitoring costs extra

  user_data                   = local.user_data
  user_data_replace_on_change = true # new bundle = brand-new server (immutable infrastructure)

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required" # IMDSv2 only: stops SSRF-style credential theft
    http_put_response_hop_limit = 2          # lets Alertmanager (in a container) sign SNS calls;
    instance_metadata_tags      = "disabled" # a host firewall rule blocks every other container
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_gb
    encrypted             = true
    delete_on_termination = true
  }

  tags = {
    Name = var.project
  }

  lifecycle {
    ignore_changes = [ami] # don't replace the server just because Ubuntu published a newer image

    precondition {
      condition     = local.subnet_id != null
      error_message = "No default subnet found in this region. Create the default VPC with: aws ec2 create-default-vpc --profile slo --region <your region>"
    }
  }

  # The permissions must exist before the server boots and starts downloading.
  depends_on = [aws_iam_role_policy.instance, aws_iam_role_policy_attachment.ssm_core]
}
