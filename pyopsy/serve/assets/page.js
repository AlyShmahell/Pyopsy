const state = {
  snapshot: null,
  selected: null,
  processId: null,
  zoom: [],
  zoomMem: [],
};

function $(id) {
  return document.getElementById(id);
}

function fmtTime(value) {
  if (value == null) {
    return "0.000 s";
  }
  if (value < 0.001) {
    return `${(value * 1e6).toFixed(0)} us`;
  }
  return `${value.toFixed(3)} s`;
}

function fmtBytes(count) {
  if (count == null || count <= 0) {
    return "0.0B";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(count) / Math.log(1024)), units.length - 1);
  return `${(count / (1024 ** index)).toFixed(2)}${units[index]}`;
}

function currentSnapshot(root) {
  if (!root) {
    return null;
  }
  if (state.processId == null || state.processId === root.process_id) {
    return root;
  }
  const processes = root.processes || [];
  for (const item of processes) {
    if (item.process_id === state.processId && item.snapshot) {
      return item.snapshot;
    }
  }
  return root;
}

function renderProcessSelect(root) {
  const box = $("process-box");
  const select = $("process-select");
  const processes = root.processes || [];
  if (processes.length < 2) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  const current = state.processId == null ? root.process_id : state.processId;
  select.innerHTML = "";
  for (const item of processes) {
    const option = document.createElement("option");
    option.value = String(item.process_id);
    const rank = item.rank == null ? "" : ` rank ${item.rank}`;
    option.textContent = `${item.label} ${item.process_id}${rank} port ${item.port}`;
    if (String(item.process_id) === String(current)) {
      option.selected = true;
    }
    select.appendChild(option);
  }
}

function runtimeOf(snap) {
  if (snap.runtime != null) {
    return snap.runtime;
  }
  return (snap.wall || []).reduce((sum, row) => sum + (row.total_wall_time || 0), 0);
}

function renderSummary(snap) {
  const memory = snap.memory || {};
  const rank = snap.rank == null ? "none" : String(snap.rank);
  const cards = [
    ["Session time", fmtTime(snap.session_time)],
    ["Runtime", fmtTime(runtimeOf(snap))],
    ["RSS", memory.rss_text || "0.0B"],
    ["Peak RSS", memory.peak_rss_text || "0.0B"],
    ["Traced Python memory", memory.traced_text || "0.0B"],
    ["Process", String(snap.process_id)],
    ["Rank / port", `${rank} / ${snap.port}`],
  ];
  $("summary").innerHTML = cards.map(
    ([label, value]) => `<article class="card"><span>${label}</span><strong>${value}</strong></article>`
  ).join("");
}

function renderWall(snap) {
  const rows = snap.wall || [];
  if (!rows.length) {
    $("wall").innerHTML = "<p class=\"empty\">Mark a function with @pyopsy.profiler.</p>";
    return;
  }
  const body = rows.map((row) => {
    const id = `${row.filename}|${row.firstlineno}|${row.name}`;
    const selected = state.selected === id ? " class=\"selected\"" : "";
    return `<tr data-id="${id}"${selected}><td>${row.name}</td><td>${row.kind}</td><td>${row.call_count}</td><td>${fmtTime(row.wall_time)}</td><td>${fmtTime(row.total_wall_time)}</td><td>${fmtBytes(row.mem_mean)}</td><td>${fmtBytes(row.mem_peak)}</td><td>${row.lines ? "yes" : "no"}</td></tr>`;
  }).join("");
  $("wall").innerHTML = `<table><thead><tr><th>Name</th><th>Kind</th><th>Calls</th><th>Wall time</th><th>Total wall time</th><th>Mem mean</th><th>Mem peak</th><th>Line data</th></tr></thead><tbody>${body}</tbody></table>`;
  $("wall").querySelectorAll("tr[data-id]").forEach((row) => {
    row.addEventListener("click", () => {
      state.selected = row.getAttribute("data-id");
      draw(state.snapshot);
    });
  });
}

function colorFor(time, maxTime) {
  const ratio = maxTime <= 0 ? 0 : time / maxTime;
  const hot = Math.round(80 + ratio * 140);
  return `hsl(${70 - ratio * 70}, 80%, ${48 + ratio * 10}%)`;
}

function findNode(nodes, id) {
  for (const node of nodes) {
    if (node.id === id) {
      return node;
    }
    const hit = findNode(node.children || [], id);
    if (hit) {
      return hit;
    }
  }
  return null;
}

function findPath(nodes, id, trail) {
  const path = trail || [];
  for (const node of nodes) {
    const next = path.concat(node);
    if (node.id === id) {
      return next;
    }
    const hit = findPath(node.children || [], id, next);
    if (hit) {
      return hit;
    }
  }
  return null;
}

function hueFor(id) {
  let hash = 0;
  const key = id || "";
  for (let i = 0; i < key.length; i += 1) {
    hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
  }
  return hash % 360;
}

function branchColor(hue, depth) {
  const light = Math.max(32, 58 - depth * 8);
  return `hsl(${hue}, 72%, ${light}%)`;
}

function rootHue(forest, id) {
  const path = findPath(forest, id);
  if (!path || !path.length) {
    return hueFor(id);
  }
  return hueFor(path[0].id);
}

function nodeValue(node, key) {
  return node[key] || 0;
}

function flattenSunburst(node, start, end, depth, hue, out, key) {
  out.push({ node, start, end, depth, hue });
  const kids = (node.children || []).slice().sort((a, b) => nodeValue(b, key) - nodeValue(a, key));
  if (!kids.length) {
    return;
  }
  const total = kids.reduce((sum, kid) => sum + nodeValue(kid, key), 0) || nodeValue(node, key) || 1;
  let cursor = start;
  const span = end - start;
  for (const kid of kids) {
    const share = (nodeValue(kid, key) / total) * span;
    flattenSunburst(kid, cursor, cursor + share, depth + 1, hue, out, key);
    cursor += share;
  }
}

function flattenForest(nodes, start, end, out, key) {
  const siblings = nodes.slice().sort((a, b) => nodeValue(b, key) - nodeValue(a, key));
  const total = siblings.reduce((sum, node) => sum + nodeValue(node, key), 0) || 1;
  let cursor = start;
  const span = end - start;
  for (const node of siblings) {
    const share = (nodeValue(node, key) / total) * span;
    flattenSunburst(node, cursor, cursor + share, 0, hueFor(node.id), out, key);
    cursor += share;
  }
}

function polar(cx, cy, radius, angle) {
  return [cx + radius * Math.cos(angle), cy + radius * Math.sin(angle)];
}

function arcPath(cx, cy, inner, outer, start, end) {
  const large = end - start > Math.PI ? 1 : 0;
  const [ox1, oy1] = polar(cx, cy, outer, start);
  const [ox2, oy2] = polar(cx, cy, outer, end);
  const [ix2, iy2] = polar(cx, cy, inner, end);
  const [ix1, iy1] = polar(cx, cy, inner, start);
  return `M ${ox1} ${oy1} A ${outer} ${outer} 0 ${large} 1 ${ox2} ${oy2} L ${ix2} ${iy2} A ${inner} ${inner} 0 ${large} 0 ${ix1} ${iy1} Z`;
}

function slicePath(cx, cy, inner, outer, start, end) {
  const span = end - start;
  if (span >= 2 * Math.PI - 1e-6) {
    return `M ${cx + outer} ${cy} A ${outer} ${outer} 0 1 1 ${cx - outer} ${cy} A ${outer} ${outer} 0 1 1 ${cx + outer} ${cy} M ${cx + inner} ${cy} A ${inner} ${inner} 0 1 0 ${cx - inner} ${cy} A ${inner} ${inner} 0 1 0 ${cx + inner} ${cy}`;
  }
  return arcPath(cx, cy, inner, outer, start, end);
}

function sunburstSvg(source, size, centerName, centerValue, forest, key, format) {
  const slices = [];
  const start = -Math.PI / 2;
  const end = start + 2 * Math.PI;
  if (Array.isArray(source)) {
    flattenForest(source, start, end, slices, key);
  } else {
    flattenSunburst(source, start, end, 0, rootHue(forest, source.id), slices, key);
  }
  const depthCount = Math.max(...slices.map((item) => item.depth), 0) + 1;
  const cx = size / 2;
  const cy = size / 2;
  const hole = size * 0.18;
  const ring = (size / 2 - hole - 8) / depthCount;
  const shapes = slices.map((item) => {
    const inner = hole + item.depth * ring;
    const outer = inner + ring;
    const fill = branchColor(item.hue, item.depth);
    const label = `${item.node.name} ${format(nodeValue(item.node, key))}`;
    const selected = state.selected === item.node.id ? "stroke=#c6f06c stroke-width=2" : "stroke=#12141a stroke-width=1";
    const mid = (item.start + item.end) / 2;
    const radius = (inner + outer) / 2;
    const arcLen = (item.end - item.start) * radius;
    const [tx, ty] = polar(cx, cy, radius, mid);
    const ink = Math.max(32, 58 - item.depth * 8) < 45 ? "#e8ead6" : "#12141a";
    const text = arcLen < 28 ? "" : `<text x="${tx}" y="${ty}" text-anchor="middle" dominant-baseline="middle" fill="${ink}" font-size="11">${item.node.name}</text>`;
    return `<g data-id="${item.node.id}" data-depth="${item.depth}"><path d="${slicePath(cx, cy, inner, outer, item.start, item.end)}" fill="${fill}" fill-rule="evenodd" ${selected}></path><title>${label}</title>${text}</g>`;
  }).join("");
  const center = `<text x="${cx}" y="${cy - 8}" text-anchor="middle" fill="#e8ead6" font-size="13">${centerName}</text><text x="${cx}" y="${cy + 12}" text-anchor="middle" fill="#9aa194" font-size="12">${centerValue}</text>`;
  return `<svg viewBox="0 0 ${size} ${size}">${shapes}${center}</svg>`;
}

function pruneZoom(forest, path) {
  const zoom = path.slice();
  while (zoom.length && !findNode(forest, zoom[zoom.length - 1])) {
    zoom.pop();
  }
  return zoom;
}

function bindRingClicks(host, forest, zoomed, zoomKey) {
  host.querySelectorAll("g[data-id]").forEach((node) => {
    node.addEventListener("click", (event) => {
      event.stopPropagation();
      const id = node.getAttribute("data-id");
      const depth = Number(node.getAttribute("data-depth"));
      state.selected = id;
      if (!zoomed) {
        const path = findPath(forest, id) || [];
        state[zoomKey] = path.map((item) => item.id);
      } else if (depth === 0) {
        state[zoomKey] = state[zoomKey].slice(0, -1);
      } else {
        const path = findPath(forest, id) || [];
        state[zoomKey] = path.map((item) => item.id);
      }
      draw(state.snapshot);
    });
  });
}

function bindCrumbs(host, zoomKey) {
  host.querySelectorAll(".crumb button").forEach((button) => {
    button.addEventListener("click", () => {
      const index = Number(button.getAttribute("data-zoom"));
      state[zoomKey] = index < 0 ? [] : state[zoomKey].slice(0, index + 1);
      draw(state.snapshot);
    });
  });
}

function ringPane(forest, zoom, zoomKey, key, format, sessionName) {
  const roots = forest.slice().sort((a, b) => nodeValue(b, key) - nodeValue(a, key)).slice(0, 40);
  const total = roots.reduce((sum, node) => sum + nodeValue(node, key), 0);
  let zoomed = zoom.length > 0;
  const focus = zoomed ? findNode(forest, zoom[zoom.length - 1]) : null;
  if (zoomed && !focus) {
    zoomed = false;
  }
  if (!zoomed && key === "mem" && total <= 0) {
    return { html: "<p class=\"empty\">Memory appears after a traced allocation.</p>", zoomed: false };
  }
  if (zoomed) {
    const crumbs = ["<button type=\"button\" data-zoom=\"-1\">Session</button>"];
    zoom.forEach((id, index) => {
      const node = findNode(forest, id);
      if (!node) {
        return;
      }
      crumbs.push(`<button type=\"button\" data-zoom=\"${index}\">${node.name}</button>`);
    });
    return {
      html: `<p class="crumb">${crumbs.join(" / ")}</p><div class="ring-chart">${sunburstSvg(focus, 520, focus.name, format(nodeValue(focus, key)), forest, key, format)}</div>`,
      zoomed: true,
    };
  }
  return {
    html: `<div class="ring-chart">${sunburstSvg(roots, 520, sessionName, format(total), forest, key, format)}</div>`,
    zoomed: false,
  };
}

function renderRings(snap) {
  const forest = (((snap.function_data || {}).tree || {}).icicle) || [];
  const host = $("rings");
  if (!forest.length) {
    state.zoom = [];
    state.zoomMem = [];
    host.innerHTML = "<p class=\"empty\">Run a marked function to fill the call structure.</p>";
    return;
  }
  state.zoom = pruneZoom(forest, state.zoom);
  state.zoomMem = pruneZoom(forest, state.zoomMem);
  const timePane = ringPane(forest, state.zoom, "zoom", "time", fmtTime, "Runtime");
  const memPane = ringPane(forest, state.zoomMem, "zoomMem", "mem", fmtBytes, "Memory");
  host.innerHTML = `<div class="ring-pair"><div class="ring-pane" data-zoom="zoom"><h3>Time</h3>${timePane.html}</div><div class="ring-pane" data-zoom="zoomMem"><h3>Memory</h3>${memPane.html}</div></div>`;
  host.querySelectorAll(".ring-pane").forEach((pane) => {
    const zoomKey = pane.getAttribute("data-zoom");
    const zoomed = zoomKey === "zoomMem" ? memPane.zoomed : timePane.zoomed;
    bindCrumbs(pane, zoomKey);
    bindRingClicks(pane, forest, zoomed, zoomKey);
  });
}

function renderFunctionTable(snap) {
  const rows = ((snap.function_data || {}).rows) || [];
  const sorted = rows.slice().sort((a, b) => b.cumtime - a.cumtime).slice(0, 40);
  if (!sorted.length) {
    $("functions").innerHTML = "<p class=\"empty\">Function data appears after the first call.</p>";
    return;
  }
  const body = sorted.map((row) => {
    const selected = state.selected === row.id ? " class=\"selected\"" : "";
    return `<tr data-id="${row.id}"${selected}><td>${row.name}</td><td>${row.ncalls}</td><td>${fmtTime(row.tottime)}</td><td>${fmtTime(row.cumtime)}</td><td>${fmtBytes(row.mem_mean)}</td><td>${fmtBytes(row.mem_peak)}</td><td>${row.filename}:${row.firstlineno}</td></tr>`;
  }).join("");
  $("functions").innerHTML = `<table><thead><tr><th>Name</th><th>Calls</th><th>Own time</th><th>Inclusive time</th><th>Mem mean</th><th>Mem peak</th><th>Source</th></tr></thead><tbody>${body}</tbody></table>`;
  $("functions").querySelectorAll("tr[data-id]").forEach((row) => {
    row.addEventListener("click", () => {
      state.selected = row.getAttribute("data-id");
      draw(state.snapshot);
    });
  });
}

function renderGraph(snap) {
  const tree = ((snap.function_data || {}).tree) || {};
  const hottest = (tree.nodes || []).slice().sort((a, b) => b.cumtime - a.cumtime).slice(0, 40);
  const keep = new Set(hottest.map((node) => node.id));
  const nodes = hottest;
  const edges = (tree.edges || []).filter((edge) => keep.has(edge.caller) && keep.has(edge.callee));
  const host = $("graph");
  if (!nodes.length) {
    host.innerHTML = "<p class=\"empty\">The call graph fills with function data.</p>";
    return;
  }
  const incoming = {};
  nodes.forEach((node) => { incoming[node.id] = 0; });
  edges.forEach((edge) => { incoming[edge.callee] = (incoming[edge.callee] || 0) + 1; });
  const depthOf = {};
  const queue = nodes.filter((node) => incoming[node.id] === 0).map((node) => node.id);
  queue.forEach((id) => { depthOf[id] = 0; });
  const children = {};
  edges.forEach((edge) => {
    children[edge.caller] = children[edge.caller] || [];
    children[edge.caller].push(edge.callee);
  });
  for (let i = 0; i < queue.length; i += 1) {
    const id = queue[i];
    for (const child of children[id] || []) {
      const next = (depthOf[id] || 0) + 1;
      if (depthOf[child] == null || next < depthOf[child]) {
        depthOf[child] = next;
        queue.push(child);
      }
    }
  }
  const layers = {};
  nodes.forEach((node) => {
    const depth = depthOf[node.id] || 0;
    layers[depth] = layers[depth] || [];
    layers[depth].push(node);
  });
  const depthCount = Object.keys(layers).length || 1;
  const width = 1000;
  const height = depthCount * 90 + 20;
  const pos = {};
  Object.keys(layers).forEach((depth) => {
    const row = layers[depth];
    row.forEach((node, index) => {
      pos[node.id] = {
        x: ((index + 1) / (row.length + 1)) * width,
        y: Number(depth) * 90 + 30,
      };
    });
  });
  const maxTime = Math.max(...nodes.map((node) => node.cumtime), 0.000001);
  const lines = edges.map((edge) => {
    const a = pos[edge.caller];
    const b = pos[edge.callee];
    if (!a || !b) {
      return "";
    }
    return `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke="#6ec8ff" stroke-opacity="0.45"></line>`;
  }).join("");
  const dots = nodes.map((node) => {
    const point = pos[node.id];
    if (!point) {
      return "";
    }
    const selected = state.selected === node.id ? "stroke=#c6f06c stroke-width=3" : "stroke=#12141a stroke-width=1";
    return `<g data-id="${node.id}"><circle cx="${point.x}" cy="${point.y}" r="14" fill="${colorFor(node.cumtime, maxTime)}" ${selected}></circle><text x="${point.x}" y="${point.y + 28}" text-anchor="middle" fill="#e8ead6" font-size="11">${node.name}</text><title>${node.name} ${fmtTime(node.cumtime)}</title></g>`;
  }).join("");
  host.innerHTML = `<div class="graph"><svg viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" preserveAspectRatio="xMinYMin meet">${lines}${dots}</svg></div>`;
  host.querySelectorAll("g[data-id]").forEach((node) => {
    node.addEventListener("click", () => {
      state.selected = node.getAttribute("data-id");
      draw(state.snapshot);
    });
  });
}

function renderLines(snap) {
  const functions = snap.line_data || [];
  const host = $("lines");
  if (!functions.length) {
    host.innerHTML = "<p class=\"empty\">Mark a function with @pyopsy.profiler(lines=True) to record line data.</p>";
    return;
  }
  let chosen = functions[0];
  if (state.selected) {
    const match = functions.find((item) => `${item.filename}|${item.firstlineno}|${item.name}` === state.selected);
    if (match) {
      chosen = match;
    }
  }
  const byLine = Object.fromEntries((chosen.lines || []).map((row) => [row.lineno, row]));
  const sourceByLine = Object.fromEntries((chosen.source || []).map((row) => [row.lineno, row]));
  const lineNos = new Set([
    ...Object.keys(byLine).map(Number),
    ...Object.keys(sourceByLine).map(Number),
  ]);
  const maxTime = Math.max(0, ...Object.values(byLine).map((row) => row.time));
  const source = [...lineNos].sort((a, b) => a - b).map((lineno) => {
    const stats = byLine[lineno];
    const text = sourceByLine[lineno] ? sourceByLine[lineno].text : "";
    const hits = stats ? stats.hits : "";
    const time = stats ? fmtTime(stats.time) : "";
    const heat = stats && maxTime ? Math.round((stats.time / maxTime) * 70) : 0;
    const light = 12 + heat;
    const ink = light >= 45 ? "#12141a" : "#e8ead6";
    return `<tr><td>${lineno}</td><td>${hits}</td><td>${time}</td><td class="line-src" style="background:hsl(12,80%,${light}%);color:${ink}">${escapeHtml(text)}</td></tr>`;
  }).join("");
  host.innerHTML = `<p>${chosen.name}</p><table><thead><tr><th>Line</th><th>Hits</th><th>Line time</th><th>Source</th></tr></thead><tbody>${source}</tbody></table>`;
}

function escapeHtml(text) {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function draw(root) {
  state.snapshot = root;
  renderProcessSelect(root);
  const snap = currentSnapshot(root);
  if (!snap) {
    return;
  }
  renderSummary(snap);
  renderWall(snap);
  renderRings(snap);
  renderFunctionTable(snap);
  renderGraph(snap);
  renderLines(snap);
}

$("process-select").addEventListener("change", (event) => {
  state.processId = Number(event.target.value);
  draw(state.snapshot);
});

const events = new EventSource("/events");
events.onmessage = (event) => {
  const root = JSON.parse(event.data);
  draw(root);
};

const support = $("support-dialog");
$("support-open").addEventListener("click", () => {
  support.showModal();
});
support.addEventListener("click", (event) => {
  if (event.target === support) {
    support.close();
  }
});
