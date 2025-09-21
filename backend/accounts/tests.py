from __future__ import annotations

from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.core import mail
from django.http import HttpRequest
from django.test import TestCase
from django.test.client import RequestFactory
from django.urls import reverse
from django.utils import timezone

from . import admin as accounts_admin
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


class LogoutIntegrationTests(TestCase):
    def setUp(self) -> None:
        self.UserModel = get_user_model()
        self.username = "operator"
        self.password = "SecurePass123!"
        self.user = self.UserModel.objects.create_user(
            username=self.username,
            password=self.password,
        )
        self.user.profile.mark_password_changed()

    def test_post_logout_ends_session_and_redirects_to_login(self) -> None:
        login_response = self.client.post(
            reverse("accounts:login"),
            {"username": self.username, "password": self.password},
        )
        self.assertRedirects(
            login_response,
            reverse("accounts:dashboard"),
            fetch_redirect_response=False,
        )

        response = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(
            response,
            reverse("accounts:login"),
            fetch_redirect_response=False,
        )
        self.assertNotIn("_auth_user_id", self.client.session)

        dashboard_response = self.client.get(reverse("accounts:dashboard"))
        self.assertRedirects(
            dashboard_response,
            f"{reverse('accounts:login')}?next={reverse('accounts:dashboard')}",
        )


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

    def test_user_with_unknown_role_gets_no_results(self) -> None:
        outsider = self.UserModel.objects.create_user(
            username="outsider",
            password="StrongPass123",
        )
        outsider.profile.role = "MANAGER"
        outsider.profile.save(update_fields=["role"])

        queryset = UserProfile.objects.order_by("pk")
        filtered = restrict_queryset_for_user(queryset, outsider)
        self.assertEqual(list(filtered), [])


class UserNotificationTests(TestCase):
    def setUp(self) -> None:
        self.UserModel = get_user_model()

    def test_email_sent_for_new_user_with_address(self) -> None:
        mail.outbox.clear()

        self.UserModel.objects.create_user(
            username="with-email",
            email="user@example.com",
            password="StrongPass123!",
        )

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertIn("учётная запись", message.subject.lower())
        self.assertIn("with-email", message.body)

    def test_email_not_sent_when_address_missing(self) -> None:
        mail.outbox.clear()

        self.UserModel.objects.create_user(
            username="without-email",
            password="StrongPass123!",
        )

        self.assertEqual(len(mail.outbox), 0)


class UserAdminActionsTests(TestCase):
    def setUp(self) -> None:
        self.UserModel = get_user_model()
        self.admin_user = self.UserModel.objects.create_superuser(
            username="supervisor",
            email="admin@example.com",
            password="AdminPass123!",
        )
        self.user_admin = accounts_admin.UserAdmin(self.UserModel, AdminSite())
        self.factory = RequestFactory()

    def _build_request(self) -> HttpRequest:
        request = self.factory.post("/admin/accounts/user/")
        request.user = self.admin_user
        session_middleware = SessionMiddleware(lambda req: None)
        session_middleware.process_request(request)
        request.session.save()
        setattr(request, "_messages", FallbackStorage(request))
        return request

    def test_activate_users_action(self) -> None:
        target = self.UserModel.objects.create_user(
            username="inactive",
            password="StrongPass123!",
            is_active=False,
        )

        request = self._build_request()
        queryset = self.UserModel.objects.filter(pk=target.pk)

        self.user_admin.activate_users(request, queryset)

        target.refresh_from_db()
        self.assertTrue(target.is_active)
        messages = list(get_messages(request))
        self.assertTrue(any("Активировано" in message.message for message in messages))

    def test_deactivate_users_action(self) -> None:
        target = self.UserModel.objects.create_user(
            username="active",
            password="StrongPass123!",
            is_active=True,
        )

        request = self._build_request()
        queryset = self.UserModel.objects.filter(pk=target.pk)

        self.user_admin.deactivate_users(request, queryset)

        target.refresh_from_db()
        self.assertFalse(target.is_active)
        messages = list(get_messages(request))
        self.assertTrue(any("Деактивировано" in message.message for message in messages))

    @patch("accounts.admin.generate_temporary_password", return_value="TempPass123!")
    def test_reset_passwords_action(self, _mocked_generator) -> None:
        target = self.UserModel.objects.create_user(
            username="reset", password="StrongPass123!"
        )
        profile = target.profile
        profile.mark_password_changed()
        self.assertIsNotNone(profile.password_changed_at)

        request = self._build_request()
        queryset = self.UserModel.objects.filter(pk=target.pk)

        self.user_admin.reset_passwords(request, queryset)

        target.refresh_from_db()
        profile.refresh_from_db()

        self.assertTrue(target.check_password("TempPass123!"))
        self.assertIsNone(profile.password_changed_at)
        messages = list(get_messages(request))
        self.assertTrue(any("TempPass123!" in message.message for message in messages))


class UserAdminInlineTests(TestCase):
    def setUp(self) -> None:
        self.UserModel = get_user_model()
        self.admin_user = self.UserModel.objects.create_superuser(
            username="main-admin",
            email="admin@example.com",
            password="AdminPass123!",
        )
        self.admin_user.profile.mark_password_changed()

    def test_create_user_with_profile_inline_does_not_duplicate(self) -> None:
        self.client.force_login(self.admin_user)

        response = self.client.post(
            reverse("admin:auth_user_add"),
            data={
                "username": "denis-bulgin",
                "password1": "TempPass123!",
                "password2": "TempPass123!",
                "profile-TOTAL_FORMS": "1",
                "profile-INITIAL_FORMS": "0",
                "profile-MIN_NUM_FORMS": "0",
                "profile-MAX_NUM_FORMS": "1",
                "profile-0-id": "",
                "profile-0-full_name": "Булгин Денис",
                "profile-0-role": UserProfile.Roles.ADMIN,
                "profile-0-phone": "+7 999 111-22-33",
                "profile-0-employee_id": "ADM-001",
                "profile-0-password_changed_at": "",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        created_user = self.UserModel.objects.get(username="denis-bulgin")

        profiles = UserProfile.objects.filter(user=created_user)
        self.assertEqual(profiles.count(), 1)

        profile = profiles.get()
        self.assertEqual(profile.full_name, "Булгин Денис")
        self.assertEqual(profile.role, UserProfile.Roles.ADMIN)
        self.assertEqual(profile.phone, "+7 999 111-22-33")
        self.assertEqual(profile.employee_id, "ADM-001")


class AdminAccessRestrictionsTests(TestCase):
    """Ensure Django Admin разделён между техническими и прикладными ролями."""

    def setUp(self) -> None:
        self.UserModel = get_user_model()
        self.superuser = self.UserModel.objects.create_superuser(
            username="operator",
            email="operator@example.com",
            password="OperatorPass123!",
        )
        self.superuser.profile.mark_password_changed()
        self.superuser.profile.save(update_fields=["password_changed_at"])
        self.staff_admin = self.UserModel.objects.create_user(
            username="manager",
            password="StrongPass123!",
            is_staff=True,
        )
        self.staff_admin.profile.role = UserProfile.Roles.ADMIN
        self.staff_admin.profile.mark_password_changed()
        self.staff_admin.profile.save(update_fields=["role", "password_changed_at"])

    def test_staff_admin_cannot_access_hidden_sections(self) -> None:
        self.client.force_login(self.staff_admin)

        response = self.client.get(reverse("admin:catalog_building_changelist"))
        self.assertEqual(response.status_code, 403)

        response = self.client.get(reverse("admin:audits_audit_changelist"))
        self.assertEqual(response.status_code, 403)

    def test_staff_admin_does_not_see_catalog_or_audits_apps(self) -> None:
        self.client.force_login(self.staff_admin)

        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 200)

        app_list = response.context.get("app_list", [])
        app_labels = {app["app_label"].lower() for app in app_list}
        self.assertNotIn("catalog", app_labels)
        self.assertNotIn("audits", app_labels)

    def test_superuser_retains_full_admin_access(self) -> None:
        self.client.force_login(self.superuser)

        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 200)

        app_list = response.context.get("app_list", [])
        app_labels = {app["app_label"].lower() for app in app_list}
        self.assertIn("catalog", app_labels)
        self.assertIn("audits", app_labels)


class NavigationRenderingTests(TestCase):
    """Проверяем, что навигация кабинета соответствует роли пользователя."""

    def setUp(self) -> None:
        self.UserModel = get_user_model()

    def test_admin_navigation_hides_django_admin_link(self) -> None:
        user = self.UserModel.objects.create_user(
            username="cab-admin",
            password="StrongPass123!",
            email="admin@example.com",
        )
        profile = user.profile
        profile.role = UserProfile.Roles.ADMIN
        profile.mark_password_changed()
        profile.save(update_fields=["role", "password_changed_at"])

        logged_in = self.client.login(username="cab-admin", password="StrongPass123!")
        self.assertTrue(logged_in)

        response = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(response, "Кабинет администратора")
        self.assertContains(response, reverse("checklists:template-list"))
        self.assertNotContains(response, reverse("admin:index"))

    def test_auditor_navigation_contains_only_auditor_links(self) -> None:
        user = self.UserModel.objects.create_user(
            username="cab-auditor",
            password="StrongPass123!",
        )
        user.profile.mark_password_changed()
        user.profile.save(update_fields=["password_changed_at"])

        logged_in = self.client.login(username="cab-auditor", password="StrongPass123!")
        self.assertTrue(logged_in)

        response = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(response, "Кабинет аудитора")
        self.assertContains(response, reverse("audits:audit-list"))
        self.assertContains(response, reverse("checklists:template-list"))
        self.assertNotContains(response, reverse("admin:index"))

    def test_superuser_sees_django_admin_link(self) -> None:
        user = self.UserModel.objects.create_superuser(
            username="tech-operator",
            email="tech@example.com",
            password="AdminPass123!",
        )
        profile = user.profile
        profile.role = UserProfile.Roles.ADMIN
        profile.mark_password_changed()
        profile.save(update_fields=["role", "password_changed_at"])

        logged_in = self.client.login(username="tech-operator", password="AdminPass123!")
        self.assertTrue(logged_in)

        response = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(response, reverse("admin:index"))
        self.assertContains(response, "Django Admin")
