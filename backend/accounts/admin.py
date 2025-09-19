from __future__ import annotations

from django.contrib import admin
from django.contrib.admin.sites import NotRegistered
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "full_name",
        "role",
        "phone",
        "employee_id",
        "password_changed_at",
    )
    list_filter = ("role",)
    search_fields = (
        "user__username",
        "user__email",
        "full_name",
        "phone",
        "employee_id",
    )


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    extra = 0
    max_num = 1

    def get_extra(self, request, obj=None, **kwargs):
        return 1 if obj is None else 0


User = get_user_model()


try:
    admin.site.unregister(User)
except NotRegistered:
    pass


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    inlines = [UserProfileInline]
    list_display = DjangoUserAdmin.list_display + ("profile_role",)
    list_select_related = ("profile",)

    @admin.display(ordering="profile__role", description="Роль")
    def profile_role(self, obj: User) -> str:
        if hasattr(obj, "profile"):
            return obj.profile.get_role_display()
        return "—"
