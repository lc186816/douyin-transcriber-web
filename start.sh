#!/bin/bash
# 一键启动: ./start.sh   （自动使用项目虚拟环境）
cd "$(dirname "$0")"
if [ -x .venv/bin/python ]; then
    exec .venv/bin/python app.py
else
    exec python3 app.py
fi
