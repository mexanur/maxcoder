# MaxCoder v2 — Windows launcher
# Starts backend in a new window, then launches the Gradio UI here.

$backend = Start-Process powershell -PassThru -ArgumentList `
    "-NoExit", "-Command", `
    "cd '$PSScriptRoot\..'; .venv\Scripts\activate; uvicorn server.app:app --host 127.0.0.1 --port 8000"

Write-Host "Waiting for backend..."
Start-Sleep -Seconds 3

Set-Location "$PSScriptRoot\.."
.venv\Scripts\activate
python ui\gradio_app.py

Stop-Process -Id $backend.Id -ErrorAction SilentlyContinue
