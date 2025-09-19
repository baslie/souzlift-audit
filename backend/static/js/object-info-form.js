(function (window) {
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
    document.querySelectorAll("[data-object-info-form]").forEach((element) => {
      new ObjectInfoForm(element);
    });
  });

  class ObjectInfoForm {
    constructor(root) {
      this.root = root;
      this.clientId = root.dataset.clientId || "";
      this.catalogUrl = root.dataset.catalogUrl || "";
      this.listUrl = root.dataset.listUrl || "";

      this.statusBox = root.querySelector("[data-status]");
      this.errorBox = root.querySelector("[data-error]");
      this.catalogTimestamp = root.querySelector("[data-catalog-timestamp]");
      this.emptyFieldsNote = root.querySelector("[data-empty-fields]");

      this.buildingSelect = root.querySelector("[data-building-select]");
      this.elevatorSelect = root.querySelector("[data-elevator-select]");
      this.manualBuildingInput = root.querySelector("[data-building-manual]");
      this.manualElevatorInput = root.querySelector("[data-elevator-manual]");
      this.noteField = root.querySelector("[data-note-field]");
      this.fieldsContainer = root.querySelector("[data-dynamic-fields]");
      this.saveButton = root.querySelector('[data-action="save"]');
      this.refreshButton = root.querySelector('[data-action="refresh-catalog"]');

      this.db = null;
      this.record = null;
      this.catalog = { buildings: [], elevators: [] };
      this.fields = [];
      this.fieldInputs = new Map();
      this.catalogGeneratedAt = null;

      this.initialFields = readJsonScript("object-info-fields") || [];
      this.initialCatalog = readJsonScript("catalog-initial-data") || {};
      this.initialMeta = readJsonScript("catalog-meta") || {};

      this.init();
    }

    async init() {
      this.catalog = {
        buildings: Array.isArray(this.initialCatalog.buildings)
          ? this.initialCatalog.buildings.slice()
          : [],
        elevators: Array.isArray(this.initialCatalog.elevators)
          ? this.initialCatalog.elevators.slice()
          : [],
      };
      this.fields = Array.isArray(this.initialFields) ? this.initialFields.slice() : [];
      this.catalogGeneratedAt = this.initialMeta?.generated_at || null;

      if (!Offline || !Offline.isSupported()) {
        this.showError(
          "Браузер не поддерживает локальное хранилище. Сохранение черновика будет недоступно на этом устройстве.",
        );
        this.disableForm();
        this.renderCatalogOptions();
        this.renderFields();
        this.updateCatalogTimestamp();
        return;
      }

      try {
        this.db = await Offline.openDatabase();
      } catch (error) {
        console.error("Failed to open offline database", error);
        this.showError("Не удалось инициализировать локальное хранилище. Сохранение недоступно.");
        this.disableForm();
        this.renderCatalogOptions();
        this.renderFields();
        this.updateCatalogTimestamp();
        return;
      }

      await this.ensureInitialDataStored();
      await this.loadDraftRecord();
      await this.loadCatalogFromCache();
      await this.loadFieldsFromCache();

      this.renderCatalogOptions();
      this.renderFields();
      this.applyRecordValues();
      this.updateCatalogTimestamp();
      this.bindEvents();
      this.refreshFromServer();
    }

    bindEvents() {
      if (this.buildingSelect) {
        this.buildingSelect.addEventListener("change", () => {
          if (this.manualBuildingInput && this.buildingSelect.value) {
            this.manualBuildingInput.value = "";
          }
          if (this.record) {
            this.record.buildingId = this.buildingSelect.value ? Number(this.buildingSelect.value) : null;
            if (this.record.buildingId) {
              this.record.building = this.getBuildingLabel(this.record.buildingId);
            }
          }
          this.updateElevatorOptions();
        });
      }

      if (this.manualBuildingInput) {
        this.manualBuildingInput.addEventListener("input", () => {
          if (this.manualBuildingInput.value.trim() && this.buildingSelect) {
            this.buildingSelect.value = "";
            if (this.record) {
              this.record.buildingId = null;
            }
            this.updateElevatorOptions();
          }
        });
      }

      if (this.elevatorSelect) {
        this.elevatorSelect.addEventListener("change", () => {
          if (this.manualElevatorInput && this.elevatorSelect.value) {
            this.manualElevatorInput.value = "";
          }
          if (this.record) {
            this.record.elevatorId = this.elevatorSelect.value ? Number(this.elevatorSelect.value) : null;
            if (this.record.elevatorId) {
              this.record.elevator = this.getElevatorLabel(this.record.elevatorId);
            }
          }
        });
      }

      if (this.manualElevatorInput) {
        this.manualElevatorInput.addEventListener("input", () => {
          if (this.manualElevatorInput.value.trim() && this.elevatorSelect) {
            this.elevatorSelect.value = "";
            if (this.record) {
              this.record.elevatorId = null;
            }
          }
        });
      }

      if (this.saveButton) {
        this.saveButton.addEventListener("click", (event) => {
          event.preventDefault();
          this.handleSave();
        });
      }

      if (this.refreshButton) {
        this.refreshButton.addEventListener("click", (event) => {
          event.preventDefault();
          this.refreshFromServer();
        });
      }

      window.addEventListener("online", () => {
        this.refreshFromServer();
      });
    }

    disableForm() {
      [
        this.buildingSelect,
        this.elevatorSelect,
        this.manualBuildingInput,
        this.manualElevatorInput,
        this.noteField,
        this.saveButton,
        this.refreshButton,
      ].forEach((element) => {
        if (element) {
          element.setAttribute("disabled", "disabled");
        }
      });
    }

    async ensureInitialDataStored() {
      if (!this.db || !Offline) {
        return;
      }
      try {
        const [existingBuildings, existingElevators, existingFields] = await Promise.all([
          Offline.getAllRecords(this.db, STORES.BUILDINGS),
          Offline.getAllRecords(this.db, STORES.ELEVATORS),
          Offline.getAllRecords(this.db, STORES.OBJECT_FIELDS),
        ]);
        if (!existingBuildings.length && Array.isArray(this.initialCatalog.buildings) && this.initialCatalog.buildings.length) {
          await Offline.putRecords(this.db, STORES.BUILDINGS, this.initialCatalog.buildings);
        }
        if (!existingElevators.length && Array.isArray(this.initialCatalog.elevators) && this.initialCatalog.elevators.length) {
          await Offline.putRecords(this.db, STORES.ELEVATORS, this.initialCatalog.elevators);
        }
        if (!existingFields.length && Array.isArray(this.initialFields) && this.initialFields.length) {
          await Offline.putRecords(this.db, STORES.OBJECT_FIELDS, this.initialFields);
        }
        const generatedAt = this.initialMeta?.generated_at;
        if (generatedAt) {
          await Offline.putRecord(this.db, STORES.META, {
            key: "catalog_generated_at",
            value: generatedAt,
          });
        }
      } catch (error) {
        console.warn("Failed to seed offline catalogue", error);
      }
    }

    async loadDraftRecord() {
      if (!this.db || !Offline) {
        this.record = this.createEmptyRecord(this.clientId || "");
        return;
      }
      const identifier = this.clientId || Offline.generateClientId();
      this.clientId = identifier;
      let record = await Offline.getRecord(this.db, STORES.AUDITS, identifier);
      if (!record) {
        record = this.createEmptyRecord(identifier);
        await Offline.putRecord(this.db, STORES.AUDITS, record);
      }
      if (!record.objectInfo || typeof record.objectInfo !== "object") {
        record.objectInfo = {};
      }
      this.record = record;
    }

    async loadCatalogFromCache() {
      if (!this.db || !Offline) {
        return;
      }
      const [buildings, elevators, meta] = await Promise.all([
        Offline.getAllRecords(this.db, STORES.BUILDINGS),
        Offline.getAllRecords(this.db, STORES.ELEVATORS),
        Offline.getRecord(this.db, STORES.META, "catalog_generated_at"),
      ]);
      if (buildings.length) {
        this.catalog.buildings = buildings.slice();
      }
      if (elevators.length) {
        this.catalog.elevators = elevators.slice();
      }
      if (meta && typeof meta.value === "string" && meta.value) {
        this.catalogGeneratedAt = meta.value;
      }
    }

    async loadFieldsFromCache() {
      if (!this.db || !Offline) {
        this.sortFields();
        return;
      }
      const storedFields = await Offline.getAllRecords(this.db, STORES.OBJECT_FIELDS);
      if (storedFields.length) {
        this.fields = storedFields.slice();
      }
      this.sortFields();
    }

    sortFields() {
      this.fields.sort((left, right) => {
        const orderDiff = (left.order || 0) - (right.order || 0);
        if (orderDiff !== 0) {
          return orderDiff;
        }
        return (left.label || "").localeCompare(right.label || "");
      });
    }

    renderCatalogOptions() {
      if (this.buildingSelect) {
        const selected = this.record?.buildingId ? String(this.record.buildingId) : "";
        this.buildingSelect.innerHTML = "";
        const placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = "Выберите здание…";
        this.buildingSelect.appendChild(placeholder);
        const sortedBuildings = (this.catalog.buildings || []).slice().sort((a, b) => {
          return (a.label || a.address || "").localeCompare(b.label || b.address || "");
        });
        sortedBuildings.forEach((building) => {
          const option = document.createElement("option");
          option.value = String(building.id);
          option.textContent = building.label || building.address || `Здание #${building.id}`;
          option.dataset.reviewStatus = building.review_status || "";
          this.buildingSelect.appendChild(option);
        });
        this.buildingSelect.value = selected;
      }

      this.updateElevatorOptions();
    }

    updateElevatorOptions() {
      if (!this.elevatorSelect) {
        return;
      }
      const selectedBuildingId = this.buildingSelect ? this.buildingSelect.value : "";
      const selectedElevatorId = this.record?.elevatorId ? String(this.record.elevatorId) : "";
      this.elevatorSelect.innerHTML = "";
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = selectedBuildingId ? "Выберите лифт…" : "Сначала выберите здание";
      this.elevatorSelect.appendChild(placeholder);

      const buildingId = selectedBuildingId ? Number(selectedBuildingId) : null;
      const elevators = (this.catalog.elevators || []).filter((item) => {
        return buildingId ? Number(item.building_id) === buildingId : false;
      });
      elevators.sort((a, b) => (a.label || a.identifier || "").localeCompare(b.label || b.identifier || ""));

      elevators.forEach((item) => {
        const option = document.createElement("option");
        option.value = String(item.id);
        option.textContent = item.label || item.identifier || `Лифт #${item.id}`;
        option.dataset.buildingId = String(item.building_id || "");
        option.dataset.reviewStatus = item.review_status || "";
        this.elevatorSelect.appendChild(option);
      });

      const hasOptions = elevators.length > 0;
      this.elevatorSelect.disabled = !buildingId || !hasOptions;
      if (hasOptions && selectedElevatorId) {
        const exists = elevators.some((item) => String(item.id) === selectedElevatorId);
        this.elevatorSelect.value = exists ? selectedElevatorId : "";
      } else {
        this.elevatorSelect.value = "";
      }

      if (this.manualBuildingInput && !buildingId && this.record) {
        this.manualBuildingInput.value = this.record.buildingId ? "" : this.record.building || "";
      }
      if (this.manualElevatorInput && this.record) {
        this.manualElevatorInput.value = this.record.elevatorId ? "" : this.record.elevator || "";
      }
    }

    renderFields() {
      if (!this.fieldsContainer) {
        return;
      }
      this.fieldsContainer.innerHTML = "";
      this.fieldInputs.clear();

      if (!Array.isArray(this.fields) || this.fields.length === 0) {
        if (this.emptyFieldsNote) {
          this.emptyFieldsNote.classList.remove("hidden");
        }
        return;
      }

      if (this.emptyFieldsNote) {
        this.emptyFieldsNote.classList.add("hidden");
      }

      this.fields.forEach((field) => {
        const wrapper = document.createElement("div");
        wrapper.className = "space-y-1";
        const label = document.createElement("label");
        label.className = "text-xs font-semibold uppercase tracking-wide text-slate-500";
        const fieldId = `object-field-${field.code}`;
        label.setAttribute("for", fieldId);
        label.textContent = field.label || field.code;
        if (field.is_required) {
          const requiredMark = document.createElement("span");
          requiredMark.className = "ml-1 text-red-600";
          requiredMark.textContent = "*";
          label.appendChild(requiredMark);
        }

        const input = this.createInputForField(field, fieldId);
        wrapper.appendChild(label);
        wrapper.appendChild(input);
        this.fieldsContainer.appendChild(wrapper);
        this.fieldInputs.set(field.code, input);
      });
    }

    createInputForField(field, fieldId) {
      const type = field.field_type || "text";
      let input;
      const baseClass = "block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-sky-500 focus:outline-none focus:ring-2 focus:ring-sky-200";
      switch (type) {
        case "number":
          input = document.createElement("input");
          input.type = "number";
          input.step = "any";
          break;
        case "date":
          input = document.createElement("input");
          input.type = "date";
          break;
        case "boolean":
        case "choice":
          input = document.createElement("select");
          const placeholder = document.createElement("option");
          placeholder.value = "";
          placeholder.textContent = "Не выбрано";
          input.appendChild(placeholder);
          if (type === "boolean") {
            const yesOption = document.createElement("option");
            yesOption.value = "true";
            yesOption.textContent = "Да";
            const noOption = document.createElement("option");
            noOption.value = "false";
            noOption.textContent = "Нет";
            input.appendChild(yesOption);
            input.appendChild(noOption);
          } else if (Array.isArray(field.choices)) {
            field.choices.forEach((choice) => {
              const option = document.createElement("option");
              option.value = String(choice);
              option.textContent = String(choice);
              input.appendChild(option);
            });
          }
          break;
        default:
          input = document.createElement("input");
          input.type = "text";
          break;
      }
      input.id = fieldId;
      input.dataset.fieldCode = field.code;
      input.className = baseClass;
      if (field.is_required) {
        input.setAttribute("data-required", "true");
      }
      return input;
    }

    applyRecordValues() {
      if (!this.record) {
        return;
      }

      if (this.buildingSelect) {
        this.buildingSelect.value = this.record.buildingId ? String(this.record.buildingId) : "";
      }
      if (this.manualBuildingInput) {
        this.manualBuildingInput.value = this.record.buildingId ? "" : this.record.building || "";
      }

      this.updateElevatorOptions();

      if (this.elevatorSelect) {
        this.elevatorSelect.value = this.record.elevatorId ? String(this.record.elevatorId) : "";
      }
      if (this.manualElevatorInput) {
        this.manualElevatorInput.value = this.record.elevatorId ? "" : this.record.elevator || "";
      }

      if (this.noteField) {
        this.noteField.value = this.record.note || "";
      }

      const values = this.record.objectInfo || {};
      this.fieldInputs.forEach((input, code) => {
        const field = this.fields.find((item) => item.code === code);
        if (!field) {
          return;
        }
        const value = values[code];
        if (field.field_type === "boolean") {
          if (typeof value === "boolean") {
            input.value = value ? "true" : "false";
          } else {
            input.value = "";
          }
        } else if (value !== undefined && value !== null) {
          input.value = String(value);
        } else {
          input.value = "";
        }
      });
    }

    async refreshFromServer() {
      if (!this.catalogUrl || !this.db || !Offline) {
        return;
      }
      try {
        this.showStatus("Обновляем справочники…", "info");
        const response = await fetch(this.catalogUrl, {
          headers: { Accept: "application/json" },
          credentials: "same-origin",
        });
        if (!response.ok) {
          throw new Error(`Request failed with status ${response.status}`);
        }
        const payload = await response.json();
        await this.persistCataloguePayload(payload);
        this.catalog = {
          buildings: Array.isArray(payload.buildings) ? payload.buildings.slice() : [],
          elevators: Array.isArray(payload.elevators) ? payload.elevators.slice() : [],
        };
        this.fields = Array.isArray(payload.object_fields) ? payload.object_fields.slice() : this.fields;
        this.sortFields();
        this.catalogGeneratedAt = payload.generated_at || new Date().toISOString();
        this.renderCatalogOptions();
        this.renderFields();
        this.applyRecordValues();
        this.updateCatalogTimestamp();
        this.showStatus("Справочники обновлены.", "success");
      } catch (error) {
        console.warn("Failed to refresh catalogue snapshot", error);
        if (!this.catalog.buildings.length) {
          this.showError("Не удалось загрузить справочники. Проверьте подключение к интернету.");
        } else {
          this.showStatus("Не удалось обновить справочники. Используются сохранённые данные.", "warning");
        }
      }
    }

    async persistCataloguePayload(payload) {
      if (!this.db || !Offline) {
        return;
      }
      const buildings = Array.isArray(payload.buildings) ? payload.buildings : [];
      const elevators = Array.isArray(payload.elevators) ? payload.elevators : [];
      const fields = Array.isArray(payload.object_fields) ? payload.object_fields : [];
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
        if (payload.generated_at) {
          await Offline.putRecord(this.db, STORES.META, {
            key: "catalog_generated_at",
            value: payload.generated_at,
          });
        }
      } catch (error) {
        console.warn("Failed to store catalogue snapshot", error);
      }
    }

    handleSave() {
      if (!this.db || !Offline) {
        this.showError("Локальное хранилище недоступно. Сохранение невозможно.");
        return;
      }
      if (!this.record) {
        this.showError("Черновик не найден. Создайте новый аудит из списка.");
        return;
      }

      const result = this.collectFormValues();
      if (!result.ok) {
        this.showError(result.message || "Проверьте правильность заполнения формы.");
        return;
      }
      this.clearError();

      const now = new Date().toISOString();
      this.record.updatedAt = now;
      this.record.buildingId = result.buildingId;
      this.record.elevatorId = result.elevatorId;
      this.record.building = result.buildingLabel;
      this.record.elevator = result.elevatorLabel;
      this.record.note = result.note;
      this.record.objectInfo = result.objectInfo;
      if (result.catalogGeneratedAt) {
        this.record.catalogGeneratedAt = result.catalogGeneratedAt;
      }

      Offline.putRecord(this.db, STORES.AUDITS, this.record)
        .then(() => {
          this.showStatus("Черновик сохранён.");
        })
        .catch((error) => {
          console.error("Failed to persist offline record", error);
          this.showError("Не удалось сохранить данные. Попробуйте ещё раз.");
        });
    }

    collectFormValues() {
      const errors = [];
      const buildingIdRaw = this.buildingSelect ? this.buildingSelect.value : "";
      const manualBuilding = this.manualBuildingInput ? this.manualBuildingInput.value.trim() : "";
      const elevatorIdRaw = this.elevatorSelect ? this.elevatorSelect.value : "";
      const manualElevator = this.manualElevatorInput ? this.manualElevatorInput.value.trim() : "";
      const note = this.noteField ? this.noteField.value.trim() : "";

      const buildingId = buildingIdRaw ? Number(buildingIdRaw) : null;
      if (!buildingId && !manualBuilding) {
        errors.push("Укажите здание из справочника или заполните адрес вручную.");
      }

      const elevatorId = elevatorIdRaw ? Number(elevatorIdRaw) : null;

      const objectInfo = {};
      this.fieldInputs.forEach((input, code) => {
        const field = this.fields.find((item) => item.code === code);
        if (!field) {
          return;
        }
        const value = readFieldValue(field, input);
        if (value === undefined) {
          errors.push(`Заполните поле «${field.label || field.code}».`);
          return;
        }
        if (value !== null) {
          objectInfo[code] = value;
        }
      });

      if (errors.length) {
        return { ok: false, message: errors.join(" "), objectInfo: {} };
      }

      const buildingLabel = buildingId ? this.getBuildingLabel(buildingId) : manualBuilding;
      const elevatorLabel = elevatorId ? this.getElevatorLabel(elevatorId) : manualElevator;

      return {
        ok: true,
        buildingId,
        elevatorId,
        buildingLabel,
        elevatorLabel,
        note,
        objectInfo,
        catalogGeneratedAt: this.catalogGeneratedAt,
      };
    }

    getBuildingLabel(buildingId) {
      const building = (this.catalog.buildings || []).find((item) => Number(item.id) === buildingId);
      return building ? building.label || building.address || `Здание #${building.id}` : "";
    }

    getElevatorLabel(elevatorId) {
      const elevator = (this.catalog.elevators || []).find((item) => Number(item.id) === elevatorId);
      return elevator ? elevator.label || elevator.identifier || `Лифт #${elevator.id}` : "";
    }

    showError(message) {
      if (!this.errorBox) {
        return;
      }
      this.errorBox.textContent = message;
      this.errorBox.classList.remove("hidden");
    }

    clearError() {
      if (!this.errorBox) {
        return;
      }
      this.errorBox.textContent = "";
      this.errorBox.classList.add("hidden");
    }

    showStatus(message, variant = "success") {
      if (!this.statusBox) {
        return;
      }
      const classMap = {
        success: ["border-emerald-200", "bg-emerald-50", "text-emerald-800"],
        error: ["border-red-200", "bg-red-50", "text-red-700"],
        info: ["border-sky-200", "bg-sky-50", "text-sky-800"],
        warning: ["border-amber-200", "bg-amber-50", "text-amber-800"],
      };
      const classes = classMap[variant] || classMap.success;
      this.statusBox.className = "rounded-lg border px-4 py-3 text-sm font-medium";
      this.statusBox.classList.add(...classes);
      this.statusBox.textContent = message;
      this.statusBox.classList.remove("hidden");
    }

    updateCatalogTimestamp() {
      if (!this.catalogTimestamp) {
        return;
      }
      if (this.catalogGeneratedAt) {
        this.catalogTimestamp.textContent = formatDateTime(this.catalogGeneratedAt);
      } else {
        this.catalogTimestamp.textContent = "—";
      }
    }

    createEmptyRecord(clientId) {
      const now = new Date().toISOString();
      return {
        clientId,
        building: "",
        elevator: "",
        buildingId: null,
        elevatorId: null,
        plannedDate: null,
        note: "",
        createdAt: now,
        updatedAt: now,
        status: "draft",
        syncState: "pending",
        objectInfo: {},
      };
    }
  }

  function readJsonScript(elementId) {
    const element = document.getElementById(elementId);
    if (!element) {
      return null;
    }
    try {
      return JSON.parse(element.textContent || "null");
    } catch (error) {
      console.warn(`Failed to parse JSON from #${elementId}`, error);
      return null;
    }
  }

  function readFieldValue(field, input) {
    const raw = input.value;
    if (field.field_type === "boolean") {
      if (!raw) {
        return field.is_required ? undefined : null;
      }
      return raw === "true";
    }
    if (field.field_type === "number") {
      if (!raw.trim()) {
        return field.is_required ? undefined : null;
      }
      const value = Number(raw);
      if (Number.isNaN(value)) {
        return undefined;
      }
      return value;
    }
    if (field.field_type === "date") {
      if (!raw) {
        return field.is_required ? undefined : null;
      }
      return raw;
    }
    if (field.field_type === "choice") {
      if (!raw) {
        return field.is_required ? undefined : null;
      }
      return raw;
    }
    const text = raw.trim();
    if (field.is_required && !text) {
      return undefined;
    }
    return text ? text : null;
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
})(window);
