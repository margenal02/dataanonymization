$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker was not found. Install and start Docker Desktop, then run this script again.'
}

if (-not (Test-Path '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
    Write-Warning 'Created .env from the template. Change all secrets and database passwords before production use.'
}

docker compose up -d --build
if ($LASTEXITCODE -ne 0) { throw 'Containers failed to start. Run docker compose logs for details.' }

Write-Host ''
Write-Host 'Data anonymization service: http://localhost:5291' -ForegroundColor Green
Write-Host 'View logs: docker compose logs -f'
