$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $root 'stop-private.ps1')
$pgCtl = 'C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe'
$data = Join-Path $root '.runtime\postgres'
if (-not (Test-Path -LiteralPath (Join-Path $data 'PG_VERSION'))) { exit 0 }
& $pgCtl -D $data status *> $null
if ($LASTEXITCODE -eq 0) {
    & $pgCtl -D $data -m fast -w stop *> $null
    if ($LASTEXITCODE -ne 0) { throw 'La base RDW locale ne peut pas etre arretee.' }
    Write-Output 'Base RDW locale arretee.'
}
