from django.db import models
from pgvector.django import VectorField, HnswIndex
from django.db.models import JSONField
from django.contrib.postgres.indexes import GinIndex

class ChatSession(models.Model):
    """Groups messages into a conversation context."""
    started_at = models.DateTimeField(auto_now_add=True)
    title = models.CharField(max_length=200, default="New Conversation")

class ChatMessage(models.Model):
    """Raw history of the conversation (The 'Dataset of Truth')."""
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=20, choices=[('user', 'User'), ('assistant', 'Assistant')])
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Link to the memory chunks created from this message (for debugging)
    processed = models.BooleanField(default=False)

class MemoryChunk(models.Model):
    """The Semantic Brain (Vector Storage)."""
    # The actual text used for RAG
    content = models.TextField()
    consolidated = models.BooleanField(default=False)
    
    # 768 dimensions for EmbeddingGemma-300m
    embedding = VectorField(dimensions=768) 
    
    # HSCF Metadata: {"topic": "diet", "entities": [...]}
    metadata = JSONField(default=dict)

    # AI's reflection on the user's message
    reflection = models.TextField(blank=True, default="")
    
    # Link back to the raw message
    source_message = models.ForeignKey(ChatMessage, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            # HNSW index for fast semantic search
            HnswIndex(
                fields=['embedding'],
                name='vector_idx',
                opclasses=['vector_cosine_ops']
            ),
            # GIN index for fast JSON metadata filtering
            GinIndex(
                fields=['metadata'],
                name='metadata_idx',
                opclasses=['jsonb_path_ops']
            ),
        ]

class PromptLog(models.Model):
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE)
    full_prompt = models.TextField() # The exact string sent to the LLM
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Prompt for Session {self.session_id} at {self.created_at}"