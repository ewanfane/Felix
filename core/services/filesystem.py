import os
from pathlib import Path
from django.conf import settings

class FileSystemService:
    def __init__(self, user_id="default"):
        # The base sandbox for this specific user
        self.root_path = (Path(settings.MEDIA_ROOT) / "user_documents" / user_id).resolve()
        self.root_path.mkdir(parents=True, exist_ok=True)

    def _is_safe_path(self, path):
        """Prevents directory traversal."""
        try:
            # Join and resolve to check if it's still inside root_path
            target_path = (self.root_path / path).resolve()
            return str(target_path).startswith(str(self.root_path))
        except Exception:
            return False

    def list_files(self, subpath="."):
        """Returns a visual tree, masking the user_id root."""
        if not self._is_safe_path(subpath):
            return "Error: Access Denied"
        
        target = self.root_path / subpath
        if not target.exists():
            return "Directory is empty."

        tree_str = ""
        # We walk the directory but we want to show paths RELATIVE to root_path
        for root, dirs, files in os.walk(target):
            # Calculate depth relative to the target
            rel_root = os.path.relpath(root, target)
            level = 0 if rel_root == "." else rel_root.count(os.sep) + 1
            
            if level > 2: continue 
            
            indent = ' ' * 4 * level
            # We use '.' for the root of the sandbox to keep it clear for the AI
            folder_name = os.path.basename(root) if rel_root != "." else "root"
            tree_str += f"{indent}{folder_name}/\n"
            
            subindent = ' ' * 4 * (level + 1)
            for f in files:
                tree_str += f"{subindent}{f}\n"
                
        return tree_str if tree_str else "Directory is empty."

    def read_file(self, filepath):
        # Normalize the path: if AI sends /passwords.txt or ./passwords.txt
        clean_path = filepath.lstrip('./')
        
        if not self._is_safe_path(clean_path):
            return "Error: Access Denied"
            
        target = self.root_path / clean_path
        if target.exists() and target.is_file():
            return target.read_text(encoding='utf-8', errors='ignore')
        
        # Debugging info for you in the logs
        print(f"FileSystem Error: AI tried to read {filepath}, resolved to {target}")
        return "Error: File not found"

    def write_file(self, filepath, content):
        clean_path = filepath.lstrip('./')
        if not self._is_safe_path(clean_path):
            return "Error: Access Denied"
            
        target = self.root_path / clean_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')
        return f"Saved to {clean_path}"