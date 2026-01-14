#!/bin/bash
set -e

echo "🚀 开始安装 Hetzner 流量监控机器人 v6.0..."

# 检查root权限
if [ "$EUID" -ne 0 ]; then 
    echo "❌ 请使用root权限运行此脚本"
    echo "使用方法: sudo bash install.sh"
    exit 1
fi

# 检查Docker
if ! command -v docker &> /dev/null; then
    echo "❌ 请先安装 Docker"
    echo "安装命令: curl -fsSL https://get.docker.com | sh"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ 请先安装 Docker Compose"
    echo "安装命令: https://docs.docker.com/compose/install/"
    exit 1
fi

# 创建安装目录
INSTALL_DIR="/opt/hetzner_monitor"
echo "📁 创建安装目录: $INSTALL_DIR"
mkdir -p $INSTALL_DIR
cd $INSTALL_DIR

# 下载必要文件
echo "📥 下载项目文件..."
curl -fsSL -o docker-compose.yml https://raw.githubusercontent.com/liuweiqiang0523/Hetzner-Automation/main/docker-compose.yml
curl -fsSL -o config.json https://raw.githubusercontent.com/liuweiqiang0523/Hetzner-Automation/main/config.example.json
curl -fsSL -o Dockerfile https://raw.githubusercontent.com/liuweiqiang0523/Hetzner-Automation/main/Dockerfile

# 创建配置目录
mkdir -p $INSTALL_DIR/config
mkdir -p $INSTALL_DIR/logs

# 设置权限
chmod 755 $INSTALL_DIR
chmod 644 $INSTALL_DIR/*.yml $INSTALL_DIR/*.json

echo "🔧 配置说明:"
echo "========================================"
echo "📝 请编辑配置文件: $INSTALL_DIR/config.json"
echo "   - Hetzner API Token"
echo "   - Telegram Bot Token" 
echo "   - Telegram Chat ID"
echo "========================================"

# 询问是否立即启动
read -p "是否立即启动服务? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "🚀 启动服务..."
    docker-compose up -d
    echo "✅ 服务启动完成!"
    echo "📊 查看日志: docker logs -f hetzner-monitor"
    echo "🛠️  管理命令: docker-compose restart hetzner-monitor"
fi

echo "🎉 安装完成!"
echo "💡 使用说明:"
echo "   - 编辑配置: nano $INSTALL_DIR/config.json"
echo "   - 重启服务: docker-compose restart"
echo "   - 查看日志: docker logs -f hetzner-monitor"
echo "   - 停止服务: docker-compose down"
