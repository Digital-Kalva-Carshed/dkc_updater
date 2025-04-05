import sys
import os
import tempfile
import json
import shutil
from pathlib import Path
import requests
from zipfile import ZipFile
from PySide6.QtWidgets import (QApplication, QMainWindow, QLabel, QProgressBar, 
                             QPushButton, QVBoxLayout, QHBoxLayout, QWidget, 
                             QMessageBox, QFrame, QSplashScreen)
from PySide6.QtCore import QThread, Signal, Qt, QUrl, QTimer, QSize, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap, QColor, QPalette, QFont, QFontDatabase

# Constants
CONFIG_FILE = "updater_config.json"
STYLE_LIGHT_BG = QColor(240, 244, 247)
STYLE_ACCENT = QColor(66, 133, 244)  # Blue accent color
STYLE_SUCCESS = QColor(52, 168, 83)  # Green for success
STYLE_ERROR = QColor(234, 67, 53)    # Red for error
STYLE_TEXT = QColor(33, 33, 33)      # Dark text
STYLE_SECONDARY_TEXT = QColor(95, 99, 104)  # Secondary text

class StyleHelper:
    @staticmethod
    def setup_application_style(app):
        # Add custom font
        font_id = QFontDatabase.addApplicationFont("src/static/fonts/Roboto.ttf")
        if font_id != -1:
            font_family = QFontDatabase.applicationFontFamilies(font_id)[0]
            custom_font = QFont(font_family)
            app.setFont(custom_font)
        else:
            print("Font failed to load, using system default")
            
        # Set application palette
        palette = QPalette()
        palette.setColor(QPalette.Window, STYLE_LIGHT_BG)
        palette.setColor(QPalette.WindowText, STYLE_TEXT)
        palette.setColor(QPalette.Button, STYLE_LIGHT_BG)
        palette.setColor(QPalette.ButtonText, STYLE_TEXT)
        palette.setColor(QPalette.Base, Qt.white)
        palette.setColor(QPalette.AlternateBase, QColor(245, 245, 245))
        palette.setColor(QPalette.ToolTipBase, STYLE_LIGHT_BG)
        palette.setColor(QPalette.ToolTipText, STYLE_TEXT)
        palette.setColor(QPalette.Text, STYLE_TEXT)
        palette.setColor(QPalette.PlaceholderText, STYLE_SECONDARY_TEXT)
        app.setPalette(palette)
        
        # Apply global stylesheet
        app.setStyleSheet("""
            QMainWindow {
                background-color: #F0F4F7;
                border: none;
            }
            QLabel {
                color: #212121;
            }
            QPushButton {
                background-color: #4285F4;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 20px;
                font-size: 14px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #5294FF;
            }
            QPushButton:pressed {
                background-color: #3B78E7;
            }
            QPushButton:disabled {
                background-color: #A4C2F4;
                color: #F0F4F7;
            }
            QProgressBar {
                border: none;
                border-radius: 4px;
                text-align: center;
                height: 8px;
                background-color: #E0E0E0;
            }
            QProgressBar::chunk {
                background-color: #4285F4;
                border-radius: 4px;
            }
            QFrame.Card {
                background-color: white;
                border-radius: 8px;
                border: 1px solid #E0E0E0;
            }
        """)

class AnimatedButton(QPushButton):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setFixedHeight(40)
        self._animation = QPropertyAnimation(self, b"size")
        self._animation.setDuration(100)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        
    def enterEvent(self, event):
        current_size = self.size()
        self._animation.setStartValue(current_size)
        self._animation.setEndValue(QSize(current_size.width(), current_size.height() + 4))
        self._animation.start()
        super().enterEvent(event)
        
    def leaveEvent(self, event):
        current_size = self.size()
        self._animation.setStartValue(current_size)
        self._animation.setEndValue(QSize(current_size.width(), 40))
        self._animation.start()
        super().leaveEvent(event)

class CardFrame(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setProperty("class", "Card")
        
class DownloadThread(QThread):
    """Thread for downloading files without freezing UI"""
    progress_signal = Signal(int)
    status_signal = Signal(str)
    completed_signal = Signal(bool, str)
    
    def __init__(self, url, download_path):
        super().__init__()
        self.url = url
        self.download_path = download_path
        
    def run(self):
        try:
            self.status_signal.emit("Starting download...")
            response = requests.get(self.url, stream=True)
            response.raise_for_status()
            
            # Get file size if possible
            total_size = int(response.headers.get('content-length', 0))
            
            # Create temporary file
            with open(self.download_path, 'wb') as f:
                downloaded = 0
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        downloaded += len(chunk)
                        f.write(chunk)
                        if total_size:
                            progress = int((downloaded / total_size) * 100)
                            self.progress_signal.emit(progress)
                        self.status_signal.emit(f"Downloading... {downloaded/1024/1024:.1f} MB")
            
            self.status_signal.emit("Download completed!")
            self.completed_signal.emit(True, self.download_path)
        except Exception as e:
            self.status_signal.emit(f"Error: {str(e)}")
            self.completed_signal.emit(False, str(e))

class UpdaterApp(QMainWindow):
    def __init__(self):
        super().__init__(None, Qt.WindowStaysOnTopHint)
        self.setWindowTitle("Application Updater")
        self.setMinimumSize(600, 500)
        
        # Initialize variables
        self.download_thread = None
        self.temp_dir = tempfile.mkdtemp()
        self.download_path = os.path.join(self.temp_dir, "update.zip")
        
        # Create splash screen
        self.show_splash_screen()
        
        # Set up the UI
        self.setup_ui()
        
        # Load configuration
        self.config = self.load_config()
        self.update_available = False
        
        # Check for updates on startup
        QTimer.singleShot(1500, self.check_for_updates)
    
    def show_splash_screen(self):
        # Use a default splash image if none exists
        splash_path = "src/static/images/splash.jpg"
        if not os.path.exists(splash_path):
            # Create a simple colored splash with icon
            splash_pixmap = QPixmap(400, 300)
            splash_pixmap.fill(STYLE_LIGHT_BG)
            self.splash = QSplashScreen(splash_pixmap, Qt.WindowStaysOnTopHint)
            self.splash.showMessage("Starting updater...", Qt.AlignBottom | Qt.AlignCenter, STYLE_TEXT)
        else:
            self.splash = QSplashScreen(QPixmap(splash_path), Qt.WindowStaysOnTopHint)
        
        self.splash.show()
    
    def setup_ui(self):
        # Set window icon
        if os.path.exists("logo.ico"):
            self.setWindowIcon(QIcon("logo.ico"))
        
        # Create central widget
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # App header with logo
        header_layout = QHBoxLayout()
        
        # Logo (if available)
        if os.path.exists("src/static/images/logo.png"):
            logo_label = QLabel()
            logo_pixmap = QPixmap("src/static/images/logo.png").scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo_label.setPixmap(logo_pixmap)
            header_layout.addWidget(logo_label)
        
        # App title
        app_title = QLabel("Application Updater")
        app_title.setStyleSheet("font-size: 22px; font-weight: bold; color: #212121;")
        header_layout.addWidget(app_title)
        header_layout.addStretch()
        main_layout.addLayout(header_layout)
        
        # Card widget for main content
        card = CardFrame()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(30, 30, 30, 30)
        card_layout.setSpacing(20)
        
        # Status section
        self.status_icon = QLabel()
        self.status_icon.setFixedSize(48, 48)
        self.status_label = QLabel("Checking for updates...")
        self.status_label.setStyleSheet("font-size: 16px; font-weight: 500;")
        
        status_layout = QHBoxLayout()
        status_layout.addWidget(self.status_icon)
        status_layout.addWidget(self.status_label, 1)
        card_layout.addLayout(status_layout)
        
        # Version info
        self.version_label = QLabel("Current version: Checking...")
        self.version_label.setStyleSheet("color: #5F6368;")
        card_layout.addWidget(self.version_label)
        
        # Progress section
        progress_container = QFrame()
        progress_layout = QVBoxLayout(progress_container)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumHeight(8)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        
        progress_layout.addWidget(self.progress_bar)
        card_layout.addWidget(progress_container)
        
        # Button section
        button_layout = QHBoxLayout()
        
        self.check_btn = AnimatedButton("   Check for Updates")
        self.check_btn.clicked.connect(self.check_for_updates)
        self.check_btn.setIcon(QIcon.fromTheme("view-refresh", QIcon()))
        
        self.download_btn = AnimatedButton("Download and Install")
        self.download_btn.clicked.connect(self.download_update)
        self.download_btn.setEnabled(False)
        self.download_btn.setIcon(QIcon.fromTheme("download", QIcon()))
        
        button_layout.addWidget(self.check_btn)
        button_layout.addWidget(self.download_btn)
        card_layout.addLayout(button_layout)
        
        # Release notes section (hidden by default)
        self.notes_frame = QFrame()
        self.notes_frame.setVisible(False)
        notes_layout = QVBoxLayout(self.notes_frame)
        
        notes_title = QLabel("Release Notes")
        notes_title.setStyleSheet("font-weight: bold; font-size: 14px;")
        
        self.notes_content = QLabel()
        self.notes_content.setStyleSheet("background-color: #F5F5F5; padding: 10px; border-radius: 4px;")
        self.notes_content.setWordWrap(True)
        
        notes_layout.addWidget(notes_title)
        notes_layout.addWidget(self.notes_content)
        
        card_layout.addWidget(self.notes_frame)
        
        # Add card to main layout
        main_layout.addWidget(card, 1)
        
        # Footer with website link
        footer = QHBoxLayout()
        footer.addStretch()
        
        self.website_btn = QPushButton("Visit Website")
        self.website_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #4285F4;
                border: none;
                padding: 5px;
                font-size: 13px;
            }
            QPushButton:hover {
                text-decoration: underline;
                background-color: transparent;
            }
        """)
        self.website_btn.clicked.connect(self.open_website)
        
        footer.addWidget(self.website_btn)
        main_layout.addLayout(footer)
        
        self.setCentralWidget(central_widget)
    
    def load_config(self):
        """Load configuration from JSON file"""
        default_config = {
            "app_name": "YourApp",
            "current_version": "1.0.0",
            "update_url": "https://yourusername.github.io/app-updates/latest.json",
            "website_url": "https://yourusername.github.io/app-updates/"
        }
        
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    return json.load(f)
            else:
                # Create default config if not exists
                with open(CONFIG_FILE, 'w') as f:
                    json.dump(default_config, f, indent=4)
                return default_config
        except Exception as e:
            if hasattr(self, 'splash'):
                self.splash.hide()
            QMessageBox.warning(self, "Configuration Error", f"Error loading configuration: {str(e)}")
            return default_config
    
    def set_status(self, message, icon_type="info"):
        """Set status message with appropriate icon"""
        self.status_label.setText(message)
        
        # Set icon based on type
        icon_pixmap = QPixmap(10, 10)
        if icon_type == "success":
            icon_pixmap.fill(STYLE_SUCCESS)
        elif icon_type == "error":
            icon_pixmap.fill(STYLE_ERROR)
        elif icon_type == "update":
            icon_pixmap.fill(STYLE_ACCENT)
        else:  # info
            icon_pixmap.fill(STYLE_SECONDARY_TEXT)
            
        self.status_icon.setPixmap(icon_pixmap)
    
    def check_for_updates(self):
        """Check for updates from the update URL"""
        self.set_status("Checking for updates...")
        self.download_btn.setEnabled(False)
        self.notes_frame.setVisible(False)
        
        try:
            response = requests.get(self.config["update_url"], timeout=10)
            response.raise_for_status()
            
            update_info = response.json()
            latest_version = update_info.get("version")
            current_version = self.config["current_version"]
            self.update_url = update_info.get("download_url")
            self.update_notes = update_info.get("notes", "")
            
            # Update version label
            self.version_label.setText(f"Current version: {current_version}")
            
            # Close splash screen if it's showing
            if hasattr(self, 'splash') and self.splash.isVisible():
                self.splash.finish(self)
            
            if self.is_newer_version(latest_version, current_version):
                self.set_status(f"Update available: v{latest_version}", "update")
                self.download_btn.setEnabled(True)
                self.update_available = True
                
                # Show release notes
                if self.update_notes:
                    self.notes_content.setText(self.update_notes)
                    self.notes_frame.setVisible(True)
                
            else:
                self.set_status(f"You have the latest version (v{current_version})", "success")
                self.update_available = False
        
        except Exception as e:
            self.set_status(f"Error checking for updates", "error")
            
            # Close splash screen if it's showing
            if hasattr(self, 'splash') and self.splash.isVisible():
                self.splash.finish(self)
                
            QMessageBox.warning(self, "Update Check Failed", f"Error: {str(e)}")
    
    def is_newer_version(self, version_a, version_b):
        """Compare version strings (simple implementation)"""
        try:
            # Convert version strings to tuples of integers
            ver_a = tuple(map(int, version_a.split('.')))
            ver_b = tuple(map(int, version_b.split('.')))
            return ver_a > ver_b
        except:
            # Fallback for invalid version strings
            return version_a != version_b
    
    def download_update(self):
        """Download the update zip file"""
        if not self.update_available or not self.update_url:
            return
        
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.check_btn.setEnabled(False)
        self.download_btn.setEnabled(False)
        
        # Create and start download thread
        self.download_thread = DownloadThread(self.update_url, self.download_path)
        self.download_thread.progress_signal.connect(self.update_progress)
        self.download_thread.status_signal.connect(self.update_status)
        self.download_thread.completed_signal.connect(self.handle_download_complete)
        self.download_thread.start()
    
    def update_progress(self, progress):
        """Update progress bar"""
        self.progress_bar.setValue(progress)
    
    def update_status(self, message):
        """Update status label"""
        self.status_label.setText(message)
    
    def handle_download_complete(self, success, result):
        """Handle download completion"""
        if success:
            self.set_status("Installing update...", "info")
            self.install_update(result)
        else:
            self.set_status("Download failed!", "error")
            QMessageBox.critical(self, "Download Failed", f"Error: {result}")
            self.progress_bar.setVisible(False)
            self.check_btn.setEnabled(True)
            self.download_btn.setEnabled(True)
    
    def install_update(self, zip_path):
        """Extract the update and replace files"""
        try:
            app_dir = os.path.dirname(os.path.abspath(__file__))
            extract_dir = os.path.join(self.temp_dir, "extracted")
            
            # Create extraction directory
            if not os.path.exists(extract_dir):
                os.makedirs(extract_dir)
            
            # Extract the zip file
            with ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            
            # Update the app directory with new files
            self.copy_with_overwrite(extract_dir, app_dir)
            
            # Update the configuration with new version
            try:
                version_file = os.path.join(extract_dir, "version.json")
                if os.path.exists(version_file):
                    with open(version_file, 'r') as f:
                        version_info = json.load(f)
                        self.config["current_version"] = version_info.get("version", self.config["current_version"])
                
                # Save updated config
                with open(CONFIG_FILE, 'w') as f:
                    json.dump(self.config, f, indent=4)
            except Exception as e:
                print(f"Error updating version: {str(e)}")
            
            # Show success message
            self.set_status("Update installed successfully!", "success")
            QMessageBox.information(self, "Update Complete", 
                                  "The application has been updated successfully!\nPlease restart the application.")
            
            self.check_btn.setEnabled(True)
        
        except Exception as e:
            self.set_status("Installation failed!", "error")
            QMessageBox.critical(self, "Installation Failed", f"Error: {str(e)}")
            self.check_btn.setEnabled(True)
            self.download_btn.setEnabled(True)
        
        finally:
            self.progress_bar.setVisible(False)
    
    def copy_with_overwrite(self, src_dir, dst_dir):
        """Copy files from src_dir to dst_dir, overwriting existing files"""
        for item in os.listdir(src_dir):
            src_path = os.path.join(src_dir, item)
            dst_path = os.path.join(dst_dir, item)
            
            # Skip updating the updater executable itself
            if item.lower() == "updater.exe" or item.lower() == "updater.py":
                continue
                
            if os.path.isdir(src_path):
                if not os.path.exists(dst_path):
                    os.makedirs(dst_path)
                self.copy_with_overwrite(src_path, dst_path)
            else:
                shutil.copy2(src_path, dst_path)
    
    def open_website(self):
        """Open the project website"""
        QDesktopServices.openUrl(QUrl(self.config["website_url"]))
    
    def closeEvent(self, event):
        """Handle application close event"""
        # Clean up temporary directory
        try:
            shutil.rmtree(self.temp_dir)
        except:
            pass
        event.accept()

def main():
    app = QApplication(sys.argv)
    
    # Set application style
    StyleHelper.setup_application_style(app)
    
    # Create folders if they don't exist
    os.makedirs("src/static/fonts", exist_ok=True)
    
    window = UpdaterApp()
    window.setFixedHeight(550)
    window.setFixedWidth(600)
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()