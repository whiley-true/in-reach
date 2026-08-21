@echo off
setlocal enabledelayedexpansion

rem Usage: install_tesseract.bat [system|user]
rem Installs Tesseract OCR via winget and adds it to the requested PATH scope.

set "SCOPE=%~1"
if /I "%SCOPE%"=="system" (
    set "WINGET_SCOPE=machine"
    set "ENV_TARGET=Machine"
) else (
    set "SCOPE=user"
    set "WINGET_SCOPE=user"
    set "ENV_TARGET=User"
)

where winget >nul 2>nul
if errorlevel 1 (
    echo winget was not found on PATH. Install the App Installer package from the Microsoft Store, then retry.
    exit /b 1
)

echo Installing Tesseract OCR ^(%SCOPE%^) via winget...
winget install --id UB-Mannheim.TesseractOCR -e --scope %WINGET_SCOPE% --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo winget install failed with exit code %errorlevel%.
    exit /b %errorlevel%
)

echo Adding Tesseract to the %ENV_TARGET% PATH...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$scope = '%ENV_TARGET%';" ^
    "$candidates = @();" ^
    "if ($scope -eq 'Machine') {" ^
    "    $candidates += (Join-Path $env:ProgramFiles 'Tesseract-OCR');" ^
    "    $candidates += (Join-Path ${env:ProgramFiles(x86)} 'Tesseract-OCR')" ^
    "} else {" ^
    "    $candidates += (Join-Path $env:LOCALAPPDATA 'Programs\Tesseract-OCR')" ^
    "};" ^
    "$tesseractDir = $candidates | Where-Object { Test-Path (Join-Path $_ 'tesseract.exe') } | Select-Object -First 1;" ^
    "if (-not $tesseractDir) { Write-Error 'Could not locate tesseract.exe after install.'; exit 1 };" ^
    "$current = [Environment]::GetEnvironmentVariable('Path', $scope);" ^
    "if (($current -split ';') -notcontains $tesseractDir) {" ^
    "    [Environment]::SetEnvironmentVariable('Path', ($current.TrimEnd(';') + ';' + $tesseractDir), $scope)" ^
    "};" ^
    "Write-Output \"Added $tesseractDir to $scope PATH.\""
if errorlevel 1 (
    echo Failed to add Tesseract to the %ENV_TARGET% PATH.
    exit /b 1
)

rem Source the updated PATH into this script's own session, in case a
rem later step in the same process needs tesseract on PATH.
for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')"`) do set "PATH=%%A"

echo Tesseract OCR installed and added to the %ENV_TARGET% PATH.
exit /b 0
