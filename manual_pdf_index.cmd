@echo off
setlocal
if not exist "%~dp0daily_pdf_index.cmd" (
  echo ERROR: Missing "%~dp0daily_pdf_index.cmd"
  pause
  exit /b 2
)
call "%~dp0daily_pdf_index.cmd"
set "pdf_index_exit=%errorlevel%"
echo.
echo Finished. Exit code: %pdf_index_exit%
pause
exit /b %pdf_index_exit%
