# Copies SERVER_APP_PASSWORD from .env into encrypted SSM Parameter Store, where the
# learnable-dev server reads it when starting TGTG Halal Finder. Prints nothing secret.
$ErrorActionPreference = "Stop"
$envFile = Join-Path $PSScriptRoot "..\.env"
$match = Select-String -Path $envFile -Pattern '^SERVER_APP_PASSWORD=(.+)$' | Select-Object -First 1
if (-not $match) { throw "SERVER_APP_PASSWORD not found in $envFile" }
$pw = $match.Matches[0].Groups[1].Value.Trim()
# Your `aws login` session lives in the "learnable" profile; AWS_PROFILE overrides it.
$awsProfile = if ($env:AWS_PROFILE) { $env:AWS_PROFILE } else { "learnable" }

aws ssm put-parameter --profile $awsProfile --region eu-west-1 --name /learnable/dev/tgtg-halal-password `
    --type SecureString --overwrite --value $pw --output text | Out-Null
if ($LASTEXITCODE -ne 0) { throw "aws ssm put-parameter failed" }
Write-Host "Password stored in SSM (/learnable/dev/tgtg-halal-password)."
