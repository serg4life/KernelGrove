# Construye el ejecutable de KernelGrove para Windows (--onedir) con PyInstaller.
#
# El equivalente de `packaging/linux/build.sh`. No incluye `bindings.db` ni
# `db_manager` — ver `kernelgrove.spec`. El resultado queda en `dist\kernelgrove\`.
#
#   .\packaging\windows\build.ps1
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $repoRoot

python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "PyInstaller no esta instalado. Instalalo con:"
    Write-Host "  pip install -e '.[packaging]'"
    exit 1
}

pyinstaller packaging\windows\kernelgrove.spec `
    --distpath dist `
    --workpath build `
    --noconfirm
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Construido en dist\kernelgrove\. Probar con:"
Write-Host "  `$env:KERNELGROVE_DB_PATH='C:\ruta\a\bindings.db'; .\dist\kernelgrove\kernelgrove.exe"
Write-Host "Y para el instalador:  .\packaging\windows\build_installer.ps1"
