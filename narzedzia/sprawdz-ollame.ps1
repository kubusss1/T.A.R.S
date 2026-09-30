# TARS: sprawdza Ollame i dociaga brakujace modele Qwen na dysk F.
# Uruchom: powershell -ExecutionPolicy Bypass -File narzedzia\sprawdz-ollame.ps1
$ErrorActionPreference = "Continue"
$F = "F:\ollama\models"
$models = @("qwen3.5:9b", "qwen3.5:4b", "qwen3.5:2b")

New-Item -ItemType Directory -Force $F | Out-Null
if ([Environment]::GetEnvironmentVariable("OLLAMA_MODELS", "User") -ne $F) {
    setx OLLAMA_MODELS $F | Out-Null
    Write-Host "Ustawiono OLLAMA_MODELS = $F" -ForegroundColor Yellow
}
$env:OLLAMA_MODELS = $F

try {
    Invoke-RestMethod "http://localhost:11434/api/tags" -TimeoutSec 5 | Out-Null
} catch {
    Write-Host "Ollama nie dziala - uruchamiam..." -ForegroundColor Yellow
    Start-Process "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe"
    Start-Sleep 8
}

$installed = (Invoke-RestMethod "http://localhost:11434/api/tags").models.name
foreach ($m in $models) {
    if ($installed -contains $m) {
        Write-Host "OK      $m" -ForegroundColor Green
    } else {
        Write-Host "POBIERAM $m" -ForegroundColor Yellow
        ollama pull $m
    }
}

Write-Host "`nModele:" ; ollama list
"{0:N1} GB na F" -f ((Get-ChildItem $F -Recurse -File | Measure-Object Length -Sum).Sum / 1GB)
