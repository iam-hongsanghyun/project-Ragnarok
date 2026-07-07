# Build the CLIMADA worker's PROJECT-LOCAL conda env on Windows (.\.climada-env).
#
# Windows counterpart of scripts/setup_climada_worker.sh — same contract:
# the physical-risk worker (backend/physical_risk_worker/) needs CLIMADA's
# conda-forge geospatial stack (Python 3.11 / GDAL / PROJ / older numpy+pandas),
# which cannot share an interpreter with .venv-pypsa and is not pip-installable.
# It is built as a PREFIX env inside the repo — never a global/named env.
# Ragnarok auto-detects it: worker.py looks for <env>\python.exe on Windows.
# See docs/physical-risk-worker.md.
#
# Usage (PowerShell):
#   powershell -ExecutionPolicy Bypass -File scripts\setup_climada_worker.ps1
#   $env:RAGNAROK_CLIMADA_WORKER_ENV = "D:\envs\climada"; ...  # optional override
# Or double-click scripts\setup_climada_worker.bat, which bootstraps this file.

$ErrorActionPreference = "Stop"

$Repo = Split-Path -Parent $PSScriptRoot
$EnvDir = if ($env:RAGNAROK_CLIMADA_WORKER_ENV) { $env:RAGNAROK_CLIMADA_WORKER_ENV } else { Join-Path $Repo ".climada-env" }
$EnvYml = Join-Path $Repo "backend\physical_risk_worker\env_climada.yml"

if (-not (Test-Path $EnvYml)) {
    Write-Error "env spec not found: $EnvYml (run from a full pypsa_gui checkout)"
    exit 1
}

# Prefer mamba (much faster solver), fall back to conda.
$Solver = $null
foreach ($candidate in @("mamba", "conda")) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) { $Solver = $candidate; break }
}
if (-not $Solver) {
    Write-Host "error: neither conda nor mamba found on PATH." -ForegroundColor Red
    Write-Host "Install Miniforge (https://conda-forge.org/download/) and re-run this script"
    Write-Host "from the 'Miniforge Prompt', or add conda to PATH first."
    exit 1
}

$WorkerPython = Join-Path $EnvDir "python.exe"

if (Test-Path $WorkerPython) {
    Write-Host "worker env already exists at $EnvDir - updating from env_climada.yml"
    & $Solver env update -f $EnvYml --prefix $EnvDir
} else {
    Write-Host "creating the CLIMADA worker env at $EnvDir (this downloads ~2 GB, be patient)"
    & $Solver env create -f $EnvYml --prefix $EnvDir
}
if ($LASTEXITCODE -ne 0) {
    Write-Error "$Solver env create/update failed (exit $LASTEXITCODE)"
    exit $LASTEXITCODE
}

Write-Host "sanity check: importing climada in the worker env..."
& $WorkerPython -c "import climada, importlib.metadata as m; print('climada ok:', m.version('climada'), '| petals:', m.version('climada_petals'))"
if ($LASTEXITCODE -ne 0) {
    Write-Error "climada import failed in $EnvDir"
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Done. Ragnarok auto-detects the env (RAGNAROK_CLIMADA_WORKER defaults to 'auto');"
Write-Host "restart the backend and physical-risk runs will use the real CLIMADA worker."
Write-Host "Seed offline hazard data with: $WorkerPython scripts\physical_risk_build_hazard.py list"
