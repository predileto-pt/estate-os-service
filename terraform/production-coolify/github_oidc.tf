resource "aws_iam_role" "github_actions" {
  name = "${var.prefix_name}-github-actions"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = data.aws_iam_openid_connect_provider.github_actions.arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
          StringLike = {
            "token.actions.githubusercontent.com:sub" = [
              "repo:predileto-pt/estate-os-service:environment:production",
              "repo:predileto-pt/estate-os-service:ref:refs/heads/main",
            ]
          }
        }
      }
    ]
  })
}

# ECR push only. No lambda:*, ssm:*, ec2:*, or s3:* — the dormant
# production/github_oidc.tf carries those for the Lambda/EC2 revert path
# and stays untouched.
resource "aws_iam_role_policy" "github_actions_ecr" {
  name = "${var.prefix_name}-github-ecr"
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
        ]
        Resource = module.ecr.repository_arn
      }
    ]
  })
}
