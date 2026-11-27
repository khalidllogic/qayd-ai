$ErrorActionPreference = "Stop"
Write-Host "=== Starting Qayd AI Server & Frontend ===" -ForegroundColor Cyan

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & .\setup.ps1
}

$url = "http://127.0.0.1:8000"
Write-Host "Opening browser at: $url" -ForegroundColor Green
Start-Process $url
& .\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload