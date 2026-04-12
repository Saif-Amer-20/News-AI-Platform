from __future__ import annotations

from django.db import models
from django.utils.text import slugify


def build_unique_slug(
    model_class: type[models.Model],
    value: str,
    *,
    instance: models.Model | None = None,
    slug_field: str = "slug",
    max_length: int = 120,
    fallback_prefix: str = "item",
) -> str:
    base_slug = slugify(value).strip("-") or fallback_prefix
    base_slug = base_slug[:max_length].strip("-") or fallback_prefix
    candidate = base_slug
    counter = 2

    queryset = model_class._default_manager.all()
    if instance is not None and instance.pk:
        queryset = queryset.exclude(pk=instance.pk)

    while queryset.filter(**{slug_field: candidate}).exists():
        suffix = f"-{counter}"
        trimmed = base_slug[: max_length - len(suffix)].strip("-") or fallback_prefix
        candidate = f"{trimmed}{suffix}"
        counter += 1

    return candidate

