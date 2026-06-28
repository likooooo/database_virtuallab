# Runs on Windows after WSL uploads scripts via SSH/SCP (no Python required).
param(
    [Parameter(Mandatory = $true)]
    [string]$VirtuallabDir,
    [string]$PayloadRoot = $PSScriptRoot,
    [int]$Limit = 0
)

$ErrorActionPreference = "Stop"

$exportScript = Join-Path $PayloadRoot "simulation_database/vl/export_materials.ps1"
if (-not (Test-Path $exportScript)) {
    $exportScript = Join-Path $PayloadRoot "export_materials.ps1"
}
if (-not (Test-Path $exportScript)) {
    throw "export_materials.ps1 not found under $PayloadRoot"
}

$csvRoot = Join-Path $PayloadRoot "csv_export"
$materialsOut = Join-Path $csvRoot "materials"

$invokeParams = @{
    InstallDir = $VirtuallabDir
    OutRoot    = $materialsOut
    IndexRoot  = $csvRoot
}
if ($Limit -gt 0) {
    $invokeParams.Limit = $Limit
}

Write-Host "Running export_materials.ps1 (Limit=$(if ($Limit -gt 0) { $Limit } else { 'all' }))"
& $exportScript @invokeParams
if (-not $?) {
    Write-Error "export_materials.ps1 failed"
}
Write-Host "CSV export finished -> $materialsOut"
exit 0
