###############################################################################
# Coolify ECR reader.
#
# Used by the Hetzner VM host (NOT the api container) to refresh
# `docker login` every ~8h via a systemd timer. ECR auth tokens expire
# every 12h and Hetzner has no IAM instance profile, so this is the
# simplest reliable pull-side auth mechanism. See the runbook for the
# systemd unit text + setup steps.
#
# Concerns are kept separate from the api's S3 user (below) so a leak
# of either doesn't widen the other's scope.
###############################################################################

resource "aws_iam_user" "coolify_ecr_reader" {
  name = "${var.prefix_name}-coolify-ecr-reader"
}

resource "aws_iam_user_policy" "coolify_ecr_reader" {
  name = "${var.prefix_name}-coolify-ecr-read"
  user = aws_iam_user.coolify_ecr_reader.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # ECR auth is account-wide — `GetAuthorizationToken` must be * .
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      # Pull-side reads scoped to this stack's single repo.
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:DescribeRepositories",
          "ecr:ListImages",
        ]
        Resource = module.ecr.repository_arn
      }
    ]
  })
}

resource "aws_iam_access_key" "coolify_ecr_reader" {
  user = aws_iam_user.coolify_ecr_reader.name
}
