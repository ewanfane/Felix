from datetime import datetime
from django.utils import timezone
from ..models import PendingChange
from .audit_service import AuditService


class PendingChangeService:
    def __init__(self):
        self.audit = AuditService()

    def create(self, change_type, summary, detail=None, auto_approve=True):
        change = PendingChange.objects.create(
            change_type=change_type,
            summary=str(summary)[:500],
            detail=detail or {},
            auto_approve=auto_approve,
            status='approved' if auto_approve else 'pending',
        )

        if auto_approve:
            self.audit.log(
                action_type=change_type,
                target_model="PendingChange",
                target_id=change.id,
                summary=f"Auto-approved: {summary}",
                new_state=detail,
                approved=True,
            )

        return change

    def get_recent(self, limit=20):
        return PendingChange.objects.all().order_by('-created_at')[:limit]

    def pending_count(self):
        return 0
