from django.urls import path
from . import views

urlpatterns = [
    path('', views.chat_interface, name='chat_interface'),
    path('chat/api/', views.chat_api, name='chat_api'),
    path('chat/delete/<str:session_id>/', views.delete_chat, name='delete_chat'),
    path('chat/delete-all/', views.delete_all_chats, name='delete_all_chats'),
    path('system/purge/', views.system_purge, name='system_purge'),
    path('api/history/', views.list_chats, name='list_chats'),
    path('api/history/<int:session_id>/', views.load_chat, name='load_chat'),
    path('api/new-chat/', views.new_chat, name='new_chat'),
    path('chat/debug/', views.chat_debug, name='chat_debug_no_id'),
    path('chat/debug/<int:session_id>/', views.chat_debug, name='chat_debug'),
    path('system/trigger-scribe/', views.trigger_scribe, name='trigger_scribe'),
]