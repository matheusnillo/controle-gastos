@echo off
rem Faz o Controle de Gastos abrir sozinho (sem janela) sempre que voce entrar no Windows,
rem para os alertas de WhatsApp e o app do celular funcionarem sem precisar abrir nada.
rem Para desfazer: schtasks /delete /tn "ControleDeGastos" /f
cd /d "%~dp0"
if not exist .env copy .env.example .env >nul
for /f "delims=" %%p in ('py -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set PYW=%%p
if not exist "%PYW%" (
  echo Nao encontrei o pythonw.exe. Verifique se o Python esta instalado.
  pause
  exit /b 1
)
schtasks /create /tn "ControleDeGastos" /sc onlogon /rl limited /f /tr "\"%PYW%\" \"%~dp0app.py\" --no-browser"
if errorlevel 1 (
  echo Nao foi possivel criar a tarefa.
) else (
  echo Pronto! O app vai iniciar sozinho no proximo login.
  echo Iniciando agora em segundo plano...
  start "" "%PYW%" "%~dp0app.py" --no-browser
  echo Acesse no computador: http://127.0.0.1:8765
)
pause
