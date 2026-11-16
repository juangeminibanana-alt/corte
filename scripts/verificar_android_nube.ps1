[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$raizPrueba = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$javaPrueba = 'D:\android-toolchain\jdk-17.0.19+10\bin'
$salidaPrueba = Join-Path $raizPrueba 'android\build\pruebas-nube'
New-Item -ItemType Directory -Force -Path $salidaPrueba | Out-Null
$fuentesPrueba=@('SeguridadNube.java','PoliticaCacheImagenes.java','ControlPrecargaImagenes.java') | ForEach-Object { Join-Path $raizPrueba ('android\app\src\main\java\app\creatorhub\red\' + $_) }
$fuentesPrueba+=Join-Path $raizPrueba 'android\pruebas\PruebaSeguridadNube.java'
& (Join-Path $javaPrueba 'javac.exe') --release 17 -encoding UTF-8 -d $salidaPrueba @fuentesPrueba
if ($LASTEXITCODE -ne 0) { throw 'No se compilaron las pruebas nativas.' }
& (Join-Path $javaPrueba 'java.exe') -cp $salidaPrueba PruebaSeguridadNube
if ($LASTEXITCODE -ne 0) { throw 'Falló una comprobación del canal nativo.' }
