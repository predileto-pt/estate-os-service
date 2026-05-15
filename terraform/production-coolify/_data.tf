data "aws_caller_identity" "current" {}

# Account-level singleton — created once outside any project's terraform.
# `production/github_oidc.tf` references the same data source.
data "aws_iam_openid_connect_provider" "github_actions" {
  url = "https://token.actions.githubusercontent.com"
}
