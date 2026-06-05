"""
macOS 和 Windows 打包配置
使用 PyInstaller 将应用打包成可执行文件

已包含所有依赖：
- portaudio (音频输入)
- ffmpeg (音频解码，用于 opus/ogg 格式)
- 所有 Python 库
"""

import subprocess
import os
import platform

# 获取脚本所在目录
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

# 设置 PyInstaller 缓存目录到项目目录
os.environ['PYINSTALLER_CONFIG_DIR'] = os.path.join(script_dir, '.pyinstaller_cache')

# 获取 portaudio 库路径
portaudio_path = '/Users/admin/Library/Python/3.11/lib/python/site-packages/_sounddevice_data/portaudio-binaries/libportaudio.dylib'

# 获取 ffmpeg 路径（用于解码 opus/ogg 音频）
ffmpeg_path = ''
if platform.system() == 'Darwin':
    # macOS 系统
    # 尝试从多个位置查找 ffmpeg
    possible_ffmpeg_paths = [
        '/opt/homebrew/bin/ffmpeg',
        '/usr/local/bin/ffmpeg',
        '/usr/bin/ffmpeg',
    ]
    for path in possible_ffmpeg_paths:
        if os.path.exists(path):
            ffmpeg_path = path
            break
elif platform.system() == 'Windows':
    # Windows 系统
    ffmpeg_path = 'C:\\ffmpeg\\bin\\ffmpeg.exe'

# PyInstaller 命令
cmd = [
    '/Users/admin/Library/Python/3.11/bin/pyinstaller',
    'main.py',
    '--name=MeetTranslator',
    '--windowed',
    '--onedir',
    '--add-data=python_protogen:python_protogen',
    f'--add-binary={portaudio_path}:.',
    '--hidden-import=PyQt6',
    '--hidden-import=PyQt6.QtCore',
    '--hidden-import=PyQt6.QtGui',
    '--hidden-import=PyQt6.QtWidgets',
    '--hidden-import=sounddevice',
    '--hidden-import=numpy',
    '--hidden-import=websockets',
    '--hidden-import=google.protobuf',
    '--hidden-import=google.protobuf.json_format',
    '--hidden-import=aiohttp',
    '--hidden-import=aiohttp.client_exceptions',
    '--hidden-import=aiohttp.http_exceptions',
    '--hidden-import=aiohttp.connector',
    '--hidden-import=aiohttp.helpers',
    '--hidden-import=aiohttp.http_websocket',
    '--hidden-import=aiohttp.streams',
    '--hidden-import=aiohttp.typedefs',
    '--hidden-import=aiohttp.web',
    '--hidden-import=aiohttp.web_exceptions',
    '--hidden-import=aiohttp.web_protocol',
    '--hidden-import=aiohttp.web_server',
    '--hidden-import=requests',
    '--hidden-import=asyncio',
    '--hidden-import=uuid',
    '--hidden-import=logging',
    '--hidden-import=logging.handlers',
    '--hidden-import=pydub',
    '--hidden-import=opuslib',
    '--specpath=' + script_dir,
    '--workpath=' + os.path.join(script_dir, 'build'),
    '--distpath=' + os.path.join(script_dir, 'dist'),
    '--clean',
    '-y',
]

# 如果找到 ffmpeg，添加到打包中
if ffmpeg_path and os.path.exists(ffmpeg_path):
    cmd.append(f'--add-binary={ffmpeg_path}:ffmpeg')
    print(f"[INFO] Found ffmpeg at: {ffmpeg_path}")
else:
    print("[WARNING] ffmpeg not found! Audio playback may not work correctly.")
    print("Please install ffmpeg: brew install ffmpeg (macOS) or download from ffmpeg.org")

# 检查图标文件
if not os.path.exists('icon.icns'):
    cmd = [arg for arg in cmd if not arg.startswith('--icon')]

print("=" * 60)
print("Meet Translator 打包工具")
print("=" * 60)
print(f"[*] 正在使用 PyInstaller 打包...")
print(f"[*] 工作目录: {script_dir}")
print(f"[*] 命令: {' '.join(cmd)}")

# 执行 PyInstaller
result = subprocess.run(cmd, capture_output=False)

if result.returncode == 0:
    print("")
    print("=" * 60)
    print("[✓] 打包完成！")
    print(f"[*] macOS 应用位置: {script_dir}/dist/MeetTranslator/MeetTranslator.app")
    
    # 添加麦克风权限声明到 Info.plist
    print("[*] 添加麦克风权限声明...")
    info_plist_path = os.path.join(script_dir, 'dist', 'MeetTranslator.app', 'Contents', 'Info.plist')
    with open(info_plist_path, 'r') as f:
        plist_content = f.read()
    
    # 添加麦克风权限声明
    microphone_permission = '''        <key>NSMicrophoneUsageDescription</key>
        <string>MeetTranslator 需要访问麦克风进行语音翻译</string>
'''
    # 在 </dict> 之前添加
    plist_content = plist_content.replace('</dict>', microphone_permission + '</dict>')
    
    with open(info_plist_path, 'w') as f:
        f.write(plist_content)
    
    print("[✓] 麦克风权限已添加")
    
    # 重新签名应用以包含麦克风权限授权
    print("[*] 重新签名应用...")
    entitlements_path = os.path.join(script_dir, 'entitlements.plist')
    entitlements_content = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.device.audio-input</key>
    <true/>
</dict>
</plist>
'''
    with open(entitlements_path, 'w') as f:
        f.write(entitlements_content)
    
    app_path = os.path.join(script_dir, 'dist', 'MeetTranslator.app')
    sign_cmd = ['codesign', '--force', '--sign', '-', '--entitlements', entitlements_path, app_path]
    sign_result = subprocess.run(sign_cmd, capture_output=True)
    if sign_result.returncode == 0:
        print("[✓] 应用签名成功")
    else:
        print(f"[!] 签名警告: {sign_result.stderr.decode()}")
    
    # 删除临时授权文件
    os.remove(entitlements_path)
    
    print("")
    print("[*] 创建压缩包...")
    
    # 创建压缩包
    import zipfile
    import shutil
    
    app_dir = os.path.join(script_dir, 'dist', 'MeetTranslator')
    zip_name = os.path.join(script_dir, 'dist', 'MeetTranslator-macOS.zip')
    
    with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(app_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, os.path.dirname(app_dir))
                zipf.write(file_path, arcname)
    
    print(f"[✓] macOS 压缩包已创建: {zip_name}")
    print("=" * 60)
else:
    print("")
    print("=" * 60)
    print("[✗] 打包失败！")
    print("=" * 60)
