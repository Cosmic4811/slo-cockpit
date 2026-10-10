# The server's identity (an IAM role). No access keys anywhere: AWS hands the
# server short-lived credentials automatically, limited to what is listed here.

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "instance" {
  name_prefix        = "${var.project}-"
  description        = "SLO cockpit server: SSM access, read its bundle and secrets, publish alerts"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

# Lets the server register with Systems Manager, so we can reach it without SSH.
resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Least privilege: exactly one bucket folder, two parameters and one topic.
data "aws_iam_policy_document" "instance" {
  statement {
    sid       = "ReadDeployBundle"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.artifacts.arn}/bundles/*"]
  }

  statement {
    sid     = "ReadOwnSecrets"
    actions = ["ssm:GetParameter"]
    resources = [
      aws_ssm_parameter.grafana_admin_password.arn,
      aws_ssm_parameter.shop_api_admin_token.arn,
    ]
  }

  statement {
    sid       = "SendAlertEmails"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
  }
}

resource "aws_iam_role_policy" "instance" {
  name   = "least-privilege"
  role   = aws_iam_role.instance.id
  policy = data.aws_iam_policy_document.instance.json
}

resource "aws_iam_instance_profile" "instance" {
  name_prefix = "${var.project}-"
  role        = aws_iam_role.instance.name
}
