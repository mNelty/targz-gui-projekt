
import sys
from PyQt5.QtWidgets import (QApplication, QDialog, QVBoxLayout, QHBoxLayout, 
                             QTreeView, QTextEdit, QPushButton, QSplitter)
from PyQt5.QtGui import QStandardItemModel, QStandardItem
from PyQt5.QtCore import Qt

from ..core.installer import Installer

class InspectionDialog(QDialog):
    def __init__(self, archive_path, parent=None):
        super().__init__(parent)
        self.archive_path = archive_path
        
        self.setWindowTitle("Package Inspection")
        self.setGeometry(150, 150, 900, 700)
        
        # --- Layouts ---
        main_layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)
        
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)

        # --- Widgets ---
        self.tree_view = QTreeView()
        self.tree_model = QStandardItemModel()
        self.tree_view.setModel(self.tree_model)
        self.tree_view.setHeaderHidden(True)
        
        self.text_viewer = QTextEdit()
        self.text_viewer.setReadOnly(True)
        self.text_viewer.setFontFamily("monospace")

        self.proceed_button = QPushButton("Proceed with Installation")
        self.cancel_button = QPushButton("Cancel")

        # --- Assembly ---
        left_layout.addWidget(self.tree_view)
        right_layout.addWidget(self.text_viewer)
        
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.proceed_button)
        main_layout.addLayout(button_layout)
        
        # --- Connections ---
        self.proceed_button.clicked.connect(self.accept) # QDialog.accept()
        self.cancel_button.clicked.connect(self.reject) # QDialog.reject()
        self.tree_view.clicked.connect(self.on_tree_item_clicked)
        
        # --- Populate Data ---
        self.populate_tree()

    def populate_tree(self):
        members = Installer.list_archive_contents(self.archive_path)
        
        root_item = self.tree_model.invisibleRootItem()
        path_map = {'': root_item}

        for member in sorted(members, key=lambda x: x.name):
            path_parts = member.name.strip('/').split('/')
            parent_path = ''
            parent = root_item
            
            for part in path_parts[:-1]:
                parent_path += part + '/'
                if parent_path in path_map:
                    parent = path_map[parent_path]
                else:
                    new_parent = QStandardItem(part)
                    parent.appendRow(new_parent)
                    path_map[parent_path] = new_parent
                    parent = new_parent
            
            item = QStandardItem(path_parts[-1])
            item.setData(member.name, Qt.UserRole)
            item.setEditable(False)
            
            # Highlight potentially dangerous files
            if member.name.endswith(('.sh', '.py', '.pl')):
                font = item.font()
                font.setBold(True)
                item.setFont(font)

            parent.appendRow(item)
            if member.isdir():
                path_map[member.name + '/'] = item

    def on_tree_item_clicked(self, index):
        item = self.tree_model.itemFromIndex(index)
        member_name = item.data(Qt.UserRole)
        
        if member_name:
            # Check if it's not a directory
            is_dir = member_name.endswith('/')
            if not is_dir:
                content = Installer.read_file_from_archive(self.archive_path, member_name)
                self.text_viewer.setText(content)
            else:
                self.text_viewer.setText(f"--- Directory: {member_name} ---")


# Standalone execution for testing
if __name__ == '__main__':
    app = QApplication(sys.argv)
    # Pass a dummy path
    dialog = InspectionDialog("dummy_path.tar.gz")
    if dialog.exec_() == QDialog.Accepted:
        print("User chose to proceed.")
    else:
        print("User cancelled.")
    sys.exit(0)
