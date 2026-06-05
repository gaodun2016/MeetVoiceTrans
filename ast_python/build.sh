#!/bin/bash

# Meet Translator 打包脚本
# 支持 macOS (.app) 和 Windows (.exe)

set -e

echo "======================================"
echo "Meet Translator 打包工具"
echo "======================================"

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 打包 macOS 应用
build_mac() {
    echo -e "${GREEN}[*] 正在打包 macOS 应用...${NC}"
    
    # 安装依赖
    echo "[*] 安装打包依赖..."
    pip3 install py2app
    
    # 执行打包
    echo "[*] 执行 py2app 打包..."
    python3 setup_mac.py py2app
    
    # 查找生成的 .app 文件
    APP_PATH=$(find dist -name "*.app" -type d 2>/dev/null | head -n 1)
    
    if [ -n "$APP_PATH" ]; then
        echo -e "${GREEN}[✓] macOS 应用打包成功！${NC}"
        echo "[*] 应用位置: $APP_PATH"
        echo "[*] 打包目录: dist/"
        
        # 创建 ZIP 压缩包
        echo "[*] 正在创建压缩包..."
        cd dist
        ZIP_NAME="MeetTranslator-macOS.zip"
        zip -r "$ZIP_NAME" "Meet Translator.app"
        echo -e "${GREEN}[✓] 压缩包已创建: dist/$ZIP_NAME${NC}"
        cd ..
    else
        echo -e "${RED}[✗] macOS 应用打包失败${NC}"
        exit 1
    fi
}

# 打包 Windows 可执行文件
build_windows() {
    echo -e "${GREEN}[*] 正在打包 Windows 可执行文件...${NC}"
    
    # 检查是否安装了葡萄
    if ! command -v wine &> /dev/null; then
        echo -e "${YELLOW}[!] 警告: 未安装 Wine，无法在 macOS 上交叉编译 Windows 版本${NC}"
        echo "[*] 请在 Windows 系统上运行此脚本，或安装 Wine"
        echo "[*] 安装 Wine: brew install --cask wine-stable"
        return 1
    fi
    
    # 安装依赖
    echo "[*] 安装打包依赖..."
    pip3 install pyinstaller
    
    # 执行打包
    echo "[*] 执行 PyInstaller 打包..."
    python3 -m PyInstaller meet_translator.spec
    
    # 查找生成的 .exe 文件
    if [ -d "dist/MeetTranslator" ]; then
        echo -e "${GREEN}[✓] Windows 可执行文件打包成功！${NC}"
        echo "[*] 应用位置: dist/MeetTranslator/MeetTranslator.exe"
        echo "[*] 打包目录: dist/MeetTranslator/"
        
        # 创建 ZIP 压缩包
        echo "[*] 正在创建压缩包..."
        cd dist
        ZIP_NAME="MeetTranslator-Windows.zip"
        zip -r "$ZIP_NAME" "MeetTranslator"
        echo -e "${GREEN}[✓] 压缩包已创建: dist/$ZIP_NAME${NC}"
        cd ..
    else
        echo -e "${RED}[✗] Windows 可执行文件打包失败${NC}"
        return 1
    fi
}

# 清理构建文件
clean() {
    echo -e "${YELLOW}[*] 清理构建文件...${NC}"
    rm -rf build dist __pycache__ *.egg-info
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete 2>/dev/null || true
    echo -e "${GREEN}[✓] 清理完成${NC}"
}

# 显示帮助信息
show_help() {
    echo "用法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  mac      打包 macOS 应用 (.app)"
    echo "  windows  打包 Windows 可执行文件 (.exe)"
    echo "  all      打包所有平台"
    echo "  clean    清理构建文件"
    echo "  help     显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  $0 mac      # 打包 macOS 版本"
    echo "  $0 windows  # 打包 Windows 版本"
    echo "  $0 all      # 打包所有平台"
    echo "  $0 clean    # 清理构建文件"
}

# 主程序
case "${1:-help}" in
    mac)
        build_mac
        ;;
    windows)
        build_windows
        ;;
    all)
        build_mac
        build_windows
        ;;
    clean)
        clean
        ;;
    help|*)
        show_help
        ;;
esac

echo ""
echo "======================================"
echo "打包完成！"
echo "======================================"
