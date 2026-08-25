from datetime import datetime
from ..models import VersionSnapshot
from .audit_service import AuditService


class VersionService:
    def __init__(self):
        self.audit = AuditService()

    def create_snapshot(self, content_type, content, content_id="", summary="", tags=None):
        snapshot = VersionSnapshot.objects.create(
            content_type=content_type,
            content_id=content_id,
            content=content,
            summary=str(summary)[:500],
            tags=tags or [],
        )
        self.audit.log(
            action_type="snapshot_created",
            target_model="VersionSnapshot",
            target_id=snapshot.id,
            summary=f"Snapshot {content_type}/{content_id}: {summary[:100]}",
            new_state={"content_type": content_type, "content_id": content_id},
        )
        return snapshot

    def get_snapshots(self, content_type, content_id="", limit=20):
        filters = {"content_type": content_type}
        if content_id:
            filters["content_id"] = content_id
        return VersionSnapshot.objects.filter(**filters).order_by('-created_at')[:limit]

    def get_snapshot(self, snapshot_id):
        try:
            return VersionSnapshot.objects.get(id=snapshot_id)
        except VersionSnapshot.DoesNotExist:
            return None

    def restore_snapshot(self, snapshot_id):
        snapshot = self.get_snapshot(snapshot_id)
        if not snapshot:
            return None, "Snapshot not found"
        content_type = snapshot.content_type
        from ..services.filesystem import FileSystemService
        fs = FileSystemService()
        path_map = {
            "personality": "identity/personality.md",
            "user_profile": "user/profile.md",
        }
        file_path = path_map.get(content_type)
        if not file_path and content_type == "project_doc":
            file_path = f"knowledge/projects/{snapshot.content_id}"
        if not file_path:
            return None, f"No restore target for {content_type}"
        fs.write_file(file_path, snapshot.content)
        self.audit.log(
            action_type="snapshot_restored",
            target_model="VersionSnapshot",
            target_id=snapshot.id,
            summary=f"Restored {content_type}/{snapshot.content_id} from snapshot",
            previous_state={"restored_from": snapshot_id},
            new_state={"content_type": content_type, "content_id": snapshot.content_id},
        )
        return snapshot, "restored"

    def get_diff(self, snapshot_id_a, snapshot_id_b=None):
        snap_a = self.get_snapshot(snapshot_id_a)
        if not snap_a:
            return "Snapshot A not found"
        if snapshot_id_b:
            snap_b = self.get_snapshot(snapshot_id_b)
            if not snap_b:
                return "Snapshot B not found"
            content_b = snap_b.content
        else:
            content_b = self._get_current_content(snap_a.content_type, snap_a.content_id)
        return self._compute_diff(snap_a.content, content_b)

    def _get_current_content(self, content_type, content_id):
        from ..services.filesystem import FileSystemService
        fs = FileSystemService()
        path_map = {
            "personality": "identity/personality.md",
            "user_profile": "user/profile.md",
        }
        file_path = path_map.get(content_type)
        if not file_path and content_type == "project_doc":
            file_path = f"knowledge/projects/{content_id}"
        if not file_path:
            return ""
        return fs.read_file(file_path) or ""

    def _compute_diff(self, old_text, new_text):
        old_lines = old_text.splitlines(keepends=True)
        new_lines = new_text.splitlines(keepends=True)
        import difflib
        diff = list(difflib.unified_diff(old_lines, new_lines, n=3))
        return "".join(diff)
