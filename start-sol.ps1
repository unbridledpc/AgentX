<# 
start-sol.ps1
Launch Sol stack: API backend + Desktop (Tauri) + SolWeb (Vite) + optional tests.

Usage:
  powershell -ExecutionPolicy Bypass -File .\start-sol.ps1
  powershell -ExecutionPolicy Bypass -File .\start-sol.ps1 -RunTests
  powershell -ExecutionPolicy Bypass -File .\start-sol.ps1 -RunTests -NoDesktop
#>

param(
  [string]$RepoRoot = $PSScriptRoot,
  [switch]$RunTests,
  [switch]$NoApi,
  [switch]$NoDesktop,
  [switch]$NoWeb,
  [switch]$NoSolv2Tests
)

function Get-ApiPythonCommand {
  param(
    [Parameter(Mandatory=$true)][string]$RepoRoot
  )

  $apiDir = Join-Path $RepoRoot "apps\api"
  $venvPython = Join-Path $apiDir ".venv\Scripts\python.exe"

  if (Test-Path $venvPython) {
    return "& '$venvPython' -m sol_api"
  }

  return "python -m sol_api"
}

function New-RunnerWindow {
  param(
    [Parameter(Mandatory=$true)][string]$Title,
    [Parameter(Mandatory=$true)][string]$WorkDir,
    [Parameter(Mandatory=$true)][string]$Command
  )

  if (-not (Test-Path $WorkDir)) {
    Write-Host "Skipping $Title (missing dir): $WorkDir" -ForegroundColor Yellow
    return
  }

  $ps = @"
`$Host.UI.RawUI.WindowTitle = '$Title'
Set-Location -LiteralPath '$WorkDir'
Write-Host '[$Title] Working dir: ' (Get-Location) -ForegroundColor Cyan
Write-Host '[$Title] Command: $Command' -ForegroundColor Cyan
$Command
"@

  Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy", "Bypass",
    "-Command", $ps
  ) | Out-Null
}

Write-Host "RepoRoot: $RepoRoot" -ForegroundColor Green
if (-not (Test-Path $RepoRoot)) {
  throw "Repo root not found: $RepoRoot"
}

# Optional tests (run in their own window so they don't block launch)
if ($RunTests) {
  New-RunnerWindow -Title "Sol Tests (Repo Root)" -WorkDir $RepoRoot -Command "python -m pytest -q"
  if (-not $NoSolv2Tests) {
    New-RunnerWindow -Title "SolVersion2 Tests" -WorkDir (Join-Path $RepoRoot "SolVersion2") -Command "python -m pytest -q"
  }
}

# API backend
if (-not $NoApi) {
  $apiCommand = Get-ApiPythonCommand -RepoRoot $RepoRoot
  New-RunnerWindow -Title "Sol API Backend" -WorkDir (Join-Path $RepoRoot "apps\api") -Command $apiCommand
}

# Desktop (Tauri)
#if (-not $NoDesktop) {
#  New-RunnerWindow -Title "Sol Desktop (Tauri Dev)" -WorkDir (Join-Path $RepoRoot "apps\desktop") -Command "npm exec tauri dev"
#}

# SolWeb (Vite)
if (-not $NoWeb) {
  New-RunnerWindow -Title "SolWeb (Dev)" -WorkDir (Join-Path $RepoRoot "SolWeb") -Command "npm run dev"
}

Write-Host "`nLaunched requested services. Close any window to stop that service." -ForegroundColor Green
Write-Host "Tip: re-run with -RunTests to open test windows." -ForegroundColor DarkGray
