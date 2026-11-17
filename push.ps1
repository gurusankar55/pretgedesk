# PreTGE Desk - upload to GitHub and turn on GitHub Pages.
# Usage (in D:\PreTGEDesk):
#   powershell -ExecutionPolicy Bypass -File .\push.ps1
#   powershell -ExecutionPolicy Bypass -File .\push.ps1 -Demo 0xDEMO... -Production 0xPROD...
param(
  [string]$Demo = "",
  [string]$Production = "",
  [string]$Message = "PreTGE Desk update"
)
$ErrorActionPreference = "Continue"
$Repo = "gurusankar55/pretgedesk"
Set-Location -Path $PSScriptRoot

function Test-Addr($a) { return $a -match '^0x[0-9a-fA-F]{40}$' }

# 1. contract addresses -> docs/config.js
if ($Demo -ne "" -or $Production -ne "") {
  $cfgPath = Join-Path $PSScriptRoot "docs\config.js"
  $cfg = Get-Content $cfgPath -Raw
  if ($Demo -ne "") {
    if (-not (Test-Addr $Demo)) { Write-Host "Demo address is not 0x + 40 hex" -ForegroundColor Red; exit 1 }
    $cfg = [regex]::Replace($cfg, 'demo: "[^"]*"', ('demo: "' + $Demo + '"'))
  }
  if ($Production -ne "") {
    if (-not (Test-Addr $Production)) { Write-Host "Production address is not 0x + 40 hex" -ForegroundColor Red; exit 1 }
    $cfg = [regex]::Replace($cfg, 'production: "[^"]*"', ('production: "' + $Production + '"'))
  }
  Set-Content -Path $cfgPath -Value $cfg -NoNewline -Encoding UTF8
  Write-Host "config.js updated" -ForegroundColor Green
}

# 2. git commit
if (-not (Test-Path ".git")) { git init | Out-Null; git symbolic-ref HEAD refs/heads/main }
git add -A
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) { git commit -m $Message | Out-Null; Write-Host "Committed: $Message" -ForegroundColor Green }
else { Write-Host "Nothing new to commit" }
git branch -M main

# 3. push (creates the repo with GitHub CLI if it is installed)
$hasGh = $null -ne (Get-Command gh -ErrorAction SilentlyContinue)
$hasRemote = (git remote) -contains "origin"
if ($hasGh) {
  gh repo view $Repo 2>$null | Out-Null
  if ($LASTEXITCODE -ne 0) {
    gh repo create $Repo --public --description "PreTGE Desk: pre-market escrow on GenLayer" | Out-Null
    Write-Host "Created repo $Repo" -ForegroundColor Green
  }
}
if (-not $hasRemote) { git remote add origin ("https://github.com/" + $Repo + ".git") }
git push -u origin main
if ($LASTEXITCODE -ne 0) {
  Write-Host "Push failed. If the repo does not exist yet, create an EMPTY public repo named 'pretgedesk' on github.com, then run this script again." -ForegroundColor Yellow
  exit 1
}

# 4. GitHub Pages from /docs
if ($hasGh) {
  gh api -X POST "repos/$Repo/pages" -f "source[branch]=main" -f "source[path]=/docs" 2>$null | Out-Null
  if ($LASTEXITCODE -eq 0) { Write-Host "GitHub Pages turned on (main /docs)" -ForegroundColor Green }
  else { Write-Host "GitHub Pages already on (or turn it on: Settings > Pages > main /docs)" }
} else {
  Write-Host "Turn on Pages once: github.com/$Repo > Settings > Pages > Branch: main, folder: /docs" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "Repo: https://github.com/$Repo" -ForegroundColor Cyan
Write-Host "Site: https://gurusankar55.github.io/pretgedesk/ (ready in 1-2 minutes)" -ForegroundColor Cyan
