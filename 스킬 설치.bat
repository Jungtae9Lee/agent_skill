@echo off
title Skill installer
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0site\start-installer.ps1"
if errorlevel 1 pause
