$ErrorActionPreference = "Stop"

$packageRoot = "D:\ocr3"
$packageScript = Join-Path $packageRoot "package_pywrapper_server.bat"
$stopScript = Join-Path $packageRoot "closeserver.bat"
$releaseSourceDir = Join-Path $packageRoot "dist\OCRSERVER"
$releaseRepo = "D:\ocr3\VA"
$commitMessage = "release: OCRSERVER $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

Write-Host "[INFO] Package root: $packageRoot"
Write-Host "[INFO] Stop script: $stopScript"
Write-Host "[INFO] Release source: $releaseSourceDir"
Write-Host "[INFO] Release repo: $releaseRepo"

if (-not (Test-Path $packageScript)) {
    throw "Package script not found: $packageScript"
}
if (-not (Test-Path $stopScript)) {
    throw "Stop script not found: $stopScript"
}
if (-not (Test-Path $releaseRepo)) {
    throw "Release repo not found: $releaseRepo"
}
if (-not (Test-Path (Join-Path $releaseRepo ".git"))) {
    throw "Release repo is missing .git: $releaseRepo"
}

$repoTop = git -C $releaseRepo rev-parse --show-toplevel
if ($LASTEXITCODE -ne 0) {
    throw "Failed to resolve git toplevel for: $releaseRepo"
}
$resolvedRepoTop = [System.IO.Path]::GetFullPath($repoTop).TrimEnd('\')
$resolvedReleaseRepo = [System.IO.Path]::GetFullPath($releaseRepo).TrimEnd('\')
if ($resolvedRepoTop -ne $resolvedReleaseRepo) {
    throw "Release repo root mismatch: expected $resolvedReleaseRepo but git reported $resolvedRepoTop"
}

$dirty = git -C $releaseRepo status --porcelain
if ($LASTEXITCODE -ne 0) {
    throw "Failed to read git status for: $releaseRepo"
}
if (-not [string]::IsNullOrWhiteSpace($dirty)) {
    throw "Release repo is not clean: $releaseRepo"
}

& $stopScript
if ($LASTEXITCODE -ne 0) {
    throw "Stop script failed with exit code $LASTEXITCODE"
}

& $packageScript
if ($LASTEXITCODE -ne 0) {
    throw "Packaging failed with exit code $LASTEXITCODE"
}

if (-not (Test-Path $releaseSourceDir)) {
    throw "Release source directory not found after packaging: $releaseSourceDir"
}

Get-ChildItem -LiteralPath $releaseRepo -Force |
    Where-Object { $_.Name -ne ".git" } |
    Remove-Item -Recurse -Force

Get-ChildItem -LiteralPath $releaseSourceDir -Force |
    Copy-Item -Destination $releaseRepo -Recurse -Force

git -C $releaseRepo add -A
if ($LASTEXITCODE -ne 0) {
    throw "git add failed for: $releaseRepo"
}

$staged = git -C $releaseRepo diff --cached --name-only
if ($LASTEXITCODE -ne 0) {
    throw "Failed to inspect staged changes for: $releaseRepo"
}
if ([string]::IsNullOrWhiteSpace($staged)) {
    Write-Host "[INFO] No publish changes detected; skipping commit and push."
    exit 0
}

git -C $releaseRepo commit -m $commitMessage
if ($LASTEXITCODE -ne 0) {
    throw "git commit failed for: $releaseRepo"
}

git -C $releaseRepo push -u origin HEAD:main
if ($LASTEXITCODE -ne 0) {
    throw "git push failed for: $releaseRepo"
}

$head = git -C $releaseRepo rev-parse --short HEAD
if ($LASTEXITCODE -ne 0) {
    throw "Failed to read published commit id for: $releaseRepo"
}

Write-Host "[OK] Published OCRSERVER release commit: $head"
