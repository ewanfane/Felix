from django.db import migrations
from pgvector.django import VectorExtension # Requires the 'pgvector' python package

class Migration(migrations.Migration):
    dependencies = [
        # Should be empty or point to your first migration
    ]

    operations = [
        VectorExtension(), # This runs 'CREATE EXTENSION IF NOT EXISTS vector'
    ]