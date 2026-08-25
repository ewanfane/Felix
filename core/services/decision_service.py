from ..models import DecisionRecord
from .audit_service import AuditService


class DecisionService:
    def __init__(self):
        self.audit = AuditService()

    def create_decision(self, project, title, rationale="", alternatives=None, context="", tags=None):
        decision = DecisionRecord.objects.create(
            project=project,
            title=title,
            rationale=rationale,
            alternatives=alternatives or [],
            context=context,
            tags=tags or [],
            status='accepted',
        )
        self.audit.log(
            action_type="decision_created",
            target_model="DecisionRecord",
            target_id=decision.id,
            summary=f"Decision: {project} - {title[:200]}",
            new_state={"project": project, "title": title, "rationale": rationale[:200]},
        )
        return decision

    def get_decisions(self, project=None, status=None, limit=50):
        filters = {}
        if project:
            filters["project"] = project
        if status:
            filters["status"] = status
        return DecisionRecord.objects.filter(**filters).order_by('-created_at')[:limit]

    def update_status(self, decision_id, new_status, superseded_by_id=None):
        try:
            decision = DecisionRecord.objects.get(id=decision_id)
            old_status = decision.status
            decision.status = new_status
            if superseded_by_id:
                try:
                    decision.superseded_by = DecisionRecord.objects.get(id=superseded_by_id)
                except DecisionRecord.DoesNotExist:
                    pass
            decision.save()
            self.audit.log(
                action_type="decision_status_changed",
                target_model="DecisionRecord",
                target_id=decision.id,
                summary=f"Decision {decision.title[:100]}: {old_status} → {new_status}",
                previous_state={"status": old_status},
                new_state={"status": new_status},
            )
            return True
        except DecisionRecord.DoesNotExist:
            return False
