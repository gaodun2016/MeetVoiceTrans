"""
License Manager - 卡密管理模块
支持天卡、周卡、月卡、年卡
密钥内置过期时间，每次启动拉取网络时间对比
添加设备绑定功能，防止一码多用
"""

import hashlib
import base64
import time
import requests
import json
import os
import logging
import platform
import uuid
import random

# 密钥签名密钥（用于验证密钥合法性）
# 生产环境应使用更安全的密钥管理方式
SIGNING_KEY = "MeetTranslator@2024#SecureKey"

# 时间常量
HOUR_SECONDS = 60 * 60
DAY_SECONDS = 24 * 60 * 60
WEEK_SECONDS = 7 * DAY_SECONDS
MONTH_SECONDS = 30 * DAY_SECONDS
YEAR_SECONDS = 365 * DAY_SECONDS

# 支持的卡类型
CARD_TYPES = {
    'trial': {'name': '体验卡', 'duration': 1 * HOUR_SECONDS},  # 1小时体验卡
    'day': {'name': '天卡', 'duration': DAY_SECONDS},
    'week': {'name': '周卡', 'duration': WEEK_SECONDS},
    'month': {'name': '月卡', 'duration': MONTH_SECONDS},
    'year': {'name': '年卡', 'duration': YEAR_SECONDS}
}

# 密钥签名密钥（用于验证密钥合法性）
# 生产环境应使用更安全的密钥管理方式
SIGNING_KEY = "MeetTranslator@2024#SecureKey"

class LicenseManager:
    def __init__(self):
        # 获取正确的许可证文件路径
        # 使用用户主目录，避免 macOS App Translocation 导致的只读文件系统问题
        # 在打包后的应用中，应用可能被复制到临时只读位置，无法写入
        base_dir = os.path.dirname(__file__)
        
        # 检查是否在 zip 文件中（打包后的情况）
        if '.zip' in base_dir:
            # 在打包后的应用中，使用用户主目录
            # macOS App Translocation 会将应用复制到临时只读位置
            # 必须使用用户主目录来保存许可证文件
            app_data_dir = os.path.expanduser('~/Library/Application Support/MeetTranslator')
            os.makedirs(app_data_dir, exist_ok=True)
            self.license_file = os.path.join(app_data_dir, 'license.dat')
        else:
            # 在开发环境中，使用脚本所在目录
            self.license_file = os.path.join(base_dir, 'license.dat')
        
        self.valid_until = 0
        self.card_type = ''
        self.activated = False
        self.device_id = ''  # 设备 ID
    
    def get_device_fingerprint(self):
        """
        生成设备唯一标识
        基于主机名、架构、处理器信息和 MAC 地址生成指纹
        """
        try:
            # 获取设备信息
            info = []
            info.append(platform.node())  # 主机名
            info.append(platform.machine())  # 硬件架构
            info.append(platform.processor())  # 处理器信息
            
            # 添加 MAC 地址
            try:
                mac_addr = uuid.getnode()
                info.append(str(mac_addr))
            except:
                pass
            
            # 组合信息
            device_info = ':'.join(info)
            
            # 生成指纹（取前16位）
            fingerprint = hashlib.sha256(device_info.encode()).hexdigest()[:16]
            
            return fingerprint
        except Exception as e:
            logging.warning(f"Failed to get device fingerprint: {e}")
            # 如果获取失败，返回一个默认值（降低安全性但保证可用性）
            return "default_device"
    
    def generate_key(self, card_type, days=0, seconds=0, device_id=None):
        """
        生成密钥（管理员使用）
        card_type: trial/day/week/month/year/custom
        days: 自定义天数（可选）
        seconds: 自定义秒数（可选，用于生成短有效期测试卡）
        device_id: 设备 ID（可选，绑定特定设备）
        
        密钥格式：card_type:expire_time[:device_id]:nonce:signature
        有效期从生成时开始计算，过期时间固定不变
        """
        # 根据参数计算有效期时长
        if seconds > 0:
            # 自定义秒数（用于测试卡）
            duration = seconds
        elif days > 0:
            duration = days * DAY_SECONDS
        elif card_type == 'custom':
            raise ValueError("请指定 --days 或 --seconds 参数")
        elif card_type in CARD_TYPES:
            duration = CARD_TYPES[card_type]['duration']
        else:
            raise ValueError(f"Unknown card type: {card_type}")
        
        # 生成唯一随机数，确保每张卡密都是唯一的
        nonce = random.randint(1000000000, 9999999999)
        
        # 获取当前网络时间（作为生成时间）
        network_time = self._get_network_time()
        if network_time == 0:
            network_time = int(time.time())
        
        # 计算过期时间：生成时间 + 有效期时长（固定不变）
        expire_time = network_time + duration
        
        # 生成密钥数据（格式：card_type:expire_time[:device_id]:nonce）
        # 过期时间在生成时固定，不受激活时间影响
        if device_id:
            data = f"{card_type}:{expire_time}:{device_id}:{nonce}"
        else:
            data = f"{card_type}:{expire_time}:{nonce}"
        
        # 生成签名
        signature = self._sign(data)
        
        # 组合密钥
        key = f"{data}:{signature}"
        
        # Base64 编码便于分发
        encoded_key = base64.b64encode(key.encode()).decode()
        
        return encoded_key
    
    def _sign(self, data):
        """生成数据签名"""
        sign_data = f"{data}:{SIGNING_KEY}"
        return hashlib.sha256(sign_data.encode()).hexdigest()
    
    def _verify_signature(self, data, signature):
        """验证签名"""
        expected_signature = self._sign(data)
        return signature == expected_signature
    
    def activate_key(self, key):
        """
        激活密钥
        返回: (success, message, valid_until, card_type)
        
        密钥格式：
        card_type:expire_time:nonce:signature (无设备绑定，4部分)
        card_type:expire_time:device_id:nonce:signature (预绑定设备，5部分)
        
        过期时间在生成时固定，不受激活时间影响
        首次激活时自动绑定到当前设备（软绑定）
        """
        try:
            # Base64 解码
            decoded_key = base64.b64decode(key).decode()
            
            # 解析密钥
            parts = decoded_key.split(':')
            
            # 密钥格式：
            # card_type:expire_time:nonce:signature (无设备绑定，4部分)
            # card_type:expire_time:device_id:nonce:signature (预绑定设备，5部分)
            
            is_pre_bound = False  # 是否为预绑定密钥
            if len(parts) == 5:
                # 预绑定设备格式
                card_type, expire_time_str, device_id, nonce, signature = parts
                is_pre_bound = True
            elif len(parts) == 4:
                # 无绑定格式（首次激活时自动绑定）
                card_type, expire_time_str, nonce, signature = parts
                device_id = None
            else:
                return False, "无效的密钥格式", 0, ''
            
            # 获取当前设备 ID
            current_device = self.get_device_fingerprint()
            
            # 如果是预绑定密钥，验证设备是否匹配
            if is_pre_bound and device_id != current_device:
                return False, "该卡密已绑定其他设备，无法在此设备使用", 0, ''
            
            # 生成验证用的数据
            if is_pre_bound:
                data = f"{card_type}:{expire_time_str}:{device_id}:{nonce}"
            else:
                data = f"{card_type}:{expire_time_str}:{nonce}"
            
            # 验证签名
            if not self._verify_signature(data, signature):
                return False, "密钥签名无效", 0, ''
            
            # 使用卡密中嵌入的过期时间（生成时已固定）
            expire_time = int(expire_time_str)
            
            # 获取网络时间（用于验证过期时间是否有效）
            network_time = self._get_network_time()
            if network_time == 0:
                network_time = int(time.time())
            
            # 检查卡密是否已过期
            if network_time > expire_time:
                return False, "该卡密已过期", 0, ''
            
            # 保存许可证（自动绑定到当前设备）
            self.valid_until = expire_time
            self.card_type = card_type
            self.activated = True
            self.device_id = current_device  # 首次激活时绑定当前设备
            
            # 保存到文件
            self._save_license()
            
            card_name = CARD_TYPES.get(card_type, {'name': '未知'})['name']
            expire_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(expire_time))
            
            if is_pre_bound:
                return True, f"激活成功！{card_name} - 有效期至: {expire_str}\n该卡密已绑定本设备", expire_time, card_type
            else:
                return True, f"激活成功！{card_name} - 有效期至: {expire_str}\n", expire_time, card_type
        
        except Exception as e:
            return False, f"激活失败: {str(e)}", 0, ''
    
    def _get_network_time(self):
        """获取网络时间（使用 HTTPS + 多服务器交叉验证）"""
        try:
            # 使用 HTTPS 加密传输，防止中间人攻击
            # 格式：(URL, 类型)
            # 类型: 'json' - 从 JSON 响应获取时间戳
            # 类型: 'header' - 从响应头获取时间
            # 类型: 'suning' - 从苏宁接口获取时间
            servers = [
                ('https://api.pingxx.com/time', 'json'),       # Ping++ - 返回 {"timestamp": ...}
                # ('https://quan.suning.com/getSysTime.do', 'suning'),  # 苏宁 - 返回 {"sysTime2": "2024-03-20 15:30:00"}
                ('https://www.baidu.com', 'header'),           # 百度
                ('https://www.taobao.com', 'header'),          # 淘宝
                ('https://www.aliyun.com', 'header'),          # 阿里云
            ]
            
            times = []
            
            for server, server_type in servers:
                try:
                    response = requests.get(server, timeout=2, verify=False)
                    timestamp = None
                    
                    if server_type == 'json':
                        # 解析 JSON 时间戳
                        data = response.json()
                        timestamp = int(data.get('timestamp', 0))
                    elif server_type == 'suning':
                        # 解析苏宁时间格式
                        data = response.json()
                        sys_time2 = data.get('sysTime2', '')
                        if sys_time2:
                            from datetime import datetime
                            dt = datetime.strptime(sys_time2, '%Y-%m-%d %H:%M:%S')
                            timestamp = int(dt.timestamp())
                    else:
                        # 从响应头获取时间
                        date_header = response.headers.get('Date')
                        if date_header:
                            import email.utils
                            timestamp = int(email.utils.mktime_tz(email.utils.parsedate_tz(date_header)))
                    
                    if timestamp:
                        times.append(timestamp)
                        logging.debug(f"Time from {server}: {timestamp}")
                except Exception as e:
                    logging.debug(f"Failed to get time from {server}: {e}")
                    continue
            
            if len(times) == 0:
                return 0
            
            # 交叉验证：取多个服务器时间的平均值
            avg_time = sum(times) // len(times)
            
            # 安全检查：如果某个服务器时间偏差超过 5 分钟，可能是被攻击了
            max_deviation = 300  # 5 分钟
            for t in times:
                deviation = abs(t - avg_time)
                if deviation > max_deviation:
                    logging.warning(f"Time deviation detected: {deviation} seconds, possible attack")
                    # 使用最小时间（更保守，防止时间被改大）
                    return min(times)
            
            # 所有服务器时间一致，返回平均值
            return avg_time
        
        except Exception as e:
            logging.error(f"Failed to get network time: {e}")
            return 0
    
    def _save_license(self):
        """保存许可证信息到文件"""
        license_data = {
            'valid_until': self.valid_until,
            'card_type': self.card_type,
            'activated': self.activated,
            'device_id': self.device_id  # 保存设备 ID
        }
        with open(self.license_file, 'w') as f:
            json.dump(license_data, f)
    
    def load_license(self):
        """加载许可证信息"""
        try:
            if os.path.exists(self.license_file):
                with open(self.license_file, 'r') as f:
                    license_data = json.load(f)
                    self.valid_until = license_data.get('valid_until', 0)
                    self.card_type = license_data.get('card_type', '')
                    self.activated = license_data.get('activated', False)
                    self.device_id = license_data.get('device_id', '')
                    
                    # 验证许可证是否仍然有效
                    if self.activated:
                        # 检查设备是否匹配
                        current_device = self.get_device_fingerprint()
                        if self.device_id and self.device_id != current_device:
                            logging.warning("Device mismatch, invalidating license")
                            self.activated = False
                            self._save_license()
                            return
                        
                        network_time = self._get_network_time()
                        if network_time == 0:
                            network_time = int(time.time())
                        
                        if network_time > self.valid_until:
                            self.activated = False
                            self._save_license()
        except:
            self.activated = False
    
    def is_valid(self):
        """检查许可证是否有效"""
        if not self.activated:
            return False
        
        # 检查设备是否匹配
        current_device = self.get_device_fingerprint()
        if self.device_id and self.device_id != current_device:
            return False
        
        network_time = self._get_network_time()
        if network_time == 0:
            network_time = int(time.time())
        
        return network_time <= self.valid_until
    
    def get_remaining_time(self):
        """获取剩余时间（秒）"""
        if not self.activated:
            return 0
        
        network_time = self._get_network_time()
        if network_time == 0:
            network_time = int(time.time())
        
        return max(0, self.valid_until - network_time)
    
    def get_remaining_days(self):
        """获取剩余天数"""
        remaining = self.get_remaining_time()
        return max(0, remaining // DAY_SECONDS)
    
    def get_expire_str(self):
        """获取过期时间字符串"""
        if not self.activated:
            return ""
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.valid_until))
    
    def get_card_name(self):
        """获取卡名称"""
        if not self.activated:
            return ""
        return CARD_TYPES.get(self.card_type, {'name': '未知'})['name']
    
    def reset_license(self):
        """重置许可证"""
        self.valid_until = 0
        self.card_type = ''
        self.activated = False
        self.device_id = ''
        self._save_license()
    
    def get_duration(self, card_type):
        """获取卡类型的有效期（秒）"""
        if card_type in CARD_TYPES:
            return CARD_TYPES[card_type]['duration']
        return 0

def main():
    """
    命令行工具 - 批量生成密钥
    支持参数：
    --type: 卡类型 (day/week/month/year/trial)
    --count: 数量 (默认1)
    --days: 自定义天数 (可选)
    --all: 生成所有类型各一张
    --batch: 批量生成 (trial, day, week, month, year 数量)
    --output: 输出文件 (可选)
    --bind-device: 绑定当前设备 (可选)
    --device-id: 指定设备 ID (可选)
    """
    import argparse
    
    parser = argparse.ArgumentParser(
        description='卡密批量生成工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  %(prog)s --type trial --count 10         生成10张体验卡(1小时)
  %(prog)s --type day --count 10          生成10张天卡
  %(prog)s --type week --count 5          生成5张周卡
  %(prog)s --type month --count 3         生成3张月卡
  %(prog)s --type year --count 1          生成1张年卡
  %(prog)s --days 15 --count 20           生成20张15天卡
  %(prog)s --seconds 60 --count 5        生成5张1分钟测试卡
  %(prog)s --type custom --seconds 120    生成1张2分钟测试卡
  %(prog)s --all                          生成所有类型各一张
  %(prog)s --batch 10 5 3 2 1            生成体验卡10张、天卡5张、周卡3张、月卡2张、年卡1张
  %(prog)s --type trial -c 100 -o keys.txt 生成100张体验卡并保存到文件
  %(prog)s --type day --bind-device      生成1张天卡并绑定当前设备
  %(prog)s --type day --device-id abc123  生成1张天卡并绑定指定设备
  %(prog)s --type day --reset            重置当前卡密并生成1张天卡
        '''
    )
    
    parser.add_argument(
        '--type', '-t',
        choices=['trial', 'day', 'week', 'month', 'year', 'custom'],
        help='卡类型: trial(体验卡1小时), day(天卡), week(周卡), month(月卡), year(年卡), custom(自定义秒数)'
    )
    
    parser.add_argument(
        '--count', '-c',
        type=int,
        default=1,
        help='生成数量 (默认1)'
    )
    
    parser.add_argument(
        '--days', '-d',
        type=int,
        default=0,
        help='自定义天数 (可选)'
    )
    
    parser.add_argument(
        '--seconds', '-s',
        type=int,
        default=0,
        help='自定义秒数 (可选，用于生成短有效期测试卡)'
    )
    
    parser.add_argument(
        '--all', '-a',
        action='store_true',
        help='生成所有类型各一张'
    )
    
    parser.add_argument(
        '--batch', '-b',
        nargs=5,
        metavar=('TRIAL', 'DAY', 'WEEK', 'MONTH', 'YEAR'),
        type=int,
        help='批量生成: 指定各类型数量 (示例: --batch 10 5 3 2 1)'
    )
    
    parser.add_argument(
        '--output', '-o',
        type=str,
        help='输出文件 (可选)'
    )
    
    parser.add_argument(
        '--bind-device',
        action='store_true',
        help='绑定当前设备 (可选)'
    )
    
    parser.add_argument(
        '--device-id',
        type=str,
        help='指定设备 ID (可选)'
    )
    
    parser.add_argument(
        '--reset',
        action='store_true',
        help='重置当前已绑定的卡密 (可选)'
    )
    
    args = parser.parse_args()
    
    lm = LicenseManager()
    
    # 重置当前已绑定的卡密
    if args.reset:
        lm.reset_license()
        print("已重置当前已绑定的卡密")
        print()
    
    # 获取设备 ID
    device_id = None
    if args.device_id:
        device_id = args.device_id
    elif args.bind_device:
        device_id = lm.get_device_fingerprint()
        print(f"设备 ID: {device_id}")
    
    keys = []
    
    def _format_duration(duration):
        """格式化时长显示"""
        if duration < HOUR_SECONDS:
            return f"{duration}秒"
        elif duration < DAY_SECONDS:
            hours = duration // HOUR_SECONDS
            return f"{hours}小时"
        elif duration < WEEK_SECONDS:
            days = duration // DAY_SECONDS
            return f"{days}天"
        elif duration < MONTH_SECONDS:
            weeks = duration // WEEK_SECONDS
            return f"{weeks}周"
        elif duration < YEAR_SECONDS:
            months = duration // MONTH_SECONDS
            return f"{months}个月"
        else:
            years = duration // YEAR_SECONDS
            return f"{years}年"
    
    # 生成所有类型各一张
    if args.all:
        print("=" * 60)
        print("批量生成密钥 - 所有类型")
        if device_id:
            print(f"绑定设备: {device_id}")
        print("=" * 60)
        
        for card_type in ['trial', 'day', 'week', 'month', 'year']:
            key = lm.generate_key(card_type, device_id=device_id)
            card_name = CARD_TYPES[card_type]['name']
            duration = CARD_TYPES[card_type]['duration']
            duration_str = _format_duration(duration)
            
            keys.append({
                'type': card_type,
                'name': card_name,
                'key': key,
                'duration': duration_str
            })
            
            print(f"[{card_name}] 密钥: {key}")
            print(f"    有效期时长: {duration_str} (激活时开始计时)")
            print()
    
    # 批量生成指定数量
    elif args.batch:
        trial_count, day_count, week_count, month_count, year_count = args.batch
        print("=" * 60)
        print(f"批量生成密钥")
        print(f"  体验卡: {trial_count} 张")
        print(f"  天卡: {day_count} 张")
        print(f"  周卡: {week_count} 张")
        print(f"  月卡: {month_count} 张")
        print(f"  年卡: {year_count} 张")
        print(f"  总计: {trial_count + day_count + week_count + month_count + year_count} 张")
        if device_id:
            print(f"绑定设备: {device_id}")
        print("=" * 60)
        
        for card_type, count, name in [
            ('trial', trial_count, '体验卡'),
            ('day', day_count, '天卡'),
            ('week', week_count, '周卡'),
            ('month', month_count, '月卡'),
            ('year', year_count, '年卡')
        ]:
            for i in range(count):
                key = lm.generate_key(card_type, device_id=device_id)
                duration = CARD_TYPES[card_type]['duration']
                duration_str = _format_duration(duration)
                
                keys.append({
                    'type': card_type,
                    'name': name,
                    'key': key,
                    'duration': duration_str
                })
                
                print(f"[{name}-{i+1}] 密钥: {key}")
                print(f"    有效期时长: {duration_str} (激活时开始计时)")
                print()
    
    # 生成指定类型
    elif args.type:
        card_type = args.type
        count = args.count
        
        # 处理 custom 类型
        if card_type == 'custom':
            if args.seconds <= 0:
                print("错误: --type custom 需要配合 --seconds 参数使用")
                return
            card_name = f"{args.seconds}秒测试卡"
        else:
            card_name = CARD_TYPES[card_type]['name']
        
        print("=" * 60)
        print(f"批量生成密钥 - {card_name} x {count}")
        if device_id:
            print(f"绑定设备: {device_id}")
        print("=" * 60)
        
        for i in range(count):
            key = lm.generate_key(card_type, days=args.days, seconds=args.seconds, device_id=device_id)
            
            # 计算有效期时长
            if args.seconds > 0:
                # 自定义秒数
                duration = args.seconds
                duration_str = _format_duration(duration)
                card_name = f"{args.seconds}秒测试卡"
            elif args.days > 0:
                duration = args.days * DAY_SECONDS
                duration_str = _format_duration(duration)
                card_name = f"{args.days}天卡"
            elif card_type == 'custom':
                duration = args.seconds
                duration_str = _format_duration(duration)
                card_name = f"{args.seconds}秒测试卡"
            else:
                duration = CARD_TYPES[card_type]['duration']
                duration_str = _format_duration(duration)
            
            keys.append({
                'type': card_type,
                'name': card_name,
                'key': key,
                'duration': duration_str
            })
            
            print(f"[{i+1}] 密钥: {key}")
            print(f"    有效期时长: {duration_str} (激活时开始计时)")
            print()
    
    else:
        parser.print_help()
        return
    
    # 输出统计
    print("=" * 60)
    print("生成统计")
    print(f"总计生成: {len(keys)} 张")
    print("=" * 60)
    
    # 保存到文件
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write("=" * 60 + "\n")
            f.write("Meet Translator 卡密生成\n")
            f.write(f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            if device_id:
                f.write(f"绑定设备: {device_id}\n")
            f.write("=" * 60 + "\n\n")
            
            for k in keys:
                f.write(f"[{k['name']}]\n")
                f.write(f"密钥: {k['key']}\n")
                f.write(f"有效期时长: {k['duration']} (激活时开始计时)\n")
                f.write("\n")
            
            f.write("=" * 60 + "\n")
            f.write(f"总计: {len(keys)} 张\n")
            f.write("=" * 60 + "\n")
        
        print(f"\n密钥已保存到: {args.output}")

if __name__ == "__main__":
    main()

