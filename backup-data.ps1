$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$envPath = Join-Path $root '.env'
$pgDump = 'C:\Program Files\PostgreSQL\18\bin\pg_dump.exe'
if (-not (Test-Path -LiteralPath $pgDump)) { throw 'pg_dump PostgreSQL 18 est introuvable.' }
$databaseLine = Get-Content -LiteralPath $envPath | Where-Object { $_ -match '^DATABASE_URL=' } | Select-Object -First 1
if (-not $databaseLine) { throw 'DATABASE_URL absente.' }
$databaseUrl = ($databaseLine -split '=', 2)[1].Trim()
$uri = [Uri]$databaseUrl
$credentials = $uri.UserInfo -split ':', 2
if ($credentials.Count -ne 2) { throw 'DATABASE_URL locale invalide.' }
$databaseUser = [Uri]::UnescapeDataString($credentials[0])
$databasePassword = [Uri]::UnescapeDataString($credentials[1])
$databaseName = $uri.AbsolutePath.TrimStart('/')
$backupDir = Join-Path $root 'backups'
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss')
$destination = Join-Path $backupDir ("rdw_bot-$stamp.dump")
$previousPassword = $env:PGPASSWORD
try {
    $env:PGPASSWORD = $databasePassword
    & $pgDump -h $uri.Host -p $uri.Port -U $databaseUser -d $databaseName -Fc -f $destination
    if ($LASTEXITCODE -ne 0) { throw 'La sauvegarde PostgreSQL a échoué.' }
} finally {
    $env:PGPASSWORD = $previousPassword
}
$size = (Get-Item -LiteralPath $destination).Length
if ($size -lt 100) { throw 'La sauvegarde créée est anormalement petite.' }
Write-Output "Sauvegarde locale créée : backups\$(Split-Path -Leaf $destination)"
