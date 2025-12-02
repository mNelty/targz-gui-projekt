
import sqlite3
import os

class DBManager:
    def __init__(self, db_path='library.db'):
        # Ensure the database directory exists
        db_dir = os.path.dirname(os.path.abspath(db_path))
        if not os.path.exists(db_dir):
            os.makedirs(db_dir)
            
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()
        self._create_tables()

    def _create_tables(self):
        """Creates the necessary tables if they don't exist."""
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS packages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                version TEXT,
                install_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS installed_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                package_id INTEGER,
                path TEXT NOT NULL,
                FOREIGN KEY (package_id) REFERENCES packages(id)
            )
        ''')
        self.conn.commit()

    def add_package(self, name, version, files):
        """Adds a new package and its files to the database."""
        self.cursor.execute("INSERT INTO packages (name, version) VALUES (?, ?)", (name, version))
        package_id = self.cursor.lastrowid
        
        file_records = [(package_id, file_path) for file_path in files]
        self.cursor.executemany("INSERT INTO installed_files (package_id, path) VALUES (?, ?)", file_records)
        
        self.conn.commit()
        return package_id

    def get_files_for_package(self, package_id):
        """Retrieves all file paths for a given package ID."""
        self.cursor.execute("SELECT path FROM installed_files WHERE package_id = ?", (package_id,))
        return [row[0] for row in self.cursor.fetchall()]

    def close(self):
        """Closes the database connection."""
        self.conn.close()

# Example usage (for testing)
if __name__ == '__main__':
    # Use an in-memory database for testing
    db_manager = DBManager(':memory:')
    
    print("Database and tables created.")
    
    # Test adding a package
    package_name = "test-package"
    package_version = "1.0"
    files_installed = [
        "/usr/local/bin/test-app",
        "/usr/local/lib/libtest.so",
        "/usr/local/share/doc/test-package/README"
    ]
    
    package_id = db_manager.add_package(package_name, package_version, files_installed)
    print(f"Added package '{package_name}' with ID: {package_id}")

    # Test retrieving files for the package
    retrieved_files = db_manager.get_files_for_package(package_id)
    print(f"Retrieved {len(retrieved_files)} files for package ID {package_id}:")
    for f in retrieved_files:
        print(f"- {f}")
        
    assert set(files_installed) == set(retrieved_files)
    print("\nTest successful!")
    
    db_manager.close()
