@echo off
rem Publica o app no GitHub (modo nuvem). Veja o README, secao "Modo nuvem".
cd /d "%~dp0"
py -m pip install --user --quiet cryptography pynacl
py publicar_nuvem.py
pause
