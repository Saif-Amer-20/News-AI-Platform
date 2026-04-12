"""
Custom AdminSite that groups models into logical operations sections
instead of the default per-app alphabetical listing.
"""
from __future__ import annotations

from django.contrib.admin import AdminSite


# Logical grouping: (group_label, [(app_label, model_name), ...])
ADMIN_GROUPS = [
    (
        "📡 Source Management",
        "Add and manage news sources — the starting point for all data ingestion.",
        [
            ("sources", "source"),
            ("sources", "sourcehealthevent"),
        ],
    ),
    (
        "🔄 Ingestion Pipeline",
        "Monitor fetch runs, errors, raw items, and parsed candidates. These are generated automatically.",
        [
            ("sources", "sourcefetchrun"),
            ("sources", "sourcefetcherror"),
            ("sources", "rawitem"),
            ("sources", "parsedarticlecandidate"),
        ],
    ),
    (
        "🧠 Intelligence Objects",
        "Articles, stories, events, and entities are produced by the pipeline. Do not create manually.",
        [
            ("sources", "article"),
            ("sources", "story"),
            ("sources", "event"),
            ("sources", "entity"),
            ("sources", "articleentity"),
        ],
    ),
    (
        "🎯 Topics & Watchlists",
        "Define monitoring topics and keyword rules to focus the intelligence pipeline.",
        [
            ("topics", "topic"),
            ("topics", "watchlist"),
            ("topics", "keywordrule"),
        ],
    ),
    (
        "🔔 Alerts",
        "Triggered alerts and their event history.",
        [
            ("alerts", "alert"),
            ("alerts", "alertevent"),
        ],
    ),
    (
        "📁 Case Management",
        "Investigation cases created by analysts.",
        [
            ("cases", "case"),
            ("cases", "casemember"),
            ("cases", "casenote"),
            ("cases", "casereference"),
        ],
    ),
    (
        "⚙️ Operations",
        "Audit logs, dead-letter queue, and system diagnostics.",
        [
            ("ops", "auditlog"),
            ("ops", "deadletteritem"),
        ],
    ),
    (
        "👤 Accounts & Auth",
        "User accounts, profiles, groups, and permissions.",
        [
            ("auth", "user"),
            ("auth", "group"),
            ("accounts", "userprofile"),
        ],
    ),
]


class NewsIntelAdminSite(AdminSite):
    site_header = "News Intelligence — Operations Console"
    site_title = "NewsIntel Ops"
    index_title = "Platform Administration"
    index_template = "admin/ops_index.html"

    def get_app_list(self, request, app_label=None):
        """
        Override to return model entries grouped by logical section
        instead of Django app.
        """
        # Build a flat lookup: (app_label, model_name) -> model_dict
        original = super().get_app_list(request, app_label=app_label)
        lookup: dict[tuple[str, str], dict] = {}
        for app in original:
            for model in app.get("models", []):
                key = (app["app_label"], model["object_name"].lower())
                lookup[key] = model

        grouped: list[dict] = []
        used_keys: set[tuple[str, str]] = set()

        for group_label, group_desc, members in ADMIN_GROUPS:
            models_in_group: list[dict] = []
            for app_lbl, model_name in members:
                key = (app_lbl, model_name)
                if key in lookup:
                    entry = dict(lookup[key])
                    models_in_group.append(entry)
                    used_keys.add(key)
            if models_in_group:
                grouped.append({
                    "name": group_label,
                    "app_label": members[0][0],  # for URL resolution
                    "app_url": "#",
                    "has_module_perms": True,
                    "models": models_in_group,
                    "description": group_desc,
                })

        # Append any remaining models not covered by ADMIN_GROUPS
        for app in original:
            remaining = []
            for model in app.get("models", []):
                key = (app["app_label"], model["object_name"].lower())
                if key not in used_keys:
                    remaining.append(model)
            if remaining:
                grouped.append({
                    "name": app["name"],
                    "app_label": app["app_label"],
                    "app_url": app.get("app_url", "#"),
                    "has_module_perms": True,
                    "models": remaining,
                })

        return grouped
