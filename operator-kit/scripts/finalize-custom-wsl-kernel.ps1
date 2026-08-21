[CmdletBinding()]
param(
    [string]$Distribution = 'Ubuntu-24.04'
)

$ErrorActionPreference = 'Stop'

$expectedRelease = '6.18.33.2-microsoft-standard-WSL2-x32off'
$expectedSourceSha256 = '21f28efed81a1c097d249917000eed9ca70e8f90bfeebc687ea9b559d5310906'
$expectedGeneratorSha256 = 'a484271fdd29d7be9f41b026dfcf96a109e1c1f3be4d4a76458152ab89eb2492'
$ArtifactDirectory = 'D:\WSL\Kernels\6.18.33.2-x32off'
$sourceArchive = 'D:\codework\.websitebench-tools\wsl-kernel\source\linux-msft-wsl-6.18.33.2.tar.gz'
$linuxSourceArchive = '/mnt/d/codework/.websitebench-tools/wsl-kernel/source/linux-msft-wsl-6.18.33.2.tar.gz'
$generatorArchiveMember = 'WSL2-Linux-Kernel-linux-msft-wsl-6.18.33.2/Microsoft/scripts/gen_modules_vhdx.sh'
$modulesDirectory = '/home/xhw/websitebench-wsl-kernel/modules-x32off'
$verifiedRootDirectory = '/root/websitebench-wsl-kernel-finalize'
$scratchDirectory = "$verifiedRootDirectory/vhdx-scratch"
$generator = "$verifiedRootDirectory/gen_modules_vhdx.sh"
$linuxModulesVhdx = '/mnt/d/WSL/Kernels/6.18.33.2-x32off/modules.vhdx'

$kernelPath = Join-Path $ArtifactDirectory 'bzImage'
$modulesPath = Join-Path $ArtifactDirectory 'modules.vhdx'
$configPath = Join-Path $ArtifactDirectory 'config'
$configDiffPath = Join-Path $ArtifactDirectory 'config.diff'
$systemMapPath = Join-Path $ArtifactDirectory 'System.map'
$moduleSymversPath = Join-Path $ArtifactDirectory 'Module.symvers'
$releasePath = Join-Path $ArtifactDirectory 'kernel-release.txt'
$receiptPath = Join-Path $ArtifactDirectory 'build-stage-receipt.json'
$manifestPath = Join-Path $ArtifactDirectory 'build-manifest.json'

foreach ($requiredPath in @(
    $sourceArchive,
    $kernelPath,
    $configPath,
    $configDiffPath,
    $systemMapPath,
    $moduleSymversPath,
    $releasePath,
    $receiptPath
)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required build artifact is missing: $requiredPath"
    }
}
foreach ($refusedPath in @($modulesPath, $manifestPath)) {
    if (Test-Path -LiteralPath $refusedPath) {
        throw "Refusing to overwrite finalized artifact: $refusedPath"
    }
}

$sourceHash = (Get-FileHash -LiteralPath $sourceArchive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($sourceHash -ne $expectedSourceSha256) {
    throw 'Pinned Microsoft source archive SHA-256 mismatch.'
}
$receipt = Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json
if ($receipt.schema_version -ne 'websitebench.wsl-kernel-build-stage.v1' -or
    $receipt.builder_user -ne 'xhw' -or
    $receipt.source_archive_sha256 -ne $expectedSourceSha256 -or
    $receipt.kernel_release -ne $expectedRelease) {
    throw 'Build-stage receipt does not identify the approved build inputs.'
}
$receiptHashChecks = [ordered]@{
    kernel_sha256 = $kernelPath
    config_sha256 = $configPath
    config_diff_sha256 = $configDiffPath
    system_map_sha256 = $systemMapPath
    module_symvers_sha256 = $moduleSymversPath
}
foreach ($entry in $receiptHashChecks.GetEnumerator()) {
    $actualHash = (Get-FileHash -LiteralPath $entry.Value -Algorithm SHA256).Hash.ToLowerInvariant()
    $receiptHash = [string]$receipt.PSObject.Properties[$entry.Key].Value
    if ($actualHash -ne $receiptHash) {
        throw "Build artifact does not match build-stage receipt: $($entry.Value)"
    }
}
$release = (Get-Content -Raw -LiteralPath $releasePath).Trim()
if ($release -ne $expectedRelease) {
    throw "Unexpected kernel release: $release"
}
$expectedDiff = @(
    ' LOCALVERSION "-microsoft-standard-WSL2" -> "-microsoft-standard-WSL2-x32off"',
    ' X86_X32_ABI y -> n'
)
$actualDiff = @(Get-Content -LiteralPath $configDiffPath)
if ($actualDiff.Count -ne 2 -or
    $actualDiff[0] -ne $expectedDiff[0] -or
    $actualDiff[1] -ne $expectedDiff[1]) {
    throw 'Kernel config.diff is not the exact two-line approved change set.'
}
$configText = Get-Content -Raw -LiteralPath $configPath
foreach ($requiredConfig in @(
    '# CONFIG_X86_X32_ABI is not set',
    'CONFIG_IA32_EMULATION=y',
    'CONFIG_COMPAT=y',
    'CONFIG_SECURITY_LANDLOCK=y',
    'CONFIG_SECCOMP=y',
    'CONFIG_SECCOMP_FILTER=y'
)) {
    if ($configText -notmatch "(?m)^$([regex]::Escape($requiredConfig))$") {
        throw "Required kernel setting is missing: $requiredConfig"
    }
}

& wsl.exe -d $Distribution -u root -- test '!' -e $verifiedRootDirectory
if ($LASTEXITCODE -ne 0) {
    throw "Root-owned finalize directory already exists; inspect it before retrying: $verifiedRootDirectory"
}
& wsl.exe -d $Distribution -u root -- mkdir -p $scratchDirectory
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to create the isolated modules VHDX scratch directory.'
}
& wsl.exe -d $Distribution -u root -- tar -xzf $linuxSourceArchive -C $verifiedRootDirectory --strip-components=3 $generatorArchiveMember
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to extract the pinned Microsoft generator into the root-owned directory.'
}
& wsl.exe -d $Distribution -u root -- test -f $generator
if ($LASTEXITCODE -ne 0) {
    throw 'The extracted Microsoft generator is missing.'
}
& wsl.exe -d $Distribution -u root -- test '!' -L $generator
if ($LASTEXITCODE -ne 0) {
    throw 'The extracted Microsoft generator is a symbolic link.'
}
$generatorHashOutput = & wsl.exe -d $Distribution -u root -- sha256sum $generator
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to hash the extracted Microsoft generator.'
}
$generatorHash = (($generatorHashOutput | Out-String).Trim() -split '\s+')[0].ToLowerInvariant()
if ($generatorHash -ne $expectedGeneratorSha256) {
    throw 'Extracted Microsoft generator SHA-256 mismatch.'
}
& wsl.exe -d $Distribution -u root -- chmod 700 $generator
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to restrict the extracted Microsoft generator permissions.'
}

try {
    & wsl.exe -d $Distribution -u root -- env SUDO_USER=xhw TMPDIR=$scratchDirectory bash $generator $modulesDirectory $expectedRelease $linuxModulesVhdx
    if ($LASTEXITCODE -ne 0) {
        throw "Microsoft modules VHDX generator failed with exit code $LASTEXITCODE."
    }
    & wsl.exe -d $Distribution -u root -- qemu-img check $linuxModulesVhdx
    if ($LASTEXITCODE -ne 0) {
        throw "qemu-img check failed with exit code $LASTEXITCODE."
    }
}
finally {
    & wsl.exe --shutdown
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to shut down WSL while detaching the modules VHDX scratch image.'
    }
    $resolvedScratch = & wsl.exe -d $Distribution -u root -- realpath -e $verifiedRootDirectory
    if ($LASTEXITCODE -eq 0) {
        $resolvedScratch = ($resolvedScratch | Out-String).Trim()
        if ($resolvedScratch -ne $verifiedRootDirectory) {
            throw "Refusing to clean unexpected scratch path: $resolvedScratch"
        }
        & wsl.exe -d $Distribution -u root -- rm -rf -- $verifiedRootDirectory
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to clean verified root-owned finalize directory: $verifiedRootDirectory"
        }
    }
}

if (-not (Test-Path -LiteralPath $modulesPath -PathType Leaf) -or
    (Get-Item -LiteralPath $modulesPath).Length -lt 8MB) {
    throw 'Finalized modules.vhdx is missing or unexpectedly small.'
}

function Get-LowerSha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

$manifest = [ordered]@{
    schema_version = 'websitebench.wsl-kernel-build.v1'
    build_started_at_utc = [string]$receipt.build_started_at_utc
    build_completed_at_utc = [string]$receipt.build_completed_at_utc
    finalized_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    builder_distribution = $Distribution
    builder_user = [string]$receipt.builder_user
    build_jobs = [int]$receipt.build_jobs
    source_repository = 'https://github.com/microsoft/WSL2-Linux-Kernel.git'
    source_tag = 'linux-msft-wsl-6.18.33.2'
    source_commit = 'c21a03b2943d147c280bdf32530d4fe6badfd6bd'
    source_archive_sha256 = $sourceHash
    kernel_release = $expectedRelease
    stock_kernel_release = 'captured-at-activation'
    config_changes = @(
        'LOCALVERSION: -microsoft-standard-WSL2 -> -microsoft-standard-WSL2-x32off',
        'CONFIG_X86_X32_ABI: y -> n'
    )
    preserved_config = @(
        'CONFIG_IA32_EMULATION=y',
        'CONFIG_COMPAT=y',
        'CONFIG_SECURITY_LANDLOCK=y',
        'CONFIG_SECCOMP=y',
        'CONFIG_SECCOMP_FILTER=y'
    )
    kernel_sha256 = Get-LowerSha256 $kernelPath
    modules_sha256 = Get-LowerSha256 $modulesPath
    config_sha256 = Get-LowerSha256 $configPath
    config_diff_sha256 = Get-LowerSha256 $configDiffPath
    system_map_sha256 = Get-LowerSha256 $systemMapPath
    module_symvers_sha256 = Get-LowerSha256 $moduleSymversPath
    modules_vhdx_check = 'qemu-img check: no errors'
}
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText(
    $manifestPath,
    ($manifest | ConvertTo-Json -Depth 5),
    $utf8NoBom
)

Write-Host "Finalized custom kernel artifacts: $ArtifactDirectory"
Write-Host "Build manifest: $manifestPath"
