$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Environnement Python absent. Consultez README.md.' }
& $python (Join-Path $root 'setup_local_db.py')
if ($LASTEXITCODE -ne 0) { throw 'Base locale indisponible. Le bot ne peut pas demarrer.' }
& (Join-Path $root 'backup-data.ps1')
& (Join-Path $root 'start-private.ps1')
