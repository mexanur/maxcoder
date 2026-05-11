# MaxCoder v2 — one-shot Windows setup
Set-Location "$PSScriptRoot\.."

Write-Host "1/5  Pulling Ollama models..." -ForegroundColor Cyan
ollama pull qwen2.5-coder:3b
ollama pull qwen2.5-coder:7b

Write-Host "2/5  Creating MaxCoder personas..." -ForegroundColor Cyan
ollama create maxcoder-fast -f Modelfile.fast
ollama create maxcoder      -f Modelfile

Write-Host "3/5  Creating Python venv..." -ForegroundColor Cyan
py -3.11 -m venv .venv
.venv\Scripts\activate

Write-Host "4/5  Installing Python deps..." -ForegroundColor Cyan
pip install --upgrade pip
pip install -r requirements.txt

Write-Host "5/5  Creating workspace dirs..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path workspace, rag\indexes, memory_store, sandbox | Out-Null

Write-Host ""
Write-Host "✅  Setup complete! Run:  .\scripts\run_all.ps1" -ForegroundColor Green
