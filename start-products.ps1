param(
    [string]$PythonPath,
    [switch]$Offline,
    [switch]$SavedCase,
    [switch]$NoBrowser,
    [switch]$Check,
    [ValidateSet('codex_cli','openai_api')][string]$Provider = 'codex_cli',
    [string]$DataDir,
    [int]$CopilotPort = 8857,
    [int]$CareflowPort = 8858
)
$ErrorActionPreference = 'Stop'
if (-not $PythonPath) {
    $candidates = @(
        (Join-Path $PSScriptRoot '.venv/Scripts/python.exe')
    )
    $PythonPath = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if (-not $PythonPath) { $PythonPath = (Get-Command python -ErrorAction Stop).Source }
}
$launchArgs = @((Join-Path $PSScriptRoot 'tools/serve_products.py'))
$launchArgs += @('--provider', $Provider)
if ($Offline) { $launchArgs += '--offline' }
if ($SavedCase) { $launchArgs += '--saved-case' }
if ($NoBrowser) { $launchArgs += '--no-browser' }
if ($Check) { $launchArgs += '--check' }
if ($DataDir) { $launchArgs += @('--data-dir', $DataDir) }
$launchArgs += @('--copilot-port', $CopilotPort, '--careflow-port', $CareflowPort)
& $PythonPath @launchArgs
exit $LASTEXITCODE
