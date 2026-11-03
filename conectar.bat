@echo off
chcp 65001 > nul
title Configurador MCP Aula Virtual UJI ^& Google Tasks
echo ========================================================
echo Iniciando asistente de configuracion...
echo ========================================================
python setup.py %*
pause
