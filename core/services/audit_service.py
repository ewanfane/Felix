import json
from datetime import datetime
from ..models import AuditLog


class AuditService:
    def log(self, action_type, target_model, previous_state=None, new_state=None, summary="", target_id="", approved=True):
        AuditLog.objects.create(
            action_type=action_type,
            target_model=target_model,
            target_id=str(target_id) if target_id else "",
            previous_state=previous_state or {},
            new_state=new_state or {},
            summary=str(summary)[:500],
            approved=approved,
        )

    def get_recent(self, limit=50):
        return AuditLog.objects.order_by('-created_at')[:limit]

    def get_by_model(self, target_model, limit=20):
        return AuditLog.objects.filter(target_model=target_model).order_by('-created_at')[:limit]
