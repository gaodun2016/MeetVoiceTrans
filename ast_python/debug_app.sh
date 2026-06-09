#!/bin/bash

# 查看打包应用的详细错误日志

APP_PATH="dist/Meet Translator.app"

if [ ! -d "$APP_PATH" ]; then
    echo "错误：应用不存在：$APP_PATH"
    echo "请先运行打包：./build.sh mac"
    exit 1
fi

echo "======================================"
echo "查看 Meet Translator 启动错误日志"
echo "======================================"
echo ""

# 尝试启动应用并捕获错误
echo "尝试启动应用..."
open -W "$APP_PATH" 2>&1 | tee /tmp/meet_translator_error.log

echo ""
echo "======================================"
echo "错误日志已保存到：/tmp/meet_translator_error.log"
echo "======================================"

# 查看控制台日志
echo ""
echo "最近的控制台日志："
log show --predicate 'process == "Meet Translator"' --last 5m --info 2>/dev/null | tail -20
