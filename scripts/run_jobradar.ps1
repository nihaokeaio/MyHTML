param(
    [string]$PythonPath = "",
    [string]$StateDirectory = ""
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $PythonPath) { $PythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe' }
if (-not $StateDirectory) { $StateDirectory = Join-Path $projectRoot '.jobradar-state' }
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw "Python not found: $PythonPath" }
New-Item -ItemType Directory -Path $StateDirectory -Force | Out-Null
$logFile = Join-Path $StateDirectory ("run-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + ".jsonl")
# No scheduler, service, credential storage, Git commit or Git push.
& $PythonPath (Join-Path $PSScriptRoot 'run_jobradar.py') --state-dir $StateDirectory 2>&1 | Tee-Object -FilePath $logFile
$batchExit = $LASTEXITCODE
Write-Output "JobRadar exit=$batchExit; log=$logFile"
exit $batchExit
