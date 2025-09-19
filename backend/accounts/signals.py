"""Signal handlers for the accounts app."""
from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserProfile

UserModel = get_user_model()


@receiver(post_save, sender=UserModel)
def ensure_user_profile(sender: type[UserModel], instance: UserModel, created: bool, **_: Any) -> None:
    """Создаёт профиль сразу после появления пользователя."""

    profile, profile_created = UserProfile.objects.get_or_create(user=instance)

    if created and profile_created:
        full_name = instance.get_full_name()
        if full_name and not profile.full_name:
            profile.full_name = full_name
            profile.save(update_fields=["full_name"])
    elif not profile.full_name:
        full_name = instance.get_full_name()
        if full_name:
            profile.full_name = full_name
            profile.save(update_fields=["full_name"])
