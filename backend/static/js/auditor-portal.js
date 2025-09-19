(function () {
  "use strict";

  const Offline = window.SouzliftOffline || null;
  const STORES = Offline
    ? Offline.STORES
    : {
        AUDITS: "offline_audits",
        BUILDINGS: "catalog_buildings",
        ELEVATORS: "catalog_elevators",
        OBJECT_FIELDS: "object_info_fields",
        META: "catalog_meta",
      };

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-auditor-portal]").forEach((element) => {
      new AuditorPortal(element);
    });
  });

  class AuditorPortal {
    constructor(root) {
      this.root = root;
      this.dialogId = root.dataset.dialogId || "offline-audit-dialog";
      this.dialog = document.getElementById(this.dialogId);
      this.form = this.dialog ? this.dialog.querySelector("[data-offline-form]") : null;
      this.flash = root.querySelector("[data-portal-flash]");
      this.offlineList = root.querySelector("#offline-audit-list");
      this.offlineEmpty = root.querySelector("#offline-audit-empty");
      this.offlineWarning = root.querySelector("#offline-support-warning");
      this.template = root.querySelector("#offline-audit-template");
      this.errorBox = this.form ? this.form.querySelector("[data-offline-error]") : null;
      this.openButtons = Array.from(root.querySelectorAll('[data-portal-action="open-dialog"]'));
      this.closeButtons = Array.from(root.querySelectorAll('[data-portal-action="close-dialog"]'));
      this.catalogUrl = root.dataset.catalogUrl || "";
      this.objectInfoUrl = root.dataset.objectInfoUrl || "";
      this.db = null;

      if (this.dialog && typeof this.dialog.showModal !== "function") {
        this.dialog.setAttribute("data-dialog-fallback", "true");
        this.dialog.style.display = "none";
      }

      this.bindEvents();
      this.initDatabase();
    }

    bindEvents() {
      this.openButtons.forEach((button) => {
        button.addEventListener("click", (event) => {
          event.preventDefault();
          this.openDialog();
        });
      });
      this.closeButtons.forEach((button) => {
        button.addEventListener("click", (event) => {
          event.preventDefault();
          this.closeDialog();
        });
      });
      if (this.dialog) {
        this.dialog.addEventListener("cancel", (event) => {
          event.preventDefault();
          this.closeDialog();
        });
      }
      if (this.form) {
        this.form.addEventListener("submit", (event) => {
          event.preventDefault();
          this.handleFormSubmit();
        });
      }
      window.addEventListener("beforeunload", () => {
        if (this.db) {
          this.db.close();
        }
      });
      window.addEventListener("online", () => {
        if (this.db) {
          this.refreshCatalogCache();
        }
      });
    }

    initDatabase() {
      if (!Offline || !Offline.isSupported()) {
        this.showOfflineWarning("Браузер не поддерживает IndexedDB. Черновики будут недоступны.");
        this.disableOfflineCreation();
        return;
      }
      Offline.openDatabase()
        .then((db) => {
          this.db = db;
          this.refreshOfflineList();
          this.refreshCatalogCache();
        })
        .catch((error) => {
          console.error("Failed to initialise offline database", error);
          this.showOfflineWarning("Не удалось инициализировать локальное хранилище. Черновики будут недоступны.");
          this.disableOfflineCreation();
        });
    }

    disableOfflineCreation() {
      this.openButtons.forEach((button) => {
        button.setAttribute("disabled", "disabled");
        button.classList.add("cursor-not-allowed", "opacity-60");
      });
      if (this.offlineEmpty) {
        this.offlineEmpty.textContent = "Офлайн-режим недоступен в этом браузере.";
      }
    }

    showOfflineWarning(message) {
      if (!this.offlineWarning) {
        return;
      }
      this.offlineWarning.textContent = message;
      this.offlineWarning.classList.remove("hidden");
    }

    openDialog() {
      if (!this.dialog) {
        return;
      }
      this.clearFormError();
      if (typeof this.dialog.showModal === "function") {
        this.dialog.showModal();
      } else {
        this.dialog.style.display = "block";
        this.dialog.setAttribute("open", "open");
      }
      const field = this.form ? this.form.querySelector("input[name='building']") : null;
      if (field && typeof field.focus === "function") {
        field.focus();
      }
    }

    closeDialog() {
      if (!this.dialog) {
        return;
      }
      if (typeof this.dialog.close === "function") {
        this.dialog.close();
      } else {
        this.dialog.removeAttribute("open");
        this.dialog.style.display = "none";
      }
      if (this.form) {
        this.form.reset();
      }
      this.clearFormError();
    }

    handleFormSubmit() {
      if (!this.form || !this.db) {
        return;
      }
      if (!Offline) {
        this.showFormError("Локальное хранилище недоступно.");
        return;
      }
      const building = (this.form.elements.building?.value || "").trim();
      const elevator = (this.form.elements.elevator?.value || "").trim();
      const plannedDateRaw = (this.form.elements.planned_date?.value || "").trim();
      const note = (this.form.elements.note?.value || "").trim();

      if (!building && !elevator) {
        this.showFormError("Укажите хотя бы адрес объекта или идентификатор лифта.");
        return;
      }

      const now = new Date().toISOString();
      const record = {
        clientId: Offline.generateClientId(),
        building,
        elevator,
        buildingId: null,
        elevatorId: null,
        plannedDate: plannedDateRaw || null,
        note,
        createdAt: now,
        updatedAt: now,
        status: "draft",
        syncState: "pending",
        objectInfo: {},
      };

      Offline.putRecord(this.db, STORES.AUDITS, record)
        .then(() => {
          this.showFlash("Черновик сохранён. Он будет доступен без подключения к интернету.");
          this.closeDialog();
          this.refreshOfflineList();
        })
        .catch((error) => {
          console.error("Failed to persist offline audit", error);
          this.showFormError("Не удалось сохранить черновик. Попробуйте ещё раз.");
        });
    }

    showFormError(message) {
      if (!this.errorBox) {
        return;
      }
      this.errorBox.textContent = message;
      this.errorBox.classList.remove("hidden");
    }

    clearFormError() {
      if (!this.errorBox) {
        return;
      }
      this.errorBox.textContent = "";
      this.errorBox.classList.add("hidden");
    }

    showFlash(message, variant = "success") {
      if (!this.flash) {
        return;
      }
      const classMap = {
        success: ["border-emerald-200", "bg-emerald-50", "text-emerald-800"],
        error: ["border-red-200", "bg-red-50", "text-red-700"],
        info: ["border-sky-200", "bg-sky-50", "text-sky-800"],
      };
      const classes = classMap[variant] || classMap.success;
      this.flash.className = "rounded-lg border px-4 py-3 text-sm font-medium";
      this.flash.classList.add(...classes);
      this.flash.textContent = message;
      this.flash.classList.remove("hidden");
      window.clearTimeout(this.flashTimeout);
      this.flashTimeout = window.setTimeout(() => {
        this.flash?.classList.add("hidden");
      }, 4000);
    }

    refreshOfflineList() {
      if (!this.db || !this.offlineList || !Offline) {
        return;
      }
      Offline.getAllRecords(this.db, STORES.AUDITS)
        .then((records) => {
          records.sort((a, b) => {
            const left = a.updatedAt || a.createdAt || "";
            const right = b.updatedAt || b.createdAt || "";
            return right.localeCompare(left);
          });
          this.renderOfflineList(records);
        })
        .catch((error) => {
          console.error("Failed to read offline audits", error);
          this.showFlash("Не удалось прочитать офлайн-черновики.", "error");
        });
    }

    async refreshCatalogCache() {
      if (!this.db || !this.catalogUrl || !Offline) {
        return;
      }
      try {
        const response = await fetch(this.catalogUrl, {
          headers: { Accept: "application/json" },
          credentials: "same-origin",
        });
        if (!response.ok) {
          throw new Error(`Request failed with status ${response.status}`);
        }
        const payload = await response.json();
        await this.persistCatalogPayload(payload);
      } catch (error) {
        console.warn("Failed to refresh catalogue snapshot", error);
      }
    }

    async persistCatalogPayload(payload) {
      if (!this.db || !Offline) {
        return;
      }
      const buildings = Array.isArray(payload?.buildings) ? payload.buildings : [];
      const elevators = Array.isArray(payload?.elevators) ? payload.elevators : [];
      const fields = Array.isArray(payload?.object_fields) ? payload.object_fields : [];
      try {
        await Offline.clearStore(this.db, STORES.BUILDINGS);
        await Offline.clearStore(this.db, STORES.ELEVATORS);
        await Offline.clearStore(this.db, STORES.OBJECT_FIELDS);
        if (buildings.length) {
          await Offline.putRecords(this.db, STORES.BUILDINGS, buildings);
        }
        if (elevators.length) {
          await Offline.putRecords(this.db, STORES.ELEVATORS, elevators);
        }
        if (fields.length) {
          await Offline.putRecords(this.db, STORES.OBJECT_FIELDS, fields);
        }
        const generatedAt = payload?.generated_at || null;
        if (generatedAt) {
          await Offline.putRecord(this.db, STORES.META, {
            key: "catalog_generated_at",
            value: generatedAt,
          });
        }
      } catch (error) {
        console.warn("Failed to store catalogue snapshot", error);
      }
    }

    renderOfflineList(records) {
      if (!this.offlineList) {
        return;
      }
      this.offlineList.innerHTML = "";
      const hasRecords = Array.isArray(records) && records.length > 0;
      if (this.offlineEmpty) {
        this.offlineEmpty.classList.toggle("hidden", hasRecords);
      }
      if (!hasRecords) {
        return;
      }
      records.forEach((record) => {
        const element = this.createOfflineCard(record);
        this.offlineList.appendChild(element);
      });
    }

    createOfflineCard(record) {
      const template = this.template ? this.template.content : null;
      const fragment = template ? template.cloneNode(true) : document.createElement("div");
      const container = fragment.querySelector ? fragment : document.createDocumentFragment();
      const root = container.querySelector ? container.querySelector("article") : null;
      if (!root) {
        return document.createElement("div");
      }
      const buildingField = root.querySelector("[data-field='building']");
      const elevatorField = root.querySelector("[data-field='elevator']");
      const plannedDateField = root.querySelector("[data-field='planned-date']");
      const updatedField = root.querySelector("[data-field='updated']");
      const titleField = root.querySelector("[data-field='title']");
      const openButton = root.querySelector('[data-action="open"]');
      const deleteButton = root.querySelector('[data-action="delete"]');

      if (titleField) {
        titleField.textContent = buildTitle(record);
      }
      if (buildingField) {
        buildingField.textContent = record.building || "—";
      }
      if (elevatorField) {
        elevatorField.textContent = record.elevator || "—";
      }
      if (plannedDateField) {
        plannedDateField.textContent = formatDate(record.plannedDate);
      }
      if (updatedField) {
        updatedField.textContent = formatDateTime(record.updatedAt || record.createdAt);
      }
      if (openButton) {
        openButton.addEventListener("click", (event) => {
          event.preventDefault();
          this.openDraft(record);
        });
      }
      if (deleteButton) {
        deleteButton.addEventListener("click", (event) => {
          event.preventDefault();
          this.handleDelete(record.clientId);
        });
      }
      return root;
    }

    openDraft(record) {
      if (!record || !record.clientId) {
        this.showFlash("Черновик не найден.", "error");
        return;
      }
      if (!this.objectInfoUrl) {
        this.showFlash("Форма информационной карты появится позже.", "info");
        return;
      }
      try {
        const target = new URL(this.objectInfoUrl, window.location.href);
        target.searchParams.set("client_id", record.clientId);
        window.location.href = target.toString();
      } catch (error) {
        const separator = this.objectInfoUrl.includes("?") ? "&" : "?";
        window.location.href = `${this.objectInfoUrl}${separator}client_id=${encodeURIComponent(record.clientId)}`;
      }
    }

    handleDelete(clientId) {
      if (!this.db) {
        return;
      }
      const confirmed = window.confirm("Удалить офлайн-черновик? Данные будет невозможно восстановить.");
      if (!confirmed) {
        return;
      }
      if (!Offline) {
        this.showFlash("Локальное хранилище недоступно.", "error");
        return;
      }
      Offline.deleteRecord(this.db, STORES.AUDITS, clientId)
        .then(() => {
          this.showFlash("Черновик удалён.");
          this.refreshOfflineList();
        })
        .catch((error) => {
          console.error("Failed to delete offline audit", error);
          this.showFlash("Не удалось удалить черновик.", "error");
        });
    }
  }

  function formatDate(value) {
    if (!value) {
      return "—";
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return "—";
    }
    return date.toLocaleDateString("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    });
  }

  function formatDateTime(value) {
    if (!value) {
      return "—";
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return "—";
    }
    return date.toLocaleString("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function buildTitle(record) {
    if (record.building && record.elevator) {
      return `${record.building} — ${record.elevator}`;
    }
    if (record.building) {
      return record.building;
    }
    if (record.elevator) {
      return record.elevator;
    }
    return "Черновик аудита";
  }
})();
