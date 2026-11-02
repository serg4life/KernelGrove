# Empaqueta en un instalador `.exe` el `dist\kernelgrove\` que deja `build.ps1`.
#
# El equivalente de `packaging/linux/build_deb.sh`: sin paso de compilacion,
# solo el envoltorio. Necesita Inno Setup 6.1 o posterior (`ISCC.exe`).
#
# Las URL de `dtc` y del preprocesador se inyectan desde el entorno, no viven
# en el `.iss` (ahi son placeholders vacios). Sin ellas el instalador se
# compila igual y sale sin el componente de herramientas:
#
#   $env:KERNELGROVE_TOOLS_DTC_URL    = 'https://.../dtc-1.7.0-win64.zip'
#   $env:KERNELGROVE_TOOLS_DTC_SHA256 = '...'
#   $env:KERNELGROVE_TOOLS_CPP_URL    = 'https://.../clang-win64.zip'
#   $env:KERNELGROVE_TOOLS_CPP_SHA256 = '...'
#   .\packaging\windows\build_installer.ps1
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $repoRoot

if (-not (Test-Path 'dist\kernelgrove\kernelgrove.exe')) {
    Write-Host "No hay ejecutable en dist\kernelgrove. Construyelo antes con:"
    Write-Host "  .\packaging\windows\build.ps1"
    exit 1
}

# Misma fuente de verdad que el `.deb` y que el `.spec`: `pyproject.toml`.
$version = (Select-String -Path pyproject.toml -Pattern '^version = "(.+)"' `
    | Select-Object -First 1).Matches.Groups[1].Value

$iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    $iscc = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
}
if (-not (Test-Path $iscc)) {
    Write-Host "No se encuentra ISCC.exe (Inno Setup 6). Instalalo con:"
    Write-Host "  winget install --id JRSoftware.InnoSetup"
    exit 1
}

$defines = @("/DAppVersion=$version")
$pares = @(
    @('ToolsDtcUrl',    $env:KERNELGROVE_TOOLS_DTC_URL),
    @('ToolsDtcSha256', $env:KERNELGROVE_TOOLS_DTC_SHA256),
    @('ToolsCppUrl',    $env:KERNELGROVE_TOOLS_CPP_URL),
    @('ToolsCppSha256', $env:KERNELGROVE_TOOLS_CPP_SHA256)
)
foreach ($par in $pares) {
    if ($par[1]) { $defines += "/D$($par[0])=$($par[1])" }
}
if (-not $env:KERNELGROVE_TOOLS_DTC_URL -or -not $env:KERNELGROVE_TOOLS_CPP_URL) {
    Write-Host "Aviso: sin URL de herramientas; el instalador saldra sin el"
    Write-Host "componente de dtc/cpp (ver packaging\windows\README.md)."
}

& $iscc @defines packaging\windows\kernelgrove.iss
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Instalador en dist\kernelgrove-$version-win64-setup.exe"
