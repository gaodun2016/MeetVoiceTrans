import asyncio
import sys
import os
import sounddevice as sd
import numpy as np
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QTextEdit, QStatusBar, QMenuBar, QMenu,
    QMessageBox, QComboBox, QLabel, QSplitter, QDialog
)
from PyQt6.QtGui import QFont, QIcon, QAction
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer

# Add python_protogen to path
sys.path.append(os.path.join(os.path.dirname(__file__), "python_protogen"))

from translator_adapter import TranslatorAdapter
from config import Config
from settings_dialog import SettingsDialog

class AudioPlayer(QThread):
    def __init__(self, device_id=None):
        super().__init__()
        self.device_id = device_id
        self.audio_queue = asyncio.Queue()
        self.running = True
    
    def add_audio(self, audio_data):
        asyncio.run_coroutine_threadsafe(self.audio_queue.put(audio_data), asyncio.get_event_loop())
    
    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._play_audio())
    
    async def _play_audio(self):
        while self.running:
            try:
                audio_data = await asyncio.wait_for(self.audio_queue.get(), timeout=1.0)
                if audio_data:
                    # Decode Ogg/Opus to PCM
                    pcm_data = self._decode_opus(audio_data)
                    if pcm_data:
                        sd.play(pcm_data, samplerate=24000, device=self.device_id)
                        sd.wait()
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"Audio play error: {e}")
    
    def _decode_opus(self, opus_data):
        try:
            import subprocess
            import tempfile
            
            with tempfile.NamedTemporaryFile(suffix='.opus', delete=False) as f:
                f.write(opus_data)
                opus_file = f.name
            
            cmd = ['ffmpeg', '-i', opus_file, '-f', 's16le', '-ar', '24000', '-ac', '1', '-']
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            pcm_data, _ = process.communicate()
            
            os.unlink(opus_file)
            
            if pcm_data:
                return np.frombuffer(pcm_data, dtype=np.int16)
        except Exception as e:
            print(f"Decode error: {e}")
        
        return None
    
    def stop(self):
        self.running = False
        self.wait()

class TranslatorThread(QThread):
    translate_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    audio_signal = pyqtSignal(bytes)
    
    def __init__(self, api_key, device_id):
        super().__init__()
        self.api_key = api_key
        self.device_id = device_id
        self.translator = None
        self.running = False
    
    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._translate_loop())
    
    async def _translate_loop(self):
        self.running = True
        
        # 使用 meet_translator.py 的适配器
        self.translator = TranslatorAdapter(self.api_key, self.device_id)
        self.translator.set_callbacks(
            translate_callback=self.on_translate,
            status_callback=self.on_status,
            error_callback=self.on_error
        )
        
        # 运行翻译循环
        await self.translator.run()
    
    def on_translate(self, text):
        self.translate_signal.emit(text)
    
    def on_audio(self, audio_data):
        self.audio_signal.emit(audio_data)
    
    def on_status(self, msg):
        self.status_signal.emit(msg)
    
    def on_error(self, msg):
        self.error_signal.emit(msg)
    
    def stop(self):
        if self.translator:
            self.translator.stop()
        self.running = False
        self.wait()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = Config()
        self.translator_thread = None
        self.audio_player = None
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("Meet Translator")
        self.setGeometry(100, 100, 800, 600)
        
        # Set window icon (optional)
        # self.setWindowIcon(QIcon('icon.png'))
        
        # Create menu bar
        self.create_menu_bar()
        
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
        title_label.setStyleSheet("color: #333;")
        main_layout.addWidget(title_label)
        
        # Subtitle
        subtitle_label = QLabel("Real-time speech translation for meetings")
        subtitle_label.setFont(QFont("Arial", 14))
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle_label.setStyleSheet("color: #666;")
        main_layout.addWidget(subtitle_label)
        
        # Control panel
        control_layout = QHBoxLayout()
        control_layout.setSpacing(20)
        control_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # API Key Status
        api_status_layout = QHBoxLayout()
        api_status_label = QLabel("API Key:")
        api_status_label.setFont(QFont("Arial", 12))
        api_status_layout.addWidget(api_status_label)
        
        self.api_status_badge = QLabel()
        self.api_status_badge.setFont(QFont("Arial", 11))
        self.update_api_status()
        api_status_layout.addWidget(self.api_status_badge)
        
        # Settings Button
        self.settings_btn = QPushButton("Settings")
        self.settings_btn.setFont(QFont("Arial", 12))
        self.settings_btn.setStyleSheet("""
            QPushButton {
                background-color: #e0e0e0;
                color: #333;
                padding: 8px 16px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover {
                background-color: #d0d0d0;
            }
        """)
        self.settings_btn.clicked.connect(self.show_settings)
        api_status_layout.addWidget(self.settings_btn)
        
        control_layout.addLayout(api_status_layout)
        
        # Output device selector
        device_layout = QHBoxLayout()
        device_label = QLabel("Output Device:")
        device_label.setFont(QFont("Arial", 12))
        device_layout.addWidget(device_label)
        
        self.device_combo = QComboBox()
        self.device_combo.addItem("Default Speaker", -1)
        devices = sd.query_devices()
        for i, device in enumerate(devices):
            if device['max_output_channels'] > 0:
                self.device_combo.addItem(device['name'], i)
        
        if self.config.output_device >= 0:
            idx = self.device_combo.findData(self.config.output_device)
            if idx >= 0:
                self.device_combo.setCurrentIndex(idx)
        
        device_layout.addWidget(self.device_combo)
        control_layout.addLayout(device_layout)
        
        main_layout.addLayout(control_layout)
        
        # Action button
        self.action_button = QPushButton("Start Translation")
        self.action_button.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        self.action_button.setStyleSheet("""
            QPushButton {
                background-color: #4a90d9;
                color: white;
                padding: 15px 60px;
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover {
                background-color: #3a80c9;
            }
            QPushButton:disabled {
                background-color: #ccc;
            }
        """)
        self.action_button.clicked.connect(self.toggle_translation)
        main_layout.addWidget(self.action_button, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # Translation output
        output_group = QVBoxLayout()
        output_label = QLabel("Translation Output")
        output_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        output_group.addWidget(output_label)
        
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setFont(QFont("Arial", 14))
        self.output_text.setStyleSheet("""
            QTextEdit {
                background-color: white;
                border: 1px solid #ddd;
                border-radius: 8px;
                padding: 15px;
            }
        """)
        output_group.addWidget(self.output_text)
        main_layout.addLayout(output_group)
        
        # Status bar
        self.status_bar = QStatusBar()
        self.status_bar.setFont(QFont("Arial", 12))
        self.setStatusBar(self.status_bar)
        self.update_status("Ready. Click Start to begin translation.")
    
    def create_menu_bar(self):
        menu_bar = QMenuBar()
        
        # File menu
        file_menu = QMenu("File", self)
        
        settings_action = QAction("Settings", self)
        settings_action.triggered.connect(self.show_settings)
        file_menu.addAction(settings_action)
        
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        menu_bar.addMenu(file_menu)
        
        # Help menu
        help_menu = QMenu("Help", self)
        
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
        
        menu_bar.addMenu(help_menu)
        
        self.setMenuBar(menu_bar)
    
    def show_settings(self):
        dialog = SettingsDialog(self.config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.update_api_status()
    
    def update_api_status(self):
        if self.config.api_key:
            # Show masked API key
            masked_key = self.config.api_key[:4] + "*" * (len(self.config.api_key) - 8) + self.config.api_key[-4:]
            self.api_status_badge.setText(f"✓ {masked_key}")
            self.api_status_badge.setStyleSheet("color: #27ae60; font-weight: bold;")
        else:
            self.api_status_badge.setText("✗ Not Set")
            self.api_status_badge.setStyleSheet("color: #e74c3c; font-weight: bold;")
    
    def show_about(self):
        QMessageBox.about(self, "About Meet Translator", 
            "Meet Translator\n\nReal-time speech translation for meetings.\n\nVersion 1.0.0")
    
    def toggle_translation(self):
        if self.translator_thread and self.translator_thread.isRunning():
            self.stop_translation()
        else:
            self.start_translation()
    
    def start_translation(self):
        if not self.config.api_key:
            QMessageBox.warning(self, "Warning", "Please set X-Api-Key in Settings")
            self.show_settings()
            return
        
        self.action_button.setText("Stop Translation")
        self.action_button.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                padding: 15px 60px;
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover {
                background-color: #c73c2c;
            }
        """)
        
        # Clear output
        self.output_text.clear()
        
        # Get selected output device
        device_id = self.device_combo.currentData()
        
        # Start audio player
        self.audio_player = AudioPlayer(device_id)
        self.audio_player.start()
        
        # Start translator thread
        self.translator_thread = TranslatorThread(self.config.api_key, device_id)
        self.translator_thread.translate_signal.connect(self.on_translate)
        self.translator_thread.status_signal.connect(self.update_status)
        self.translator_thread.error_signal.connect(self.on_error)
        self.translator_thread.audio_signal.connect(self.on_audio)
        self.translator_thread.finished.connect(self.on_translation_finished)
        self.translator_thread.start()
        
        self.update_status("Connecting to server...")
    
    def stop_translation(self):
        self.action_button.setText("Start Translation")
        self.action_button.setStyleSheet("""
            QPushButton {
                background-color: #4a90d9;
                color: white;
                padding: 15px 60px;
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover {
                background-color: #3a80c9;
            }
        """)
        
        if self.translator_thread:
            self.translator_thread.stop()
            self.translator_thread = None
        
        if self.audio_player:
            self.audio_player.stop()
            self.audio_player = None
        
        self.update_status("Translation stopped. Ready.")
    
    def on_translate(self, text):
        self.output_text.append(f"> {text}")
        # Auto scroll to bottom
        scroll_bar = self.output_text.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())
    
    def on_audio(self, audio_data):
        if self.audio_player:
            self.audio_player.add_audio(audio_data)
    
    def on_error(self, error):
        self.output_text.append(f"[ERROR] {error}")
        self.update_status(f"Error: {error}")
        
        # 提供更友好的错误提示
        if "timeout" in error.lower() or "not accessible" in error.lower():
            QMessageBox.critical(self, "Connection Error", 
                f"Failed to connect to translation server:\n\n{error}\n\n"
                "Please check:\n"
                "1. Your network connection\n"
                "2. The server URL in translator.py\n"
                "3. Your API Key is valid")
        else:
            QMessageBox.critical(self, "Error", error)
        
        self.stop_translation()
    
    def update_status(self, message):
        self.status_bar.showMessage(message)
    
    def on_translation_finished(self):
        if self.translator_thread and not self.translator_thread.isRunning():
            self.stop_translation()
    
    def closeEvent(self, event):
        if self.translator_thread and self.translator_thread.isRunning():
            self.stop_translation()
        event.accept()