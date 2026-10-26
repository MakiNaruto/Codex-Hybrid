@echo off
rem Compatibility entry point for existing installations.
call "%~dp0codex-hybrid.cmd" %*
exit /b %errorlevel%
