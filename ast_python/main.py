import sys
import os

# Add python_protogen to path
sys.path.append(os.path.join(os.path.dirname(__file__), "python_protogen"))

from PyQt6.QtWidgets import QApplication
from main_window import MainWindow

def main():
    app = QApplication(sys.argv)
    
    # Set application style
    app.setStyle("Fusion")
    
    # Set application name
    app.setApplicationName("Meet Translator")
    app.setApplicationVersion("1.0.0")
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()