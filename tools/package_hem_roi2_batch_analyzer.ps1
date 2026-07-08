$ErrorActionPreference = "Stop"

$packageRoot = "D:\ocr3"
$sourceRoot = if ($env:HEM_ROI2_SOURCE_ROOT -and -not [string]::IsNullOrWhiteSpace($env:HEM_ROI2_SOURCE_ROOT)) { $env:HEM_ROI2_SOURCE_ROOT } else { $packageRoot }
$artifactRoot = if ($env:HEM_ROI2_ARTIFACT_ROOT -and -not [string]::IsNullOrWhiteSpace($env:HEM_ROI2_ARTIFACT_ROOT)) { $env:HEM_ROI2_ARTIFACT_ROOT } else { $packageRoot }
$entry = Join-Path $sourceRoot "tools\hem_roi2_batch_analyzer.py"
$runtimeRoot = Join-Path $sourceRoot "resource\pywrapper"
$settingsPath = Join-Path $sourceRoot "settings"
$appName = "hem_roi2_batch_analyzer"
$distRoot = Join-Path $artifactRoot "dist"
$exePath = Join-Path $distRoot ($appName + ".exe")

if (-not $env:PYTHON_EXE -or [string]::IsNullOrWhiteSpace($env:PYTHON_EXE)) {
    $env:PYTHON_EXE = "D:\miniconda3\envs\houyang\python.exe"
}
$pythonExe = $env:PYTHON_EXE

Write-Host "[INFO] Package root: $packageRoot"
Write-Host "[INFO] Source root: $sourceRoot"
Write-Host "[INFO] Artifact root: $artifactRoot"
Write-Host "[INFO] Python: $pythonExe"
Write-Host "[INFO] Entry: $entry"

if (-not (Test-Path $pythonExe)) {
    throw "Python not found: $pythonExe"
}
if (-not (Test-Path $entry)) {
    throw "Entry script not found: $entry"
}
if (-not (Test-Path $runtimeRoot)) {
    throw "Pywrapper runtime directory not found: $runtimeRoot"
}
if (-not (Test-Path $settingsPath)) {
    throw "Settings file not found: $settingsPath"
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

& $pythonExe -c "import PyInstaller, PIL, openpyxl, numpy, tkinter" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Required Python packages are missing in $pythonExe. Required imports: PyInstaller, PIL, openpyxl, numpy, tkinter"
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
        "--paths", (Join-Path $sourceRoot "resource\pywrapper"),
        "--paths", $sourceRoot,
        "--distpath", $distRoot,
        "--workpath", $workPath,
        "--specpath", $specPath,
        "--hidden-import", "api_server",
        "--hidden-import", "openpyxl",
        "--hidden-import", "openpyxl.cell._writer",
        "--add-data", "$settingsPath;.",
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
$sidecarSettingsPath = Join-Path $distRoot "settings"
Copy-Item -LiteralPath $settingsPath -Destination $sidecarSettingsPath -Force
if (-not (Test-Path $sidecarSettingsPath)) {
    throw "Settings sidecar file was not copied next to exe: $sidecarSettingsPath"
}
Write-Host "[OK] HEM ROI2 batch analyzer exe created:"
Write-Host "     $exePath"
Write-Host "[OK] Settings sidecar copied:"
Write-Host "     $sidecarSettingsPath"
Write-Host ("[OK] Size: {0:N2} MB" -f ($exeInfo.Length / 1MB))
