# Obrenna dev launcher — starts the Tauri desktop app in dev mode.
# Usage: .\dev.ps1

$ErrorActionPreference = "Stop"

Write-Host "Starting Obrenna desktop dev mode..." -ForegroundColor Cyan

$env:OBRENNA_TRACE_LOGS = "1"
$env:OBRENNA_LOG_LEVEL = "DEBUG"
Write-Host "Full orchestrator trace logging enabled (OBRENNA_TRACE_LOGS=1)." -ForegroundColor Yellow

# Run tauri from the root so it finds src-tauri, but use the CLI from the frontend folder
npm exec --prefix frontend tauri dev
