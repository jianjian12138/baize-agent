# Baize Agent Studio PowerShell Launcher
$Host.UI.RawUI.WindowTitle = "Baize Agent Studio - 白泽智能桌面工作台"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Definition)
Set-Location $RepoRoot

Write-Host "===================================================" -ForegroundColor Cyan
Write-Host "  Baize Agent Studio - 白泽智能桌面工作台 (V33.0.0)" -ForegroundColor Green
Write-Host "  正在唤起沉浸式桌面客户端..." -ForegroundColor Yellow
Write-Host "===================================================" -ForegroundColor Cyan

python -m baize desktop
