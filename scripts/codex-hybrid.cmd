@echo off
setlocal
set PYTHONUTF8=1
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 "%~dp0launch.py" %*
exit /b %errorlevel%
:use_python
where python >nul 2>nul
if errorlevel 1 goto missing
python "%~dp0launch.py" %*
exit /b %errorlevel%
:missing
echo Python 3.11+ is required. Install from https://www.python.org/downloads/windows/
echo Enable the Python launcher or add Python to PATH during installation.
exit /b 1
