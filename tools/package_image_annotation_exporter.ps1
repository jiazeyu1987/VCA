$ErrorActionPreference = "Stop"

$packageRoot = "D:\ocr3"
$sourceRoot = if ($env:IMAGE_ANNOTATION_EXPORTER_SOURCE_ROOT -and -not [string]::IsNullOrWhiteSpace($env:IMAGE_ANNOTATION_EXPORTER_SOURCE_ROOT)) { $env:IMAGE_ANNOTATION_EXPORTER_SOURCE_ROOT } else { $packageRoot }
$artifactRoot = if ($env:IMAGE_ANNOTATION_EXPORTER_ARTIFACT_ROOT -and -not [string]::IsNullOrWhiteSpace($env:IMAGE_ANNOTATION_EXPORTER_ARTIFACT_ROOT)) { $env:IMAGE_ANNOTATION_EXPORTER_ARTIFACT_ROOT } else { $packageRoot }
$entry = Join-Path $sourceRoot "tools\image_annotation_exporter.py"
$appName = "image_annotation_exporter"
$distRoot = Join-Path $artifactRoot "dist"
$exePath = Join-Path $distRoot "$appName.exe"

if ($env:PYTHON_EXE -and -not [string]::IsNullOrWhiteSpace($env:PYTHON_EXE)) {
    $pythonExe = $env:PYTHON_EXE
}
else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw "Python command not found. Set PYTHON_EXE to the Python executable that has PyInstaller, PIL, and tkinter installed."
    }
    $pythonExe = $pythonCommand.Source
}

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

& $pythonExe -c "import PyInstaller, PIL, tkinter" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Required Python packages are missing in $pythonExe. Required imports: PyInstaller, PIL, tkinter"
}

$pythonPrefix = & $pythonExe -c "import sys; print(sys.base_prefix)"
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($pythonPrefix)) {
    throw "Failed to resolve Python base_prefix for: $pythonExe"
}
$pythonPrefix = $pythonPrefix.Trim()

$tkDllCandidates = @(
    (Join-Path $pythonPrefix "DLLs\tcl86t.dll"),
    (Join-Path (Split-Path $pythonExe -Parent) "Library\bin\tcl86t.dll")
)
$tkRuntimeCandidates = @(
    (Join-Path $pythonPrefix "DLLs\tk86t.dll"),
    (Join-Path (Split-Path $pythonExe -Parent) "Library\bin\tk86t.dll")
)
$tclDll = $tkDllCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
$tkDll = $tkRuntimeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $tclDll) {
    throw "Required tkinter runtime file not found: tcl86t.dll"
}
if (-not $tkDll) {
    throw "Required tkinter runtime file not found: tk86t.dll"
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
        "--add-binary", "$tclDll;.",
        "--add-binary", "$tkDll;.",
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
Write-Host "[OK] Image annotation exporter exe created:"
Write-Host "     $exePath"
Write-Host ("[OK] Size: {0:N2} MB" -f ($exeInfo.Length / 1MB))
