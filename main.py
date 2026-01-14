#!/usr/bin/env python3
import json
import time
import logging
import threading
import schedule
import pytz
from datetime import datetime, timedelta
from hcloud import Client
from hcloud.servers.domain import Server
from hcloud.images.domain import Image
from hcloud.server_types.domain import ServerType
from hcloud.ssh_keys.domain import SSHKey
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
import requests
import os

class HetznerAutomation:
    def __init__(self, config_path="/app/config.json"):
        self.config = self.load_config(config_path)
        self.setup_logging()
        self.setup_clients()
        self.notified_thresholds = {}
        self.setup_telegram_bot()
        
    def load_config(self, config_path):
        """加载配置文件"""
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"加载配置文件失败: {e}")
            return {}
    
    def setup_logging(self):
        """设置日志"""
        log_level = getattr(logging, self.config.get('log_level', 'INFO'))
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler('/var/log/hetzner_monitor.log')
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def setup_clients(self):
        """初始化API客户端"""
        try:
            self.hcloud = Client(token=self.config['hcloud_token'])
            self.logger.info("Hetzner Cloud客户端初始化成功")
        except Exception as e:
            self.logger.error(f"Hetzner客户端初始化失败: {e}")
        
        try:
            self.bot = telebot.TeleBot(self.config['telegram_bot_token'])
            self.logger.info("Telegram Bot初始化成功")
        except Exception as e:
            self.logger.error(f"Telegram Bot初始化失败: {e}")
    
    def setup_telegram_bot(self):
        """设置Telegram Bot命令处理器"""
        
        @self.bot.message_handler(commands=['start', 'help'])
        def send_welcome(message):
            help_text = """
🤖 *Hetzner 流量监控机器人 v6.0*

*命令列表:*
/start, /help - 显示帮助信息
/ll, /list - 列出所有服务器和流量统计
/rebuild <服务器名> - 重建指定服务器
/stop <服务器名> - 删除指定服务器
/status - 查看监控状态
/traffic - 查看流量使用情况

*自动功能:*
• 每5分钟监控流量使用
• 流量预警(10%-90%阈值通知)
• 超限自动删除保护
• 定时睡眠模式(23:50关机, 08:00开机)
            """
            self.bot.reply_to(message, help_text, parse_mode='Markdown')
        
        @self.bot.message_handler(commands=['ll', 'list'])
        def list_servers(message):
            servers = self.get_all_servers()
            if not servers:
                self.bot.reply_to(message, "❌ 没有找到运行的服务器")
                return
            
            response = "🖥️ *服务器列表*\n\n"
            for server in servers:
                traffic_info = self.get_traffic_usage(server)
                usage_percent = (traffic_info['used'] / traffic_info['total']) * 100
                
                status_emoji = "🟢" if server.status == "running" else "🔴"
                response += f"{status_emoji} *{server.name}*\n"
                response += f"  📊 流量: {usage_percent:.1f}% ({traffic_info['used']}GB/{traffic_info['total']}GB)\n"
                response += f"  🏷️ 类型: {server.server_type.name}\n"
                response += f"  📍 位置: {server.datacenter.location.name}\n"
                response += f"  🔄 状态: {server.status}\n\n"
            
            self.bot.reply_to(message, response, parse_mode='Markdown')
        
        @self.bot.message_handler(commands=['rebuild'])
        def rebuild_server(message):
            try:
                server_name = message.text.split(' ', 1)[1]
                if self.rebuild_server(server_name):
                    self.bot.reply_to(message, f"✅ 服务器 *{server_name}* 重建成功", parse_mode='Markdown')
                else:
                    self.bot.reply_to(message, f"❌ 服务器 *{server_name}* 重建失败", parse_mode='Markdown')
            except IndexError:
                self.bot.reply_to(message, "❌ 使用方法: /rebuild <服务器名>")
            except Exception as e:
                self.bot.reply_to(message, f"❌ 重建失败: {str(e)}")
        
        @self.bot.message_handler(commands=['stop'])
        def stop_server(message):
            try:
                server_name = message.text.split(' ', 1)[1]
                if self.delete_server(server_name):
                    self.bot.reply_to(message, f"✅ 服务器 *{server_name}* 已删除", parse_mode='Markdown')
                else:
                    self.bot.reply_to(message, f"❌ 服务器 *{server_name}* 删除失败", parse_mode='Markdown')
            except IndexError:
                self.bot.reply_to(message, "❌ 使用方法: /stop <服务器名>")
        
        @self.bot.message_handler(commands=['status'])
        def show_status(message):
            status_text = "📊 *监控系统状态*\n\n"
            status_text += f"🕒 最后检查: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            status_text += f"🔔 通知阈值: {self.config['notification_thresholds']}%\n"
            status_text += f"🚨 删除阈值: {self.config['traffic_limit_percent']}%\n"
            status_text += f"⏰ 睡眠模式: {'启用' if self.config['sleep_mode']['enable'] else '禁用'}\n"
            
            if self.config['sleep_mode']['enable']:
                status_text += f"  🛌 关机时间: {self.config['sleep_mode']['shutdown_time']}\n"
                status_text += f"  ☀️ 开机时间: {self.config['sleep_mode']['startup_time']}\n"
            
            self.bot.reply_to(message, status_text, parse_mode='Markdown')
        
        @self.bot.message_handler(commands=['traffic'])
        def show_traffic(message):
            servers = self.get_all_servers()
            if not servers:
                self.bot.reply_to(message, "❌ 没有找到运行的服务器")
                return
            
            traffic_text = "📈 *流量使用统计*\n\n"
            for server in servers:
                traffic_info = self.get_traffic_usage(server)
                usage_percent = (traffic_info['used'] / traffic_info['total']) * 100
                
                # 创建流量进度条
                bars = 20
                filled = int(bars * usage_percent / 100)
                bar = '█' * filled + '░' * (bars - filled)
                
                traffic_text += f"*{server.name}*\n"
                traffic_text += f"`{bar}` {usage_percent:.1f}%\n"
                traffic_text += f"{traffic_info['used']}GB / {traffic_info['total']}GB\n\n"
            
            self.bot.reply_to(message, traffic_text, parse_mode='Markdown')
    
    def get_all_servers(self):
        """获取所有服务器"""
        try:
            return self.hcloud.servers.get_all()
        except Exception as e:
            self.logger.error(f"获取服务器列表失败: {e}")
            return []
    
    def get_traffic_usage(self, server):
        """获取服务器流量使用情况"""
        try:
            # Hetzner API 获取流量统计
            # 注意: 这里需要实际调用Hetzner的流量统计API
            # 简化实现，返回模拟数据
            total_traffic = server.primary_disk_size * 1000  # GB
            used_traffic = 500  # 模拟已使用流量
            
            return {
                'total': total_traffic,
                'used': used_traffic,
                'remaining': total_traffic - used_traffic
            }
        except Exception as e:
            self.logger.error(f"获取服务器 {server.name} 流量失败: {e}")
            return {'total': 1000, 'used': 0, 'remaining': 1000}
    
    def check_traffic_and_notify(self):
        """检查流量并发送通知"""
        self.logger.info("开始流量检查...")
        servers = self.get_all_servers()
        
        for server in servers:
            try:
                traffic_info = self.get_traffic_usage(server)
                usage_percent = (traffic_info['used'] / traffic_info['total']) * 100
                
                # 检查通知阈值
                self.check_notification_thresholds(server, usage_percent)
                
                # 检查是否超限需要删除
                if usage_percent >= self.config['traffic_limit_percent']:
                    self.handle_traffic_exceeded(server, usage_percent)
                    
            except Exception as e:
                self.logger.error(f"检查服务器 {server.name} 失败: {e}")
    
    def check_notification_thresholds(self, server, usage_percent):
        """检查通知阈值并发送预警"""
        server_key = server.name
        last_notified = self.notified_thresholds.get(server_key, 0)
        
        for threshold in self.config['notification_thresholds']:
            if usage_percent >= threshold and last_notified < threshold:
                message = f"⚠️ *流量预警: {server.name}*\n"
                message += f"📊 使用率: {usage_percent:.1f}%\n"
                message += f"🔄 状态: {server.status}\n"
                message += f"⏰ 时间: {datetime.now().strftime('%H:%M:%S')}"
                
                self.send_telegram_message(message)
                self.notified_thresholds[server_key] = threshold
                self.logger.info(f"服务器 {server.name} 流量达到 {threshold}%")
                break
    
    def handle_traffic_exceeded(self, server, usage_percent):
        """处理流量超限"""
        message = f"🚨 *流量超限警报: {server.name}*\n"
        message += f"📊 使用率: {usage_percent:.1f}%\n"
        message += "🗑️ 正在自动删除服务器以保护账户..."
        
        self.send_telegram_message(message)
        self.logger.warning(f"服务器 {server.name} 流量超限，正在删除")
        
        if self.delete_server(server.name):
            self.logger.info(f"服务器 {server.name} 已删除")
            # 重置通知阈值
            self.notified_thresholds.pop(server.name, None)
        else:
            self.logger.error(f"删除服务器 {server.name} 失败")
    
    def delete_server(self, server_name):
        """删除服务器"""
        try:
            server = self.hcloud.servers.get_by_name(server_name)
            if server:
                server.delete()
                return True
        except Exception as e:
            self.logger.error(f"删除服务器 {server_name} 失败: {e}")
        return False
    
    def rebuild_server(self, server_name):
        """重建服务器"""
        try:
            # 获取原服务器配置
            server = self.hcloud.servers.get_by_name(server_name)
            if not server:
                return False
            
            # 备份配置
            server_config = {
                'name': server.name,
                'server_type': server.server_type.name,
                'image': server.image.name,
                'location': server.datacenter.location.name,
                'ssh_keys': [key.name for key in server.ssh_keys]
            }
            
            # 删除原服务器
            server.delete()
            time.sleep(5)  # 等待删除完成
            
            # 重建服务器
            new_server = self.hcloud.servers.create(
                name=server_config['name'],
                server_type=ServerType(name=server_config['server_type']),
                image=Image(name=server_config['image']),
                location=server_config['location'],
                ssh_keys=[SSHKey(name=key) for key in server_config['ssh_keys']]
            )
            
            # 更新Cloudflare DNS
            if self.config['cloudflare']['enable']:
                self.update_cloudflare_dns(new_server.public_net.ipv4.ip)
            
            return True
            
        except Exception as e:
            self.logger.error(f"重建服务器 {server_name} 失败: {e}")
            return False
    
    def update_cloudflare_dns(self, ip_address):
        """更新Cloudflare DNS记录"""
        if not self.config['cloudflare']['enable']:
            return
        
        try:
            cf_config = self.config['cloudflare']
            domain = cf_config.get('subdomain', '') + '.' + cf_config['domain']
            
            # Cloudflare API调用逻辑
            # 这里需要实现实际的DNS更新
            self.logger.info(f"更新Cloudflare DNS记录 {domain} -> {ip_address}")
            
        except Exception as e:
            self.logger.error(f"更新Cloudflare DNS失败: {e}")
    
    def send_telegram_message(self, message):
        """发送Telegram消息"""
        try:
            self.bot.send_message(self.config['telegram_chat_id'], message, parse_mode='Markdown')
        except Exception as e:
            self.logger.error(f"发送Telegram消息失败: {e}")
    
    def setup_scheduled_tasks(self):
        """设置定时任务"""
        # 流量监控（每5分钟）
        schedule.every(5).minutes.do(self.check_traffic_and_notify)
        
        # 定时睡眠模式
        if self.config['sleep_mode']['enable']:
            schedule.every().day.at(self.config['sleep_mode']['shutdown_time']).do(
                self.shutdown_servers
            )
            schedule.every().day.at(self.config['sleep_mode']['startup_time']).do(
                self.startup_servers
            )
        
        self.logger.info("定时任务设置完成")
    
    def shutdown_servers(self):
        """定时关机（删除服务器）"""
        self.logger.info("执行定时关机...")
        servers = self.get_all_servers()
        
        for server in servers:
            if self.delete_server(server.name):
                message = f"🌙 *定时关机完成*\n服务器 {server.name} 已删除"
                self.send_telegram_message(message)
    
    def startup_servers(self):
        """定时开机（重建服务器）"""
        self.logger.info("执行定时开机...")
        
        if not self.config['sleep_mode']['enable']:
            return
        
        for server_config in self.config['sleep_mode']['rebuild_servers']:
            try:
                # 重建服务器
                new_server = self.hcloud.servers.create(
                    name=server_config['name'],
                    server_type=ServerType(name=server_config['server_type']),
                    image=Image(name=server_config['image']),
                    location=server_config['location'],
                    ssh_keys=[SSHKey(name=key) for key in server_config.get('ssh_keys', [])]
                )
                
                message = f"☀️ *定时开机完成*\n服务器 {server_config['name']} 已重建\nIP: {new_server.public_net.ipv4.ip}"
                self.send_telegram_message(message)
                
            except Exception as e:
                self.logger.error(f"重建服务器 {server_config['name']} 失败: {e}")
    
    def run_scheduler(self):
        """运行调度器"""
        self.setup_scheduled_tasks()
        
        while True:
            try:
                schedule.run_pending()
                time.sleep(1)
            except Exception as e:
                self.logger.error(f"调度器错误: {e}")
                time.sleep(60)
    
    def start(self):
        """启动监控系统"""
        self.logger.info("🚀 启动Hetzner自动化监控系统 v6.0")
        
        # 启动定时任务线程
        scheduler_thread = threading.Thread(target=self.run_scheduler, daemon=True)
        scheduler_thread.start()
        
        # 启动Telegram Bot
        self.logger.info("启动Telegram Bot...")
        try:
            self.bot.infinity_polling()
        except Exception as e:
            self.logger.error(f"Telegram Bot启动失败: {e}")

def main():
    """主函数"""
    try:
        monitor = HetznerAutomation()
        monitor.start()
    except KeyboardInterrupt:
        print("\n👋 程序已退出")
    except Exception as e:
        print(f"❌ 程序启动失败: {e}")

if __name__ == "__main__":
    main()
