"""Start the Giveaway Tracker app with Streamlit"""
param(
  [string]$Dir = "."
)

$Root = (Resolve-Path -Path $Dir).ProviderPath

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  Write-Host "Python is not installed or not in PATH." -ForegroundColor Red
  Read-Host "Press Enter to exit"
  exit 1
}

$AppFile = Join-Path -Path $Root -ChildPath "app.py"
if (-not (Test-Path $AppFile)) {
  Write-Host "app.py not found in $Root" -ForegroundColor Red
  Read-Host "Press Enter to exit"
  exit 1
}

Write-Host "Starting Giveaway Tracker..." -ForegroundColor Green
Set-Location $Root
python -m streamlit run app.py
