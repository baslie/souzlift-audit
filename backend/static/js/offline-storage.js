(function (window) {
  "use strict";

  const DB_NAME = "souzlift_offline";
  const DB_VERSION = 3;
  const STORES = Object.freeze({
    AUDITS: "offline_audits",
    BUILDINGS: "catalog_buildings",
    ELEVATORS: "catalog_elevators",
    OBJECT_FIELDS: "object_info_fields",
    META: "catalog_meta",
    RESPONSES: "offline_responses",
    ATTACHMENTS: "offline_attachments",
    CATALOG_ADDITIONS: "offline_catalog_additions",
  });

  function isSupported() {
    return typeof window.indexedDB !== "undefined";
  }

  function openDatabase() {
    return new Promise((resolve, reject) => {
      if (!isSupported()) {
        reject(new Error("IndexedDB не поддерживается в этом окружении."));
        return;
      }

      const request = window.indexedDB.open(DB_NAME, DB_VERSION);

      request.onerror = () => reject(request.error || new Error("Не удалось открыть IndexedDB."));

      request.onupgradeneeded = () => {
        const db = request.result;
        const upgradeTx = request.transaction;

        let auditStore;
        if (db.objectStoreNames.contains(STORES.AUDITS)) {
          auditStore = upgradeTx ? upgradeTx.objectStore(STORES.AUDITS) : null;
        } else {
          auditStore = db.createObjectStore(STORES.AUDITS, { keyPath: "clientId" });
        }
        if (auditStore) {
          if (!auditStore.indexNames.contains("updatedAt")) {
            auditStore.createIndex("updatedAt", "updatedAt", { unique: false });
          }
          if (!auditStore.indexNames.contains("status")) {
            auditStore.createIndex("status", "status", { unique: false });
          }
        }

        if (!db.objectStoreNames.contains(STORES.BUILDINGS)) {
          db.createObjectStore(STORES.BUILDINGS, { keyPath: "id" });
        }

        if (!db.objectStoreNames.contains(STORES.ELEVATORS)) {
          const elevatorStore = db.createObjectStore(STORES.ELEVATORS, { keyPath: "id" });
          elevatorStore.createIndex("by_building", "building_id", { unique: false });
        } else if (upgradeTx) {
          const elevatorStore = upgradeTx.objectStore(STORES.ELEVATORS);
          if (!elevatorStore.indexNames.contains("by_building")) {
            elevatorStore.createIndex("by_building", "building_id", { unique: false });
          }
        }

        if (!db.objectStoreNames.contains(STORES.OBJECT_FIELDS)) {
          db.createObjectStore(STORES.OBJECT_FIELDS, { keyPath: "code" });
        }

        if (!db.objectStoreNames.contains(STORES.META)) {
          db.createObjectStore(STORES.META, { keyPath: "key" });
        }

        let responseStore;
        if (db.objectStoreNames.contains(STORES.RESPONSES)) {
          responseStore = upgradeTx ? upgradeTx.objectStore(STORES.RESPONSES) : null;
        } else {
          responseStore = db.createObjectStore(STORES.RESPONSES, { keyPath: "id" });
        }
        if (responseStore) {
          if (!responseStore.indexNames.contains("by_client")) {
            responseStore.createIndex("by_client", "clientId", { unique: false });
          }
          if (!responseStore.indexNames.contains("by_question")) {
            responseStore.createIndex("by_question", "questionKey", { unique: false });
          }
        }

        let attachmentStore;
        if (db.objectStoreNames.contains(STORES.ATTACHMENTS)) {
          attachmentStore = upgradeTx ? upgradeTx.objectStore(STORES.ATTACHMENTS) : null;
        } else {
          attachmentStore = db.createObjectStore(STORES.ATTACHMENTS, { keyPath: "id" });
        }
        if (attachmentStore) {
          if (!attachmentStore.indexNames.contains("by_client")) {
            attachmentStore.createIndex("by_client", "clientId", { unique: false });
          }
          if (!attachmentStore.indexNames.contains("by_question")) {
            attachmentStore.createIndex("by_question", "questionKey", { unique: false });
          }
        }

        if (!db.objectStoreNames.contains(STORES.CATALOG_ADDITIONS)) {
          const catalogStore = db.createObjectStore(STORES.CATALOG_ADDITIONS, { keyPath: "id" });
          catalogStore.createIndex("by_client", "clientId", { unique: false });
          catalogStore.createIndex("by_type", "type", { unique: false });
        } else if (upgradeTx) {
          const catalogStore = upgradeTx.objectStore(STORES.CATALOG_ADDITIONS);
          if (!catalogStore.indexNames.contains("by_client")) {
            catalogStore.createIndex("by_client", "clientId", { unique: false });
          }
          if (!catalogStore.indexNames.contains("by_type")) {
            catalogStore.createIndex("by_type", "type", { unique: false });
          }
        }
      };

      request.onsuccess = () => {
        const database = request.result;
        database.onversionchange = () => {
          database.close();
        };
        resolve(database);
      };
    });
  }

  function withStore(db, storeName, mode, callback) {
    return new Promise((resolve, reject) => {
      try {
        const transaction = db.transaction(storeName, mode);
        const store = transaction.objectStore(storeName);
        const request = callback(store, transaction);
        transaction.oncomplete = () => resolve(request?.result ?? null);
        transaction.onerror = () => reject(transaction.error || new Error("Ошибка операции IndexedDB."));
      } catch (error) {
        reject(error);
      }
    });
  }

  function putRecord(db, storeName, record) {
    return withStore(db, storeName, "readwrite", (store) => store.put(record)).then(() => record);
  }

  function putRecords(db, storeName, records) {
    if (!Array.isArray(records) || records.length === 0) {
      return Promise.resolve([]);
    }
    return new Promise((resolve, reject) => {
      try {
        const transaction = db.transaction(storeName, "readwrite");
        const store = transaction.objectStore(storeName);
        records.forEach((record) => store.put(record));
        transaction.oncomplete = () => resolve(records);
        transaction.onerror = () => reject(transaction.error || new Error("Ошибка пакетной записи в IndexedDB."));
      } catch (error) {
        reject(error);
      }
    });
  }

  function getRecord(db, storeName, key) {
    return withStore(db, storeName, "readonly", (store) => store.get(key)).then((result) => result ?? null);
  }

  function getAllRecords(db, storeName) {
    return withStore(db, storeName, "readonly", (store) => store.getAll()).then((result) => {
      if (!Array.isArray(result)) {
        return [];
      }
      return result.slice();
    });
  }

  function getRecordsByIndex(db, storeName, indexName, value) {
    return withStore(db, storeName, "readonly", (store) => {
      const index = store.index(indexName);
      return index.getAll(value);
    }).then((result) => {
      if (!Array.isArray(result)) {
        return [];
      }
      return result.slice();
    });
  }

  function deleteRecords(db, storeName, keys) {
    if (!Array.isArray(keys) || keys.length === 0) {
      return Promise.resolve();
    }
    return new Promise((resolve, reject) => {
      try {
        const transaction = db.transaction(storeName, "readwrite");
        const store = transaction.objectStore(storeName);
        keys.forEach((key) => store.delete(key));
        transaction.oncomplete = () => resolve();
        transaction.onerror = () => reject(transaction.error || new Error("Ошибка удаления из IndexedDB."));
      } catch (error) {
        reject(error);
      }
    });
  }

  function deleteRecord(db, storeName, key) {
    return withStore(db, storeName, "readwrite", (store) => store.delete(key)).then(() => undefined);
  }

  function clearStore(db, storeName) {
    return withStore(db, storeName, "readwrite", (store) => store.clear()).then(() => undefined);
  }

  function generateClientId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    const random = Math.random().toString(16).slice(2);
    return `draft-${Date.now().toString(16)}-${random}`;
  }

  window.SouzliftOffline = Object.freeze({
    DB_NAME,
    DB_VERSION,
    STORES,
    isSupported,
    openDatabase,
    putRecord,
    putRecords,
    getRecord,
    getAllRecords,
    getRecordsByIndex,
    deleteRecord,
    deleteRecords,
    clearStore,
    generateClientId,
  });
})(window);
