# Run from an Administrator PowerShell. Installs only the verified local package.
# No downloads, association with Microsoft Office formats, or automatic reboot.
#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$installer = Join-Path $projectRoot 'storage\installers\LibreOffice_26.8.0_Win_x86-64.msi'
$target = 'D:\AICoding\Tools\LibreOffice'
$executable = Join-Path $target 'program\soffice.exe'
$expectedHash = '4AA6C6E1895F4055104EFFCB556BD3362D20C6AD707C149543304F395EF9DB95'

if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
    throw "Verified installer missing: $installer"
}
if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash -ne $expectedHash) {
    throw 'Installer checksum mismatch. Installation stopped.'
}
if ((Get-AuthenticodeSignature -LiteralPath $installer).Status -ne 'Valid') {
    throw 'Installer signature is not valid. Installation stopped.'
}
if (Test-Path -LiteralPath $target) {
    throw "Target already exists; inspect it before installing: $target"
}
$log = Join-Path $projectRoot ('storage\installers\libreoffice-install-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
$arguments = @('/i', ('"' + $installer + '"'), '/qn', '/norestart',
    ('INSTALLLOCATION="' + $target + '"'), 'REGISTER_NO_MSO_TYPES=1',
    'REGISTER_ALL_MSO_TYPES=0', 'CREATEDESKTOPLINK=0', '/L*v', ('"' + $log + '"'))
$process = Start-Process -FilePath "$env:SystemRoot\System32\msiexec.exe" `
    -ArgumentList $arguments -WindowStyle Hidden -PassThru -Wait
Write-Output "InstallerExitCode=$($process.ExitCode)"
Write-Output "InstallerLog=$log"
if ($process.ExitCode -notin @(0, 3010)) {
    throw 'Installation failed. Keep the log for diagnosis; do not retry blindly.'
}
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw 'Installer finished but soffice.exe is missing at the intended path.'
}
Write-Output "InstalledExecutable=$executable"
Write-Output ('InstalledVersion=' + (Get-Item -LiteralPath $executable).VersionInfo.ProductVersion)
if ($process.ExitCode -eq 3010) {
    Write-Output 'Windows Installer requested a restart. No restart was performed.'
}
