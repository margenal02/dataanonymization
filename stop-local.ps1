$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtimeDirectory = Join-Path $projectRoot '.runtime'

foreach ($port in @(5291, 8529)) {
    $listeners = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    foreach ($listener in $listeners) {
        $process = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
        if ($process) {
            Write-Host "Stopping $($process.ProcessName) on port $port"
            Stop-Process -Id $process.Id -Force
        }
    }
}

if (Test-Path -LiteralPath $runtimeDirectory) {
    Get-ChildItem -LiteralPath $runtimeDirectory -Filter '*.pid' -File | ForEach-Object {
        $processId = [int](Get-Content -LiteralPath $_.FullName -Raw)
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($process) { Stop-Process -Id $process.Id -Force }
    }
}

Write-Host 'Local service stopped.'

