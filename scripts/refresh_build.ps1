# Rebuild the committed web app at .\build (the copy serve.* and the backend
# serve to npm-less machines). Run after frontend changes, then commit .\build.
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
$FE = 'frontend\Ragnarok_default'

Push-Location $FE
if (-not (Test-Path 'node_modules')) { npm install --no-audit --no-fund }
$env:GENERATE_SOURCEMAP = 'false'
npm run build
if ($LASTEXITCODE -ne 0) { Pop-Location; throw 'Web build failed.' }
Pop-Location

if (Test-Path '.\build') { Remove-Item -Recurse -Force '.\build' }
Copy-Item -Recurse (Join-Path $FE 'build') '.\build'
Write-Host 'Refreshed .\build - commit it to update the deployed web app.'
