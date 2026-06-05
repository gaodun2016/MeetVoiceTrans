"""
macOS 打包配置
使用 py2app 将应用打包成 .app 文件
"""
from setuptools import setup
import os

APP = ['main.py']

# 检查图标文件是否存在
iconfile = 'icon.icns' if os.path.exists('icon.icns') else None

OPTIONS = {
    'plist': {
        'CFBundleName': 'Meet Translator',
        'CFBundleDisplayName': 'Meet Translator',
        'CFBundleIdentifier': 'com.meettranslator.app',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'CFBundlePackageType': 'APPL',
        'NSMicrophoneUsageDescription': 'Meet Translator 需要使用麦克风进行语音翻译',
        'NSHighResolutionCapable': True,
    },
    'optimize': 2,
    'strip': True,
}

# 只有在图标文件存在时才添加
if iconfile:
    OPTIONS['iconfile'] = iconfile

setup(
    app=APP,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
