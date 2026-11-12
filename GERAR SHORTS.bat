@echo off
title Area Pequena - gerando shorts
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
".venv\Scripts\python.exe" -u gerar.py
echo.
echo Pronto! Abra saida\dia-XX\painel.html
pause
