"""
License Manager - 卡密管理模块
支持天卡、周卡、月卡、年卡
密钥内置过期时间，每次启动拉取网络时间对比
"""

import hashlib
import base64
import time
import requests
import json
import os

# 密钥版本号
LICENSE_VERSION = "v1"

# 时间常量
DAY_SECONDS = 24 * 60 * 60
WEEK_SECONDS = 7 * DAY_SECONDS
MONTH_SECONDS = 30 * DAY_SECONDS
YEAR_SECONDS = 365 * DAY_SECONDS

# 支持的卡类型
CARD_TYPES = {
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
        self.license_file = os.path.join(os.path.dirname(__file__), 'license.dat')
        self.valid_until = 0
        self.card_type = ''
        self.activated = False
    
    def generate_key(self, card_type, days=0):
        """
        生成密钥（管理员使用）
        card_type: day/week/month/year
        days: 自定义天数（可选，用于生成特定天数的密钥）
        """
        if days > 0:
            duration = days * DAY_SECONDS
        elif card_type in CARD_TYPES:
            duration = CARD_TYPES[card_type]['duration']
        else:
            raise ValueError(f"Unknown card type: {card_type}")
        
        # 计算过期时间（从当前时间加上有效期）
        expire_time = int(time.time()) + duration
        
        # 生成密钥数据
        data = f"{LICENSE_VERSION}:{card_type}:{expire_time}"
        
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
        """
        try:
            # Base64 解码
            decoded_key = base64.b64decode(key).decode()
            
            # 解析密钥
            parts = decoded_key.split(':')
            if len(parts) != 4:
                return False, "无效的密钥格式", 0, ''
            
            version, card_type, expire_time_str, signature = parts
            
            # 验证版本
            if version != LICENSE_VERSION:
                return False, "密钥版本不兼容", 0, ''
            
            # 验证签名
            data = f"{version}:{card_type}:{expire_time_str}"
            if not self._verify_signature(data, signature):
                return False, "密钥签名无效", 0, ''
            
            # 获取网络时间
            network_time = self._get_network_time()
            if network_time == 0:
                # 如果无法获取网络时间，使用本地时间（不太安全）
                network_time = int(time.time())
            
            # 解析过期时间
            expire_time = int(expire_time_str)
            
            # 检查是否过期
            if network_time > expire_time:
                return False, "密钥已过期", 0, ''
            
            # 保存许可证
            self.valid_until = expire_time
            self.card_type = card_type
            self.activated = True
            
            # 保存到文件
            self._save_license()
            
            card_name = CARD_TYPES.get(card_type, {'name': '未知'})['name']
            expire_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(expire_time))
            
            return True, f"激活成功！{card_name} - 有效期至: {expire_str}", expire_time, card_type
        
        except Exception as e:
            return False, f"激活失败: {str(e)}", 0, ''
    
    def _get_network_time(self):
        """获取网络时间"""
        try:
            # 尝试多个时间服务器
            servers = [
                'http://worldtimeapi.org/api/timezone/Asia/Shanghai',
                'http://api.pingxx.com/time',
                'https://www.baidu.com',
            ]
            
            for server in servers:
                try:
                    response = requests.get(server, timeout=5)
                    if server == 'http://worldtimeapi.org/api/timezone/Asia/Shanghai':
                        data = response.json()
                        return int(data['unixtime'])
                    elif server == 'http://api.pingxx.com/time':
                        data = response.json()
                        return int(data['timestamp'])
                    else:
                        # 从响应头获取时间
                        date_header = response.headers.get('Date')
                        if date_header:
                            import email.utils
                            return int(email.utils.mktime_tz(email.utils.parsedate_tz(date_header)))
                except:
                    continue
            
            return 0
        except:
            return 0
    
    def _save_license(self):
        """保存许可证信息到文件"""
        license_data = {
            'valid_until': self.valid_until,
            'card_type': self.card_type,
            'activated': self.activated
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
                    
                    # 验证许可证是否仍然有效
                    if self.activated:
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
        
        remaining = self.valid_until - network_time
        return max(0, remaining)
    
    def get_remaining_days(self):
        """获取剩余天数"""
        remaining = self.get_remaining_time()
        return int(remaining / DAY_SECONDS)
    
    def get_expire_str(self):
        """获取过期时间字符串"""
        if not self.activated:
            return "未激活"
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.valid_until))
    
    def get_card_name(self):
        """获取卡类型名称"""
        return CARD_TYPES.get(self.card_type, {'name': '未知'})['name']
    
    def reset_license(self):
        """重置许可证"""
        self.valid_until = 0
        self.card_type = ''
        self.activated = False
        if os.path.exists(self.license_file):
            os.remove(self.license_file)


# 示例：生成密钥（管理员使用）
if __name__ == '__main__':
    lm = LicenseManager()
    
    # 生成各种类型的密钥
    print("=== 生成测试密钥 ===")
    print(f"天卡: {lm.generate_key('day')}")
    print(f"周卡: {lm.generate_key('week')}")
    print(f"月卡: {lm.generate_key('month')}")
    print(f"年卡: {lm.generate_key('year')}")
    print(f"3天卡: {lm.generate_key('day', days=3)}")
