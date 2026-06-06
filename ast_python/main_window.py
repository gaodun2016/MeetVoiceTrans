import asyncio
import sys
import os
import sounddevice as sd
import numpy as np
import time
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QTextEdit, QStatusBar, QMenuBar, QMenu,
    QMessageBox, QComboBox, QLabel, QSplitter, QDialog,
    QLineEdit
)
from PyQt6.QtGui import QFont, QIcon, QAction
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer

# Add python_protogen to path
sys.path.append(os.path.join(os.path.dirname(__file__), "python_protogen"))

from translator_adapter import TranslatorAdapter
from config import Config
from settings_dialog import SettingsDialog
from license_manager import LicenseManager

class TranslatorThread(QThread):
    translation_result = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    status_changed = pyqtSignal(str)  # New signal for status updates
    
    def __init__(self, api_key, output_device=None):
        super().__init__()
        self.api_key = api_key
        self.output_device = output_device
        self.running = False
        self.adapter = None  # Reference to TranslatorAdapter
    
    def run(self):
        self.running = True
        try:
            asyncio.run(self.translate())
        except Exception as e:
            self.error_occurred.emit(str(e))
            
    async def translate(self):
        self.adapter = TranslatorAdapter(self.api_key, self.output_device)
        
        def callback(text):
            if self.running:
                self.translation_result.emit(text)
                
        self.adapter.set_translate_callback(callback)
        
        def error_callback(error):
            if self.running:
                self.error_occurred.emit(error)
                
        self.adapter.set_error_callback(error_callback)
        
        def status_callback(status):
            self.status_changed.emit(status)
            
        self.adapter.set_status_callback(status_callback)
        
        await self.adapter.start()
        
    def stop(self):
        self.running = False
        # 异步调用 adapter.stop()
        if self.adapter:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.adapter.stop())
            loop.close()
        self.wait()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = Config()
        self.translator_thread = None
        self.audio_player = None
        self.license_manager = LicenseManager()
        self.init_ui()
        self.check_license()
        
        # 设置定时器：每分钟检查一次许可证状态（保底检查）
        self.license_check_timer = QTimer()
        self.license_check_timer.timeout.connect(self.check_license)
        self.license_check_timer.start(60 * 1000)  # 每60秒检查一次
        
        # 设置到期即时检测定时器
        self.schedule_expire_check()
    
    def schedule_expire_check(self):
        """计算距离到期的时间，设置定时器在到期时刻触发（简化版本，避免线程问题）"""
        try:
            # 使用已加载的许可证数据，避免重复网络请求
            if hasattr(self.license_manager, 'valid_until') and self.license_manager.valid_until:
                expire_time = self.license_manager.valid_until
                # 使用本地时间计算，避免网络请求阻塞
                current_time = int(time.time())
                time_until_expire = expire_time - current_time
                
                if time_until_expire > 0:
                    # 如果已有定时器，先停止
                    if hasattr(self, 'expire_timer') and self.expire_timer:
                        self.expire_timer.stop()
                    
                    self.expire_timer = QTimer()
                    self.expire_timer.singleShot(time_until_expire * 1000, self.on_license_expire)
                    print(f"许可证将在 {time_until_expire} 秒后到期，已设置到期提醒")
                else:
                    print("许可证已过期或即将过期")
        except Exception as e:
            print(f"设置到期检测失败: {e}")
    
    def on_license_expire(self):
        """许可证到期时的处理"""
        print("许可证已到期，立即更新UI")
        self.check_license()
        # 重新设置下一次到期检测（如果用户激活了新卡密）
        self.schedule_expire_check()
    
    def init_ui(self):
        self.setWindowTitle("Meet Translator")
        self.setGeometry(100, 100, 800, 600)
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout()
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)
        central_widget.setLayout(main_layout)
        
        # Title
        title_label = QLabel("Meet Translator")
        title_label.setFont(QFont("Arial", 24, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title_label)
        
        subtitle_label = QLabel("Real-time speech translation for meetings")
        subtitle_label.setFont(QFont("Arial", 14))
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(subtitle_label)
        
        # API Key and Settings
        api_layout = QHBoxLayout()
        api_layout.setSpacing(20)
        
        api_label = QLabel("API Key:")
        api_label.setFont(QFont("Arial", 12))
        api_layout.addWidget(api_label)
        
        api_key = self.config.api_key
        masked_key = api_key[:4] + '*' * 20 + api_key[-4:] if len(api_key) > 8 else "Not set"
        self.api_status = QLabel(f'<span style="color: #27ae60;">✓ {masked_key}</span>')
        self.api_status.setFont(QFont("Arial", 12))
        api_layout.addWidget(self.api_status)
        
        settings_btn = QPushButton("Settings")
        settings_btn.setFont(QFont("Arial", 12))
        settings_btn.clicked.connect(self.show_settings)
        api_layout.addWidget(settings_btn)
        
        # Output Device
        output_label = QLabel("Output Device:")
        output_label.setFont(QFont("Arial", 12))
        api_layout.addWidget(output_label)
        
        self.output_device_combo = QComboBox()
        self.output_device_combo.setFont(QFont("Arial", 12))
        self.output_device_combo.addItem("Default Speaker")
        api_layout.addWidget(self.output_device_combo)
        
        api_layout.addStretch()
        main_layout.addLayout(api_layout)
        
        # License Panel
        license_widget = QWidget()
        license_widget.setStyleSheet("background-color: #f8f9fa; padding: 15px; border-radius: 8px;")
        license_layout = QHBoxLayout(license_widget)
        license_layout.setSpacing(15)
        license_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.license_input = QLineEdit()
        self.license_input.setPlaceholderText("请输入卡密")
        self.license_input.setFont(QFont("Arial", 12))
        self.license_input.setStyleSheet("""
            QLineEdit {
                padding: 8px 12px;
                border: 1px solid #ddd;
                border-radius: 4px;
                min-width: 300px;
            }
            QLineEdit:focus {
                border-color: #3498db;
                outline: none;
            }
        """)
        license_layout.addWidget(self.license_input)
        
        self.activate_btn = QPushButton("激活")
        self.activate_btn.setFont(QFont("Arial", 12))
        self.activate_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                padding: 8px 24px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:disabled {
                background-color: #bdc3c7;
            }
        """)
        self.activate_btn.clicked.connect(self.activate_license)
        license_layout.addWidget(self.activate_btn)
        
        self.license_status = QLabel("<span style='color: #e74c3c;'>✗ 未激活或已过期</span>")
        self.license_status.setFont(QFont("Arial", 12))
        license_layout.addWidget(self.license_status)
        
        license_layout.addStretch()
        main_layout.addWidget(license_widget)
        
        # Start Translation Button
        self.start_btn = QPushButton("Start Translation")
        self.start_btn.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                padding: 15px 40px;
                border: none;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:disabled {
                background-color: #bdc3c7;
            }
        """)
        self.start_btn.clicked.connect(self.toggle_translation)
        self.start_btn.setFixedSize(300, 50)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(self.start_btn)
        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)
        
        # Translation Output
        output_label = QLabel("Translation Output")
        output_label.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        main_layout.addWidget(output_label)
        
        self.output_text = QTextEdit()
        self.output_text.setFont(QFont("Arial", 12))
        self.output_text.setReadOnly(True)
        self.output_text.setStyleSheet("""
            QTextEdit {
                border: 1px solid #ddd;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        main_layout.addWidget(self.output_text)
        
        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Translation stopped. Ready.")
        
        # Load output devices
        self.load_output_devices()
    
    def load_output_devices(self):
        try:
            devices = sd.query_devices()
            for i, device in enumerate(devices):
                if device['max_output_channels'] > 0:
                    self.output_device_combo.addItem(f"{device['name']} (Device {i})")
        except Exception as e:
            print(f"Error loading output devices: {e}")
    
    def show_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec():
            api_key = self.config.api_key
            masked_key = api_key[:4] + '*' * 20 + api_key[-4:] if len(api_key) > 8 else "Not set"
            self.api_status.setText(f'<span style="color: #27ae60;">✓ {masked_key}</span>')
    
    def toggle_translation(self):
        if not self.license_manager.is_valid():
            QMessageBox.warning(self, "Warning", "请先激活许可证")
            return
            
        if self.translator_thread and self.translator_thread.isRunning():
            self.stop_translation()
        else:
            self.start_translation()
    
    def start_translation(self):
        api_key = self.config.api_key
        if not api_key:
            QMessageBox.warning(self, "Warning", "Please set API Key in Settings")
            return
        
        output_device = None
        index = self.output_device_combo.currentIndex()
        if index > 0:
            # Convert combo index to device index (skip "Default Speaker")
            output_device = index - 1
        
        # Show loading state immediately
        self.start_btn.setText("Connecting...")
        self.start_btn.setEnabled(False)
        self.status_bar.showMessage("Connecting to server...")
        
        # Start translation in background
        self.translator_thread = TranslatorThread(api_key, output_device)
        self.translator_thread.translation_result.connect(self.update_output)
        self.translator_thread.error_occurred.connect(self.show_error)
        self.translator_thread.status_changed.connect(self.on_translator_status_changed)
        self.translator_thread.finished.connect(self.on_translation_finished)
        self.translator_thread.start()
        
        self.output_text.clear()
    
    def stop_translation(self):
        if self.translator_thread:
            # Show stopping state immediately
            self.start_btn.setText("Stopping...")
            self.start_btn.setEnabled(False)
            self.status_bar.showMessage("Stopping...")
            
            # 非阻塞方式停止线程
            thread = self.translator_thread
            self.translator_thread = None
            
            # 在单独的线程中等待线程结束，避免阻塞主线程
            def wait_and_cleanup():
                thread.stop()  # 这会阻塞等待线程结束，但不会阻塞主线程
                thread.deleteLater()
                # 在主线程中更新 UI
                QTimer.singleShot(0, self._on_translation_stopped)
            
            import threading
            wait_thread = threading.Thread(target=wait_and_cleanup, daemon=True)
            wait_thread.start()
        else:
            self._on_translation_stopped()
    
    def _on_translation_stopped(self):
        """翻译停止后的 UI 更新（在主线程中执行）"""
        self.start_btn.setText("Start Translation")
        self.start_btn.setEnabled(True)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                padding: 15px 40px;
                border: none;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
        """)
        self.status_bar.showMessage("Translation stopped. Ready.")
    
    def update_output(self, text):
        self.output_text.append(text)
        # Auto-scroll to bottom
        cursor = self.output_text.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.output_text.setTextCursor(cursor)
    
    def show_error(self, error):
        self.output_text.append(f"[ERROR] {error}")
    
    def on_translator_status_changed(self, status):
        """Handle translator status changes"""
        self.status_bar.showMessage(status)
        
        # When session starts successfully, update button to Stop Translation
        if "Session started" in status or "recording" in status.lower():
            self.start_btn.setText("Stop Translation")
            self.start_btn.setEnabled(True)
            self.start_btn.setStyleSheet("""
                QPushButton {
                    background-color: #e74c3c;
                    color: white;
                    padding: 15px 40px;
                    border: none;
                    border-radius: 8px;
                }
                QPushButton:hover {
                    background-color: #c0392b;
                }
            """)
    
    def on_translation_finished(self):
        self.stop_translation()
    
    def check_license(self):
        """检查许可证状态"""
        try:
            self.license_manager.load_license()
            self.update_license_display()
        except Exception as e:
            print(f"检查许可证失败: {e}")
            self.license_status.setText("<span style='color: #e74c3c;'>✗ 检查许可证失败</span>")
    
    def activate_license(self):
        """激活卡密"""
        key = self.license_input.text().strip()
        if not key:
            QMessageBox.warning(self, "Warning", "请输入卡密")
            return
        
        # 禁用按钮防止重复点击
        self.activate_btn.setEnabled(False)
        
        # 直接执行激活（简化版本，避免线程问题）
        try:
            success, message, _, _ = self.license_manager.activate_key(key)
            
            if success:
                QMessageBox.information(self, "Success", message)
                # 更新许可证状态显示
                self.update_license_display()
                # 设置到期检测
                self.schedule_expire_check()
            else:
                QMessageBox.warning(self, "Error", message)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"激活失败: {str(e)}")
        
        # 重新启用按钮
        self.activate_btn.setEnabled(True)
    
    def update_license_display(self):
        """更新许可证状态显示"""
        if self.license_manager.is_valid():
            remaining_days = self.license_manager.get_remaining_days()
            expire_str = self.license_manager.get_expire_str()
            card_name = self.license_manager.get_card_name()
            self.license_status.setText(f"<span style='color: #27ae60;'>✓ {card_name} - 有效期至: {expire_str} (剩余{remaining_days}天)</span>")
            self.license_input.setEnabled(False)
            self.activate_btn.setEnabled(False)
        else:
            self.license_status.setText("<span style='color: #e74c3c;'>✗ 未激活或已过期</span>")
            self.license_input.setEnabled(True)
            self.activate_btn.setEnabled(True)
    
    def closeEvent(self, event):
        if self.translator_thread and self.translator_thread.isRunning():
            self.translator_thread.stop()
        event.accept()

def main():
    app = asyncio.run(get_event_loop())
    
async def get_event_loop():
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QTimer
    
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    
    loop = asyncio.get_event_loop()
    future = loop.create_future()
    
    def on_exit():
        future.set_result(None)
    
    app.aboutToQuit.connect(on_exit)
    
    await future

if __name__ == "__main__":
    asyncio.run(main())
