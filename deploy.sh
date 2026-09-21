#!/bin/bash

echo "=== 开始部署A股选股服务器 ==="

set -e

WORK_DIR="/opt/stock_selector"
REPO_URL="${1:-}"  # 第一个参数为 Git 仓库地址

if [ -z "$REPO_URL" ]; then
    echo "错误: 请提供 Git 仓库地址"
    echo "用法: bash deploy.sh <git_repo_url>"
    echo "示例: bash deploy.sh https://github.com/yourname/Bas2Excel.git"
    exit 1
fi

echo "1. 安装系统依赖..."
apt update -y
apt install python3 python3-pip git -y

echo "2. 克隆代码..."
if [ -d "$WORK_DIR/.git" ]; then
    echo "  仓库已存在，拉取最新代码..."
    cd $WORK_DIR
    git pull
else
    git clone "$REPO_URL" $WORK_DIR
    cd $WORK_DIR
fi

echo "3. 安装 Python 依赖..."
pip3 install -r requirements.txt

echo "4. 配置 config.py..."
if [ ! -f "$WORK_DIR/config.py" ]; then
    cp $WORK_DIR/config.py.example $WORK_DIR/config.py
    echo "  已创建 config.py（从模板复制），请编辑填入实际 SendKey："
    echo "  vi $WORK_DIR/config.py"
    echo ""
    echo "  必须设置 SEND_KEY 后服务才能正常推送消息！"
    echo ""
    read -p "  是否现在配置？(y/n): " configure_now
    if [ "$configure_now" = "y" ] || [ "$configure_now" = "Y" ]; then
        read -p "  请输入 Server酱 SendKey: " send_key
        sed -i "s/YOUR_SEND_KEY_HERE/$send_key/" $WORK_DIR/config.py
        echo "  SendKey 已配置"
    fi
else
    echo "  config.py 已存在，同步选股策略阈值（SEND_KEYS / WXPUSHER 等密钥保持不变）..."
    # config.py 在 .gitignore 中不会随 git pull 更新，这里以 config.py.example 为准，
    # 仅强制同步非密钥的策略阈值；密钥项（SEND_KEYS、WXPUSHER_*）一律保留用户现有值。
    for key in AUCTION_AMOUNT_THRESHOLD AUCTION_GAIN_MIN AUCTION_GAIN_MAX \
               AUCTION_GAIN_DIFF_THRESHOLD AUCTION_FLOAT_MV_MAX \
               LATE_SCHEME1_LOOKBACK_DAYS LATE_SCHEME1_VOLUME_RATIO \
               LATE_SCHEME2_MIN_BULLISH_DAYS LATE_SCHEME2_MA_PERIOD \
               LATE_LOOKBACK_DAYS LOG_FILE; do
        example_line=$(grep -E "^${key}[[:space:]]*=" "$WORK_DIR/config.py.example" | head -1)
        [ -z "$example_line" ] && continue
        new_value=$(echo "$example_line" | sed -E "s/^${key}[[:space:]]*=[[:space:]]*//")
        if grep -qE "^${key}[[:space:]]*=" "$WORK_DIR/config.py"; then
            # 键已存在：更新为 example 中的最新值（用 | 作分隔符，策略值不含 |）
            sed -i -E "s|^${key}[[:space:]]*=.*|${key} = ${new_value}|" "$WORK_DIR/config.py"
        else
            # 键不存在：追加 example 整行
            echo "$example_line" >> "$WORK_DIR/config.py"
        fi
    done
    echo "  策略阈值已同步（密钥项未改动），请确认 SEND_KEYS 仍正确"
fi

echo "5. 设置脚本权限..."
chmod +x $WORK_DIR/start.sh $WORK_DIR/stop.sh $WORK_DIR/status.sh

echo "6. 配置 systemd 服务..."
cat > /etc/systemd/system/stock_selector.service << 'EOF'
[Unit]
Description=Stock Selector Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/stock_selector
ExecStart=/usr/bin/python3 stock_server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable stock_selector

echo "7. 启动服务..."
systemctl start stock_selector

echo ""
echo "=== 部署完成 ==="
echo ""
systemctl status stock_selector --no-pager || true
echo ""
echo "常用命令:"
echo "  查看状态:  systemctl status stock_selector"
echo "  查看日志:  tail -f $WORK_DIR/stock_selector.log"
echo "  停止服务:  systemctl stop stock_selector"
echo "  重启服务:  systemctl restart stock_selector"
echo "  更新代码:  cd $WORK_DIR && git pull && systemctl restart stock_selector"
echo "  修改配置:  vi $WORK_DIR/config.py && systemctl restart stock_selector"
