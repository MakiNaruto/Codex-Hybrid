@echo off
call "%~dp0codex-hybrid.cmd" install
set MODEL_ROUTER_RESULT=%errorlevel%
echo.
pause
exit /b %MODEL_ROUTER_RESULT%
