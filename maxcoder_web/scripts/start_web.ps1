# Start MaxCoder web UI
# Run from: D:\Web app\maxcoder_v2\

Set-Location "$PSScriptRoot\.."

# Start FastAPI backend in new window
Start-Process powershell -ArgumentList `
  "-NoExit", "-Command", `
  "cd '$PSScriptRoot\..'; .venv\Scripts\activate; uvicorn server.app:app --host 127.0.0.1 --port 8000"

Start-Sleep -Seconds 2

# Start React frontend
Set-Location "$PSScriptRoot\..\maxcoder_web"
npm run dev
