$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv-windows\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -c 'import sys; assert (3, 10) <= sys.version_info[:2] < (3, 15)'
        if ($LASTEXITCODE -ne 0) { throw 'Please install Python 3.10-3.14 (64-bit), or use the portable ZIP.' }
        & py -3 -m venv (Join-Path $root '.venv-windows')
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -c 'import sys; assert (3, 10) <= sys.version_info[:2] < (3, 15)'
        if ($LASTEXITCODE -ne 0) { throw 'Please install Python 3.10-3.14 (64-bit), or use the portable ZIP.' }
        & python -m venv (Join-Path $root '.venv-windows')
    } else {
        throw 'Please install Python 3.10-3.14 (64-bit), or use the portable ZIP; the ZIP needs no setup.'
    }
    if ($LASTEXITCODE -ne 0) { throw 'Unable to create the local Python environment.' }
}
& $python -m pip install --disable-pip-version-check 'PySide6-Essentials==6.12.0' 'Pillow>=12,<14'
if ($LASTEXITCODE -ne 0) { throw 'Dependency download failed. Please try again.' }
Write-Output 'Ready. Double-click Codex launcher in this folder.'
