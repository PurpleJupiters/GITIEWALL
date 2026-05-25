@echo off
setlocal

set PYTHON=C:\Dev\envs\sunomaster\python.exe
set SCRIPT=E:\SunoMaster\scripts\sunomaster_v54_final.py
set INPUT=C:\Users\equat\Downloads\Transfinite (Agent WALL) Master.wav
set VOCAL=C:\Users\equat\Desktop\MUSIC OUTPUT\Latest Mastered Songs\AUDIMEE VOCAL DOWNLOADS\Transfinite (Agent WALL) Master_click_133.9bpm_Hailey\Transfinite_vocals_Hailey.wav
set REF=E:\SunoMaster\references\normalized reference tracks\# Guy J - Worlds Apart (Original Mix) Normalized -8 LUFS.wav
set OUTPUT=E:\SunoMaster\output
set LOG=E:\SunoMaster\logs\hailey_remaster.log

if not exist "E:\SunoMaster\logs" mkdir "E:\SunoMaster\logs"

echo [%DATE% %TIME%] Starting Hailey re-master... > "%LOG%"
echo Input:  %INPUT% >> "%LOG%"
echo Vocal:  %VOCAL% >> "%LOG%"
echo. >> "%LOG%"

"%PYTHON%" -u "%SCRIPT%" ^
    --input "%INPUT%" ^
    --reference "%REF%" ^
    --output "%OUTPUT%" ^
    --vocal "%VOCAL%" ^
    --reuse-stems >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo [%DATE% %TIME%] Pipeline exited with code %ERRORLEVEL% >> "%LOG%"
