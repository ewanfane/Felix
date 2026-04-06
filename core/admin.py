from django.contrib import admin
from .models import ChatSession, ChatMessage, MemoryChunk, PromptLog 
# Register your models here.

admin.site.register(ChatSession)
admin.site.register(ChatMessage)
admin.site.register(MemoryChunk)
admin.site.register(PromptLog)
