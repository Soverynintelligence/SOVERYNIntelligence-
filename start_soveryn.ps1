# SOVERYN Auto-Startup Script
# PowerShell version - more trusted by Windows

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "SOVERYN - Starting Autonomous AI System" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# Start ComfyUI in new window
Write-Host "Starting ComfyUI..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd 'C:\Users\jonde\Downloads\soveryn_vision_crew\ComfyUI'; python main.py" -WindowStyle Normal

# Wait for ComfyUI to initialize
Write-Host "Waiting for ComfyUI to initialize..." -ForegroundColor Yellow
Start-Sleep -Seconds 5

# Start SOVERYN in new window
Write-Host "Starting SOVERYN..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd 'C:\Users\jonde\Downloads\soveryn_vision_crew'; python app.py" -WindowStyle Normal

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "SOVERYN is starting..." -ForegroundColor Cyan
Write-Host "ComfyUI: http://127.0.0.1:8188" -ForegroundColor Green
Write-Host "SOVERYN: http://127.0.0.1:5000" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press any key to close this launcher..." -ForegroundColor Yellow
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
