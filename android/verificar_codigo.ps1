<#
  Revisión estática de android-shell contra los contratos congelados (sin emulador ni internet):
   1. PuenteJs expone EXACTAMENTE los métodos de PuenteAndroid (spec/ui_firmas/plataforma.d.ts): nombres, número de
      parámetros y tipos; @JavascriptInterface solo en PuenteJs (BUILD_SPEC §9).
   2. creatorhub-copia y EstadoConexionPc llevan exactamente las claves de EventosAndroid / EstadoConexionPc (rev. 3.1:
      img_rev y sync_en_curso).
   3. La CSP de Android = la de BUILD_SPEC §6.4 (frame-src 'none' + media-src) y va como CABECERA en ServidorAssets;
      lo que no es el origen local responde 403; la interfaz de prueba no trae CSP en <meta>.
   4. inyectarEntorno escribe data-system-reduced-motion; data-reduced-motion no aparece en el código Java/XML y la
      interfaz de prueba solo lo lee (para comprobar que nadie lo pone).
   5. Sin Log de cuerpos, claves ni tokens: el código de main/ no usa android.util.Log, System.out/err ni
      printStackTrace; el de debug/ solo registra resultados de prueba.
   6. Manifiesto: exactamente los 5 permisos y <queries> de com.zhiliaoapp.musically.
   7. Si existe el APK release: aapt2 (minSdk 26, targetSdk 35, 5 permisos, no depurable) y que no contenga el código
      de prueba (CorteTls, ch_prueba_tls).
  Uso: powershell -NoProfile -ExecutionPolicy Bypass -File android\verificar_codigo.ps1
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Raiz    = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Android = Join-Path $Raiz 'android'
$Main    = Join-Path $Android 'app\src\main\java\app\creatorhub'
$Debug   = Join-Path $Android 'app\src\debug\java'
$fallas  = New-Object System.Collections.Generic.List[string]
function Bien([string]$t) { Write-Host "[ok] $t" }
function Mal([string]$t) { Write-Host "[FALLA] $t"; $fallas.Add($t) }
function Leer([string]$r) { [IO.File]::ReadAllText($r, [Text.Encoding]::UTF8) }

# ---------------------------------------------------------------- 1. PuenteJs = PuenteAndroid
$dts = Leer (Join-Path $Raiz 'spec\ui_firmas\plataforma.d.ts')
$bloque = [regex]::Match($dts, 'export interface PuenteAndroid \{(.*?)\n\}', 'Singleline').Groups[1].Value
$ts = @{}
foreach ($m in [regex]::Matches($bloque, '(?m)^\s+(\w+)\(([^)]*)\):\s*(\w+);')) {
    $params = @(); if ($m.Groups[2].Value.Trim()) { $params = @($m.Groups[2].Value.Split(',') | ForEach-Object { $_.Split(':')[1].Trim() }) }
    $ts[$m.Groups[1].Value] = @{ ret = $m.Groups[3].Value; params = $params }
}
$puente = Leer (Join-Path $Main 'web\PuenteJs.java')
$java = @{}
foreach ($m in [regex]::Matches($puente, '@JavascriptInterface\s+public\s+(\w+)\s+(\w+)\(([^)]*)\)')) {
    $params = @(); if ($m.Groups[3].Value.Trim()) { $params = @($m.Groups[3].Value.Split(',') | ForEach-Object { $_.Trim().Split(' ')[0] }) }
    $java[$m.Groups[2].Value] = @{ ret = $m.Groups[1].Value; params = $params }
}
$mapa = @{ 'string' = 'String'; 'boolean' = 'boolean'; 'void' = 'void'; 'number' = 'int' }
$soloTs = @($ts.Keys | Where-Object { -not $java.ContainsKey($_) })
$soloJava = @($java.Keys | Where-Object { -not $ts.ContainsKey($_) })
if ($ts.Count -eq 0) { Mal 'No se pudo leer PuenteAndroid de plataforma.d.ts' }
elseif ($soloTs.Count -or $soloJava.Count) { Mal "PuenteJs ≠ PuenteAndroid · faltan: $($soloTs -join ',') · sobran: $($soloJava -join ',')" }
else {
    $tipos = @()
    foreach ($k in $ts.Keys) {
        $t = $ts[$k]; $j = $java[$k]
        if ($mapa[$t.ret] -ne $j.ret) { $tipos += "$k devuelve $($j.ret) (d.ts: $($t.ret))" }
        if ($t.params.Count -ne $j.params.Count) { $tipos += "$k con $($j.params.Count) parámetros (d.ts: $($t.params.Count))" }
        else { for ($i = 0; $i -lt $t.params.Count; $i++) { if ($mapa[$t.params[$i]] -ne $j.params[$i]) { $tipos += "$k parámetro $($i + 1): $($j.params[$i]) (d.ts: $($t.params[$i]))" } } }
    }
    if ($tipos.Count) { Mal ("Tipos distintos: " + ($tipos -join ' · ')) } else { Bien "PuenteJs expone exactamente los $($ts.Count) métodos de PuenteAndroid con sus tipos" }
}
$otros = @(Get-ChildItem $Main -Recurse -Filter *.java | Where-Object { $_.Name -ne 'PuenteJs.java' -and (Leer $_.FullName) -match '@JavascriptInterface' })
if ($otros.Count) { Mal "@JavascriptInterface fuera de PuenteJs: $($otros.Name -join ', ')" } else { Bien '@JavascriptInterface solo en PuenteJs' }
if ((Leer (Join-Path $Main 'MainActivity.java')) -match 'addJavascriptInterface\(new PuenteJs\(this, nucleo\), "CreatorHubAndroid"\)') { Bien 'window.CreatorHubAndroid = PuenteJs' } else { Mal 'MainActivity no inyecta PuenteJs como CreatorHubAndroid' }
if ($puente -match 'RESTAURAR = Pattern\.compile\("/api/plantillas/\[A-Za-z0-9_-\]\{1,64\}/restaurar"\)' -and $puente -match '"POST"\.equals\(metodo\)' -and $puente -match '"/api/sync"\.equals\(ruta\)') { Bien 'peticion() solo admite POST /api/sync y POST /api/plantillas/{id}/restaurar' } else { Mal 'peticion() no restringe las rutas' }

# ---------------------------------------------------------------- 2. claves de eventos y estado
function ClavesTs([string]$texto) { @([regex]::Matches($texto, '(\w+)\??:') | ForEach-Object { $_.Groups[1].Value }) | Sort-Object -Unique }
$copiaTs = ClavesTs ([regex]::Match($dts, "'creatorhub-copia': \{([^}]*)\}").Groups[1].Value)
$nucleo = Leer (Join-Path $Main 'Nucleo.java')
$emitirCopia = [regex]::Match($nucleo, 'public void emitirCopia\(.*?\n    \}', 'Singleline').Value
$copiaJava = @([regex]::Matches($emitirCopia, '\.put\("(\w+)"') | ForEach-Object { $_.Groups[1].Value }) | Sort-Object -Unique
if (($copiaTs -join ',') -eq ($copiaJava -join ',') -and $copiaJava -contains 'img_rev' -and $copiaJava -contains 'sync_en_curso') { Bien "creatorhub-copia = {$($copiaJava -join ', ')}" } else { Mal "creatorhub-copia: Java {$($copiaJava -join ',')} vs d.ts {$($copiaTs -join ',')}" }
$estTs = ClavesTs ([regex]::Match($dts, 'export interface EstadoConexionPc \{(.*?)\n\}', 'Singleline').Groups[1].Value -replace '/\*\*.*?\*/', '')
$estado = [regex]::Match($nucleo, 'public JSONObject estado\(\).*?return o;', 'Singleline').Value
$estJava = @([regex]::Matches($estado, '\.put\("(\w+)"') | ForEach-Object { $_.Groups[1].Value }) | Sort-Object -Unique
if (($estTs -join ',') -eq ($estJava -join ',')) { Bien "EstadoConexionPc = {$($estJava -join ', ')}" } else { Mal "EstadoConexionPc: Java {$($estJava -join ',')} vs d.ts {$($estTs -join ',')}" }

# ---------------------------------------------------------------- 3. CSP como cabecera y 403
$build = Leer (Join-Path $Raiz 'spec\BUILD_SPEC.md')
$cspWin = [regex]::Match($build, '`(default-src ''self''; script-src[^`]*)`').Groups[1].Value
$cspAndEsperada = @(($cspWin -replace 'frame-src https://www\.tiktok\.com', "frame-src 'none'") -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ }) + "media-src 'self' blob: mediastream:"
$servidor = Leer (Join-Path $Main 'web\ServidorAssets.java')
$cspCodigo = (([regex]::Matches([regex]::Match($servidor, 'String CSP = (.*?);\r?\n', 'Singleline').Groups[1].Value, '"([^"]*)"') | ForEach-Object { $_.Groups[1].Value }) -join '')
$cspAnd = @($cspCodigo -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if ($cspWin -and ((@($cspAndEsperada | Sort-Object) -join '|') -eq (@($cspAnd | Sort-Object) -join '|'))) { Bien "CSP de Android = BUILD_SPEC §6.4 ($($cspAnd.Count) directivas)" } else { Mal "CSP distinta de §6.4: $cspCodigo" }
if ($servidor -match 'h\.put\("Content-Security-Policy", CSP\)') { Bien 'CSP como cabecera HTTP en ServidorAssets.respuesta' } else { Mal 'ServidorAssets no pone la CSP como cabecera' }
if ($servidor -match 'if \(!esLocal\(u\)\) return vacio\(403, "Forbidden"\)') { Bien 'Todo lo que no es https://appassets.androidplatform.net responde 403' } else { Mal 'Falta el 403 a lo externo' }
$metas = @(Get-ChildItem (Join-Path $Android 'ui_prueba') -Recurse -Filter *.html | Where-Object { (Leer $_.FullName) -match '(?i)<meta[^>]+http-equiv' })
if ($metas.Count) { Mal 'La interfaz de prueba trae CSP en <meta>' } else { Bien 'Sin CSP en <meta>' }

# ---------------------------------------------------------------- 4. entorno: solo data-system-reduced-motion
$act = Leer (Join-Path $Main 'MainActivity.java')
$inyectar = [regex]::Match($act, 'void inyectarEntorno\(\) \{.*?\n    \}', 'Singleline').Value
$conPatron = @(Get-ChildItem (Join-Path $Android 'app\src') -Recurse -File -Include *.java, *.xml | Where-Object { (Leer $_.FullName) -match 'data-reduced-motion' })
# la interfaz de prueba solo puede LEERLO (comprueba que Java no lo ponga), nunca escribirlo
$conPatron += @(Get-ChildItem (Join-Path $Android 'ui_prueba') -Recurse -File -Include *.js, *.html | Where-Object { (Leer $_.FullName) -match "(setAttribute|toggleAttribute)\(\s*'data-reduced-motion'|reducedMotion\s*=" })
if ($inyectar -match "toggleAttribute\('data-system-reduced-motion'" -and $inyectar -match '--native-inset-top' -and $inyectar -match "'--fs'" -and $inyectar -match "data-platform','android'" -and $inyectar -match "data-glass','on'") { Bien 'inyectarEntorno escribe --native-inset-*, --native-ime, --fs, data-platform, data-glass y data-system-reduced-motion' } else { Mal 'inyectarEntorno incompleto' }
if ($conPatron.Count) { Mal "data-reduced-motion aparece en: $($conPatron.FullName -join ', ')" } else { Bien 'data-reduced-motion no aparece en el código Java/XML y nadie lo escribe (C48)' }

# ---------------------------------------------------------------- 5. sin Log de cuerpos ni secretos
$conLog = @(Get-ChildItem $Main -Recurse -Filter *.java | Where-Object { (Leer $_.FullName) -match 'android\.util\.Log|\bLog\.[videwa]\(|System\.(out|err)\.|printStackTrace' })
if ($conLog.Count) { Mal "Registro en main/: $($conLog.Name -join ', ')" } else { Bien 'main/ no registra nada (sin android.util.Log, System.out/err ni printStackTrace)' }
$logsDebug = @(Get-ChildItem $Debug -Recurse -Filter *.java | ForEach-Object { Select-String -Path $_.FullName -Pattern '\bLog\.[videwa]\(' })
$sospechosos = @($logsDebug | Where-Object { $_.Line -match '(?i)key|clave|token|secret|cuerpo|codigo|sig' })
if ($sospechosos.Count) { Mal "Log sospechoso en debug/: $($sospechosos.Line -join ' | ')" } else { Bien "debug/: $($logsDebug.Count) llamadas a Log, solo con resultados de prueba (etiquetas CorteTls/CorteWeb)" }

# ---------------------------------------------------------------- 6. manifiesto
$man = Leer (Join-Path $Android 'app\src\main\AndroidManifest.xml')
$perms = @([regex]::Matches($man, 'uses-permission android:name="([^"]+)"') | ForEach-Object { $_.Groups[1].Value }) | Sort-Object
$esperados = @('android.permission.ACCESS_NETWORK_STATE', 'android.permission.CAMERA', 'android.permission.INTERNET', 'android.permission.POST_NOTIFICATIONS', 'android.permission.RECEIVE_BOOT_COMPLETED')
if (($perms -join ',') -eq ($esperados -join ',')) { Bien 'Manifiesto: exactamente los 5 permisos' } else { Mal "Permisos: $($perms -join ', ')" }
if ($man -match '<queries>\s*<package android:name="com\.zhiliaoapp\.musically" />\s*</queries>') { Bien '<queries> com.zhiliaoapp.musically' } else { Mal 'Falta <queries> de TikTok' }

# ---------------------------------------------------------------- 7. APK release (si existe)
$apk = Join-Path $Android 'app\build\outputs\apk\release\app-release.apk'
if (Test-Path $apk) {
    $previo = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    $badging = & 'D:\Android\Sdk\build-tools\35.0.0\aapt2.exe' dump badging $apk 2>&1 | ForEach-Object { "$_" }
    $ErrorActionPreference = $previo
    $p2 = @($badging | Select-String "uses-permission: name='([^']+)'" | ForEach-Object { $_.Matches[0].Groups[1].Value }) | Sort-Object
    $sdkOk = ($badging -match "minSdkVersion:'26'") -and ($badging -match "targetSdkVersion:'35'")
    $depurable = [bool]($badging -match 'application-debuggable')
    if ($sdkOk -and (($p2 -join ',') -eq ($esperados -join ',')) -and -not $depurable) { Bien "APK release: minSdk 26, targetSdk 35, 5 permisos, no depurable ($([int]((Get-Item $apk).Length / 1KB)) KB)" } else { Mal "APK release: sdk=$sdkOk permisos=$($p2 -join ',') depurable=$depurable" }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($apk)
    try {
        $dex = @($zip.Entries | Where-Object { $_.FullName -like 'classes*.dex' })
        $hallados = @()
        foreach ($e in $dex) {
            $ms = New-Object IO.MemoryStream; $s = $e.Open(); try { $s.CopyTo($ms) } finally { $s.Dispose() }
            $txt = [Text.Encoding]::ASCII.GetString($ms.ToArray())
            foreach ($marca in @('CorteTls', 'CorteWeb', 'ch_prueba_tls', 'ch_prueba_web')) { if ($txt.Contains($marca)) { $hallados += $marca } }
        }
        if ($hallados.Count) { Mal "El APK release contiene código de prueba: $($hallados -join ', ')" } else { Bien 'El APK release no contiene el código de prueba (CorteTls, ch_prueba_*)' }
    } finally { $zip.Dispose() }
} else { Write-Host "[--] Sin APK release en $apk (compila con gradle --offline :app:assembleRelease)" }

Write-Host ''
if ($fallas.Count) { Write-Host "$($fallas.Count) falla(s)"; exit 1 }
Write-Host 'Revisión estática: todo en orden'
exit 0
