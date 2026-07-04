#!/bin/bash
cd "$(dirname "$0")"

if [ -f "stock_server.pid" ]; then
    pid=$(cat stock_server.pid)
    if ps -p $pid > /dev/null; then
        echo "服务器运行中，PID: $pid"
        echo "日志文件: stock_selector.log"
        echo "最近10条日志:"
        tail -10 stock_selector.log
    else
        echo "服务器已停止（PID文件存在但进程不存在）"
        rm -f stock_server.pid
    fi
else
    echo "服务器未运行"
fi