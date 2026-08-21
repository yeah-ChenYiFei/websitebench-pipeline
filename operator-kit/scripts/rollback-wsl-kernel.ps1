[CmdletBinding()]
param(
    [string]$Distribution = 'Ubuntu-24.04',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$rollbackDirectory = 'D:\WSL\Kernels\rollback'
$rollbackStatePath = Join-Path $rollbackDirectory 'websitebench-wsl-kernel-state.json'
$rollbackStateNextPath = "$rollbackStatePath.next"
$rollbackResultPath = Join-Path $rollbackDirectory 'websitebench-wsl-kernel-rollback-result.json'

if (-not (Test-Path -LiteralPath $rollbackStatePath -PathType Leaf)) {
    throw "Rollback state is missing: $rollbackStatePath"
}

try {
    $state = Get-Content -Raw -LiteralPath $rollbackStatePath | ConvertFrom-Json
}
catch {
    throw "Rollback state is damaged and automatic rollback was not attempted. Run 'wsl.exe --shutdown', inspect $env:USERPROFILE\.wslconfig, and only if it contains the WebsiteBench kernel/kernelModules override, rename it out of the way; then run 'wsl.exe --shutdown' and start Ubuntu-24.04. Original error: $($_.Exception.Message)"
}
$wslConfigPath = [string]$state.wslconfig_path
$currentExists = Test-Path -LiteralPath $wslConfigPath -PathType Leaf
$rollbackTimestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$driftArchivePath = $null
$currentHash = $null

if ($currentExists) {
    $currentHash = (Get-FileHash -LiteralPath $wslConfigPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($currentHash -ne [string]$state.managed_sha256 -and -not $Force) {
        throw 'The active .wslconfig changed after activation. Re-run with -Force only after reviewing those changes.'
    }
    if ($currentHash -ne [string]$state.managed_sha256) {
        $driftArchivePath = Join-Path (Split-Path -Parent $wslConfigPath) ".wslconfig.websitebench-drift-$rollbackTimestamp"
        Copy-Item -LiteralPath $wslConfigPath -Destination $driftArchivePath
    }
}

$phase = if ($state.PSObject.Properties.Name -contains 'phase') { [string]$state.phase } else { 'active' }
$stagedConfigPath = if ($state.PSObject.Properties.Name -contains 'staged_wslconfig_path') {
    [string]$state.staged_wslconfig_path
}
else {
    "$wslConfigPath.websitebench.next"
}
if ($phase -eq 'prepared' -and (-not $currentExists -or $currentHash -ne [string]$state.managed_sha256)) {
    $stagedArchivePath = $null
    if (Test-Path -LiteralPath $stagedConfigPath -PathType Leaf) {
        $stagedHash = (Get-FileHash -LiteralPath $stagedConfigPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($stagedHash -ne [string]$state.managed_sha256) {
            throw "Prepared transaction has an unexpected staged .wslconfig hash: $stagedConfigPath"
        }
        $stagedArchivePath = Join-Path $rollbackDirectory ".wslconfig.staged-aborted-$rollbackTimestamp"
        Move-Item -LiteralPath $stagedConfigPath -Destination $stagedArchivePath
    }
    $baselineOutput = & wsl.exe -d $Distribution -- uname -r
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to verify $Distribution while aborting the prepared transaction."
    }
    $baselineRelease = ($baselineOutput | Out-String).Trim()
    if ($baselineRelease -ne [string]$state.expected_stock_release) {
        throw "Prepared transaction abort found an unexpected baseline release: $baselineRelease"
    }
    $abortedStatePath = Join-Path $rollbackDirectory "websitebench-wsl-kernel-state.prepared-aborted-$rollbackTimestamp.json"
    $abortResult = [ordered]@{
        schema_version = 'websitebench.wsl-kernel-rollback-result.v1'
        rolled_back_at = (Get-Date).ToUniversalTime().ToString('o')
        distribution = $Distribution
        restored_release = $baselineRelease
        aborted_prepared_transaction = $true
        archived_staged_config = $stagedArchivePath
        archived_state = $abortedStatePath
    }
    $abortEncoding = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($rollbackResultPath, ($abortResult | ConvertTo-Json -Depth 4), $abortEncoding)
    Move-Item -LiteralPath $rollbackStatePath -Destination $abortedStatePath
    Remove-Item -LiteralPath "$rollbackStatePath.next" -Force -ErrorAction SilentlyContinue
    Write-Host "Prepared activation was safely aborted. Active kernel: $baselineRelease"
    Write-Host "Rollback state was archived at: $abortedStatePath"
    exit 0
}

& wsl.exe --shutdown
if ($LASTEXITCODE -ne 0) {
    throw "Initial wsl.exe --shutdown failed with exit code $LASTEXITCODE."
}

$disabledPath = $null
if ([bool]$state.original_existed) {
    $backupPath = [string]$state.original_backup_path
    if (-not (Test-Path -LiteralPath $backupPath -PathType Leaf)) {
        throw "Original .wslconfig backup is missing: $backupPath"
    }
    $backupHash = (Get-FileHash -LiteralPath $backupPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($backupHash -ne [string]$state.original_sha256) {
        throw 'Original .wslconfig backup SHA-256 does not match rollback state.'
    }
    $restoreNextPath = "$wslConfigPath.websitebench-restore.next"
    if (Test-Path -LiteralPath $restoreNextPath) {
        throw "Stale restore file exists: $restoreNextPath"
    }
    Copy-Item -LiteralPath $backupPath -Destination $restoreNextPath
    Move-Item -LiteralPath $restoreNextPath -Destination $wslConfigPath -Force
}
elseif ($currentExists) {
    $disabledPath = Join-Path (Split-Path -Parent $wslConfigPath) ".wslconfig.websitebench-disabled-$rollbackTimestamp"
    Move-Item -LiteralPath $wslConfigPath -Destination $disabledPath
}

$stagedArchivePath = $null
if (Test-Path -LiteralPath $stagedConfigPath -PathType Leaf) {
    $stagedArchivePath = Join-Path $rollbackDirectory ".wslconfig.staged-after-activation-$rollbackTimestamp"
    Move-Item -LiteralPath $stagedConfigPath -Destination $stagedArchivePath
}

& wsl.exe --shutdown
if ($LASTEXITCODE -ne 0) {
    throw "Final wsl.exe --shutdown failed with exit code $LASTEXITCODE."
}

$releaseOutput = & wsl.exe -d $Distribution -- uname -r
if ($LASTEXITCODE -ne 0) {
    throw "Failed to start $Distribution after rollback."
}
$release = ($releaseOutput | Out-String).Trim()
if ($release -ne [string]$state.expected_stock_release) {
    throw "Rollback did not restore the expected stock kernel. Actual release: $release"
}

$archivedStateNextPath = $null
if (Test-Path -LiteralPath $rollbackStateNextPath -PathType Leaf) {
    try {
        $stateNext = Get-Content -Raw -LiteralPath $rollbackStateNextPath | ConvertFrom-Json
    }
    catch {
        throw "Rollback restored the baseline kernel, but the atomic state-update file is damaged and was retained for manual review: $rollbackStateNextPath"
    }
    if ($stateNext.schema_version -ne $state.schema_version -or
        [string]$stateNext.managed_sha256 -ne [string]$state.managed_sha256) {
        throw "Rollback restored the baseline kernel, but the atomic state-update file does not match the main transaction and was retained: $rollbackStateNextPath"
    }
    $archivedStateNextPath = Join-Path $rollbackDirectory "websitebench-wsl-kernel-state.active-next-$rollbackTimestamp.json"
}

$result = [ordered]@{
    schema_version = 'websitebench.wsl-kernel-rollback-result.v1'
    rolled_back_at = (Get-Date).ToUniversalTime().ToString('o')
    distribution = $Distribution
    restored_release = $release
    original_config_restored = [bool]$state.original_existed
    disabled_managed_config = $disabledPath
    archived_drift_config = $driftArchivePath
    archived_staged_config = $stagedArchivePath
    archived_original_backup = $null
    archived_state_next = $archivedStateNextPath
    archived_state = Join-Path $rollbackDirectory "websitebench-wsl-kernel-state.rolled-back-$rollbackTimestamp.json"
}
$originalBackupArchivePath = $null
if ([bool]$state.original_existed) {
    $originalBackupArchivePath = Join-Path $rollbackDirectory ".wslconfig.before-websitebench.rolled-back-$rollbackTimestamp"
    $result['archived_original_backup'] = $originalBackupArchivePath
}
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText(
    $rollbackResultPath,
    ($result | ConvertTo-Json -Depth 4),
    $utf8NoBom
)
if ($originalBackupArchivePath) {
    Move-Item -LiteralPath ([string]$state.original_backup_path) -Destination $originalBackupArchivePath
}
if ($archivedStateNextPath) {
    Move-Item -LiteralPath $rollbackStateNextPath -Destination $archivedStateNextPath
}
Move-Item -LiteralPath $rollbackStatePath -Destination ([string]$result.archived_state)

Write-Host "Rollback completed. Active kernel: $release"
if ($disabledPath) {
    Write-Host "Managed .wslconfig was preserved at: $disabledPath"
}
Write-Host "Rollback state was archived at: $($result.archived_state)"
Write-Host 'Custom kernel artifacts were retained for diagnosis.'
