import os
import re
from pathlib import Path
from ..services.filesystem import FileSystemService

CANONICAL_PATHS = {
    "user_profile": "knowledge/user/profile.md",
    "user_preferences": "knowledge/user/preferences.md",
    "user_goals": "knowledge/user/goals.md",
    "agent_identity": "knowledge/agent/identity.md",
    "agent_capabilities": "knowledge/agent/capabilities.md",
}

CATEGORY_MAP = {
    "user_profile": {"profile", "identity", "name", "role", "background", "user"},
    "user_preferences": {"preference", "communication", "style", "likes", "dislikes"},
    "user_goals": {"goal", "objective", "aim", "want", "aspiration"},
    "agent_identity": {"agent", "identity", "ontology", "self", "role_definition", "felix"},
    "agent_capabilities": {"capability", "skill", "ability", "feature", "function"},
}

PROTECTED_PATHS = [
    "identity/",
    "user/",
    "learnings.md",
    "personality.md",
    "user_model.md",
    "KNOWLEDGE/",
    "knowledge/",
]


class FileManager:
    def __init__(self):
        self.fs = FileSystemService()

    def write_knowledge(self, category, content):
        path = CANONICAL_PATHS.get(category)
        if not path:
            return f"Unknown category: {category}"
        if not content or not content.strip():
            return f"Empty content for {category}"

        if category in ("user_profile", "agent_identity"):
            return self._write_overwrite(path, content)
        else:
            return self._write_append_dedup(path, content)

    def write_project_knowledge(self, project_name, content):
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', project_name.lower())[:40]
        path = f"knowledge/projects/{safe_name}.md"
        return self._write_overwrite(path, content)

    def classify_content(self, topic_name, content_text=""):
        topic_lower = topic_name.lower()
        content_lower = content_text.lower()
        scores = {}
        for category, keywords in CATEGORY_MAP.items():
            score = 0
            for kw in keywords:
                if kw in topic_lower:
                    score += 3
                if kw in content_lower:
                    score += 1
            scores[category] = score
        if not any(scores.values()):
            return "user_profile"
        return max(scores, key=scores.get)

    def _write_overwrite(self, path, content):
        self.fs.write_file(path, content)
        return f"Written to {path}"

    def _write_append_dedup(self, path, content):
        existing = self.fs.read_file(path)
        if not existing or existing.startswith("Error"):
            self.fs.write_file(path, content)
            return f"Created {path}"
        existing_lines = set(line.strip().lower() for line in existing.split("\n") if line.strip())
        new_lines = []
        added = 0
        for line in content.split("\n"):
            if line.strip() and line.strip().lower() not in existing_lines:
                new_lines.append(line)
                existing_lines.add(line.strip().lower())
                added += 1
        if not new_lines:
            return f"No new content for {path}"
        updated = existing.rstrip("\n") + "\n" + "\n".join(new_lines) + "\n"
        self.fs.write_file(path, updated)
        return f"Added {added} lines to {path}"

    def _walk_files(self):
        files = []
        for root, dirs, fnames in os.walk(self.fs.root_path):
            for fname in fnames:
                if fname.endswith((".md", ".json")):
                    full = os.path.join(root, fname)
                    rel = os.path.relpath(full, self.fs.root_path)
                    files.append(rel)
        return files

    def _is_protected(self, rel_path):
        for p in PROTECTED_PATHS:
            if rel_path.startswith(p):
                return True
        return False

    def consolidate_stale_files(self):
        all_content = {}
        files = self._walk_files()

        stale_files = [f for f in files if not self._is_protected(f)]

        for rel_path in stale_files:
            full_path = self.fs.root_path / rel_path
            try:
                content = full_path.read_text(encoding='utf-8', errors='ignore')
            except:
                continue
            if not content.strip():
                continue
            category = self.classify_content(rel_path, content)
            existing = all_content.get(category, "")
            all_content[category] = (existing + "\n" + content) if existing else content

        results = []
        for category, content in all_content.items():
            if content.strip():
                result = self.write_knowledge(category, content)
                results.append(f"{category}: {result}")

        for rel_path in stale_files:
            try:
                full_path = self.fs.root_path / rel_path
                if full_path.exists() and not self._is_protected(rel_path):
                    full_path.unlink()
                    results.append(f"Removed {rel_path}")
            except:
                pass

        return "; ".join(results) if results else "Nothing to consolidate."

    def cleanup_empty_files(self):
        removed = 0
        for rel_path in self._walk_files():
            if self._is_protected(rel_path):
                continue
            full_path = self.fs.root_path / rel_path
            try:
                if full_path.stat().st_size == 0:
                    full_path.unlink()
                    removed += 1
                else:
                    content = full_path.read_text(encoding='utf-8', errors='ignore')
                    if not content.strip():
                        full_path.unlink()
                        removed += 1
            except:
                pass
        return removed
