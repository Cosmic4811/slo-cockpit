# Alert e-mails: Alertmanager publishes to this SNS topic, SNS e-mails you.

resource "aws_sns_topic" "alerts" {
  name              = "${var.project}-alerts"
  kms_master_key_id = "alias/aws/sns" # encrypt stored messages with the free AWS-managed key
}

# AWS e-mails you a "Confirm subscription" link. Nothing is delivered until you click it.
resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}
