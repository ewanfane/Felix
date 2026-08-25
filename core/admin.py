from django.contrib import admin
from .models import ChatSession, ChatMessage, MemoryChunk, PromptLog, AuditLog, VersionSnapshot, UserFact, ConceptLink, DecisionRecord, PendingChange

admin.site.register(ChatSession)
admin.site.register(ChatMessage)
admin.site.register(MemoryChunk)
admin.site.register(PromptLog)
admin.site.register(AuditLog)
admin.site.register(VersionSnapshot)
admin.site.register(UserFact)
admin.site.register(ConceptLink)
admin.site.register(DecisionRecord)
admin.site.register(PendingChange)