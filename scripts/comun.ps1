# Funciones comunes de los scripts de Creator Hub (Windows PowerShell 5.1). Uso: . (Join-Path $PSScriptRoot 'comun.ps1')
# Regla: NUNCA pasar comillas dobles dentro de un argumento a un programa nativo con & / Ejecutar (PS 5.1 no las escapa
# y el argumento se parte). Usar comillas simples dentro ("print('x')") o un archivo temporal.
Set-StrictMode -Version Latest
$script:Reloj = [Diagnostics.Stopwatch]::StartNew()
$script:NodeDir = 'D:\android-toolchain\node-v24.22.3-win-x64'
if (-not ($env:PATH -like "$script:NodeDir;*")) { $env:PATH = "$script:NodeDir;$env:PATH" }

function Paso([string]$t) { Write-Host ('[{0,6:N1} s] {1}' -f $script:Reloj.Elapsed.TotalSeconds, $t) -ForegroundColor Cyan }

# Corre un programa externo mostrando su salida; en 5.1 el stderr redirigido de un nativo se vuelve error, por eso
# ErrorActionPreference baja a Continue durante la llamada y el resultado se juzga por $LASTEXITCODE.
function Ejecutar([string]$exe, [string[]]$argumentos) {
    $previo = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { & $exe @argumentos 2>&1 | ForEach-Object { "$_" } } finally { $ErrorActionPreference = $previo }
    if ($LASTEXITCODE -ne 0) { throw "Falló ($LASTEXITCODE): $exe $($argumentos -join ' ')" }
}

# Igual, pero devuelve la salida estándar (sin stderr) en lugar de mostrarla.
function Capturar([string]$exe, [string[]]$argumentos) {
    $previo = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { $salida = & $exe @argumentos 2>$null } finally { $ErrorActionPreference = $previo }
    if ($LASTEXITCODE -ne 0) { throw "Falló ($LASTEXITCODE): $exe" }
    return $salida
}

function EscribirUtf8SinBom([string]$ruta, [string]$texto) {
    [IO.File]::WriteAllText($ruta, $texto, (New-Object Text.UTF8Encoding $false))
}

# node_modules al día con el lock: compara el SHA-256 de package-lock.json con la marca del último npm ci.
function AsegurarNodeModules([string]$carpetaUi) {
    $lock = Join-Path $carpetaUi 'package-lock.json'
    if (-not (Test-Path -LiteralPath $lock)) {
        throw "Falta $lock. Genéralo una vez con 'npm install' dentro de ui\ y guárdalo con el proyecto."
    }
    $hash = (Get-FileHash -LiteralPath $lock -Algorithm SHA256).Hash
    $marca = Join-Path $carpetaUi 'node_modules\.ch-lock.sha256'
    if ((Test-Path -LiteralPath $marca) -and ((Get-Content -LiteralPath $marca -Raw).Trim() -eq $hash)) {
        Write-Host 'node_modules al día con package-lock.json'
        return
    }
    Push-Location -LiteralPath $carpetaUi
    try { Ejecutar (Join-Path $script:NodeDir 'npm.cmd') @('ci', '--prefer-offline', '--no-audit', '--no-fund') }
    finally { Pop-Location }
    EscribirUtf8SinBom $marca $hash
}
