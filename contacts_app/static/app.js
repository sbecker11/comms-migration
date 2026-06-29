const pendingSaves = new Set();
let suppressGroupSaveAlerts = false;

function rowTemplate(kind) {
  const labelName = `${kind}_label`;
  const valueName = `${kind}_value`;
  const placeholders = {
    email: ["Label", "email@example.com"],
    phone: ["Label", "+1…"],
    url: ["Label", "https://…"],
  };
  const [labelPh, valuePh] = placeholders[kind];
  const inputType = kind === "email" ? "email" : kind === "phone" ? "tel" : "url";

  const row = document.createElement("div");
  row.className = "repeat-row";
  row.innerHTML = `
    <input type="text" name="${labelName}" placeholder="${labelPh}">
    <input type="${inputType}" name="${valueName}" placeholder="${valuePh}">
    <button type="button" class="btn-ghost remove-row">Remove</button>
  `;
  return row;
}

async function flushPendingSaves() {
  const pending = [...pendingSaves];
  if (pending.length === 0) return;
  await Promise.allSettled(pending);
}

function trackSave(promise) {
  pendingSaves.add(promise);
  promise.finally(() => pendingSaves.delete(promise));
  return promise;
}

function groupsFormData(row) {
  const formData = new FormData();
  row.querySelectorAll("input.group-checkbox:checked").forEach((checkbox) => {
    formData.append("groups", checkbox.value);
  });
  return formData;
}

function groupsSaveUrl(row) {
  const contactId = row.dataset.contactId;
  if (!contactId) throw new Error("missing contact id");
  return `/contacts/${encodeURIComponent(contactId)}/groups`;
}

async function saveRowGroups(row) {
  const formData = groupsFormData(row);
  const response = await fetch(groupsSaveUrl(row), {
    method: "POST",
    body: formData,
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new Error("save failed");

  const deleted = row.querySelector("input.group-checkbox[value='Is Deleted']");
  row.classList.toggle("row-deleted", deleted instanceof HTMLInputElement && deleted.checked);
}

function scrollToContactRow(rowId) {
  const row = document.getElementById(rowId);
  if (!row) return false;
  row.scrollIntoView({ block: "center" });
  row.classList.add("row-highlight");
  window.setTimeout(() => row.classList.remove("row-highlight"), 1500);
  return true;
}

function restoreListScroll() {
  const hashId = location.hash.startsWith("#contact-") ? location.hash.slice(1) : "";
  const storedId = sessionStorage.getItem("contactsScrollTo") || "";
  const rowId = hashId || storedId;
  if (!rowId) return;

  if (scrollToContactRow(rowId)) {
    sessionStorage.removeItem("contactsScrollTo");
    return;
  }

  // Row may be hidden after delete-deduping; scroll to the first visible row instead.
  const fallback = document.querySelector(".data-table-contacts .contact-row");
  if (fallback instanceof HTMLTableRowElement) {
    fallback.scrollIntoView({ block: "center" });
  }
  sessionStorage.removeItem("contactsScrollTo");
}

function setSaveStatus(message, isError = false) {
  const status = document.getElementById("save-status");
  if (!status) return;
  status.textContent = message;
  status.classList.toggle("save-status-error", isError);
}

function initListPage() {
  const table = document.querySelector(".data-table-contacts");
  if (!table) return;

  table.addEventListener("change", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) return;
    if (!target.classList.contains("group-checkbox")) return;

    const row = target.closest(".contact-row");
    if (!(row instanceof HTMLTableRowElement)) return;

    const checkbox = target;
    const previousChecked = !checkbox.checked;

    const savePromise = trackSave(
      (async () => {
        checkbox.disabled = true;
        try {
          await saveRowGroups(row);
        } catch {
          checkbox.checked = previousChecked;
          if (!suppressGroupSaveAlerts) {
            window.alert("Failed to save group change.");
          }
          throw new Error("save failed");
        } finally {
          checkbox.disabled = false;
        }
      })()
    );
    void savePromise;
  });

  table.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;

    const link = target.closest(".contact-detail-link");
    if (!(link instanceof HTMLAnchorElement)) return;

    event.preventDefault();
    event.stopPropagation();

    const row = link.closest(".contact-row");
    const rowId = row?.id || "";
    const href = link.href;

    void (async () => {
      suppressGroupSaveAlerts = true;
      try {
        await flushPendingSaves();
      } finally {
        suppressGroupSaveAlerts = false;
      }
      if (rowId) {
        sessionStorage.setItem("contactsScrollTo", rowId);
      }
      window.location.href = href;
    })();
  });
}

function initDetailPage() {
  const form = document.querySelector(".detail-form[data-autosave='true']");
  if (!(form instanceof HTMLFormElement)) return;

  let saveTimer = null;
  let dirty = false;

  async function saveDetailForm() {
    const formData = new FormData(form);
    setSaveStatus("Saving…");
    const response = await fetch(form.action, {
      method: "POST",
      body: formData,
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      setSaveStatus("Save failed", true);
      throw new Error("save failed");
    }
    dirty = false;
    setSaveStatus("Saved");
    window.setTimeout(() => {
      if (!dirty) setSaveStatus("");
    }, 1500);
  }

  function scheduleDetailSave() {
    dirty = true;
    window.clearTimeout(saveTimer);
    saveTimer = window.setTimeout(() => {
      const savePromise = trackSave(saveDetailForm());
      void savePromise.catch(() => {});
    }, 400);
  }

  form.addEventListener("input", scheduleDetailSave);
  form.addEventListener("change", scheduleDetailSave);

  document.querySelectorAll(".detail-nav-link").forEach((link) => {
    link.addEventListener("click", (event) => {
      if (!(link instanceof HTMLAnchorElement)) return;
      event.preventDefault();
      window.clearTimeout(saveTimer);
      const savePromise = dirty ? trackSave(saveDetailForm()) : Promise.resolve();
      void savePromise
        .then(() => flushPendingSaves())
        .then(() => {
          const rowId = form.dataset.contactDomId || "";
          if (rowId) {
            sessionStorage.setItem("contactsScrollTo", rowId);
          }
          window.location.href = link.href;
        })
        .catch(() => {
          window.alert("Failed to save changes before leaving this page.");
        });
    });
  });

  window.addEventListener("beforeunload", (event) => {
    if (!dirty && pendingSaves.size === 0) return;
    event.preventDefault();
    event.returnValue = "";
  });
}

document.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;

  if (target.classList.contains("add-row")) {
    const kind = target.dataset.target;
    const container = document.querySelector(`[data-repeatable="${kind}"]`);
    if (container && kind) {
      container.appendChild(rowTemplate(kind));
    }
  }

  if (target.classList.contains("remove-row")) {
    const row = target.closest(".repeat-row");
    const container = row?.parentElement;
    if (row && container) {
      if (container.querySelectorAll(".repeat-row").length > 1) {
        row.remove();
      } else {
        row.querySelectorAll("input").forEach((input) => {
          input.value = "";
        });
      }
      const form = target.closest(".detail-form[data-autosave='true']");
      if (form instanceof HTMLFormElement) {
        form.dispatchEvent(new Event("input", { bubbles: true }));
      }
    }
  }
});

document.addEventListener("DOMContentLoaded", () => {
  restoreListScroll();
  initListPage();
  initDetailPage();
});
