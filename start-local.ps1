$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtimeDirectory = Join-Path $projectRoot '.runtime'
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$backendDirectory = Join-Path $projectRoot 'backend'
$frontendDirectory = Join-Path $projectRoot 'frontend'

Set-Location $projectRoot

$publicPort = 5291
$backendPort = 8529
$occupiedPorts = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in @($publicPort, $backendPort) }
if ($occupiedPorts) {
    $ports = ($occupiedPorts.LocalPort | Sort-Object -Unique) -join ', '
    throw "Required port is already in use: $ports. Run .\stop-local.ps1 first."
}

if (-not (Test-Path -LiteralPath $pythonPath)) {
    $pythonCommand = Get-Command python -ErrorAction Stop
    & $pythonCommand.Source -m venv (Join-Path $projectRoot '.venv')
    & $pythonPath -m pip install -r (Join-Path $backendDirectory 'requirements.txt')
}

$npmCommand = Get-Command npm.cmd -ErrorAction Stop
if (-not (Test-Path -LiteralPath (Join-Path $frontendDirectory 'node_modules'))) {
    Push-Location $frontendDirectory
    try { & $npmCommand.Source ci } finally { Pop-Location }
}

& $pythonPath (Join-Path $backendDirectory 'manage.py') migrate --noinput
if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }

New-Item -ItemType Directory -Force -Path $runtimeDirectory | Out-Null
$backendLog = Join-Path $runtimeDirectory 'backend.log'
$backendErrorLog = Join-Path $runtimeDirectory 'backend-error.log'
$frontendLog = Join-Path $runtimeDirectory 'frontend.log'
$frontendErrorLog = Join-Path $runtimeDirectory 'frontend-error.log'

$env:DJANGO_DEBUG = '1'
$backend = Start-Process -FilePath $pythonPath `
    -ArgumentList @('manage.py', 'runserver', "127.0.0.1:$backendPort", '--noreload') `
    -WorkingDirectory $backendDirectory -WindowStyle Hidden `
    -RedirectStandardOutput $backendLog -RedirectStandardError $backendErrorLog -PassThru

$env:LOCAL_BACKEND_URL = "http://127.0.0.1:$backendPort"
$frontend = Start-Process -FilePath $npmCommand.Source `
    -ArgumentList @('run', 'dev', '--', '--host', '0.0.0.0', '--port', "$publicPort", '--strictPort') `
    -WorkingDirectory $frontendDirectory -WindowStyle Hidden `
    -RedirectStandardOutput $frontendLog -RedirectStandardError $frontendErrorLog -PassThru

Set-Content -LiteralPath (Join-Path $runtimeDirectory 'backend.pid') -Value $backend.Id -Encoding ascii
Set-Content -LiteralPath (Join-Path $runtimeDirectory 'frontend.pid') -Value $frontend.Id -Encoding ascii

Write-Host ''
Write-Host "Data anonymization service: http://localhost:$publicPort" -ForegroundColor Green
Write-Host 'Local mode uses SQLite. Run .\stop-local.ps1 to stop it.'

