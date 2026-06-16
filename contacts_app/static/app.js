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
    }
  }
});
