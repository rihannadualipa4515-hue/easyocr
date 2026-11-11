@echo off
setlocal
cd /d "%~dp0"
title OCR Text Finder - build .exe

if not exist ".venv\Scripts\python.exe" (
    py -3.11 -m venv .venv 2>nul || py -3 -m venv .venv || python -m venv .venv
    if errorlevel 1 ( echo Python 3.11+ is required. & pause & exit /b 1 )
)
call ".venv\Scripts\activate.bat"
if not exist ".venv\.deps_installed" (
    python -m pip install --upgrade pip
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu || goto :fail
    pip install -r requirements.txt || goto :fail
    echo ok> ".venv\.deps_installed"
)
pip install "pyinstaller>=6.0" || goto :fail

echo Downloading OCR models so the .exe works offline...
python tools\download_models.py || goto :fail

echo Building OCRTextFinder.exe ^(this takes several minutes^)...
pyinstaller --noconfirm --clean --onedir --windowed --name OCRTextFinder ^
    --collect-all easyocr --collect-submodules skimage --collect-submodules scipy ^
    --hidden-import PIL._tkinter_finder main.py || goto :fail

xcopy /E /I /Y data "dist\OCRTextFinder\data" >nul
xcopy /E /I /Y models "dist\OCRTextFinder\models" >nul
echo.
echo DONE:  dist\OCRTextFinder\OCRTextFinder.exe
echo Edit dist\OCRTextFinder\data\text.txt to use your own text. Copy the whole OCRTextFinder folder to move it.
pause
exit /b 0

:fail
echo.
echo Build failed - see the messages above.
pause
exit /b 1
