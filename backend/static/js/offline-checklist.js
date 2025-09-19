(function (window) {
  "use strict";

  const Offline = window.SouzliftOffline || null;
  const STORES = Offline
    ? Offline.STORES
    : {
        AUDITS: "offline_audits",
        RESPONSES: "offline_responses",
        ATTACHMENTS: "offline_attachments",
      };

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-checklist-form]").forEach((element) => {
      new OfflineChecklistManager(element);
    });
  });

  class OfflineChecklistManager {
    constructor(root) {
      this.root = root;
      this.form = root.checklistForm || null;
      this.clientId = resolveClientId(root);
      this.db = null;
      this.isSupported = Boolean(Offline && Offline.isSupported());
      this.isRestoring = false;
      this.pendingState = null;
      this.flushTimeout = null;

      if (this.form && this.clientId) {
        this.form.clientId = this.clientId;
        this.root.dataset.clientId = this.clientId;
      }

      this.handleReady = this.handleReady.bind(this);
      this.handleChange = this.handleChange.bind(this);
      this.handleSaveDraft = this.handleSaveDraft.bind(this);

      this.root.addEventListener("checklist:ready", this.handleReady);
      this.root.addEventListener("checklist:change", this.handleChange);
      this.root.addEventListener("checklist:save-draft", this.handleSaveDraft);
    }

    async handleReady(event) {
      if (!this.form) {
        this.form = this.root.checklistForm || null;
      }
      const detail = event?.detail || {};
      if (!this.clientId && detail.clientId) {
        this.clientId = detail.clientId;
      }
      if (!this.clientId) {
        this.clientId = resolveClientId(this.root);
      }
      if (this.form && this.clientId) {
        this.form.clientId = this.clientId;
        this.root.dataset.clientId = this.clientId;
      }

      if (!this.isSupported || !Offline) {
        if (this.form && typeof this.form.showStatus === "function") {
          this.form.showStatus(
            "Браузер не поддерживает локальное сохранение. Данные чек-листа не будут доступны офлайн."
          );
        }
        return;
      }

      try {
        await this.ensureDatabase();
        await this.restoreState();
      } catch (error) {
        console.error("Failed to restore offline checklist state", error);
        if (this.form && typeof this.form.showError === "function") {
          this.form.showError("Не удалось загрузить сохранённый черновик. Продолжайте работу с новой формой.");
        }
      }
    }

    async ensureDatabase() {
      if (this.db || !this.isSupported || !Offline) {
        return;
      }
      this.db = await Offline.openDatabase();
    }

    async restoreState() {
      if (!this.db || !this.form || !this.clientId || !Offline) {
        return;
      }

      const [responses, attachments] = await Promise.all([
        Offline.getRecordsByIndex(this.db, STORES.RESPONSES, "by_client", this.clientId),
        Offline.getRecordsByIndex(this.db, STORES.ATTACHMENTS, "by_client", this.clientId),
      ]);

      if (!responses.length && !attachments.length) {
        return;
      }

      this.isRestoring = true;
      if (this.form.questions && typeof this.form.questions.forEach === "function") {
        this.form.questions.forEach((question) => {
          clearQuestionAttachments(question);
          this.form.updateAttachmentInfo(question);
        });
      }
      this.form.totalAttachments = 0;

      responses.forEach((record) => {
        const question = findQuestion(this.form, record.questionId);
        if (!question) {
          return;
        }
        applyScore(this.form, question, record.score);
        if (question.commentField) {
          question.commentField.value = record.comment || "";
          question.commentField.dispatchEvent(new Event("input", { bubbles: true }));
        }
      });

      const attachmentPromises = attachments
        .slice()
        .sort((left, right) => {
          const leftTime = left.createdAt || left.updatedAt || "";
          const rightTime = right.createdAt || right.updatedAt || "";
          return leftTime.localeCompare(rightTime);
        })
        .map((record) => {
          const question = findQuestion(this.form, record.questionId);
          if (!question) {
            return Promise.resolve();
          }
          return this.restoreAttachment(question, record).catch((error) => {
            console.warn("Failed to restore attachment", error);
          });
        });

      await Promise.all(attachmentPromises);

      this.isRestoring = false;
      this.form.updateTotalCounter();
    }

    async restoreAttachment(question, record) {
      if (!this.form) {
        return;
      }
      const storedFile = record.file;
      if (!(storedFile instanceof Blob)) {
        return;
      }
      const fileName = record.name || storedFile.name || "attachment";
      const mimeType = record.mimeType || storedFile.type || "application/octet-stream";
      const lastModified = record.lastModified || Date.now();
      const file = storedFile instanceof File ? storedFile : new File([storedFile], fileName, { type: mimeType, lastModified });
      const previewUrl = await this.form.createPreviewUrl(file);
      const attachment = {
        id: record.attachmentId || extractStorageId(record.id),
        file,
        originalName: fileName,
        size: record.size || file.size,
        previewUrl,
      };
      question.attachments.push(attachment);
      this.form.renderAttachment(question, attachment);
      this.form.totalAttachments += 1;
      this.form.updateAttachmentInfo(question);
    }

    handleChange(event) {
      if (!this.db || !this.isSupported || this.isRestoring || !Offline) {
        return;
      }
      const detail = event?.detail ? { ...event.detail } : null;
      if (!detail) {
        return;
      }
      if (!detail.clientId && this.clientId) {
        detail.clientId = this.clientId;
      }
      if (!detail.clientId) {
        return;
      }
      this.clientId = detail.clientId;
      this.pendingState = detail;
      if (this.flushTimeout) {
        window.clearTimeout(this.flushTimeout);
      }
      this.flushTimeout = window.setTimeout(() => {
        this.flushChanges().catch((error) => {
          console.error("Failed to persist offline state", error);
          if (this.form && typeof this.form.showError === "function") {
            this.form.showError("Не удалось сохранить данные формы локально. Попробуйте ещё раз позже.");
          }
        });
      }, 300);
    }

    handleSaveDraft() {
      this.flushChanges(true).catch((error) => {
        console.error("Failed to persist checklist draft", error);
        if (this.form && typeof this.form.showError === "function") {
          this.form.showError("Не удалось сохранить черновик локально.");
        }
      });
    }

    async flushChanges(force = false) {
      if (this.flushTimeout) {
        window.clearTimeout(this.flushTimeout);
        this.flushTimeout = null;
      }
      let state = this.pendingState;
      this.pendingState = null;
      if (!state && force && this.form && typeof this.form.collectState === "function") {
        state = this.form.collectState();
        if (state && this.clientId && !state.clientId) {
          state.clientId = this.clientId;
        }
      }
      if (!state) {
        return;
      }
      await this.persistState(state);
    }

    async persistState(state) {
      if (!this.db || !Offline) {
        return;
      }
      const clientId = state.clientId || this.clientId;
      if (!clientId) {
        return;
      }
      this.clientId = clientId;

      const now = new Date().toISOString();
      let auditRecord = await Offline.getRecord(this.db, STORES.AUDITS, clientId);
      if (!auditRecord) {
        auditRecord = {
          clientId,
          createdAt: now,
          updatedAt: now,
          status: "draft",
          syncState: "pending",
          objectInfo: {},
        };
      }
      auditRecord.updatedAt = now;
      auditRecord.totalAttachments = state.totalAttachments || 0;
      auditRecord.hasChecklistDraft = true;
      await Offline.putRecord(this.db, STORES.AUDITS, auditRecord);

      const [existingResponses, existingAttachments] = await Promise.all([
        Offline.getRecordsByIndex(this.db, STORES.RESPONSES, "by_client", clientId),
        Offline.getRecordsByIndex(this.db, STORES.ATTACHMENTS, "by_client", clientId),
      ]);

      const responseMap = new Map();
      existingResponses.forEach((record) => {
        responseMap.set(record.questionId, record);
      });

      const attachmentMap = new Map();
      existingAttachments.forEach((record) => {
        attachmentMap.set(record.id, record);
      });

      const responseIdsToKeep = new Set();
      const attachmentIdsToKeep = new Set();

      const questions = Array.isArray(state.questions) ? state.questions : [];
      for (const question of questions) {
        if (!question) {
          continue;
        }
        const questionId = Number(question.id);
        if (!Number.isFinite(questionId)) {
          continue;
        }
        const recordId = `${clientId}:${questionId}`;
        responseIdsToKeep.add(recordId);
        const existingResponse = responseMap.get(questionId);
        const responseRecord = {
          id: recordId,
          clientId,
          questionId,
          questionKey: recordId,
          questionType: question.type || existingResponse?.questionType || "score",
          maxScore: Number.isFinite(question.maxScore) ? Number(question.maxScore) : null,
          score: typeof question.score === "number" ? question.score : null,
          comment: typeof question.comment === "string" ? question.comment : "",
          requiresComment: Boolean(question.requiresComment),
          createdAt: existingResponse?.createdAt || existingResponse?.updatedAt || now,
          updatedAt: now,
        };
        await Offline.putRecord(this.db, STORES.RESPONSES, responseRecord);

        const attachments = Array.isArray(question.attachments) ? question.attachments : [];
        for (const attachment of attachments) {
          if (!attachment || !attachment.id || !attachment.file) {
            continue;
          }
          const storageId = `${clientId}:${attachment.id}`;
          attachmentIdsToKeep.add(storageId);
          const existingAttachment = attachmentMap.get(storageId);
          const file = attachment.file;
          const record = {
            id: storageId,
            clientId,
            questionId,
            questionKey: recordId,
            attachmentId: attachment.id,
            name: attachment.originalName || attachment.name || file.name || "attachment",
            size: Number.isFinite(attachment.size) ? attachment.size : file.size || 0,
            mimeType: file.type || existingAttachment?.mimeType || "",
            lastModified: file.lastModified || existingAttachment?.lastModified || Date.now(),
            file,
            createdAt: existingAttachment?.createdAt || existingAttachment?.updatedAt || now,
            updatedAt: now,
          };
          await Offline.putRecord(this.db, STORES.ATTACHMENTS, record);
        }
      }

      const responsesToDelete = existingResponses
        .filter((record) => !responseIdsToKeep.has(record.id))
        .map((record) => record.id);
      if (responsesToDelete.length) {
        await Offline.deleteRecords(this.db, STORES.RESPONSES, responsesToDelete);
      }

      const attachmentsToDelete = existingAttachments
        .filter((record) => !attachmentIdsToKeep.has(record.id))
        .map((record) => record.id);
      if (attachmentsToDelete.length) {
        await Offline.deleteRecords(this.db, STORES.ATTACHMENTS, attachmentsToDelete);
      }
    }
  }

  function resolveClientId(root) {
    if (root && root.dataset && root.dataset.clientId) {
      return root.dataset.clientId;
    }
    try {
      const params = new URLSearchParams(window.location.search || "");
      const raw = params.get("client_id");
      return raw ? raw.trim() : "";
    } catch (error) {
      console.warn("Failed to read client_id from URL", error);
      return "";
    }
  }

  function findQuestion(form, questionId) {
    if (!form || !form.questions) {
      return null;
    }
    const numericId = Number(questionId);
    return form.questions.get(Number.isFinite(numericId) ? numericId : questionId) || null;
  }

  function applyScore(form, question, score) {
    if (!form || !question) {
      return;
    }
    if (typeof score !== "number") {
      question.selectedScore = null;
      if (question.scoreButtons && question.scoreButtons.length) {
        question.scoreButtons.forEach((button) => {
          form.setOptionActive(button, false);
        });
      }
      form.updateCommentRequirement(question);
      return;
    }
    const scoreValue = String(score);
    const targetButton = Array.isArray(question.scoreButtons)
      ? question.scoreButtons.find((button) => (button.dataset.scoreValue || "") === scoreValue)
      : null;
    if (targetButton) {
      form.handleScoreSelection(question, targetButton, score);
    } else {
      question.selectedScore = score;
      form.updateCommentRequirement(question);
    }
  }

  function clearQuestionAttachments(question) {
    if (!question) {
      return;
    }
    if (Array.isArray(question.attachments)) {
      question.attachments.forEach((attachment) => {
        if (attachment && attachment.previewUrl) {
          URL.revokeObjectURL(attachment.previewUrl);
        }
      });
      question.attachments.length = 0;
    }
    if (question.attachmentList) {
      question.attachmentList.innerHTML = "";
    }
  }

  function extractStorageId(value) {
    if (!value || typeof value !== "string") {
      return "";
    }
    const parts = value.split(":");
    return parts.length ? parts[parts.length - 1] : value;
  }
})(window);
