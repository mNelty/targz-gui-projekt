
import sys
import os
from PyQt5.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget, QTextEdit, QDialog, QMessageBox
from PyQt5.QtCore import QThread, pyqtSignal

from ..core.installer import Installer
from ..core.db_manager import DBManager
from .inspection_dialog import InspectionDialog

# --- Global DB Manager ---
config_dir = os.path.expanduser("~/.config/library")
os.makedirs(config_dir, exist_ok=True)
APP_DB_PATH = os.path.join(config_dir, "library.db")
db_manager = DBManager(APP_DB_PATH)


class Worker(QThread):
    """
    Worker thread to run the installation process without freezing the GUI.
    """
    progress = pyqtSignal(str)
    finished = pyqtSignal(str)
    dependency_found = pyqtSignal(str) # New signal for dependency issues

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path

    def run(self):
        installer = Installer(self.file_path, 
                              log_callback=self.progress.emit, 
                              db_manager=db_manager)
        
        extracted_path = installer.extract_package()
        if not extracted_path:
            self.finished.emit("Failed to extract package.")
            return
        
        success, result = installer.run_installation()
        
        if success:
            self.finished.emit("Installation completed successfully!")
        else:
            # Check if it's a dependency issue
            if isinstance(result, dict) and result.get("type") == "dependency":
                self.dependency_found.emit(result.get("package"))
            else:
                self.finished.emit(f"Installation failed: {result}")
            
        installer.cleanup()
        self.progress.emit("Cleanup complete.")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('LibRARy - .tar.gz Installer')
        self.setGeometry(100, 100, 800, 600)

        self.setAcceptDrops(True)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        self.drop_label = QLabel('Drag and drop a .tar.gz file here', self)
        self.drop_label.setStyleSheet('''
            QLabel {
                border: 2px dashed #aaa;
                border-radius: 5px;
                padding: 20px;
                font-size: 16px;
                text-align: center;
                color: #aaa;
            }
        ''')
        layout.addWidget(self.drop_label)

        self.log_viewer = QTextEdit(self)
        self.log_viewer.setReadOnly(True)
        self.log_viewer.setStyleSheet("QTextEdit { background-color: #222; color: #eee; font-family: monospace; }")
        layout.addWidget(self.log_viewer, 1) # Give it more stretch factor

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and event.mimeData().urls()[0].toLocalFile().endswith('.tar.gz'):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        file_path = event.mimeData().urls()[0].toLocalFile()
        
        # Open the inspection dialog
        dialog = InspectionDialog(file_path, self)
        
        # If the user clicks "Proceed", then start the installation
        if dialog.exec_() == QDialog.Accepted:
            self.drop_label.setText(f'Processing: {os.path.basename(file_path)}')
            self.log_viewer.clear()
            
            self.worker = Worker(file_path)
            self.worker.progress.connect(self.update_log)
            self.worker.finished.connect(self.on_installation_finished)
            self.worker.dependency_found.connect(self.handle_dependency_issue) # Connect the new signal
            self.worker.start()
        else:
            self.drop_label.setText('Drag and drop a .tar.gz file here')
            self.log_viewer.setText("Installation cancelled by user.")

    def update_log(self, message):
        self.log_viewer.append(message)

    def on_installation_finished(self, message):
        self.log_viewer.append(f"\n--- FINISHED ---\n{message}")
        self.drop_label.setText('Drag and drop a .tar.gz file here')

    def handle_dependency_issue(self, package_name):
        """Shows a dialog to the user to install a missing dependency."""
        self.update_log(f"Dependency issue: A required package '{package_name}' seems to be missing.")
        
        reply = QMessageBox.question(self, 'Missing Dependency',
                                     f"The package '{package_name}' appears to be missing.\n\n"
                                     f"Would you like to try installing it with 'sudo apt install {package_name}'?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            self.update_log(f"User approved installation of '{package_name}'.")
            self.update_log("NOTE: Automatic execution of 'sudo' is not yet implemented.")
            self.update_log("Please open a terminal and run the command manually for now.")
            # In a future version, this could trigger a secure process to run the sudo command.
        else:
            self.update_log("User declined to install the dependency. Installation aborted.")


if __name__ == '__main__':
    app = QApplication(sys.argv)
    main_win = MainWindow()
    main_win.show()
    sys.exit(app.exec_())
