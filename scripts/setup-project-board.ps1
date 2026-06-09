# setup-project-board.ps1
# Creates the "Job-Batch Roadmap" GitHub Project (v2) and adds all open issues.
#
# Prereq: token needs the 'project' scope. Run this once first:
#   gh auth refresh -s project
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\scripts\setup-project-board.ps1

$ErrorActionPreference = "Continue"
$repo = "NavyaTejaBoddu/Job-Batch"
$owner = "NavyaTejaBoddu"
$boardTitle = "Job-Batch Roadmap"

# Verify auth has the right scope
$scopes = gh auth status 2>&1 | Select-String "Token scopes"
if ($scopes -notmatch "project") {
  Write-Host "Token is missing the 'project' scope." -ForegroundColor Red
  Write-Host "Run this first, then re-run this script:" -ForegroundColor Yellow
  Write-Host "  gh auth refresh -s project" -ForegroundColor Cyan
  exit 1
}

Write-Host ""
Write-Host "=== Creating project board ===" -ForegroundColor Cyan
$created = gh project create --owner $owner --title $boardTitle --format json 2>&1
if ($LASTEXITCODE -ne 0) {
  Write-Host "Project creation failed (may already exist). Trying to find it..." -ForegroundColor DarkGray
  $list = gh project list --owner $owner --format json 2>&1 | ConvertFrom-Json
  $existing = $list.projects | Where-Object { $_.title -eq $boardTitle } | Select-Object -First 1
  if ($null -eq $existing) {
    Write-Host "Could not create or find a board titled '$boardTitle'." -ForegroundColor Red
    Write-Host $created
    exit 1
  }
  $projectNumber = $existing.number
  Write-Host ("  . Reusing existing board #" + $projectNumber)
} else {
  $projectNumber = ($created | ConvertFrom-Json).number
  Write-Host ("  + Created board #" + $projectNumber + ": " + $boardTitle) -ForegroundColor Green
}

Write-Host ""
Write-Host "=== Adding open issues ===" -ForegroundColor Cyan
$issues = gh issue list --repo $repo --state open --limit 100 --json number,title,url | ConvertFrom-Json
foreach ($i in $issues) {
  $out = gh project item-add $projectNumber --owner $owner --url $i.url 2>&1
  if ($LASTEXITCODE -eq 0) {
    Write-Host ("  + #" + $i.number + " " + $i.title) -ForegroundColor Green
  } else {
    Write-Host ("  . #" + $i.number + " (already on board or failed)") -ForegroundColor DarkGray
  }
}

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Cyan
Write-Host ("View board: https://github.com/users/" + $owner + "/projects/" + $projectNumber) -ForegroundColor Yellow
