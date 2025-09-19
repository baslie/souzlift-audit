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
  const DEVICE_STORAGE_KEY = "souzlift_device_id";
  const SYNC_BADGE_CLASSES = Object.freeze({
    pending: ["border-amber-200", "bg-amber-50", "text-amber-700"],
    processing: ["border-sky-200", "bg-sky-50", "text-sky-700"],
    error: ["border-red-200", "bg-red-50", "text-red-700"],
    synced: ["border-emerald-200", "bg-emerald-50", "text-emerald-700"],
  });

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
      this.syncPanel = root.querySelector("[data-sync-panel]");
      this.syncStatus = root.querySelector("[data-sync-status]");
      this.syncDetails = root.querySelector("[data-sync-details]");
      this.syncErrors = root.querySelector("[data-sync-errors]");
      this.syncButton = root.querySelector("[data-sync-trigger]");
      this.syncUrl = root.dataset.syncUrl || "";
      this.deviceId = this.loadDeviceId();
      this.syncStatusTimeout = null;
      this.syncStatusSticky = false;
      this.syncInProgress = false;
      this.fallbackDeviceId = null;
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
      if (this.syncButton) {
        this.syncButton.addEventListener("click", (event) => {
          event.preventDefault();
          this.handleManualSync();
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
        if (!this.syncInProgress) {
          this.updateSyncStatus("Соединение восстановлено. Можно отправить данные.", "info", { sticky: true });
          this.scheduleStatusReset();
        }
        this.refreshOfflineList();
      });
      window.addEventListener("offline", () => {
        if (!this.syncInProgress) {
          this.updateSyncStatus(
            "Нет подключения к интернету. Синхронизация станет доступна после восстановления связи.",
            "warning",
            { sticky: true }
          );
        }
      });
    }

    initDatabase() {
      if (!Offline || !Offline.isSupported()) {
        this.showOfflineWarning("Браузер не поддерживает IndexedDB. Черновики будут недоступны.");
        this.disableOfflineCreation();
        this.disableSyncPanel("Офлайн-синхронизация недоступна в этом браузере.");
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
          this.disableSyncPanel("Не удалось инициализировать локальное хранилище. Синхронизация отключена.");
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
      this.disableSyncPanel("Офлайн-синхронизация недоступна в этом браузере.");
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
          this.updateSyncSummary(records);
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
      this.applySyncState(root, record);
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

    async handleManualSync() {
      if (this.syncInProgress) {
        return;
      }
      if (!this.db || !Offline) {
        this.updateSyncStatus("Локальное хранилище недоступно. Синхронизация невозможна.", "error", { sticky: true });
        return;
      }
      if (!this.syncUrl) {
        this.updateSyncStatus("Не указан адрес для синхронизации.", "error", { sticky: true });
        return;
      }
      if (!navigator.onLine) {
        this.updateSyncStatus("Нет подключения к интернету. Попробуйте позже.", "warning", { sticky: true });
        return;
      }

      this.setSyncInProgress(true);
      this.clearSyncErrors();
      this.updateSyncStatus("Отправляем данные…", "info", { sticky: true });

      try {
        const result = await this.performSync();
        if (result.errors.length) {
          this.renderSyncErrors(result.errors);
          this.updateSyncStatus("Не удалось отправить все данные. Проверьте ошибки.", "error", { sticky: true });
        } else if (result.syncedAudits > 0) {
          const attachmentsNote = result.uploadedAttachments
            ? `, вложений: ${result.uploadedAttachments}`
            : "";
          this.showFlash(`Отправлено аудитов: ${result.syncedAudits}${attachmentsNote}.`, "success");
          this.updateSyncStatus("Данные успешно отправлены.", "success", { sticky: true });
          this.scheduleStatusReset();
        } else {
          this.updateSyncStatus("Нет данных для синхронизации.", "info");
        }
      } catch (error) {
        console.error("Offline sync failed", error);
        const message = error && error.message ? error.message : "Не удалось выполнить синхронизацию.";
        this.updateSyncStatus(message, "error", { sticky: true });
        this.renderSyncErrors([message]);
      } finally {
        this.setSyncInProgress(false);
        this.refreshOfflineList();
      }
    }

    async performSync() {
      if (!this.db || !Offline) {
        throw new Error("Локальное хранилище недоступно.");
      }

      const deviceId = this.deviceId || this.loadDeviceId();
      if (!deviceId) {
        throw new Error("Не удалось определить идентификатор устройства.");
      }

      let audits = [];
      let additions = [];
      try {
        [audits, additions] = await Promise.all([
          Offline.getAllRecords(this.db, STORES.AUDITS),
          Offline.getAllRecords(this.db, STORES.CATALOG_ADDITIONS),
        ]);
      } catch (error) {
        throw new Error("Не удалось прочитать локальные данные для синхронизации.");
      }

      const pendingAudits = audits.filter(
        (record) => record && record.clientId && record.syncState !== "synced"
      );
      if (!pendingAudits.length) {
        return { syncedAudits: 0, uploadedAttachments: 0, errors: [] };
      }

      const additionMap = new Map();
      additions.forEach((record) => {
        if (!record || !record.clientId) {
          return;
        }
        const current = additionMap.get(record.clientId) || { building: null, elevator: null };
        if (record.type === "building" && !current.building) {
          current.building = record;
        } else if (record.type === "elevator" && !current.elevator) {
          current.elevator = record;
        }
        additionMap.set(record.clientId, current);
      });

      const usedAuditIds = new Set();
      const payloadAudits = [];
      const attachmentsQueue = [];
      const errors = [];

      for (const record of pendingAudits) {
        const result = await this.prepareAuditForSync(record, additionMap);
        if (!result.ok) {
          errors.push(...result.errors);
          await this.persistAuditError(record, result.errors.join(" "));
          continue;
        }
        payloadAudits.push(result.payload);
        attachmentsQueue.push(result.attachments);
        usedAuditIds.add(record.clientId);
        record.syncState = "processing";
        record.syncError = null;
        record.updatedAt = new Date().toISOString();
        try {
          await Offline.putRecord(this.db, STORES.AUDITS, record);
        } catch (error) {
          console.warn("Failed to update offline audit state", error);
        }
      }

      if (!payloadAudits.length) {
        return { syncedAudits: 0, uploadedAttachments: 0, errors };
      }

      const catalogPayload = this.prepareCatalogPayload(additions, usedAuditIds);
      const payload = {
        device_id: deviceId,
        catalog: catalogPayload,
        audits: payloadAudits,
      };

      const csrfToken = getCsrfToken();
      if (!csrfToken) {
        throw new Error("CSRF токен не найден. Обновите страницу.");
      }

      const response = await fetch(this.syncUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify(payload),
      });

      let body = null;
      try {
        body = await response.json();
      } catch (error) {
        body = null;
      }

      if (!response.ok || !body || body.status !== "ok") {
        const errorMessages = this.extractSyncErrors(body);
        if (!errorMessages.length) {
          errorMessages.push(body && body.message ? body.message : `Сервер вернул статус ${response.status}.`);
        }
        errors.push(...errorMessages);
        for (const item of attachmentsQueue) {
          if (item && item.auditRecord) {
            await this.persistAuditError(item.auditRecord, errorMessages[0] || "Ошибка синхронизации.");
          }
        }
        return { syncedAudits: 0, uploadedAttachments: 0, errors };
      }

      const responseMap = this.buildResponseMap(body);
      const attachmentResult = await this.uploadPendingAttachments(
        attachmentsQueue,
        responseMap,
        deviceId,
        csrfToken
      );

      const successAudits = attachmentResult.successAudits;
      const attachmentErrors = attachmentResult.errors;
      errors.push(...attachmentErrors);

      for (const item of attachmentsQueue) {
        const auditId = item && item.auditRecord ? item.auditRecord.clientId : null;
        if (!auditId) {
          continue;
        }
        if (successAudits.has(auditId)) {
          await this.clearAuditData(auditId);
        } else if (attachmentErrors.length && item.auditRecord) {
          await this.persistAuditError(item.auditRecord, attachmentErrors[0] || "Не удалось загрузить вложения.");
        }
      }

      return {
        syncedAudits: successAudits.size,
        uploadedAttachments: attachmentResult.uploaded,
        errors,
      };
    }

    async prepareAuditForSync(record, additionMap) {
      if (!record || !record.clientId) {
        return { ok: false, errors: ["Не удалось определить идентификатор черновика."] };
      }

      const errors = [];
      const clientId = record.clientId;
      const additions = additionMap.get(clientId) || { building: null, elevator: null };
      const payload = {
        client_id: clientId,
        status: typeof record.status === "string" && record.status ? record.status : "submitted",
      };

      if (record.plannedDate) {
        payload.planned_date = record.plannedDate;
      }

      if (record.objectInfo && typeof record.objectInfo === "object") {
        const entries = Object.entries(record.objectInfo).filter(([, value]) => value !== undefined);
        if (entries.length) {
          payload.object_info = Object.fromEntries(entries);
        }
      }

      let hasElevatorReference = false;
      if (Number.isFinite(Number(record.elevatorId))) {
        payload.elevator_id = Number(record.elevatorId);
        hasElevatorReference = true;
      } else if (additions.elevator) {
        payload.elevator_client_id = additions.elevator.id;
        hasElevatorReference = true;
      }

      if (!hasElevatorReference) {
        errors.push("Укажите лифт из справочника или добавьте его вручную.");
      }

      const responses = await Offline.getRecordsByIndex(this.db, STORES.RESPONSES, "by_client", clientId).catch(
        () => []
      );
      const responsePayload = [];
      responses.forEach((responseRecord) => {
        if (!responseRecord || typeof responseRecord.score !== "number") {
          return;
        }
        const questionId = Number(responseRecord.questionId);
        if (!Number.isFinite(questionId)) {
          return;
        }
        responsePayload.push({
          client_id: responseRecord.id || `${clientId}:${questionId}`,
          question_id: questionId,
          score: responseRecord.score,
          comment: typeof responseRecord.comment === "string" ? responseRecord.comment : "",
          is_flagged: Boolean(responseRecord.isFlagged),
        });
      });

      if (!responsePayload.length) {
        errors.push("Чек-лист не содержит ответов. Заполните вопросы перед отправкой.");
      }

      payload.responses = responsePayload;

      const attachmentRecords = await Offline.getRecordsByIndex(
        this.db,
        STORES.ATTACHMENTS,
        "by_client",
        clientId
      ).catch(() => []);

      const attachments = [];
      for (const attachmentRecord of attachmentRecords) {
        if (!attachmentRecord || !attachmentRecord.file) {
          continue;
        }
        const responseClientId = attachmentRecord.questionKey || attachmentRecord.id;
        if (!responseClientId) {
          continue;
        }
        const file = ensureFile(attachmentRecord.file, attachmentRecord.name || "attachment");
        const offlineUuid = await this.ensureAttachmentUuid(attachmentRecord);
        attachments.push({
          storageId: attachmentRecord.id,
          responseClientId,
          file,
          name: attachmentRecord.name || file.name || "attachment",
          offlineUuid,
        });
      }

      if (errors.length) {
        return { ok: false, errors };
      }

      return {
        ok: true,
        payload,
        attachments: { auditRecord: record, attachments },
      };
    }

    async ensureAttachmentUuid(record) {
      if (!record) {
        return this.generateOfflineUuid();
      }
      if (record.offlineUuid) {
        return record.offlineUuid;
      }
      const uuid = this.generateOfflineUuid();
      record.offlineUuid = uuid;
      try {
        await Offline.putRecord(this.db, STORES.ATTACHMENTS, record);
      } catch (error) {
        console.warn("Failed to persist offline UUID for attachment", error);
      }
      return uuid;
    }

    generateOfflineUuid() {
      if (window.crypto && typeof window.crypto.randomUUID === "function") {
        return window.crypto.randomUUID();
      }
      const random = Math.random().toString(16).slice(2);
      return `att-${Date.now().toString(16)}-${random}`;
    }

    prepareCatalogPayload(additions, usedAuditIds) {
      const payload = { buildings: [], elevators: [] };
      additions.forEach((addition) => {
        if (!addition || !addition.clientId || !usedAuditIds.has(addition.clientId)) {
          return;
        }
        if (addition.type === "building") {
          const address = addition.payload && addition.payload.label ? addition.payload.label.trim() : "";
          if (!address) {
            return;
          }
          const entry = { client_id: addition.id, address };
          if (addition.payload && addition.payload.note) {
            entry.notes = addition.payload.note;
          }
          payload.buildings.push(entry);
        } else if (addition.type === "elevator") {
          const identifier = addition.payload && addition.payload.label ? addition.payload.label.trim() : "";
          if (!identifier) {
            return;
          }
          const entry = {
            client_id: addition.id,
            identifier,
            status: "in_service",
          };
          if (addition.payload && addition.payload.note) {
            entry.description = addition.payload.note;
          }
          const buildingId = addition.payload?.buildingId || addition.relatedBuildingId;
          if (buildingId) {
            entry.building_id = buildingId;
          } else {
            const buildingAddition = additions.find(
              (item) => item && item.clientId === addition.clientId && item.type === "building"
            );
            if (buildingAddition) {
              entry.building_client_id = buildingAddition.id;
            }
          }
          payload.elevators.push(entry);
        }
      });
      return payload;
    }

    buildResponseMap(body) {
      const map = new Map();
      const audits = Array.isArray(body?.audits) ? body.audits : [];
      audits.forEach((audit) => {
        const responses = Array.isArray(audit?.responses) ? audit.responses : [];
        responses.forEach((response) => {
          if (response && response.client_id && response.id) {
            map.set(String(response.client_id), Number(response.id));
          }
        });
      });
      return map;
    }

    async uploadPendingAttachments(queue, responseMap, deviceId, csrfToken) {
      const successAudits = new Set();
      const errors = [];
      let uploaded = 0;

      for (const item of queue) {
        if (!item || !item.auditRecord) {
          continue;
        }
        const attachments = Array.isArray(item.attachments) ? item.attachments : [];
        if (!attachments.length) {
          successAudits.add(item.auditRecord.clientId);
          continue;
        }
        let failed = false;
        for (const attachment of attachments) {
          const responseId = responseMap.get(String(attachment.responseClientId));
          if (!responseId) {
            continue;
          }
          const formData = new FormData();
          formData.append(
            "payload",
            JSON.stringify({
              device_id: deviceId,
              attachment: {
                response_id: responseId,
                caption: attachment.name || "",
                offline_uuid: attachment.offlineUuid,
              },
            })
          );
          formData.append("file", attachment.file, attachment.name || "attachment");

          const response = await fetch(this.syncUrl, {
            method: "POST",
            credentials: "same-origin",
            headers: { "X-CSRFToken": csrfToken },
            body: formData,
          });

          let body = null;
          try {
            body = await response.json();
          } catch (error) {
            body = null;
          }

          if (!response.ok || !body || body.status !== "ok") {
            failed = true;
            const errorMessages = this.extractSyncErrors(body);
            if (errorMessages.length) {
              errors.push(...errorMessages);
            } else {
              errors.push(body && body.message ? body.message : `Не удалось загрузить файл (статус ${response.status}).`);
            }
            break;
          }
          uploaded += 1;
        }
        if (!failed) {
          successAudits.add(item.auditRecord.clientId);
        }
      }

      return { uploaded, successAudits, errors };
    }

    async clearAuditData(clientId) {
      if (!this.db || !Offline || !clientId) {
        return;
      }
      try {
        await Offline.deleteRecord(this.db, STORES.AUDITS, clientId);
      } catch (error) {
        console.warn("Failed to delete offline audit record", error);
      }
      const [responses, attachments, additions] = await Promise.all([
        Offline.getRecordsByIndex(this.db, STORES.RESPONSES, "by_client", clientId).catch(() => []),
        Offline.getRecordsByIndex(this.db, STORES.ATTACHMENTS, "by_client", clientId).catch(() => []),
        Offline.getRecordsByIndex(this.db, STORES.CATALOG_ADDITIONS, "by_client", clientId).catch(() => []),
      ]);
      if (responses.length) {
        try {
          await Offline.deleteRecords(
            this.db,
            STORES.RESPONSES,
            responses.map((record) => record.id)
          );
        } catch (error) {
          console.warn("Failed to delete offline responses", error);
        }
      }
      if (attachments.length) {
        try {
          await Offline.deleteRecords(
            this.db,
            STORES.ATTACHMENTS,
            attachments.map((record) => record.id)
          );
        } catch (error) {
          console.warn("Failed to delete offline attachments", error);
        }
      }
      if (additions.length) {
        try {
          await Offline.deleteRecords(
            this.db,
            STORES.CATALOG_ADDITIONS,
            additions.map((record) => record.id)
          );
        } catch (error) {
          console.warn("Failed to delete offline catalogue additions", error);
        }
      }
    }

    async persistAuditError(record, message) {
      if (!record || !record.clientId || !this.db || !Offline) {
        return;
      }
      record.syncState = "error";
      record.syncError = message;
      record.updatedAt = new Date().toISOString();
      try {
        await Offline.putRecord(this.db, STORES.AUDITS, record);
      } catch (error) {
        console.warn("Failed to store sync error state", error);
      }
    }

    updateSyncSummary(records) {
      if (!this.syncStatus || this.syncStatusSticky) {
        return;
      }
      const list = Array.isArray(records) ? records : [];
      const pending = list.filter((record) => record && record.syncState !== "synced").length;
      const errors = list.filter((record) => record && record.syncState === "error").length;
      if (!pending) {
        this.updateSyncStatus("Нет данных для синхронизации.", "info");
        return;
      }
      const detailMessage = errors
        ? `Есть черновики с ошибками (${errors}). Исправьте их и повторите попытку.`
        : "Нажмите «Отправить данные», когда появится подключение к интернету.";
      this.updateSyncStatus(`Готово к отправке черновиков: ${pending}.`, "info", { details: detailMessage });
    }

    updateSyncStatus(message, variant = "info", options = {}) {
      if (!this.syncStatus) {
        return;
      }
      const { sticky = false, details = null } = options;
      const classMap = {
        success: ["text-emerald-700"],
        error: ["text-red-700"],
        warning: ["text-amber-700"],
        info: ["text-slate-700"],
      };
      const classes = classMap[variant] || classMap.info;
      this.syncStatus.className = ["font-medium", "text-sm", ...classes].join(" ");
      this.syncStatus.textContent = message;
      this.syncStatusSticky = sticky;
      if (this.syncDetails) {
        if (details) {
          this.syncDetails.textContent = details;
          this.syncDetails.classList.remove("hidden");
        } else if (!sticky) {
          this.syncDetails.textContent = "";
          this.syncDetails.classList.add("hidden");
        }
      }
      if (sticky) {
        if (this.syncStatusTimeout) {
          window.clearTimeout(this.syncStatusTimeout);
          this.syncStatusTimeout = null;
        }
      }
    }

    scheduleStatusReset(delay = 4000) {
      if (this.syncStatusTimeout) {
        window.clearTimeout(this.syncStatusTimeout);
      }
      this.syncStatusTimeout = window.setTimeout(() => {
        this.syncStatusSticky = false;
        this.syncStatusTimeout = null;
        this.refreshOfflineList();
      }, delay);
    }

    renderSyncErrors(messages) {
      if (!this.syncErrors) {
        return;
      }
      this.syncErrors.innerHTML = "";
      const items = Array.isArray(messages) ? messages.filter((message) => Boolean(message)) : [];
      if (!items.length) {
        this.syncErrors.classList.add("hidden");
        return;
      }
      const unique = Array.from(new Set(items));
      unique.forEach((message) => {
        const li = document.createElement("li");
        li.textContent = message;
        this.syncErrors.appendChild(li);
      });
      this.syncErrors.classList.remove("hidden");
    }

    clearSyncErrors() {
      this.renderSyncErrors([]);
    }

    setSyncInProgress(isInProgress) {
      this.syncInProgress = isInProgress;
      if (!this.syncButton) {
        return;
      }
      if (isInProgress) {
        this.syncButton.setAttribute("disabled", "disabled");
        this.syncButton.classList.add("opacity-60", "cursor-not-allowed");
        if (!this.syncButton.dataset.originalText) {
          this.syncButton.dataset.originalText = this.syncButton.textContent || "";
        }
        this.syncButton.textContent = "Отправляем…";
      } else {
        this.syncButton.removeAttribute("disabled");
        this.syncButton.classList.remove("opacity-60", "cursor-not-allowed");
        const originalText = this.syncButton.dataset.originalText || "Отправить данные";
        this.syncButton.textContent = originalText;
      }
    }

    disableSyncPanel(message) {
      if (!this.syncPanel) {
        return;
      }
      this.updateSyncStatus(message, "warning", { sticky: true, details: null });
      if (this.syncButton) {
        this.syncButton.setAttribute("disabled", "disabled");
        this.syncButton.classList.add("opacity-60", "cursor-not-allowed");
      }
      this.clearSyncErrors();
    }

    loadDeviceId() {
      try {
        const storage = window.localStorage;
        if (storage) {
          const existing = storage.getItem(DEVICE_STORAGE_KEY);
          if (existing) {
            return existing;
          }
          const generated = this.generateDeviceId();
          storage.setItem(DEVICE_STORAGE_KEY, generated);
          return generated;
        }
      } catch (error) {
        console.warn("Failed to access localStorage for device ID", error);
      }
      if (!this.fallbackDeviceId) {
        this.fallbackDeviceId = this.generateDeviceId();
      }
      return this.fallbackDeviceId;
    }

    generateDeviceId() {
      if (window.crypto && typeof window.crypto.randomUUID === "function") {
        return window.crypto.randomUUID();
      }
      const random = Math.random().toString(16).slice(2);
      return `device-${Date.now().toString(16)}-${random}`;
    }

    extractSyncErrors(body) {
      if (!body || typeof body !== "object" || !body.errors) {
        return [];
      }
      const errors = [];
      const raw = body.errors;
      if (typeof raw !== "object") {
        return errors;
      }
      Object.values(raw).forEach((value) => {
        if (Array.isArray(value)) {
          value.forEach((item) => {
            if (typeof item === "string") {
              errors.push(item);
            } else if (item && typeof item === "object") {
              Object.values(item).forEach((nested) => {
                if (typeof nested === "string") {
                  errors.push(nested);
                }
              });
            }
          });
        } else if (typeof value === "string") {
          errors.push(value);
        }
      });
      return errors;
    }

    applySyncState(root, record) {
      if (!root) {
        return;
      }
      const badge = root.querySelector("[data-field='sync-state']");
      const state = record && record.syncState ? record.syncState : "pending";
      const classes = SYNC_BADGE_CLASSES[state] || SYNC_BADGE_CLASSES.pending;
      const baseClasses = [
        "inline-flex",
        "items-center",
        "gap-1",
        "rounded-full",
        "border",
        "px-3",
        "py-1",
        "text-xs",
        "font-semibold",
      ];
      if (badge) {
        badge.className = [...baseClasses, ...classes].join(" ");
        const labels = {
          pending: "Ожидает синхронизации",
          processing: "Отправляется…",
          error: "Ошибка синхронизации",
          synced: "Отправлено",
        };
        badge.textContent = labels[state] || labels.pending;
      }
      const errorField = root.querySelector("[data-field='sync-error']");
      if (errorField) {
        if (record && record.syncError) {
          errorField.textContent = record.syncError;
          errorField.classList.remove("hidden");
        } else {
          errorField.textContent = "";
          errorField.classList.add("hidden");
        }
      }
    }

  }

  function getCsrfToken() {
    if (typeof document === "undefined" || typeof document.cookie !== "string") {
      return null;
    }
    const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : null;
  }

  function ensureFile(source, fallbackName) {
    if (source instanceof File) {
      return source;
    }
    const blob = source instanceof Blob ? source : new Blob([source || new ArrayBuffer(0)]);
    const name = fallbackName || (source && source.name) || "attachment";
    const options = {
      type: blob.type || "application/octet-stream",
      lastModified:
        (source && typeof source.lastModified === "number" && source.lastModified) || Date.now(),
    };
    try {
      return new File([blob], name, options);
    } catch (error) {
      return new File([new Blob([blob], { type: options.type })], name, options);
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
