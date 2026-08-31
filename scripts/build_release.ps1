[CmdletBinding()]
param(
    [ValidateSet('Both', 'Full', 'Lite')]
    [string]$PackageMode = 'Both',

    [string]$WebView2Archive,

    [string]$WebView2Bootstrapper
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Native command failed with exit code $LASTEXITCODE`: $FilePath"
    }
}

function Get-NativeOutput {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $output = & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Native command failed with exit code $LASTEXITCODE`: $FilePath"
    }
    return (($output | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine).Trim()
}

function Assert-MicrosoftSignature {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
        throw "$Label Authenticode signature is not valid."
    }
    if (
        $null -eq $signature.SignerCertificate -or
        $signature.SignerCertificate.Subject -notmatch '(^|, )O=Microsoft Corporation(,|$)'
    ) {
        throw "$Label signer is not Microsoft Corporation."
    }
}

function Remove-ControlledSmokeCopy {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$BuildRoot
    )

    $fullPath = [IO.Path]::GetFullPath($Path)
    $fullBuildRoot = [IO.Path]::GetFullPath($BuildRoot)
    $parent = [IO.Directory]::GetParent($fullPath)
    if ($null -eq $parent -or $parent.FullName -ine $fullBuildRoot) {
        throw "Refusing to remove a work directory outside build/release: $fullPath"
    }
    $allowedNames = @('smoke-copy-fixed', 'smoke-copy-evergreen')
    if ($allowedNames -notcontains (Split-Path -Leaf $fullPath)) {
        throw "Refusing to remove an unexpected work directory: $fullPath"
    }
    if (Test-Path -LiteralPath $fullPath) {
        Remove-Item -LiteralPath $fullPath -Recurse -Force
    }
}

function Invoke-FrozenSmoke {
    param(
        [Parameter(Mandatory = $true)][string]$ReleaseDirectory,
        [Parameter(Mandatory = $true)][ValidateSet('fixed', 'evergreen')][string]$RuntimeMode,
        [Parameter(Mandatory = $true)][string]$BuildRoot,
        [Parameter(Mandatory = $true)][string]$ExpectedVersion
    )

    $smokeCopy = Join-Path $BuildRoot "smoke-copy-$RuntimeMode"
    Copy-Item -LiteralPath $ReleaseDirectory -Destination $smokeCopy -Recurse
    $frozenSmoke = Join-Path $smokeCopy 'frozen-smoke.json'
    $smokeArguments = "--smoke-test --json-output `"$frozenSmoke`""
    $smokeProcess = Start-Process `
        -FilePath (Join-Path $smokeCopy 'GameSaveScout.exe') `
        -ArgumentList $smokeArguments `
        -Wait `
        -PassThru `
        -WindowStyle Hidden
    if ($smokeProcess.ExitCode -ne 0) {
        $detail = ''
        if (Test-Path -LiteralPath $frozenSmoke -PathType Leaf) {
            $failedPayload = Get-Content -LiteralPath $frozenSmoke -Raw -Encoding utf8 | ConvertFrom-Json
            $detail = [string]$failedPayload.error
        }
        if ($RuntimeMode -eq 'evergreen') {
            throw "Evergreen frozen smoke failed. Install WebView2 Runtime on the build machine first. $detail"
        }
        throw "Fixed frozen smoke failed with exit code $($smokeProcess.ExitCode). $detail"
    }
    $payload = Get-Content -LiteralPath $frozenSmoke -Raw -Encoding utf8 | ConvertFrom-Json
    if (
        -not $payload.ok -or
        -not $payload.frozen -or
        $payload.appVersion -ne $ExpectedVersion -or
        $payload.runtimeMode -ne $RuntimeMode
    ) {
        throw "$RuntimeMode frozen startup smoke report is invalid."
    }
    foreach ($check in $payload.checks.PSObject.Properties) {
        if ($check.Value -ne $true) {
            throw "$RuntimeMode frozen startup smoke check failed: $($check.Name)"
        }
    }
    if ($RuntimeMode -eq 'fixed') {
        $expectedRuntime = [IO.Path]::GetFullPath((Join-Path $smokeCopy 'runtime'))
        if ([IO.Path]::GetFullPath([string]$payload.webviewRuntime) -ine $expectedRuntime) {
            throw 'Fixed frozen smoke did not use the bundled runtime.'
        }
    }
    elseif (
        $null -ne $payload.webviewRuntime -or
        $payload.checks.evergreenRuntime -ne $true -or
        $payload.checks.webviewBootstrapper -ne $true
    ) {
        throw 'Evergreen frozen smoke did not validate the system runtime and Bootstrapper.'
    }
    Remove-ControlledSmokeCopy -Path $smokeCopy -BuildRoot $BuildRoot
}

$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$buildFixed = $PackageMode -in @('Both', 'Full')
$buildEvergreen = $PackageMode -in @('Both', 'Lite')
$releaseModeArgument = switch ($PackageMode) {
    'Full' { 'fixed' }
    'Lite' { 'evergreen' }
    default { 'both' }
}

$archivePath = $null
if ($buildFixed) {
    if ([string]::IsNullOrWhiteSpace($WebView2Archive)) {
        throw 'WebView2Archive is required for Full and Both package modes.'
    }
    if ($WebView2Archive -notmatch '^[A-Za-z]:[\\/]') {
        throw 'WebView2Archive must be an absolute path.'
    }
    $archivePath = [IO.Path]::GetFullPath($WebView2Archive)
    if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
        throw "WebView2Archive does not exist or is not a file: $archivePath"
    }
}

$bootstrapperPath = $null
if ($buildEvergreen) {
    if ([string]::IsNullOrWhiteSpace($WebView2Bootstrapper)) {
        throw 'WebView2Bootstrapper is required for Lite and Both package modes.'
    }
    if ($WebView2Bootstrapper -notmatch '^[A-Za-z]:[\\/]') {
        throw 'WebView2Bootstrapper must be an absolute path.'
    }
    $bootstrapperPath = [IO.Path]::GetFullPath($WebView2Bootstrapper)
    if (-not (Test-Path -LiteralPath $bootstrapperPath -PathType Leaf)) {
        throw "WebView2Bootstrapper does not exist or is not a file: $bootstrapperPath"
    }
}
if (-not [Environment]::Is64BitOperatingSystem -or -not [Environment]::Is64BitProcess) {
    throw 'GameSave Scout release builds require 64-bit Windows and a 64-bit process.'
}

if ($buildFixed) {
    Assert-MicrosoftSignature -Path $archivePath -Label 'WebView2 Fixed Runtime CAB'
}
if ($buildEvergreen) {
    Assert-MicrosoftSignature -Path $bootstrapperPath -Label 'WebView2 Bootstrapper'
}

$expectedPrefix = [IO.Path]::GetFullPath((Join-Path $repositoryRoot '.venv'))
$expectedPython = [IO.Path]::GetFullPath((Join-Path $expectedPrefix 'python.exe'))
if (-not (Test-Path -LiteralPath $expectedPython -PathType Leaf)) {
    throw "The repository Conda prefix is missing python.exe: $expectedPython"
}
$pythonCommand = (Get-Command python.exe -ErrorAction Stop).Source
if ([IO.Path]::GetFullPath($pythonCommand) -ine $expectedPython) {
    throw "Activate the repository .venv before building. Active python: $pythonCommand"
}
$activePrefix = Get-NativeOutput $expectedPython @('-c', 'import sys; print(sys.prefix)')
if ([IO.Path]::GetFullPath($activePrefix) -ine $expectedPrefix) {
    throw "Python sys.prefix is not the repository .venv: $activePrefix"
}

$pythonInfo = Get-NativeOutput $expectedPython @(
    '-c',
    "import importlib.metadata as m, platform, struct; print(platform.python_version(), struct.calcsize('P') * 8, m.version('pyinstaller'), sep=chr(124))"
)
$pythonParts = $pythonInfo -split '\|'
if ($pythonParts.Count -ne 3) {
    throw "Python environment probe returned an invalid result: $pythonInfo"
}
$pythonVersion = [version]$pythonParts[0]
$pythonBits = [int]$pythonParts[1]
$pyinstallerVersion = [version]$pythonParts[2]
if ($pythonVersion.Major -ne 3 -or $pythonVersion.Minor -ne 12) {
    throw "Python 3.12 is required: $pythonVersion"
}
if ($pythonBits -ne 64) {
    throw "64-bit Python is required: $pythonBits-bit"
}
if ($pyinstallerVersion.Major -ne 6 -or $pyinstallerVersion -lt [version]'6.21') {
    throw "PyInstaller >=6.21,<7 is required: $pyinstallerVersion"
}

$nodeCommand = (Get-Command node.exe -ErrorAction Stop).Source
$npmCommand = (Get-Command npm.cmd -ErrorAction Stop).Source
$nodeVersionText = (Get-NativeOutput $nodeCommand @('--version')).TrimStart('v')
$npmVersionText = Get-NativeOutput $npmCommand @('--version')
if (([version]$nodeVersionText).Major -ne 24) {
    throw "Node.js 24 is required: $nodeVersionText"
}
if (-not (Test-Path -LiteralPath (Join-Path $repositoryRoot 'frontend\package-lock.json') -PathType Leaf)) {
    throw 'frontend/package-lock.json is required.'
}

$releaseTools = Join-Path $repositoryRoot 'scripts\release_tools.py'
$contextArguments = @(
    $releaseTools,
    'verify-context',
    '--repository-root', $repositoryRoot,
    '--package-mode', $releaseModeArgument
)
if ($buildFixed) {
    $contextArguments += @('--webview-archive', $archivePath)
}
if ($buildEvergreen) {
    $contextArguments += @('--webview-bootstrapper', $bootstrapperPath)
}
$contextJson = Get-NativeOutput $expectedPython $contextArguments
$releaseContext = $contextJson | ConvertFrom-Json
$fixedReleaseName = [string]$releaseContext.fixedReleaseName
$evergreenReleaseName = [string]$releaseContext.evergreenReleaseName

Invoke-Native $expectedPython @(
    $releaseTools,
    'prepare-build-root',
    '--repository-root', $repositoryRoot
)
$buildRoot = [IO.Path]::GetFullPath((Join-Path $repositoryRoot 'build\release'))

Invoke-Native $npmCommand @('--prefix', (Join-Path $repositoryRoot 'frontend'), 'ci')
Invoke-Native $npmCommand @('--prefix', (Join-Path $repositoryRoot 'frontend'), 'run', 'test:unit', '--', '--run')
Invoke-Native $npmCommand @('--prefix', (Join-Path $repositoryRoot 'frontend'), 'run', 'type-check')
Invoke-Native $npmCommand @('--prefix', (Join-Path $repositoryRoot 'frontend'), 'run', 'build')
Invoke-Native $expectedPython @('-m', 'pytest', '-q')
Invoke-Native $expectedPython @('-m', 'ruff', 'check', 'src', 'tests', 'scripts')
Invoke-Native $expectedPython @('-m', 'mypy', 'src', 'scripts')

$sourceSmoke = Join-Path $buildRoot 'source-smoke.json'
$sourceSmokeRoot = Join-Path $buildRoot 'source-smoke-app'
Invoke-Native $expectedPython @(
    '-m', 'gamesave_scout.app',
    '--smoke-test',
    '--json-output', $sourceSmoke,
    '--app-root', $sourceSmokeRoot
)
$sourcePayload = Get-Content -LiteralPath $sourceSmoke -Raw -Encoding utf8 | ConvertFrom-Json
if (-not $sourcePayload.ok -or $sourcePayload.frozen -or $sourcePayload.runtimeMode -ne 'source') {
    throw 'Source startup smoke failed.'
}

$pyinstallerDist = Join-Path $buildRoot 'pyinstaller-dist'
$pyinstallerWork = Join-Path $buildRoot 'pyinstaller-work'
Invoke-Native $expectedPython @(
    '-m', 'PyInstaller',
    '--clean',
    '--noconfirm',
    (Join-Path $repositoryRoot 'GameSaveScout.spec'),
    '--distpath', $pyinstallerDist,
    '--workpath', $pyinstallerWork
)
$frozenDirectory = Join-Path $pyinstallerDist 'GameSaveScout'
if (-not (Test-Path -LiteralPath (Join-Path $frozenDirectory 'GameSaveScout.exe') -PathType Leaf)) {
    throw 'PyInstaller did not produce GameSaveScout.exe.'
}

$stagingRoot = Join-Path $buildRoot 'staging'
New-Item -ItemType Directory -Path $stagingRoot | Out-Null
$releasePlans = @()
if ($buildFixed) {
    $extractedDirectory = Join-Path $buildRoot 'webview2-extracted'
    $runtimeRoot = Get-NativeOutput $expectedPython @(
        $releaseTools,
        'extract-runtime',
        '--repository-root', $repositoryRoot,
        '--webview-archive', $archivePath,
        '--destination', $extractedDirectory
    )
    $runtimeRoot = [IO.Path]::GetFullPath($runtimeRoot)
    Assert-MicrosoftSignature `
        -Path (Join-Path $runtimeRoot 'msedgewebview2.exe') `
        -Label 'WebView2 Fixed Runtime executable'

    $fixedDirectory = Join-Path $stagingRoot $fixedReleaseName
    Copy-Item -LiteralPath $frozenDirectory -Destination $fixedDirectory -Recurse
    Copy-Item -LiteralPath $runtimeRoot -Destination (Join-Path $fixedDirectory 'runtime') -Recurse
    $releasePlans += [PSCustomObject]@{
        Directory = $fixedDirectory
        Readme = 'README.txt'
        Mode = 'fixed'
        ReleaseName = $fixedReleaseName
        Archive = $null
        Checksum = $null
    }
}
if ($buildEvergreen) {
    $evergreenDirectory = Join-Path $stagingRoot $evergreenReleaseName
    Copy-Item -LiteralPath $frozenDirectory -Destination $evergreenDirectory -Recurse
    $prerequisites = Join-Path $evergreenDirectory 'prerequisites'
    New-Item -ItemType Directory -Path $prerequisites | Out-Null
    Copy-Item `
        -LiteralPath $bootstrapperPath `
        -Destination (Join-Path $prerequisites 'MicrosoftEdgeWebview2Setup.exe')
    $releasePlans += [PSCustomObject]@{
        Directory = $evergreenDirectory
        Readme = 'README-lite.txt'
        Mode = 'evergreen'
        ReleaseName = $evergreenReleaseName
        Archive = $null
        Checksum = $null
    }
}

foreach ($release in $releasePlans) {
    Copy-Item `
        -LiteralPath (Join-Path $repositoryRoot "release\$($release.Readme)") `
        -Destination (Join-Path $release.Directory 'README.txt')
    Copy-Item -LiteralPath (Join-Path $repositoryRoot 'LICENSE') -Destination (Join-Path $release.Directory 'LICENSE')
    Copy-Item -LiteralPath (Join-Path $repositoryRoot 'THIRD_PARTY_NOTICES.md') -Destination (Join-Path $release.Directory 'THIRD_PARTY_NOTICES.md')
    if (Test-Path -LiteralPath (Join-Path $release.Directory 'data')) {
        throw 'A staged release directory must not contain data.'
    }
    if (
        $release.Mode -eq 'fixed' -and
        (Test-Path -LiteralPath (Join-Path $release.Directory 'prerequisites'))
    ) {
        throw 'The fixed release must not contain prerequisites.'
    }
    if (
        $release.Mode -eq 'evergreen' -and
        (Test-Path -LiteralPath (Join-Path $release.Directory 'runtime'))
    ) {
        throw 'The evergreen release must not contain a fixed runtime.'
    }
    Invoke-Native $expectedPython @(
        $releaseTools,
        'write-manifest',
        '--repository-root', $repositoryRoot,
        '--release-directory', $release.Directory,
        '--runtime-mode', $release.Mode
    )
}

foreach ($release in $releasePlans) {
    Invoke-FrozenSmoke `
        -ReleaseDirectory $release.Directory `
        -RuntimeMode $release.Mode `
        -BuildRoot $buildRoot `
        -ExpectedVersion $releaseContext.version

    $release.Archive = Join-Path $stagingRoot "$($release.ReleaseName).zip"
    $release.Checksum = Join-Path $stagingRoot "$($release.ReleaseName).zip.sha256"
    Invoke-Native $expectedPython @(
        $releaseTools,
        'verify-release',
        '--repository-root', $repositoryRoot,
        '--release-directory', $release.Directory,
        '--runtime-mode', $release.Mode
    )
    Invoke-Native $expectedPython @(
        $releaseTools,
        'build-archive',
        '--repository-root', $repositoryRoot,
        '--release-directory', $release.Directory,
        '--archive', $release.Archive,
        '--checksum', $release.Checksum,
        '--runtime-mode', $release.Mode
    )
}

$publishArguments = @(
    $releaseTools,
    'publish',
    '--repository-root', $repositoryRoot
)
foreach ($release in $releasePlans) {
    $prefix = "--$($release.Mode)"
    $publishArguments += @(
        "$prefix-release-directory", $release.Directory,
        "$prefix-archive", $release.Archive,
        "$prefix-checksum", $release.Checksum
    )
}
Invoke-Native $expectedPython $publishArguments

$createdNames = $releasePlans | ForEach-Object { "dist\$($_.ReleaseName)" }
Write-Host "GameSave Scout release candidates created: $($createdNames -join ' and ')"
