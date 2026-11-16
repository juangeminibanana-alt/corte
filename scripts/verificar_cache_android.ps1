[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$raizCache=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$fuenteCache=Join-Path $raizCache 'android\pruebas\cache_proxy'
$salidaCache=Join-Path $raizCache 'android\build\pruebas-cache'
$jdkCache='D:\android-toolchain\jdk-17.0.19+10\bin'
New-Item -ItemType Directory -Force -Path $salidaCache | Out-Null
$archivosCache=@(Get-ChildItem -LiteralPath $fuenteCache -Recurse -Filter '*.java' -File | ForEach-Object FullName)
$archivosCache+=Join-Path $raizCache 'android\app\src\main\java\app\creatorhub\web\ProxyHub.java'
$politicaCache=Join-Path $raizCache 'android\app\src\main\java\app\creatorhub\red\PoliticaCacheImagenes.java'
if(Test-Path -LiteralPath $politicaCache){$archivosCache+=$politicaCache}
& (Join-Path $jdkCache 'javac.exe') --release 17 -encoding UTF-8 -d $salidaCache @archivosCache
if($LASTEXITCODE -ne 0){throw 'No compilo el harness de ProxyHub.'}
& (Join-Path $jdkCache 'java.exe') -cp $salidaCache app.creatorhub.web.PruebaProxyImagenes
if($LASTEXITCODE -ne 0){throw 'Regresiones de cache detectadas en ProxyHub.'}
