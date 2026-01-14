#!/bin/bash
# Hetzner 监控命令行工具

CONFIG_DIR="/opt/hetzner_monitor"
CONFIG_FILE="$CONFIG_DIR/config.json"

case "$1" in
    "start")
        docker-compose -f $CONFIG_DIR/docker-compose.yml up -d
        echo "✅ 服务已启动"
        ;;
    "stop")
        docker-compose -f $CONFIG_DIR/docker-compose.yml down
        echo "✅ 服务已停止"
        ;;
    "restart")
        docker-compose -f $CONFIG_DIR/docker-compose.yml restart
        echo "✅ 服务已重启"
        ;;
    "logs")
        docker logs -f hetzner-monitor
        ;;
    "config")
        nano $CONFIG_FILE
        echo "✅ 配置已更新，请重启服务: hz restart"
        ;;
    "status")
        docker ps | grep hetzner-monitor
        ;;
    "help")
        echo "Hetzner 监控命令行工具"
        echo "用法: hz [command]"
        echo ""
        echo "命令:"
        echo "  start    - 启动服务"
        echo "  stop     - 停止服务"
        echo "  restart  - 重启服务"
        echo "  logs     - 查看日志"
        echo "  config   - 编辑配置"
        echo "  status   - 查看状态"
        echo "  help     - 显示帮助"
        ;;
    *)
        echo "❌ 未知命令: $1"
        echo "使用 'hz help' 查看帮助"
        ;;
esac
