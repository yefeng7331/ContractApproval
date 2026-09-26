# Project-local CPU OCR runtime. Run only after dependency/model installation approval.
param([string]$UvExecutable = 'uv')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot '.tools\ocr\python'
$env:UV_CACHE_DIR = Join-Path $projectRoot 'storage\ocr\uv-cache'
$env:UV_SYSTEM_CERTS = 'true'
$basePython = Join-Path $env:UV_PYTHON_INSTALL_DIR 'cpython-3.12.13-windows-x86_64-none\python.exe'
$runtime = Join-Path $projectRoot '.tools\ocr\venv'
$python = Join-Path $runtime 'Scripts\python.exe'

if (-not (Test-Path -LiteralPath $basePython)) {
    & $UvExecutable python install 3.12.13 --no-bin --no-registry
    if ($LASTEXITCODE -ne 0) { throw 'OCR Python download failed' }
}
if (-not (Test-Path -LiteralPath $python)) {
    & $UvExecutable venv $runtime --python $basePython
    if ($LASTEXITCODE -ne 0) { throw 'OCR virtual environment creation failed' }
}
& $UvExecutable pip install --python $python --index-url https://pypi.org/simple -r (Join-Path $PSScriptRoot 'requirements-ocr-lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'OCR dependency installation failed' }
& $python -X utf8 (Join-Path $PSScriptRoot 'verify_ocr.py')
if ($LASTEXITCODE -ne 0) { throw 'OCR model preparation or real sample verification failed' }
Write-Output "OcrPython=$python"
