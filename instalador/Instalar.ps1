<#
  Instala o actualiza Corte por usuario, sin administrador (camino zip, cuando no hay Inno Setup).
  Uso: doble clic en "Instalar Corte.cmd". Los parámetros solo se cambian en pruebas.
#>
param(
    [string]$Destino = (Join-Path $env:LOCALAPPDATA 'Programs\CreatorHub'),
    [string]$ClaveDesinstalar = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CreatorHub',
    [string[]]$CarpetasAccesos = @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop')),
    [switch]$SinAbrir
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$origen = Join-Path $PSScriptRoot 'CreatorHub'
$exe    = Join-Path $Destino 'CreatorHub.exe'
if (-not (Test-Path -LiteralPath (Join-Path $origen 'CreatorHub.exe'))) { throw "No encuentro $origen\CreatorHub.exe. Descomprime todo el zip." }

function DetenerCreatorHub([string]$rutaExe) {
    if (-not (Test-Path -LiteralPath $rutaExe)) { return }
    # --salir espera (hasta 15 s) a que la app suelte su mutex; después se espera a que el proceso termine de verdad.
    $p = Start-Process -FilePath $rutaExe -ArgumentList '--salir' -PassThru -WindowStyle Hidden
    if (-not $p.WaitForExit(20000)) { try { $p.Kill() } catch { } }
    Get-Process -Name 'CreatorHub' -ErrorAction SilentlyContinue | Where-Object { $_.Path -and ($_.Path -ieq $rutaExe) } |
        ForEach-Object { if (-not $_.WaitForExit(10000)) { throw 'Corte sigue abierto. Ciérralo desde la bandeja y vuelve a intentar.' } }
}

DetenerCreatorHub $exe
# /R:5 /W:1: si algo siguiera bloqueado falla en ~5 s (por defecto reintenta 1,000,000 de veces cada 30 s)
& robocopy $origen $Destino /MIR /R:5 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "No se pudieron copiar los archivos (robocopy $LASTEXITCODE)." }

# Accesos directos con el MISMO AppUserModelID que fija el proceso (WScript.Shell no puede ponerlo)
if (-not ('CreatorHubAccesos' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class CreatorHubAccesos {
    [ComImport, Guid("00021401-0000-0000-C000-000000000046")] class ShellLink { }
    [ComImport, Guid("0000010b-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IPersistFile {
        void GetClassID(out Guid c);
        [PreserveSig] int IsDirty();
        void Load([MarshalAs(UnmanagedType.LPWStr)] string archivo, uint modo);
        void Save([MarshalAs(UnmanagedType.LPWStr)] string archivo, [MarshalAs(UnmanagedType.Bool)] bool recordar);
        void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string archivo);
        void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string archivo);
    }
    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IPropertyStore {
        void GetCount(out uint n);
        void GetAt(uint i, out ClavePropiedad k);
        void GetValue(ref ClavePropiedad k, out PropVariant v);
        void SetValue(ref ClavePropiedad k, ref PropVariant v);
        void Commit();
    }
    [StructLayout(LayoutKind.Sequential, Pack = 4)] public struct ClavePropiedad { public Guid fmtid; public uint pid; }
    [StructLayout(LayoutKind.Explicit, Size = 24)] public struct PropVariant { [FieldOffset(0)] public ushort vt; [FieldOffset(8)] public IntPtr p; }
    [DllImport("ole32.dll")] static extern int PropVariantClear(ref PropVariant pv);
    static ClavePropiedad Aumid() { return new ClavePropiedad { fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 5 }; }

    public static void FijarAumid(string lnk, string aumid) {
        object link = new ShellLink();
        try {
            ((IPersistFile)link).Load(lnk, 2);                       // STGM_READWRITE
            ClavePropiedad k = Aumid();
            PropVariant v = new PropVariant { vt = 31, p = Marshal.StringToCoTaskMemUni(aumid) };   // VT_LPWSTR
            try { ((IPropertyStore)link).SetValue(ref k, ref v); ((IPropertyStore)link).Commit(); }
            finally { PropVariantClear(ref v); }
            ((IPersistFile)link).Save(lnk, true);
        } finally { Marshal.FinalReleaseComObject(link); }
    }

    public static string LeerAumid(string lnk) {
        object link = new ShellLink();
        try {
            ((IPersistFile)link).Load(lnk, 0);
            ClavePropiedad k = Aumid(); PropVariant v;
            ((IPropertyStore)link).GetValue(ref k, out v);
            try { return v.vt == 31 ? Marshal.PtrToStringUni(v.p) : null; } finally { PropVariantClear(ref v); }
        } finally { Marshal.FinalReleaseComObject(link); }
    }
}
'@
}
$shell = New-Object -ComObject WScript.Shell
$accesos = @()
foreach ($carpeta in $CarpetasAccesos) {
    $lnk = Join-Path $carpeta 'Corte.lnk'
    $a = $shell.CreateShortcut($lnk); $a.TargetPath = $exe; $a.WorkingDirectory = $Destino
    $a.IconLocation = "$exe,0"; $a.Description = 'Tus muestras, ventas y plan de videos'; $a.Save()
    [CreatorHubAccesos]::FijarAumid($lnk, 'CreatorHub.App')
    $accesos += $lnk
}

# Entrada en Ajustes > Aplicaciones. Desinstala desinstalar.ps1 (se copia a %TEMP% antes de borrar la carpeta).
$version = [string](Get-Item -LiteralPath $exe).VersionInfo.ProductVersion
$kb = [int]((Get-ChildItem -LiteralPath $Destino -Recurse -File | Measure-Object Length -Sum).Sum / 1KB)
$desinstalar = Join-Path $Destino 'desinstalar.ps1'
New-Item -Path $ClaveDesinstalar -Force | Out-Null
$valores = [ordered]@{
    DisplayName = 'Corte'; DisplayVersion = $version; Publisher = 'Corte'; DisplayIcon = "$exe,0"
    InstallLocation = $Destino; NoModify = 1; NoRepair = 1; EstimatedSize = $kb
    UninstallString = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$desinstalar`" -Clave `"$ClaveDesinstalar`""
}
foreach ($k in $valores.Keys) {
    $tipo = if ($valores[$k] -is [int]) { 'DWord' } else { 'String' }
    New-ItemProperty -Path $ClaveDesinstalar -Name $k -Value $valores[$k] -PropertyType $tipo -Force | Out-Null
}
New-ItemProperty -Path $ClaveDesinstalar -Name 'Accesos' -Value ([string[]]$accesos) -PropertyType MultiString -Force | Out-Null
if (-not $SinAbrir) { Start-Process -FilePath $exe }
