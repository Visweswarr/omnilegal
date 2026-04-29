param(
    [string]$Python = ".venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$VenvPath = Join-Path $RepoRoot ".venv-gliner"

if (-not (Test-Path (Join-Path $RepoRoot $Python))) {
    $ResolvedPython = "python"
} else {
    $ResolvedPython = Join-Path $RepoRoot $Python
}

if (-not (Test-Path $VenvPath)) {
    & $ResolvedPython -m venv $VenvPath
}

$GlinerPython = Join-Path $VenvPath "Scripts\python.exe"
& $GlinerPython -m pip install --upgrade pip
& $GlinerPython -m pip install "gliner==0.2.26" "transformers>=4.42,<5" "torch" "onnxruntime" "sentencepiece" "huggingface-hub"

$Smoke = @'
from gliner import GLiNER
print("gliner_ok")
'@
$Smoke | & $GlinerPython -

Write-Host "GLiNER environment ready at $VenvPath"
Write-Host "Smoke test:"
$Payload = '{"text":"Corfu Channel and Article 51 of the UN Charter","labels":["ICJ case","treaty article","treaty"],"threshold":0.3}'
$Payload | & $GlinerPython (Join-Path $RepoRoot "scripts\gliner_worker.py")
