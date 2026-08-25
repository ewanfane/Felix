from datetime import datetime, timedelta
from django.utils import timezone
from django.db import transaction
from ..models import MemoryChunk, ChatMessage, ChatSession, LifecycleStage
from ..services.filesystem import FileSystemService
from ..services.personality_service import PersonalityService
from ..services.user_model_service import UserModelService
from ..services.file_manager import FileManager
from ..services.scribe import ScribeService
from ..services.audit_service import AuditService


class MemoryMaintenanceService:
    def __init__(self):
        self.fs = FileSystemService()
        self.audit = AuditService()

    def run_full_maintenance(self):
        results = []
        results.append(self.prune_orphaned_chunks())
        results.append(self.cleanup_empty_sessions())
        results.append(self.compress_personality())
        results.append(self.compress_profile())
        results.append(self.run_scribe_consolidation())
        results.append(self.deactivate_stale_scratchpad())
        results.append(self.manage_lifecycle_stages())
        results.append(self.run_knowledge_maintenance())
        results.append(self.cleanup_file_system())
        return results

    def run_knowledge_maintenance(self):
        try:
            from .knowledge_maintenance_service import KnowledgeMaintenanceService
            km = KnowledgeMaintenanceService()
            sub_results = km.run_full_maintenance()
            self.audit.log(
                action_type="knowledge_maintenance",
                target_model="KnowledgeMaintenanceService",
                summary=f"Knowledge maintenance: {'; '.join(sub_results)}",
            )
            return f"Knowledge maintenance complete"
        except Exception as e:
            return f"Knowledge maintenance error: {e}"

    def manage_lifecycle_stages(self):
        results = []
        cutoff_active = timezone.now() - timedelta(hours=72)
        stale = MemoryChunk.objects.filter(
            lifecycle_stage=LifecycleStage.INBOX,
            is_active=True,
            created_at__lt=cutoff_active,
        )
        count = stale.count()
        if count:
            stale.update(lifecycle_stage=LifecycleStage.ACTIVE)
            results.append(f"Promoted {count} inbox chunks to active")

        cutoff_archive = timezone.now() - timedelta(days=14)
        archival = MemoryChunk.objects.filter(
            lifecycle_stage=LifecycleStage.ACTIVE,
            is_active=True,
            created_at__lt=cutoff_archive,
        )
        count2 = archival.count()
        if count2:
            archival.update(lifecycle_stage=LifecycleStage.ARCHIVED)
            results.append(f"Archived {count2} active chunks")

        return "; ".join(results) if results else "Lifecycle OK"

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
            self.audit.log(
                action_type="scribe_consolidation",
                target_model="ScribeService",
                summary=result,
            )
            return f"Scribe: {result}"
        except Exception as e:
            return f"Scribe error: {e}"

    def deactivate_stale_scratchpad(self, max_hours=48):
        cutoff = timezone.now() - timedelta(hours=max_hours)
        stale = MemoryChunk.objects.filter(
            chunk_type="raw",
            is_active=True,
            created_at__lt=cutoff,
        )
        count = stale.count()
        if count:
            stale.update(is_active=False)
        return f"Deactivated {count} stale scratchpad chunks older than {max_hours}h"

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
        MemoryChunk.objects.all().delete()
        return "Data folder and vector store wiped"

    def get_boarding_status(self):
        from ..services.core_memory_service import CoreMemoryService
        return CoreMemoryService().get_onboarding_status()
