<#
  Verificación global de Corte: la secuencia EXACTA de BUILD_SPEC §11.1, en este orden:
     1. unittest del hub completo
     2. tsc del contrato con los 44 ejemplos (34 reales de ejemplos.check.ts + 10 de UX de ejemplos_ux.check.ts)
     3. fixtures.check.ts (ui\fixtures\verificar, contra spec\contrato.ts)
     4. npm run firmas
     5. npm run iconos
     6. npm run typecheck
     7. npm test
     8. npm run build (con verificar_dist)
     9. spec\verificacion\v06_cifras_ux.py «TODO OK»
    10. android\jdk\correr.ps1
    11. android\pruebas_tls\correr_conscrypt.ps1
  Antes (salvo -SinPreparar) deja ui\node_modules al día con el lock (NodeModulesAlDia: adopta la marca si node_modules
  ya coincide con el lock y si no, AsegurarNodeModules hace npm ci, que borra node_modules: ojo en el árbol compartido).
  Corre todos los pasos aunque uno falle (salvo -Detener), guarda la salida de cada uno en build\verificar\paso-NN.log y
  al final imprime la tabla. Sale con 0 solo si pasan todos los pasos pedidos.
  Uso: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verificar_todo.ps1 [-Pasos 1-7,9] [-SinPreparar] [-Detener] [-Listar]
       Sin -Pasos corre los 11. -Pasos solo elige cuáles; el orden siempre es el de §11.1. -Listar los muestra sin correrlos.
#>
[CmdletBinding()]
param([string[]]$Pasos = @('1-11'), [switch]$SinPreparar, [switch]$Detener, [switch]$Listar)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'comun.ps1')
. (Join-Path $PSScriptRoot 'comun_empaquetado.ps1')

$Raiz    = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Py      = Join-Path $Raiz '.venv-hub\Scripts\python.exe'
$Node    = Join-Path $script:NodeDir 'node.exe'
$Npm     = Join-Path $script:NodeDir 'npm.cmd'
$UI      = Join-Path $Raiz 'ui'
$Tsc     = Join-Path $UI 'node_modules\typescript\bin\tsc'
$PS      = Join-Path ([Environment]::SystemDirectory) 'WindowsPowerShell\v1.0\powershell.exe'
$Logs    = Join-Path $Raiz 'build\verificar'
$Spec    = Join-Path $Raiz 'spec'
$Ejemplos   = Join-Path $Spec 'verificacion\ejemplos\ejemplos.check.ts'
$EjemplosUx = Join-Path $Spec 'verificacion\ejemplos_ux\ejemplos_ux.check.ts'
$Fixtures   = Join-Path $UI 'fixtures\verificar\fixtures.check.ts'
$TscComun   = @('--strict', '--exactOptionalPropertyTypes', '--noEmit', '--target', 'es2022', '--module', 'esnext', '--moduleResolution', 'bundler')

# -Pasos llega como «1,2,3» (una sola cadena con powershell -File) o como arreglo; también acepta rangos «1-7».
$lista = New-Object System.Collections.Generic.List[int]
foreach ($pieza in @($Pasos | ForEach-Object { "$_" -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })) {
    if ($pieza -match '^(\d+)-(\d+)$') { foreach ($k in [int]$Matches[1]..[int]$Matches[2]) { $lista.Add($k) } }
    elseif ($pieza -match '^\d+$') { $lista.Add([int]$pieza) }
    else { throw "Paso inválido: '$pieza' (usa números del 1 al 11, separados por comas, o un rango como 1-7)" }
}
[int[]]$Elegidos = @($lista | Select-Object -Unique)          # variable aparte: $Pasos conserva su tipo [string[]]
foreach ($n in $Elegidos) { if ($n -lt 1 -or $n -gt 11) { throw "Paso inválido: $n (van del 1 al 11)" } }
foreach ($r in @($Py, $Node, $Npm)) { if (-not (Test-Path -LiteralPath $r)) { throw "No existe $r" } }
New-Item -ItemType Directory -Force $Logs | Out-Null

# Corre un programa nativo en $dir mostrando su salida y guardándola en el log; devuelve @{codigo; salida}.
function Correr([string]$exe, [string[]]$argumentos, [string]$dir, [string]$log) {
    $lineas = New-Object System.Collections.Generic.List[string]
    $lineas.Add(">> $exe $($argumentos -join ' ')   (en $dir)")
    $previo = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    Push-Location -LiteralPath $dir
    try { & $exe @argumentos 2>&1 | ForEach-Object { $l = TextoDeSalida $_; $lineas.Add($l); Write-Host $l } }
    finally { Pop-Location; $ErrorActionPreference = $previo }
    $codigo = $LASTEXITCODE
    [IO.File]::AppendAllText($log, (($lineas -join "`r`n") + "`r`n"), (New-Object Text.UTF8Encoding $false))
    return @{ codigo = $codigo; salida = $lineas }
}
function ContarExports([string]$archivo) { @(Select-String -LiteralPath $archivo -Pattern '^export const ').Count }

# Cada paso devuelve '' si pasó o el motivo de la falla.
$definicion = @(
    @{ n = 1;  nombre = 'unittest del hub completo'; accion = {
            param($log)
            $r = Correr $Py @('-I', '-m', 'unittest', 'discover', '-s', 'hub\pruebas', '-t', 'hub', '-v') $Raiz $log
            if ($r.codigo -ne 0) { "unittest salió con $($r.codigo)" } else { '' } } },
    @{ n = 2;  nombre = 'tsc del contrato con los 44 ejemplos'; accion = {
            param($log)
            $n1 = ContarExports $Ejemplos; $n2 = ContarExports $EjemplosUx
            if ($n1 -ne 34 -or $n2 -ne 10) { return "se esperaban 34 + 10 ejemplos y hay $n1 + $n2" }
            $a = Correr $Node (@($Tsc) + $TscComun + @('--noUncheckedIndexedAccess', (Join-Path $Spec 'contrato.ts'), $Ejemplos)) $Raiz $log
            $b = Correr $Node (@($Tsc) + $TscComun + @((Join-Path $Spec 'contrato.ts'), $EjemplosUx)) $Raiz $log
            if ($a.codigo -ne 0 -or $b.codigo -ne 0) { "tsc salió con $($a.codigo) (34 reales) y $($b.codigo) (10 de UX)" } else { '' } } },
    @{ n = 3;  nombre = 'fixtures.check.ts'; accion = {
            param($log)
            if (-not (Test-Path -LiteralPath $Fixtures)) { return "falta $Fixtures" }
            $r = Correr $Node (@('--max-old-space-size=8192', $Tsc) + $TscComun + @('--noUncheckedIndexedAccess', $Fixtures)) $Raiz $log
            if ($r.codigo -ne 0) { "tsc salió con $($r.codigo)" } else { '' } } },
    @{ n = 4;  nombre = 'npm run firmas'; accion = {
            param($log); $r = Correr $Npm @('run', 'firmas') $UI $log; if ($r.codigo -ne 0) { "salió con $($r.codigo)" } else { '' } } },
    @{ n = 5;  nombre = 'npm run iconos'; accion = {
            param($log); $r = Correr $Npm @('run', 'iconos') $UI $log; if ($r.codigo -ne 0) { "salió con $($r.codigo)" } else { '' } } },
    @{ n = 6;  nombre = 'npm run typecheck'; accion = {
            param($log); $r = Correr $Npm @('run', 'typecheck') $UI $log; if ($r.codigo -ne 0) { "salió con $($r.codigo)" } else { '' } } },
    @{ n = 7;  nombre = 'npm test'; accion = {
            param($log); $r = Correr $Npm @('test') $UI $log; if ($r.codigo -ne 0) { "salió con $($r.codigo)" } else { '' } } },
    @{ n = 8;  nombre = 'npm run build (con verificar_dist)'; accion = {
            param($log); $r = Correr $Npm @('run', 'build') $UI $log; if ($r.codigo -ne 0) { "salió con $($r.codigo)" } else { '' } } },
    @{ n = 9;  nombre = 'v06_cifras_ux.py «TODO OK»'; accion = {
            param($log)
            $r = Correr $Py @('-I', '-B', (Join-Path $Spec 'verificacion\v06_cifras_ux.py')) $Raiz $log
            if ($r.codigo -ne 0) { "salió con $($r.codigo)" }
            elseif (-not ($r.salida | Where-Object { $_.Trim() -eq 'TODO OK' })) { 'no imprimió «TODO OK»' } else { '' } } },
    @{ n = 10; nombre = 'android\jdk\correr.ps1'; accion = {
            param($log)
            $r = Correr $PS @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $Raiz 'android\jdk\correr.ps1')) $Raiz $log
            if ($r.codigo -ne 0) { "salió con $($r.codigo)" } else { '' } } },
    @{ n = 11; nombre = 'android\pruebas_tls\correr_conscrypt.ps1'; accion = {
            param($log)
            $r = Correr $PS @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $Raiz 'android\pruebas_tls\correr_conscrypt.ps1')) $Raiz $log
            switch ($r.codigo) {
                0 { '' }
                1 { 'Conscrypt/TLS FALLA: activar el plan B de 04 §F.6 (código 1)' }
                2 { 'Conscrypt OK pero la prueba web o un extra falló (código 2)' }
                3 { 'no se pudo correr: emulador, servidor o build (código 3)' }
                default { "salió con $($r.codigo)" }
            } } }
)

if ($Listar) {
    $definicion | Where-Object { $Elegidos -contains $_.n } | ForEach-Object { '{0,2}. {1}' -f $_.n, $_.nombre }
    exit 0
}

if (-not $SinPreparar) {
    Paso 'Preparación: ui\node_modules al día con package-lock.json'
    NodeModulesAlDia $UI
}

$tabla = New-Object System.Collections.Generic.List[object]
foreach ($d in ($definicion | Where-Object { $Elegidos -contains $_.n })) {         # siempre en el orden de §11.1
    $n = $d.n
    $log = Join-Path $Logs ('paso-{0:D2}.log' -f $n)
    if (Test-Path -LiteralPath $log) { Remove-Item -LiteralPath $log -Force }
    Paso ("Paso {0}/11 · {1}" -f $n, $d.nombre)
    $cronometro = [Diagnostics.Stopwatch]::StartNew()      # (no $reloj: es el mismo nombre que $script:Reloj de Paso)
    try { $motivo = [string](& $d.accion $log) } catch { $motivo = "error: $($_.Exception.Message)" }
    $segundos = [math]::Round($cronometro.Elapsed.TotalSeconds, 1)
    $tabla.Add([pscustomobject]@{ Paso = $n; Verificacion = $d.nombre; Resultado = $(if ($motivo) { 'FALLA' } else { 'OK' }); Segundos = $segundos; Detalle = $motivo })
    if ($motivo) { Write-Host "Paso $n FALLA: $motivo (log: $log)" -ForegroundColor Red } else { Write-Host "Paso $n OK ($segundos s)" -ForegroundColor Green }
    if ($motivo -and $Detener) { break }
}

Write-Host ''
$tabla | Format-Table -AutoSize -Wrap | Out-String -Width 200 | Write-Host
$fallas = @($tabla | Where-Object { $_.Resultado -ne 'OK' }).Count
$hechos = @($tabla | ForEach-Object { $_.Paso })
$faltan = @($Elegidos | Select-Object -Unique | Where-Object { $hechos -notcontains $_ }).Count
if ($fallas -gt 0 -or $faltan -gt 0) {
    Write-Host ("verificar_todo: FALLA · {0} de {1} pasos con falla{2} · logs en {3}" -f $fallas, $Elegidos.Count, $(if ($faltan) { ", $faltan sin correr" } else { '' }), $Logs) -ForegroundColor Red
    exit 1
}
Write-Host ("verificar_todo: OK · {0} pasos de BUILD_SPEC §11.1 en verde · logs en {1}" -f $tabla.Count, $Logs) -ForegroundColor Green
exit 0
