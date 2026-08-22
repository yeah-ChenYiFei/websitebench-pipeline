[CmdletBinding()]
param(
    [string]$Distribution = 'Ubuntu-24.04',
    [string]$ArtifactDirectory = 'D:\WSL\Kernels\6.18.33.2-x32off'
)

$ErrorActionPreference = 'Stop'

$kernelPath = Join-Path $ArtifactDirectory 'bzImage'
$modulesPath = Join-Path $ArtifactDirectory 'modules.vhdx'
$buildManifestPath = Join-Path $ArtifactDirectory 'build-manifest.json'
$rollbackDirectory = 'D:\WSL\Kernels\rollback'
$rollbackStatePath = Join-Path $rollbackDirectory 'websitebench-wsl-kernel-state.json'
$rollbackStateNextPath = "$rollbackStatePath.next"
$wslConfigPath = Join-Path $env:USERPROFILE '.wslconfig'
$wslConfigNextPath = "$wslConfigPath.websitebench.next"

function Write-JsonAtomically([string]$Path, [object]$Value) {
    $nextPath = "$Path.next"
    if (Test-Path -LiteralPath $nextPath) {
        throw "Stale atomic-write file exists: $nextPath"
    }
    $encoding = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($nextPath, ($Value | ConvertTo-Json -Depth 5), $encoding)
    if (Test-Path -LiteralPath $Path) {
        [System.IO.File]::Replace($nextPath, $Path, $null)
    }
    else {
        Move-Item -LiteralPath $nextPath -Destination $Path
    }
}

foreach ($requiredPath in @($kernelPath, $modulesPath, $buildManifestPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required custom-kernel artifact is missing: $requiredPath"
    }
}

if ((Get-Item -LiteralPath $kernelPath).Length -lt 8MB) {
    throw "Kernel artifact is unexpectedly small: $kernelPath"
}
if ((Get-Item -LiteralPath $modulesPath).Length -lt 8MB) {
    throw "Kernel modules VHD is unexpectedly small: $modulesPath"
}

$buildManifest = Get-Content -Raw -LiteralPath $buildManifestPath | ConvertFrom-Json
if ($buildManifest.schema_version -ne 'websitebench.wsl-kernel-build.v1') {
    throw "Unexpected build manifest schema: $($buildManifest.schema_version)"
}
if ($buildManifest.source_tag -ne 'linux-msft-wsl-6.18.33.2' -or
    $buildManifest.source_commit -ne 'c21a03b2943d147c280bdf32530d4fe6badfd6bd' -or
    $buildManifest.source_archive_sha256 -ne '21f28efed81a1c097d249917000eed9ca70e8f90bfeebc687ea9b559d5310906') {
    throw 'Build manifest does not identify the pinned Microsoft source archive.'
}
if ($buildManifest.kernel_release -ne '6.18.33.2-microsoft-standard-WSL2-x32off') {
    throw "Unexpected kernel release in build manifest: $($buildManifest.kernel_release)"
}

$kernelHash = (Get-FileHash -LiteralPath $kernelPath -Algorithm SHA256).Hash.ToLowerInvariant()
$modulesHash = (Get-FileHash -LiteralPath $modulesPath -Algorithm SHA256).Hash.ToLowerInvariant()
$configPath = Join-Path $ArtifactDirectory 'config'
$configDiffPath = Join-Path $ArtifactDirectory 'config.diff'
foreach ($requiredPath in @($configPath, $configDiffPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required custom-kernel provenance artifact is missing: $requiredPath"
    }
}
$configHash = (Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash.ToLowerInvariant()
$configDiffHash = (Get-FileHash -LiteralPath $configDiffPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($kernelHash -ne [string]$buildManifest.kernel_sha256) {
    throw 'bzImage SHA-256 does not match build-manifest.json.'
}
if ($modulesHash -ne [string]$buildManifest.modules_sha256) {
    throw 'modules.vhdx SHA-256 does not match build-manifest.json.'
}
if ($configHash -ne [string]$buildManifest.config_sha256 -or
    $configDiffHash -ne [string]$buildManifest.config_diff_sha256) {
    throw 'Kernel config provenance does not match build-manifest.json.'
}

New-Item -ItemType Directory -Path $rollbackDirectory -Force | Out-Null
if (Test-Path -LiteralPath $rollbackStatePath) {
    throw "Rollback state already exists; refusing to replace the original baseline: $rollbackStatePath"
}
if (Test-Path -LiteralPath $rollbackStateNextPath) {
    throw "Stale rollback-state transaction exists; inspect it before retrying: $rollbackStateNextPath"
}
if (Test-Path -LiteralPath $wslConfigNextPath) {
    throw "Stale staged WSL configuration exists; inspect it before retrying: $wslConfigNextPath"
}

$originalExists = Test-Path -LiteralPath $wslConfigPath -PathType Leaf
if ($originalExists) {
    throw "A pre-existing .wslconfig was found at $wslConfigPath. Automatic merging is intentionally refused; preserve and review all existing WSL2 settings before enabling this kernel."
}

$baselineReleaseOutput = & wsl.exe -d $Distribution -- uname -r
if ($LASTEXITCODE -ne 0) {
    throw "Failed to capture the baseline kernel release for $Distribution."
}
$baselineRelease = ($baselineReleaseOutput | Out-String).Trim()
if ([string]::IsNullOrWhiteSpace($baselineRelease) -or
    $baselineRelease -eq '6.18.33.2-microsoft-standard-WSL2-x32off') {
    throw "Unexpected baseline kernel release: $baselineRelease"
}

$escapedKernelPath = $kernelPath.Replace('\', '\\')
$escapedModulesPath = $modulesPath.Replace('\', '\\')
$managedConfig = "[wsl2]`r`nkernel=$escapedKernelPath`r`nkernelModules=$escapedModulesPath`r`n"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($wslConfigNextPath, $managedConfig, $utf8NoBom)
$managedHash = (Get-FileHash -LiteralPath $wslConfigNextPath -Algorithm SHA256).Hash.ToLowerInvariant()

$rollbackState = [ordered]@{
    schema_version = 'websitebench.wsl-kernel-rollback.v1'
    phase = 'prepared'
    distribution = $Distribution
    activated_at = (Get-Date).ToUniversalTime().ToString('o')
    expected_custom_release = '6.18.33.2-microsoft-standard-WSL2-x32off'
    expected_stock_release = $baselineRelease
    wslconfig_path = $wslConfigPath
    original_existed = $false
    original_backup_path = $null
    original_sha256 = $null
    managed_sha256 = $managedHash
    staged_wslconfig_path = $wslConfigNextPath
    kernel_path = $kernelPath
    kernel_sha256 = $kernelHash
    modules_path = $modulesPath
    modules_sha256 = $modulesHash
}
Write-JsonAtomically -Path $rollbackStatePath -Value $rollbackState

try {
    Move-Item -LiteralPath $wslConfigNextPath -Destination $wslConfigPath
    $rollbackState['phase'] = 'active'
    Write-JsonAtomically -Path $rollbackStatePath -Value $rollbackState
    & wsl.exe --shutdown
    if ($LASTEXITCODE -ne 0) {
        throw "wsl.exe --shutdown failed with exit code $LASTEXITCODE."
    }
}
catch {
    $managedConfigIsActive = $false
    if (Test-Path -LiteralPath $wslConfigPath -PathType Leaf) {
        $activeHash = (Get-FileHash -LiteralPath $wslConfigPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $managedConfigIsActive = $activeHash -eq $managedHash
    }
    if (-not $managedConfigIsActive) {
        Remove-Item -LiteralPath $rollbackStatePath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $rollbackStateNextPath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $wslConfigNextPath -Force -ErrorAction SilentlyContinue
    }
    throw "Custom-kernel activation did not complete: $($_.Exception.Message) If the managed .wslconfig is active, run rollback-wsl-kernel.ps1."
}

Write-Host "Custom WSL kernel configuration enabled for all WSL2 distributions."
Write-Host "Rollback state: $rollbackStatePath"
Write-Host "Next: start $Distribution and verify the expected custom kernel release."
