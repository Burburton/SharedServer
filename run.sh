#!/bin/bash

# 设置颜色输出
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "       文件共享服务器启动脚本 (macOS/Linux)"
echo "════════════════════════════════════════════════════════════════"
echo ""

# 检查Python是否安装
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ 错误: 系统未安装Python3${NC}"
    echo "macOS安装方法:"
    echo "  brew install python3"
    echo "或访问 https://www.python.org/downloads/ 下载安装"
    exit 1
fi

echo -e "${GREEN}✅ 检测到Python安装${NC}"
python3 --version

# 检查pip是否可用
if ! command -v pip3 &> /dev/null; then
    echo -e "${RED}❌ 错误: pip3 未安装${NC}"
    exit 1
fi

# 检查是否需要安装依赖
echo ""
echo -e "${YELLOW}📦 正在检查依赖...${NC}"
pip3 install -q -r requirements.txt

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ 依赖安装失败${NC}"
    exit 1
fi

echo -e "${GREEN}✅ 依赖已安装${NC}"

# 启动Flask服务器
echo ""
echo -e "${GREEN}🚀 启动文件共享服务器...${NC}"
echo ""
python3 app.py
