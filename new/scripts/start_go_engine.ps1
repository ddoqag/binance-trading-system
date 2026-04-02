# PowerShell script to start Go HFT Engine with HTTP and Metrics
# Usage: .\start_go_engine.ps1 [symbol] [paper|live] [margin]

param(
    [string]$Symbol = "btcusdt",
    [string]$Mode = "paper",  # paper or live
    [switch]$Margin
)

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  P10 Go Engine Launcher" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Check if we're in the right directory
if (-not (Test-Path "core_go\engine.go")) {
    Write-Error "Please run this script from the project root directory"
    exit 1
}

# Build Go engine if needed
Write-Host "[1] Building Go Engine..." -ForegroundColor Yellow
cd core_go

$buildArgs = @("build", "-o", "hft_engine_http.exe", "main_with_http.go", "*.go")
$buildArgs = $buildArgs | Where-Object { $_ -ne "main.go" -and $_ -ne "main_with_http.go" }

# Build all Go files except main.go (we use main_with_http.go)
go build -o hft_engine_http.exe main_with_http.go

if ($LASTEXITCODE -ne 0) {
    Write-Error "Build failed!"
    exit 1
}

Write-Host "      [OK] Build successful" -ForegroundColor Green

# Prepare arguments
$modeArg = if ($Mode -eq "live") { "live" } else { "paper" }
$marginArg = if ($Margin) { "margin" } else { "" }

Write-Host ""
Write-Host "[2] Configuration:" -ForegroundColor Yellow
Write-Host "      Symbol: $Symbol"
Write-Host "      Mode: $Mode"
Write-Host "      Margin: $(if ($Margin) { 'Yes' } else { 'No' })"
Write-Host ""

Write-Host "[3] Starting Go Engine..." -ForegroundColor Yellow
Write-Host "      HTTP API: http://localhost:8080" -ForegroundColor Gray
Write-Host "      Metrics:  http://localhost:9090/metrics" -ForegroundColor Gray
Write-Host ""

# Start the engine
.\hft_engine_http.exe $Symbol $modeArg $marginArg
