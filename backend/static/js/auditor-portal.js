(function () {
  "use strict";

  const DB_NAME = "souzlift_offline";
  const DB_VERSION = 1;
  const STORE_AUDITS = "offline_audits";

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
    }

    initDatabase() {
      if (!window.indexedDB) {
        this.showOfflineWarning("Браузер не поддерживает IndexedDB. Черновики будут недоступны.");
        this.disableOfflineCreation();
        return;
      }
      openDatabase()
        .then((db) => {
          this.db = db;
          this.refreshOfflineList();
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
        clientId: generateClientId(),
        building,
        elevator,
        plannedDate: plannedDateRaw || null,
        note,
        createdAt: now,
        updatedAt: now,
        status: "draft",
        syncState: "pending",
      };

      saveRecord(this.db, record)
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
      if (!this.db || !this.offlineList) {
        return;
      }
      fetchAllRecords(this.db)
        .then((records) => {
          this.renderOfflineList(records);
        })
        .catch((error) => {
          console.error("Failed to read offline audits", error);
          this.showFlash("Не удалось прочитать офлайн-черновики.", "error");
        });
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
          this.showFlash("Заполнение черновика будет доступно после настройки форм чек-листа.", "info");
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

    handleDelete(clientId) {
      if (!this.db) {
        return;
      }
      const confirmed = window.confirm("Удалить офлайн-черновик? Данные будет невозможно восстановить.");
      if (!confirmed) {
        return;
      }
      deleteRecord(this.db, clientId)
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

  function openDatabase() {
    return new Promise((resolve, reject) => {
      try {
        const request = window.indexedDB.open(DB_NAME, DB_VERSION);
        request.onerror = () => reject(request.error || new Error("Не удалось открыть IndexedDB."));
        request.onupgradeneeded = () => {
          const db = request.result;
          if (!db.objectStoreNames.contains(STORE_AUDITS)) {
            const store = db.createObjectStore(STORE_AUDITS, { keyPath: "clientId" });
            store.createIndex("updatedAt", "updatedAt", { unique: false });
            store.createIndex("status", "status", { unique: false });
          }
        };
        request.onsuccess = () => resolve(request.result);
      } catch (error) {
        reject(error);
      }
    });
  }

  function saveRecord(db, record) {
    return new Promise((resolve, reject) => {
      const transaction = db.transaction(STORE_AUDITS, "readwrite");
      const store = transaction.objectStore(STORE_AUDITS);
      store.put(record);
      transaction.oncomplete = () => resolve(record);
      transaction.onerror = () => reject(transaction.error || new Error("Ошибка записи в IndexedDB."));
    });
  }

  function fetchAllRecords(db) {
    return new Promise((resolve, reject) => {
      const transaction = db.transaction(STORE_AUDITS, "readonly");
      const store = transaction.objectStore(STORE_AUDITS);
      const request = store.getAll();
      request.onsuccess = () => {
        const records = Array.isArray(request.result) ? request.result.slice() : [];
        records.sort((a, b) => {
          const left = a.updatedAt || a.createdAt || "";
          const right = b.updatedAt || b.createdAt || "";
          return right.localeCompare(left);
        });
        resolve(records);
      };
      request.onerror = () => reject(request.error || new Error("Ошибка чтения из IndexedDB."));
    });
  }

  function deleteRecord(db, clientId) {
    return new Promise((resolve, reject) => {
      const transaction = db.transaction(STORE_AUDITS, "readwrite");
      const store = transaction.objectStore(STORE_AUDITS);
      store.delete(clientId);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error || new Error("Ошибка удаления из IndexedDB."));
    });
  }

  function generateClientId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    const random = Math.random().toString(16).slice(2);
    return `draft-${Date.now().toString(16)}-${random}`;
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
