import {
  $,
  esc,
  fmt,
  bytes,
  title,
  panel,
  table,
  metric,
  options,
  api,
  toast,
  bind,
  followJobs,
  bookmark,
  askText,
} from "./lab-common.js?v=2.0.1-r2";
import {
  experimentsPage,
  bindExperiments,
  journalPage,
  bindJournal,
  backupsPage,
  bindBackups,
  bookmarksPage,
  bindBookmarks,
  repeatDialog,
} from "./lab-organize.js?v=2.0.1-r2";
import {
  familyPage,
  bindFamily,
  weightsPage,
  bindWeights,
} from "./lab-genetics.js?v=2.0.1-r2";
import {
  chartsPage,
  bindCharts,
  replayPage,
  bindReplay,
  timelinePage,
  bindTimeline,
} from "./lab-history.js?v=2.0.1-r2";
let draftLoaded = false,
  draftSaving = Promise.resolve();
export async function loadDraft() {
  if (draftLoaded) return null;
  draftLoaded = true;
  const sets = await api("/lab/baskets");
  const saved = sets.find((b) => b.id === "draft");
  if (saved)
    return saved.entrants.map(({ experiment_id, network_id, available }) => ({
      experiment_id,
      network_id,
      available,
    }));
  try {
    return JSON.parse(localStorage.getItem("evolution-basket") || "[]");
  } catch {
    return [];
  }
}
export function persistDraft(entrants) {
  const clean = entrants.map(({ experiment_id, network_id }) => ({
    experiment_id,
    network_id,
  }));
  localStorage.setItem("evolution-basket", JSON.stringify(clean));
  draftSaving = draftSaving
    .catch(() => {})
    .then(() =>
      api(
        "/lab/baskets/draft",
        { name: "Current tournament basket", entrants: clean },
        "PUT",
      ),
    )
    .catch((e) =>
      toast(
        "Basket saved in this browser; workspace save failed: " + e.message,
        true,
      ),
    );
  return draftSaving;
}
async function resourcesPage() {
  const s = await api("/settings"),
    p = s.disk_policy;
  return (
    title(
      "System Resources",
      "Linux measurements distinguish overall machine use from Engine worker activity.",
    ) +
    panel(
      "Live resource measurements",
      '<div id="lab-resources" aria-live="polite">Sampling resources…</div>',
    ) +
    panel(
      "Disk-space warnings and safe pause",
      `<form id="disk-policy-form"><div class="form-grid"><label>Threshold units<select name="unit"><option value="gib" ${p.unit === "gib" ? "selected" : ""}>Free GiB</option><option value="percent" ${p.unit === "percent" ? "selected" : ""}>Percent free</option></select></label><label>Information threshold<input name="warning" type="number" min="0" step="any" value="${p.warning}"></label><label>Stop scheduling threshold<input name="critical" type="number" min="0" step="any" value="${p.critical}"></label><label>Safe worker pause threshold<input name="pause" type="number" min="0" step="any" value="${p.pause}"></label><label><input name="enabled" type="checkbox" ${p.enabled ? "checked" : ""}>Enable disk-space protection</label></div><p class="small">Thresholds must descend. Critical capacity blocks new workers. At the safety threshold, workers pause at committed generation boundaries. No research is deleted. Free storage, then resume paused experiments.</p><button>Save disk thresholds</button></form>`,
    )
  );
}
function bindResources() {
  const node = $("#lab-resources");
  const refresh = async () => {
    if (!node.isConnected) return;
    try {
      const r = await api("/lab/resources");
      node.innerHTML = `<div class="metrics">${metric("OVERALL CPU", fmt(r.overall_cpu_percent, 1) + "%", "Across " + r.cpu_count + " logical cores; first sample may be unavailable")}${metric("ENGINE WORKER CPU", fmt(r.worker_cpu_percent, 1) + "%", "100% equals one full CPU core")}${metric("MEMORY USED", bytes(r.memory_used_bytes), "Available " + bytes(r.memory_available_bytes))}${metric("WORKERS", r.workers.length + " / " + r.max_workers, r.queued + " queued")}</div><div class="legend"><span>Compute throughput estimate: ${fmt(r.aggregate_compute_generations_per_second)} gen/s</span><span>Load: ${r.load_average.map((x) => fmt(x)).join(" / ")}</span><span>Database: ${bytes(r.database_bytes)}</span><span>Free disk: ${bytes(r.disk.free_bytes)} (${fmt(r.disk.free_percent)}%)</span></div><p class="small">${esc(r.throughput_note)}</p>${r.disk.level === "normal" ? "<p>Disk capacity is within configured thresholds.</p>" : `<p class="note error">Disk state: ${esc(r.disk.level)}. ${esc(r.disk.guidance)}</p>`}${table(
        ["Experiment", "Process ID", "CPU", "Resident memory"],
        r.workers.map(
          (w) =>
            `<tr><td>${esc(w.name)}<br>${w.id}</td><td>${w.pid ?? "Unavailable"}</td><td>${fmt(w.cpu_percent, 1)}%</td><td>${bytes(w.rss_bytes)}</td></tr>`,
        ),
      )}${
        r.failures.length
          ? `<h3>Recent worker failures</h3>${table(
              ["Experiment", "Failure"],
              r.failures.map(
                (f) =>
                  `<tr><td>${esc(f.name)}</td><td>${esc(f.error)}</td></tr>`,
              ),
            )}`
          : ""
      }`;
    } catch (e) {
      node.textContent = e.message;
    }
    if (node.isConnected) setTimeout(refresh, 2000);
  };
  refresh();
  bind($("#disk-policy-form"), async (d) => {
    await api(
      "/settings",
      {
        disk_policy: {
          enabled: !!d.get("enabled"),
          unit: d.get("unit"),
          warning: Number(d.get("warning")),
          critical: Number(d.get("critical")),
          pause: Number(d.get("pause")),
        },
      },
      "PUT",
    );
    toast("Disk thresholds saved");
  });
}
export async function labRoute(route, parts, all) {
  if (["family", "weights", "replay", "charts"].includes(route) && parts[1] && !all.some(e => e.id === parts[1]))
    all.push(await api("/experiments/" + encodeURIComponent(parts[1])));
  if (route === "experiments" || route === "storage")
    return experimentsPage(route === "storage");
  if (route === "backups") return backupsPage();
  if (route === "resources") return resourcesPage();
  if (route === "bookmarks") return bookmarksPage();
  const populated = all.find(e => e.generation > 0)?.id;
  if (route === "family") return familyPage(all, parts[1] || populated, parts[2]);
  if (route === "weights") return weightsPage(all, parts[1] || populated, parts[2]);
  if (route === "replay") return replayPage(all, parts[1] || populated, parts[2]);
  if (route === "charts" || route === "compare")
    return chartsPage(all, parts[1] || populated, route === "compare");
  if (route === "journal") return journalPage(parts[1]);
  if (route === "timeline") return timelinePage(parts[1]);
  return null;
}
export async function labEnhance(route, parts, context) {
  if (route === "experiments" || route === "storage") await bindExperiments();
  if (route === "backups") bindBackups();
  if (route === "resources") bindResources();
  if (route === "bookmarks") await bindBookmarks();
  if (route === "family") await bindFamily();
  if (route === "weights") await bindWeights();
  if (route === "replay") await bindReplay();
  if (route === "charts" || route === "compare") await bindCharts();
  if (route === "journal") bindJournal(parts[1]);
  if (route === "timeline") await bindTimeline(parts[1]);
  if (route === "experiment") {
    const eid = parts[1],
      tabs = $("#main .tabs");
    if (tabs)
      tabs.insertAdjacentHTML(
        "beforeend",
        `<a href="#journal/${eid}">Journal & report</a><a href="#charts/${eid}">Interactive charts</a><a href="#replay/${eid}">Replay</a><a href="#timeline/${eid}">Timeline</a><a href="#family/${eid}/${parts[3] || 1}">Family tree</a>`,
      );
    $("#main .title-row").insertAdjacentHTML(
      "afterend",
      `<p class="actions"><button id="repeat-current">Repeat experiment…</button><button id="mark-current">Bookmark experiment</button></p>`,
    );
    $("#repeat-current").onclick = () =>
      repeatDialog(eid).catch((e) => toast(e.message, true));
    $("#mark-current").onclick = () =>
      bookmark(eid, "experiment").catch((e) => toast(e.message, true));
    if (parts[2] === "inspector" && parts[3]) {
      $("#main .title-row").insertAdjacentHTML(
        "afterend",
        `<p><button id="mark-network">Bookmark this network</button> <a class="button" href="#weights/${eid}/${parts[3]}">Compare genetic weights</a></p>`,
      );
      $("#mark-network").onclick = () =>
        bookmark(eid, "network", { network_id: Number(parts[3]) }).catch((e) =>
          toast(e.message, true),
        );
    }
  }
  if (route === "create") {
    const f = $("#create-form"),
      presets = await api("/lab/retention-presets");
    f.elements.seed.type = "text";
    f.elements.seed.inputMode = "numeric";
    f.elements.seed.maxLength = 19;
    f.elements.seed.removeAttribute("max");
    if (context.seedText) f.elements.seed.value = context.seedText;
    f.elements.history_stride
      .closest(".form-grid")
      .insertAdjacentHTML(
        "beforebegin",
        `<label>New-run retention preset<select id="retention-preset"><option value="custom">Keep current settings</option><option value="detailed">Detailed — each population snapshot</option><option value="balanced">Balanced — each tenth population</option><option value="compact">Compact — each hundredth population</option></select></label><p class="small">${esc(presets.notice)}</p><p id="retention-estimate" class="small"></p>`,
      );
    f.elements.history_stride
      .closest(".form-grid")
      .insertAdjacentHTML(
        "beforeend",
        `<label>Archived checkpoints retained<input name="checkpoint_retention" type="number" min="1" max="10000" value="${context.config.execution.checkpoint_retention}"></label>`,
      );
    const estimate = () => {
      const c = context.config,
        size = Number(f.elements.size.value) || c.population.size,
        layers = f.elements.layers.value.split(",").map(Number),
        count = layers
          .slice(1)
          .reduce((sum, n, i) => sum + n * (layers[i] + 1), 0),
        generations = Number(f.elements.generations.value) || 1,
        stride = Number(f.elements.history_stride.value) || 1;
      $("#retention-estimate").textContent =
        `Parameter payload estimate: ${bytes((size + generations * (size - (Number(f.elements.elites.value) || 20))) * count * 8)} before mutation metadata and shared database overhead; about ${Math.ceil(generations / stride)} full snapshots. All unique genomes remain, so sparse retention mainly reduces fitness and population history.`;
    };
    $("#retention-preset").onchange = (e) => {
      const preset = presets.presets[e.target.value];
      if (preset)
        for (const [key, val] of Object.entries(preset))
          f.elements[key].value = val;
      estimate();
    };
    f.addEventListener("change", estimate);
    estimate();
  }
  if (route === "tournament") {
    const sets = await api("/lab/baskets");
    $("#basket").insertAdjacentHTML(
      "beforebegin",
      `<div class="toolbar"><label>Saved baskets<select id="saved-basket"><option value="">Choose saved basket</option>${sets
        .filter((b) => b.id !== "draft")
        .map(
          (b) =>
            `<option value="${b.id}">${esc(b.name)} (${b.entrants.length})</option>`,
        )
        .join(
          "",
        )}</select></label><button type="button" id="save-basket">Save named basket</button><button type="button" id="load-basket">Load basket</button></div><p class="small">Current basket persists in this workspace and in this browser. Unavailable entries must be removed before a tournament.</p>`,
    );
    $("#save-basket").onclick = async () => {
      try {
        const name = await askText("Basket name");
        if (!name) return;
        const id = "basket-" + crypto.randomUUID();
        await api(
          "/lab/baskets/" + id,
          {
            name,
            entrants: context
              .getBasket()
              .map(({ experiment_id, network_id }) => ({
                experiment_id,
                network_id,
              })),
          },
          "PUT",
        );
        const option = document.createElement("option");
        option.value = id;
        option.textContent = name;
        $("#saved-basket").append(option);
        sets.push({ id, name, entrants: structuredClone(context.getBasket()) });
        toast("Named basket saved");
      } catch (e) {
        toast(e.message, true);
      }
    };
    $("#load-basket").onclick = () => {
      const saved = sets.find((b) => b.id === $("#saved-basket").value);
      if (saved) {
        context.setBasket(structuredClone(saved.entrants));
        persistDraft(context.getBasket());
        context.refreshBasket();
        toast("Basket loaded");
      }
    };
    if (parts[1]) {
      const button = document.querySelector(
        `[data-load-tournament="${Number(parts[1])}"]`,
      );
      button?.click();
    }
    document.addEventListener("click", tournamentButtons, { once: true });
    function tournamentButtons() {
      /* Delegated reorder controls are installed once below. */
    }
  }
  followJobs();
}
