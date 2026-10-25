@echo off
rem Compatibility entry point for existing installations.
call "%~dp0codex-model-bridge.cmd" %*
exit /b %errorlevel%
