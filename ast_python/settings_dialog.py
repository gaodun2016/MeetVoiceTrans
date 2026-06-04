from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QMessageBox, QCheckBox
)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt

class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("Settings")
        self.resize(400, 350)
        self.setModal(True)
        
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # API Key
        api_group = QVBoxLayout()
        api_group.setSpacing(5)
        
        api_label = QLabel("X-Api-Key")
        api_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        api_group.addWidget(api_label)
        
        api_row = QHBoxLayout()
        api_row.setSpacing(10)
        
        self.api_edit = QLineEdit()
        self.api_edit.setPlaceholderText("Enter your API key")
        self.api_edit.setText(self.config.api_key)
        self.api_edit.setEchoMode(QLineEdit.EchoMode.Password)
        api_row.addWidget(self.api_edit)
        
        self.show_key = QCheckBox("Show")
        self.show_key.stateChanged.connect(self.toggle_key_visibility)
        api_row.addWidget(self.show_key)
        
        api_group.addLayout(api_row)
        layout.addLayout(api_group)
        
        # Languages
        lang_group = QHBoxLayout()
        lang_group.setSpacing(20)
        
        src_group = QVBoxLayout()
        src_group.setSpacing(5)
        src_label = QLabel("Source Language")
        src_label.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        src_group.addWidget(src_label)
        
        self.src_combo = QComboBox()
        self.src_combo.addItems(["Chinese (zh)", "English (en)", "Japanese (ja)", "Korean (ko)"])
        idx = self.src_combo.findText(f"{self._lang_name(self.config.source_language)} ({self.config.source_language})")
        if idx >= 0:
            self.src_combo.setCurrentIndex(idx)
        src_group.addWidget(self.src_combo)
        lang_group.addLayout(src_group)
        
        tgt_group = QVBoxLayout()
        tgt_group.setSpacing(5)
        tgt_label = QLabel("Target Language")
        tgt_label.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        tgt_group.addWidget(tgt_label)
        
        self.tgt_combo = QComboBox()
        self.tgt_combo.addItems(["English (en)", "Chinese (zh)", "Japanese (ja)", "Korean (ko)"])
        idx = self.tgt_combo.findText(f"{self._lang_name(self.config.target_language)} ({self.config.target_language})")
        if idx >= 0:
            self.tgt_combo.setCurrentIndex(idx)
        tgt_group.addWidget(self.tgt_combo)
        lang_group.addLayout(tgt_group)
        
        layout.addLayout(lang_group)
        
        # Output Device
        device_group = QVBoxLayout()
        device_group.setSpacing(5)
        
        device_label = QLabel("Output Device ID")
        device_label.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        device_group.addWidget(device_label)
        
        self.device_edit = QLineEdit()
        self.device_edit.setPlaceholderText("Leave empty for default")
        self.device_edit.setText(str(self.config.output_device) if self.config.output_device >= 0 else "")
        device_group.addWidget(self.device_edit)
        
        layout.addLayout(device_group)
        
        # Buttons
        btn_group = QHBoxLayout()
        btn_group.setSpacing(10)
        btn_group.setAlignment(Qt.AlignmentFlag.AlignRight)
        
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self.save)
        btn_group.addWidget(self.save_btn)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        btn_group.addWidget(self.cancel_btn)
        
        layout.addLayout(btn_group)
        
        self.setLayout(layout)
    
    def toggle_key_visibility(self, state):
        if state == Qt.CheckState.Checked.value:
            self.api_edit.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            self.api_edit.setEchoMode(QLineEdit.EchoMode.Password)
    
    def _lang_name(self, code):
        lang_map = {"zh": "Chinese", "en": "English", "ja": "Japanese", "ko": "Korean"}
        return lang_map.get(code, code)
    
    def _lang_code(self, text):
        if "zh" in text:
            return "zh"
        elif "en" in text:
            return "en"
        elif "ja" in text:
            return "ja"
        elif "ko" in text:
            return "ko"
        return "en"
    
    def save(self):
        api_key = self.api_edit.text().strip()
        if not api_key:
            QMessageBox.warning(self, "Warning", "Please enter X-Api-Key")
            return
        
        self.config.api_key = api_key
        self.config.source_language = self._lang_code(self.src_combo.currentText())
        self.config.target_language = self._lang_code(self.tgt_combo.currentText())
        
        device_text = self.device_edit.text().strip()
        self.config.output_device = int(device_text) if device_text else -1
        
        self.config.save()
        QMessageBox.information(self, "Success", "Settings saved successfully")
        self.accept()