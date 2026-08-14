resource "aws_iam_policy" "scoped" {
  name        = "loom-terraform-scoped"
  description = "Scoped permissions for loom-terraform. Widen here, never in the console."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3FullProjectScope"
        Effect = "Allow"
        Action = ["s3:*"]
        Resource = [
          "arn:aws:s3:::loom-*",
          "arn:aws:s3:::loom-*/*"
        ]
      },
      {
        Sid      = "DynamoDBFullProjectScope"
        Effect   = "Allow"
        Action   = ["dynamodb:*"]
        Resource = "arn:aws:dynamodb:*:${data.aws_caller_identity.current.account_id}:table/loom-*"
      },
      {
        Sid    = "IAMProjectScope"
        Effect = "Allow"
        Action = ["iam:*"]
        Resource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/loom-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/loom-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/loom-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/token.actions.githubusercontent.com"
        ]
      },
      {
        # The experiment runner instance carries loom-experiment-runner, so the
        # launch call has to be allowed to hand that role to EC2. Scoped to the
        # loom-* role prefix and to the EC2 service, so it cannot be used to
        # escalate onto some other principal's role.
        Sid      = "IAMPassRoleToEC2"
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/loom-*"
        Condition = {
          StringEquals = {
            "iam:PassedToService" = "ec2.amazonaws.com"
          }
        }
      },
      {
        # Creation calls name resources that either do not exist yet (instances,
        # security groups, launch templates, spot requests) or are owned by AWS
        # (the Deep Learning AMI and its snapshots), so there is no ARN to scope
        # against. Mutation of anything that results is caught by
        # EC2MutateProjectTagged below.
        Sid    = "EC2CreateAndLaunch"
        Effect = "Allow"
        Action = [
          "ec2:RunInstances",
          "ec2:RequestSpotInstances",
          "ec2:CreateSecurityGroup",
          "ec2:CreateLaunchTemplate",
          "ec2:CreateLaunchTemplateVersion",
          "ec2:CreateVolume",
          "ec2:CreateNetworkInterface",
          "ec2:CreateKeyPair",
          "ec2:ImportKeyPair"
        ]
        Resource = "*"
      },
      {
        # Tag-on-create: allowed only when the request carries Project=loom,
        # which every provider in this repo does via default_tags.
        Sid      = "EC2TagOnCreate"
        Effect   = "Allow"
        Action   = ["ec2:CreateTags"]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:RequestTag/Project" = "loom"
          }
        }
      },
      {
        # Everything mutating after creation — TerminateInstances,
        # DeleteSecurityGroup, AuthorizeSecurityGroup*, DeleteLaunchTemplate,
        # CancelSpotInstanceRequests, DeleteTags, DeleteVolume — scoped by the
        # resource's own Project tag. Read calls are covered by ReadAll.
        Sid      = "EC2MutateProjectTagged"
        Effect   = "Allow"
        Action   = ["ec2:*"]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:ResourceTag/Project" = "loom"
          }
        }
      },
      {
        Sid    = "IAMSelfManagement"
        Effect = "Allow"
        Action = [
          "iam:AttachUserPolicy",
          "iam:DetachUserPolicy",
          "iam:CreatePolicyVersion",
          "iam:DeletePolicyVersion",
          "iam:ListPolicyVersions",
          "iam:TagUser",
          "iam:UntagUser"
        ]
        Resource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/loom-terraform",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/loom-terraform-scoped"
        ]
      },
      {
        Sid      = "ReadAll"
        Effect   = "Allow"
        Action   = ["*:Get*", "*:Describe*", "*:List*"]
        Resource = "*"
      },
      {
        Sid      = "STSCallerIdentity"
        Effect   = "Allow"
        Action   = ["sts:GetCallerIdentity"]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_user_policy_attachment" "scoped" {
  user       = data.aws_iam_user.self.user_name
  policy_arn = aws_iam_policy.scoped.arn
}
