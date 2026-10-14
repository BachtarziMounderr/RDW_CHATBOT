$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $root 'stop-assistant.ps1')
if (Test-Path -LiteralPath (Join-Path $root '.runtime\bot.pid')) {
    throw 'Ancienne instance encore active ; aucun nouveau bot lancé.'
}
& (Join-Path $root 'start-assistant.ps1')
