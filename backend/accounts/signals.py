"""Signal handlers for the accounts app."""
from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .emails import send_user_created_email
from .models import UserProfile

UserModel = get_user_model()


@receiver(post_save, sender=UserModel)
def ensure_user_profile(sender: type[UserModel], instance: UserModel, created: bool, **_: Any) -> None:
    """Создаёт профиль сразу после появления пользователя."""

    profile, profile_created = UserProfile.objects.get_or_create(user=instance)

    if created:
        if profile_created:
            full_name = instance.get_full_name()
            if full_name and not profile.full_name:
                profile.full_name = full_name
                profile.save(update_fields=["full_name"])
        send_user_created_email(instance)
    elif not profile.full_name:
        full_name = instance.get_full_name()
        if full_name:
            profile.full_name = full_name
            profile.save(update_fields=["full_name"])


@receiver(pre_save, sender=UserModel)
def reset_password_change_marker(sender: type[UserModel], instance: UserModel, **_: Any) -> None:
    """Сбрасывает отметку о смене пароля при его обновлении."""

    if not instance.pk:
        return

    previous_password = (
        sender.objects.filter(pk=instance.pk).values_list("password", flat=True).first()
    )
    if not previous_password or previous_password == instance.password:
        return

    profile, _ = UserProfile.objects.get_or_create(user=instance)
    if profile.password_changed_at is not None:
        profile.password_changed_at = None
        profile.save(update_fields=["password_changed_at"])
