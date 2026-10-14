param(
    [Parameter(Mandatory = $true)]
    [string]$BackupPath
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pgRestore = 'C:\Program Files\PostgreSQL\18\bin\pg_restore.exe'
$psql = 'C:\Program Files\PostgreSQL\18\bin\psql.exe'

if (-not (Test-Path -LiteralPath $pgRestore)) { throw 'pg_restore PostgreSQL 18 est introuvable.' }
if (-not (Test-Path -LiteralPath $psql)) { throw 'psql PostgreSQL 18 est introuvable.' }

$resolvedBackup = (Resolve-Path -LiteralPath $BackupPath).Path
$allowedRoot = [IO.Path]::GetFullPath((Join-Path $root 'backups'))
if (-not $resolvedBackup.StartsWith($allowedRoot + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase)) {
    throw 'La sauvegarde doit se trouver dans telegram-bot\backups.'
}
if ([IO.Path]::GetExtension($resolvedBackup) -ne '.dump') { throw 'Le fichier doit avoir l’extension .dump.' }

Write-Output 'Dans Neon, ouvrez Connect, désactivez Pooled connection et copiez la chaîne directe.'
$secureUrl = Read-Host 'Collez la chaîne PostgreSQL Neon directe (saisie masquée)' -AsSecureString
$pointer = [IntPtr]::Zero
$targetUrl = $null
$savedEnvironment = @{}
foreach ($name in @('PGHOST','PGPORT','PGUSER','PGPASSWORD','PGDATABASE','PGSSLMODE')) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureUrl)
    $targetUrl = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    $target = [Uri]$targetUrl
    if ($target.Scheme -notin @('postgres', 'postgresql')) { throw 'Chaîne PostgreSQL Neon invalide.' }
    if (-not $target.Host.EndsWith('.neon.tech', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'La cible doit être une base Neon distante.'
    }
    if ($target.Host -match '-pooler\.') {
        throw 'Utilisez la chaîne directe, sans -pooler, pour la restauration.'
    }
    $userInfo = $target.UserInfo.Split(':', 2)
    if ($userInfo.Count -ne 2) { throw 'Utilisateur ou mot de passe absent de la chaîne Neon.' }
    $database = [Uri]::UnescapeDataString($target.AbsolutePath.TrimStart('/'))
    if (-not $database) { throw 'Nom de base absent de la chaîne Neon.' }

    $env:PGHOST = $target.Host
    $env:PGPORT = if ($target.Port -gt 0) { [string]$target.Port } else { '5432' }
    $env:PGUSER = [Uri]::UnescapeDataString($userInfo[0])
    $env:PGPASSWORD = [Uri]::UnescapeDataString($userInfo[1])
    $env:PGDATABASE = $database
    $env:PGSSLMODE = 'require'

    & $pgRestore --no-owner --no-privileges --single-transaction --exit-on-error $resolvedBackup
    if ($LASTEXITCODE -ne 0) {
        throw 'Restauration refusée. La transaction a été annulée ; vérifiez que le schéma telegram est absent de Neon.'
    }

    & $psql -v ON_ERROR_STOP=1 -c "SELECT count(*) AS fiches_consenties FROM telegram.prospects WHERE consent_at IS NOT NULL;"
    if ($LASTEXITCODE -ne 0) { throw 'Restauration terminée, mais la vérification SQL a échoué.' }
    Write-Output 'Restauration Neon terminée et schéma Telegram vérifié.'
} finally {
    foreach ($name in $savedEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process')
    }
    if ($pointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
    $targetUrl = $null
    $secureUrl = $null
}
