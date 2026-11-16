<#
  Mide el arranque REAL de Corte (instalado, app cerrada antes): corre CreatorHub.exe --medir N veces y resume.
  Literal de 04 §D.4 (el criterio de arranque de 04 §E se fija con esta medición tras el primer build real).
  Uso: powershell -ExecutionPolicy Bypass -File scripts\medir_arranque.ps1 [-Exe <ruta>] [-Corridas 5]
#>
param([string]$Exe = (Join-Path $env:LOCALAPPDATA 'Programs\CreatorHub\CreatorHub.exe'), [int]$Corridas = 5)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$informe = Join-Path $env:TEMP 'CreatorHub-medir\medicion.json'
$filas = foreach ($i in 1..$Corridas) {
    if (Test-Path $informe) { Remove-Item $informe -Force }
    $p = Start-Process -FilePath $Exe -ArgumentList '--medir' -PassThru
    $null = $p.Handle
    if (-not $p.WaitForExit(30000)) { $p.Kill(); throw 'La medición no terminó en 30 s' }
    $m = Get-Content $informe -Raw | ConvertFrom-Json
    [pscustomobject]@{ corrida = $i; hub_listo_ms = $m.t_hub_listo_ms; ventana_ms = $m.t_ventana_ms; pagina_ms = $m.t_pagina_ms }
}
$filas | Format-Table -AutoSize
$calientes = @($filas | Select-Object -Skip 1 | Sort-Object pagina_ms)
if ($calientes.Count -gt 0) { 'Mediana en caliente (sin la 1.ª): {0} ms hasta la página lista' -f $calientes[[int][math]::Floor(($calientes.Count - 1) / 2)].pagina_ms }
