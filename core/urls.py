from django.urls import path
from . import views

urlpatterns = [
    # Single continuous chat
    path('', views.chat_interface, name='chat_interface'),
    path('chat/api/', views.chat_api, name='chat_api'),
    path('chat/history/', views.chat_history, name='chat_history'),

    # System
    path('system/purge/', views.system_purge, name='system_purge'),
    path('system/status/', views.system_status, name='system_status'),
    path('system/maintenance/', views.trigger_maintenance, name='trigger_maintenance'),
    path('system/trigger-scribe/', views.trigger_scribe, name='trigger_scribe'),
    path('system/cleanup-files/', views.trigger_file_cleanup, name='trigger_file_cleanup'),

    # File Browser
    path('api/files/', views.list_knowledge_files, name='list_knowledge_files'),
    path('api/files/read/<path:file_path>/', views.read_knowledge_file, name='read_knowledge_file'),
    path('api/files/write/<path:file_path>/', views.write_knowledge_file, name='write_knowledge_file'),

    # Project Knowledge
    path('api/projects/', views.list_projects, name='list_projects'),
    path('api/projects/<str:project_name>/', views.project_detail, name='project_detail'),
    path('api/projects/<str:project_name>/<str:doc_type>/', views.project_doc, name='project_doc'),
    path('api/projects/search/', views.project_search, name='project_search'),

    # Version Snapshots
    path('api/snapshots/', views.list_snapshots, name='list_snapshots'),
    path('api/snapshots/<int:snapshot_id>/restore/', views.restore_snapshot, name='restore_snapshot'),
    path('api/snapshots/<int:snapshot_id>/diff/', views.diff_snapshot, name='diff_snapshot'),

    # Structured Facts
    path('api/facts/', views.list_facts, name='list_facts'),
    path('api/facts/create/', views.create_fact, name='create_fact'),
    path('api/facts/<int:fact_id>/delete/', views.delete_fact, name='delete_fact'),

    # Memory Lifecycle
    path('api/memory/<int:chunk_id>/stage/', views.set_lifecycle_stage, name='set_lifecycle_stage'),
    path('api/memory/stage/<str:stage>/', views.list_chunks_by_stage, name='list_chunks_by_stage'),

    # Core Memory Management
    path('api/memory/<int:chunk_id>/promote/', views.promote_to_core, name='promote_to_core'),
    path('api/memory/<int:chunk_id>/demote/', views.demote_from_core, name='demote_from_core'),
    path('api/core-memory/', views.core_memory_view, name='core_memory_view'),
    path('api/core-memory/list/', views.list_core_memory, name='list_core_memory'),

    # Concept Links
    path('api/links/create/', views.create_concept_link, name='create_concept_link'),
    path('api/links/<int:chunk_id>/', views.get_chunk_links, name='get_chunk_links'),
    path('api/links/<int:chunk_id>/related/', views.get_related_chunks, name='get_related_chunks'),

    # Knowledge Maintenance
    path('system/knowledge-maintenance/', views.trigger_knowledge_maintenance, name='trigger_knowledge_maintenance'),

    # Decision Records
    path('api/decisions/', views.list_decisions, name='list_decisions'),
    path('api/decisions/create/', views.create_decision, name='create_decision'),
    path('api/decisions/<int:decision_id>/status/', views.update_decision_status, name='update_decision_status'),

    # Audit
    path('api/audit-log/', views.audit_log_view, name='audit_log_view'),

    # Debug
    path('chat/debug/', views.chat_debug, name='chat_debug'),
    path('chat/debug/<int:session_id>/', views.chat_debug, name='chat_debug_with_id'),
]
