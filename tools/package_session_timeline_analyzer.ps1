$ErrorActionPreference = "Stop"

$packageRoot = "D:\ocr3"
$sourceRoot = if ($env:SESSION_ANALYZER_SOURCE_ROOT -and -not [string]::IsNullOrWhiteSpace($env:SESSION_ANALYZER_SOURCE_ROOT)) { $env:SESSION_ANALYZER_SOURCE_ROOT } else { $packageRoot }
$artifactRoot = if ($env:SESSION_ANALYZER_ARTIFACT_ROOT -and -not [string]::IsNullOrWhiteSpace($env:SESSION_ANALYZER_ARTIFACT_ROOT)) { $env:SESSION_ANALYZER_ARTIFACT_ROOT } else { $packageRoot }
$entry = Join-Path $sourceRoot "tools\session_timeline_analyzer.py"
$appName = "session_timeline_analyzer"
$distRoot = Join-Path $artifactRoot "dist"
$exePath = Join-Path $distRoot "session_timeline_analyzer.exe"

if (-not $env:PYTHON_EXE -or [string]::IsNullOrWhiteSpace($env:PYTHON_EXE)) {
    $env:PYTHON_EXE = "D:\miniconda3\envs\houyang\python.exe"
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

$pythonDir = Split-Path $pythonExe -Parent
$condaBin = Join-Path $pythonDir "Library\bin"
$requiredCondaFiles = @(
    "ffi.dll",
    "libbz2.dll",
    "libcrypto-3-x64.dll",
    "libexpat.dll",
    "liblzma.dll",
    "libssl-3-x64.dll",
    "sqlite3.dll",
    "tcl86t.dll",
    "tk86t.dll"
)
foreach ($name in $requiredCondaFiles) {
    $path = Join-Path $condaBin $name
    if (-not (Test-Path $path)) {
        throw "Required conda runtime file not found: $path"
    }
}

& $pythonExe -c "import PyInstaller, PIL, tkinter" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Required Python packages are missing in $pythonExe. Required imports: PyInstaller, PIL, tkinter"
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
        "--add-binary", "$condaBin\ffi.dll;.",
        "--add-binary", "$condaBin\libbz2.dll;.",
        "--add-binary", "$condaBin\libcrypto-3-x64.dll;.",
        "--add-binary", "$condaBin\libexpat.dll;.",
        "--add-binary", "$condaBin\liblzma.dll;.",
        "--add-binary", "$condaBin\libssl-3-x64.dll;.",
        "--add-binary", "$condaBin\sqlite3.dll;.",
        "--add-binary", "$condaBin\tcl86t.dll;.",
        "--add-binary", "$condaBin\tk86t.dll;.",
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
