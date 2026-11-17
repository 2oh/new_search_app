@echo off
setlocal
set "pdf_index_exe=%~dp0pdf_index_update.exe"
set "pdf_index_config=%~dp0pdf_index_config.json"
if not exist "%pdf_index_exe%" (
  echo ERROR: Missing "%pdf_index_exe%"
  exit /b 2
)
if not exist "%pdf_index_config%" (
  echo ERROR: Missing "%pdf_index_config%"
  exit /b 2
)
"%pdf_index_exe%" --config "%pdf_index_config%"
set "pdf_index_exit=%errorlevel%"
echo PDF index exit code: %pdf_index_exit%
exit /b %pdf_index_exit%
