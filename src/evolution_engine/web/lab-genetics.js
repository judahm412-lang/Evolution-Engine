import {
  $,
  esc,
  fmt,
  title,
  panel,
  table,
  pre,
  options,
  api,
  toast,
  bind,
  bookmark,
  download,
} from "./lab-common.js?v=2.0.1-r2";
export function familyPage(all, eid, nid) {
  return (
    title(
      "Family Trees",
      "Explore actual stored parent edges. Missing historical ancestors remain visible as unknown nodes.",
    ) +
    panel(
      "Choose a lineage",
      `<form id="family-form" class="toolbar"><label>Experiment<select name="eid">${options(all, eid)}</select></label><label>Network ID<input name="nid" type="number" min="1" value="${Number(nid) || 1}" required></label><label>Direction<select name="direction"><option value="ancestors">Ancestors</option><option value="descendants">Descendants</option></select></label><label>Depth<input name="depth" type="number" min="1" max="30" value="5"></label><label>From birth generation<input name="generation_min" type="number" min="0" value="0"></label><label>Through birth generation<input name="generation_max" type="number" min="0" value="1000000"></label><button class="primary">Load family</button></form>`,
    ) +
    panel(
      "Recorded family graph",
      `<div class="toolbar"><label>Color nodes by<select id="family-color"><option value="fitness">Recorded fitness</option><option value="birth">Birth generation</option><option value="founder">Loaded founder lineage</option><option value="mutations">Mutation count</option><option value="bookmark">Bookmarks</option><option value="selected">Selected branch</option><option value="cluster" disabled>Cluster membership not recorded</option></select></label><button id="family-in">Zoom in</button><button id="family-out">Zoom out</button><button id="family-fit">Fit graph</button><button id="family-center">Center selection</button><button id="family-expand">Expand selected node</button><button id="family-collapse">Collapse descendants</button><button id="family-more">Load next page</button></div><p id="family-legend" class="small"></p><div class="graph-frame"><svg id="family-svg" viewBox="0 0 1000 520" role="group" aria-label="Interactive family tree" tabindex="0"></svg></div><p class="small">Drag to pan, use wheel or zoom buttons to zoom. Arrow keys pan the focused graph. Tab to nodes and press Enter to select. Up to 500 loaded nodes; expand individual branches to explore further.</p><div id="family-detail" aria-live="polite">Choose a network above.</div><div class="actions"><button id="family-bookmark">Bookmark selected branch</button><button id="family-export">Export loaded graph</button></div><details><summary>Keyboard-accessible node and edge list</summary><div id="family-table"></div></details>`,
    )
  );
}
export async function bindFamily() {
  const form = $("#family-form"),
    svg = $("#family-svg");
  let nodes = new Map(),
    edges = new Map(),
    cursor = null,
    cursorRoot = null,
    deferred = new Set(),
    selected = Number(form.elements.nid.value),
    params = null,
    box = [0, 0, 1000, 520],
    positions = new Map(),
    bounds = [-50, 0, 1100, 520],
    drag = null;
  const setBox = () => svg.setAttribute("viewBox", box.join(" "));
  const zoom = (factor) => {
    const [x, y, w, h] = box;
    box = [
      x + (w * (1 - factor)) / 2,
      y + (h * (1 - factor)) / 2,
      w * factor,
      h * factor,
    ];
    setBox();
  };
  const select = (id) => {
    selected = id;
    const n = nodes.get(id);
    if (!n) return;
    $("#family-detail").innerHTML =
      `<h3>Network #${id}${n.unknown ? " · Unknown ancestor" : ""}</h3><p>${n.unknown ? "No genome metadata is available." : `Born ${n.birth_generation} · ${n.mutation_count} changed parameters · ${esc(n.layers.join(" → "))} · ${esc(n.activations.join(", "))}`}</p>${n.unknown ? "" : `<p>Fingerprint <code>${n.fingerprint}</code></p><a class="button" href="#experiment/${params.eid}/inspector/${id}">Open network inspector</a> <a class="button" href="#weights/${params.eid}/${id}">Compare weights</a>`}`;
    draw();
  };
  const colorValue = (n, mode) => {
    if (mode === "fitness") return n.fitness?.total;
    if (mode === "birth") return n.birth_generation;
    if (mode === "mutations") return n.mutation_count;
    if (mode === "bookmark") return n.bookmarked ? 1 : 0;
    if (mode === "selected") {
      const branch = new Set([selected]);
      for (const direction of ["ancestors", "descendants"]) {
        const todo = [selected],
          seen = new Set();
        while (todo.length) {
          const id = todo.pop();
          if (seen.has(id)) continue;
          seen.add(id);
          for (const edge of edges.values()) {
            if (direction === "ancestors" && edge.child === id) {
              branch.add(edge.parent);
              todo.push(edge.parent);
            }
            if (direction === "descendants" && edge.parent === id) {
              branch.add(edge.child);
              todo.push(edge.child);
            }
          }
        }
      }
      return branch.has(n.id) ? 1 : 0;
    }
    if (mode === "founder") {
      let cur = n.id,
        seen = new Set();
      while (!seen.has(cur)) {
        seen.add(cur);
        const parents = [...edges.values()].filter((e) => e.child === cur);
        if (!parents.length) return nodes.get(cur)?.founder ? cur : null;
        if (parents.length > 1) return null;
        cur = parents[0].parent;
      }
      return null;
    }
  };
  const draw = () => {
    const mode = $("#family-color").value,
      palette = ["#e4edda", "#b5d399", "#78b58b", "#3b8e76", "#155d4d"],
      values = [...nodes.values()]
        .map((n) => colorValue(n, mode))
        .filter((v) => v != null),
      lo = Math.min(...values),
      hi = Math.max(...values);
    const generations = [...nodes.values()]
        .map((n) => n.birth_generation)
        .filter((v) => v != null),
      min = Math.min(...generations),
      max = Math.max(...generations),
      groups = new Map();
    positions = new Map();
    for (const node of [...nodes.values()].sort((a, b) => a.id - b.id)) {
      const gen = node.birth_generation ?? min - 1,
        key = gen;
      const group = groups.get(key) || [];
      group.push(node);
      groups.set(key, group);
    }
    const orderedGroups = [...groups].sort((a, b) => a[0] - b[0]);
    const spacing = Math.max(130, 820 / Math.max(1, orderedGroups.length - 1));
    const graphHeight = Math.max(420, ...orderedGroups.map(([,group]) => group.length * 64));
    orderedGroups.forEach(([gen, group], column) => {
      group.forEach((node, row) => positions.set(node.id, [
        80 + column * spacing,
        50 + graphHeight / 2 + (row - (group.length - 1) / 2) * 64,
      ]));
    });
    bounds = [0, 0, Math.max(1000, 160 + (orderedGroups.length - 1) * spacing), graphHeight + 100];
    const links = [...edges.values()]
      .filter((e) => positions.has(e.parent) && positions.has(e.child))
      .map((e) => {
        const a = positions.get(e.parent),
          b = positions.get(e.child);
        return `<path d="M${a[0]},${a[1]} C${(a[0] + b[0]) / 2},${a[1]} ${(a[0] + b[0]) / 2},${b[1]} ${b[0]},${b[1]}" class="family-edge" marker-end="url(#family-arrow)"><title>Parent ${e.parent} → child ${e.child}</title></path>`;
      })
      .join("");
    svg.innerHTML =
      `<defs><marker id="family-arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#80958b"/></marker></defs>${links}` +
      [...nodes.values()]
        .map((n) => {
          const [x, y] = positions.get(n.id),
            value = colorValue(n, mode),
            index =
              value == null
                ? -1
                : Math.min(
                    4,
                    Math.floor((4 * (value - lo)) / Math.max(1, hi - lo)),
                  );
          return `<g class="family-node ${n.id === selected ? "chosen" : ""} ${n.outside_range ? "outside-range" : ""}" tabindex="0" role="button" aria-label="Select network ${n.id}${n.unknown ? ", unknown ancestor" : ""}" data-node="${n.id}" transform="translate(${x},${y})"><rect x="-40" y="-18" width="80" height="36" rx="8" fill="${index < 0 ? "#e6e6e2" : palette[index]}"/><text text-anchor="middle" y="4" fill="${index > 2 ? "white" : "#17362d"}">${n.unknown ? "? " : ""}#${n.id}</text><title>${n.unknown ? "Unknown historical ancestor" : `Born ${n.birth_generation}; ${n.mutation_count} mutations`}</title></g>`;
        })
        .join("");
    svg.querySelectorAll("[data-node]").forEach((n) => {
      n.onclick = () => select(Number(n.dataset.node));
      n.onkeydown = (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          select(Number(n.dataset.node));
        }
      };
    });
    $("#family-legend").textContent =
      `${nodes.size} loaded nodes · ${edges.size} stored parent edges. ${mode === "founder" ? "Colors identify resolved founders within the loaded graph; gray = unresolved or multiple ancestry." : `Light → dark: ${mode} ${fmt(lo)} → ${fmt(hi)}; gray = unavailable.`} Faded nodes are outside the requested birth range. Cluster membership was not stored by v2.0.${deferred.size ? ` Wider branches require a separate view from network IDs: ${[...deferred].join(", ")}.` : ""}`;
    $("#family-table").innerHTML = table(
      ["Network", "Birth", "Parents in view", "Recorded fitness"],
      [...nodes.values()].map(
        (n) =>
          `<tr><td><button data-text-node="${n.id}">#${n.id}${n.unknown ? " (unknown)" : ""}</button></td><td>${n.birth_generation ?? "Unknown"}</td><td>${
            [...edges.values()]
              .filter((e) => e.child === n.id)
              .map((e) => e.parent)
              .join(", ") || "No loaded edge"
          }</td><td>${fmt(n.fitness?.total)}</td></tr>`,
      ),
    );
    document
      .querySelectorAll("[data-text-node]")
      .forEach((b) => (b.onclick = () => select(Number(b.dataset.textNode))));
    $("#family-more").disabled = !cursor;
  };
  const load = async (reset = true, id = null, next = null) => {
    const d = new FormData(form);
    params = Object.fromEntries(d);
    if (reset) {
      nodes.clear();
      deferred.clear();
      edges.clear();
      selected = Number(params.nid);
    }
    const query = new URLSearchParams({
      direction: params.direction,
      depth: params.depth,
      limit: 100,
      generation_min: params.generation_min,
      generation_max: params.generation_max,
    });
    if (next) query.set("cursor", next);
    const root = next ? cursorRoot : id || params.nid;
    const result = await api(
      `/lab/experiments/${params.eid}/family/${root}?${query}`,
    );
    cursorRoot = root;
    if (nodes.size + result.nodes.filter((n) => !nodes.has(n.id)).length > 500)
      throw Error(
        "Loaded-node limit reached. Start a new view centered on the selected branch.",
      );
    result.nodes.forEach((n) => nodes.set(n.id, n));
    result.edges.forEach((e) => edges.set(e.parent + ":" + e.child, e));
    cursor = result.next_cursor;
    (result.deferred_expansion || []).forEach(id => deferred.add(id));
    draw();
    if (reset) {
      const pos = positions.get(selected) || [500, 260];
      box = bounds[2] <= 1100 ? [...bounds] : [pos[0] - 820, pos[1] - 260, 1100, 520];
      setBox();
      select(selected);
    }
  };
  bind(form, () => load());
  $("#family-color").onchange = draw;
  $("#family-in").onclick = () => zoom(0.8);
  $("#family-out").onclick = () => zoom(1.25);
  $("#family-fit").onclick = () => {
    box = [...bounds];
    setBox();
  };
  $("#family-center").onclick = () => {
    const pos = positions.get(selected);
    if (pos) {
      box = [pos[0] - box[2] / 2, pos[1] - box[3] / 2, box[2], box[3]];
      setBox();
    }
  };
  $("#family-expand").onclick = () =>
    load(false, selected).catch((e) => toast(e.message, true));
  $("#family-more").onclick = () =>
    load(false, null, cursor).catch((e) => toast(e.message, true));
  $("#family-collapse").onclick = () => {
    const remove = new Set(),
      todo = [selected];
    while (todo.length) {
      const id = todo.pop();
      for (const e of edges.values())
        if (e.parent === id && e.child !== selected && !remove.has(e.child)) {
          remove.add(e.child);
          todo.push(e.child);
        }
    }
    for (const id of remove) nodes.delete(id);
    for (const [key, e] of edges)
      if (remove.has(e.parent) || remove.has(e.child)) edges.delete(key);
    draw();
  };
  $("#family-bookmark").onclick = () =>
    bookmark(params?.eid, "branch", { network_id: selected }).catch((e) =>
      toast(e.message, true),
    );
  $("#family-export").onclick = () =>
    download(
      "recorded-family.json",
      JSON.stringify(
        {
          experiment_id: params?.eid,
          nodes: [...nodes.values()],
          edges: [...edges.values()],
          bounded: true,
        },
        null,
        2,
      ),
    );
  svg.addEventListener(
    "wheel",
    (e) => {
      e.preventDefault();
      zoom(e.deltaY > 0 ? 1.1 : 0.9);
    },
    { passive: false },
  );
  svg.onpointerdown = (e) => {
    if (e.target.closest("[data-node]")) return;
    drag = { x: e.clientX, y: e.clientY, box: [...box] };
    svg.setPointerCapture(e.pointerId);
  };
  svg.onpointermove = (e) => {
    if (!drag) return;
    const r = svg.getBoundingClientRect();
    box = [
      drag.box[0] - ((e.clientX - drag.x) * drag.box[2]) / r.width,
      drag.box[1] - ((e.clientY - drag.y) * drag.box[3]) / r.height,
      ...drag.box.slice(2),
    ];
    setBox();
  };
  svg.onpointerup = () => (drag = null);
  svg.onkeydown = (e) => {
    const moves = {
      ArrowLeft: [-40, 0],
      ArrowRight: [40, 0],
      ArrowUp: [0, -40],
      ArrowDown: [0, 40],
    };
    if (moves[e.key]) {
      e.preventDefault();
      box[0] += moves[e.key][0];
      box[1] += moves[e.key][1];
      setBox();
    }
  };
  if (form.elements.eid.value) {
    try { await load(); } catch (e) { $("#family-detail").textContent = "Choose an existing saved network. " + e.message; }
  }
}
export function weightsPage(all, eid, nid) {
  return (
    title(
      "Genetic weight comparison",
      "Exact differences in the original stored parameter order, with bounded layer sections.",
    ) +
    panel(
      "Choose two saved networks",
      `<form id="weights-form" class="form-grid"><label>First experiment<select name="a">${options(all, eid)}</select></label><label>First network<input name="an" type="number" min="1" value="${Number(nid) || 1}" required></label><label>Second experiment<select name="b">${options(all, eid)}</select></label><label>Second network<input name="bn" type="number" min="1" value="2" required></label><label>Layer (zero based)<input name="layer" type="number" min="0" max="6" value="0"></label><label>Parameter type<select name="kind"><option>weights</option><option>biases</option></select></label><label>Section offset<input name="offset" type="number" min="0" value="0"></label><button class="primary">Compare genomes</button></form>`,
    ) +
    panel(
      "Layer differences",
      '<div id="weight-results">Select two networks to inspect exact changes.</div>',
    )
  );
}
export async function bindWeights() {
  bind($("#weights-form"), async (d) => {
    const result = await api(
      "/lab/genetic-comparison?" + new URLSearchParams(d),
    );
    let html = `<div class="grid"><div><h3>First network</h3>${pre(result.a)}</div><div><h3>Second network</h3>${pre(result.b)}</div></div>`;
    if (!result.compatible) {
      $("#weight-results").innerHTML =
        html + `<p class="note">${esc(result.explanation)}</p>`;
      return;
    }
    const max = Math.max(...result.cells.map((c) => c.absolute), 1e-15);
    html += `<p>RMS distance ${fmt(result.rms, 10)} · ${fmt(result.changed_parameters, 0)} changed parameters.</p><p class="small">${esc(result.ordering)} Matrix ${result.rows} rows × ${result.columns} columns. Showing ${result.offset}–${result.offset + result.cells.length - 1} of ${result.section_length} parameters in this layer section.</p><p>Heatmap: neutral = unchanged, green = increase, ochre = decrease. Darker cells have larger absolute changes within this section. Select a cell for exact values.</p><div class="weight-heat">${result.cells.map((c) => `<button class="weight-cell ${c.changed ? (c.difference > 0 ? "positive" : "negative") : "unchanged"} intensity-${Math.ceil((3 * c.absolute) / max)}" data-weight-index="${c.index}" aria-label="Parameter ${c.index}: ${c.a} to ${c.b}; difference ${c.difference}">${c.section_index}<small>${fmt(c.difference, 4)}</small></button>`).join("")}</div><p id="weight-selected" aria-live="polite">Select a parameter.</p>${result.next_offset != null ? `<button id="weights-next" data-offset="${result.next_offset}">Next matrix section</button>` : ""}<details><summary>Largest absolute differences across the complete compatible genomes</summary>${pre(result.largest_differences)}</details>`;
    $("#weight-results").innerHTML = html;
    document.querySelectorAll("[data-weight-index]").forEach(
      (b) =>
        (b.onclick = () => {
          const c = result.cells.find(
            (x) => x.index === Number(b.dataset.weightIndex),
          );
          $("#weight-selected").textContent =
            `Parameter ${c.index} · layer row ${Math.floor(c.section_index / result.columns)}, column ${c.section_index % result.columns} · first ${c.a} · second ${c.b} · signed difference ${c.difference} · absolute difference ${c.absolute}`;
        }),
    );
    if ($("#weights-next"))
      $("#weights-next").onclick = () => {
        $("#weights-form").elements.offset.value = result.next_offset;
        $("#weights-form").requestSubmit();
      };
  });
  if ($("#weights-form").elements.a.value) $("#weights-form").requestSubmit();
}
