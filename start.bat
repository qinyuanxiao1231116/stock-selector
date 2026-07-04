@echo off
cd /d "%~dp0"
start /min python stock_server.py
echo A股选股服务器已启动
pause