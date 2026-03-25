(function () {
  function apiUrl(path) {
    var b = (typeof window !== "undefined" && window.API_BASE) ? String(window.API_BASE).replace(/\/$/, "") : "";
    var p = path.charAt(0) === "/" ? path : "/" + path;
    return b ? b + p : p;
  }

  var lastResult = null;
  var csvInput = document.getElementById("csv");
  var btnPreview = document.getElementById("btnPreview");
  var btnRun = document.getElementById("btnRun");
  var previewEl = document.getElementById("preview");
  var timeCol = document.getElementById("timeCol");
  var targetCol = document.getElementById("targetCol");
  var idCol = document.getElementById("idCol");
  var categoryCol = document.getElementById("categoryCol");
  var categoryBox = document.getElementById("categoryBox");
  var btnLoadCats = document.getElementById("btnLoadCats");
  var runMode = document.getElementById("runMode");

  function fillSelect(sel, cols) {
    sel.innerHTML = "";
    cols.forEach(function (c) {
      var o = document.createElement("option");
      o.value = c;
      o.textContent = c;
      sel.appendChild(o);
    });
  }

  function syncRunMode() {
    var m = runMode.value;
    document.getElementById("lblRolling").classList.toggle("hidden", m !== "rolling");
    document.getElementById("lblDirect").classList.toggle("hidden", m !== "direct");
    document.getElementById("lblForecastOnly").classList.toggle("hidden", m !== "forecast_only");
  }

  document.getElementById("btnToggleCfg").onclick = function () {
    var c = document.getElementById("configCard");
    c.classList.toggle("collapsed");
    this.textContent = c.classList.contains("collapsed") ? "show" : "hide";
  };

  runMode.addEventListener("change", syncRunMode);
  syncRunMode();

  csvInput.addEventListener("change", function () {
    btnPreview.disabled = !csvInput.files || !csvInput.files.length;
    btnRun.disabled = !csvInput.files || !csvInput.files.length;
  });

  idCol.addEventListener("change", function () {
    btnLoadCats.disabled = !categoryCol.value || !csvInput.files || !csvInput.files.length;
  });
  categoryCol.addEventListener("change", function () {
    btnLoadCats.disabled = !categoryCol.value || !csvInput.files || !csvInput.files.length;
    categoryBox.classList.add("hidden");
    categoryBox.innerHTML = "";
  });

  btnPreview.addEventListener("click", async function () {
    var fd = new FormData();
    fd.append("file", csvInput.files[0]);
    previewEl.textContent = "Loading…";
    var r = await fetch(apiUrl("/api/preview"), { method: "POST", body: fd });
    var j = await r.json();
    if (!r.ok) {
      previewEl.textContent = (typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail)) || "Error";
      return;
    }
    previewEl.textContent = j.rows + " rows · " + j.columns.length + " columns";
    var cols = j.columns;
    fillSelect(timeCol, cols);
    fillSelect(targetCol, cols);
    if (targetCol.options.length > 1) targetCol.selectedIndex = 1;
    idCol.innerHTML = '<option value="">— single series —</option>';
    cols.forEach(function (c) {
      var o = document.createElement("option");
      o.value = c;
      o.textContent = c;
      idCol.appendChild(o);
    });
    categoryCol.innerHTML = '<option value="">— none —</option>';
    cols.forEach(function (c) {
      var o = document.createElement("option");
      o.value = c;
      o.textContent = c;
      categoryCol.appendChild(o);
    });
    btnLoadCats.disabled = !categoryCol.value || !csvInput.files.length;
  });

  btnLoadCats.addEventListener("click", async function () {
    var col = categoryCol.value;
    if (!col || !csvInput.files[0]) return;
    var fd = new FormData();
    fd.append("file", csvInput.files[0]);
    fd.append("column", col);
    fd.append("limit", "200");
    var r = await fetch(apiUrl("/api/column-values"), { method: "POST", body: fd });
    var j = await r.json();
    if (!r.ok) {
      alert(j.detail || "Failed to load values");
      return;
    }
    categoryBox.innerHTML = "";
    j.values.forEach(function (v, i) {
      var id = "catv_" + i;
      var lab = document.createElement("label");
      lab.className = "inline";
      var cb = document.createElement("input");
      cb.type = "checkbox";
      cb.value = v;
      cb.id = id;
      lab.appendChild(cb);
      lab.appendChild(document.createTextNode(" " + v));
      categoryBox.appendChild(lab);
    });
    categoryBox.classList.remove("hidden");
  });

  function selectedCategories() {
    var cbs = categoryBox.querySelectorAll('input[type="checkbox"]:checked');
    return Array.prototype.map.call(cbs, function (x) { return x.value; });
  }

  function renderTable(rows) {
    var tbody = document.querySelector("#tbl tbody");
    var thead = document.querySelector("#tbl thead");
    tbody.innerHTML = "";
    thead.innerHTML = "";
    if (!rows || !rows.length) return;
    var keys = Object.keys(rows[0]);
    var trh = document.createElement("tr");
    keys.forEach(function (k) {
      var th = document.createElement("th");
      th.textContent = k;
      trh.appendChild(th);
    });
    thead.appendChild(trh);
    rows.forEach(function (row) {
      var tr = document.createElement("tr");
      keys.forEach(function (k) {
        var td = document.createElement("td");
        var v = row[k];
        td.textContent = typeof v === "number" ? (Math.round(v * 1e6) / 1e6).toString() : (v == null ? "" : String(v));
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
  }

  function renderCharts(item) {
    var main = document.getElementById("chartMain");
    var an = document.getElementById("chartAnalysis");
    if (typeof Plotly === "undefined") return;
    var ch = item && item.chart;
    if (!ch) {
      try { Plotly.purge(main); Plotly.purge(an); } catch (e) {}
      return;
    }
    var tH = ch.history.t;
    var yH = ch.history.y;
    var seg = ch.segment || [];
    var tS = seg.map(function (s) { return s.t; });
    var p50 = seg.map(function (s) { return s.p50; });
    var p10 = seg.map(function (s) { return s.p10; });
    var p90 = seg.map(function (s) { return s.p90; });
    var act = seg.map(function (s) { return s.actual; });

    var traces = [];
    traces.push({ x: tH, y: yH, mode: "lines", name: "Observed", line: { color: "#8b98a8", width: 2 } });
    var xBand = tS.concat(tS.slice().reverse());
    var yBand = p90.concat(p10.slice().reverse());
    traces.push({
      x: xBand,
      y: yBand,
      fill: "toself",
      fillcolor: "rgba(61,139,253,0.18)",
      line: { color: "transparent" },
      name: "P10–P90",
      hoverinfo: "skip",
      showlegend: true,
    });
    traces.push({ x: tS, y: p50, mode: "lines+markers", name: "P50", line: { color: "#3d8bfd", width: 2 }, marker: { size: 5 } });
    var hasAct = act.some(function (a) { return a != null && !isNaN(a); });
    if (hasAct) {
      traces.push({
        x: tS,
        y: act,
        mode: "markers",
        name: "Actual (eval)",
        marker: { size: 7, color: "#e7ecf3", line: { width: 1, color: "#3d8bfd" } },
      });
    }
    var layout = {
      paper_bgcolor: "#0f1419",
      plot_bgcolor: "#1a2332",
      font: { color: "#e7ecf3" },
      margin: { t: 36, r: 20, b: 48, l: 56 },
      xaxis: { gridcolor: "#2a3544" },
      yaxis: { gridcolor: "#2a3544" },
      title: "Chronos forecast vs history (" + (item.item_id || "") + ")",
      showlegend: true,
      legend: { orientation: "h" },
    };
    Plotly.newPlot(main, traces, layout, { responsive: true, displayModeBar: true });

    var err = seg.map(function (s) {
      if (s.actual == null || s.p50 == null) return null;
      return Math.abs(s.actual - s.p50);
    });
    var spread = seg.map(function (s) {
      if (s.p90 == null || s.p10 == null) return null;
      return s.p90 - s.p10;
    });
    var traces2 = [
      { x: tS, y: err, mode: "lines+markers", name: "|actual − P50|", line: { color: "#f0a030" } },
      { x: tS, y: spread, mode: "lines+markers", name: "P90 − P10", line: { color: "#5cdb95" }, yaxis: "y2" },
    ];
    var layout2 = {
      paper_bgcolor: "#0f1419",
      plot_bgcolor: "#1a2332",
      font: { color: "#e7ecf3" },
      margin: { t: 36, r: 56, b: 48, l: 56 },
      title: "Error & uncertainty band",
      xaxis: { gridcolor: "#2a3544" },
      yaxis: { gridcolor: "#2a3544", title: "|error|" },
      yaxis2: { overlaying: "y", side: "right", title: "spread", gridcolor: "transparent" },
      showlegend: true,
    };
    if (!hasAct) {
      Plotly.newPlot(an, [{ x: tS, y: spread, mode: "lines+markers", name: "P90 − P10", line: { color: "#5cdb95" } }], {
        paper_bgcolor: "#0f1419",
        plot_bgcolor: "#1a2332",
        font: { color: "#e7ecf3" },
        margin: { t: 36, r: 20, b: 48, l: 56 },
        title: "Forecast uncertainty (no holdout errors)",
        xaxis: { gridcolor: "#2a3544" },
        yaxis: { gridcolor: "#2a3544" },
      }, { responsive: true });
    } else {
      Plotly.newPlot(an, traces2, layout2, { responsive: true });
    }
  }

  function pickItemIndex() {
    var sel = document.getElementById("itemSelect");
    var i = parseInt(sel.value, 10);
    return isNaN(i) ? 0 : i;
  }

  document.getElementById("itemSelect").addEventListener("change", function () {
    if (!lastResult || !lastResult.items) return;
    var idx = pickItemIndex();
    var it = lastResult.items[idx];
    document.getElementById("metrics").textContent = JSON.stringify(it.metrics, null, 2);
    renderTable(it.forecasts || []);
    renderCharts(it);
  });

  btnRun.addEventListener("click", async function () {
    var status = document.getElementById("status");
    var outSection = document.getElementById("outSection");
    status.textContent = "Loading model & forecasting (first run downloads weights)…";
    outSection.classList.add("hidden");
    var fd = new FormData();
    fd.append("file", csvInput.files[0]);
    fd.append("time_col", timeCol.value);
    fd.append("target_col", targetCol.value);
    fd.append("id_col", idCol.value || "");
    fd.append("freq", document.getElementById("freq").value.trim());
    fd.append("model_id", document.getElementById("modelId").value.trim());
    fd.append("run_mode", runMode.value);
    fd.append("rolling_windows", document.getElementById("rollingWindows").value);
    fd.append("direct_horizon", document.getElementById("directHorizon").value);
    fd.append("forecast_horizon", document.getElementById("forecastHorizon").value);
    fd.append("winsorize", document.getElementById("winsorize").checked);
    fd.append("date_start", document.getElementById("dateStart").value);
    fd.append("date_end", document.getElementById("dateEnd").value);
    fd.append("item_ids", document.getElementById("itemIds").value);
    fd.append("category_col", categoryCol.value || "");
    var cats = selectedCategories();
    fd.append("category_values", cats.join(","));

    var r = await fetch(apiUrl("/api/forecast"), { method: "POST", body: fd });
    var j = await r.json();
    if (!r.ok) {
      status.textContent = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
      return;
    }
    lastResult = j;
    status.textContent = "Done.";
    outSection.classList.remove("hidden");

    var lblItem = document.getElementById("lblItemPick");
    var itemSel = document.getElementById("itemSelect");
    itemSel.innerHTML = "";
    if (j.items && j.items.length > 1) {
      lblItem.classList.remove("hidden");
      j.items.forEach(function (it, idx) {
        var o = document.createElement("option");
        o.value = String(idx);
        o.textContent = it.item_id || String(idx);
        itemSel.appendChild(o);
      });
    } else {
      lblItem.classList.add("hidden");
    }

    document.getElementById("metrics").textContent = JSON.stringify(j.aggregate != null ? j.aggregate : (j.items && j.items[0] ? j.items[0].metrics : {}), null, 2);
    var first = (j.items && j.items[0]) ? j.items[0] : {};
    renderTable(first.forecasts || []);
    renderCharts(first);
  });
})();
