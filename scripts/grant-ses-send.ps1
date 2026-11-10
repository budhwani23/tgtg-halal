# Lets the server's EC2 instance role send sign-in code emails through Amazon SES, and
# only from the verified sender address. Adds one inline policy to the role.
#
#   pwsh scripts/grant-ses-send.ps1 -Sender you@example.com [-Role my-ec2-role] [-Region eu-west-1]
#
# Uses the "learnable" AWS CLI profile unless AWS_PROFILE is set.
param(
    [string]$Sender = $env:MAIL_FROM,
    [string]$Role = "learnable-dev-ec2",
    [string]$Region = "eu-west-1"
)
$ErrorActionPreference = "Stop"
if (-not $Sender) { throw "Pass -Sender (the SES-verified From address) or set MAIL_FROM." }
$awsProfile = if ($env:AWS_PROFILE) { $env:AWS_PROFILE } else { "learnable" }

$account = aws sts get-caller-identity --profile $awsProfile --query Account --output text
if ($LASTEXITCODE -ne 0) { throw "Couldn't read the AWS account (are you signed in? try: aws login --profile $awsProfile)" }

$policy = @{
    Version   = "2012-10-17"
    Statement = @(@{
        Sid       = "TgtgHalalSignInCodes"
        Effect    = "Allow"
        Action    = "ses:SendEmail"
        Resource  = "arn:aws:ses:${Region}:${account}:identity/*"
        Condition = @{ StringEquals = @{ "ses:FromAddress" = $Sender } }
    })
} | ConvertTo-Json -Depth 6 -Compress

$file = New-TemporaryFile
Set-Content -Path $file -Value $policy -NoNewline -Encoding ascii
aws iam put-role-policy --profile $awsProfile --role-name $Role `
    --policy-name tgtg-halal-ses-send --policy-document "file://$file"
$code = $LASTEXITCODE
Remove-Item $file
if ($code -ne 0) { throw "aws iam put-role-policy failed" }
Write-Host "Done: $Role can now send email from $Sender via SES."
