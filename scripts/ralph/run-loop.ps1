#!/usr/bin/env pwsh
# Ralph loop via droid exec with MiniMax-M2.1
# Each iteration gets fresh context and picks the next story

$ErrorActionPreference = "Continue"
$maxIters = 100
$model = "custom:MiniMax-M2.1"
$cwd = (Get-Location).Path
$prdPath = Join-Path $cwd "scripts/ralph/prd.json"

for ($i = 1; $i -le $maxIters; $i++) {
    Write-Host "`n========== ITERATION $i / $maxIters ==========" -ForegroundColor Cyan

    # Check if all stories pass
    $prd = Get-Content $prdPath -Raw | ConvertFrom-Json
    $remaining = ($prd.userStories | Where-Object { -not $_.passes }).Count
    if ($remaining -eq 0) {
        Write-Host "ALL STORIES PASS - COMPLETE" -ForegroundColor Green
        break
    }
    Write-Host "Remaining stories: $remaining" -ForegroundColor Yellow

    # Run droid exec with fresh context
    $prompt = Get-Content (Join-Path $cwd "scripts/ralph/prompt.md") -Raw
    Write-Host "Launching droid exec with MiniMax-M2.1..." -ForegroundColor Magenta

    droid exec --model $model --auto medium --cwd $cwd $prompt 2>&1 | Tee-Object -Variable output

    $exitCode = $LASTEXITCODE
    Write-Host "`nDroid exit code: $exitCode" -ForegroundColor $(if ($exitCode -eq 0) { "Green" } else { "Red" })

    # Run verification
    Write-Host "`n--- Verification ---" -ForegroundColor Cyan
    python -m pytest tests/ -v 2>&1
    python -m consurg --help 2>&1

    Write-Host "`n--- End of iteration $i ---" -ForegroundColor Cyan
}

# Final summary
$prd = Get-Content $prdPath -Raw | ConvertFrom-Json
$passed = ($prd.userStories | Where-Object { $_.passes }).Count
$total = $prd.userStories.Count
Write-Host "`n========== FINAL: $passed / $total stories passed ==========" -ForegroundColor $(if ($passed -eq $total) { "Green" } else { "Yellow" })
