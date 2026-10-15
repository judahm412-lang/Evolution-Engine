import {
  $,
  esc,
  fmt,
  date,
  title,
  panel,
  table,
  pre,
  options,
  api,
  toast,
  bind,
  download,
  jobPanel,
  startJob,
  bookmark,
} from "./lab-common.js?v=2.0.1-r2";
const names = {
  mean: "Mean fitness",
  maximum: "Maximum fitness",
  minimum: "Minimum fitness",
  self_mean: "Self-play mean",
  bot_mean: "Bot mean",
  genetic_rms: "Genetic RMS",
  behavioral_hamming: "Policy Hamming",
  mutation_mean: "Mean mutations",
  unique_policies: "Unique policies",
};
const colors = [
  "#14775d",
  "#a18737",
  "#805ead",
  "#337bb4",
  "#c16645",
  "#5e8581",
  "#805140",
  "#697620",
  "#b45c80",
];
export async function chartsPage(all, eid, compare = false) {
  const e = eid ? await api("/experiments/" + eid) : all[0];
  return (
    title(
      compare ? "Compare Experiments" : "Fitness history",
      compare
        ? "Compare exact configurations and synchronize recorded generation ranges."
        : "Raw observations, selectable metrics and explicit downsampling for long histories.",
    ) +
    panel(
      "Generation range and series",
      `<form id="chart-form"><div class="form-grid"><label>${compare ? "Experiments (select several)" : "Experiment"}<select name="ids" ${compare ? 'multiple size="5"' : ""}>${options(all, e?.id)}</select></label><label>First generation<input name="start" type="number" min="0" value="0"></label><label>Last generation<input name="end" type="number" min="0" value="${Math.max(0, (e?.generation || 1) - 1)}"></label><label>Smoothing<select name="smooth"><option value="1">Raw values</option><option value="5">5 plotted-point moving mean</option><option value="20">20 plotted-point moving mean</option></select></label></div><div class="legend">${Object.entries(
        names,
      )
        .map(
          ([key, label]) =>
            `<label><input type="checkbox" name="metrics" value="${key}" ${["mean", "maximum"].includes(key) ? "checked" : ""}>${label}</label>`,
        )
        .join(
          "",
        )}</div><p class="actions"><button class="primary">Update charts</button><button type="button" data-chart-range="in">Zoom in</button><button type="button" data-chart-range="out">Zoom out</button><button type="button" data-chart-range="left">Pan earlier</button><button type="button" data-chart-range="right">Pan later</button></p></form><p class="small">All comparison charts share the same generation range. Each chart labels its value scale. Smoothing uses plotted points and never changes the underlying raw measurements.</p>`,
    ) +
    `<div id="lab-charts">Loading observations…</div>` +
    (compare
      ? panel(
          "Exact configuration comparison",
          `<form id="config-diff-form" class="toolbar"><label>First experiment<select name="a">${options(all, e?.id)}</select></label><label>Second experiment<select name="b">${options(all, all[1]?.id)}</select></label><button>Compare configurations</button></form><div id="config-diff-result"></div>`,
        )
      : "")
  );
}
function svgChart(data, smoothing) {
  const rows = data.rows,
    metrics = data.metrics;
  let displayed = rows.map((r, i) => {
    const out = { ...r };
    for (const key of metrics) {
      const vals = rows
        .slice(Math.max(0, i - smoothing + 1), i + 1)
        .map((r) => r[key])
        .filter((v) => v != null);
      out[key] = vals.length
        ? vals.reduce((a, b) => a + b, 0) / vals.length
        : null;
    }
    return out;
  });
  const values = displayed.flatMap((r) =>
    metrics.map((k) => r[k]).filter((v) => v != null),
  );
  if (!values.length)
    return {
      html: "<p>No values available for the selected metrics and range.</p>",
      displayed,
    };
  let lo = Math.min(...values),
    hi = Math.max(...values);
  if (lo === hi) {
    lo -= 1;
    hi += 1;
  }
  const [start, end] = data.range,
    x = (g) => 100 + ((g - start) / Math.max(1, end - start)) * 840,
    y = (v) => 300 - ((v - lo) / (hi - lo)) * 260;
  const poly = metrics
    .map(
      (key, i) =>
        `<polyline fill="none" stroke="${colors[i]}" stroke-width="2" points="${displayed
          .filter((r) => r[key] != null)
          .map((r) => x(r.generation) + "," + y(r[key]))
          .join(" ")}"><title>${names[key]}</title></polyline>`,
    )
    .join("");
  return {
    displayed,
    html: `<svg class="interactive-chart" viewBox="0 0 980 350" role="img" aria-label="Recorded generation history"><rect width="980" height="350" fill="white"/>${Array.from(
      { length: 5 },
      (_, i) => {
        const v = lo + ((hi - lo) * i) / 4;
        return `<line x1="100" x2="940" y1="${y(v)}" y2="${y(v)}" stroke="#e2e8dd"/><text x="90" y="${y(v) + 4}" text-anchor="end" font-size="11" fill="#607276">${fmt(v, 2)}</text>`;
      },
    ).join(
      "",
    )}${poly}${[...data.milestones.map((m) => ({ g: m.generation, label: m.kind, type: "milestone" })), ...data.bookmarks.map((b) => ({ g: b.reference.generation, label: b.name, type: "bookmark" }))].map((m) => `<a href="#replay/${data.experiment_id}/${m.g}"><circle cx="${x(m.g)}" cy="315" r="4" fill="${m.type === "milestone" ? "#a18737" : "#805ead"}"><title>${esc(m.type + " · " + m.label + " · generation " + m.g)}</title></circle></a>`).join("")}<line class="chart-crosshair" x1="100" x2="100" y1="30" y2="310" stroke="#607276" stroke-dasharray="3 3"/><text x="100" y="341" font-size="12" fill="#607276">Generation ${start}</text><text x="940" y="341" text-anchor="end" font-size="12" fill="#607276">${end}</text></svg><div class="legend">${metrics.map((k, i) => `<span><svg width="16" height="10" aria-hidden="true"><rect width="14" height="3" y="3" fill="${colors[i]}"/></svg>${names[k]}</span>`).join("")}<span>Ochre markers: milestones · Purple markers: bookmarks</span></div>`,
  };
}
export async function bindCharts() {
  const form = $("#chart-form");
  const load = async () => {
    const loadStarted = performance.now();
    const d = new FormData(form),
      ids = d.getAll("ids"),
      metrics = d.getAll("metrics");
    if (!ids.length || !metrics.length)
      throw Error("Select experiments and at least one metric.");
    if (ids.length > 8)
      throw Error("Compare at most eight experiments at once.");
    $("#lab-charts").textContent = "Loading bounded recorded history…";
    const results = await Promise.all(
      ids.map(async (eid) => {
        const q = new URLSearchParams({
          start: d.get("start"),
          end: d.get("end"),
          points: 1000,
        });
        metrics.forEach((m) => q.append("metrics", m));
        return api(`/lab/experiments/${eid}/chart?${q}`);
      }),
    );
    const renderStarted = performance.now();
    $("#lab-charts").innerHTML = results
      .map((data, index) => {
        const name = [...form.elements.ids.options].find(
          (o) => o.value === data.experiment_id,
        )?.textContent;
        const chart = svgChart(data, Number(d.get("smooth")));
        return panel(
          name,
          `<p class="small">${data.plotted_count} plotted observations of ${fmt(data.raw_count, 0)} · ${data.downsampled ? "Downsampled: extrema preserved per bucket." : "All recorded observations in this range."} ${Number(d.get("smooth")) === 1 ? "Raw values." : `${d.get("smooth")}-point smoothing of plotted observations; raw data still exported.`}</p><div data-chart="${index}">${chart.html}<p class="chart-tooltip" aria-live="polite">Move across the chart to inspect a plotted observation.</p><div class="actions"><button data-save-svg>Export SVG</button><button data-save-data>Download plotted data</button><button data-mark-generation>Bookmark inspected generation</button></div></div>`,
        );
      })
      .join("");
    results.forEach((data, index) => {
      const root = $(`[data-chart="${index}"]`),
        svg = $("svg.interactive-chart", root);
      let hovered = data.rows[0];
      if (svg)
        svg.onpointermove = (event) => {
          const r = svg.getBoundingClientRect(),
            point = ((event.clientX - r.left) / r.width) * 980,
            g =
              data.range[0] +
              Math.max(0, Math.min(1, (point - 100) / 840)) *
                (data.range[1] - data.range[0]);
          hovered = data.rows.reduce(
            (best, row) =>
              !best ||
              Math.abs(row.generation - g) < Math.abs(best.generation - g)
                ? row
                : best,
            null,
          );
          if (!hovered) return;
          const x =
            100 +
            ((hovered.generation - data.range[0]) /
              Math.max(1, data.range[1] - data.range[0])) *
              840;
          $(".chart-crosshair", svg).setAttribute("x1", x);
          $(".chart-crosshair", svg).setAttribute("x2", x);
          $(".chart-tooltip", root).textContent =
            `Recorded generation ${hovered.generation}: ` +
            metrics.map((k) => `${names[k]} ${fmt(hovered[k], 6)}`).join(" · ");
        };
      $("[data-save-svg]", root).onclick = () => {
        if (!svg) return;
        const clone = svg.cloneNode(true);
        clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
        download(
          data.experiment_id + "-chart.svg",
          new XMLSerializer().serializeToString(clone),
          "image/svg+xml",
        );
      };
      $("[data-save-data]", root).onclick = () =>
        download(
          data.experiment_id + "-plotted-data.json",
          JSON.stringify(
            { ...data, display_smoothing: Number(d.get("smooth")) },
            null,
            2,
          ),
        );
      $("[data-mark-generation]", root).onclick = () => {
        if (hovered)
          bookmark(data.experiment_id, "generation", {
            generation: hovered.generation,
          }).catch((e) => toast(e.message, true));
      };
    });
    // Local diagnostics measure script, DOM construction and layout, not GPU paint.
    const charts = $("#lab-charts");
    charts.getBoundingClientRect();
    charts.dataset.renderMs = (performance.now() - renderStarted).toFixed(2);
    charts.dataset.loadMs = (performance.now() - loadStarted).toFixed(2);
  };
  bind(form, load);
  document.querySelectorAll("[data-chart-range]").forEach(
    (b) =>
      (b.onclick = () => {
        let a = Number(form.elements.start.value),
          z = Number(form.elements.end.value),
          span = Math.max(2, z - a),
          center = (a + z) / 2;
        const mode = b.dataset.chartRange;
        if (mode === "in") {
          a = Math.max(0, Math.floor(center - span / 4));
          z = Math.ceil(center + span / 4);
        }
        if (mode === "out") {
          a = Math.max(0, Math.floor(center - span));
          z = Math.ceil(center + span);
        }
        if (mode === "left") {
          a = Math.max(0, a - Math.ceil(span / 4));
          z = a + span;
        }
        if (mode === "right") {
          a += Math.ceil(span / 4);
          z += Math.ceil(span / 4);
        }
        form.elements.start.value = a;
        form.elements.end.value = z;
        form.requestSubmit();
      }),
  );
  if ($("#config-diff-form"))
    bind($("#config-diff-form"), async (d) => {
      const diff = await api("/lab/config-diff?" + new URLSearchParams(d));
      $("#config-diff-result").innerHTML =
        table(
          ["Field", "Kind", "First", "Second"],
          diff.fields.map(
            (f) =>
              `<tr class="${f.different ? "highlight" : ""}"><td>${esc(f.path)}${f.different ? " · changed" : ""}</td><td>${esc(f.category)}</td><td><code>${esc(JSON.stringify(f.a))}</code></td><td><code>${esc(JSON.stringify(f.b))}</code></td></tr>`,
          ),
        ) +
        '<p class="actions"><button id="export-config-diff">Export comparison</button><button id="copy-config-diff">Copy comparison</button></p>';
      $("#export-config-diff").onclick = () =>
        download("configuration-diff.json", JSON.stringify(diff, null, 2));
      $("#copy-config-diff").onclick = () =>
        navigator.clipboard
          .writeText(JSON.stringify(diff, null, 2))
          .then(() => toast("Comparison copied"))
          .catch(() =>
            toast("Clipboard unavailable; use Export comparison.", true),
          );
    });
  if (form.elements.ids.value) await load();
}
export async function replayPage(all, eid, generation) {
  const e = eid ? await api("/experiments/" + eid) : all[0];
  return (
    title(
      "Evolution Replay",
      "Playback of recorded observations. This does not run another evolutionary simulation.",
    ) +
    panel(
      "Playback controls",
      `<form id="replay-form" class="toolbar"><label>Experiment<select name="eid">${options(all, e?.id)}</select></label><label>Generation<input name="generation" type="number" min="0" value="${Number(generation) || 0}"></label><button>Jump to generation</button></form><div class="toolbar"><button id="replay-back">Step backward</button><button id="replay-play" class="primary">Play</button><button id="replay-pause">Pause</button><button id="replay-forward">Step forward</button><label>Playback speed<select id="replay-speed"><option value="1000">1 observation / second</option><option value="500">2 observations / second</option><option value="200">5 observations / second</option></select></label><label>Milestone<select id="replay-milestone"><option value="">Select milestone</option></select></label></div><label>Recorded generation timeline<input id="replay-scrub" type="range" min="0" max="${Math.max(0, (e?.generation || 1) - 1)}" value="${Number(generation) || 0}"></label><button id="replay-bookmark">Bookmark this observation</button>`,
    ) +
    `<div id="replay-frame">Loading saved history…</div>`
  );
}
export async function bindReplay() {
  const form = $("#replay-form");
  let playing = false,
    busy = false,
    rows = [],
    eid = null,
    index = 0,
    current = 0;
  const initialize = async () => {
    eid = form.elements.eid.value;
    const exp = await api("/experiments/" + eid);
    $("#replay-scrub").max = Math.max(0, exp.generation - 1);
    const marks = await api(`/lab/experiments/${eid}/milestones?limit=200`);
    $("#replay-milestone").innerHTML =
      '<option value="">Jump to milestone</option>' +
      marks.items
        .map(
          (m) =>
            `<option value="${m.generation}">${m.generation} · ${esc(m.kind)}</option>`,
        )
        .join("");
    rows = [];
  };
  const show = async (generation) => {
    if (busy) return;
    busy = true;
    try {
      if (eid !== form.elements.eid.value) await initialize();
      const frame = await api(`/lab/experiments/${eid}/replay/${generation}`);
      current = generation;
      form.elements.generation.value = current;
      $("#replay-scrub").value = current;
      const s = frame.statistics;
      $("#replay-frame").innerHTML =
        `<div class="metrics">${Object.entries({
          Generation: current,
          "Mean fitness": s.mean,
          "Maximum fitness": s.maximum,
          "Genetic diversity": s.genetic_rms,
        })
          .map(
            ([k, v]) =>
              `<div class="metric"><span class="label">${k}</span><strong>${fmt(v, 4)}</strong></div>`,
          )
          .join("")}</div>` +
        panel(
          frame.snapshot_retained
            ? "Detailed population snapshot retained"
            : "Aggregate observations only",
          `<p class="note">${esc(frame.notice)} ${frame.snapshot_retained ? "" : "Population-level network fitness is unavailable for this generation."}</p><p>Recorded champion ${s.champion_id ? `<a href="#experiment/${eid}/inspector/${s.champion_id}">#${s.champion_id}</a>` : "unavailable"} · Mean mutations ${fmt(s.mutation_mean)} · Recorded cluster sizes ${esc(JSON.stringify(s.cluster_sizes ?? "unavailable"))}</p>${
            s.histogram
              ? table(
                  ["Fitness bin start", "Count"],
                  s.histogram.counts.map(
                    (n, i) =>
                      `<tr><td>${fmt(s.histogram.edges[i])}</td><td>${n}</td></tr>`,
                  ),
                )
              : ""
          }${
            frame.population.length
              ? table(
                  ["Network", "Recorded fitness"],
                  frame.population.map(
                    (p) =>
                      `<tr><td><a href="#experiment/${eid}/inspector/${p.network_id}">#${p.network_id}</a></td><td>${fmt(p.total)}</td></tr>`,
                  ),
                )
              : ""
          }<p class="small">Showing up to ${frame.population_limit} saved population entries.</p>${s.champion_id ? `<a class="button" href="#family/${eid}/${s.champion_id}">Explore champion family</a>` : ""}<details><summary>Bounded family state from stored parent edges</summary>${pre(frame.family)}</details>`,
        );
    } finally {
      busy = false;
    }
  };
  const step = async (direction) => {
    if (busy) return;
    const start = direction < 0 ? Math.max(0, current - 1000) : current + 1;
    rows = await api(`/experiments/${eid}/stats?start=${start}&limit=1000`);
    const next =
      direction < 0
        ? rows.filter((r) => r.generation < current).at(-1)
        : rows[0];
    if (!next) {
      playing = false;
      return;
    }
    await show(next.generation);
  };
  bind(form, async (d) => {
    playing = false;
    await show(Number(d.get("generation")));
  });
  $("#replay-back").onclick = () => {
    playing = false;
    step(-1).catch((e) => toast(e.message, true));
  };
  $("#replay-forward").onclick = () => {
    playing = false;
    step(1).catch((e) => toast(e.message, true));
  };
  const tick = async () => {
    if (!playing || !form.isConnected) return;
    try {
      await step(1);
    } catch (e) {
      playing = false;
      toast(e.message, true);
    }
    if (playing) setTimeout(tick, Number($("#replay-speed").value));
  };
  $("#replay-play").onclick = () => {
    if (!playing) {
      playing = true;
      tick();
    }
  };
  $("#replay-pause").onclick = () => (playing = false);
  $("#replay-scrub").onchange = (e) => {
    playing = false;
    show(Number(e.target.value)).catch((error) => toast(error.message, true));
  };
  $("#replay-milestone").onchange = (e) => {
    if (e.target.value !== "") {
      playing = false;
      show(Number(e.target.value)).catch((error) => toast(error.message, true));
    }
  };
  $("#replay-bookmark").onclick = () =>
    bookmark(eid, "generation", { generation: current }).catch((e) =>
      toast(e.message, true),
    );
  if (form.elements.eid.value) {
    await initialize();
    const first = await api(
      `/experiments/${eid}/stats?start=${Number(form.elements.generation.value)}&limit=1`,
    );
    if (first.length) await show(first[0].generation);
    else
      $("#replay-frame").textContent =
        "No observations have been recorded yet.";
  }
}
export async function timelinePage(eid) {
  const e = await api("/experiments/" + eid);
  return (
    title(
      "Event timeline",
      e.name +
        " · Recorded execution events and separately labeled annotations.",
    ) +
    panel(
      "Chronological events",
      `<form id="timeline-filter" class="toolbar"><label>Event type<select name="kind"><option value="">All types</option>${["created", "running", "pause", "paused", "resume", "cancelled", "completed", "failed", "recovery", "disk_pause", "checkpoint", "bookmark", "milestone"].map((v) => `<option>${v}</option>`).join("")}</select></label><button>Filter timeline</button></form><div id="timeline-results"></div><button id="timeline-more">More events</button>`,
    ) +
    panel(
      "Descriptive milestone detection",
      `<p>Uses stored measurements only. Detection dates are annotation dates. A mutation near a fitness increase does not establish causation.</p><form id="milestone-form" class="form-grid"><label>Fitness threshold<input name="fitness_threshold" type="number" step="any"></label><label>Major fitness increase<input name="fitness_increase" type="number" min="0.000001" step="any"></label><label>Diversity at or below<input name="diversity_threshold" type="number" min="0" step="any"></label><label>Absolute mutation-mean change<input name="mutation_change" type="number" min="0.000001" step="any"></label><label>Repeated champion observations<input name="champion_duration" type="number" min="2" value="20"></label><button>Detect candidates</button></form><button id="refresh-milestones">Refresh candidates</button><div id="milestone-results"></div><button id="milestone-more">More candidates</button>`,
    ) +
    jobPanel()
  );
}
export async function bindTimeline(eid) {
  let offset = 0,
    moff = 0;
  const load = async (append = false) => {
    const kind = $("#timeline-filter select").value,
      result = await api(
        `/lab/experiments/${eid}/timeline?` +
          new URLSearchParams({ offset, kind }),
      );
    const html = table(
      ["Time", "Event", "Provenance", "Reference"],
      result.items.map(
        (e) =>
          `<tr><td>${date(e.time)}</td><td>${esc(e.kind)}<br>${esc(e.description)}</td><td>${esc(e.provenance)}</td><td>${e.generation != null ? `<a href="#replay/${eid}/${e.generation}">Generation ${e.generation}</a>` : e.network_id ? `<a href="#experiment/${eid}/inspector/${e.network_id}">Network ${e.network_id}</a>` : `<a href="#experiment/${eid}/monitor">Experiment</a>`}${e.key.startsWith("event:") ? `<button data-bookmark-event="${e.key.slice(6)}">Bookmark event</button>` : ""}</td></tr>`,
      ),
    );
    if (append) $("#timeline-results").insertAdjacentHTML("beforeend", html);
    else $("#timeline-results").innerHTML = html;
    $("#timeline-more").disabled = result.next_offset == null;
    offset = result.next_offset;
    document
      .querySelectorAll("[data-bookmark-event]")
      .forEach(
        (b) =>
          (b.onclick = () =>
            bookmark(eid, "event", {
              event_id: Number(b.dataset.bookmarkEvent),
            }).catch((e) => toast(e.message, true))),
      );
  };
  const milestones = async (append = false) => {
    const r = await api(`/lab/experiments/${eid}/milestones?offset=${moff}`);
    const html =
      r.items
        .map(
          (m) =>
            `<article class="bookmark-card"><h3><a href="#replay/${eid}/${m.generation}">Generation ${m.generation}</a> · ${esc(m.kind)}</h3><p>Measured value ${fmt(m.value)} · ${esc(m.status)}</p><details><summary>Detection provenance</summary>${pre(m.provenance)}</details><form data-review-milestone="${m.id}"><label>Status<select name="status">${["candidate", "confirmed", "dismissed"].map((v) => `<option ${v === m.status ? "selected" : ""}>${v}</option>`).join("")}</select></label><label>Annotation<textarea name="notes" maxlength="16000">${esc(m.notes)}</textarea></label><p><button>Save review</button></p></form></article>`,
        )
        .join("") || "<p>No candidates yet. Run detection above.</p>";
    if (append) $("#milestone-results").insertAdjacentHTML("beforeend", html);
    else $("#milestone-results").innerHTML = html;
    $("#milestone-more").disabled = r.next_offset == null;
    moff = r.next_offset;
    r.items.forEach((m) =>
      bind($(`[data-review-milestone="${m.id}"]`), async (d) => {
        await api("/lab/milestones/" + m.id, Object.fromEntries(d), "PUT");
        toast("Milestone review saved");
      }),
    );
  };
  bind($("#timeline-filter"), async () => {
    offset = 0;
    await load();
  });
  $("#timeline-more").onclick = () =>
    load(true).catch((e) => toast(e.message, true));
  bind($("#milestone-form"), (d) => {
    const config = { record_high: true };
    for (const [k, v] of d) if (v !== "") config[k] = Number(v);
    return startJob("milestones", { experiment_id: eid, config });
  });
  $("#refresh-milestones").onclick = () => {
    moff = 0;
    milestones().catch((e) => toast(e.message, true));
  };
  $("#milestone-more").onclick = () =>
    milestones(true).catch((e) => toast(e.message, true));
  await Promise.all([load(), milestones()]);
}
