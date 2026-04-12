"""URL routing for the full-text Search API (OpenSearch)."""
from django.urls import path

from .views_explore import search_articles, search_events

urlpatterns = [
    path("articles/", search_articles, name="search-articles"),
    path("events/", search_events, name="search-events"),
]
