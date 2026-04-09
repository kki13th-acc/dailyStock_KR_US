@echo off
title Stock Chart AI Analysis (US & KR)
echo ======================================================
echo  Stock Chart AI Analysis (Gemini Vision)
echo ======================================================
echo.

echo [1/2] Starting US Stock Chart Analysis...
python US/main.py

echo.
echo ------------------------------------------------------
echo [2/2] Starting KR Stock Chart Analysis...
python KR/main_kr.py

echo.
echo ======================================================
echo  All analysis completed!
echo ======================================================
pause
