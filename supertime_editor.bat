@echo off
rem Supertime sequence editor launcher for the control PC (Python 2.7).
rem Put this file next to the supertime_editor folder; drag a .dt4 onto it or double-click.
cd /d "%~dp0"
if exist C:\Python27\python.exe (
  C:\Python27\python.exe -m supertime_editor.app %1
) else (
  python -m supertime_editor.app %1
)
if errorlevel 1 pause
