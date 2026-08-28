# Baize Agent — Windows One-Click PowerShell Installer
# Usage: irm https://raw.githubusercontent.com/jianjian12138/baize-agent/main/install/install.ps1 | iex
$ErrorActionPreference = "Stop"

Write-Host @"
  ██████╗  █████╗ ██╗███████╗███████╗
  ██╔══██╗██╔══██╗██║╚══███╔╝██╔════╝
  ██████╔╝███████║██║  ███╔╝ █████╗  
  ██╔══██╗██╔══██╗██║ ███╔╝  ██╔══╝  
  ██████╔╝██║  ██║██║███████╗███████╗
  ╚═════╝ ╚═╝  ╚═╝╚═╝╚══════╝╚══════╝
  Baize Agent Autonomous Engine — Windows Installer
"@ -ForegroundColor Cyan

# Locate Python >= 3.10
$pyBin = $null
foreach ($cmd in @("py", "python", "python3")) {
    try {
        $verStr = & $cmd -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>$null
        if ($verStr) {
            $parts = $verStr.Trim().Split(".")
            if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 10) {
                $pyBin = $cmd
                break
            }
        }
    } catch {}
}

if (-not $pyBin) {
    Write-Host "[ERROR] Python 3.10 or newer is required." -ForegroundColor Red
    Write-Host "Install Python 3.10+ from python.org or via 'winget install Python.Python.3.12' and retry."
    exit 1
}

Write-Host "✓ Found compatible Python ($pyBin)" -ForegroundColor Green

$scriptPath = $MyInvocation.MyCommand.Path
if ($scriptPath -and (Test-Path "$PSScriptRoot\bootstrap.py")) {
    $rootDir = Resolve-Path "$PSScriptRoot\.."
    Set-Location $rootDir
    & $pyBin install\bootstrap.py $args
} else {
    $targetDir = if ($env:BAIZE_HOME) { $env:BAIZE_HOME } else { "$HOME\.baize-agent" }
    Write-Host "Deploying Baize Agent to $targetDir..." -ForegroundColor Yellow
    if (Get-Command git -ErrorAction SilentlyContinue) {
        if (Test-Path $targetDir) {
            Set-Location $targetDir
            git pull --ff-only
        } else {
            git clone --depth=1 https://github.com/jianjian12138/baize-agent.git $targetDir
        }
    } else {
        if (-not (Test-Path $targetDir)) { New-Item -ItemType Directory -Path $targetDir -Force | Out-Null }
        $zipUrl = "https://github.com/jianjian12138/baize-agent/archive/refs/heads/main.zip"
        $zipFile = "$env:TEMP\baize-main.zip"
        Invoke-WebRequest -Uri $zipUrl -OutFile $zipFile
        Expand-Archive -Path $zipFile -DestinationPath "$env:TEMP\baize-extract" -Force
        Copy-Item -Path "$env:TEMP\baize-extract\baize-agent-main\*" -Destination $targetDir -Recurse -Force
        Remove-Item -Recurse -Force "$env:TEMP\baize-extract", $zipFile
    }
    Set-Location $targetDir
    & $pyBin install\bootstrap.py $args
}
