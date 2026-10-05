@echo off
setlocal
set "ROOT=%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%ROOT%run.py" %*
  exit /b %errorlevel%
)
where python >nul 2>nul
if not errorlevel 1 (
  python "%ROOT%run.py" %*
  exit /b %errorlevel%
)
echo Python 3.11 or newer was not found. Install Python, then run this launcher again. 1>&2
exit /b 1
