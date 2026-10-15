import {
  $,
  esc,
  fmt,
  bytes,
  date,
  title,
  panel,
  table,
  metric,
  pre,
  options,
  api,
  toast,
  bind,
  download,
  jobPanel,
  followJobs,
  startJob,
  bookmark,
  dialog,
} from "./lab-common.js?v=2.0.1-r2";
let selection = new Map();
export async function experimentsPage(storage = false) {
  const tags = await api("/lab/tags");
  const suggestions = `<datalist id="existing-tags">${tags.map(t => `<option value="${esc(t.name)}">${t.count} experiments</option>`).join("")}</datalist>`;
  let head = title(
    storage ? "Storage Manager" : "Experiments",
    storage
      ? "Physical workspace usage and clearly labeled logical experiment estimates."
      : "Search saved research, organize experiments, and work with a selection.",
  );
  if (storage) {
    const s = await api("/lab/storage"),
      last = s.measurements[0];
    head +=
      `<div class="metrics">${metric("DATABASE", bytes(s.database_bytes), "Physical SQLite file")}${metric("WAL / SHARED MEMORY", bytes(s.wal_bytes) + " / " + bytes(s.shm_bytes), "Separate physical files")}${metric("WORKSPACE", bytes(last?.workspace_bytes), "Measured " + date(last?.time))}${metric("FREE DISK", bytes(s.free_disk_bytes), "Current available capacity")}</div>` +
      panel(
        "Storage accounting",
        `<div class="legend"><span>${fmt(s.counts.experiments, 0)} experiments</span>${s.states.map(r => `<span>${r.n} ${esc(r.status)}</span>`).join("")}<span>${fmt(s.counts.genomes, 0)} genomes</span><span>${fmt(s.counts.retained_population_snapshots, 0)} snapshots</span><span>${fmt(s.counts.checkpoints, 0)} checkpoints</span><span>Reusable pages: ${bytes(s.estimated_reusable_bytes)}</span></div><p>Cached logical estimates: ${bytes(s.cached_logical_bytes)} across ${s.estimate_coverage} experiments. Shared accounting remainder: ${bytes(s.physical_minus_estimate_bytes)}.</p><p class="small">${esc(s.overhead_note)} Deletion frees reusable pages; SQLite usually keeps its physical size until Reclaim Storage.</p><p>Last verified backup: ${s.last_backup ? date(s.last_backup.verified) : "None"}. ${s.last_backup?.recent ? "Recent archive available." : "Create and verify a backup before deleting research."}</p><div class="actions"><button id="measure-storage">Refresh measurements</button><button id="reclaim-storage">Reclaim Storage</button><a class="button" href="#backups">Backups</a></div><details><summary>Measured growth history</summary>${table(
          ["Measured", "Database + WAL + SHM", "Workspace", "Free disk"],
          s.measurements.map(
            (r) =>
              `<tr><td>${date(r.time)}</td><td>${bytes(r.physical_bytes)}</td><td>${bytes(r.workspace_bytes)}</td><td>${bytes(r.free_bytes)}</td></tr>`,
          ),
        )}</details>`,
      );
  }
  return (
    head + suggestions +
    panel(
      "Find experiments",
      `<form id="lab-search"><div class="form-grid"><label>Search names, IDs, notes, tags or config<input name="q" maxlength="500"></label><label>Status<select name="status"><option value="">Any state</option>${["created", "queued", "running", "paused", "pausing", "completed", "failed", "cancelled", "imported"].map((s) => `<option>${s}</option>`).join("")}</select></label><label>Tags (all required, comma separated)<input name="tags" list="existing-tags"></label><label>Research project<input name="group"></label><label>Exact seed<input name="seed" inputmode="numeric" maxlength="19"></label><label>Environment<select name="environment"><option value="">All</option><option>rps</option><option>target</option></select></label><label>Origin<select name="origin"><option value="">All</option><option value="native">Native</option><option value="imported">Imported</option></select></label><label>Created after<input name="since" type="date"></label><label>Created before<input name="until" type="date"></label><label>Minimum generation<input name="min_generation" type="number" min="0"></label><label>Maximum generation<input name="max_generation" type="number" min="0"></label><label>Minimum observed maximum fitness<input name="min_fitness" type="number" step="any"></label><label>Maximum observed maximum fitness<input name="max_fitness" type="number" step="any"></label><label>Minimum estimated MiB<input name="min_size" type="number" min="0" step="any"></label><label>Maximum estimated MiB<input name="max_size" type="number" min="0" step="any"></label><label>Sort<select name="sort">${["date", "name", "generation", "size", "status"].map((s) => `<option ${s === (storage ? "size" : "date") ? "selected" : ""}>${s}</option>`).join("")}</select></label><label>Direction<select name="descending"><option value="true">Descending</option><option value="false">Ascending</option></select></label></div><p><button class="primary">Apply filters</button></p><details><summary>Existing tags and experiment counts</summary><div class="legend">${tags.map(t => `<span>${esc(t.name)} · ${t.count}</span>`).join("") || "No tags saved yet."}</div></details></form>`,
    ) +
    panel(
      "Selected research",
      `<p id="selection-count">No experiments selected.</p><div class="toolbar"><label>Add tags<input id="bulk-add-tags" list="existing-tags" placeholder="replication, pilot"></label><label>Remove tags<input id="bulk-remove-tags" list="existing-tags"></label><label>Research project<input id="bulk-group"></label><button id="bulk-tags">Apply to selection</button><button id="clear-selection">Clear selection</button></div><div class="actions"><button id="bulk-export">Export selected summaries</button><button id="bulk-backup">Back up whole workspace</button><button id="bulk-delete" class="danger">Preview deletion</button></div><p class="small">Summary exports are not restorable backups. Backup always preserves the whole workspace.</p>`,
    ) +
    panel(
      "Results",
      '<div id="lab-results">Loading experiments…</div><div class="actions"><button id="search-prev">Previous page</button><button id="search-next">Next page</button><button id="select-page">Select this page</button></div>',
    ) +
    jobPanel()
  );
}
export async function bindExperiments() {
  let offset = 0,
    items = [],
    total = 0;
  const form = $("#lab-search");
  const updateSelection = () => {
    $("#selection-count").textContent =
      `${selection.size} experiments selected · ${bytes([...selection.values()].reduce((n, e) => n + (e.logical_bytes || 0), 0))} estimated logical storage (unmeasured entries excluded)`;
  };
  const load = async () => {
    const d = new FormData(form),
      query = new URLSearchParams({ limit: 50, offset });
    for (const [key, value] of d) {
      if (!value) continue;
      if (key === "tags") {
        value
          .split(",")
          .map((x) => x.trim())
          .filter(Boolean)
          .forEach((tag) => query.append("tags", tag));
      } else if (["since", "until"].includes(key))
        query.set(
          key,
          Date.parse(value) / 1000 + (key === "until" ? 86399 : 0),
        );
      else if (["min_size", "max_size"].includes(key))
        query.set(key, Math.round(Number(value) * 2 ** 20));
      else query.set(key, value);
    }
    $("#lab-results").textContent = "Searching saved experiments…";
    const result = await api("/lab/search?" + query);
    items = result.items;
    total = result.total;
    $("#lab-results").innerHTML =
      `<p>${fmt(total, 0)} matching experiments · ${offset + 1}–${Math.min(offset + 50, total)}. ${esc(result.size_note)}</p>` +
      table(
        [
          "Select",
          "Experiment",
          "State / generation",
          "Tags / project",
          "Logical size",
          "Research",
        ],
        items.map(
          (e) =>
            `<tr><td><input type="checkbox" data-select-experiment="${e.id}" aria-label="Select ${esc(e.name)}" ${selection.has(e.id) ? "checked" : ""}></td><td><a href="#experiment/${e.id}/monitor">${esc(e.name)}</a><br><code>${e.id}</code><br>Seed ${e.seed_text}<br><small>${date(e.created)}</small></td><td>${esc(e.status)}<br>${fmt(e.generation, 0)} generations</td><td>${e.tags.map(esc).join(", ") || "—"}<br>${esc(e.research_group)}</td><td>${bytes(e.logical_bytes)}<details><summary>Size details</summary>${e.storage ? pre({ ...e.storage, measured: date(e.storage_measured), generation: e.estimated_at_generation }) : "Refresh measurements in Storage Manager."}</details></td><td><a href="#journal/${e.id}">Journal</a> · <a href="#charts/${e.id}">Charts</a> · <a href="#timeline/${e.id}">Timeline</a><br><button data-repeat="${e.id}">Repeat…</button></td></tr>`,
        ),
      );
    $("#search-prev").disabled = offset === 0;
    $("#search-next").disabled = offset + 50 >= total;
    document.querySelectorAll("[data-select-experiment]").forEach((box) =>
      box.addEventListener("change", () => {
        const e = items.find((e) => e.id === box.dataset.selectExperiment);
        box.checked ? selection.set(e.id, e) : selection.delete(e.id);
        updateSelection();
      }),
    );
    document
      .querySelectorAll("[data-repeat]")
      .forEach((b) =>
        b.addEventListener("click", () => repeatDialog(b.dataset.repeat)),
      );
    updateSelection();
  };
  bind(form, async () => {
    offset = 0;
    await load();
  });
  $("#search-prev").onclick = () => {
    offset = Math.max(0, offset - 50);
    load().catch((e) => toast(e.message, true));
  };
  $("#search-next").onclick = () => {
    offset += 50;
    load().catch((e) => toast(e.message, true));
  };
  $("#select-page").onclick = () => {
    items.forEach((e) => selection.set(e.id, e));
    load();
  };
  $("#clear-selection").onclick = () => {
    selection.clear();
    load();
  };
  const ids = () => {
    if (!selection.size) throw Error("Select at least one experiment.");
    return [...selection.keys()];
  };
  $("#bulk-tags").onclick = async () => {
    try {
      const split = (id) =>
        $(id)
          .value.split(",")
          .map((s) => s.trim())
          .filter(Boolean);
      await startJob("tags", {
        ids: ids(),
        add: split("#bulk-add-tags"),
        remove: split("#bulk-remove-tags"),
        group: $("#bulk-group").value || null,
      });
    } catch (e) {
      toast(e.message, true);
    }
  };
  $("#bulk-export").onclick = () => {
    try {
      startJob("export", { ids: ids(), kind: "summary" }).catch((e) =>
        toast(e.message, true),
      );
    } catch (e) {
      toast(e.message, true);
    }
  };
  $("#bulk-backup").onclick = () =>
    startJob("backup").catch((e) => toast(e.message, true));
  $("#bulk-delete").onclick = () => {
    try {
      deleteDialog(ids()).catch((e) => toast(e.message, true));
    } catch (e) {
      toast(e.message, true);
    }
  };
  if ($("#measure-storage"))
    $("#measure-storage").onclick = () =>
      startJob("storage_measure").catch((e) => toast(e.message, true));
  if ($("#reclaim-storage"))
    $("#reclaim-storage").onclick = () => {
      const node = dialog(
        `<h2>Reclaim SQLite storage</h2><p>Pause all workers first. This preserves records and rebuilds the database to reclaim free pages. It requires temporary free disk space and exclusive maintenance access.</p><form method="dialog"><button value="cancel">Cancel</button><button value="confirm">Reclaim Storage</button></form>`,
      );
      node.addEventListener("close", () => {
        if (node.returnValue === "confirm")
          startJob("reclaim").catch((e) => toast(e.message, true));
      });
    };
  await load();
}
export async function repeatDialog(eid) {
  const e = await api("/experiments/" + eid);
  const node = dialog(
    `<h2>Repeat ${esc(e.name)}</h2><p>Source ${esc(eid)} · exact seed <code>${e.seed_text}</code></p><form id="repeat-form"><label>Seed<select name="seed_mode"><option value="same">Same seed — reproduce this configuration</option><option value="fresh">New backend-generated seed</option></select></label><label>After creating<select name="start"><option value="false">Leave ready for inspection</option><option value="true">Queue immediately</option></select></label><p>New experiment identity and repetition provenance are stored. The source run is preserved.</p><div class="actions"><button type="button" data-close>Cancel</button><button class="primary">Create repeat</button></div></form>`,
  );
  $("[data-close]", node).onclick = () => node.close();
  bind($("#repeat-form", node), async (d) => {
    const r = await api(`/lab/experiments/${eid}/repeat`, {
      seed_mode: d.get("seed_mode"),
      start: d.get("start") === "true",
    });
    node.close();
    location.hash = "experiment/" + r.id + "/monitor";
    toast("Repeat created · exact seed " + r.seed_text);
  });
}
async function deleteDialog(ids) {
  const p = await api("/lab/delete-preview", { ids });
  const recent = p.backup?.recent;
  const node = dialog(
    `<h2>Delete ${ids.length} selected experiment${ids.length === 1 ? "" : "s"}?</h2><p class="error note">This removes the selected experiments, genomes, history, checkpoints and annotations. ${esc(p.policy)}</p>${table(
      ["Experiment / ID", "State", "Estimated logical size"],
      p.items.map(
        (e) =>
          `<tr><td>${esc(e.name)}<br><code>${e.id}</code></td><td>${esc(e.status)}${e.protected ? " · PROTECTED" : ""}</td><td>${bytes(e.storage.logical_bytes)}</td></tr>`,
      ),
    )}<details><summary>Dependent records</summary>${pre({ analyses: p.analyses, baskets: p.baskets, rows: p.items.map((e) => ({ id: e.id, ...e.storage.counts })) })}</details><p>Backup: ${recent ? "verified " + date(p.backup.verified) : "no recent verified backup"}.</p><button id="backup-before-delete">Create backup first</button><form id="delete-confirm"><p><label><input type="checkbox" name="confirm" required>I confirm these ${ids.length} identities and their permanent deletion.</label></p>${recent ? "" : '<p><label><input type="checkbox" name="no_backup" required>I understand that I am deleting without a recent verified backup.</label></p>'}<label><input type="checkbox" name="remove_analyses">Also remove dependent tournament results (otherwise preserve results with source-deleted markers)</label><p class="actions"><button type="button" data-close>Cancel</button><button class="danger" ${p.items.some((e) => e.protected) ? "disabled" : ""}>Delete selected research</button></p></form>`,
  );
  $("[data-close]", node).onclick = () => node.close();
  $("#backup-before-delete", node).onclick = async () => {
    await startJob("backup");
    node.close();
    toast(
      "Backup queued. Wait for completion, then open deletion preview again.",
    );
  };
  bind($("#delete-confirm", node), async (d) => {
    await startJob("delete", {
      ids,
      confirm: ids,
      acknowledge_no_backup: !!d.get("no_backup"),
      remove_analyses: !!d.get("remove_analyses"),
    });
    node.close();
    selection.clear();
  });
}
export async function journalPage(eid) {
  const [e, n] = await Promise.all([
    api("/experiments/" + eid),
    api(`/lab/experiments/${eid}/notes`),
  ]);
  return (
    title("Research journal", e.name + " · " + eid) +
    panel(
      "User annotations",
      `<p class="small">Separate from scientific configuration. Editable while a run is active. Last updated ${date(n.updated)}.</p><form id="journal-form" data-eid="${eid}">${Object.entries(
        n.content,
      )
        .map(
          ([key, value]) =>
            `<label>${esc(key.replaceAll("_", " "))}<textarea name="${key}" rows="3" maxlength="16000">${esc(value)}</textarea></label>`,
        )
        .join(
          "",
        )}<p class="actions"><button class="primary">Save journal</button><a class="button" href="/api/lab/experiments/${eid}/notes/export" download>Export notes</a><button type="button" id="bookmark-experiment">Bookmark experiment</button></p></form>`,
    ) +
    panel(
      "Reports and provenance",
      `<p>Generate an offline HTML report with annotations, recorded measurements, configuration, exact seed, champion, charts, bookmarks and limitations.</p><form id="report-form" data-eid="${eid}"><label><input type="checkbox" name="include_weights">Include champion weights (may be large)</label><p><label><input type="checkbox" name="include_lineage">Include bounded lineage details</label></p><button>Generate Research Report</button></form><p><a href="#timeline/${eid}">Event timeline</a> · <a href="#charts/${eid}">Interactive fitness charts</a> · <a href="#replay/${eid}">Evolution replay</a></p>`,
    ) +
    jobPanel()
  );
}
export function bindJournal(eid) {
  bind($("#journal-form"), async (d) => {
    await api(
      `/lab/experiments/${eid}/notes`,
      { content: Object.fromEntries(d) },
      "PUT",
    );
    toast("Journal saved");
  });
  bind($("#report-form"), (d) =>
    startJob("report", {
      experiment_id: eid,
      include_weights: !!d.get("include_weights"),
      include_lineage: !!d.get("include_lineage"),
    }),
  );
  $("#bookmark-experiment").onclick = () =>
    bookmark(eid, "experiment").catch((e) => toast(e.message, true));
}
export async function backupsPage() {
  const result = await api("/lab/backups");
  return (
    title(
      "Backups",
      "Consistent SQLite snapshots, checksums and verification.",
    ) +
    panel(
      "Preserve your workspace",
      `<p>Includes experiments, immutable genomes, history, recovery state, annotations and saved analyses. External historical databases remain explicit dependencies. Archives never overwrite earlier backups.</p><button id="create-backup" class="primary">Create workspace backup</button><button id="refresh-backups">Refresh backup list</button><div class="note">${esc(result.restore_instructions)}</div><p class="small">Restore uses a new folder through the local command line. It never overwrites the workspace served by this dashboard.</p>`,
    ) +
    panel(
      "Saved archives",
      table(
        ["Created", "Version", "Size", "Dependencies", "Verification", "Actions"],
        result.items.map(
          (b) =>
            `<tr><td>${date(b.created)}<br><code>${b.id}</code></td><td>Engine ${esc(b.manifest.application_version)}<br>Schema ${b.manifest.schema_version}</td><td>${bytes(b.size)}</td><td>${b.manifest.self_contained ? "Self-contained SQLite snapshot" : `${b.manifest.external_dependencies.length} external files required`}<details><summary>Manifest</summary>${pre(b.manifest)}</details></td><td>${date(b.verified)}${!b.available ? " · Archive unavailable" : ""}</td><td><button data-verify-backup="${b.id}">Verify archive</button>${b.available ? `<a class="button" href="/api/lab/backups/${b.id}/download" download>Download</a>` : ""}</td></tr>`,
        ),
      ),
    ) +
    jobPanel()
  );
}
export function bindBackups() {
  $("#create-backup").onclick = () =>
    startJob("backup").catch((e) => toast(e.message, true));
  $("#refresh-backups").onclick = async () => {
    const main = $("main"), button = $("#refresh-backups");
    button.disabled = true;
    try {
      const html = await backupsPage();
      if (!button.isConnected) return;
      main.innerHTML = html;
      bindBackups();
      followJobs();
    } catch (e) { toast(e.message, true); button.disabled = false; }
  };
  document
    .querySelectorAll("[data-verify-backup]")
    .forEach(
      (b) =>
        (b.onclick = () =>
          startJob("verify_backup", {
            backup_id: b.dataset.verifyBackup,
          }).catch((e) => toast(e.message, true))),
    );
}
export async function bookmarksPage() {
  return (
    title(
      "Research bookmarks",
      "Named pointers to experiments, observations, networks, branches and tournaments.",
    ) +
    panel(
      "Saved references",
      '<form id="bookmark-search" class="toolbar"><label>Search names, notes or tags<input name="q"></label><button>Search bookmarks</button></form><div id="bookmark-results"></div><button id="bookmark-next">More bookmarks</button>',
    )
  );
}
export async function bindBookmarks() {
  let offset = 0;
  const load = async (append = false) => {
    const q = $("#bookmark-search input").value,
      result = await api(
        "/lab/bookmarks?" + new URLSearchParams({ q, offset }),
      );
    const html =
      result.items
        .map((b) => {
          const r = b.reference;
          const href =
            b.kind === "tournament"
              ? `#tournament/${r.analysis_id}`
              : b.kind === "branch"
                ? `#family/${b.experiment_id}/${r.network_id}`
                : b.kind === "experiment"
                  ? `#experiment/${b.experiment_id}/monitor`
              : r.network_id
                ? `#experiment/${b.experiment_id}/inspector/${r.network_id}`
                : r.generation != null
                  ? `#replay/${b.experiment_id}/${r.generation}`
                  : `#timeline/${b.experiment_id}`;
          return `<article class="bookmark-card"><h3><a href="${href}">${esc(b.name)}</a></h3><p>${esc(b.notes)}</p><p class="small">${esc(b.kind)} · ${esc(b.experiment_id)} · ${b.tags.map(esc).join(", ")}</p><details><summary>Edit annotation</summary><form data-bookmark-id="${b.id}"><label>Name<input name="name" value="${esc(b.name)}" maxlength="200" required></label><label>Notes<textarea name="notes" maxlength="16000">${esc(b.notes)}</textarea></label><label>Tags<input name="tags" value="${esc(b.tags.join(", "))}"></label><p><button>Save bookmark</button></p></form></details></article>`;
        })
        .join("") || "<p>No bookmarks match this search.</p>";
    if (append) $("#bookmark-results").insertAdjacentHTML("beforeend", html);
    else $("#bookmark-results").innerHTML = html;
    result.items.forEach((b) =>
      bind($(`[data-bookmark-id="${b.id}"]`), async (d) => {
        await api(
          "/lab/bookmarks/" + b.id,
          {
            experiment_id: b.experiment_id,
            kind: b.kind,
            reference: b.reference,
            name: d.get("name"),
            notes: d.get("notes"),
            tags: d
              .get("tags")
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean),
          },
          "PUT",
        );
        toast("Bookmark updated");
      }),
    );
    $("#bookmark-next").disabled = result.next_offset == null;
    offset = result.next_offset;
  };
  bind($("#bookmark-search"), async () => {
    offset = 0;
    await load();
  });
  $("#bookmark-next").onclick = () =>
    load(true).catch((e) => toast(e.message, true));
  await load();
}
