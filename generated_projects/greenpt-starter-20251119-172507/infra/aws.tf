## AWS Infrastructure Configuration
provider "aws" {
  region = "us-west-2"
}

## IAM Roles and Permissions
resource "aws_iam_role" "lambda_exec" {
  name        = "lambda_exec"
  description = "Execution role for Lambda functions"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_policy" "lambda_policy" {
  name        = "lambda_policy"
  description = "Policy for Lambda functions"

  policy      = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Effect = "Allow"
        Resource = "arn:aws:logs:*:*:*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_attach" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = aws_iam_policy.lambda_policy.arn
}

## AWS Lambda Functions
resource "aws_lambda_function" "game_analysis" {
  filename      = "game_analysis.zip"
  function_name = "game_analysis"
  handler       = "index.handler"
  runtime       = "nodejs14.x"
  role          = aws_iam_role.lambda_exec.arn
}

resource "aws_lambda_function" "user_auth" {
  filename      = "user_auth.zip"
  function_name = "user_auth"
  handler       = "index.handler"
  runtime       = "nodejs14.x"
  role          = aws_iam_role.lambda_exec.arn
}

## API Gateway
resource "aws_api_gateway_rest_api" "gaming_assistant" {
  name        = "gaming_assistant"
  description = "API for gaming assistant"
}

resource "aws_api_gateway_resource" "games" {
  rest_api_id = aws_api_gateway_rest_api.gaming_assistant.id
  parent_id   = aws_api_gateway_rest_api.gaming_assistant.root_resource_id
  path_part   = "games"
}

resource "aws_api_gateway_method" "get_games" {
  rest_api_id = aws_api_gateway_rest_api.gaming_assistant.id
  resource_id = aws_api_gateway_resource.games.id
  http_method = "GET"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "get_games" {
  rest_api_id = aws_api_gateway_rest_api.gaming_assistant.id
  resource_id = aws_api_gateway_resource.games.id
  http_method = aws_api_gateway_method.get_games.http_method
  integration_http_method = "POST"