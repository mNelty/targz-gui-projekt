
import tarfile
import tempfile
import os
import subprocess
import re
import shutil
from .db_manager import DBManager

class Installer:
    def __init__(self, file_path, log_callback=None, db_manager=None):
        self.file_path = file_path
        self.temp_dir = None
        self.log_callback = log_callback or (lambda msg: print(msg))
        self.db_manager = db_manager

    def _log(self, message):
        """Logs a message using the provided callback."""
        self.log_callback(message)

    def extract_package(self):
        """Extracts the .tar.gz file to a temporary directory."""
        if not self.file_path.endswith('.tar.gz'):
            raise ValueError("Invalid file type. Only .tar.gz is supported.")
        
        self.temp_dir = tempfile.mkdtemp(prefix="library_")
        self._log(f"Extracting {self.file_path} to {self.temp_dir}")
        
        try:
            with tarfile.open(self.file_path, 'r:gz') as tar:
                # To handle nested directories correctly, find the root directory inside the tarball
                members = tar.getmembers()
                if members:
                    # Often the content is inside a single root folder, e.g., package-1.0/
                    root_folder = members[0].name.split('/')[0]
                    self.extracted_path = os.path.join(self.temp_dir, root_folder)
                else:
                    self.extracted_path = self.temp_dir

                tar.extractall(path=self.temp_dir)
                self._log(f"Extraction successful to {self.extracted_path}")
                return self.extracted_path
        except tarfile.TarError as e:
            self._log(f"Error extracting tar file: {e}")
            self.cleanup()
            return None

    def detect_build_system(self):
        """Detects the build system by checking for specific files."""
        if not self.extracted_path or not os.path.isdir(self.extracted_path):
            self._log("Extracted path not found.")
            return None

        if os.path.exists(os.path.join(self.extracted_path, 'configure')):
            return 'autotools'
        elif os.path.exists(os.path.join(self.extracted_path, 'CMakeLists.txt')):
            return 'cmake'
        elif os.path.exists(os.path.join(self.extracted_path, 'setup.py')):
            return 'python'
        elif os.path.exists(os.path.join(self.extracted_path, 'Makefile')):
            return 'make'
        return None

    def _parse_error_for_dependencies(self, error_output):
        """Parses stderr output to find potential missing dependencies."""
        # For missing header files, e.g., "fatal error: xyz.h: No such file or directory"
        header_match = re.search(r"fatal error: ([\w\/\.]+\.h):", error_output)
        if header_match:
            missing_header = header_match.group(1)
            # A common strategy is to search for the package providing this file.
            # For now, we will suggest a package name based on common conventions.
            # E.g., for "X11/Xlib.h", the package is often "libx11-dev"
            # This is a heuristic and might need a more robust solution like `apt-file`.
            self._log(f"Potential missing header file: {missing_header}. Try installing a related '-dev' package.")
            return f"package containing {missing_header}" # Placeholder

        # For missing libraries, e.g., "/usr/bin/ld: cannot find -lxyz"
        lib_match = re.search(r"cannot find -l(\w+)", error_output)
        if lib_match:
            missing_lib = lib_match.group(1)
            suggested_package = f"lib{missing_lib}-dev"
            self._log(f"Potential missing library: lib{missing_lib}. Suggested package: {suggested_package}")
            return suggested_package

        return None

    def run_installation(self):
        """Runs the installation process based on the detected build system."""
        build_system = self.detect_build_system()
        if not build_system:
            self._log("Could not detect a known build system.")
            return False, "Build system not detected"

        self._log(f"Detected build system: {build_system}")

        commands = {
            'autotools': [['./configure'], ['make'], ['make', 'install']],
            'cmake': [['cmake', '.'], ['make'], ['make', 'install']],
            'python': [['python3', 'setup.py', 'install']], # Note: setup.py install often needs --prefix
            'make': [['make'], ['make', 'install']]
        }
        
        install_commands = commands.get(build_system, [])

        # Separate build commands from install commands
        build_commands = [cmd for cmd in install_commands if 'install' not in ' '.join(cmd)]
        install_commands_only = [cmd for cmd in install_commands if 'install' in ' '.join(cmd)]

        # --- 1. Run Build Commands ---
        for command in build_commands:
            self._log(f"\n--- Running build command: {' '.join(command)} ---")
            try:
                process = subprocess.Popen(command, cwd=self.extracted_path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
                full_output = ""
                for line in iter(process.stdout.readline, ''):
                    self._log(line.strip())
                    full_output += line
                process.stdout.close()
                return_code = process.wait()
                if return_code != 0:
                    self._log(f"Error executing command: {' '.join(command)}")
                    missing_package = self._parse_error_for_dependencies(full_output)
                    if missing_package:
                        error_info = {"type": "dependency", "package": missing_package}
                        return False, error_info
                    return False, f"Command failed: {' '.join(command)}"
            except FileNotFoundError:
                self._log(f"Error: Command '{command[0]}' not found. Is it in your PATH?")
                return False, f"Command not found: {command[0]}"

        self._log("\nBuild process completed successfully.")

        # --- 2. Run Install Command with DESTDIR for tracking ---
        if not install_commands_only:
            self._log("No installation command found. Skipping file tracking.")
            return True, "Build successful (no install step)"

        install_command = install_commands_only[0]
        staging_dir = tempfile.mkdtemp(prefix="library_staging_")
        self._log(f"Created staging directory for installation tracking: {staging_dir}")

        env = os.environ.copy()
        env['DESTDIR'] = staging_dir
        
        self._log(f"\n--- Running install command: {' '.join(install_command)} with DESTDIR={staging_dir} ---")
        
        process = subprocess.Popen(install_command, cwd=self.extracted_path, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                   text=True, bufsize=1)
        
        for line in iter(process.stdout.readline, ''):
            self._log(line.strip())
        
        process.stdout.close()
        return_code = process.wait()

        if return_code != 0:
            self._log(f"Error executing install command: {' '.join(install_command)}")
            shutil.rmtree(staging_dir)
            return False, "Installation command failed"

        # --- 3. Track Installed Files ---
        installed_files = []
        for root, _, files in os.walk(staging_dir):
            for file in files:
                full_path = os.path.join(root, file)
                # Get the relative path from the staging dir to represent the final path
                relative_path = os.path.relpath(full_path, staging_dir)
                installed_files.append('/' + relative_path)

        self._log(f"Tracked {len(installed_files)} installed files:")
        for file in installed_files:
            self._log(f"- {file}")

        if self.db_manager and installed_files:
            package_name = self._get_package_name()
            package_version = self._get_package_version()
            self._log(f"Saving package '{package_name}-{package_version}' to database.")
            self.db_manager.add_package(package_name, package_version, installed_files)
            self._log("Package information saved successfully.")
        
        shutil.rmtree(staging_dir)
        self._log("Cleaned up staging directory.")

        self._log("\nInstallation tracking finished.")
        return True, "Success"

    def _get_package_name(self):
        """Extracts a plausible package name from the archive filename."""
        basename = os.path.basename(self.file_path)
        # Assuming format like 'package-name-1.2.3.tar.gz'
        parts = basename.replace('.tar.gz', '').split('-')
        # Filter out version-like parts
        name_parts = [p for p in parts if not re.match(r'^\d', p)]
        return '-'.join(name_parts) or "unknown_package"

    def _get_package_version(self):
        """Extracts a plausible version from the archive filename."""
        basename = os.path.basename(self.file_path)
        # Find numeric parts that look like versions
        matches = re.findall(r'(\d+\.\d+\.\d+|\d+\.\d+)', basename)
        return matches[0] if matches else "unknown"


    def cleanup(self):
        """Removes the temporary directory."""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
            self._log(f"Cleaned up temporary directory: {self.temp_dir}")

    @staticmethod
    def list_archive_contents(archive_path):
        """Lists the contents of a .tar.gz archive."""
        try:
            with tarfile.open(archive_path, 'r:gz') as tar:
                return tar.getmembers()
        except tarfile.TarError:
            return []

    @staticmethod
    def read_file_from_archive(archive_path, member_name):
        """Reads the content of a single file from a .tar.gz archive."""
        try:
            with tarfile.open(archive_path, 'r:gz') as tar:
                member = tar.getmember(member_name)
                if member.isfile():
                    with tar.extractfile(member) as f:
                        return f.read().decode('utf-8', errors='ignore')
                return "--- Not a text file or directory ---"
        except (tarfile.TarError, KeyError):
            return "--- Error reading file from archive ---"


# Example usage (for testing)
if __name__ == '__main__':
    # A simple logger for testing
    def console_logger(message):
        print(f"[LOG] {message}")

    print("--- Running Test Case: Successful 'make' and 'install' with DESTDIR ---")
    dummy_dir_ok = 'dummy_package_ok-1.0' # Add version for testing
    os.makedirs(dummy_dir_ok, exist_ok=True)
    makefile_content = """
all:
	@echo "Build successful!"
install:
	@echo "Installing..."
	@mkdir -p $(DESTDIR)/usr/local/bin
	@echo "dummy content" > $(DESTDIR)/usr/local/bin/dummy_app
"""
    with open(os.path.join(dummy_dir_ok, 'Makefile'), 'w') as f:
        f.write(makefile_content)
    
    tar_path_ok = 'dummy_ok-1.0.tar.gz'
    with tarfile.open(tar_path_ok, 'w:gz') as tar:
        tar.add(dummy_dir_ok, arcname=os.path.basename(dummy_dir_ok))

    installer_ok = Installer(tar_path_ok, log_callback=console_logger)
    installer_ok.extract_package()
    installer_ok.run_installation()
    installer_ok.cleanup()
    os.remove(tar_path_ok)
    import shutil
    shutil.rmtree(dummy_dir_ok)

    print("\n--- Running Test Case: Missing Header Dependency ---")
    dummy_dir_fail = 'dummy_package_fail'
    os.makedirs(dummy_dir_fail, exist_ok=True)
    with open(os.path.join(dummy_dir_fail, 'main.c'), 'w') as f:
        f.write('#include <nonexistent.h>\nint main() { return 0; }')
    with open(os.path.join(dummy_dir_fail, 'Makefile'), 'w') as f:
        f.write('all:\n\tgcc main.c -o main')

    tar_path_fail = 'dummy_fail.tar.gz'
    with tarfile.open(tar_path_fail, 'w:gz') as tar:
        tar.add(dummy_dir_fail, arcname=os.path.basename(dummy_dir_fail))

    installer_fail = Installer(tar_path_fail, log_callback=console_logger)
    installer_fail.extract_package()
    installer_fail.run_installation()
    installer_fail.cleanup()
    os.remove(tar_path_fail)
    shutil.rmtree(dummy_dir_fail)

    print("\n--- Running Test Case: Archive Inspection ---")
    # Create a test archive
    dummy_inspect_dir = 'dummy_inspect'
    os.makedirs(dummy_inspect_dir, exist_ok=True)
    with open(os.path.join(dummy_inspect_dir, 'README.md'), 'w') as f:
        f.write('This is a test README.')
    with open(os.path.join(dummy_inspect_dir, 'run.sh'), 'w') as f:
        f.write('echo "Hello"')
    
    tar_inspect_path = 'dummy_inspect.tar.gz'
    with tarfile.open(tar_inspect_path, 'w:gz') as tar:
        tar.add(dummy_inspect_dir, arcname=os.path.basename(dummy_inspect_dir))

    # Test listing
    print("Listing contents:")
    members = Installer.list_archive_contents(tar_inspect_path)
    for member in members:
        print(f"- {member.name} ({'Dir' if member.isdir() else 'File'})")

    # Test reading a file
    print("\nReading README.md:")
    content = Installer.read_file_from_archive(tar_inspect_path, 'dummy_inspect/README.md')
    print(content)

    os.remove(tar_inspect_path)
    shutil.rmtree(dummy_inspect_dir)
