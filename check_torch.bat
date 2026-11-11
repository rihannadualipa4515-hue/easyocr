@echo off
cd /d "%~dp0"
echo Python / torch diagnostic
".venv\Scripts\python.exe" -c "import sys,struct; print(sys.version); print('bits:', struct.calcsize('P')*8)"
echo.
".venv\Scripts\python.exe" -c "import torch; print('torch OK', torch.__version__)"
echo.
".venv\Scripts\python.exe" -c "import easyocr; print('easyocr OK')"
echo.
pause
