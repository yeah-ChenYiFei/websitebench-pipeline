#Requires -RunAsAdministrator

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$minimumFreeBytes = 5GB
$systemDrive = Get-PSDrive -Name C
if ($systemDrive.Free -lt $minimumFreeBytes) {
    $freeGB = [math]::Round($systemDrive.Free / 1GB, 2)
    throw "C: requires at least 5 GB free before WSL installation; current free space: $freeGB GB"
}

$minimumDataFreeBytes = 15GB
$dataDrive = Get-PSDrive -Name D
if ($dataDrive.Free -lt $minimumDataFreeBytes) {
    $freeGB = [math]::Round($dataDrive.Free / 1GB, 2)
    throw "D: requires at least 15 GB free for Ubuntu and project dependencies; current free space: $freeGB GB"
}

$distribution = 'Ubuntu-24.04'
$installLocation = 'D:\WSL\WebsiteBench-Ubuntu'

if (Test-Path -LiteralPath $installLocation) {
    throw "Install location already exists; refusing to overwrite: $installLocation"
}

& wsl.exe --install $distribution `
    --location $installLocation `
    --no-launch `
    --web-download

if ($LASTEXITCODE -ne 0) {
    $targetState = if (Test-Path -LiteralPath $installLocation) {
        "The target directory now exists at $installLocation. Do not delete it until 'wsl.exe --list --verbose' confirms whether the distribution was registered."
    }
    else {
        "The target directory was not created."
    }
    throw "WSL installation failed with exit code $LASTEXITCODE. $targetState"
}

Write-Host 'Ubuntu installation completed without launching the distribution.'
Write-Host 'If Windows requests a restart, restart before the first launch.'
Write-Host "First launch: wsl.exe --distribution $distribution"
