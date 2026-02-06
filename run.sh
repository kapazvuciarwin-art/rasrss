#!/bin/bash
# rasrss 啟動腳本：先安裝依賴再啟動，並顯示網址
cd "$(dirname "$0")"

# 若有 venv 則使用
if [ -d "venv" ] && [ -x "venv/bin/python" ]; then
    PY="venv/bin/python"
    [ ! -f "venv/.installed" ] && venv/bin/pip install -q -r requirements.txt && touch venv/.installed
else
    PY="python3"
fi

# 檢查能否載入
if ! $PY -c "from app import app" 2>/dev/null; then
    echo "依賴未安裝，請先執行："
    echo "  pip install -r requirements.txt"
    echo "或："
    echo "  python3 -m venv venv && ./venv/bin/pip install -r requirements.txt"
    exit 1
fi

echo "啟動 rasrss，請在瀏覽器開啟："
echo "  http://127.0.0.1:5001"
echo "或從其他裝置： http://$(hostname -I 2>/dev/null | awk '{print $1}'):5001"
echo "---"
exec $PY app.py
