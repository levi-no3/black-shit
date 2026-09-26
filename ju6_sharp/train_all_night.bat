@echo off
REM Overnight GPT training: loops resume chunks until you close the window.
REM Best weights only (never regresses). Close window to stop.
cd /d "%~dp0"
title ju6 GPT overnight training
:loop
start "" /belownormal /wait python -u train_gpt.py --steps 120 --batch 16 --lr 2e-4 --resume
echo Chunk done at %TIME%. Looping in 5s... (close window to stop)
timeout /t 5 >nul
goto loop
