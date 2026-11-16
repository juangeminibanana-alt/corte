<#
  Pruebas del paquete build-empaquetado. Todo lo que compila, instala o modifica va a una carpeta temporal
  (%TEMP%\corte-empaquetado-*) y a la clave de prueba HKCU:\Software\CreatorHubPrueba (se borra al final); en el
  proyecto solo regenera branding\ (render_iconos.mjs) y escribe build\pruebas_empaquetado\resultado.txt.
    A. Los .ps1 propios: parser sin errores, UTF-8 con BOM y CRLF.
    B. render_iconos.mjs: branding\ (12 PNG, .ico con 10 tamaños, mipmaps de Android) y la forma literal de 04 §D.4.
    C. generar_licencias.ps1: JSON válido con TODAS las dependencias de ejecución (revisado aparte contra el lock y
       requirements.txt) y dos pruebas negativas (requisito sin instalar, lock distinto de node_modules).
    D. CreatorHub.spec: Python válido; collect_data_files('creatorhub', excludes=['**/pruebas/**']); version.json como
       dato en creatorhub; PIL fuera de excludes; dependencias de compilación excluidas.
    E. verificar_todo.ps1: los 11 pasos de BUILD §11.1 en orden (y una corrida corta).
    F. build_windows.ps1 de punta a punta en un árbol temporal: -SinUI con una interfaz mínima, el paquete creatorhub
       REAL y un __main__ de SONDA (el real lo entrega windows-shell): preparar_entorno -SinRed, licencias, íconos,
       PyInstaller con CreatorHub.spec, guardia, 2 autopruebas (t_hub_listo_ms <= 800) y zip con Instalar.ps1.
    G. La guardia rechaza exes de prueba con creador_demo o __DOBLE_CORTE__ (dentro de un módulo del PYZ, invisibles
       para una búsqueda simple de bytes, y en archivos de datos), .map, research\, fixtures, spec\verificacion\ejemplos,
       config.json, setuptools y secretos; la excepción de creatorhub.demo.transporte no deja pasar otro módulo y se
       informa con AVISO. Datos privados (§11.6) con un perfil FALSO: username, open_id y avatar se rechazan nombrando
       el campo sin mostrar el valor; el exe de F no trae la identidad real de research\datos-reales.
    H. Instalar.ps1 y desinstalar.ps1 del zip: instalar, AUMID del acceso, actualizar con la app abierta, guardia de la
       desinstalación y desinstalar con la app abierta.
    I. dev.ps1 (con un hub falso en 127.0.0.1:39229 si está libre) y medir_arranque.ps1 (plomería con la sonda).
    J. build_android.ps1 -Tipo release en una COPIA de android\ (--offline, sin daemon, interfaz mínima): permisos, firma,
       archivos prohibidos y licencias.json de Android dentro del APK. Luego -Tipo debug -UiDist <otra interfaz> con un
       manifiesto al que se le quitó CAMERA: Gradle usa esa interfaz (-PchUiDist) y la verificación falla por el permiso
       que falta. Por último, con un perfil privado FALSO en research\datos-reales de la copia y su username en la
       interfaz, falla nombrando el campo sin mostrar el valor. El android\ real no se toca.
    K. comprobar_node_modules.mjs y NodeModulesAlDia con un ui\ falso: adopta la marca si node_modules coincide con el
       lock (sin npm ci) y detecta versión distinta, paquete faltante y paquete de más. Nunca toca ui\node_modules real.
  Uso: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\probar_empaquetado.ps1 [-Solo A,B,C] [-Conservar]
  Sale con 0 solo si todo pasa. F, G, H e I necesitan el árbol temporal de F (con -Solo se arma igual si hace falta).
#>
[CmdletBinding()]
param([string[]]$Solo = @(), [switch]$Conservar)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'comun.ps1')
. (Join-Path $PSScriptRoot 'comun_empaquetado.ps1')

$Raiz  = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Py    = Join-Path $Raiz '.venv-hub\Scripts\python.exe'
$Node  = Join-Path $script:NodeDir 'node.exe'
$PS    = Join-Path ([Environment]::SystemDirectory) 'WindowsPowerShell\v1.0\powershell.exe'
$Tmp     = Join-Path $env:TEMP ('corte-empaquetado-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
$Clave = 'HKCU:\Software\CreatorHubPrueba\Uninstall\CreatorHub'
$Salida = Join-Path $Raiz 'build\pruebas_empaquetado'
$Solo = @($Solo | ForEach-Object { $_ -split ',' } | Where-Object { $_ } | ForEach-Object { $_.Trim().ToUpper() })
$script:res = New-Object System.Collections.Generic.List[string]
$script:fallas = 0
$script:enlaces = New-Object System.Collections.Generic.List[string]

function Anotar([string]$t) { $script:res.Add($t); Write-Host $t }
function Ok([string]$t) { $script:res.Add("[ok] $t"); Write-Host "[ok] $t" -ForegroundColor Green }
function Falla([string]$t) { $script:fallas++; $script:res.Add("[FALLA] $t"); Write-Host "[FALLA] $t" -ForegroundColor Red }
function Comprobar([bool]$cond, [string]$bien, [string]$mal) { if ($cond) { Ok $bien } else { Falla $mal } }
function Toca([string]$s) { return ($Solo.Count -eq 0 -or $Solo -contains $s) }
function Seccion([string]$t) { Anotar ''; Anotar "== $t" }

# Corre un .ps1 en otro powershell.exe (como lo haría una persona) y devuelve @{codigo; salida}.
function CorrerPs([string]$archivo, [string[]]$argumentos = @()) {
    $previo = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { $salida = @(& $PS -NoProfile -ExecutionPolicy Bypass -File $archivo @argumentos 2>&1 | ForEach-Object { TextoDeSalida $_ }) }
    finally { $ErrorActionPreference = $previo }
    return @{ codigo = $LASTEXITCODE; salida = $salida }
}
function CorrerNativo([string]$exe, [string[]]$argumentos) {
    $previo = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { $salida = @(& $exe @argumentos 2>&1 | ForEach-Object { TextoDeSalida $_ }) } finally { $ErrorActionPreference = $previo }
    return @{ codigo = $LASTEXITCODE; salida = $salida }
}
function Ultimas($r, [int]$n = 6) { (@($r.salida) | Select-Object -Last $n) -join ' | ' }

# Enlaces de directorio (junction) hacia .venv-hub y ui\node_modules: se quitan SOLO con rmdir (nunca recursivo).
function Enlazar([string]$ruta, [string]$destino) {
    New-Item -ItemType Directory -Force (Split-Path -Parent $ruta) | Out-Null
    $null = New-Item -ItemType Junction -Path $ruta -Target $destino
    $script:enlaces.Add($ruta)
}
function QuitarEnlaces {
    foreach ($e in $script:enlaces) {
        if (Test-Path -LiteralPath $e) {
            $item = Get-Item -LiteralPath $e -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { [IO.Directory]::Delete($e, $false) }
        }
    }
    $script:enlaces.Clear()
}
function MedidasPng([string]$ruta) {
    $b = [IO.File]::ReadAllBytes($ruta)
    $w = ([int]$b[16] -shl 24) -bor ([int]$b[17] -shl 16) -bor ([int]$b[18] -shl 8) -bor [int]$b[19]
    $h = ([int]$b[20] -shl 24) -bor ([int]$b[21] -shl 16) -bor ([int]$b[22] -shl 8) -bor [int]$b[23]
    return "${w}x$h"
}
function TamanosIco([string]$ruta) {
    $ico = [IO.File]::ReadAllBytes($ruta)
    $n = [BitConverter]::ToUInt16($ico, 4)
    return (@(foreach ($i in 0..($n - 1)) { $w = $ico[6 + 16 * $i]; if ($w -eq 0) { 256 } else { [int]$w } }) | Sort-Object) -join ','
}
function EscribirPy([string]$nombre, [string]$codigo) {
    $ruta = Join-Path $Tmp "py\$nombre"
    New-Item -ItemType Directory -Force (Split-Path -Parent $ruta) | Out-Null
    EscribirUtf8SinBom $ruta $codigo
    return $ruta
}

$Propios = @(Get-ChildItem (Join-Path $Raiz 'scripts\*.ps1') | Where-Object { $_.Name -notin @('comun.ps1', 'preparar_entorno.ps1') }) +
           @(Get-ChildItem (Join-Path $Raiz 'instalador\*.ps1'))
New-Item -ItemType Directory -Force $Tmp, $Salida | Out-Null
Anotar ("probar_empaquetado · {0:s} · árbol temporal {1}" -f (Get-Date), $Tmp)

try {
# =========================================================================================== A
if (Toca 'A') {
    Seccion 'A. .ps1 propios: sintaxis, UTF-8 con BOM y CRLF'
    foreach ($f in $Propios) {
        $tok = $null; $err = $null
        [void][System.Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$tok, [ref]$err)
        $b = [IO.File]::ReadAllBytes($f.FullName)
        $bom = $b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF
        $texto = [Text.Encoding]::UTF8.GetString($b)
        $lf = ([regex]::Matches($texto, "`n")).Count; $crlf = ([regex]::Matches($texto, "`r`n")).Count
        $rel = $f.FullName.Substring($Raiz.Length + 1)
        Comprobar ($err.Count -eq 0 -and $bom -and $lf -eq $crlf -and $lf -gt 0) "$rel · 0 errores de sintaxis · BOM · $crlf líneas CRLF" `
            "$rel · errores $($err.Count) $(($err | ForEach-Object { 'L' + $_.Extent.StartLineNumber + ': ' + $_.Message }) -join '; ') · BOM $bom · LF sueltos $($lf - $crlf)"
    }
    $cmd = [IO.File]::ReadAllBytes((Join-Path $Raiz 'instalador\Instalar Corte.cmd'))
    Comprobar (-not ($cmd | Where-Object { $_ -gt 127 }) -and ([Text.Encoding]::ASCII.GetString($cmd) -match "`r`n")) 'instalador\Instalar Corte.cmd en ASCII con CRLF' 'Instalar Corte.cmd no es ASCII con CRLF'
    $codigo = @(Get-ChildItem (Join-Path $Raiz 'tools\*.py')) + @(Get-ChildItem (Join-Path $Raiz 'scripts\*.mjs')) +
              @(Get-Item -LiteralPath (Join-Path $Raiz 'ui\scripts\render_iconos.mjs'), (Join-Path $Raiz 'hub\CreatorHub.spec'))
    $conBom = @($codigo | Where-Object { $b = [IO.File]::ReadAllBytes($_.FullName); $b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF })
    $malSintaxis = @(foreach ($f in $codigo) {
        if ($f.Extension -eq '.mjs') { $r = CorrerNativo $Node @('--check', $f.FullName) }
        else { $r = CorrerNativo $Py @('-I', '-c', 'import ast,sys; ast.parse(open(sys.argv[1], encoding=''utf-8'').read())', $f.FullName) }
        if ($r.codigo -ne 0) { "$($f.Name): $(Ultimas $r 2)" } })
    Comprobar ($conBom.Count -eq 0 -and $malSintaxis.Count -eq 0) "código propio en UTF-8 sin BOM (BUILD §9) y con sintaxis válida (node --check / ast.parse): $(($codigo | ForEach-Object Name) -join ', ')" `
        "con BOM: $(($conBom | ForEach-Object Name) -join ', ') · sintaxis: $($malSintaxis -join '; ')"
}

# =========================================================================================== B
if (Toca 'B') {
    Seccion 'B. render_iconos.mjs'
    $r = CorrerNativo $Node @((Join-Path $Raiz 'ui\scripts\render_iconos.mjs'))
    Comprobar ($r.codigo -eq 0) "node ui\scripts\render_iconos.mjs · $(Ultimas $r 1)" "render_iconos.mjs salió con $($r.codigo): $(Ultimas $r)"
    $b = Join-Path $Raiz 'branding'
    $malos = @(foreach ($t in 16, 20, 24, 32, 40, 48, 64, 96, 128, 256, 512, 1024) {
        $p = Join-Path $b "png\icono-$t.png"; if (-not (Test-Path $p) -or (MedidasPng $p) -ne "${t}x$t") { "icono-$t" } })
    Comprobar ($malos.Count -eq 0) 'branding\png: 12 PNG con el tamaño exacto (16–1024)' "PNG con tamaño incorrecto: $($malos -join ', ')"
    $ico = Join-Path $b 'CreatorHub.ico'
    Comprobar ((Test-Path $ico) -and (TamanosIco $ico) -eq '16,20,24,32,40,48,64,96,128,256') "branding\CreatorHub.ico con [$(if (Test-Path $ico) { TamanosIco $ico })]" 'CreatorHub.ico falta o no trae los 10 tamaños'
    $densidades = [ordered]@{ mdpi = 1; hdpi = 1.5; xhdpi = 2; xxhdpi = 3; xxxhdpi = 4 }
    $malos = @(foreach ($d in $densidades.Keys) {
        $f = $densidades[$d]
        foreach ($par in @(@('ic_launcher.png', 48), @('ic_launcher_round.png', 48), @('ic_launcher_foreground.png', 108), @('ic_launcher_monochrome.png', 108))) {
            $t = [int][math]::Round($par[1] * $f); $p = Join-Path $b "android\res\mipmap-$d\$($par[0])"
            if (-not (Test-Path $p) -or (MedidasPng $p) -ne "${t}x$t") { "mipmap-$d\$($par[0])" } } })
    $tienda = Join-Path $b 'android\play_store_512.png'
    Comprobar ($malos.Count -eq 0 -and (Test-Path $tienda) -and (MedidasPng $tienda) -eq '512x512') 'branding\android\res\mipmap-{mdpi…xxxhdpi}: ic_launcher(_round) 48 dp y capas adaptables 108 dp (20 PNG) + play_store_512.png' "mipmaps mal: $($malos -join ', ')"
    $iguales = (Get-FileHash (Join-Path $b 'icono.svg')).Hash -eq (Get-FileHash (Join-Path $Raiz 'spec\assets\icon.svg')).Hash -and
               (Get-FileHash (Join-Path $b 'icono_pequeno.svg')).Hash -eq (Get-FileHash (Join-Path $Raiz 'spec\assets\icon-16.svg')).Hash
    Comprobar $iguales 'branding\icono.svg e icono_pequeno.svg = spec\assets\icon.svg e icon-16.svg (las rutas que usa build_windows)' 'los SVG de branding\ no coinciden con spec\assets'
    $lit = Join-Path $Tmp 'iconos_literal'
    $r = CorrerNativo $Node @((Join-Path $Raiz 'ui\scripts\render_iconos.mjs'), (Join-Path $b 'icono.svg'), $lit, (Join-Path $b 'icono_pequeno.svg'))
    $r2 = CorrerNativo $Py @((Join-Path $Raiz 'tools\generar_ico.py'), $lit, (Join-Path $lit 'CreatorHub.ico'))
    $n = @(Get-ChildItem $lit -Filter 'icono-*.png').Count
    Comprobar ($r.codigo -eq 0 -and $r2.codigo -eq 0 -and $n -eq 12 -and (TamanosIco (Join-Path $lit 'CreatorHub.ico')) -eq '16,20,24,32,40,48,64,96,128,256') `
        "forma literal de 04 §D.4 (la del paso 2 de build_windows): $n PNG + generar_ico.py -> .ico con 10 tamaños" "forma literal: render $($r.codigo), ico $($r2.codigo), $n PNG"
}

# =========================================================================================== C
if (Toca 'C') {
    Seccion 'C. generar_licencias.ps1'
    $lic = Join-Path $Tmp 'licencias\licencias.json'
    $r = CorrerPs (Join-Path $Raiz 'scripts\generar_licencias.ps1') @('-Salida', $lic)
    Comprobar ($r.codigo -eq 0 -and (Test-Path $lic)) "scripts\generar_licencias.ps1 · $(Ultimas $r 1)" "generar_licencias.ps1 salió con $($r.codigo): $(Ultimas $r)"
    $verificar = EscribirPy 'verificar_licencias.py' @'
import importlib.metadata as md, json, re, sys
raiz, ruta = sys.argv[1], sys.argv[2]
d = json.load(open(ruta, encoding='utf-8'))            # JSON válido
lock = json.load(open(raiz + r'\ui\package-lock.json', encoding='utf-8'))
esperados = {k.rsplit('node_modules/', 1)[-1]: v['version'] for k, v in lock['packages'].items()
             if k and not v.get('dev') and not v.get('devOptional')}
reqs, dentro = {}, False
for l in open(raiz + r'\hub\requirements.txt', encoding='utf-8'):
    s = l.strip()
    if s.startswith('# ---'):
        dentro = 'entran en CreatorHub.exe' in s; continue
    m = re.match(r'^([A-Za-z0-9_.\-]+)==(\S+)', s)
    if dentro and m: reqs[m.group(1)] = m.group(2)
norm = lambda n: re.sub(r'[-_.]+', '_', n).lower()
inter = {c['nombre']: c for c in d['componentes'] if c['origen'] == 'interfaz'}
exe = {norm(c['nombre']): c for c in d['componentes'] if c['origen'] == 'ejecutable'}
problemas = []
for n, v in esperados.items():
    if n not in inter: problemas.append(f'falta {n}')
    elif inter[n]['version'] != v: problemas.append(f'{n}: {inter[n]["version"]} != lock {v}')
for n in inter:
    if n not in esperados: problemas.append(f'sobra {n}')
for n, v in reqs.items():
    c = exe.get(norm(n)) or exe.get(norm(md.distribution(n).metadata['Name']))
    if not c: problemas.append(f'falta {n}')
    elif c['version'] != v: problemas.append(f'{n}: {c["version"]} != requirements {v}')
for extra in ('python', 'microsoft_web_webview2'):
    if extra not in exe: problemas.append(f'falta {extra}')
if not any(k.startswith('pyinstaller') for k in exe): problemas.append('falta el cargador de PyInstaller')
for c in d['componentes']:
    for campo in ('nombre', 'version', 'licencia', 'texto'):
        if not c.get(campo): problemas.append(f'{c.get("nombre")}: sin {campo}')
lic = {c['nombre']: c['licencia'] for c in d['componentes']}
claves = {'jsqr': 'Apache-2.0', '@fontsource-variable/mona-sans': 'OFL-1.1', '@fontsource-variable/geist-mono': 'OFL-1.1',
          'lucide-react': 'ISC', 'react': 'MIT', 'pillow': 'MIT-CMU', 'pythonnet': 'MIT'}
for n, l in claves.items():
    if lic.get(n) != l: problemas.append(f'{n}: licencia {lic.get(n)} (se esperaba {l})')
texto = open(ruta, encoding='utf-8').read()
for p in ('creador_demo', '__DOBLE_CORTE__'):
    if p in texto: problemas.append(f'contiene {p}')
if re.search('fixtures', texto, re.I): problemas.append('contiene fixtures')
print(json.dumps({'problemas': problemas, 'interfaz': len(inter), 'lock': len(esperados), 'ejecutable': len(exe),
                  'requisitos': len(reqs), 'plataforma': d['plataforma'], 'version': d['version']}, ensure_ascii=False))
'@
    if (Test-Path $lic) {
        $j = (Capturar $Py @('-I', $verificar, $Raiz, $lic)) | ConvertFrom-Json
        Comprobar ($j.problemas.Count -eq 0) ("licencias.json válido: {0} de interfaz = las {1} dependencias de ejecución del lock · {2} del ejecutable ({3} de requirements.txt + Python, WebView2 y el cargador de PyInstaller) · licencias SPDX y textos presentes" -f $j.interfaz, $j.lock, $j.ejecutable, $j.requisitos) `
            "licencias.json con problemas: $($j.problemas -join '; ')"
    }
    $licA = Join-Path $Tmp 'licencias\licencias_android.json'
    $r = CorrerPs (Join-Path $Raiz 'scripts\generar_licencias.ps1') @('-Plataforma', 'android', '-Salida', $licA)
    $soloInterfaz = $false
    if ($r.codigo -eq 0) { $da = Get-Content $licA -Raw -Encoding UTF8 | ConvertFrom-Json; $soloInterfaz = -not ($da.componentes | Where-Object { $_.origen -ne 'interfaz' }) }
    Comprobar ($r.codigo -eq 0 -and $soloInterfaz) '-Plataforma android: solo la interfaz (el APK no lleva otras dependencias)' "android: código $($r.codigo)"
    $r2 = CorrerPs (Join-Path $Raiz 'scripts\generar_licencias.ps1') @('-Salida', (Join-Path $Tmp 'licencias\otra.json'))
    Comprobar ($r2.codigo -eq 0 -and (Get-FileHash $lic).Hash -eq (Get-FileHash (Join-Path $Tmp 'licencias\otra.json')).Hash) 'salida determinista (dos corridas, mismo SHA-256)' 'dos corridas dieron archivos distintos'

    # Negativas en una raíz falsa: requisito no instalado; lock con otra versión que node_modules
    $RaizNeg = Join-Path $Tmp 'licencias_neg'
    foreach ($d in 'ui', 'hub', 'tools') { New-Item -ItemType Directory -Force (Join-Path $RaizNeg $d) | Out-Null }
    Copy-Item (Join-Path $Raiz 'version.json') $RaizNeg
    Copy-Item (Join-Path $Raiz 'tools\licencias') (Join-Path $RaizNeg 'tools') -Recurse
    Enlazar (Join-Path $RaizNeg 'ui\node_modules') (Join-Path $Raiz 'ui\node_modules')
    $req = [IO.File]::ReadAllText((Join-Path $Raiz 'hub\requirements.txt')) -replace '(?m)^(pypng==.*)$', "`$1`r`npaquete-que-no-existe==1.0"
    EscribirUtf8SinBom (Join-Path $RaizNeg 'hub\requirements.txt') $req
    Copy-Item (Join-Path $Raiz 'ui\package-lock.json') (Join-Path $RaizNeg 'ui')
    $neg1 = Join-Path $RaizNeg 'neg1.json'
    $r = CorrerNativo $Py @('-I', (Join-Path $Raiz 'tools\generar_licencias.py'), '--raiz', $RaizNeg, '--salida', $neg1)
    Comprobar ($r.codigo -eq 1 -and -not (Test-Path $neg1) -and ((Ultimas $r) -match 'paquete-que-no-existe')) "negativa: un requisito del exe sin instalar -> código 1, sin archivo ($(Ultimas $r 1))" "negativa 1: código $($r.codigo), archivo $(Test-Path $neg1)"
    Copy-Item (Join-Path $Raiz 'hub\requirements.txt') (Join-Path $RaizNeg 'hub') -Force
    $lockTxt = [IO.File]::ReadAllText((Join-Path $Raiz 'ui\package-lock.json'))
    $lockMal = [regex]::Replace($lockTxt, '("node_modules/react": \{\s*"version": ")19\.3\.1"', '${1}19.3.0"')
    EscribirUtf8SinBom (Join-Path $RaizNeg 'ui\package-lock.json') $lockMal
    $neg2 = Join-Path $RaizNeg 'neg2.json'
    $r = CorrerNativo $Py @('-I', (Join-Path $Raiz 'tools\generar_licencias.py'), '--raiz', $RaizNeg, '--salida', $neg2)
    Comprobar ($lockMal -ne $lockTxt -and $r.codigo -eq 1 -and -not (Test-Path $neg2)) "negativa: lock con react 19.3.0 y node_modules con 19.3.1 -> código 1, sin archivo ($(Ultimas $r 1))" "negativa 2: código $($r.codigo)"
    QuitarEnlaces
}

# =========================================================================================== D
if (Toca 'D') {
    Seccion 'D. hub\CreatorHub.spec'
    $revisar = EscribirPy 'revisar_spec.py' @'
import ast, json, sys
fuente = open(sys.argv[1], encoding='utf-8').read()
arbol = ast.parse(fuente)                       # Python válido
r = {'collect_data_files': False, 'version_json_dato': False, 'version_json_raiz': False, 'pil_excluido': None,
     'excluidos': [], 'analysis_excludes': False, 'ui_dist': False, 'icono': False, 'console_false': False}
asign = {}
for n in ast.walk(arbol):
    if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
        asign[n.targets[0].id] = n.value
for n in ast.walk(arbol):
    if isinstance(n, ast.Call) and getattr(n.func, 'id', None) == 'collect_data_files':
        a = [x.value for x in n.args if isinstance(x, ast.Constant)]
        k = {kw.arg: kw.value for kw in n.keywords}
        exc = k.get('excludes')
        if a == ['creatorhub'] and isinstance(exc, ast.List) and [e.value for e in exc.elts] == ['**/pruebas/**']:
            r['collect_data_files'] = True
    if isinstance(n, ast.Tuple) and len(n.elts) == 2 and isinstance(n.elts[1], ast.Constant):
        a, b = n.elts
        if isinstance(a, ast.Name) and a.id == 'VERSION_JSON' and b.value == 'creatorhub': r['version_json_dato'] = True
        if isinstance(a, ast.Name) and a.id == 'UI_DIST' and b.value == 'ui': r['ui_dist'] = True
        if isinstance(a, ast.Name) and a.id == 'ICO' and b.value == 'recursos': r['icono'] = True
    if isinstance(n, ast.Call) and getattr(n.func, 'id', None) == 'Analysis':
        r['analysis_excludes'] = any(kw.arg == 'excludes' and getattr(kw.value, 'id', None) == 'EXCLUIDOS' for kw in n.keywords)
    if isinstance(n, ast.Call) and getattr(n.func, 'id', None) == 'EXE':
        r['console_false'] = any(kw.arg == 'console' and getattr(kw.value, 'value', None) is False for kw in n.keywords)
v = asign.get('VERSION_JSON')
r['version_json_raiz'] = isinstance(v, ast.Call) and ast.unparse(v) == "os.path.join(RAIZ, 'version.json')"
e = asign.get('EXCLUIDOS')
r['excluidos'] = [x.value for x in e.elts] if isinstance(e, ast.List) else []
r['pil_excluido'] = 'PIL' in r['excluidos']
print(json.dumps(r))
'@
    $j = (Capturar $Py @('-I', $revisar, (Join-Path $Raiz 'hub\CreatorHub.spec'))) | ConvertFrom-Json
    Comprobar $j.collect_data_files "collect_data_files('creatorhub', excludes=['**/pruebas/**'])" 'falta collect_data_files con excludes'
    Comprobar ($j.version_json_dato -and $j.version_json_raiz) "version.json de la raíz como dato en 'creatorhub' (VERSION_JSON = os.path.join(RAIZ, 'version.json'))" 'version.json no va como dato en creatorhub'
    Comprobar (-not $j.pil_excluido -and $j.analysis_excludes) ("PIL ya no está en excludes (C3) · excludes = {0}" -f ($j.excluidos -join ', ')) 'PIL sigue excluido o Analysis no usa EXCLUIDOS'
    $compilacion = @('PyInstaller', 'altgraph', 'pefile', 'win32ctypes', 'packaging', 'setuptools', 'pkg_resources', '_distutils_hack')
    $faltan = @($compilacion | Where-Object { $j.excluidos -notcontains $_ })
    Comprobar ($faltan.Count -eq 0 -and $j.ui_dist -and $j.icono -and $j.console_false) 'excluye las dependencias de compilación · ui\dist -> ui · CreatorHub.ico -> recursos · sin consola' "spec incompleta: faltan excluir $($faltan -join ', ')"
}

# =========================================================================================== E
if (Toca 'E') {
    Seccion 'E. verificar_todo.ps1'
    $texto = [IO.File]::ReadAllText((Join-Path $Raiz 'scripts\verificar_todo.ps1'))
    $marcas = [ordered]@{
        1 = "'unittest', 'discover', '-s', 'hub\pruebas', '-t', 'hub'"; 2 = '$EjemplosUx'; 3 = '$Fixtures'; 4 = "'run', 'firmas'"
        5 = "'run', 'iconos'"; 6 = "'run', 'typecheck'"; 7 = "@('test')"; 8 = "'run', 'build'"; 9 = 'v06_cifras_ux.py'
        10 = 'android\jdk\correr.ps1'; 11 = 'android\pruebas_tls\correr_conscrypt.ps1' }
    $posiciones = @(foreach ($n in $marcas.Keys) { [regex]::Match($texto, "(?m)^\s*@\{ n = $n;").Index })
    $bloques = @(for ($i = 0; $i -lt 11; $i++) { $fin = if ($i -lt 10) { $posiciones[$i + 1] } else { $texto.IndexOf('if (-not $SinPreparar)') }; $texto.Substring($posiciones[$i], [math]::Max(0, $fin - $posiciones[$i])) })
    $orden = @(for ($i = 1; $i -lt 11; $i++) { $posiciones[$i] -gt $posiciones[$i - 1] -and $posiciones[$i - 1] -gt 0 }) -notcontains $false
    $listaMarcas = @($marcas.Values)          # (un OrderedDictionary con índice entero se lee por POSICIÓN, no por clave)
    $marcasOk = @(for ($i = 0; $i -lt 11; $i++) { $bloques[$i].Contains($listaMarcas[$i]) }) -notcontains $false
    $ejemplos = $bloques[1].Contains('$n1 -ne 34 -or $n2 -ne 10')
    Comprobar ($orden -and $marcasOk -and $ejemplos) 'los 11 pasos de BUILD §11.1 en orden: unittest · tsc 34+10 ejemplos · fixtures.check.ts · firmas · iconos · typecheck · test · build · v06 · jdk · Conscrypt' 'verificar_todo.ps1 no tiene los 11 pasos en orden'
    $r = CorrerPs (Join-Path $Raiz 'scripts\verificar_todo.ps1') @('-Pasos', '5', '-SinPreparar')
    $log5 = Join-Path $Raiz 'build\verificar\paso-05.log'
    $corrioIconos = (Test-Path $log5) -and ((Get-Content $log5 -Raw -Encoding UTF8) -match 'npm\.cmd run iconos')
    Comprobar ($r.codigo -eq 0 -and $corrioIconos) "corrida corta (-Pasos 5 -SinPreparar) corre justo «npm run iconos»: $(Ultimas $r 1)" "verificar_todo -Pasos 5 salió con $($r.codigo) (¿corrió npm run iconos? $corrioIconos): $(Ultimas $r)"
    $r = CorrerPs (Join-Path $Raiz 'scripts\verificar_todo.ps1') @('-Pasos', '12', '-SinPreparar')
    Comprobar ($r.codigo -ne 0) 'un paso inexistente (-Pasos 12) se rechaza' 'verificar_todo aceptó -Pasos 12'
    $r = CorrerPs (Join-Path $Raiz 'scripts\verificar_todo.ps1') @('-Pasos', '11,1-3,9', '-Listar')
    $listados = @($r.salida | Where-Object { $_ -match '^\s*(\d+)\.' } | ForEach-Object { [int]([regex]::Match($_, '^\s*(\d+)\.').Groups[1].Value) })
    Comprobar ($r.codigo -eq 0 -and ($listados -join ',') -eq '1,2,3,9,11') "«-Pasos 11,1-3,9» (una sola cadena con powershell -File) elige 1, 2, 3, 9 y 11 y los deja en el orden de §11.1" "-Pasos 11,1-3,9 -Listar dio [$($listados -join ',')] (código $($r.codigo))"
    $r = CorrerPs (Join-Path $Raiz 'scripts\verificar_todo.ps1') @('-Listar')
    $listados = @($r.salida | Where-Object { $_ -match '^\s*\d+\.' })
    Comprobar ($r.codigo -eq 0 -and $listados.Count -eq 11) "sin -Pasos son los 11: $(($listados | ForEach-Object { $_.Trim() }) -join ' · ')" "sin -Pasos lista $($listados.Count) pasos"
}

# =========================================================================================== F
$App = Join-Path $Tmp 'arbol\build\windows\dist\CreatorHub'
$necesitaArbol = (Toca 'F') -or (Toca 'G') -or (Toca 'H') -or (Toca 'I')
if ($necesitaArbol) {
    Seccion 'F. build_windows.ps1 de punta a punta (árbol temporal, -SinUI, __main__ de SONDA)'
    $Arbol = Join-Path $Tmp 'arbol'
    foreach ($d in 'scripts', 'tools', 'instalador', 'spec\assets', 'hub', 'ui\scripts', 'ui\dist\assets') { New-Item -ItemType Directory -Force (Join-Path $Arbol $d) | Out-Null }
    Copy-Item (Join-Path $Raiz 'version.json') $Arbol
    Copy-Item (Join-Path $Raiz 'scripts\*') (Join-Path $Arbol 'scripts')
    Copy-Item (Join-Path $Raiz 'tools\*') (Join-Path $Arbol 'tools') -Recurse
    Copy-Item (Join-Path $Raiz 'instalador\*') (Join-Path $Arbol 'instalador')
    Copy-Item (Join-Path $Raiz 'spec\assets\icon*.svg') (Join-Path $Arbol 'spec\assets')
    Copy-Item (Join-Path $Raiz 'hub\requirements.txt'), (Join-Path $Raiz 'hub\CreatorHub.spec') (Join-Path $Arbol 'hub')
    Copy-Item (Join-Path $Raiz 'ui\package.json'), (Join-Path $Raiz 'ui\package-lock.json') (Join-Path $Arbol 'ui')
    Copy-Item (Join-Path $Raiz 'ui\scripts\render_iconos.mjs') (Join-Path $Arbol 'ui\scripts')
    # creatorhub REAL, sin __main__ ni plataforma\ (son de windows-shell) y sin __pycache__
    $origen = Join-Path $Raiz 'hub\creatorhub'
    $destinoCh = Join-Path $Arbol 'hub\creatorhub'
    $null = & robocopy $origen $destinoCh /E /XD __pycache__ plataforma /XF __main__.py *.pyc /NFL /NDL /NJH /NJS /NP
    if ($LASTEXITCODE -ge 8) { throw "robocopy de creatorhub falló ($LASTEXITCODE)" }
    $extraidos = Join-Path $Tmp 'spec04'
    $null = Capturar $Py @('-I', (Join-Path $Raiz 'spec\pruebas\plataforma\extraer_bloques.py'), $extraidos)
    New-Item -ItemType Directory -Force (Join-Path $destinoCh 'plataforma\windows') | Out-Null
    EscribirUtf8SinBom (Join-Path $destinoCh 'plataforma\__init__.py') "`"`"`"Solo para la prueba de empaquetado (el real es de windows-shell).`"`"`"`n"
    EscribirUtf8SinBom (Join-Path $destinoCh 'plataforma\windows\__init__.py') ''
    Copy-Item (Join-Path $extraidos 'hub\creatorhub\plataforma\windows\instancia.py') (Join-Path $destinoCh 'plataforma\windows')
    EscribirUtf8SinBom (Join-Path $destinoCh '__main__.py') @'
r"""SONDA de scripts\probar_empaquetado.ps1. NO es el __main__ de Corte (lo entrega windows-shell): solo reemplaza el
arranque para ejercitar CreatorHub.spec y los pasos 4-8 de build_windows.ps1 con el paquete creatorhub REAL.
--autoprueba: comprueba datos, fábricas, Pillow, QR, TLS con CNG y WebView2 ya congelados y escribe
%TEMP%\CreatorHub-autoprueba\autoprueba.json; t_hub_listo_ms = ms desde que Windows creó el proceso hasta tener
importadas las fábricas y leídos version.json, plantillas y el esquema (antes de PIL y de WebView2).
--medir: plomería de medir_arranque.ps1 (sin ventana: t_ventana_ms y t_pagina_ms van en null).
--salir/--desinstalar y sin banderas: instancia.py literal de 04 §A.5 con nombres de prueba."""
import sys
from creatorhub.plataforma.windows import instancia

T_MAIN = instancia.ms_desde_inicio_proceso()
instancia.MUTEX = 'Local\\CreatorHub.PruebaEmpaquetado.Instancia'
instancia.ACTIVAR = 'Local\\CreatorHub.PruebaEmpaquetado.Activar'
instancia.SALIR = 'Local\\CreatorHub.PruebaEmpaquetado.Salir'

import importlib
import importlib.resources as res
import importlib.util
import io
import json
import os
import sqlite3
import ssl
import tempfile
import time
import traceback


def ms():
    return instancia.ms_desde_inicio_proceso()


def escribir(carpeta, nombre, datos):
    destino = os.path.join(os.environ['TEMP'], carpeta)
    os.makedirs(destino, exist_ok=True)
    with open(os.path.join(destino, nombre), 'w', encoding='utf-8') as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)


def cargar_hub(r):
    from creatorhub import config
    from creatorhub.interfaces import FABRICAS
    hechas, pendientes = 0, []
    for clave in FABRICAS:
        modulo, _, nombre = clave.rpartition('.')
        try:
            m = importlib.import_module(modulo)
        except ModuleNotFoundError as e:
            if e.name == modulo:                     # todavía no existe en el árbol (p. ej. creatorhub.hub, de hub-api)
                pendientes.append(modulo)
                continue
            raise
        getattr(m, nombre)
        hechas += 1
    r['fabricas'] = f'ok · {hechas} fábricas importadas' + (f' · pendientes: {", ".join(pendientes)}' if pendientes else '')
    v = json.loads((res.files('creatorhub') / 'version.json').read_text(encoding='utf-8'))['version']
    assert config.VERSION == v, (config.VERSION, v)
    r['version'] = f'ok · {v} desde creatorhub/version.json empaquetado'
    p = json.loads((res.files('creatorhub.local') / 'plantillas.json').read_text(encoding='utf-8'))
    r['plantillas'] = f"ok · {len(p['plantillas'])} plantillas"
    sql = (res.files('creatorhub.almacen') / 'schema.sql').read_text(encoding='utf-8')
    migs = sorted(x.name for x in (res.files('creatorhub.almacen') / 'migraciones').iterdir() if x.name.endswith('.sql'))
    con = sqlite3.connect(':memory:')
    con.executescript(sql)
    n = con.execute("select count(*) from sqlite_master where type='table'").fetchone()[0]
    con.close()
    r['esquema'] = f'ok · base nueva con {n} tablas · migraciones {migs}'


def autoprueba():
    r, t = {}, {'sonda': True, 't_main_ms': T_MAIN}

    def paso(nombre, f):
        try:
            v = f()
            if v is not None:
                r[nombre] = v
            elif nombre not in r:
                r[nombre] = 'ok'
        except Exception as e:                       # noqa: BLE001 - la sonda informa, no se cae (sin diálogos)
            r[nombre] = f'ERROR {type(e).__name__}: {e}'

    paso('hub', lambda: cargar_hub(r))
    t['t_import_ms'] = t['t_hub_listo_ms'] = ms()

    def version():
        from creatorhub import config
        t['version'] = config.VERSION                # build_windows.ps1 la compara con version.json
    paso('version_informe', version)

    def interfaz():
        base = os.path.join(sys._MEIPASS, 'ui')
        assert os.path.isfile(os.path.join(base, 'index.html')), 'falta ui/index.html'
        lic = json.load(open(os.path.join(base, 'licencias.json'), encoding='utf-8'))
        assert os.path.isfile(os.path.join(sys._MEIPASS, 'recursos', 'CreatorHub.ico')), 'falta recursos/CreatorHub.ico'
        return f"ok · ui/index.html · licencias.json con {len(lic['componentes'])} componentes · recursos/CreatorHub.ico"
    paso('interfaz', interfaz)

    def pillow():
        import PIL
        from PIL import Image
        b = io.BytesIO()
        Image.new('RGB', (8, 8), (200, 242, 60)).save(b, 'WEBP', quality=80)
        assert b.getvalue()[:4] == b'RIFF' and b.getvalue()[8:12] == b'WEBP'
        return f'ok · Pillow {PIL.__version__} empaquetado, codifica WebP'
    paso('pillow', pillow)

    def qr():
        import qrcode
        import qrcode.image.pure
        b = io.BytesIO()
        qrcode.make('creatorhub://pair?v=1', image_factory=qrcode.image.pure.PyPNGImage).save(b)
        assert b.getvalue()[:8] == b'\x89PNG\r\n\x1a\n'
        return 'ok · QR PNG con PyPNGImage'
    paso('qr', qr)

    t0 = time.perf_counter()

    def tls():
        from creatorhub.cripto import tls_cng
        cert, llave, clave, huella = tls_cng.generar_identidad()
        with tempfile.TemporaryDirectory() as d:
            rc, rk = os.path.join(d, 'c.pem'), os.path.join(d, 'k.pem')
            open(rc, 'wb').write(cert)
            open(rk, 'wb').write(llave)
            ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(rc, rk, password=clave)
        return f'ok · identidad CNG + load_cert_chain ({ssl.OPENSSL_VERSION})'
    paso('identidad_tls', tls)
    t['t_identidad_tls_ms'] = int((time.perf_counter() - t0) * 1000)

    t1 = time.perf_counter()

    def webview2():
        import webview
        import webview.platforms.edgechromium  # noqa: F401 (carga pythonnet y WebView2)
        return 'ok · pywebview + edgechromium (CLR)'
    paso('webview', webview2)
    t['t_edgechromium_ms'] = int((time.perf_counter() - t1) * 1000)

    def excluidos():
        presentes = [m for m in ('setuptools', 'pkg_resources', '_distutils_hack', 'PyInstaller', 'unittest', 'tkinter', 'pydoc')
                     if importlib.util.find_spec(m) is not None]
        assert not presentes, f'importables: {presentes}'
        return 'ok · sin setuptools, PyInstaller, unittest, tkinter ni pydoc'
    paso('excluidos', excluidos)
    t['comprobaciones'] = r
    t['t_total_ms'] = ms()
    escribir('CreatorHub-autoprueba', 'autoprueba.json', t)
    return 0 if not any(str(v).startswith('ERROR') for v in r.values()) else 3


def medir():
    r = {}
    cargar_hub(r)
    escribir('CreatorHub-medir', 'medicion.json', {'sonda': True, 't_hub_listo_ms': ms(), 't_ventana_ms': None, 't_pagina_ms': None})
    return 0


def principal():
    if '--salir' in sys.argv or '--desinstalar' in sys.argv:
        return instancia.pedir_salida()
    if '--autoprueba' in sys.argv:
        return autoprueba()
    if '--medir' in sys.argv:
        return medir()
    inst = instancia.tomar_instancia()
    if inst is None:
        return 0
    try:
        instancia.k32.WaitForSingleObject(inst.salir, 600000)
        time.sleep(2)                                # cierre ordenado simulado
    finally:
        inst.liberar()
    return 0


try:
    codigo = principal()
except BaseException:                                # noqa: BLE001 - sin consola: nunca un diálogo de error
    escribir('CreatorHub-autoprueba', 'sonda_error.json', {'error': traceback.format_exc()})
    codigo = 4
sys.exit(codigo)
'@
    EscribirUtf8SinBom (Join-Path $Arbol 'ui\dist\index.html') '<!doctype html><html lang="es-MX" data-theme="system"><head><meta charset="utf-8"><title>Corte</title><script src="/tema-inicial.js"></script><script type="module" src="/assets/index-prueba.js"></script><link rel="stylesheet" href="/assets/index-prueba.css"></head><body><div id="raiz"></div></body></html>'
    EscribirUtf8SinBom (Join-Path $Arbol 'ui\dist\tema-inicial.js') 'try{var t=localStorage.getItem("corte.tema");if(t)document.documentElement.dataset.theme=t}catch(e){}'
    EscribirUtf8SinBom (Join-Path $Arbol 'ui\dist\assets\index-prueba.js') 'document.getElementById("raiz").textContent="Corte";'
    EscribirUtf8SinBom (Join-Path $Arbol 'ui\dist\assets\index-prueba.css') 'body{margin:0}'
    Enlazar (Join-Path $Arbol '.venv-hub') (Join-Path $Raiz '.venv-hub')
    Enlazar (Join-Path $Arbol 'ui\node_modules') (Join-Path $Raiz 'ui\node_modules')

    $cronometro = [Diagnostics.Stopwatch]::StartNew()
    $r = CorrerPs (Join-Path $Arbol 'scripts\build_windows.ps1') @('-SinUI', '-SinRed')
    [IO.File]::WriteAllLines((Join-Path $Salida 'build_windows_salida.txt'), [string[]]$r.salida, (New-Object Text.UTF8Encoding $false))
    $zipHecho = @(Get-ChildItem (Join-Path $Arbol 'dist') -Filter 'CreatorHub-*-windows.zip' -ErrorAction SilentlyContinue)
    Comprobar ($r.codigo -eq 0 -and $zipHecho.Count -eq 1) ("build_windows.ps1 -SinUI -SinRed en verde en {0:N0} s (salida completa en build\pruebas_empaquetado\build_windows_salida.txt)" -f $cronometro.Elapsed.TotalSeconds) `
        "build_windows.ps1 salió con $($r.codigo): $(Ultimas $r 12)"
    foreach ($l in @($r.salida | Where-Object { $_ -match 'Guardia: OK|guardia_exe: OK|AVISO:|Arranque: main|Listo\. Carpeta|SHA-256|dependencias OK|generar_licencias: OK|render_iconos' })) { Anotar "     $l" }
    Comprobar (-not (@($r.salida) -match 'no trae «version»')) 'la autoprueba informa «version» y build_windows la comparó con version.json' 'build_windows avisó que el informe no trae «version»'
    $informe = Join-Path $env:TEMP 'CreatorHub-autoprueba\autoprueba.json'
    if (Test-Path $informe) {
        $inf = Get-Content $informe -Raw -Encoding UTF8 | ConvertFrom-Json
        $comp = $inf.comprobaciones
        $errores = @($comp.PSObject.Properties | Where-Object { "$($_.Value)" -like 'ERROR*' })
        Comprobar ($inf.sonda -and $errores.Count -eq 0) ("autoprueba (sonda) dentro del exe congelado: {0}" -f (($comp.PSObject.Properties | ForEach-Object { "$($_.Name): $($_.Value)" }) -join ' · ')) `
            "la sonda congelada reportó errores: $(($errores | ForEach-Object { "$($_.Name): $($_.Value)" }) -join ' · ')"
        Anotar ("     tiempos de la sonda (2.ª corrida): main {0} ms · hub listo {1} ms · TLS {2} ms · edgechromium {3} ms · total {4} ms" -f $inf.t_main_ms, $inf.t_hub_listo_ms, $inf.t_identidad_tls_ms, $inf.t_edgechromium_ms, $inf.t_total_ms)
    } else { Falla "la autoprueba no dejó $informe" }
    if (Test-Path (Join-Path $App 'CreatorHub.exe')) {
        $vi = (Get-Item (Join-Path $App 'CreatorHub.exe')).VersionInfo
        $vj = [string](Get-Content (Join-Path $Raiz 'version.json') -Raw | ConvertFrom-Json).version
        Comprobar ($vi.ProductName -eq 'Corte' -and $vi.FileDescription -eq 'Corte' -and $vi.ProductVersion -eq $vj -and $vi.OriginalFilename -eq 'CreatorHub.exe') `
            "VersionInfo del exe: ProductName «$($vi.ProductName)» · FileDescription «$($vi.FileDescription)» · versión $($vi.ProductVersion) · $($vi.OriginalFilename)" "VersionInfo incorrecto: $($vi.ProductName) $($vi.ProductVersion)"
        $datos = @('_internal\creatorhub\version.json', '_internal\creatorhub\almacen\schema.sql', '_internal\creatorhub\local\plantillas.json', '_internal\ui\index.html', '_internal\ui\licencias.json', '_internal\recursos\CreatorHub.ico')
        $faltan = @($datos | Where-Object { -not (Test-Path (Join-Path $App $_)) })
        $migs = @(Get-ChildItem (Join-Path $App '_internal\creatorhub\almacen\migraciones') -Filter *.sql -ErrorAction SilentlyContinue).Count
        $sueltos = @(Get-ChildItem (Join-Path $App '_internal\creatorhub') -Recurse -Include *.py, *.pyc -ErrorAction SilentlyContinue).Count
        Comprobar ($faltan.Count -eq 0 -and $migs -gt 0 -and $sueltos -eq 0) "datos en _internal: creatorhub\version.json, almacen\schema.sql + $migs migraciones, local\plantillas.json, ui\, recursos\CreatorHub.ico (sin .py sueltos)" "faltan datos: $($faltan -join ', ') · migraciones $migs · .py sueltos $sueltos"
        $mb = (Get-ChildItem $App -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
        Anotar ("     carpeta onedir: {0:N1} MB en {1} archivos" -f $mb, @(Get-ChildItem $App -Recurse -File).Count)
    }
}

# =========================================================================================== G
if ((Toca 'G') -and (Test-Path (Join-Path $App 'CreatorHub.exe'))) {
    Seccion 'G. Guardia del build'
    $sondaPyz = EscribirPy 'leer_pyz.py' @'
import json, sys
from PyInstaller.archive.readers import CArchiveReader
pkg = CArchiveReader(sys.argv[1])
pyz = pkg.open_embedded_archive(next(n for n, e in pkg.toc.items() if e[-1] == 'z'))
datos = pyz.extract(sys.argv[2], raw=True)
print(json.dumps({'existe': datos is not None, 'contiene': bool(datos) and sys.argv[3].encode() in datos}))
'@
    $j = (Capturar $Py @('-I', $sondaPyz, (Join-Path $App 'CreatorHub.exe'), 'creatorhub.demo.transporte', 'creador_demo')) | ConvertFrom-Json
    $r = CorrerPs (Join-Path $Raiz 'scripts\guardia_exe.ps1') @('-App', $App, '-Exigir', 'PIL,qrcode,png,webview,creatorhub')
    $avisoVisible = [bool](@($r.salida) -match '^AVISO: .*creatorhub\.demo\.transporte')
    if ($j.contiene) {
        Comprobar ($r.codigo -eq 0 -and $avisoVisible) "el exe de F (creatorhub real) pasa la guardia aunque creatorhub.demo.transporte SÍ trae «creador_demo» (excepción documentada, BUILD §6.3, informada con AVISO): $(Ultimas $r 3)" "exe de F: guardia $($r.codigo), AVISO $avisoVisible · $(Ultimas $r)"
    } else {
        Comprobar ($r.codigo -eq 0 -and -not $avisoVisible) "el exe de F (creatorhub real) pasa la guardia; creatorhub.demo.transporte ya no trae «creador_demo» (la excepción no se usó): $(Ultimas $r 2)" "exe de F: guardia $($r.codigo) · $(Ultimas $r)"
    }

    # Exe de prueba «sucio»: los marcadores dentro de módulos (PYZ, comprimidos con zlib)
    $Sucia = Join-Path $Tmp 'exe_sucio'
    $src = Join-Path $Sucia 'src'
    New-Item -ItemType Directory -Force (Join-Path $src 'creatorhub\demo') | Out-Null
    EscribirUtf8SinBom (Join-Path $src 'app_sucia.py') "import sys`nimport modulo_sucio, modulo_doble, creatorhub.demo.transporte, creatorhub.demo.otro`nsys.exit(0)`n"
    EscribirUtf8SinBom (Join-Path $src 'modulo_sucio.py') "USUARIO = 'creador_demo'`n"
    EscribirUtf8SinBom (Join-Path $src 'modulo_doble.py') "MARCA = '__DOBLE_CORTE__'`n"
    EscribirUtf8SinBom (Join-Path $src 'creatorhub\__init__.py') ''
    EscribirUtf8SinBom (Join-Path $src 'creatorhub\demo\__init__.py') ''
    EscribirUtf8SinBom (Join-Path $src 'creatorhub\demo\transporte.py') "USUARIO_DEMO = 'creador_demo'`n"
    EscribirUtf8SinBom (Join-Path $src 'creatorhub\demo\otro.py') "COPIA = 'creador_demo'`n"
    $r = CorrerNativo $Py @('-m', 'PyInstaller', '--noconfirm', '--clean', '--log-level', 'ERROR', '--onedir', '--windowed', '--name', 'CreatorHub',
        '--distpath', (Join-Path $Sucia 'dist'), '--workpath', (Join-Path $Sucia 'pyi'), '--specpath', (Join-Path $Sucia 'pyi'), '--paths', $src, (Join-Path $src 'app_sucia.py'))
    $Sucio = Join-Path $Sucia 'dist\CreatorHub'
    if ($r.codigo -ne 0 -or -not (Test-Path (Join-Path $Sucio 'CreatorHub.exe'))) { Falla "no se pudo compilar el exe sucio: $(Ultimas $r)" } else {
        $simple = @(Get-ChildItem $Sucio -Recurse -File | Where-Object { $bytes = [IO.File]::ReadAllBytes($_.FullName); $txt = [Text.Encoding]::GetEncoding(28591).GetString($bytes); $txt.Contains('creador_demo') -or $txt.Contains('__DOBLE_CORTE__') })
        Comprobar ($simple.Count -eq 0) 'en el exe sucio los marcadores NO se ven con una búsqueda simple de bytes (PyInstaller comprime cada módulo): por eso la guardia descomprime el PYZ' "una búsqueda simple sí los ve en: $(($simple | ForEach-Object Name) -join ', ')"
        $r = CorrerPs (Join-Path $Raiz 'scripts\guardia_exe.ps1') @('-App', $Sucio)
        $txt = ($r.salida -join "`n")
        Comprobar ($r.codigo -ne 0 -and $txt -match 'creador_demo.*modulo_sucio' -and $txt -match '__DOBLE_CORTE__.*modulo_doble') "guardia_exe.ps1 rechaza el exe de prueba con «creador_demo» y «__DOBLE_CORTE__» dentro de módulos (código $($r.codigo))" "la guardia NO rechazó el exe sucio (código $($r.codigo)): $(Ultimas $r)"
        $prohib = @($r.salida | Where-Object { $_ -like 'PROHIBIDO*' }) -join "`n"
        $avisoT = [bool](@($r.salida) -match '^AVISO: .*creatorhub\.demo\.transporte')
        Comprobar ($prohib -match 'creatorhub\.demo\.otro' -and $prohib -notmatch 'creatorhub\.demo\.transporte' -and $avisoT) 'la excepción es estrecha: creatorhub.demo.otro con «creador_demo» se rechaza; creatorhub.demo.transporte no, pero sale un AVISO' "excepción mal acotada (AVISO $avisoT): $($prohib -replace "`n", ' | ')"
    }

    # Mutaciones sobre una copia del exe limpio de F: cada una debe hacer fallar la guardia
    $Mutado = Join-Path $Tmp 'exe_mutado'
    $null = & robocopy $App $Mutado /E /NFL /NDL /NJH /NJS /NP
    $guardia = Join-Path $Raiz 'tools\guardia_exe.py'
    $base = CorrerNativo $Py @('-I', $guardia, $Mutado)
    Comprobar ($base.codigo -eq 0) "copia limpia del exe de F: guardia OK ($(Ultimas $base 1))" "la copia limpia no pasa: $(Ultimas $base)"
    $utf16 = [Text.Encoding]::Unicode.GetBytes('usuario: creador_demo')
    $casos = @(
        @{ n = '«__DOBLE_CORTE__» en un .js de la interfaz'; a = '_internal\ui\assets\doble.js'; t = '/* __DOBLE_CORTE__ */ export const x = 1;'; e = '__DOBLE_CORTE__'; ps = $true },
        @{ n = '«creador_demo» en un .js de la interfaz'; a = '_internal\ui\assets\demo.js'; t = 'export const u = "creador_demo";'; e = 'creador_demo'; ps = $true },
        @{ n = '«creador_demo» en UTF-16LE'; a = '_internal\notas.txt'; b = $utf16; e = 'creador_demo' },
        @{ n = 'mapa de código .map'; a = '_internal\ui\assets\index-prueba.js.map'; t = '{"version":3}'; e = 'archivo prohibido' },
        @{ n = 'carpeta fixtures'; a = '_internal\ui\fixtures\datos.json'; t = '{}'; e = 'ruta prohibida' },
        @{ n = 'research\datos-reales'; a = '_internal\research\datos-reales\perfil.json'; t = '{}'; e = 'ruta prohibida' },
        @{ n = 'spec\verificacion\ejemplos'; a = '_internal\spec\verificacion\ejemplos\health.json'; t = '{}'; e = 'ruta prohibida' },
        @{ n = 'config.json'; a = 'config.json'; t = '{}'; e = 'archivo prohibido' },
        @{ n = 'setuptools empaquetado'; a = '_internal\setuptools\__init__.py'; t = ''; e = 'debía excluirse' },
        @{ n = 'patrón de secreto'; a = '_internal\ui\assets\cfg.json'; t = '{"refresh_token": "abcdefgh12345"}'; e = 'posible secreto' },
        @{ n = '«creador_demo» comprimido dentro de un .zip'; a = '_internal\extra.zip'; zip = $true; e = 'creador_demo' }
    )
    foreach ($c in $casos) {
        $ruta = Join-Path $Mutado $c.a
        New-Item -ItemType Directory -Force (Split-Path -Parent $ruta) | Out-Null
        if ($c.ContainsKey('zip')) {
            Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
            $fs = [IO.File]::Open($ruta, 'Create'); $z = New-Object IO.Compression.ZipArchive($fs, [IO.Compression.ZipArchiveMode]::Create)
            $w = New-Object IO.StreamWriter($z.CreateEntry('dentro.txt', [IO.Compression.CompressionLevel]::Optimal).Open())
            $w.Write(('relleno ' * 200) + 'creador_demo'); $w.Dispose(); $z.Dispose(); $fs.Dispose()
        } elseif ($c.ContainsKey('b')) { [IO.File]::WriteAllBytes($ruta, $c.b) } else { EscribirUtf8SinBom $ruta $c.t }
        $j = Join-Path $Tmp 'guardia.json'
        $r = CorrerNativo $Py @('-I', $guardia, $Mutado, '--json', $j)
        $h = if (Test-Path $j) { (Get-Content $j -Raw -Encoding UTF8 | ConvertFrom-Json).hallazgos -join ' | ' } else { '' }
        $okPs = $true
        if ($c.ContainsKey('ps')) { $rp = CorrerPs (Join-Path $Raiz 'scripts\guardia_exe.ps1') @('-App', $Mutado); $okPs = $rp.codigo -ne 0 }
        Comprobar ($r.codigo -eq 1 -and $h -match [regex]::Escape($c.e) -and $okPs) ("rechaza {0}{1}: {2}" -f $c.n, $(if ($c.ContainsKey('ps')) { ' (también guardia_exe.ps1, la del paso 5)' } else { '' }), $h) "NO rechazó $($c.n) (código $($r.codigo)): $h"
        $quitar = switch -Wildcard ($c.a) {
            '_internal\ui\fixtures\*' { '_internal\ui\fixtures' }
            '_internal\setuptools\*'  { '_internal\setuptools' }
            '_internal\research\*'    { '_internal\research' }
            '_internal\spec\*'        { '_internal\spec' }
            default                   { $c.a }
        }
        Remove-Item -LiteralPath (Join-Path $Mutado $quitar) -Recurse -Force
    }
    # Datos privados (BUILD §11.6) con un perfil FALSO (nunca se copia la identidad real a ningún archivo de prueba)
    $perfilFalso = Join-Path $Tmp 'perfil_falso.json'
    $uFalso = 'usuario_privado_prueba_7f3a'; $oFalso = 'OPENID_PRIVADO_PRUEBA_0123456789'; $aFalso = 'https://p16-privado.example.com/obj/a/b.png'
    EscribirUtf8SinBom $perfilFalso ('{"code":0,"data":{"username":"' + $uFalso + '","creator_user_open_id":"' + $oFalso + '","avatar":{"url":"' + $aFalso + '"}}}')
    $casosPriv = @(
        @{ n = 'username real (con otras mayúsculas) en un .js'; a = '_internal\ui\assets\perfil.js'; t = ('export const u = "' + $uFalso.ToUpper() + '";'); campo = 'username' },
        @{ n = 'open_id real en UTF-16LE dentro de un binario'; a = '_internal\algo.bin'; b = [Text.Encoding]::Unicode.GetBytes("x$oFalso"); campo = 'creator_user_open_id' },
        @{ n = 'URL del avatar real en un .json'; a = '_internal\ui\avatar.json'; t = ('{"a":"' + $aFalso + '"}'); campo = 'avatar.url' }
    )
    foreach ($c in $casosPriv) {
        $ruta = Join-Path $Mutado $c.a
        if ($c.ContainsKey('b')) { [IO.File]::WriteAllBytes($ruta, $c.b) } else { EscribirUtf8SinBom $ruta $c.t }
        $j = Join-Path $Tmp 'guardia_priv.json'
        $r = CorrerNativo $Py @('-I', $guardia, $Mutado, '--perfil-privado', $perfilFalso, '--json', $j)
        $todo = ($r.salida -join "`n") + $(if (Test-Path $j) { [IO.File]::ReadAllText($j) } else { '' })
        $sinValor = -not ($todo.Contains($uFalso) -or $todo.Contains($uFalso.ToUpper()) -or $todo.Contains($oFalso) -or $todo.Contains($aFalso))
        Comprobar ($r.codigo -eq 1 -and $todo -match "dato privado de research/datos-reales \(campo $([regex]::Escape($c.campo))\)" -and $sinValor) `
            "rechaza $($c.n) y nombra el campo «$($c.campo)» sin mostrar el valor (perfil falso)" "NO rechazó $($c.n) o mostró el valor (código $($r.codigo), sin valor $sinValor): $(Ultimas $r 3)"
        Remove-Item -LiteralPath $ruta -Force
    }
    $r = CorrerNativo $Py @('-I', $guardia, $Mutado, '--perfil-privado', (Join-Path $Tmp 'no_existe.json'))
    Comprobar ($r.codigo -eq 0 -and (@($r.salida) -match '^AVISO: no existe research/datos-reales/perfil\.json')) 'sin perfil privado (otra PC) lo avisa y sigue' "sin perfil: código $($r.codigo) · $(Ultimas $r 2)"
    if (Test-Path (Join-Path $Raiz 'research\datos-reales\perfil.json')) {
        Comprobar ($base.codigo -eq 0 -and (($base.salida -join ' ') -match '3 campos privados buscados')) 'el exe de F no trae el username, el open_id ni la URL del avatar reales (perfil de research\datos-reales; solo se informan los campos)' "exe de F con datos privados o sin revisarlos: $(Ultimas $base 2)"
    }

    $fin = CorrerNativo $Py @('-I', $guardia, $Mutado)
    Comprobar ($fin.codigo -eq 0) 'al quitar cada mutación la copia vuelve a pasar' "la copia no volvió a pasar: $(Ultimas $fin)"
}

# =========================================================================================== H
if ((Toca 'H') -and (Test-Path (Join-Path $App 'CreatorHub.exe'))) {
    Seccion 'H. Instalar.ps1 y desinstalar.ps1 (desde el zip de F)'
    $zipF = @(Get-ChildItem (Join-Path $Tmp 'arbol\dist') -Filter 'CreatorHub-*-windows.zip')[0].FullName
    $ZipDir = Join-Path $Tmp 'zip'
    Expand-Archive -LiteralPath $zipF -DestinationPath $ZipDir
    $contenido = @(@('CreatorHub\CreatorHub.exe', 'CreatorHub\desinstalar.ps1', 'Instalar.ps1', 'Instalar Corte.cmd') | Where-Object { -not (Test-Path -LiteralPath (Join-Path $ZipDir $_)) })
    Comprobar ($contenido.Count -eq 0) "el zip trae CreatorHub\ (con desinstalar.ps1), Instalar.ps1 e «Instalar Corte.cmd»" "al zip le falta: $($contenido -join ', ')"
    if (-not $Tmp.StartsWith($env:LOCALAPPDATA + '\', [StringComparison]::OrdinalIgnoreCase)) { Falla "la prueba necesita que %TEMP% esté dentro de %LOCALAPPDATA% (guardia de desinstalar.ps1): $Tmp" } else {
        $destino = Join-Path $Tmp 'Programs\CreatorHub'
        $accesos = Join-Path $Tmp 'accesos'
        New-Item -ItemType Directory -Force $accesos | Out-Null
        $exe = Join-Path $destino 'CreatorHub.exe'
        $instalar = Join-Path $ZipDir 'Instalar.ps1'
        $argsI = @('-Destino', $destino, '-ClaveDesinstalar', $Clave, '-CarpetasAccesos', $accesos, '-SinAbrir')
        $r = CorrerPs $instalar $argsI
        $lnk = Join-Path $accesos 'Corte.lnk'
        Comprobar ($r.codigo -eq 0 -and (Test-Path $exe) -and (Test-Path (Join-Path $destino 'desinstalar.ps1')) -and (Test-Path $lnk)) 'instalación nueva: archivos, desinstalar.ps1 y el acceso «Corte.lnk»' "Instalar.ps1 salió con $($r.codigo): $(Ultimas $r)"
        if (Test-Path $lnk) {
            $csharp = [regex]::Match([IO.File]::ReadAllText($instalar), "(?s)@'\r?\n(.*?)\r?\n'@").Groups[1].Value
            if (-not ('CreatorHubAccesos' -as [type])) { Add-Type -TypeDefinition $csharp }
            $aumid = [CreatorHubAccesos]::LeerAumid($lnk)
            $aumidShell = [string](New-Object -ComObject Shell.Application).NameSpace($accesos).ParseName('Corte.lnk').ExtendedProperty('System.AppUserModel.ID')
            $d = Get-ItemProperty -LiteralPath $Clave
            Comprobar ($aumid -eq 'CreatorHub.App' -and $aumidShell -eq 'CreatorHub.App' -and $d.DisplayName -eq 'Corte' -and $d.DisplayVersion -eq '1.0.0' -and $d.InstallLocation -eq $destino -and $d.UninstallString -match 'desinstalar\.ps1') `
                "AUMID del acceso = $aumid (IPropertyStore) / $aumidShell (Shell) · entrada «$($d.DisplayName) $($d.DisplayVersion)» (versión leída del VersionInfo del exe)" "AUMID $aumid / $aumidShell · entrada $($d.DisplayName) $($d.DisplayVersion)"
        }
        # actualizar con la app abierta
        $p = Start-Process $exe -PassThru
        Start-Sleep -Seconds 3
        $bloqueado = $false
        try { [IO.File]::Open((Join-Path $destino '_internal\python312.dll'), 'Open', 'ReadWrite', 'None').Dispose() } catch { $bloqueado = $true }
        [IO.File]::WriteAllText((Join-Path $ZipDir 'CreatorHub\version2.txt'), 'nueva')
        $cronometro = [Diagnostics.Stopwatch]::StartNew()
        $r = CorrerPs $instalar $argsI
        $t = $cronometro.Elapsed.TotalSeconds
        Comprobar ($bloqueado -and $r.codigo -eq 0 -and $p.HasExited -and (Test-Path (Join-Path $destino 'version2.txt'))) ("actualización con la app abierta y python312.dll bloqueado: --salir esperó el cierre y robocopy copió en {0:N1} s" -f $t) "actualización: bloqueado $bloqueado · código $($r.codigo) · app cerrada $($p.HasExited)"
        # guardia de desinstalar.ps1
        $otra = Join-Path $Tmp 'NoEsCreatorHub'
        New-Item -ItemType Directory -Force $otra | Out-Null
        Copy-Item $exe $otra
        $claveMala = 'HKCU:\Software\CreatorHubPrueba\Uninstall\Mala'
        New-Item $claveMala -Force | Out-Null
        New-ItemProperty $claveMala -Name InstallLocation -Value $otra -Force | Out-Null
        $r = CorrerPs (Join-Path $destino 'desinstalar.ps1') @('-Clave', $claveMala, '-Silencioso')
        Comprobar ($r.codigo -eq 1 -and (Test-Path (Join-Path $otra 'CreatorHub.exe'))) 'desinstalar.ps1 no borra una carpeta que no se llama CreatorHub (código 1, carpeta intacta)' "la guardia de desinstalar no actuó (código $($r.codigo))"
        Remove-Item $claveMala -Recurse -Force
        # desinstalar con la app abierta, con la UninstallString registrada
        $p = Start-Process $exe -PassThru
        Start-Sleep -Seconds 3
        $cadena = [string](Get-ItemProperty -LiteralPath $Clave).UninstallString
        $cronometro.Restart()
        $u = Start-Process $PS -ArgumentList ($cadena.Substring(15) + ' -Silencioso') -PassThru -WindowStyle Hidden
        $null = $u.Handle
        $termino = $u.WaitForExit(90000)
        Comprobar ($termino -and $u.ExitCode -eq 0 -and -not (Test-Path $destino) -and -not (Test-Path $lnk) -and -not (Test-Path $Clave) -and $p.HasExited) `
            ("desinstalación con la app abierta: cerró la app y borró carpeta, acceso y entrada en {0:N1} s" -f $cronometro.Elapsed.TotalSeconds) "desinstalación: código $(if ($termino) { $u.ExitCode }) · carpeta $(Test-Path $destino) · acceso $(Test-Path $lnk) · clave $(Test-Path $Clave)"
    }
}

# =========================================================================================== I
if (Toca 'I') {
    Seccion 'I. dev.ps1 y medir_arranque.ps1'
    $ocupado = $false
    try { $c = New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1', 39229); $ocupado = $true; $c.Dispose() } catch { }
    if ($ocupado) { Anotar '[omitido] dev.ps1: el puerto 39229 está ocupado (otro hub abierto); no se prueba para no chocar' } else {
        $Dev = Join-Path $Tmp 'dev'
        New-Item -ItemType Directory -Force (Join-Path $Dev 'scripts'), (Join-Path $Dev 'hub\creatorhub') | Out-Null
        Copy-Item (Join-Path $Raiz 'scripts\dev.ps1'), (Join-Path $Raiz 'scripts\comun.ps1'), (Join-Path $Raiz 'scripts\comun_empaquetado.ps1'),
                  (Join-Path $Raiz 'scripts\comprobar_node_modules.mjs') (Join-Path $Dev 'scripts')
        Enlazar (Join-Path $Dev '.venv-hub') (Join-Path $Raiz '.venv-hub')
        EscribirUtf8SinBom (Join-Path $Dev 'hub\creatorhub\__init__.py') ''
        EscribirUtf8SinBom (Join-Path $Dev 'hub\creatorhub\__main__.py') @'
r"""Hub FALSO para probar scripts\dev.ps1: anota argv y carpeta, responde /api/health 4 s en 127.0.0.1:39229 y sale."""
import http.server, json, os, sys, threading
json.dump({'argv': sys.argv[1:], 'cwd': os.getcwd()}, open(os.environ['CH_DEV_REGISTRO'], 'w'))
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        cuerpo = b'{"ok": true}' if self.path == '/api/health' else b'{}'
        self.send_response(200 if self.path == '/api/health' else 404)
        self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(cuerpo)))
        self.end_headers(); self.wfile.write(cuerpo)
    def log_message(self, *a):
        pass
s = http.server.HTTPServer(('127.0.0.1', 39229), H)
threading.Timer(4, s.shutdown).start()
s.serve_forever()
s.server_close()
'@
        $registro = Join-Path $Tmp 'dev_registro.json'
        $env:CH_DEV_REGISTRO = $registro
        try { $r = CorrerPs (Join-Path $Dev 'scripts\dev.ps1') @('-SinVite', '-Ahora', '1794502800') } finally { Remove-Item Env:\CH_DEV_REGISTRO -ErrorAction SilentlyContinue }
        $reg = if (Test-Path $registro) { Get-Content $registro -Raw | ConvertFrom-Json } else { $null }
        $esperado = '--demo --dev --fuente fixtures_reales --ahora 1794502800'
        Comprobar ($r.codigo -eq 0 -and $null -ne $reg -and ($reg.argv -join ' ') -eq $esperado -and $reg.cwd -eq (Join-Path $Dev 'hub') -and (($r.salida -join ' ') -match 'Hub listo')) `
            "dev.ps1 -SinVite: corrió «python -m creatorhub $esperado» en hub\, esperó /api/health y terminó limpio" "dev.ps1: código $($r.codigo) · argv $(if ($reg) { $reg.argv -join ' ' }) · cwd $(if ($reg) { $reg.cwd }) · $(Ultimas $r)"
        QuitarEnlaces
    }
    if (Test-Path (Join-Path $App 'CreatorHub.exe')) {
        $r = CorrerPs (Join-Path $Raiz 'scripts\medir_arranque.ps1') @('-Exe', (Join-Path $App 'CreatorHub.exe'), '-Corridas', '2')
        $filas = @($r.salida | Where-Object { $_ -match '^\s*[12]\s+\d+' }).Count
        Comprobar ($r.codigo -eq 0 -and $filas -eq 2) 'medir_arranque.ps1 -Corridas 2 con la sonda (--medir): 2 filas y la mediana (plomería; las cifras reales salen del exe real)' "medir_arranque: código $($r.codigo), filas $filas · $(Ultimas $r)"
    }
}

# =========================================================================================== J
if (Toca 'J') {
    Seccion 'J. build_android.ps1 en una COPIA de android\ (-Tipo release -SinUI -SinDaemon, --offline, interfaz mínima)'
    $Andr = Join-Path $Tmp 'android_arbol'
    foreach ($d in 'scripts', 'tools', 'hub', 'ui\dist\assets') { New-Item -ItemType Directory -Force (Join-Path $Andr $d) | Out-Null }
    Copy-Item (Join-Path $Raiz 'version.json') $Andr
    Copy-Item (Join-Path $Raiz 'scripts\*') (Join-Path $Andr 'scripts')
    Copy-Item (Join-Path $Raiz 'tools\*') (Join-Path $Andr 'tools') -Recurse
    Copy-Item (Join-Path $Raiz 'hub\requirements.txt') (Join-Path $Andr 'hub')
    Copy-Item (Join-Path $Raiz 'ui\package.json'), (Join-Path $Raiz 'ui\package-lock.json') (Join-Path $Andr 'ui')
    $origenA = Join-Path $Raiz 'android'
    $null = & robocopy $origenA (Join-Path $Andr 'android') /E /XD (Join-Path $origenA 'build') (Join-Path $origenA 'app\build') (Join-Path $origenA '.gradle') (Join-Path $origenA 'app\src\main\assets\web') /XF local.properties firma_esperada.txt /NFL /NDL /NJH /NJS /NP
    if ($LASTEXITCODE -ge 8) { throw "robocopy de android falló ($LASTEXITCODE)" }
    EscribirUtf8SinBom (Join-Path $Andr 'ui\dist\index.html') '<!doctype html><html lang="es-MX"><head><meta charset="utf-8"><title>Corte</title><script type="module" src="/assets/index-prueba.js"></script></head><body><div id="raiz"></div></body></html>'
    EscribirUtf8SinBom (Join-Path $Andr 'ui\dist\assets\index-prueba.js') 'document.getElementById("raiz").textContent="Corte";'
    Enlazar (Join-Path $Andr '.venv-hub') (Join-Path $Raiz '.venv-hub')
    Enlazar (Join-Path $Andr 'ui\node_modules') (Join-Path $Raiz 'ui\node_modules')
    $cronometro = [Diagnostics.Stopwatch]::StartNew()
    $r = CorrerPs (Join-Path $Andr 'scripts\build_android.ps1') @('-Tipo', 'release', '-SinUI', '-SinDaemon')
    [IO.File]::WriteAllLines((Join-Path $Salida 'build_android_salida.txt'), [string[]]$r.salida, (New-Object Text.UTF8Encoding $false))
    $apk = Join-Path $Andr 'dist\CreatorHub-1.0.0.apk'
    Comprobar ($r.codigo -eq 0 -and (Test-Path $apk)) ("build_android.ps1 -Tipo release en verde en {0:N0} s: {1}" -f $cronometro.Elapsed.TotalSeconds, (@($r.salida | Where-Object { $_ -match 'APK listo' }) -join ' ')) "build_android.ps1 salió con $($r.codigo): $(Ultimas $r 12)"
    if (Test-Path $apk) {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $z = [IO.Compression.ZipFile]::OpenRead($apk)
        try {
            $nombres = @($z.Entries | ForEach-Object { $_.FullName })
            $licE = $z.Entries | Where-Object { $_.FullName -eq 'assets/web/licencias.json' } | Select-Object -First 1
            $origenes = @()
            if ($licE) { $lr = New-Object IO.StreamReader($licE.Open()); try { $origenes = @((($lr.ReadToEnd() | ConvertFrom-Json).componentes | ForEach-Object { $_.origen }) | Select-Object -Unique) } finally { $lr.Dispose() } }
        } finally { $z.Dispose() }
        Comprobar ($nombres -contains 'assets/web/index.html' -and $licE -and ($origenes -join ',') -eq 'interfaz') 'el APK trae assets/web/index.html y assets/web/licencias.json con solo la interfaz' "APK: index $($nombres -contains 'assets/web/index.html') · licencias $([bool]$licE) · orígenes $($origenes -join ',')"
        $huella = Join-Path $Andr 'android\firma_esperada.txt'
        Comprobar ((Test-Path $huella) -and ((Get-Content $huella -Raw).Trim() -match '^[0-9a-f]{64}$')) "firma de depuración estable: huella SHA-256 $((Get-Content $huella -Raw).Trim()) (en la copia; el android\ real no se tocó)" 'no quedó firma_esperada.txt con la huella'
        foreach ($l in @($r.salida | Where-Object { $_ -match 'BUILD SUCCESSFUL|Verificando|APK listo' })) { Anotar "     $l" }
    }

    # J2: -Tipo debug -UiDist <otra interfaz>, con CAMERA quitado del manifiesto DE LA COPIA: Gradle debe empaquetar esa
    # interfaz (-PchUiDist) y la verificación debe fallar por el permiso que falta (sin dejar el APK en dist\).
    $otraUi = Join-Path $Tmp 'ui_otra'
    New-Item -ItemType Directory -Force (Join-Path $otraUi 'assets') | Out-Null
    $marcaUi = 'interfaz-por-UiDist-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
    EscribirUtf8SinBom (Join-Path $otraUi 'index.html') ('<!doctype html><html lang="es-MX"><head><meta charset="utf-8"><title>Corte</title></head><body>' + $marcaUi + '</body></html>')
    $manifiesto = Join-Path $Andr 'android\app\src\main\AndroidManifest.xml'
    $txtManifiesto = [IO.File]::ReadAllText($manifiesto)
    $sinCamara = [regex]::Replace($txtManifiesto, '\s*<uses-permission android:name="android\.permission\.CAMERA"\s*/>', '')
    EscribirUtf8SinBom $manifiesto $sinCamara
    $cronometro = [Diagnostics.Stopwatch]::StartNew()
    $r = CorrerPs (Join-Path $Andr 'scripts\build_android.ps1') @('-Tipo', 'debug', '-UiDist', $otraUi, '-SinDaemon')
    [IO.File]::WriteAllLines((Join-Path $Salida 'build_android_uidist_salida.txt'), [string[]]$r.salida, (New-Object Text.UTF8Encoding $false))
    $apkD = Join-Path $Andr 'android\app\build\outputs\apk\debug\app-debug.apk'
    $indexD = ''
    if (Test-Path $apkD) {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $z = [IO.Compression.ZipFile]::OpenRead($apkD)
        try {
            $e = $z.Entries | Where-Object { $_.FullName -eq 'assets/web/index.html' } | Select-Object -First 1
            if ($e) { $lr = New-Object IO.StreamReader($e.Open()); try { $indexD = $lr.ReadToEnd() } finally { $lr.Dispose() } }
        } finally { $z.Dispose() }
    }
    $texto = $r.salida -join ' '
    Comprobar ($sinCamara -ne $txtManifiesto -and $r.codigo -ne 0 -and $texto -match 'Faltan permisos de BUILD .{0,8}7\.1: android\.permission\.CAMERA' -and
               $texto -match 'PchUiDist' -and $indexD.Contains($marcaUi) -and -not (Test-Path (Join-Path $otraUi 'licencias.json')) -and
               -not (Test-Path (Join-Path $Andr 'dist\CreatorHub-1.0.0-debug.apk'))) `
        ("-Tipo debug -UiDist: Gradle empaquetó la otra interfaz (assets/web/index.html con su marca), no escribió licencias.json en ella y la verificación falló por «Faltan permisos … CAMERA» sin dejar el APK en dist\ ({0:N0} s)" -f $cronometro.Elapsed.TotalSeconds) `
        "-UiDist/permisos: código $($r.codigo) · marca en el APK $($indexD.Contains($marcaUi)) · $(Ultimas $r 6)"

    # J3: manifiesto restaurado; un perfil privado FALSO en research\datos-reales de la copia y su username en la
    # interfaz de -UiDist: la verificación debe fallar nombrando el campo, sin mostrar el valor.
    EscribirUtf8SinBom $manifiesto $txtManifiesto
    $uFalsoA = 'usuario_privado_android_5c1e'
    New-Item -ItemType Directory -Force (Join-Path $Andr 'research\datos-reales') | Out-Null
    EscribirUtf8SinBom (Join-Path $Andr 'research\datos-reales\perfil.json') ('{"code":0,"data":{"username":"' + $uFalsoA + '","creator_user_open_id":"OPENID_FALSO_ANDROID_0123456789","avatar":{"url":"https://p16-privado.example.com/a.png"}}}')
    EscribirUtf8SinBom (Join-Path $otraUi 'index.html') ('<!doctype html><html lang="es-MX"><head><meta charset="utf-8"><title>Corte</title></head><body>Hola ' + $uFalsoA.ToUpper() + '</body></html>')
    $cronometro.Restart()
    $r = CorrerPs (Join-Path $Andr 'scripts\build_android.ps1') @('-Tipo', 'debug', '-UiDist', $otraUi, '-SinDaemon')
    $texto = $r.salida -join ' '
    Comprobar ($r.codigo -ne 0 -and $texto -match 'Dato privado de research.datos-reales \(campo username\) en assets/web/index\.html' -and
               -not $texto.Contains($uFalsoA) -and -not $texto.Contains($uFalsoA.ToUpper()) -and -not (Test-Path (Join-Path $Andr 'dist\CreatorHub-1.0.0-debug.apk'))) `
        ("el APK con el username del perfil privado (falso, otras mayúsculas) en assets/web se rechaza nombrando el campo, sin mostrar el valor ({0:N0} s)" -f $cronometro.Elapsed.TotalSeconds) `
        "privacidad en el APK: código $($r.codigo) · $(Ultimas $r 6)"
    QuitarEnlaces
}

# =========================================================================================== K
if (Toca 'K') {
    Seccion 'K. comprobar_node_modules.mjs y NodeModulesAlDia (ui\ falso; el ui\node_modules real no se toca)'
    $UiF = Join-Path $Tmp 'ui_falso'
    foreach ($d in 'node_modules\a', 'node_modules\@s\b', 'node_modules\.bin') { New-Item -ItemType Directory -Force (Join-Path $UiF $d) | Out-Null }
    EscribirUtf8SinBom (Join-Path $UiF 'package-lock.json') @'
{
  "name": "ui-falso", "version": "1.0.0", "lockfileVersion": 3, "requires": true,
  "packages": {
    "": { "name": "ui-falso", "version": "1.0.0", "dependencies": { "a": "1.0.0" }, "devDependencies": { "@s/b": "2.0.0" } },
    "node_modules/a": { "version": "1.0.0" },
    "node_modules/@s/b": { "version": "2.0.0", "dev": true },
    "node_modules/opcional-de-otra-plataforma": { "version": "3.0.0", "optional": true, "os": ["darwin"] }
  }
}
'@
    $pjA = Join-Path $UiF 'node_modules\a\package.json'
    $pjB = Join-Path $UiF 'node_modules\@s\b\package.json'
    EscribirUtf8SinBom $pjA '{"name":"a","version":"1.0.0"}'
    EscribirUtf8SinBom $pjB '{"name":"@s/b","version":"2.0.0"}'
    $comprobar = Join-Path $Raiz 'scripts\comprobar_node_modules.mjs'
    $r = CorrerNativo $Node @($comprobar, $UiF)
    Comprobar ($r.codigo -eq 0) "comprobar_node_modules: node_modules = lock (el opcional de otra plataforma se omite, .bin se ignora) -> 0 · $(Ultimas $r 1)" "comprobar_node_modules dio $($r.codigo): $(Ultimas $r)"

    $hashF = (Get-FileHash -LiteralPath (Join-Path $UiF 'package-lock.json') -Algorithm SHA256).Hash
    $marcaF = Join-Path $UiF 'node_modules\.ch-lock.sha256'
    $orden = ". '$(Join-Path $Raiz 'scripts\comun.ps1')'; . '$(Join-Path $Raiz 'scripts\comun_empaquetado.ps1')'; NodeModulesAlDia '$UiF'"
    $r1 = CorrerNativo $PS @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $orden)
    $t1 = $r1.salida -join ' | '
    $marcaOk = (Test-Path $marcaF) -and ((Get-Content $marcaF -Raw).Trim() -eq $hashF)
    Comprobar ($r1.codigo -eq 0 -and $marcaOk -and $t1 -match 'se adopta la marca sin npm ci' -and $t1 -match 'node_modules al día con package-lock\.json' -and $t1 -notmatch 'Falló') `
        'NodeModulesAlDia: como node_modules ya coincide, adopta la marca (= SHA-256 del lock) y AsegurarNodeModules no corre npm ci' "NodeModulesAlDia: código $($r1.codigo) · marca $marcaOk · $t1"
    $r2 = CorrerNativo $PS @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $orden)
    $t2 = $r2.salida -join ' | '
    Comprobar ($r2.codigo -eq 0 -and $t2 -notmatch 'comprobar_node_modules' -and $t2 -match 'node_modules al día') 'con la marca vigente ni siquiera vuelve a comprobar' "2.ª corrida: código $($r2.codigo) · $t2"

    $negativas = @(
        @{ n = 'versión distinta'; antes = { EscribirUtf8SinBom $pjA '{"name":"a","version":"1.0.1"}' }; despues = { EscribirUtf8SinBom $pjA '{"name":"a","version":"1.0.0"}' }; e = 'node_modules/a: instalado 1\.0\.1, lock 1\.0\.0'; c = 1 },
        @{ n = 'paquete faltante'; antes = { Remove-Item -LiteralPath $pjB -Force }; despues = { EscribirUtf8SinBom $pjB '{"name":"@s/b","version":"2.0.0"}' }; e = 'falta node_modules/@s/b'; c = 1 },
        @{ n = 'paquete de más'; antes = { New-Item -ItemType Directory -Force (Join-Path $UiF 'node_modules\zzz') | Out-Null; EscribirUtf8SinBom (Join-Path $UiF 'node_modules\zzz\package.json') '{"version":"9.9.9"}' }; despues = { Remove-Item -LiteralPath (Join-Path $UiF 'node_modules\zzz') -Recurse -Force }; e = 'sobra node_modules/zzz'; c = 1 },
        @{ n = 'sin package-lock.json'; antes = { Rename-Item -LiteralPath (Join-Path $UiF 'package-lock.json') 'lock.bak' }; despues = { Rename-Item -LiteralPath (Join-Path $UiF 'lock.bak') 'package-lock.json' }; e = 'falta .*package-lock\.json'; c = 2 }
    )
    foreach ($neg in $negativas) {
        & $neg.antes
        $r = CorrerNativo $Node @($comprobar, $UiF)
        & $neg.despues
        Comprobar ($r.codigo -eq $neg.c -and (Ultimas $r) -match $neg.e) "comprobar_node_modules detecta $($neg.n) -> código $($r.codigo) · $(Ultimas $r 1)" "comprobar_node_modules con $($neg.n): código $($r.codigo) · $(Ultimas $r)"
    }
    $r = CorrerNativo $Node @($comprobar, $UiF)
    Comprobar ($r.codigo -eq 0) 'al deshacer cada cambio vuelve a coincidir' "no volvió a coincidir: $(Ultimas $r)"
}
} catch {
    Falla "error inesperado: $($_.Exception.Message) ($($_.InvocationInfo.PositionMessage))"
} finally {
    Get-Process -Name 'CreatorHub' -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($Tmp, [StringComparison]::OrdinalIgnoreCase) } | Stop-Process -Force -ErrorAction SilentlyContinue
    if (Test-Path 'HKCU:\Software\CreatorHubPrueba') { Remove-Item 'HKCU:\Software\CreatorHubPrueba' -Recurse -Force }
    QuitarEnlaces
    if (-not (Test-Path (Join-Path $Raiz '.venv-hub\Scripts\python.exe')) -or -not (Test-Path (Join-Path $Raiz 'ui\node_modules\react\package.json'))) {
        Falla 'ALERTA: .venv-hub o ui\node_modules ya no están completos tras quitar los enlaces'
    } elseif (-not $Conservar -and (Test-Path $Tmp)) {
        # rmdir /s no entra en los enlaces de directorio (si quedara alguno, solo quita el enlace): nunca borra .venv-hub
        $previo = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        & cmd.exe /d /c rmdir /s /q "$Tmp" 2>&1 | Out-Null
        $ErrorActionPreference = $previo
    }
    Anotar ''
    Anotar $(if ($script:fallas -eq 0) { 'probar_empaquetado: TODO OK' } else { "probar_empaquetado: $($script:fallas) FALLAS" })
    [IO.File]::WriteAllLines((Join-Path $Salida 'resultado.txt'), $script:res, (New-Object Text.UTF8Encoding $false))
}
exit $(if ($script:fallas -eq 0) { 0 } else { 1 })
