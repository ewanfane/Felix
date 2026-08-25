from ..models import UserFact
from .audit_service import AuditService


class UserFactService:
    def __init__(self):
        self.audit = AuditService()

    def add_fact(self, category, fact_key, fact_value, source="", confidence=1.0):
        existing = UserFact.objects.filter(
            category=category,
            fact_key__iexact=fact_key,
            is_active=True,
        ).first()
        if existing:
            if existing.fact_value == fact_value:
                return existing
            old_value = existing.fact_value
            existing.fact_value = fact_value
            existing.confidence = confidence
            if source:
                existing.source = source
            existing.save()
            self.audit.log(
                action_type="fact_updated",
                target_model="UserFact",
                target_id=existing.id,
                summary=f"Updated fact {category}:{fact_key}",
                previous_state={"fact_value": old_value},
                new_state={"fact_value": fact_value},
            )
            return existing

        fact = UserFact.objects.create(
            category=category,
            fact_key=fact_key,
            fact_value=fact_value,
            source=source,
            confidence=confidence,
        )
        self.audit.log(
            action_type="fact_created",
            target_model="UserFact",
            target_id=fact.id,
            summary=f"Created fact {category}:{fact_key}",
            new_state={"category": category, "fact_key": fact_key, "fact_value": fact_value},
        )
        return fact

    def get_facts(self, category=None, is_active=True, limit=50):
        filters = {"is_active": is_active}
        if category:
            filters["category"] = category
        return UserFact.objects.filter(**filters).order_by('-updated_at')[:limit]

    def get_fact_by_key(self, fact_key, category=None):
        filters = {"fact_key__iexact": fact_key, "is_active": True}
        if category:
            filters["category"] = category
        return UserFact.objects.filter(**filters).first()

    def deactivate_fact(self, fact_id):
        try:
            fact = UserFact.objects.get(id=fact_id)
            fact.is_active = False
            fact.save()
            self.audit.log(
                action_type="fact_deactivated",
                target_model="UserFact",
                target_id=fact.id,
                summary=f"Deactivated fact {fact.category}:{fact.fact_key}",
            )
            return True
        except UserFact.DoesNotExist:
            return False

    def extract_facts_from_insight(self, insight_data):
        if not insight_data or insight_data.get("skip"):
            return []
        facts_text = insight_data.get("facts", "").strip()
        if not facts_text:
            return []
        created = []
        for line in facts_text.split("\n"):
            line = line.strip()
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip().lower()
            value = value.strip()
            if not value:
                continue
            category_map = {
                "name": "identity",
                "communication_style": "preference",
                "expertise": "expertise",
                "goals": "goal",
                "preferences": "preference",
                "role_expectations": "preference",
            }
            category = category_map.get(key, "other")
            source = f"insight:{key}"
            fact = self.add_fact(category, key, value, source=source, confidence=0.7)
            created.append(fact)
        return created
