<#
  Desinstala Corte instalado con Instalar.ps1. Conserva los datos (%LOCALAPPDATA%\CreatorHub): "Borrar todo"
  está dentro de la app. Se copia a %TEMP% y se relanza desde ahí para poder borrar su propia carpeta.
#>
param([string]$Clave = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CreatorHub', [switch]$DesdeTemp, [switch]$Silencioso)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $env:TEMP                       # nunca dentro de la carpeta que se va a borrar
$ps = Join-Path ([Environment]::SystemDirectory) 'WindowsPowerShell\v1.0\powershell.exe'

if (-not $DesdeTemp) {
    $copia = Join-Path $env:TEMP ('CreatorHub-desinstalar-' + [guid]::NewGuid().ToString('N') + '.ps1')
    Copy-Item -LiteralPath $PSCommandPath -Destination $copia
    $extra = if ($Silencioso) { ' -Silencioso' } else { '' }
    $p = Start-Process -FilePath $ps -PassThru -WindowStyle Hidden -ArgumentList ("-NoProfile -ExecutionPolicy Bypass -File `"$copia`" -Clave `"$Clave`" -DesdeTemp$extra")
    $null = $p.Handle
    $p.WaitForExit()
    exit $p.ExitCode
}

$codigo = 0
try {
    $datos = Get-ItemProperty -LiteralPath $Clave
    $destino = [string]$datos.InstallLocation
    $exe = Join-Path $destino 'CreatorHub.exe'
    # Guardia: solo una carpeta 'CreatorHub' dentro de %LOCALAPPDATA% que contenga CreatorHub.exe
    if (-not $destino -or (Split-Path $destino -Leaf) -ne 'CreatorHub' -or
        -not $destino.StartsWith($env:LOCALAPPDATA + '\', [StringComparison]::OrdinalIgnoreCase) -or
        -not (Test-Path -LiteralPath $exe)) {
        throw "La entrada de desinstalación apunta a '$destino', que no parece una instalación de Corte."
    }
    $s = Start-Process -FilePath $exe -ArgumentList '--desinstalar' -PassThru -WindowStyle Hidden   # cierra la app y quita el inicio con Windows
    if (-not $s.WaitForExit(20000)) { try { $s.Kill() } catch { } }
    Get-Process -Name 'CreatorHub' -ErrorAction SilentlyContinue | Where-Object { $_.Path -and ($_.Path -ieq $exe) } |
        ForEach-Object { [void]$_.WaitForExit(10000) }
    for ($intento = 1; ; $intento++) {
        try { Remove-Item -LiteralPath $destino -Recurse -Force -ErrorAction Stop; break }
        catch { if ($intento -ge 5) { throw }; Start-Sleep -Seconds 1 }
    }
    if ($datos.PSObject.Properties['Accesos']) {
        foreach ($lnk in @($datos.Accesos)) { if ($lnk -and (Test-Path -LiteralPath $lnk)) { Remove-Item -LiteralPath $lnk -Force } }
    }
    Remove-Item -LiteralPath $Clave -Recurse -Force          # al final: nunca queda carpeta huérfana sin entrada en Ajustes
} catch {
    $codigo = 1
    $mensaje = "No se pudo desinstalar Corte por completo: $($_.Exception.Message)"
    Add-Content -LiteralPath (Join-Path $env:TEMP 'CreatorHub-desinstalar.log') -Value ("{0:s} {1}" -f (Get-Date), $mensaje)
    if (-not $Silencioso) {
        Add-Type -AssemblyName System.Windows.Forms
        [void][System.Windows.Forms.MessageBox]::Show($mensaje, 'Corte')
    }
} finally {
    Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
}
exit $codigo
