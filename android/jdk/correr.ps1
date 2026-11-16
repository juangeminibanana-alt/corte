<#
  Prueba del Protocolo LAN 1 en el JDK 17 local (sin Gradle ni internet), portada de spec\pruebas\android_min\jdk.
  Compila android\app\src\main\java\app\creatorhub\red\ProtocoloLan.java -el mismo archivo del APK- junto con las
  pruebas de esta carpeta y corre VectoresEmparejamiento contra:
    spec\pruebas\protocolo_lan\vectores_emparejamiento.json   (Python: protocolo_lan.py)
    spec\verificacion\vectores_ch1.json                       (spec 03)
  Antes comprueba que ProtocoloLan.java es LITERAL respecto de spec\pruebas\android_min (solo cambia la línea package).
  Uso: powershell -NoProfile -ExecutionPolicy Bypass -File android\jdk\correr.ps1
  Sale con 0 solo si las 57 comprobaciones son idénticas a Python.
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Jdk    = 'D:\android-toolchain\jdk-17.0.19+10\bin'
$Aqui   = $PSScriptRoot
$Raiz   = (Resolve-Path (Join-Path $Aqui '..\..')).Path
$Spec   = Join-Path $Raiz 'spec'
$Fuente = Join-Path $Raiz 'android\app\src\main\java\app\creatorhub\red\ProtocoloLan.java'
$Ref    = Join-Path $Spec 'pruebas\android_min\app\src\main\java\app\creatorhub\prueba\ProtocoloLan.java'
$Clases = Join-Path $env:TEMP 'creatorhub-android-jdk'
$Esperadas = 57

function Ejecutar([string]$exe, [string[]]$argumentos) {
    $previo = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { $salida = & $exe @argumentos 2>&1 | ForEach-Object { "$_" } } finally { $ErrorActionPreference = $previo }
    $salida | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) { throw "Falló ($LASTEXITCODE): $exe" }
    return $salida
}

# 1) literal: idéntico a la referencia salvo la línea package
$a = [IO.File]::ReadAllText($Fuente, [Text.Encoding]::UTF8) -split "`n"
$b = [IO.File]::ReadAllText($Ref, [Text.Encoding]::UTF8) -split "`n"
if ($a.Count -ne $b.Count) { throw "ProtocoloLan.java no es literal: $($a.Count) líneas contra $($b.Count)" }
$distintas = @()
for ($i = 0; $i -lt $a.Count; $i++) { if ($a[$i] -ne $b[$i]) { $distintas += ($i + 1) } }
if ($distintas.Count -ne 1 -or $distintas[0] -ne 1 -or $a[0].TrimEnd() -ne 'package app.creatorhub.red;') {
    throw "ProtocoloLan.java no es literal: líneas distintas $($distintas -join ', ')"
}
Write-Host '[ok] ProtocoloLan.java = spec\pruebas\android_min (solo cambia la línea package)'

# 2) compilar y correr
if (Test-Path $Clases) { Remove-Item $Clases -Recurse -Force }
New-Item -ItemType Directory -Force $Clases | Out-Null
try {
    $fuentes = @($Fuente) + @(Get-ChildItem $Aqui -Filter *.java | ForEach-Object FullName)
    Ejecutar (Join-Path $Jdk 'javac.exe') (@('-encoding', 'UTF-8', '-Xlint:all', '-Werror', '-d', $Clases) + $fuentes) | Out-Null
    $salida = Ejecutar (Join-Path $Jdk 'java.exe') @('-Dfile.encoding=UTF-8', '-cp', $Clases, 'app.creatorhub.red.VectoresEmparejamiento',
        (Join-Path $Spec 'pruebas\protocolo_lan\vectores_emparejamiento.json'), (Join-Path $Spec 'verificacion\vectores_ch1.json'))
} finally {
    Remove-Item $Clases -Recurse -Force -ErrorAction SilentlyContinue
}
$linea = @($salida | Where-Object { $_ -match '^\[ok\] Java .*: \d+ comprobaciones' })
$m = if ($linea.Count -eq 1) { [regex]::Match($linea[0], ': (\d+) comprobaciones') } else { $null }
if ($null -eq $m -or -not $m.Success -or [int]$m.Groups[1].Value -ne $Esperadas) { throw "Se esperaban $Esperadas comprobaciones idénticas a Python" }
Write-Host "[ok] $Esperadas comprobaciones idénticas a Python"
exit 0
