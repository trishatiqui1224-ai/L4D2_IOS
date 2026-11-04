@echo off
rem ==============================================================================
rem Left 4 Dead 2 Recomp - Optional Steam / Community Asset Fetcher
rem ==============================================================================
echo [L4D2 Recomp] Checking for SteamCMD / optional PC asset tooling...

if exist "%~dp0..\..\Left 4 Dead 2" (
    echo [L4D2 Recomp] Found local Left 4 Dead 2 PC installation at %~dp0..\..\Left 4 Dead 2
    goto done
)

echo [L4D2 Recomp] Note: Xbox 360 World Disc assets (Title 454108D4) are the primary
echo [L4D2 Recomp] target for L4D2 Recomp. Steam assets can optionally supplement
echo [L4D2 Recomp] high-resolution UI fonts and uncompressed sound caches.

:done
echo [L4D2 Recomp] Setup completed.
exit /b 0

