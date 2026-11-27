$ErrorActionPreference = "Stop"
Write-Host "=== Qayd AI System Setup ===" -ForegroundColor Cyan

if (-not (Test-Path ".venv")) {
    Write-Host "[1/4] Creating virtual environment (.venv)..." -ForegroundColor Yellow
    python -m venv .venv
}

Write-Host "[2/4] Installing dependencies..." -ForegroundColor Yellow
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}

$envContent = Get-Content ".env" -Raw
if ($envContent -match "YOUR_API_KEY") {
    Write-Host "[Notice] GEMINI_API_KEY is not set in .env yet." -ForegroundColor Magenta
    $userKey = Read-Host "Enter your GEMINI_API_KEY now (or press Enter to skip)"
    if (-not [string]::IsNullOrWhiteSpace($userKey)) {
        $envContent = $envContent -replace "YOUR_API_KEY", $userKey.Trim()
        Set-Content -Path ".env" -Value $envContent -Encoding UTF8
        Write-Host "API key saved successfully!" -ForegroundColor Green
    }
}

Write-Host "[4/4] Running integration tests..." -ForegroundColor Yellow
& .\.venv\Scripts\python.exe -m pytest -v
