export const $ = (s, root = document) => root.querySelector(s);
export const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
export const fmt = (n, d = 2) =>
  n == null
    ? "—"
    : Number(n).toLocaleString(undefined, { maximumFractionDigits: d });
export function bytes(n) {
  if (n == null) return "Not measured";
  const u = ["B", "KiB", "MiB", "GiB", "TiB"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) {
    n /= 1024;
    i++;
  }
  return fmt(n, i ? 2 : 0) + " " + u[i];
}
export const date = (n) => (n ? new Date(n * 1000).toLocaleString() : "—");
export const title = (heading, sub) =>
  `<div class="title-row"><div><h1>${esc(heading)}</h1><p class="sub">${esc(sub)}</p></div></div>`;
export const panel = (heading, body) =>
  `<section class="panel"><h2>${esc(heading)}</h2>${body}</section>`;
export const table = (heads, rows) =>
  `<div class="table-wrap"><table><thead><tr>${heads.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
export const metric = (label, value, note = "") =>
  `<div class="metric"><span class="label">${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></div>`;
export const pre = (obj) => `<pre>${esc(JSON.stringify(obj, null, 2))}</pre>`;
export const options = (all, selected) =>
  all
    .map(
      (e) =>
        `<option value="${esc(e.id)}" ${e.id === selected ? "selected" : ""}>${esc(e.name)} · ${esc(e.id)}</option>`,
    )
    .join("");
export async function api(path, body, method = "POST") {
  const response = await fetch("/api" + path, {
    method: body === undefined ? "GET" : method,
    headers: {
      "Content-Type": "application/json",
      "X-Evolution-Client": "dashboard",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response.json();
    throw Error(
      typeof error.detail === "string"
        ? error.detail
        : JSON.stringify(error.detail),
    );
  }
  return response.json();
}
export function toast(message, error = false) {
  const node = $("#toast");
  node.textContent = message;
  node.hidden = false;
  node.classList.toggle("error", error);
  setTimeout(() => (node.hidden = true), 7000);
}
export function bind(form, handler) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const buttons = [...form.querySelectorAll("button")];
    buttons.forEach((b) => (b.disabled = true));
    try {
      await handler(new FormData(form), form);
    } catch (error) {
      toast(error.message, true);
    } finally {
      buttons.forEach((b) => (b.disabled = false));
    }
  });
}
export function download(name, data, type = "application/json") {
  const url = URL.createObjectURL(new Blob([data], { type })),
    a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export const jobPanel = () =>
  panel(
    "Background operations",
    '<div class="lab-jobs" aria-live="polite">Loading operations…</div>',
  );
export async function startJob(kind, parameters = {}) {
  const job = await api("/lab/jobs", { kind, parameters });
  toast("Operation queued. Progress appears below.");
  return job;
}
export function followJobs() {
  document.querySelectorAll(".lab-jobs").forEach((node) => {
    const refresh = async () => {
      if (!node.isConnected) return;
      try {
        const jobs = await api("/lab/jobs");
        node.innerHTML =
          jobs
            .slice(0, 10)
            .map(
              (job) =>
                `<div class="job-row"><span><strong>${esc(job.kind.replaceAll("_", " "))}</strong> · ${esc(job.status)} · ${date(job.created)}</span><progress max="1" value="${job.progress}"></progress>${job.error ? `<p class="error note">${esc(job.error)}</p>` : ""}${job.status === "completed" && job.result?.filename?.startsWith(job.id + ".") ? `<a class="button" href="/api/lab/jobs/${job.id}/download" download>Download result</a>` : ""}${job.status === "completed" ? `<details><summary>Result details</summary>${pre(job.result)}</details>` : ""}</div>`,
            )
            .join("") || "<p>No background operations yet.</p>";
      } catch (error) {
        node.textContent = error.message;
      }
      if (node.isConnected) setTimeout(refresh, 1800);
    };
    refresh();
  });
}
export async function bookmark(eid, kind, reference = {}) {
  const name = await askText("Bookmark name");
  if (!name) return;
  await api("/lab/bookmarks", {
    experiment_id: eid || null,
    kind,
    reference,
    name,
    notes: "",
    tags: [],
  });
  toast("Bookmark saved");
}
export function dialog(html) {
  const node = document.createElement("dialog");
  node.className = "lab-dialog";
  node.innerHTML = html;
  document.body.append(node);
  node.addEventListener("close", () => node.remove());
  node.showModal();
  return node;
}
export function askText(label, value = "") {
  return new Promise((resolve) => {
    const node = dialog(`<h2>${esc(label)}</h2><form><label>${esc(label)}<input name="answer" value="${esc(value)}" maxlength="200" required></label><div class="actions"><button type="button" data-cancel>Cancel</button><button class="primary">Save</button></div></form>`);
    const form = $("form", node);
    form.onsubmit = (event) => {
      event.preventDefault();
      node.close(form.elements.answer.value.trim());
    };
    $("[data-cancel]", node).onclick = () => node.close();
    node.addEventListener("close", () => resolve(node.returnValue || null), { once: true });
    form.elements.answer.focus();
  });
}
