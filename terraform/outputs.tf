output "instance_id" {
  description = "The server's ID (used by scripts/tunnel.py)."
  value       = aws_instance.cockpit.id
}

output "aws_region" {
  value = var.aws_region
}

output "aws_profile" {
  value = var.aws_profile
}

output "grafana_password_parameter" {
  description = "SSM parameter holding the Grafana admin password."
  value       = aws_ssm_parameter.grafana_admin_password.name
}

output "admin_token_parameter" {
  description = "SSM parameter holding the shop-api fault-injection token."
  value       = aws_ssm_parameter.shop_api_admin_token.name
}

output "sns_topic_arn" {
  value = aws_sns_topic.alerts.arn
}

output "next_steps" {
  value = <<-EOT

    1. Check your inbox (${var.alert_email}) and click "Confirm subscription".
    2. The server needs about 5 minutes to install everything. Meanwhile, from the project folder:
         python scripts/tunnel.py
       and open http://localhost:3000/d/slo-cockpit  (user: admin)
    3. Grafana password:  python scripts/tunnel.py --password
    4. When you are done:  terraform destroy
  EOT
}
