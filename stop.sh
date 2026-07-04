#!/bin/bash
cd "$(dirname "$0")"

if [ -f "stock_server.pid" ]; then
    kill $(cat stock_server.pid) 2>/dev/null
    rm -f stock_server.pid
    echo "A股选股服务器已停止"
else
    echo "服务器未运行"
fi