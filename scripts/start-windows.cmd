@echo off
call "%~dp0codex-model-bridge.cmd" install
set MODEL_ROUTER_RESULT=%errorlevel%
echo.
pause
exit /b %MODEL_ROUTER_RESULT%
