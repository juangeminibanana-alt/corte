[CmdletBinding()]
param([string]$Flutter = 'flutter', [switch]$NoPub)
$ErrorActionPreference = 'Stop'
$clientRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $clientRoot
try {
    $arguments = @('--no-version-check', 'build', 'windows', '--release')
    if ($NoPub) { $arguments += '--no-pub' }
    & $Flutter @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Flutter Windows build failed.' }
    $release = (Resolve-Path -LiteralPath (Join-Path $clientRoot 'build\windows\x64\runner\Release')).Path
    $binary = Join-Path $release 'CreatorHub.exe'
    if (-not (Test-Path -LiteralPath $binary)) { throw 'Missing CreatorHub.exe from the native Flutter runner.' }
    # Ship the app-local Microsoft CRT so this ZIP does not require a Visual Studio install.
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path -LiteralPath $vswhere)) { throw 'Missing Visual Studio redistributable discovery tool.' }
    $vsRoot = (& $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath | Select-Object -First 1)
    if (-not $vsRoot) { throw 'No Visual Studio C++ installation found for the app-local runtime.' }
    $redist = Get-ChildItem -LiteralPath (Join-Path $vsRoot 'VC\Redist\MSVC') -Directory |
        Where-Object { $_.Name -match '^\d+\.\d+\.\d+$' } | Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1
    if (-not $redist) { throw 'Missing Microsoft C++ redistributable directory.' }
    $crt = Get-ChildItem -LiteralPath (Join-Path $redist.FullName 'x64') -Directory |
        Where-Object Name -Match '^Microsoft\.VC\d+\.CRT$' | Select-Object -First 1
    if (-not $crt) { throw 'Missing x64 Microsoft C++ runtime.' }
    Get-ChildItem -LiteralPath $crt.FullName -Filter '*.dll' -File | Copy-Item -Destination $release
    foreach ($dependency in @('flutter_windows.dll', 'data\flutter_assets', 'msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll')) {
        if (-not (Test-Path -LiteralPath (Join-Path $release $dependency))) { throw "Missing native runtime: $dependency" }
    }
    $forbidden = Get-ChildItem -LiteralPath $release -Recurse -File | Where-Object {
        $_.Name -match '\.(sqlite|dpapi|keystore|jks|pem)$' -or $_.FullName -match '[\\/](descargas|downloads|secretos)[\\/]'
    }
    if ($forbidden) { throw 'Private data or unrelated downloads appeared in the release folder.' }
    $artifacts = Join-Path $clientRoot 'build\artifacts'
    New-Item -ItemType Directory -Path $artifacts -Force | Out-Null
    $zip = Join-Path $artifacts 'Corte-Flutter-Windows-x64.zip'
    if (Test-Path -LiteralPath $zip) { throw 'Artifact already exists. Preserve it and choose a fresh build directory.' }
    Compress-Archive -Path (Join-Path $release '*') -DestinationPath $zip -CompressionLevel Optimal
    $toolchain = Get-Content -LiteralPath (Join-Path $clientRoot 'toolchain.lock.json') -Raw | ConvertFrom-Json
    $versionLine = Select-String -LiteralPath (Join-Path $clientRoot 'pubspec.yaml') -Pattern '^version:\s*(.+)$'
    $proof = [ordered]@{
        platform = 'windows-x64'
        version = $versionLine.Matches[0].Groups[1].Value.Trim()
        source_commit = $env:GITHUB_SHA
        flutter_commit = $toolchain.flutter_commit
        binary = 'CreatorHub.exe'
        native_icon_sha256 = (Get-FileHash -LiteralPath (Join-Path $clientRoot 'windows\runner\resources\app_icon.ico') -Algorithm SHA256).Hash
        exe_sha256 = (Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash
        zip_sha256 = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash
        zip_bytes = (Get-Item -LiteralPath $zip).Length
        app_local_crt = @('msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll')
    }
    $proof | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $artifacts 'windows-proof.json') -Encoding utf8
    Write-Output ($proof | ConvertTo-Json -Compress)
} finally { Pop-Location }
