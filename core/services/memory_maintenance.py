from datetime import datetime, timedelta
from django.utils import timezone
from django.db import transaction
from ..models import MemoryChunk, ChatMessage, ChatSession
from ..services.filesystem import FileSystemService
from ..services.personality_service import PersonalityService
from ..services.user_model_service import UserModelService
from ..services.file_manager import FileManager
from ..services.scribe import ScribeService


class MemoryMaintenanceService:
    def __init__(self):
        self.fs = FileSystemService()

    def run_full_maintenance(self):
        results = []
        results.append(self.prune_orphaned_chunks())
        results.append(self.prune_stale_chunks())
        results.append(self.cleanup_empty_sessions())
        results.append(self.compress_personality())
        results.append(self.compress_profile())
        results.append(self.run_scribe_consolidation())
        results.append(self.cleanup_file_system())
        return results

    def prune_orphaned_chunks(self):
        count = 0
        orphaned = MemoryChunk.objects.filter(
            consolidated=False,
            source_message__isnull=False
        ).exclude(
            source_message__in=ChatMessage.objects.all()
        )
        count = orphaned.count()
        if count:
            orphaned.delete()
        return f"Pruned {count} orphaned chunks"

    def prune_stale_chunks(self, max_days=30):
        cutoff = timezone.now() - timedelta(days=max_days)
        stale = MemoryChunk.objects.filter(
            consolidated=False,
            created_at__lt=cutoff
        )
        count = stale.count()
        if count:
            stale.delete()
        return f"Pruned {count} stale chunks older than {max_days}d"

    def cleanup_empty_sessions(self):
        empty_sessions = ChatSession.objects.filter(messages__isnull=True)
        count = empty_sessions.count()
        if count:
            empty_sessions.delete()
        return f"Cleaned {count} empty sessions"

    def compress_personality(self):
        ps = PersonalityService()
        compressed = ps.ensure_capacity()
        return "Personality compressed" if compressed else "Personality OK"

    def compress_profile(self):
        um = UserModelService()
        compressed = um.ensure_capacity()
        return "Profile compressed" if compressed else "Profile OK"

    def run_scribe_consolidation(self):
        try:
            scribe = ScribeService()
            result = scribe.run_full_consolidation(batch_size=30)
            return f"Scribe: {result}"
        except Exception as e:
            return f"Scribe error: {e}"

    def cleanup_file_system(self):
        try:
            fm = FileManager()
            empty = fm.cleanup_empty_files()
            consolidated = fm.consolidate_stale_files()
            return f"FS: removed {empty} empty, consolidated: {consolidated}"
        except Exception as e:
            return f"FS error: {e}"

    def wipe_data_folder(self):
        import shutil
        root = self.fs.root_path
        if root.exists():
            for item in root.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
        return "Data folder wiped"

    def get_boarding_status(self):
        ps = PersonalityService()
        um = UserModelService()
        return {
            "personality_evolved": ps.is_onboarding_complete(),
            "profile_filled": um.is_onboarding_complete(),
            "fill_placeholder_count": um.fill_placeholder_count(),
            "user_name": um.get_name(),
            "interaction_count": um.get_metadata().get("interaction_count", 0),
        }
