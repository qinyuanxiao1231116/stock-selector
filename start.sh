#!/bin/bash
cd "$(dirname "$0")"

if [ -d "venv" ]; then
    source venv/bin/activate
fi

nohup python stock_server.py > /dev/null 2>&1 &
echo $! > stock_server.pid
echo "A股选股服务器已启动，PID: $(cat stock_server.pid)"