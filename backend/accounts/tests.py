from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import UserProfile
from .permissions import restrict_queryset_for_user


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


class AuthenticationFlowTests(TestCase):
    def setUp(self) -> None:
        self.UserModel = get_user_model()
        self.username = "auditor"
        self.password = "TempPass123!"
        self.user = self.UserModel.objects.create_user(
            username=self.username,
            password=self.password,
            first_name="Анна",
            last_name="Петрова",
        )

    def test_login_redirects_to_force_password_change(self) -> None:
        response = self.client.post(
            reverse("accounts:login"),
            {"username": self.username, "password": self.password},
        )

        self.assertRedirects(
            response,
            reverse("accounts:force-password-change"),
            fetch_redirect_response=True,
        )

    def test_force_password_change_updates_timestamp(self) -> None:
        logged_in = self.client.login(username=self.username, password=self.password)
        self.assertTrue(logged_in)

        response = self.client.post(
            reverse("accounts:force-password-change"),
            {
                "old_password": self.password,
                "new_password1": "NewPass321!",
                "new_password2": "NewPass321!",
            },
        )
        self.assertRedirects(
            response,
            reverse("accounts:password-change-done"),
            fetch_redirect_response=True,
        )

        profile = self.user.profile
        profile.refresh_from_db()
        self.assertIsNotNone(profile.password_changed_at)

    def test_password_change_signal_resets_marker_on_admin_reset(self) -> None:
        profile = self.user.profile
        profile.mark_password_changed()
        self.assertIsNotNone(profile.password_changed_at)

        self.user.set_password("AnotherPass456!")
        self.user.save()

        profile.refresh_from_db()
        self.assertIsNone(profile.password_changed_at)


class QuerysetRestrictionTests(TestCase):
    def setUp(self) -> None:
        self.UserModel = get_user_model()
        self.admin = self.UserModel.objects.create_user(
            username="admin",
            password="StrongPass123",
        )
        self.admin.profile.role = UserProfile.Roles.ADMIN
        self.admin.profile.save(update_fields=["role"])

        self.auditor = self.UserModel.objects.create_user(
            username="auditor",
            password="StrongPass123",
        )

    def test_admin_sees_all_profiles(self) -> None:
        queryset = UserProfile.objects.order_by("pk")
        filtered = restrict_queryset_for_user(queryset, self.admin)
        self.assertEqual(list(filtered), list(queryset))

    def test_auditor_sees_only_own_profile(self) -> None:
        queryset = UserProfile.objects.order_by("pk")
        filtered = restrict_queryset_for_user(queryset, self.auditor)
        self.assertEqual(list(filtered), [self.auditor.profile])
