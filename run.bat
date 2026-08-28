@echo off
REM LunarSerpent launcher -- see run.py for options.
REM   run              start the interface
REM   run --check      preflight only
REM   run --test       run the test suite first
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel%==0 (
    py -3 run.py %*
) else (
    python run.py %*
)
endlocal
