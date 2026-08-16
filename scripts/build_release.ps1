[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$WebView2Archive
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
    if ((Split-Path -Leaf $fullPath) -ne 'smoke-copy') {
        throw "Refusing to remove an unexpected work directory: $fullPath"
    }
    if (Test-Path -LiteralPath $fullPath) {
        Remove-Item -LiteralPath $fullPath -Recurse -Force
    }
}

$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ($WebView2Archive -notmatch '^[A-Za-z]:[\\/]') {
    throw 'WebView2Archive must be an absolute path.'
}
$archivePath = [IO.Path]::GetFullPath($WebView2Archive)
if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
    throw "WebView2Archive does not exist or is not a file: $archivePath"
}
if (-not [Environment]::Is64BitOperatingSystem -or -not [Environment]::Is64BitProcess) {
    throw 'GameShelf release builds require 64-bit Windows and a 64-bit process.'
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
$contextJson = Get-NativeOutput $expectedPython @(
    $releaseTools,
    'verify-context',
    '--repository-root', $repositoryRoot,
    '--webview-archive', $archivePath
)
$releaseContext = $contextJson | ConvertFrom-Json
$releaseName = [string]$releaseContext.releaseName

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
    '-m', 'gameshelf.app',
    '--smoke-test',
    '--json-output', $sourceSmoke,
    '--app-root', $sourceSmokeRoot
)
$sourcePayload = Get-Content -LiteralPath $sourceSmoke -Raw -Encoding utf8 | ConvertFrom-Json
if (-not $sourcePayload.ok -or $sourcePayload.frozen) {
    throw 'Source startup smoke failed.'
}

$pyinstallerDist = Join-Path $buildRoot 'pyinstaller-dist'
$pyinstallerWork = Join-Path $buildRoot 'pyinstaller-work'
Invoke-Native $expectedPython @(
    '-m', 'PyInstaller',
    '--clean',
    '--noconfirm',
    (Join-Path $repositoryRoot 'GameShelf.spec'),
    '--distpath', $pyinstallerDist,
    '--workpath', $pyinstallerWork
)
$frozenDirectory = Join-Path $pyinstallerDist 'GameShelf'
if (-not (Test-Path -LiteralPath (Join-Path $frozenDirectory 'GameShelf.exe') -PathType Leaf)) {
    throw 'PyInstaller did not produce GameShelf.exe.'
}

$stagingRoot = Join-Path $buildRoot 'staging'
New-Item -ItemType Directory -Path $stagingRoot | Out-Null
$releaseDirectory = Join-Path $stagingRoot $releaseName
Copy-Item -LiteralPath $frozenDirectory -Destination $releaseDirectory -Recurse

$extractedDirectory = Join-Path $buildRoot 'webview2-extracted'
$runtimeRoot = Get-NativeOutput $expectedPython @(
    $releaseTools,
    'extract-runtime',
    '--repository-root', $repositoryRoot,
    '--webview-archive', $archivePath,
    '--destination', $extractedDirectory
)
$runtimeRoot = [IO.Path]::GetFullPath($runtimeRoot)
Copy-Item -LiteralPath $runtimeRoot -Destination (Join-Path $releaseDirectory 'runtime') -Recurse
Copy-Item -LiteralPath (Join-Path $repositoryRoot 'release\README.txt') -Destination (Join-Path $releaseDirectory 'README.txt')
Copy-Item -LiteralPath (Join-Path $repositoryRoot 'LICENSE') -Destination (Join-Path $releaseDirectory 'LICENSE')
Copy-Item -LiteralPath (Join-Path $repositoryRoot 'THIRD_PARTY_NOTICES.md') -Destination (Join-Path $releaseDirectory 'THIRD_PARTY_NOTICES.md')
if (Test-Path -LiteralPath (Join-Path $releaseDirectory 'data')) {
    throw 'The staged release directory must not contain data.'
}

Invoke-Native $expectedPython @(
    $releaseTools,
    'write-manifest',
    '--repository-root', $repositoryRoot,
    '--release-directory', $releaseDirectory
)

$smokeCopy = Join-Path $buildRoot 'smoke-copy'
Copy-Item -LiteralPath $releaseDirectory -Destination $smokeCopy -Recurse
$frozenSmoke = Join-Path $smokeCopy 'frozen-smoke.json'
$smokeArguments = "--smoke-test --json-output `"$frozenSmoke`""
$smokeProcess = Start-Process `
    -FilePath (Join-Path $smokeCopy 'GameShelf.exe') `
    -ArgumentList $smokeArguments `
    -Wait `
    -PassThru `
    -WindowStyle Hidden
if ($smokeProcess.ExitCode -ne 0) {
    throw "Frozen startup smoke failed with exit code $($smokeProcess.ExitCode)."
}
$frozenPayload = Get-Content -LiteralPath $frozenSmoke -Raw -Encoding utf8 | ConvertFrom-Json
if (
    -not $frozenPayload.ok -or
    -not $frozenPayload.frozen -or
    $frozenPayload.appVersion -ne $releaseContext.version
) {
    throw 'Frozen startup smoke report is invalid.'
}
Remove-ControlledSmokeCopy -Path $smokeCopy -BuildRoot $buildRoot

Invoke-Native $expectedPython @(
    $releaseTools,
    'verify-release',
    '--repository-root', $repositoryRoot,
    '--release-directory', $releaseDirectory
)
$archiveOutput = Join-Path $stagingRoot "$releaseName.zip"
$checksumOutput = Join-Path $stagingRoot "$releaseName.zip.sha256"
Invoke-Native $expectedPython @(
    $releaseTools,
    'build-archive',
    '--repository-root', $repositoryRoot,
    '--release-directory', $releaseDirectory,
    '--archive', $archiveOutput,
    '--checksum', $checksumOutput
)
Invoke-Native $expectedPython @(
    $releaseTools,
    'publish',
    '--repository-root', $repositoryRoot,
    '--release-directory', $releaseDirectory,
    '--archive', $archiveOutput,
    '--checksum', $checksumOutput
)

$publishedDirectory = Join-Path $repositoryRoot "dist\$releaseName"
Write-Host "GameShelf release candidate created: $publishedDirectory"
