@echo off
chcp 65001 >nul
where py >nul 2>nul && (py server.py & goto :eof)
where python >nul 2>nul && (python server.py & goto :eof)
echo Не найден Python. Установи его с python.org (галочка Add to PATH) или открой index.html двойным кликом.
pause
