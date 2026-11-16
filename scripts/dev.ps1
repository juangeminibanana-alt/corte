<#
  Desarrollo de Corte: levanta el hub DESDE EL CÓDIGO (modo demo, --dev, datos de research\datos-reales; BUILD_SPEC
  §6.7 y C31) y Vite en modo desarrollo, que reenvía /api, /img y /boot al hub (ui\vite.config.ts).
    Push-Location hub; ..\.venv-hub\Scripts\python.exe -m creatorhub --demo --dev --fuente fixtures_reales [--ahora <epoch>]
    Push-Location ui;  npm run dev
  Abre http://localhost:5173/boot/dev en el navegador: el hub pone la cookie de sesión (solo en --dev) y te lleva a la app.
  Ctrl+C detiene Vite; al salir, el script detiene el hub. Nada de esto sirve en el exe (--dev y fixtures_reales
  terminan con código 2 si sys.frozen).
  Uso: powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 [-Ahora 1794502800] [-Fuente fixtures_reales|sinteticos] [-SinVite] [-Depurar]
       -Ahora 1794502800 = jue 12 nov 2026, 11:00 a. m. de México (el reloj del recorrido de §11.4 a).
#>
[CmdletBinding()]
param([long]$Ahora = 0, [ValidateSet('fixtures_reales', 'sinteticos')][string]$Fuente = 'fixtures_reales',
      [switch]$SinVite, [switch]$Depurar, [int]$EsperaHubS = 60)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'comun.ps1')
. (Join-Path $PSScriptRoot 'comun_empaquetado.ps1')

$Raiz = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Hub  = Join-Path $Raiz 'hub'
$UI   = Join-Path $Raiz 'ui'
$Npm  = Join-Path $script:NodeDir 'npm.cmd'
$PuertoHub  = 39229          # C8: Vite reenvía siempre a 127.0.0.1:39229
$PuertoVite = 5173           # strictPort en vite.config.ts

if (-not (Test-Path (Join-Path $Raiz '.venv-hub\Scripts\python.exe'))) { throw 'Falta .venv-hub (corre scripts\preparar_entorno.ps1)' }
if (-not (Test-Path (Join-Path $Hub 'creatorhub\__main__.py'))) { throw 'Falta hub\creatorhub\__main__.py (lo entrega windows-shell)' }

function PuertoOcupado([int]$p) {
    $cliente = New-Object Net.Sockets.TcpClient
    try { $cliente.Connect('127.0.0.1', $p); return $true } catch { return $false } finally { $cliente.Dispose() }
}
if (PuertoOcupado $PuertoHub) { throw "El puerto $PuertoHub ya está en uso (¿otro Corte abierto?). Ciérralo: Vite solo reenvía a ese puerto." }
if (-not $SinVite) {
    if (PuertoOcupado $PuertoVite) { throw "El puerto $PuertoVite ya está en uso (¿otro vite dev?)." }
    NodeModulesAlDia $UI
}

$argumentos = @('-m', 'creatorhub', '--demo', '--dev', '--fuente', $Fuente)
if ($Ahora -gt 0) { $argumentos += @('--ahora', "$Ahora") }
if ($Depurar) { $argumentos += '--depurar' }
Paso "Hub desde el código: python $($argumentos -join ' ')"
Push-Location $Hub              # = Push-Location hub; ..\.venv-hub\Scripts\python.exe -m creatorhub … (sin -I: -m necesita hub\ en sys.path)
try {
    $proceso = Start-Process -FilePath (Join-Path $Raiz '.venv-hub\Scripts\python.exe') -ArgumentList $argumentos `
        -WorkingDirectory $Hub -NoNewWindow -PassThru
} finally { Pop-Location }
$null = $proceso.Handle

try {
    $listo = $false
    $cronometro = [Diagnostics.Stopwatch]::StartNew()      # (no $reloj: es el mismo nombre que $script:Reloj de Paso)
    while ($cronometro.Elapsed.TotalSeconds -lt $EsperaHubS) {
        if ($proceso.HasExited) { throw "El hub terminó antes de estar listo (código $($proceso.ExitCode))." }
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:$PuertoHub/api/health" -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200) { $listo = $true; break }
        } catch { Start-Sleep -Milliseconds 300 }
    }
    if (-not $listo) { throw "El hub no respondió /api/health en $EsperaHubS s." }
    Paso ("Hub listo en http://127.0.0.1:{0} ({1:N1} s)" -f $PuertoHub, $cronometro.Elapsed.TotalSeconds)

    if ($SinVite) {
        Paso 'Sin Vite: el hub sirve ui\dist. Ctrl+C para detenerlo.'
        $proceso.WaitForExit()
    } else {
        Paso "Vite: abre http://localhost:$PuertoVite/boot/dev   (Ctrl+C para terminar)"
        Push-Location $UI
        try { & $Npm run dev } finally { Pop-Location }
    }
} finally {
    if (-not $proceso.HasExited) {
        Paso 'Deteniendo el hub'
        Stop-Process -Id $proceso.Id -Force -ErrorAction SilentlyContinue
        $null = $proceso.WaitForExit(10000)
    }
}
