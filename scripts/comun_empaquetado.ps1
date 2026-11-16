# Funciones de los scripts de build-empaquetado (Windows PowerShell 5.1). Se carga DESPUÉS de comun.ps1 (que es de
# hub-andamio y no se edita):  . (Join-Path $PSScriptRoot 'comun.ps1'); . (Join-Path $PSScriptRoot 'comun_empaquetado.ps1')
$script:DirEmpaquetado = $PSScriptRoot

# Texto de una línea de salida de un programa nativo con 2>&1: en 5.1 cada línea de stderr llega como ErrorRecord y
# "$_" de una línea vacía da «System.Management.Automation.RemoteException»; el mensaje es la línea tal cual.
function TextoDeSalida($linea) {
    if ($linea -is [System.Management.Automation.ErrorRecord]) { return [string]$linea.Exception.Message }
    return [string]$linea
}

# node_modules al día con el lock, sin borrarlo de más. AsegurarNodeModules (comun.ps1) corre `npm ci` cuando la marca
# .ch-lock.sha256 falta o es de otro lock, y `npm ci` BORRA node_modules antes de instalar: en el árbol compartido eso
# tumba lo que estén corriendo los demás paquetes. Aquí, si la marca no está vigente pero comprobar_node_modules.mjs
# confirma que node_modules ya coincide con el lock (cada paquete con su versión exacta y nada de más), se adopta la
# marca. Después se llama SIEMPRE a AsegurarNodeModules: si node_modules no coincidía, hace su `npm ci` como siempre.
function NodeModulesAlDia([string]$carpetaUi) {
    $lock = Join-Path $carpetaUi 'package-lock.json'
    $modulos = Join-Path $carpetaUi 'node_modules'
    $marca = Join-Path $modulos '.ch-lock.sha256'
    if ((Test-Path -LiteralPath $lock) -and (Test-Path -LiteralPath $modulos)) {
        $hash = (Get-FileHash -LiteralPath $lock -Algorithm SHA256).Hash
        $vigente = (Test-Path -LiteralPath $marca) -and ((Get-Content -LiteralPath $marca -Raw).Trim() -eq $hash)
        if (-not $vigente) {
            $node = Join-Path $script:NodeDir 'node.exe'
            $comprobar = Join-Path $script:DirEmpaquetado 'comprobar_node_modules.mjs'
            $previo = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
            try { & $node $comprobar $carpetaUi 2>&1 | ForEach-Object { Write-Host (TextoDeSalida $_) } }
            finally { $ErrorActionPreference = $previo }
            if ($LASTEXITCODE -eq 0) {
                EscribirUtf8SinBom $marca $hash
                Write-Host 'node_modules ya coincide con package-lock.json: se adopta la marca sin npm ci'
            }
        }
    }
    AsegurarNodeModules $carpetaUi
}
