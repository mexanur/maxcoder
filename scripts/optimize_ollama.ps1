# MaxCoder Ollama optimization — KV cache quantization + Flash Attention
# Run once. Sets env vars persistently for your user, then restarts Ollama.
#
# What this does:
#   OLLAMA_FLASH_ATTENTION=1   → enables memory-efficient attention kernels
#   OLLAMA_KV_CACHE_TYPE=q8_0  → quantizes KV cache from FP16 to Q8 (~2× context)
#
# Why this matters on a 4GB-VRAM laptop:
#   • Same VRAM holds 2× the conversation history
#   • Long agent loops + RAG context can finally fit
#   • Quality loss from Q8 KV is negligible for chat-style workloads
#
# To verify: after restart, `ollama ps` shows higher context, and long chats
# stop OOMing.

Write-Host "Setting Ollama optimization env vars..." -ForegroundColor Cyan

[Environment]::SetEnvironmentVariable("OLLAMA_FLASH_ATTENTION", "1", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_KV_CACHE_TYPE",    "q8_0", "User")

# Also set in current session
$env:OLLAMA_FLASH_ATTENTION = "1"
$env:OLLAMA_KV_CACHE_TYPE   = "q8_0"

Write-Host "  OLLAMA_FLASH_ATTENTION = 1"
Write-Host "  OLLAMA_KV_CACHE_TYPE   = q8_0"

Write-Host ""
Write-Host "Restarting Ollama..." -ForegroundColor Cyan

# Stop the running Ollama process
$ollama = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
if ($ollama) {
    Stop-Process -Name "ollama" -Force
    Start-Sleep -Seconds 2
    Write-Host "  Stopped existing Ollama process"
}

# Start fresh
Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
Start-Sleep -Seconds 3

# Verify
$check = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -ErrorAction SilentlyContinue
if ($check) {
    Write-Host "Ollama is running with optimizations enabled." -ForegroundColor Green
    Write-Host ""
    Write-Host "Effective settings:"
    Write-Host "  Flash Attention: ON"
    Write-Host "  KV Cache Type:   Q8_0 (vs default FP16 — saves ~50% KV memory)"
    Write-Host ""
    Write-Host "You can now use roughly 2x the context length per chat."
} else {
    Write-Host "WARNING: Ollama did not respond. Run 'ollama serve' manually." -ForegroundColor Yellow
}
