(function (window) {
  "use strict";

  const BASE_OPTION_CLASSES = [
    "border-slate-200",
    "bg-white",
    "text-slate-700",
    "hover:border-sky-400",
    "hover:text-slate-900",
  ];
  const ACTIVE_OPTION_CLASSES = [
    "border-sky-500",
    "bg-sky-600",
    "text-white",
    "shadow-sm",
  ];
  const HIGHLIGHT_COMMENT_CLASSES = ["border-amber-400", "focus:border-amber-500", "focus:ring-amber-200"];
  const COMMENT_MISSING_CLASSES = ["ring-2", "ring-amber-500", "ring-offset-1"];
  const DISABLED_TRIGGER_CLASSES = ["opacity-50", "cursor-not-allowed"];
  const DEFAULT_COMMENT_BORDER = "border-slate-300";
  const MAX_CANVAS_EDGE = 1600;

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-checklist-form]").forEach((element) => {
      new ChecklistForm(element);
    });
  });

  class ChecklistForm {
    constructor(root) {
      this.root = root;
      this.clientId = resolveClientId(root);
      if (this.clientId) {
        this.root.dataset.clientId = this.clientId;
      }
      this.maxPerResponse = parseInt(root.dataset.maxPerResponse || "10", 10);
      this.maxPerAudit = parseInt(root.dataset.maxPerAudit || "100", 10);
      this.maxSizeBytes = parseInt(root.dataset.maxSize || String(8 * 1024 * 1024), 10);

      this.totalAttachments = 0;
      this.questions = new Map();
      this.questionOrder = [];
      this.pendingChangeFrame = null;

      this.statusBox = root.querySelector("[data-status]");
      this.errorBox = root.querySelector("[data-error]");
      this.totalCounter = root.querySelector("[data-total-attachments]");
      this.saveButton = root.querySelector('[data-action="save-draft"]');

      this.root.checklistForm = this;

      this.init();
    }

    init() {
      this.initQuestions();
      this.dispatchReadyEvent();

      if (this.saveButton) {
        this.saveButton.addEventListener("click", (event) => {
          event.preventDefault();
          this.handleSaveDraft();
        });
      }
    }

    initQuestions() {
      const questionElements = this.root.querySelectorAll("[data-question]");
      questionElements.forEach((element) => {
        const id = parseInt(element.dataset.questionId || "", 10);
        if (!Number.isFinite(id)) {
          return;
        }
        const question = {
          id,
          element,
          type: element.dataset.questionType || "score",
          maxScore: parseInt(element.dataset.maxScore || "0", 10) || 0,
          requiresCommentAlways: element.dataset.requiresComment === "true",
          requiresCommentOnReduced: element.dataset.commentOnReduced === "true",
          selectedScore: null,
          commentField: element.querySelector("[data-comment-field]"),
          commentIndicator: element.querySelector("[data-comment-indicator]"),
          attachmentInput: element.querySelector("[data-attachment-input]"),
          attachmentTrigger: element.querySelector("[data-attachment-trigger]"),
          attachmentInfo: element.querySelector("[data-attachment-info]"),
          attachmentList: element.querySelector("[data-attachment-list]"),
          scoreButtons: Array.from(element.querySelectorAll("[data-score-option]")),
          attachments: [],
          commentIndicatorDefaultText: null,
          commentRequired: false,
          commentMissing: false,
        };

        if (question.commentIndicator) {
          question.commentIndicatorDefaultText = question.commentIndicator.textContent || "Комментарий обязателен";
        }

        this.questions.set(id, question);
        this.questionOrder.push(id);
        this.bindQuestion(question);
        this.updateCommentRequirement(question);
        this.updateAttachmentInfo(question);
      });
      this.updateTotalCounter();
    }

    bindQuestion(question) {
      if (question.scoreButtons.length) {
        question.scoreButtons.forEach((button) => {
          button.addEventListener("click", (event) => {
            event.preventDefault();
            const valueRaw = button.dataset.scoreValue || "";
            const value = valueRaw === "" ? null : Number(valueRaw);
            if (value !== null && !Number.isFinite(value)) {
              return;
            }
            this.handleScoreSelection(question, button, value);
          });
          this.setOptionActive(button, false);
        });
      }

      if (question.commentField) {
        question.commentField.addEventListener("input", () => {
          this.clearError();
          const requiresComment = question.commentField.hasAttribute("required");
          const value = question.commentField.value.trim();
          if (requiresComment && !value) {
            this.setCommentMissingState(question, true);
          } else {
            this.setCommentMissingState(question, false);
          }
          this.notifyChange(question);
        });
      }

      if (question.attachmentTrigger && question.attachmentInput) {
        question.attachmentTrigger.addEventListener("click", (event) => {
          event.preventDefault();
          question.attachmentInput.click();
        });
        question.attachmentInput.addEventListener("change", async () => {
          await this.handleAttachmentSelection(question, question.attachmentInput.files);
          question.attachmentInput.value = "";
        });
      }
    }

    handleScoreSelection(question, button, value) {
      question.selectedScore = value;
      question.scoreButtons.forEach((optionButton) => {
        this.setOptionActive(optionButton, optionButton === button);
      });
      this.updateCommentRequirement(question);
      const requiresComment = question.commentField && question.commentField.hasAttribute("required");
      if (requiresComment && question.commentField) {
        const valueText = question.commentField.value.trim();
        if (!valueText) {
          this.setCommentMissingState(question, true);
        }
      }
      this.clearError();
      this.notifyChange(question);
    }

    setOptionActive(button, isActive) {
      if (!button) {
        return;
      }
      if (isActive) {
        BASE_OPTION_CLASSES.forEach((cls) => button.classList.remove(cls));
        ACTIVE_OPTION_CLASSES.forEach((cls) => button.classList.add(cls));
        button.setAttribute("data-selected", "true");
      } else {
        ACTIVE_OPTION_CLASSES.forEach((cls) => button.classList.remove(cls));
        BASE_OPTION_CLASSES.forEach((cls) => {
          if (!button.classList.contains(cls)) {
            button.classList.add(cls);
          }
        });
        button.setAttribute("data-selected", "false");
      }
    }

    updateCommentRequirement(question) {
      const requiresComment =
        question.requiresCommentAlways ||
        (question.requiresCommentOnReduced &&
          typeof question.selectedScore === "number" &&
          question.maxScore > 0 &&
          question.selectedScore < question.maxScore);

      if (question.commentField) {
        if (requiresComment) {
          question.commentField.setAttribute("required", "required");
          question.commentField.classList.add(...HIGHLIGHT_COMMENT_CLASSES);
          question.commentField.classList.remove(DEFAULT_COMMENT_BORDER);
        } else {
          question.commentField.removeAttribute("required");
          question.commentField.classList.remove(...HIGHLIGHT_COMMENT_CLASSES);
          if (!question.commentField.classList.contains(DEFAULT_COMMENT_BORDER)) {
            question.commentField.classList.add(DEFAULT_COMMENT_BORDER);
          }
        }
      }
      question.commentRequired = requiresComment;
      const shouldKeepMissing = question.commentMissing && requiresComment;
      this.setCommentMissingState(question, shouldKeepMissing);
    }

    async handleAttachmentSelection(question, fileList) {
      if (!fileList || !fileList.length) {
        return;
      }
      const files = Array.from(fileList);
      let addedAny = false;

      for (const file of files) {
        if (question.attachments.length >= this.maxPerResponse) {
          this.showError(`Нельзя добавить больше ${this.maxPerResponse} фото к этому вопросу.`);
          break;
        }
        if (this.totalAttachments >= this.maxPerAudit) {
          this.showError(`Достигнут общий лимит ${this.maxPerAudit} фото для одного аудита.`);
          break;
        }
        if (!file.type || !file.type.startsWith("image/")) {
          this.showError("Можно загружать только изображения.");
          continue;
        }

        try {
          const attachment = await this.prepareAttachment(file);
          question.attachments.push(attachment);
          this.totalAttachments += 1;
          this.renderAttachment(question, attachment);
          this.updateAttachmentInfo(question);
          this.updateTotalCounter();
          this.clearError();
          addedAny = true;
        } catch (error) {
          if (error && typeof error.message === "string" && error.message === "size_limit") {
            this.showError(
              `Не удалось добавить «${file.name}»: размер файла должен быть меньше ${this.formatSize(this.maxSizeBytes)}.`
            );
          } else {
            console.error("Failed to process attachment", error);
            this.showError(`Не удалось обработать файл «${file.name}». Попробуйте другое изображение.`);
          }
        }
      }

      if (addedAny) {
        this.notifyChange(question);
      }
    }

    async prepareAttachment(file) {
      const processedFile = await this.compressImageIfNeeded(file);
      const previewUrl = await this.createPreviewUrl(processedFile);
      return {
        id: this.generateAttachmentId(),
        file: processedFile,
        originalName: file.name || processedFile.name || "Фото",
        size: processedFile.size,
        previewUrl,
      };
    }

    async compressImageIfNeeded(file) {
      if (!file.type || !file.type.startsWith("image/")) {
        throw new Error("invalid_type");
      }
      if (file.size <= this.maxSizeBytes) {
        return file;
      }

      const bitmap = await this.loadImageBitmap(file);
      const dimensions = this.calculateDimensions(bitmap.width, bitmap.height);
      const canvas = document.createElement("canvas");
      canvas.width = dimensions.width;
      canvas.height = dimensions.height;
      const context = canvas.getContext("2d");
      if (!context) {
        if (typeof bitmap.close === "function") {
          bitmap.close();
        }
        throw new Error("canvas_context");
      }
      context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      if (typeof bitmap.close === "function") {
        bitmap.close();
      }

      let quality = 0.85;
      let blob = await this.canvasToBlob(canvas, quality);
      while (blob && blob.size > this.maxSizeBytes && quality > 0.5) {
        quality -= 0.1;
        blob = await this.canvasToBlob(canvas, quality);
      }

      if (!blob) {
        throw new Error("canvas_blob");
      }

      if (blob.size > this.maxSizeBytes) {
        if (file.size <= this.maxSizeBytes) {
          return file;
        }
        throw new Error("size_limit");
      }

      const finalName = this.renameFile(file.name, "jpg");
      return new File([blob], finalName, { type: blob.type || "image/jpeg", lastModified: Date.now() });
    }

    calculateDimensions(width, height) {
      const largestEdge = Math.max(width, height);
      if (largestEdge <= MAX_CANVAS_EDGE) {
        return { width, height };
      }
      const ratio = MAX_CANVAS_EDGE / largestEdge;
      return {
        width: Math.round(width * ratio),
        height: Math.round(height * ratio),
      };
    }

    async loadImageBitmap(file) {
      if (window.createImageBitmap) {
        return window.createImageBitmap(file);
      }
      return new Promise((resolve, reject) => {
        const image = new Image();
        const url = URL.createObjectURL(file);
        image.onload = () => {
          URL.revokeObjectURL(url);
          resolve(image);
        };
        image.onerror = (event) => {
          URL.revokeObjectURL(url);
          reject(event instanceof Error ? event : new Error("image_load"));
        };
        image.src = url;
      });
    }

    canvasToBlob(canvas, quality) {
      return new Promise((resolve, reject) => {
        canvas.toBlob(
          (blob) => {
            if (blob) {
              resolve(blob);
            } else {
              reject(new Error("canvas_blob"));
            }
          },
          "image/jpeg",
          quality
        );
      });
    }

    async createPreviewUrl(file) {
      return URL.createObjectURL(file);
    }

    renderAttachment(question, attachment) {
      if (!question.attachmentList) {
        return;
      }
      const item = document.createElement("div");
      item.className = "overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm";

      const image = document.createElement("img");
      image.src = attachment.previewUrl;
      image.alt = attachment.originalName;
      image.className = "h-32 w-full object-cover";

      const infoBar = document.createElement("div");
      infoBar.className = "flex items-center justify-between gap-2 px-3 py-2 text-xs text-slate-600";

      const name = document.createElement("span");
      name.className = "truncate";
      name.textContent = `${attachment.originalName} · ${this.formatSize(attachment.size)}`;

      const removeButton = document.createElement("button");
      removeButton.type = "button";
      removeButton.textContent = "Удалить";
      removeButton.className =
        "inline-flex items-center rounded-md border border-red-200 px-2 py-0.5 text-[11px] font-semibold text-red-600 transition hover:bg-red-50 focus:outline-none focus:ring-2 focus:ring-red-400 focus:ring-offset-1";
      removeButton.addEventListener("click", (event) => {
        event.preventDefault();
        this.removeAttachment(question, attachment, item);
      });

      infoBar.appendChild(name);
      infoBar.appendChild(removeButton);

      item.appendChild(image);
      item.appendChild(infoBar);

      question.attachmentList.appendChild(item);
    }

    removeAttachment(question, attachment, item) {
      const index = question.attachments.indexOf(attachment);
      if (index !== -1) {
        question.attachments.splice(index, 1);
        this.totalAttachments = Math.max(0, this.totalAttachments - 1);
        this.updateAttachmentInfo(question);
        this.updateTotalCounter();
      }
      if (attachment.previewUrl) {
        URL.revokeObjectURL(attachment.previewUrl);
      }
      if (item && item.parentNode) {
        item.parentNode.removeChild(item);
      }
      this.notifyChange(question);
    }

    updateAttachmentInfo(question) {
      if (question.attachmentInfo) {
        question.attachmentInfo.textContent = `${question.attachments.length} / ${this.maxPerResponse}`;
      }
    }

    updateTotalCounter() {
      if (this.totalCounter) {
        this.totalCounter.textContent = String(this.totalAttachments);
      }
      this.refreshAttachmentTriggers();
    }

    handleSaveDraft() {
      const missingComments = this.validateRequiredComments();
      if (missingComments > 0) {
        const message =
          missingComments === 1
            ? "Заполните обязательный комментарий перед сохранением."
            : `Заполните обязательные комментарии (${missingComments}) перед сохранением.`;
        this.showError(message);
        return;
      }

      const state = this.collectState();
      this.dispatchFormChange(state);
      this.root.dispatchEvent(
        new CustomEvent("checklist:save-draft", {
          detail: state,
          bubbles: true,
        })
      );

      this.showStatus(
        "Данные формы подготовлены для сохранения. Синхронизация будет добавлена на следующем этапе."
      );
    }

    generateAttachmentId() {
      const random = Math.random().toString(16).slice(2, 10);
      return `att-${Date.now().toString(16)}-${random}`;
    }

    renameFile(name, extension) {
      const safeName = (name || "attachment").split(".").slice(0, -1).join(".") || "attachment";
      return `${safeName}.${extension}`;
    }

    formatSize(bytes) {
      if (!Number.isFinite(bytes)) {
        return "0 Б";
      }
      if (bytes >= 1024 * 1024) {
        return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
      }
      if (bytes >= 1024) {
        return `${Math.round(bytes / 1024)} КБ`;
      }
      return `${bytes} Б`;
    }

    showError(message) {
      if (this.errorBox) {
        this.errorBox.textContent = message;
        this.errorBox.classList.remove("hidden");
      }
      if (this.statusBox) {
        this.statusBox.classList.add("hidden");
      }
    }

    showStatus(message) {
      if (this.statusBox) {
        this.statusBox.textContent = message;
        this.statusBox.classList.remove("hidden");
      }
      if (this.errorBox) {
        this.errorBox.classList.add("hidden");
      }
    }

    clearError() {
      if (this.errorBox) {
        this.errorBox.classList.add("hidden");
      }
    }

    setCommentMissingState(question, isMissing) {
      const shouldMark = Boolean(isMissing);
      question.commentMissing = shouldMark;
      if (question.commentField) {
        if (shouldMark) {
          COMMENT_MISSING_CLASSES.forEach((cls) => question.commentField.classList.add(cls));
        } else {
          COMMENT_MISSING_CLASSES.forEach((cls) => question.commentField.classList.remove(cls));
        }
      }
      this.syncCommentIndicator(question);
    }

    syncCommentIndicator(question) {
      if (!question.commentIndicator) {
        return;
      }

      if (question.commentMissing) {
        question.commentIndicator.textContent = "Заполните обязательный комментарий";
        question.commentIndicator.classList.remove("hidden");
        return;
      }

      if (question.commentRequired) {
        const text = question.commentIndicatorDefaultText || "Комментарий обязателен";
        question.commentIndicator.textContent = text;
        question.commentIndicator.classList.remove("hidden");
      } else {
        const text = question.commentIndicatorDefaultText || "Комментарий обязателен";
        question.commentIndicator.textContent = text;
        question.commentIndicator.classList.add("hidden");
      }
    }

    refreshAttachmentTriggers() {
      const globalLimitReached = this.totalAttachments >= this.maxPerAudit;
      this.questions.forEach((question) => {
        const trigger = question.attachmentTrigger;
        if (!trigger) {
          return;
        }
        const perQuestionLimitReached = question.attachments.length >= this.maxPerResponse;
        const shouldDisable = perQuestionLimitReached || globalLimitReached;
        trigger.disabled = shouldDisable;
        trigger.setAttribute("aria-disabled", shouldDisable ? "true" : "false");
        DISABLED_TRIGGER_CLASSES.forEach((cls) => {
          if (shouldDisable) {
            trigger.classList.add(cls);
          } else {
            trigger.classList.remove(cls);
          }
        });
        if (perQuestionLimitReached) {
          trigger.title = `Лимит ${this.maxPerResponse} фото для вопроса достигнут.`;
        } else if (globalLimitReached) {
          trigger.title = `Достигнут общий лимит ${this.maxPerAudit} фото для аудита.`;
        } else {
          trigger.removeAttribute("title");
        }
      });
    }

    validateRequiredComments() {
      let missingCount = 0;
      this.questions.forEach((question) => {
        if (!question.commentField || !question.commentRequired) {
          this.setCommentMissingState(question, false);
          return;
        }
        const value = question.commentField.value.trim();
        if (!value) {
          missingCount += 1;
          this.setCommentMissingState(question, true);
        } else {
          this.setCommentMissingState(question, false);
        }
      });
      return missingCount;
    }

    getQuestionState(question) {
      if (!question) {
        return null;
      }
      const commentValue = question.commentField ? question.commentField.value : "";
      return {
        id: question.id,
        type: question.type,
        maxScore: question.maxScore,
        score: question.selectedScore,
        comment: commentValue,
        requiresComment: question.commentRequired,
        attachments: question.attachments.map((attachment) => ({
          id: attachment.id,
          name: attachment.originalName,
          size: attachment.size,
          file: attachment.file,
          previewUrl: attachment.previewUrl,
        })),
      };
    }

    collectState() {
      return {
        clientId: this.clientId,
        totalAttachments: this.totalAttachments,
        questions: this.questionOrder
          .map((questionId) => this.questions.get(questionId))
          .filter((question) => Boolean(question))
          .map((question) => this.getQuestionState(question))
          .filter((questionState) => Boolean(questionState)),
      };
    }

    notifyChange(question) {
      const questionState = this.getQuestionState(question);
      if (questionState) {
        this.root.dispatchEvent(
          new CustomEvent("checklist:question-change", {
            detail: questionState,
            bubbles: true,
          })
        );
      }
      this.scheduleFormChangeDispatch();
    }

    scheduleFormChangeDispatch() {
      if (this.pendingChangeFrame !== null) {
        return;
      }
      const requestFrame =
        typeof window.requestAnimationFrame === "function"
          ? window.requestAnimationFrame.bind(window)
          : (callback) => window.setTimeout(callback, 16);
      this.pendingChangeFrame = requestFrame(() => {
        this.pendingChangeFrame = null;
        this.dispatchFormChange();
      });
    }

    dispatchFormChange(forcedState) {
      const state = forcedState || this.collectState();
      this.root.dispatchEvent(
        new CustomEvent("checklist:change", {
          detail: state,
          bubbles: true,
        })
      );
    }

    dispatchReadyEvent() {
      const state = this.collectState();
      this.root.dispatchEvent(
        new CustomEvent("checklist:ready", {
          detail: state,
          bubbles: true,
        })
      );
      this.dispatchFormChange(state);
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
})(window);
