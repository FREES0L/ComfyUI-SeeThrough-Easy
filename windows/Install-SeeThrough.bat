@echo off
title SeeThrough installer
echo Downloading and running the SeeThrough installer...
echo This takes a while (about 15 GB to download). Leave this window open.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/FREES0L/ComfyUI-SeeThrough-Easy/master/windows/install.ps1 | iex"
echo.
pause
