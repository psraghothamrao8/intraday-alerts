@echo off
title Intraday Alert Bot - Live Engine
cd /d "%~dp0"
echo ===================================================
echo   Starting Intraday Alert Bot for NSE/BSE
echo   Telegram Bot: @daytrading_ragi_googly_101_bot
echo ===================================================
python main.py run
pause
