#!/bin/bash
# Redroid Manager 启动脚本
set -e

cd "$(dirname "$0")"

# 激活虚拟环境
if [ -f "$HOME/redroid-manager-venv/bin/activate" ]; then
    source "$HOME/redroid-manager-venv/bin/activate"
else
    echo "❌ 虚拟环境不存在，请先:"
    echo "   python3 -m venv ~/redroid-manager-venv"
    echo "   source ~/redroid-manager-venv/bin/activate"
    echo "   pip install flask docker"
    exit 1
fi

# 检查依赖
python3 -c "import flask, docker" 2>/dev/null || {
    echo "❌ 依赖缺失，正在安装..."
    pip install flask docker
}

echo "============================================"
echo "  Redroid Manager 启动"
echo "  访问: http://192.168.9.53:5000"
echo "  按 Ctrl+C 停止"
echo "============================================"

python3 app.py