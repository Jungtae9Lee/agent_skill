$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$url = "http://127.0.0.1:8765"

function Test-InstallerRunning {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $wait = $client.BeginConnect("127.0.0.1", 8765, $null, $null)
        $connected = $wait.AsyncWaitHandle.WaitOne(400, $false)
        if (-not $connected) {
            return $false
        }
        $client.EndConnect($wait)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

if (Test-InstallerRunning) {
    Start-Process $url
    exit 0
}

if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 -u (Join-Path $root "site\server.py")
    exit $LASTEXITCODE
}

if (Get-Command python -ErrorAction SilentlyContinue) {
    & python -u (Join-Path $root "site\server.py")
    exit $LASTEXITCODE
}

Write-Host "Python 3 was not found. Install Python, then double-click the launcher again."
exit 1
