from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from .models import UserProfile


class UserProfileTests(TestCase):
    def setUp(self) -> None:
        self.UserModel = get_user_model()

    def test_profile_created_for_new_user(self) -> None:
        user = self.UserModel.objects.create_user(
            username="auditor",
            password="StrongPass123",
            first_name="Иван",
            last_name="Иванов",
        )

        self.assertTrue(hasattr(user, "profile"))
        profile = user.profile
        self.assertEqual(profile.role, UserProfile.Roles.AUDITOR)
        self.assertEqual(profile.full_name, "Иван Иванов")

    def test_mark_password_changed_updates_timestamp(self) -> None:
        user = self.UserModel.objects.create_user(username="tester", password="StrongPass123")
        profile = user.profile

        self.assertIsNone(profile.password_changed_at)
        profile.mark_password_changed()
        self.assertIsNotNone(profile.password_changed_at)
        self.assertLessEqual(profile.password_changed_at, timezone.now())

    def test_role_helpers(self) -> None:
        user = self.UserModel.objects.create_user(username="admin", password="StrongPass123")
        profile = user.profile

        self.assertTrue(profile.is_auditor)
        self.assertFalse(profile.is_admin)

        profile.role = UserProfile.Roles.ADMIN
        profile.save(update_fields=["role"])

        self.assertTrue(profile.is_admin)
        self.assertFalse(profile.is_auditor)
