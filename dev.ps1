# Obrenna dev launcher — starts backend (FastAPI) and frontend (Vite) concurrently.
# Usage: .\dev.ps1

$ErrorActionPreference = "Stop"

Write-Host "Starting Obrenna in dev mode..." -ForegroundColor Cyan

# Start backend
$backend = Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "cd '$PSScriptRoot\backend'; python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000"
) -PassThru

# Start frontend
$frontend = Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "cd '$PSScriptRoot\frontend'; npm run dev"
) -PassThru

Write-Host ""
Write-Host "  Backend  -> http://localhost:8000" -ForegroundColor Green
Write-Host "  Frontend -> http://localhost:5173" -ForegroundColor Green
Write-Host ""
Write-Host "Close the two terminal windows to stop both servers." -ForegroundColor Yellow
