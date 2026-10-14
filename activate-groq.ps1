$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$envPath = Join-Path $root '.env'
$python = Join-Path $root '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python)) { throw 'Environnement Python absent. Consultez README.md.' }
$lines = [System.Collections.Generic.List[string]](Get-Content -LiteralPath $envPath)
$values = @{}
foreach ($line in $lines) {
    if ($line -match '^([^#=]+)=(.*)$') { $values[$matches[1].Trim()] = $matches[2].Trim() }
}
if (-not $values.ContainsKey('GROQ_API_KEY') -or [string]::IsNullOrWhiteSpace($values['GROQ_API_KEY'])) {
    throw 'GROQ_API_KEY est vide. Collez la clé directement dans telegram-bot\.env, sans guillemets.'
}

function Set-EnvValue([string]$name, [string]$value) {
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match ('^' + [regex]::Escape($name) + '=')) {
            $lines[$i] = "$name=$value"
            return
        }
    }
    $lines.Add("$name=$value")
}

Set-EnvValue 'AI_PROVIDER' 'groq'
Set-EnvValue 'GROQ_MODEL' 'qwen/qwen3.8-27b'
Set-EnvValue 'AI_ENABLED' 'true'
[System.IO.File]::WriteAllLines($envPath, $lines, [System.Text.UTF8Encoding]::new($false))

Push-Location $root
try {
    & $python -m bot.main check-ai
    if ($LASTEXITCODE -ne 0) {
        Set-EnvValue 'AI_ENABLED' 'false'
        [System.IO.File]::WriteAllLines($envPath, $lines, [System.Text.UTF8Encoding]::new($false))
        throw 'Le contrôle Groq a échoué. Le bot actuel reste en mode documentaire.'
    }
    & (Join-Path $root 'restart-assistant.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Groq a répondu, mais le redémarrage Telegram a échoué.' }
} finally {
    Pop-Location
}
