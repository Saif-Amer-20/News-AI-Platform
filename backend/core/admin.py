from __future__ import annotations


class ActorStampedAdminMixin:
    def save_model(self, request, obj, form, change):
        if hasattr(obj, "updated_by"):
            obj.updated_by = request.user
        if hasattr(obj, "created_by") and not getattr(obj, "created_by_id", None):
            obj.created_by = request.user
        if hasattr(obj, "owner") and not getattr(obj, "owner_id", None):
            obj.owner = request.user
        super().save_model(request, obj, form, change)

