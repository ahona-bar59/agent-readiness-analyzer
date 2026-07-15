<#
.SYNOPSIS
    One-click ARA report generator: scores agents and opens the HTML reports.

.DESCRIPTION
    Runs the Agent Readiness Analyzer over one or more agent README/spec files,
    writes JSON + Markdown + HTML into the reports folder, then opens each HTML
    report in your default browser (Ctrl+P -> Save as PDF to get a PDF).

.PARAMETER Input
    File(s) or glob(s) to analyze. Default: every .md in examples\.

.PARAMETER Out
    Output directory for reports. Default: reports.

.PARAMETER NoOpen
    Generate reports but do not open them in the browser.

.EXAMPLE
    .\make-reports.ps1
    Scores all example agents and opens their reports.

.EXAMPLE
    .\make-reports.ps1 -Input "C:\path\to\my-agent.md"
    Scores one specific agent.
#>
param(
    [string[]]$Input = @("examples/*.md"),
    [string]$Out = "reports",
    [switch]$NoOpen
)

# Always run from the folder this script lives in.
Set-Location -Path $PSScriptRoot

Write-Host "Agent Readiness Analyzer - generating reports..." -ForegroundColor Cyan
Write-Host ""

# Run ARA (all formats: JSON + Markdown + HTML).
python -m ara analyze --input $Input --format all --out $Out
$verdictCode = $LASTEXITCODE

Write-Host ""
if (-not $NoOpen) {
    $htmlReports = Get-ChildItem -Path (Join-Path $Out "*.report.html") -ErrorAction SilentlyContinue
    if ($htmlReports) {
        Write-Host "Opening $($htmlReports.Count) HTML report(s) in your browser..." -ForegroundColor Green
        Write-Host "  (In the browser: Ctrl+P -> 'Save as PDF' to export a PDF.)" -ForegroundColor DarkGray
        foreach ($report in $htmlReports) {
            Start-Process $report.FullName
        }
    } else {
        Write-Host "No HTML reports found in '$Out'." -ForegroundColor Yellow
    }
}

Write-Host ""
switch ($verdictCode) {
    0 { Write-Host "Worst verdict across all agents: DEPLOYABLE" -ForegroundColor Green }
    1 { Write-Host "Worst verdict across all agents: CONDITIONAL" -ForegroundColor Yellow }
    2 { Write-Host "Worst verdict across all agents: NOT DEPLOYABLE" -ForegroundColor Red }
    default { Write-Host "ARA exited with code $verdictCode" -ForegroundColor Yellow }
}

# Preserve ARA's exit code (0 deployable / 1 conditional / 2 not-deployable) for CI.
exit $verdictCode
