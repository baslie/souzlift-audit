"""Views for catalog management in the user-facing interface."""
from __future__ import annotations

from typing import Iterable
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Max, Q, QuerySet
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import CreateView, DeleteView, ListView, TemplateView, UpdateView

from accounts.models import UserProfile
from accounts.permissions import AdminRequiredMixin, RoleRequiredMixin

from audits.services import build_checklist_structure

from .forms import (
    BuildingForm,
    ChecklistCategoryForm,
    ChecklistQuestionForm,
    ChecklistSectionForm,
    ElevatorForm,
    ScoreOptionForm,
)
from .models import (
    Building,
    ChecklistCategory,
    ChecklistQuestion,
    ChecklistSection,
    Elevator,
    ReviewStatus,
    ScoreOption,
)


class VisibleForUserQuerysetMixin(RoleRequiredMixin):
    """Базовый mixin, ограничивающий queryset доступными пользователю записями."""

    model: type[Building | Elevator]
    allowed_roles = (UserProfile.Roles.ADMIN, UserProfile.Roles.AUDITOR)

    def prepare_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset

    def get_queryset(self) -> QuerySet:  # type: ignore[override]
        queryset = self.model.objects.visible_for_user(self.request.user)
        return self.prepare_queryset(queryset)


class BaseCatalogListView(VisibleForUserQuerysetMixin, ListView):
    """Общий список записей справочника с фильтрацией и поиском."""

    paginate_by = 20
    ordering = "-created_at"
    status_param = "status"
    search_param = "q"

    def get_status_choices(self) -> Iterable[tuple[str, str]]:
        return (
            ("", _("Все статусы")),
            (ReviewStatus.PENDING, _("Ожидают утверждения")),
            (ReviewStatus.APPROVED, _("Утверждённые")),
            (ReviewStatus.REJECTED, _("Отклонённые")),
            ("mine", _("Созданные мной")),
        )

    def get_status_filter(self) -> str:
        value = self.request.GET.get(self.status_param, "").strip()
        valid_values = {choice for choice, _ in self.get_status_choices() if choice}
        if value in valid_values or value == "mine":
            return value
        return ""

    def get_search_query(self) -> str:
        return self.request.GET.get(self.search_param, "").strip()

    def filter_queryset_by_status(self, queryset: QuerySet) -> QuerySet:
        status = self.get_status_filter()
        if not status:
            return queryset
        if status == "mine":
            return queryset.filter(created_by=self.request.user)
        return queryset.filter(review_status=status)

    def apply_search(self, queryset: QuerySet) -> QuerySet:
        query = self.get_search_query()
        if not query:
            return queryset
        return queryset.filter(self.get_search_filter(query))

    def get_search_filter(self, query: str) -> Q:
        raise NotImplementedError

    def get_queryset(self) -> QuerySet:  # type: ignore[override]
        queryset = super().get_queryset().order_by(self.ordering)
        queryset = self.filter_queryset_by_status(queryset)
        return self.apply_search(queryset)

    def get_preserved_querystring(self) -> str:
        params = self.request.GET.copy()
        params.pop("page", None)
        encoded = urlencode({k: v for k, v in params.items() if v})
        return encoded

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "status_choices": list(self.get_status_choices()),
                "selected_status": self.get_status_filter(),
                "search_query": self.get_search_query(),
                "search_param": self.search_param,
                "status_param": self.status_param,
                "querystring": self.get_preserved_querystring(),
                "can_moderate": bool(self.profile and self.profile.is_admin),
                "ReviewStatus": ReviewStatus,
            }
        )
        return context


class BuildingListView(BaseCatalogListView):
    """Список зданий с фильтрами и управлением модерацией."""

    model = Building
    template_name = "catalog/building_list.html"

    def prepare_queryset(self, queryset: QuerySet) -> QuerySet:  # type: ignore[override]
        return queryset.select_related("created_by__profile", "verified_by__profile")

    def get_search_filter(self, query: str) -> Q:
        return Q(address__icontains=query) | Q(entrance__icontains=query) | Q(notes__icontains=query)


class ElevatorListView(BaseCatalogListView):
    """Список лифтов с фильтрами и возможностью модерации."""

    model = Elevator
    template_name = "catalog/elevator_list.html"

    def prepare_queryset(self, queryset: QuerySet) -> QuerySet:  # type: ignore[override]
        return queryset.select_related("building", "created_by__profile", "verified_by__profile")

    def get_search_filter(self, query: str) -> Q:
        return (
            Q(identifier__icontains=query)
            | Q(description__icontains=query)
            | Q(building__address__icontains=query)
        )


class CatalogFormMixin(VisibleForUserQuerysetMixin):
    """Общие настройки для форм создания и редактирования каталога."""

    success_url: str | None = None
    success_message: str = ""

    def get_success_url(self) -> str:
        if self.success_url is not None:
            return str(self.success_url)
        raise NotImplementedError("success_url must be defined")

    def form_valid(self, form):  # type: ignore[override]
        if form.instance.created_by_id is None:
            form.instance.created_by = self.request.user
        response = super().form_valid(form)
        if self.success_message:
            messages.success(self.request, self.success_message)
        return response


class BuildingCreateView(CatalogFormMixin, CreateView):
    """Создание новой записи здания."""

    model = Building
    form_class = BuildingForm
    template_name = "catalog/building_form.html"
    success_url = reverse_lazy("catalog:building-list")
    success_message = _("Здание сохранено и отправлено на модерацию.")


class BuildingUpdateView(CatalogFormMixin, UpdateView):
    """Редактирование здания."""

    model = Building
    form_class = BuildingForm
    template_name = "catalog/building_form.html"
    success_url = reverse_lazy("catalog:building-list")
    success_message = _("Изменения сохранены. Запись будет отображаться после утверждения администратора.")

    def get_queryset(self) -> QuerySet:  # type: ignore[override]
        return Building.objects.select_related("created_by", "verified_by")

    def get_object(self, queryset: QuerySet | None = None):  # type: ignore[override]
        building = super().get_object(queryset)
        if not (self.profile and self.profile.is_admin):
            if building.created_by_id != self.request.user.id:
                raise PermissionDenied("Нельзя редактировать запись, созданную другим пользователем.")
            if building.review_status == ReviewStatus.APPROVED:
                raise PermissionDenied("Нельзя редактировать утверждённую запись.")
        return building

    def form_valid(self, form):  # type: ignore[override]
        is_admin = bool(self.profile and self.profile.is_admin)
        response = super().form_valid(form)
        if not is_admin and self.object.review_status != ReviewStatus.PENDING:
            self.object.send_to_review()
        return response


class ElevatorCreateView(CatalogFormMixin, CreateView):
    """Создание новой записи лифта."""

    model = Elevator
    form_class = ElevatorForm
    template_name = "catalog/elevator_form.html"
    success_url = reverse_lazy("catalog:elevator-list")
    success_message = _("Лифт сохранён и отправлен на модерацию.")

    def get_form_kwargs(self) -> dict[str, object]:
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs


class ElevatorUpdateView(CatalogFormMixin, UpdateView):
    """Редактирование лифта."""

    model = Elevator
    form_class = ElevatorForm
    template_name = "catalog/elevator_form.html"
    success_url = reverse_lazy("catalog:elevator-list")
    success_message = _("Изменения сохранены. Запись вернётся в очередь на проверку.")

    def get_queryset(self) -> QuerySet:  # type: ignore[override]
        return Elevator.objects.select_related("building", "created_by", "verified_by")

    def get_form_kwargs(self) -> dict[str, object]:
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_object(self, queryset: QuerySet | None = None):  # type: ignore[override]
        elevator = super().get_object(queryset)
        if not (self.profile and self.profile.is_admin):
            if elevator.created_by_id != self.request.user.id:
                raise PermissionDenied("Нельзя редактировать лифт другого пользователя.")
            if elevator.review_status == ReviewStatus.APPROVED:
                raise PermissionDenied("Нельзя редактировать утверждённую запись.")
        return elevator

    def form_valid(self, form):  # type: ignore[override]
        is_admin = bool(self.profile and self.profile.is_admin)
        response = super().form_valid(form)
        if not is_admin and self.object.review_status != ReviewStatus.PENDING:
            self.object.send_to_review()
        return response


class BuildingModerationView(AdminRequiredMixin, View):
    """Обработчик действий модерации для зданий."""

    http_method_names = ["post"]

    def post(self, request: HttpRequest, pk: int, *args: object, **kwargs: object) -> HttpResponse:
        building = get_object_or_404(
            Building.objects.select_related("created_by", "verified_by"), pk=pk
        )
        action = request.POST.get("action")
        next_url = request.POST.get("next") or reverse_lazy("catalog:building-list")

        if action == "approve":
            building.approve(request.user)
            messages.success(request, _("Здание утверждено и доступно всем пользователям."))
        elif action == "reject":
            building.reject(request.user)
            messages.warning(request, _("Запись отклонена и скрыта из справочника."))
        elif action == "return":
            building.send_to_review()
            messages.info(request, _("Запись возвращена в очередь на проверку."))
        else:
            messages.error(request, _("Неизвестное действие модерации."))

        return redirect(next_url)


class ElevatorModerationView(AdminRequiredMixin, View):
    """Обработчик действий модерации для лифтов."""

    http_method_names = ["post"]

    def post(self, request: HttpRequest, pk: int, *args: object, **kwargs: object) -> HttpResponse:
        elevator = get_object_or_404(
            Elevator.objects.select_related("building", "created_by", "verified_by"), pk=pk
        )
        action = request.POST.get("action")
        next_url = request.POST.get("next") or reverse_lazy("catalog:elevator-list")

        if action == "approve":
            elevator.approve(request.user)
            messages.success(request, _("Лифт утверждён и доступен всем пользователям."))
        elif action == "reject":
            elevator.reject(request.user)
            messages.warning(request, _("Запись отклонена и скрыта из справочника."))
        elif action == "return":
            elevator.send_to_review()
            messages.info(request, _("Запись возвращена на повторную проверку."))
        else:
            messages.error(request, _("Неизвестное действие модерации."))

        return redirect(next_url)


def _assign_order_if_missing(instance: object, queryset: QuerySet) -> None:
    """Назначает элементу позицию в конце списка, если порядок не задан пользователем."""

    current_order = getattr(instance, "order", None)
    if current_order is None:
        return
    if current_order > 0:
        return

    max_order = queryset.aggregate(max_value=Max("order"))
    max_value = max_order.get("max_value")
    if max_value is None:
        setattr(instance, "order", 0)
    else:
        setattr(instance, "order", max_value + 1)


def _normalize_order(queryset: QuerySet) -> None:
    """Пересортировывает элементы так, чтобы порядок шёл последовательно от нуля."""

    for index, item in enumerate(queryset.order_by("order", "pk")):
        if getattr(item, "order", None) != index:
            item.order = index
            item.save(update_fields=["order"])


def _move_in_order(instance: object, siblings: QuerySet, direction: str) -> bool:
    """Меняет порядок элементов, перемещая текущий выше или ниже."""

    ordered = list(siblings.order_by("order", "pk"))
    try:
        current_index = next(index for index, item in enumerate(ordered) if item.pk == instance.pk)
    except StopIteration:  # pragma: no cover - защитный код
        return False

    if direction == "up":
        if current_index == 0:
            return False
        swap_index = current_index - 1
    elif direction == "down":
        if current_index >= len(ordered) - 1:
            return False
        swap_index = current_index + 1
    else:
        return False

    ordered[current_index], ordered[swap_index] = ordered[swap_index], ordered[current_index]

    with transaction.atomic():
        temp_offset = len(ordered)
        for position, item in enumerate(ordered):
            desired = position + temp_offset
            if item.order != desired:
                item.order = desired
                item.save(update_fields=["order"])
        _normalize_order(siblings)
    return True


class ChecklistAdminMixin(AdminRequiredMixin):
    """Общие настройки для представлений конструктора чек-листа."""

    success_url = reverse_lazy("catalog:checklist-overview")

    def get_return_url(self) -> str:
        next_url = self.request.POST.get("next") or self.request.GET.get("next")
        if next_url:
            return str(next_url)
        return str(self.success_url)

    def get_success_url(self) -> str:  # type: ignore[override]
        return self.get_return_url()

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context.setdefault("return_url", self.get_return_url())
        context.setdefault("checklist_overview_url", reverse("catalog:checklist-overview"))
        return context


class ChecklistFormViewMixin(ChecklistAdminMixin):
    """Общий шаблон для форм создания и редактирования элементов чек-листа."""

    template_name = "catalog/checklist/form.html"
    page_title_create: str = ""
    page_title_update: str = ""
    heading_create: str = ""
    heading_update: str = ""
    subheading_create: str = ""
    subheading_update: str = ""
    submit_label_create: str = _("Сохранить")
    submit_label_update: str = _("Сохранить изменения")

    def _is_update(self) -> bool:
        obj = getattr(self, "object", None)
        return bool(obj and getattr(obj, "pk", None))

    def get_page_title(self) -> str:
        if self._is_update() and self.page_title_update:
            return self.page_title_update
        return self.page_title_create

    def get_form_heading(self) -> str:
        if self._is_update() and self.heading_update:
            return self.heading_update
        return self.heading_create

    def get_form_subheading(self) -> str:
        if self._is_update() and self.subheading_update:
            return self.subheading_update
        return self.subheading_create

    def get_submit_label(self) -> str:
        return self.submit_label_update if self._is_update() else self.submit_label_create

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context.setdefault("page_title", self.get_page_title())
        context.setdefault("form_heading", self.get_form_heading())
        context.setdefault("form_subheading", self.get_form_subheading())
        context.setdefault("submit_label", self.get_submit_label())
        context.setdefault("cancel_url", context.get("return_url", self.get_return_url()))
        return context


class ChecklistDeleteView(ChecklistAdminMixin, DeleteView):
    """Базовое представление удаления элемента чек-листа."""

    template_name = "catalog/checklist/confirm_delete.html"
    page_title: str = ""
    heading: str = ""
    subheading_template: str = ""
    success_message: str = ""

    def get_page_title(self) -> str:
        return self.page_title

    def get_heading(self) -> str:
        return self.heading

    def get_subheading(self) -> str:
        if self.subheading_template and getattr(self, "object", None):
            return self.subheading_template.format(name=self.object)
        return ""

    def get_order_queryset(self, obj: object) -> QuerySet | None:
        return None

    def delete(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        self.object = self.get_object()
        siblings = self.get_order_queryset(self.object)
        response = super().delete(request, *args, **kwargs)
        if siblings is not None:
            _normalize_order(siblings)
        if self.success_message:
            messages.success(request, self.success_message)
        return response

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context.setdefault("page_title", self.get_page_title())
        context.setdefault("form_heading", self.get_heading())
        context.setdefault("form_subheading", self.get_subheading())
        context.setdefault("cancel_url", context.get("return_url", self.get_return_url()))
        context.setdefault("submit_label", _("Удалить"))
        return context


class ChecklistOverviewView(ChecklistAdminMixin, TemplateView):
    """Отображает дерево чек-листа и предпросмотр итоговой структуры."""

    template_name = "catalog/checklist/overview.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        categories = (
            ChecklistCategory.objects.all()
            .prefetch_related("sections__questions__score_options")
            .order_by("order", "name")
        )
        context["categories"] = categories
        context["category_count"] = categories.count()
        context["section_count"] = ChecklistSection.objects.count()
        context["question_count"] = ChecklistQuestion.objects.count()
        context["score_option_count"] = ScoreOption.objects.count()
        preview = build_checklist_structure()
        context["checklist_preview"] = preview
        generated = parse_datetime(preview.get("generated_at", ""))
        if generated is not None:
            context["preview_generated_at"] = generated
        return context


class ChecklistCategoryCreateView(ChecklistFormViewMixin, CreateView):
    """Создание новой категории чек-листа."""

    model = ChecklistCategory
    form_class = ChecklistCategoryForm
    page_title_create = _("Новая категория чек-листа · Союзлифт Аудит")
    heading_create = _("Новая категория чек-листа")
    subheading_create = _(
        "Категории объединяют секции по смысловым блокам. Изменения вступают в силу сразу после сохранения."
    )
    submit_label_create = _("Создать категорию")

    def form_valid(self, form: ChecklistCategoryForm):  # type: ignore[override]
        _assign_order_if_missing(form.instance, ChecklistCategory.objects.all())
        messages.success(self.request, _("Категория сохранена."))
        return super().form_valid(form)


class ChecklistCategoryUpdateView(ChecklistFormViewMixin, UpdateView):
    """Редактирование существующей категории."""

    model = ChecklistCategory
    form_class = ChecklistCategoryForm
    page_title_update = _("Редактирование категории чек-листа · Союзлифт Аудит")
    heading_update = _("Редактирование категории чек-листа")
    subheading_update = _("Используйте категории, чтобы структурировать проверку." )

    def form_valid(self, form: ChecklistCategoryForm):  # type: ignore[override]
        messages.success(self.request, _("Изменения категории сохранены."))
        return super().form_valid(form)


class ChecklistCategoryDeleteView(ChecklistDeleteView):
    """Удаление категории вместе с дочерними секциями."""

    model = ChecklistCategory
    page_title = _("Удаление категории чек-листа · Союзлифт Аудит")
    heading = _("Удалить категорию")
    subheading_template = _(
        "Категория «{name}» и все входящие в неё секции с вопросами будут удалены. Это действие нельзя отменить."
    )
    success_message = _("Категория удалена.")

    def get_order_queryset(self, obj: ChecklistCategory) -> QuerySet | None:  # type: ignore[override]
        return ChecklistCategory.objects.all()


class ChecklistSectionCreateView(ChecklistFormViewMixin, CreateView):
    """Добавление секции внутри выбранной категории."""

    model = ChecklistSection
    form_class = ChecklistSectionForm
    page_title_create = _("Новая секция чек-листа · Союзлифт Аудит")
    heading_create = _("Новая секция чек-листа")
    submit_label_create = _("Создать секцию")

    def dispatch(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        self.category = get_object_or_404(ChecklistCategory, pk=kwargs.get("category_pk"))
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self) -> dict[str, object]:
        initial = super().get_initial()
        initial.setdefault("category", self.category)
        return initial

    def get_form(self, form_class=None):  # type: ignore[override]
        form = super().get_form(form_class)
        form.fields["category"].initial = self.category
        form.fields["category"].disabled = True
        form.fields["category"].help_text = _("Секция будет добавлена в выбранную категорию.")
        return form

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context["category"] = self.category
        context["form_subheading"] = _(
            "Категория: «{name}». Секции помогают разбить анкету на логические блоки."
        ).format(name=self.category.name)
        return context

    def form_valid(self, form: ChecklistSectionForm):  # type: ignore[override]
        form.instance.category = self.category
        _assign_order_if_missing(form.instance, self.category.sections.all())
        messages.success(self.request, _("Секция сохранена."))
        return super().form_valid(form)


class ChecklistSectionUpdateView(ChecklistFormViewMixin, UpdateView):
    """Редактирование секции."""

    model = ChecklistSection
    form_class = ChecklistSectionForm
    page_title_update = _("Редактирование секции чек-листа · Союзлифт Аудит")
    heading_update = _("Редактирование секции")

    def get_form(self, form_class=None):  # type: ignore[override]
        form = super().get_form(form_class)
        form.fields["category"].disabled = True
        form.fields["category"].help_text = _("Чтобы переместить секцию, создайте новую и перенесите вопросы.")
        return form

    def form_valid(self, form: ChecklistSectionForm):  # type: ignore[override]
        messages.success(self.request, _("Изменения секции сохранены."))
        return super().form_valid(form)


class ChecklistSectionDeleteView(ChecklistDeleteView):
    """Удаление секции и связанных вопросов."""

    model = ChecklistSection
    page_title = _("Удаление секции чек-листа · Союзлифт Аудит")
    heading = _("Удалить секцию")
    subheading_template = _(
        "Секция «{name}» и все входящие вопросы будут удалены. Убедитесь, что это действие запланировано."
    )
    success_message = _("Секция удалена.")

    def get_order_queryset(self, obj: ChecklistSection) -> QuerySet | None:  # type: ignore[override]
        return ChecklistSection.objects.filter(category=obj.category)


class ChecklistQuestionCreateView(ChecklistFormViewMixin, CreateView):
    """Добавление вопроса в выбранную секцию."""

    model = ChecklistQuestion
    form_class = ChecklistQuestionForm
    page_title_create = _("Новый вопрос чек-листа · Союзлифт Аудит")
    heading_create = _("Новый вопрос")
    submit_label_create = _("Создать вопрос")

    def dispatch(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        self.section = get_object_or_404(ChecklistSection, pk=kwargs.get("section_pk"))
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self) -> dict[str, object]:
        initial = super().get_initial()
        initial.setdefault("section", self.section)
        return initial

    def get_form(self, form_class=None):  # type: ignore[override]
        form = super().get_form(form_class)
        form.fields["section"].initial = self.section
        form.fields["section"].disabled = True
        form.fields["section"].help_text = _("Вопрос будет отображаться в выбранной секции.")
        return form

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context["section"] = self.section
        context["form_subheading"] = _(
            "Секция: «{section}» (категория «{category}»). Настройте тип, баллы и подсказки."
        ).format(section=self.section.title, category=self.section.category.name)
        return context

    def form_valid(self, form: ChecklistQuestionForm):  # type: ignore[override]
        form.instance.section = self.section
        _assign_order_if_missing(form.instance, self.section.questions.all())
        messages.success(self.request, _("Вопрос сохранён."))
        return super().form_valid(form)


class ChecklistQuestionUpdateView(ChecklistFormViewMixin, UpdateView):
    """Редактирование вопроса чек-листа."""

    model = ChecklistQuestion
    form_class = ChecklistQuestionForm
    page_title_update = _("Редактирование вопроса чек-листа · Союзлифт Аудит")
    heading_update = _("Редактирование вопроса")

    def get_form(self, form_class=None):  # type: ignore[override]
        form = super().get_form(form_class)
        form.fields["section"].disabled = True
        form.fields["section"].help_text = _("Чтобы перенести вопрос, создайте новый в нужной секции.")
        return form

    def form_valid(self, form: ChecklistQuestionForm):  # type: ignore[override]
        messages.success(self.request, _("Изменения вопроса сохранены."))
        return super().form_valid(form)


class ChecklistQuestionDeleteView(ChecklistDeleteView):
    """Удаление вопроса с сохранением порядка остальных."""

    model = ChecklistQuestion
    page_title = _("Удаление вопроса чек-листа · Союзлифт Аудит")
    heading = _("Удалить вопрос")
    subheading_template = _(
        "Вопрос «{name}» будет удалён. Если нужно скрыть вопрос временно, отредактируйте структуру позже."
    )
    success_message = _("Вопрос удалён.")

    def get_order_queryset(self, obj: ChecklistQuestion) -> QuerySet | None:  # type: ignore[override]
        return ChecklistQuestion.objects.filter(section=obj.section)


class ScoreOptionCreateView(ChecklistFormViewMixin, CreateView):
    """Добавление варианта оценки для балльного вопроса."""

    model = ScoreOption
    form_class = ScoreOptionForm
    page_title_create = _("Новый вариант оценки · Союзлифт Аудит")
    heading_create = _("Новый вариант оценки")
    submit_label_create = _("Создать вариант")

    def dispatch(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        self.question = get_object_or_404(ChecklistQuestion, pk=kwargs.get("question_pk"))
        if self.question.type != ChecklistQuestion.QuestionType.SCORE:
            raise Http404("Score options are only available for score questions.")
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self) -> dict[str, object]:
        initial = super().get_initial()
        initial.setdefault("question", self.question)
        return initial

    def get_form(self, form_class=None):  # type: ignore[override]
        form = super().get_form(form_class)
        form.fields["question"].initial = self.question
        form.fields["question"].disabled = True
        form.fields["question"].help_text = _("Вариант будет доступен только в выбранном вопросе.")
        return form

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context["question"] = self.question
        context["form_subheading"] = _(
            "Вопрос: «{question}». Укажите описание и количество баллов."
        ).format(question=self.question.text)
        return context

    def form_valid(self, form: ScoreOptionForm):  # type: ignore[override]
        form.instance.question = self.question
        _assign_order_if_missing(form.instance, self.question.score_options.all())
        messages.success(self.request, _("Вариант оценки сохранён."))
        return super().form_valid(form)


class ScoreOptionUpdateView(ChecklistFormViewMixin, UpdateView):
    """Редактирование варианта оценки."""

    model = ScoreOption
    form_class = ScoreOptionForm
    page_title_update = _("Редактирование варианта оценки · Союзлифт Аудит")
    heading_update = _("Редактирование варианта оценки")

    def get_form(self, form_class=None):  # type: ignore[override]
        form = super().get_form(form_class)
        form.fields["question"].disabled = True
        form.fields["question"].help_text = _("Чтобы перенести вариант, создайте его заново в нужном вопросе.")
        return form

    def form_valid(self, form: ScoreOptionForm):  # type: ignore[override]
        messages.success(self.request, _("Изменения варианта сохранены."))
        return super().form_valid(form)


class ScoreOptionDeleteView(ChecklistDeleteView):
    """Удаление варианта оценки."""

    model = ScoreOption
    page_title = _("Удаление варианта оценки · Союзлифт Аудит")
    heading = _("Удалить вариант оценки")
    subheading_template = _(
        "Вариант «{name}» будет удалён. Убедитесь, что итоговый набор баллов остаётся корректным."
    )
    success_message = _("Вариант оценки удалён.")

    def get_order_queryset(self, obj: ScoreOption) -> QuerySet | None:  # type: ignore[override]
        return ScoreOption.objects.filter(question=obj.question)


class ChecklistReorderView(ChecklistAdminMixin, View):
    """Общий обработчик изменения порядка элементов."""

    http_method_names = ["post"]
    model: type[ChecklistCategory | ChecklistSection | ChecklistQuestion | ScoreOption]

    def get_siblings(self, instance):
        raise NotImplementedError

    def post(self, request: HttpRequest, pk: int, *args: object, **kwargs: object) -> HttpResponse:
        instance = get_object_or_404(self.model, pk=pk)
        direction = request.POST.get("direction", "").lower()
        next_url = self.get_return_url()

        if direction not in {"up", "down"}:
            messages.error(request, _("Неизвестное направление сортировки."))
            return redirect(next_url)

        siblings = self.get_siblings(instance)
        moved = _move_in_order(instance, siblings, direction)
        if moved:
            messages.success(request, _("Порядок обновлён."))
        else:
            messages.info(request, _("Элемент уже находится на границе списка."))
        return redirect(next_url)


class ChecklistCategoryReorderView(ChecklistReorderView):
    model = ChecklistCategory

    def get_siblings(self, instance: ChecklistCategory) -> QuerySet:
        return ChecklistCategory.objects.all()


class ChecklistSectionReorderView(ChecklistReorderView):
    model = ChecklistSection

    def get_siblings(self, instance: ChecklistSection) -> QuerySet:
        return ChecklistSection.objects.filter(category=instance.category)


class ChecklistQuestionReorderView(ChecklistReorderView):
    model = ChecklistQuestion

    def get_siblings(self, instance: ChecklistQuestion) -> QuerySet:
        return ChecklistQuestion.objects.filter(section=instance.section)


class ScoreOptionReorderView(ChecklistReorderView):
    model = ScoreOption

    def get_siblings(self, instance: ScoreOption) -> QuerySet:
        return ScoreOption.objects.filter(question=instance.question)

