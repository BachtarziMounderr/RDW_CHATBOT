$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtime = Join-Path $root '.runtime'
$pidFile = Join-Path $runtime 'bot.pid'
if (-not (Test-Path -LiteralPath $pidFile)) {
    Write-Output 'Aucune instance locale connue.'
    exit 0
}
Set-Content -LiteralPath (Join-Path $runtime 'stop.request') -Value 'stop' -Encoding ascii
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 1
    if (-not (Test-Path -LiteralPath $pidFile)) {
        Write-Output 'Bot arrete.'
        exit 0
    }
}
try {
    $recordedPid = [int](Get-Content -LiteralPath $pidFile -Raw)
    $alive = Get-Process -Id $recordedPid -ErrorAction SilentlyContinue
    if (-not $alive) {
        Remove-Item -LiteralPath $pidFile -Force
        Remove-Item -LiteralPath (Join-Path $runtime 'stop.request') -Force -ErrorAction SilentlyContinue
        Write-Output 'Bot arrete ; fichier PID obsolète nettoyé.'
        exit 0
    }
} catch {
    throw 'Le fichier PID est illisible ; arrêt manuel requis avant tout redémarrage.'
}
Write-Output 'Arret demande. Verifiez .runtime/bot.pid dans quelques secondes.'
