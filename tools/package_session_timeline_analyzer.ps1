param(
    [switch]$PreflightOnly
)

$ErrorActionPreference = "Stop"

$packageRoot = "D:\ocr3"
$sourceRoot = if ($env:SESSION_ANALYZER_SOURCE_ROOT -and -not [string]::IsNullOrWhiteSpace($env:SESSION_ANALYZER_SOURCE_ROOT)) { $env:SESSION_ANALYZER_SOURCE_ROOT } else { $packageRoot }
$artifactRoot = if ($env:SESSION_ANALYZER_ARTIFACT_ROOT -and -not [string]::IsNullOrWhiteSpace($env:SESSION_ANALYZER_ARTIFACT_ROOT)) { $env:SESSION_ANALYZER_ARTIFACT_ROOT } else { $packageRoot }
$entry = Join-Path $sourceRoot "tools\session_timeline_analyzer.py"
$appName = "session_timeline_analyzer"
$distRoot = Join-Path $artifactRoot "dist"
$exePath = Join-Path $distRoot "session_timeline_analyzer.exe"

if (-not $env:PYTHON_EXE -or [string]::IsNullOrWhiteSpace($env:PYTHON_EXE)) {
    $env:PYTHON_EXE = "D:\Python39\python.exe"
}
$pythonExe = $env:PYTHON_EXE

Write-Host "[INFO] Package root: $packageRoot"
Write-Host "[INFO] Source root: $sourceRoot"
Write-Host "[INFO] Artifact root: $artifactRoot"
Write-Host "[INFO] Python: $pythonExe"

if (-not (Test-Path $pythonExe)) {
    throw "Python not found: $pythonExe"
}
if (-not (Test-Path $entry)) {
    throw "Entry script not found: $entry"
}

& $pythonExe -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 9) and sys.maxsize > 2**32 else 1)" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Standalone 64-bit Python 3.9 is required: $pythonExe"
}

& $pythonExe -c "import PyInstaller, PIL, tkinter" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Required Python packages are missing in $pythonExe. Required imports: PyInstaller, PIL, tkinter"
}

Write-Host "[OK] Session timeline analyzer packaging preflight passed."
if ($PreflightOnly) {
    return
}

$workPath = Join-Path $artifactRoot ("build\" + $appName)
$specPath = $workPath

if (Test-Path $exePath) {
    Remove-Item -LiteralPath $exePath -Force
}

Push-Location $sourceRoot
try {
    $args = @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name", $appName,
        "--paths", $sourceRoot,
        "--distpath", $distRoot,
        "--workpath", $workPath,
        "--specpath", $specPath,
        $entry
    )
    & $pythonExe @args
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

if (-not (Test-Path $exePath)) {
    throw "Build finished but exe was not found: $exePath"
}

$exeInfo = Get-Item -LiteralPath $exePath
Write-Host "[OK] Session timeline analyzer exe created:"
Write-Host "     $exePath"
Write-Host ("[OK] Size: {0:N2} MB" -f ($exeInfo.Length / 1MB))
