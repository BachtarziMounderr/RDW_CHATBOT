$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$runtime = Join-Path $root '.runtime'
if (-not (Test-Path -LiteralPath $python)) { throw 'Environnement Python absent. Consultez README.md.' }
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$launchedAt = (Get-Date).ToUniversalTime()
$process = Start-Process -FilePath $python -ArgumentList @('-m','bot.main','run') `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $runtime 'stdout.log') `
    -RedirectStandardError (Join-Path $runtime 'stderr.log')
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 1
    $process.Refresh()
    if ($process.HasExited) { throw 'Le bot ne peut pas demarrer. Verifiez la configuration locale et les journaux dans .runtime.' }
    $ready = Join-Path $runtime 'ready.json'
    if (Test-Path -LiteralPath $ready) {
        $state = Get-Content -LiteralPath $ready -Raw | ConvertFrom-Json
        $connected = [datetimeoffset]::Parse($state.connected_at, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::RoundtripKind)
        if ($connected.UtcDateTime -ge $launchedAt) {
            Write-Output "Connexion Telegram verifiee. Comptes autorises : $($state.authorized_count). Processus : $($process.Id)."
            if ($state.dashboard_url) { Write-Output "Dashboard RDW local : $($state.dashboard_url)" }
            exit 0
        }
    }
}
Write-Output "Le processus est lance, mais la verification Telegram n'est pas encore confirmee. Consultez .runtime/ready.json."
