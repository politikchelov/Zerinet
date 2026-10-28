@echo off
chcp 65001 >nul
echo Зарегистрированные пользователи:
where py >nul 2>nul && (py server.py users & goto :ask)
where python >nul 2>nul && (python server.py users & goto :ask)
echo Не найден Python.
pause
exit /b
:ask
echo.
set /p NICK=Впиши ник из списка, которого сделать админом: 
where py >nul 2>nul && (py server.py admin %NICK% & goto :done)
python server.py admin %NICK%
:done
pause
