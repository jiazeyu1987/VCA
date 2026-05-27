$ErrorActionPreference = "Stop"

$packageRoot = "D:\ocr3"
$runtimeRoot = Join-Path $packageRoot "resource\pywrapper"
$sourceRoot = if ($env:PYWRAPPER_SOURCE_ROOT -and -not [string]::IsNullOrWhiteSpace($env:PYWRAPPER_SOURCE_ROOT)) { $env:PYWRAPPER_SOURCE_ROOT } else { $packageRoot }
$artifactRoot = if ($env:PYWRAPPER_ARTIFACT_ROOT -and -not [string]::IsNullOrWhiteSpace($env:PYWRAPPER_ARTIFACT_ROOT)) { $env:PYWRAPPER_ARTIFACT_ROOT } else { $packageRoot }
$entry = Join-Path $sourceRoot "resource\pywrapper\api_server.py"
$appName = "pywrapper_api_server"
$distRoot = Join-Path $artifactRoot "dist"
$distDir = Join-Path $distRoot $appName
$zipPath = Join-Path $distRoot ($appName + ".zip")
$compatAppName = "ocrapp_pureray"
$compatDistDir = Join-Path $distRoot "OCRSERVER"
$compatZipPath = Join-Path $distRoot "OCRSERVER.zip"

if (-not $env:VEIN_MAIN_DIR -or [string]::IsNullOrWhiteSpace($env:VEIN_MAIN_DIR)) {
    $env:VEIN_MAIN_DIR = "D:\ProjectPackage\Vein\sqw\Vein"
}
if (-not $env:DEPLOY_TO_VEIN_MAIN -or [string]::IsNullOrWhiteSpace($env:DEPLOY_TO_VEIN_MAIN)) {
    $env:DEPLOY_TO_VEIN_MAIN = "1"
}
$veinMainDir = $env:VEIN_MAIN_DIR
$deployToVeinMain = $env:DEPLOY_TO_VEIN_MAIN
$veinOcrServerDir = Join-Path $veinMainDir "OCRSERVER"

if (-not $env:PYTHON_EXE -or [string]::IsNullOrWhiteSpace($env:PYTHON_EXE)) {
    $env:PYTHON_EXE = "D:\miniconda3\envs\houyang\python.exe"
}
$pythonExe = $env:PYTHON_EXE

Write-Host "[INFO] Package root: $packageRoot"
Write-Host "[INFO] Runtime root: $runtimeRoot"
Write-Host "[INFO] Source root: $sourceRoot"
Write-Host "[INFO] Artifact root: $artifactRoot"
Write-Host "[INFO] Python: $pythonExe"
Write-Host "[INFO] Main program dir: $veinMainDir"
Write-Host "[INFO] Deploy to main program: $deployToVeinMain"

if (-not (Test-Path $pythonExe)) {
    throw "Python not found: $pythonExe"
}
if (-not (Test-Path $entry)) {
    throw "Entry script not found: $entry"
}

$requiredRuntimeFiles = @(
    "PyMobileComm.pyd",
    "MobileCommunication.dll",
    "AdbWinApi.dll",
    "AdbWinUsbApi.dll",
    "D3DX9_43.dll",
    "DicomContol_Factory.dll",
    "Ijwhost.dll",
    "opencv_world440.dll",
    "Company.ini",
    "license"
)
foreach ($name in $requiredRuntimeFiles) {
    $path = Join-Path $runtimeRoot $name
    if (-not (Test-Path $path)) {
        throw "Required runtime file not found: $path"
    }
}

$settingsPath = Join-Path $sourceRoot "settings"
if (-not (Test-Path $settingsPath)) {
    throw "Settings file not found: $settingsPath"
}
$releaseSupportFiles = @(
    (Join-Path $packageRoot "closeserver.bat"),
    (Join-Path $packageRoot "restart_server.bat"),
    (Join-Path $packageRoot "test_ocr_client.exe")
)
foreach ($path in $releaseSupportFiles) {
    if (-not (Test-Path $path)) {
        throw "Required release support file not found: $path"
    }
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
    "sqlite3.dll"
)
foreach ($name in $requiredCondaFiles) {
    $path = Join-Path $condaBin $name
    if (-not (Test-Path $path)) {
        throw "Required conda runtime file not found: $path"
    }
}

& $pythonExe -c "import PyInstaller" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is not installed in $pythonExe"
}

$workPath = Join-Path $artifactRoot ("build\" + $appName)
$specPath = $workPath

Push-Location $sourceRoot
try {
    $args = @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name", $appName,
        "--paths", (Join-Path $sourceRoot "resource\pywrapper"),
        "--paths", $sourceRoot,
        "--distpath", $distRoot,
        "--workpath", $workPath,
        "--specpath", $specPath,
        "--hidden-import", "PyMobileComm",
        "--add-binary", "$runtimeRoot\PyMobileComm.pyd;.",
        "--add-binary", "$runtimeRoot\MobileCommunication.dll;.",
        "--add-binary", "$runtimeRoot\AdbWinApi.dll;.",
        "--add-binary", "$runtimeRoot\AdbWinUsbApi.dll;.",
        "--add-binary", "$runtimeRoot\D3DX9_43.dll;.",
        "--add-binary", "$runtimeRoot\DicomContol_Factory.dll;.",
        "--add-binary", "$runtimeRoot\Ijwhost.dll;.",
        "--add-binary", "$runtimeRoot\opencv_world440.dll;.",
        "--add-binary", "$condaBin\ffi.dll;.",
        "--add-binary", "$condaBin\libbz2.dll;.",
        "--add-binary", "$condaBin\libcrypto-3-x64.dll;.",
        "--add-binary", "$condaBin\libexpat.dll;.",
        "--add-binary", "$condaBin\liblzma.dll;.",
        "--add-binary", "$condaBin\libssl-3-x64.dll;.",
        "--add-binary", "$condaBin\sqlite3.dll;.",
        "--add-data", "$runtimeRoot\Company.ini;.",
        "--add-data", "$runtimeRoot\license;.",
        "--add-data", "$settingsPath;.",
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

$exePath = Join-Path $distDir ($appName + ".exe")
if (-not (Test-Path $exePath)) {
    throw "Build finished but exe was not found: $exePath"
}

foreach ($name in @("Company.ini", "AdbWinApi.dll", "AdbWinUsbApi.dll")) {
    Copy-Item -LiteralPath (Join-Path $runtimeRoot $name) -Destination (Join-Path $distDir $name) -Force
}
Copy-Item -LiteralPath (Join-Path $condaBin "sqlite3.dll") -Destination (Join-Path $distDir "sqlite3.dll") -Force
Copy-Item -LiteralPath $settingsPath -Destination (Join-Path $distDir "settings") -Force

Write-Host "[OK] Server exe created:"
Write-Host "     $exePath"

if (Test-Path $compatDistDir) {
    Remove-Item -LiteralPath $compatDistDir -Recurse -Force
}
Copy-Item -LiteralPath $distDir -Destination $compatDistDir -Recurse
Rename-Item -LiteralPath (Join-Path $compatDistDir ($appName + ".exe")) -NewName ($compatAppName + ".exe")
foreach ($path in $releaseSupportFiles) {
    Copy-Item -LiteralPath $path -Destination (Join-Path $compatDistDir (Split-Path $path -Leaf)) -Force
}

$compatExePath = Join-Path $compatDistDir ($compatAppName + ".exe")
if (-not (Test-Path $compatExePath)) {
    throw "Compatible exe was not found: $compatExePath"
}

Write-Host "[OK] Main-program compatible server exe created:"
Write-Host "     $compatExePath"

if ($deployToVeinMain -eq "1") {
    if (-not (Test-Path $veinMainDir)) {
        throw "Main program directory not found: $veinMainDir"
    }
    if (Test-Path $veinOcrServerDir) {
        Remove-Item -LiteralPath $veinOcrServerDir -Recurse -Force
    }
    Copy-Item -LiteralPath $compatDistDir -Destination $veinOcrServerDir -Recurse
    $deployedExe = Join-Path $veinOcrServerDir ($compatAppName + ".exe")
    if (-not (Test-Path $deployedExe)) {
        throw "Main-program deployment finished but exe was not found: $deployedExe"
    }
    Write-Host "[OK] Main-program OCRSERVER deployed:"
    Write-Host "     $deployedExe"
}

foreach ($zip in @($zipPath, $compatZipPath)) {
    if (Test-Path $zip) {
        Remove-Item -LiteralPath $zip -Force
    }
}

Compress-Archive -LiteralPath $distDir -DestinationPath $zipPath -CompressionLevel Optimal
Compress-Archive -LiteralPath $compatDistDir -DestinationPath $compatZipPath -CompressionLevel Optimal

if (-not (Test-Path $zipPath)) {
    throw "Zip command finished but file was not found: $zipPath"
}
if (-not (Test-Path $compatZipPath)) {
    throw "Compatible zip command finished but file was not found: $compatZipPath"
}

Write-Host "[OK] Zip created:"
Write-Host "     $zipPath"
Write-Host "[OK] Main-program compatible zip created:"
Write-Host "     $compatZipPath"
