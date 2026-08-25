from django.db import models
from pgvector.django import VectorField, HnswIndex
from django.db.models import JSONField
from django.contrib.postgres.indexes import GinIndex


class MemoryTier(models.TextChoices):
    ARCHIVAL = "archival", "Archival (vector search)"
    CORE = "core", "Core (always in context)"


class ChunkType(models.TextChoices):
    RAW = "raw", "Raw conversation chunk"
    DOC_POINTER = "doc_pointer", "Pointer to a durable document"


class LifecycleStage(models.TextChoices):
    INBOX = "inbox", "Inbox (recently created)"
    ACTIVE = "active", "Active (regularly referenced)"
    ARCHIVED = "archived", "Archived (historical reference)"
    STALE = "stale", "Stale (candidate for cleanup)"


class ChatSession(models.Model):
    started_at = models.DateTimeField(auto_now_add=True)
    title = models.CharField(max_length=200, default="New Conversation")


class ChatMessage(models.Model):
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=20, choices=[('user', 'User'), ('assistant', 'Assistant')])
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    processed = models.BooleanField(default=False)


class MemoryChunk(models.Model):
    content = models.TextField()
    consolidated = models.BooleanField(default=False)
    chunk_type = models.CharField(
        max_length=20,
        choices=ChunkType.choices,
        default=ChunkType.RAW,
    )
    memory_tier = models.CharField(
        max_length=20,
        choices=MemoryTier.choices,
        default=MemoryTier.ARCHIVAL,
    )
    lifecycle_stage = models.CharField(
        max_length=20,
        choices=LifecycleStage.choices,
        default=LifecycleStage.INBOX,
    )
    target_file = models.CharField(max_length=500, blank=True, default="")
    is_active = models.BooleanField(default=True)

    embedding = VectorField(dimensions=768)
    metadata = JSONField(default=dict)
    reflection = models.TextField(blank=True, default="")
    importance = models.FloatField(default=0.5, help_text="0.0 (trivial) to 1.0 (critical). Used for retrieval prioritization.")
    source_message = models.ForeignKey(ChatMessage, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            HnswIndex(
                fields=['embedding'],
                name='vector_idx',
                opclasses=['vector_cosine_ops']
            ),
            GinIndex(
                fields=['metadata'],
                name='metadata_idx',
                opclasses=['jsonb_path_ops']
            ),
            models.Index(fields=['chunk_type', 'is_active']),
            models.Index(fields=['memory_tier']),
            models.Index(fields=['lifecycle_stage']),
            models.Index(fields=['memory_tier', 'is_active', 'lifecycle_stage']),
            models.Index(fields=['importance']),
            models.Index(fields=['importance', 'memory_tier', 'is_active']),
        ]


class AuditLog(models.Model):
    action_type = models.CharField(max_length=50)
    target_model = models.CharField(max_length=100)
    target_id = models.CharField(max_length=50, blank=True)
    previous_state = JSONField(default=dict, blank=True)
    new_state = JSONField(default=dict, blank=True)
    summary = models.TextField(blank=True, default="")
    approved = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['action_type']),
            models.Index(fields=['target_model']),
        ]


class PendingChange(models.Model):
    CHANGE_TYPES = [
        ('personality_update', 'Personality Update'),
        ('profile_update', 'Profile Update'),
        ('project_doc_write', 'Project Document Write'),
        ('file_write', 'File Write'),
        ('fact_update', 'Fact Update'),
        ('core_memory_promote', 'Core Memory Promotion'),
        ('memory_lifecycle', 'Memory Lifecycle Change'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    change_type = models.CharField(max_length=50, choices=CHANGE_TYPES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    summary = models.TextField()
    detail = JSONField(default=dict)
    auto_approve = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
        ]


class PromptLog(models.Model):
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE)
    full_prompt = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Prompt for Session {self.session_id} at {self.created_at}"


class VersionSnapshot(models.Model):
    CONTENT_TYPES = [
        ('personality', 'Personality'),
        ('user_profile', 'User Profile'),
        ('project_doc', 'Project Document'),
        ('knowledge_file', 'Knowledge File'),
    ]

    content_type = models.CharField(max_length=50, choices=CONTENT_TYPES)
    content_id = models.CharField(max_length=200, blank=True, default="")
    content = models.TextField()
    summary = models.TextField(blank=True, default="")
    tags = JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['content_type', 'content_id']),
            models.Index(fields=['created_at']),
        ]


class UserFact(models.Model):
    FACT_CATEGORIES = [
        ('identity', 'Identity'),
        ('preference', 'Preference'),
        ('goal', 'Goal'),
        ('expertise', 'Expertise'),
        ('habit', 'Habit'),
        ('context', 'Context'),
        ('relationship', 'Relationship'),
        ('other', 'Other'),
    ]

    category = models.CharField(max_length=50, choices=FACT_CATEGORIES)
    fact_key = models.CharField(max_length=200)
    fact_value = models.TextField()
    source = models.CharField(max_length=500, blank=True, default="")
    confidence = models.FloatField(default=1.0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['category', 'is_active']),
            models.Index(fields=['fact_key']),
        ]


class DecisionRecord(models.Model):
    DECISION_STATUSES = [
        ('proposed', 'Proposed'),
        ('accepted', 'Accepted'),
        ('implemented', 'Implemented'),
        ('superseded', 'Superseded'),
        ('rejected', 'Rejected'),
    ]

    project = models.CharField(max_length=100)
    title = models.CharField(max_length=300)
    status = models.CharField(max_length=50, choices=DECISION_STATUSES, default='accepted')
    rationale = models.TextField(blank=True, default="")
    alternatives = JSONField(default=list, blank=True)
    context = models.TextField(blank=True, default="")
    tags = JSONField(default=list, blank=True)
    superseded_by = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['project', 'status']),
            models.Index(fields=['project', 'created_at']),
        ]


class ConceptLink(models.Model):
    LINK_TYPES = [
        ('related', 'Related'),
        ('depends_on', 'Depends On'),
        ('implements', 'Implements'),
        ('contradicts', 'Contradicts'),
        ('refines', 'Refines'),
        ('supersedes', 'Supersedes'),
        ('references', 'References'),
    ]

    source_chunk = models.ForeignKey(MemoryChunk, on_delete=models.CASCADE, related_name='outgoing_links')
    target_chunk = models.ForeignKey(MemoryChunk, on_delete=models.CASCADE, related_name='incoming_links')
    link_type = models.CharField(max_length=50, choices=LINK_TYPES, default='related')
    label = models.CharField(max_length=200, blank=True, default="")
    metadata = JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['link_type']),
            models.Index(fields=['source_chunk', 'link_type']),
        ]
