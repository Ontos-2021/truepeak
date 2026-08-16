"use strict";

const COLORS = {
    accent: "#1f6feb",
    ok: "#3fb950",
    warn: "#f0b429",
    bad: "#f85149",
    purple: "#d2a8ff",
    grid: "#21262d",
    text: "#8b949e",
    line: "#e6edf3",
    momentary: "#58a6ff",
    shortTerm: "#f0b429",
    fill: "rgba(31, 111, 235, 0.45)",
    fillRef: "rgba(210, 168, 255, 0.28)",
};

const state = {
    files: [],          // {file, size}
    payload: null,
    activeIndex: 0,
    reference: null,    // analyzed reference result
};

const $ = (id) => document.getElementById(id);

function fmt(value, decimals = 2) {
    if (value === null || value === undefined || Number.isNaN(value)) return "N/A";
    return Number(value).toFixed(decimals);
}

function esc(text) {
    const div = document.createElement("div");
    div.textContent = String(text);
    return div.innerHTML;
}

function humanSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

/* ---------------- canvas helpers ---------------- */

function setupCanvas(canvas) {
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const w = Math.max(rect.width, 10);
    const h = Math.max(rect.height, 10);
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, w, h };
}

function scale(x, fromMin, fromMax, toMin, toMax) {
    if (fromMax === fromMin) return (toMin + toMax) / 2;
    return toMin + ((x - fromMin) / (fromMax - fromMin)) * (toMax - toMin);
}

function drawGrid(ctx, w, h, xTicks, yTicks, opts = {}) {
    const padL = opts.padL ?? 44;
    const padR = opts.padR ?? 10;
    const padT = opts.padT ?? 8;
    const padB = opts.padB ?? 20;
    const plotW = w - padL - padR;
    const plotH = h - padT - padB;
    ctx.strokeStyle = COLORS.grid;
    ctx.lineWidth = 1;
    ctx.font = "10px Consolas, monospace";
    ctx.fillStyle = COLORS.text;
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (const [i, tick] of yTicks.entries()) {
        const y = padT + scale(i, 0, yTicks.length - 1, 0, plotH);
        ctx.beginPath();
        ctx.moveTo(padL, y);
        ctx.lineTo(w - padR, y);
        ctx.stroke();
        ctx.fillText(tick, padL - 6, y);
    }
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (const [i, tick] of xTicks.entries()) {
        const isPos = typeof tick === "object" && tick.x !== undefined;
        const x = isPos
            ? padL + tick.x * plotW
            : padL + scale(i, 0, xTicks.length - 1, 0, plotW);
        ctx.fillText(isPos ? tick.label : tick, x, h - padB + 5);
    }
    return { padL, padR, padT, padB, plotW, plotH };
}

function drawPolyline(ctx, xs, ys, xFrom, xTo, yFrom, yTo, padL, padT, plotW, plotH) {
    ctx.beginPath();
    let started = false;
    for (let i = 0; i < xs.length; i++) {
        if (ys[i] === null || ys[i] === undefined || !Number.isFinite(ys[i])) continue;
        const x = padL + scale(xs[i], xFrom, xTo, 0, plotW);
        const y = padT + scale(ys[i], yFrom, yTo, 0, plotH);
        if (!started) { ctx.moveTo(x, y); started = true; }
        else ctx.lineTo(x, y);
    }
    ctx.stroke();
}

/* ---------------- charts ---------------- */

function drawWaveform(canvas, waveMin, waveMax, duration) {
    const { ctx, w, h } = setupCanvas(canvas);
    ctx.clearRect(0, 0, w, h);
    const xMax = duration && duration > 0 ? duration : 1;
    const n = Math.max(waveMin.length, 2);
    const xs = [];
    for (let i = 0; i < n; i++) xs.push((i / (n - 1)) * xMax);
    const grid = drawGrid(ctx, w, h, ["0", "25%", "50%", "75%", "100%"], ["+1", "0", "-1"], { padL: 40 });
    ctx.fillStyle = COLORS.fill;
    ctx.beginPath();
    for (let i = 0; i < n; i++) {
        const x = grid.padL + scale(xs[i], 0, xMax, 0, grid.plotW);
        if (i === 0) ctx.moveTo(x, grid.padT + grid.plotH);
        else ctx.lineTo(x, grid.padT + grid.plotH);
    }
    for (let i = n - 1; i >= 0; i--) {
        const x = grid.padL + scale(xs[i], 0, xMax, 0, grid.plotW);
        const y = grid.padT + scale(Math.max(waveMax[i] ?? 0, 0), 1, -1, 0, grid.plotH);
        ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.fill();
    drawPolyline(ctx, xs, waveMax, 0, xMax, 1, -1, grid.padL, grid.padT, grid.plotW, grid.plotH);
}

function drawTimeline(canvas, result, reference) {
    const { ctx, w, h } = setupCanvas(canvas);
    ctx.clearRect(0, 0, w, h);
    const momT = result.timeline.t_momentary;
    const mom = result.timeline.momentary;
    const stT = result.timeline.t_short_term;
    const st = result.timeline.short_term;
    const all = mom.concat(st).filter((v) => v !== null && Number.isFinite(v));
    const dur = result.duration_s || Math.max(...(momT.length ? momT : stT), 1);
    if (!all.length) {
        ctx.fillStyle = COLORS.text;
        ctx.font = "13px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("No loudness data (signal too short or silent)", w / 2, h / 2);
        return;
    }
    const yMax = Math.max(...all);
    const yMin = Math.min(...all);
    const pad = Math.max((yMax - yMin) * 0.08, 1);
    const ticks = [-6, -12, -18, -24, -30, -36].filter((t) => t >= yMin - 2 && t <= yMax + 2);
    const grid = drawGrid(ctx, w, h, ["0", "25%", "50%", "75%", "100%"], ticks, { padL: 48 });
    const durTicks = [];
    for (let i = 0; i <= 4; i++) durTicks.push(((dur / 4) * i).toFixed(0));
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (let i = 0; i < 5; i++) {
        const x = grid.padL + scale(i, 0, 4, 0, grid.plotW);
        ctx.fillText(durTicks[i] + "s", x, h - grid.padB + 5);
    }
    ctx.strokeStyle = COLORS.bad;
    ctx.setLineDash([5, 4]);
    drawHLine(ctx, grid, yMax + pad, yMin - pad, -14, "Spotify -14");
    ctx.setLineDash([]);
    const integrated = result.analysis.loudness_integrated_lufs;
    if (integrated !== null && integrated !== undefined) {
        ctx.strokeStyle = COLORS.ok;
        drawHLine(ctx, grid, yMax + pad, yMin - pad, integrated, "integrated " + integrated.toFixed(1));
    }
    ctx.strokeStyle = COLORS.shortTerm;
    ctx.lineWidth = 1.6;
    drawPolyline(ctx, stT, st, 0, dur, yMax + pad, yMin - pad, grid.padL, grid.padT, grid.plotW, grid.plotH);
    ctx.strokeStyle = COLORS.momentary;
    ctx.lineWidth = 0.8;
    drawPolyline(ctx, momT, mom, 0, dur, yMax + pad, yMin - pad, grid.padL, grid.padT, grid.plotW, grid.plotH);
    if (reference) {
        const rSt = reference.timeline.short_term;
        const rT = reference.timeline.t_short_term;
        const rDur = reference.duration_s || 1;
        if (rSt.length) {
            ctx.strokeStyle = COLORS.purple;
            ctx.lineWidth = 1.3;
            ctx.setLineDash([3, 3]);
            drawPolyline(ctx, rT, rSt, 0, Math.max(dur, rDur), yMax + pad, yMin - pad, grid.padL, grid.padT, grid.plotW, grid.plotH);
            ctx.setLineDash([]);
        }
    }
    const legend = [
        [COLORS.momentary, "momentary"],
        [COLORS.shortTerm, "short-term"],
        [COLORS.ok, "integrated"],
        [COLORS.purple, "reference"],
    ];
    ctx.font = "10px sans-serif";
    ctx.textAlign = "left";
    let lx = grid.padL;
    for (const [color, label] of legend) {
        ctx.fillStyle = color;
        ctx.fillRect(lx, 6, 12, 3);
        ctx.fillStyle = COLORS.text;
        ctx.fillText(label, lx + 16, 2);
        lx += 16 + ctx.measureText(label).width + 14;
    }
}

function drawHLine(ctx, grid, yFrom, yTo, value, label) {
    if (value < yFrom || value > yTo) return;
    const y = grid.padT + scale(value, yFrom, yTo, 0, grid.plotH);
    ctx.beginPath();
    ctx.moveTo(grid.padL, y);
    ctx.lineTo(grid.padL + grid.plotW, y);
    ctx.stroke();
    ctx.font = "10px Consolas, monospace";
    ctx.fillStyle = COLORS.bad;
    ctx.textAlign = "left";
    const labelW = ctx.measureText(label).width;
    ctx.fillText(label, grid.padL + grid.plotW - labelW - 4, y - 3);
}

function drawSpectrum(canvas, spectrum, reference) {
    const { ctx, w, h } = setupCanvas(canvas);
    ctx.clearRect(0, 0, w, h);
    if (!spectrum || !spectrum.freqs.length) {
        ctx.fillStyle = COLORS.text;
        ctx.font = "13px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("No spectrum data", w / 2, h / 2);
        return;
    }
    const db = spectrum.db;
    const valid = db.filter((v) => v !== null && Number.isFinite(v));
    const refDb = reference && reference.spectrum ? reference.spectrum.db : null;
    const refValid = refDb ? refDb.filter((v) => v !== null && Number.isFinite(v)) : [];
    const allVals = valid.concat(refValid);
    const yMin = Math.min(...allVals, -90);
    const yMax = Math.max(...allVals, -10);
    const pad = Math.max((yMax - yMin) * 0.05, 1);
    const ticks = [];
    for (let v = Math.ceil(yMin); v <= yMax; v += 6) ticks.push(v);
    const logMin = Math.log10(20);
    const logMax = Math.log10(20000);
    const logTicks = [20, 100, 1000, 10000, 20000].map((f) => ({
        x: (Math.log10(f) - logMin) / (logMax - logMin),
        label: f >= 1000 ? (f / 1000) + "k" : String(f),
    }));
    const grid = drawGrid(ctx, w, h, logTicks, ticks, { padL: 46 });
    const n = spectrum.freqs.length;
    const drawBand = (freqs, values, color, dash) => {
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.8;
        if (dash) ctx.setLineDash(dash);
        ctx.beginPath();
        let started = false;
        for (let i = 0; i < n; i++) {
            const v = values[i];
            if (v === null || v === undefined || !Number.isFinite(v)) continue;
            const x = grid.padL + scale(Math.log10(freqs[i]), logMin, logMax, 0, grid.plotW);
            const y = grid.padT + scale(v, yMax + pad, yMin - pad, 0, grid.plotH);
            if (!started) { ctx.moveTo(x, y); started = true; }
            else ctx.lineTo(x, y);
        }
        ctx.stroke();
        ctx.setLineDash([]);
    };
    if (refDb) drawBand(spectrum.freqs, refDb, COLORS.purple, [4, 4]);
    drawBand(spectrum.freqs, db, COLORS.accent, null);
    ctx.font = "10px sans-serif";
    ctx.textAlign = "left";
    ctx.fillStyle = COLORS.accent;
    ctx.fillRect(grid.padL, 6, 12, 3);
    ctx.fillStyle = COLORS.text;
    ctx.fillText("this track", grid.padL + 16, 2);
    if (refDb) {
        const w2 = ctx.measureText("this track").width;
        ctx.fillStyle = COLORS.purple;
        ctx.fillRect(grid.padL + 16 + w2 + 14, 6, 12, 3);
        ctx.fillStyle = COLORS.text;
        ctx.fillText("reference", grid.padL + 16 + w2 + 30, 2);
    }
}

function drawBars(canvas, labels, values, opts = {}) {
    const { ctx, w, h } = setupCanvas(canvas);
    ctx.clearRect(0, 0, w, h);
    const valid = values.filter((v) => v !== null && v !== undefined && Number.isFinite(v));
    if (!valid.length) {
        ctx.fillStyle = COLORS.text;
        ctx.font = "13px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("No data", w / 2, h / 2);
        return;
    }
    const yMax = Math.max(...valid, opts.target ?? -1);
    const yMin = Math.min(...valid, opts.target ?? -20) - 2;
    const ticks = [];
    for (let v = Math.ceil(yMin); v <= yMax; v += 3) ticks.push(v);
    const grid = drawGrid(ctx, w, h, [], ticks, { padL: 46, padB: 34 });
    const n = labels.length;
    const slot = grid.plotW / n;
    const barW = Math.min(slot * 0.6, 46);
    for (let i = 0; i < n; i++) {
        const v = values[i];
        const x = grid.padL + slot * i + (slot - barW) / 2;
        const yBase = grid.padT + grid.plotH;
        const y = grid.padT + scale(v, yMax, yMin, 0, grid.plotH);
        ctx.fillStyle = COLORS.accent;
        ctx.fillRect(x, y, barW, yBase - y);
        ctx.fillStyle = COLORS.text;
        ctx.font = "10px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText(shortName(labels[i]), x + barW / 2, yBase + 6);
        if (v !== null && v !== undefined && Number.isFinite(v)) {
            ctx.textBaseline = "bottom";
            ctx.fillText(v.toFixed(1), x + barW / 2, y - 2);
            ctx.textBaseline = "alphabetic";
        }
    }
    if (opts.target !== undefined) {
        const y = grid.padT + scale(opts.target, yMax, yMin, 0, grid.plotH);
        ctx.strokeStyle = COLORS.bad;
        ctx.setLineDash([5, 4]);
        ctx.beginPath();
        ctx.moveTo(grid.padL, y);
        ctx.lineTo(w - grid.padR, y);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = COLORS.bad;
        ctx.font = "10px sans-serif";
        ctx.textAlign = "right";
        ctx.fillText(opts.targetLabel || ("target " + opts.target), w - grid.padR, y - 4);
    }
}

function shortName(name, max = 16) {
    return name.length > max ? name.slice(0, max - 1) + "…" : name;
}

/* ---------------- queue & upload ---------------- */

function addFiles(fileList) {
    for (const file of fileList) {
        if (state.files.some((f) => f.file.name === file.name && f.file.size === file.size)) continue;
        state.files.push({ file });
    }
    renderQueue();
}

function renderQueue() {
    const list = $("fileList");
    list.innerHTML = "";
    let total = 0;
    for (const entry of state.files) {
        total += entry.file.size;
        const li = document.createElement("li");
        li.innerHTML = `
            <span class="fname">${esc(entry.file.name)}</span>
            <span class="fmeta">${humanSize(entry.file.size)}</span>
            <button class="btn ghost small" data-remove>Remove</button>`;
        li.querySelector("[data-remove]").addEventListener("click", () => {
            state.files = state.files.filter((f) => f !== entry);
            renderQueue();
        });
        list.appendChild(li);
    }
    $("queueSize").textContent = humanSize(total);
    $("queue").classList.toggle("hidden", !state.files.length);
    $("analyzeBtn").disabled = !state.files.length;
}

function setBusy(busy) {
    const wrap = $("progressWrap");
    const bar = $("progressBar");
    $("analyzeBtn").disabled = busy || !state.files.length;
    if (!busy) {
        wrap.classList.add("hidden");
        bar.classList.remove("busy");
        bar.style.width = "0%";
        return;
    }
    wrap.classList.remove("hidden");
    bar.classList.add("busy");
    bar.style.width = "100%";
}

function setStatus(text) {
    $("statusLine").textContent = text;
}

function showError(message) {
    const banner = $("errorBanner");
    banner.textContent = message;
    banner.classList.remove("hidden");
    setTimeout(() => banner.classList.add("hidden"), 8000);
}

function submitAnalysis() {
    const formData = new FormData();
    for (const entry of state.files) formData.append("file", entry.file, entry.file.name);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/analyze");
    xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
            $("progressWrap").classList.remove("hidden");
            const bar = $("progressBar");
            bar.classList.remove("busy");
            bar.style.width = Math.round((e.loaded / e.total) * 100) + "%";
        }
    };
    xhr.onload = () => {
        setBusy(false);
        let data = null;
        try { data = JSON.parse(xhr.responseText); } catch (_) { /* ignore */ }
        if (xhr.status !== 200 || !data) {
            showError(data && data.error ? data.error : "Analysis failed. Please try again.");
            return;
        }
        state.payload = data;
        state.activeIndex = 0;
        renderAll();
        if ($("autoPdf").checked) downloadPdf();
    };
    xhr.onerror = () => {
        setBusy(false);
        showError("Network error. Is the server running?");
    };
    setBusy(true);
    setStatus("Analyzing " + state.files.length + " file(s)...");
    xhr.send(formData);
}

/* ---------------- rendering ---------------- */

function renderAll() {
    const payload = state.payload;
    $("results").classList.remove("hidden");
    $("exportBar").classList.remove("hidden");
    renderAlbum(payload);
    renderTabs(payload.results);
    renderTrack(state.activeIndex);
}

function renderAlbum(payload) {
    const album = payload.album;
    const card = $("albumCard");
    const valid = payload.results.filter((r) => !r.error);
    let html = `<div class="card-head"><h2>Album / batch summary</h2></div>`;
    if (!valid.length) {
        html += `<p class="muted">No tracks could be analyzed.</p>`;
        card.innerHTML = html;
        return;
    }
    html += `<div class="chips">
        <div class="chip"><div class="c-label">Tracks</div><div class="c-value">${album.track_count}</div></div>
        <div class="chip"><div class="c-label">LUFS spread</div><div class="c-value">${fmt(album.lufs_spread_lu)} LU</div></div>
        <div class="chip"><div class="c-label">Max true peak</div><div class="c-value">${fmt(album.max_true_peak_dbtp)} dBTP</div></div>
        <div class="chip"><div class="c-label">Avg LRA</div><div class="c-value">${fmt(album.mean_lra_lu)} LU</div></div>
    </div>`;
    if (payload.results.length > 1) {
        const names = valid.map((r) => r.filename);
        const lufs = valid.map((r) => r.analysis.loudness_integrated_lufs);
        const tp = valid.map((r) => r.analysis.true_peak_dbtp);
        const lra = valid.map((r) => r.analysis.lra_lu);
        html += `<div class="chart-wrap"><h3>Integrated loudness by track</h3>
            <canvas class="chart" id="albumLufsChart"></canvas></div>
            <div class="chart-wrap"><h3>True peak by track</h3>
            <canvas class="chart" id="albumTpChart"></canvas></div>
            <div class="chart-wrap"><h3>Loudness range by track</h3>
            <canvas class="chart" id="albumLraChart"></canvas></div>`;
    }
    card.innerHTML = html;
    if (payload.results.length > 1) {
        drawBars($("albumLufsChart"), names, lufs, { target: -14, targetLabel: "Spotify -14" });
        drawBars($("albumTpChart"), names, tp, { target: -1, targetLabel: "-1 dBTP" });
        drawBars($("albumLraChart"), names, lra);
    }
}

function renderTabs(results) {
    const tabs = $("tabs");
    tabs.innerHTML = "";
    results.forEach((result, i) => {
        const tab = document.createElement("button");
        tab.className = "tab" + (i === state.activeIndex ? " active" : "") + (result.error ? " error-tab" : "");
        tab.textContent = shortName(result.filename, 34);
        tab.addEventListener("click", () => {
            state.activeIndex = i;
            renderTabs(results);
            renderTrack(i);
        });
        tabs.appendChild(tab);
    });
}

function metricClass(metric, value) {
    if (value === null || value === undefined) return "";
    switch (metric) {
        case "true_peak_dbtp":
            return value > 0 ? "bad" : value > -1 ? "warn" : "ok";
        case "sample_peak_dbfs":
            return value >= 0 ? "bad" : value >= -0.5 ? "warn" : "ok";
        case "phase_correlation":
            return value >= 0.9 ? "ok" : value >= 0.5 ? "warn" : "bad";
        case "lr_balance_db":
            return Math.abs(value) <= 1 ? "ok" : Math.abs(value) <= 3 ? "warn" : "bad";
        case "lra_lu":
            return value <= 12 ? "ok" : "warn";
        default:
            return "";
    }
}

function renderTrack(index) {
    const result = state.payload.results[index];
    const container = $("trackPanels");
    if (result.error) {
        container.innerHTML = `
            <div class="panel card">
                <h2 class="v-bad">${esc(result.filename)}</h2>
                <p class="v-bad">Error: ${esc(result.error)}</p>
            </div>`;
        return;
    }
    const a = result.analysis;
    const metrics = [
        ["loudness_integrated_lufs", "Integrated", "LUFS"],
        ["true_peak_dbtp", "True peak", "dBTP"],
        ["sample_peak_dbfs", "Sample peak", "dBFS"],
        ["short_term_max_lufs", "Max short-term", "LUFS"],
        ["momentary_max_lufs", "Max momentary", "LUFS"],
        ["lra_lu", "LRA", "LU"],
        ["plr_db", "PLR", "dB"],
        ["crest_factor_db", "Crest factor", "dB"],
        ["rms_db", "RMS", "dB"],
        ["phase_correlation", "Correlation", ""],
        ["lr_balance_db", "L/R balance", "dB"],
        ["duration_s", "Duration", "s"],
    ];
    let html = `<div class="panel card">
        <div class="track-title">
            <h2>${esc(result.filename)}</h2>
            <span class="track-meta">${result.duration_s.toFixed(1)} s &middot; ${result.sample_rate} Hz &middot; ${result.channels} ch</span>
        </div>
        <div class="metrics-grid">`;
    for (const [key, label, unit] of metrics) {
        const value = a[key];
        const cls = metricClass(key, value);
        const display = key === "phase_correlation"
            ? (value === null || value === undefined ? "N/A" : value.toFixed(3))
            : fmt(value);
        html += `<div class="metric ${cls}">
            <div class="m-label">${label}</div>
            <div class="m-value">${display} <span class="m-unit">${unit}</span></div>
        </div>`;
    }
    if (a.clipping) {
        html += `<div class="metric bad">
            <div class="m-label">Clipping detected</div>
            <div class="m-value">${a.clipping.runs} events</div>
        </div>`;
    } else {
        html += `<div class="metric ok"><div class="m-label">Clipping</div><div class="m-value">None</div></div>`;
    }
    html += `</div>`;

    const verdicts = result.verdicts || [];
    if (verdicts.length) {
        html += `<h3 style="font-size:13px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px">Platform readiness</h3>
        <div class="verdicts">`;
        for (const v of verdicts) {
            const gain = v.playback_gain_db;
            let gainText = "n/a";
            let gainClass = "";
            if (gain !== null) {
                if (gain > 1) { gainText = "+" + gain.toFixed(1) + " dB boost"; gainClass = "v-ok"; }
                else if (gain < -1) { gainText = gain.toFixed(1) + " dB cut"; gainClass = "v-warn"; }
                else { gainText = "on target"; gainClass = "v-ok"; }
            }
            let tpText = "TP n/a";
            let tpClass = "v-warn";
            if (v.true_peak_ok !== null) {
                tpText = v.true_peak_ok ? "TP OK" : "TP exceeds " + v.max_tp_dbtp.toFixed(1) + " dBTP";
                tpClass = v.true_peak_ok ? "v-ok" : "v-bad";
            }
            html += `<div class="verdict">
                <div>
                    <div class="v-label">${esc(v.label)}</div>
                    <div class="v-target">target ${v.target_lufs.toFixed(0)} LUFS</div>
                </div>
                <div style="text-align:right">
                    <div class="v-gain ${gainClass}">${gainText}</div>
                    <div class="v-tp ${tpClass}">${tpText}</div>
                </div>
            </div>`;
        }
        html += `</div>`;
    }

    html += `<div class="chart-wrap"><h3>Loudness over time (LUFS)</h3>
        <canvas class="chart" id="timelineChart"></canvas></div>
        <div class="chart-wrap"><h3>Waveform</h3>
        <canvas class="chart" id="waveformChart" style="height:140px"></canvas></div>
        <div class="chart-wrap"><h3>Average spectrum (1/3 octave)</h3>
        <canvas class="chart" id="spectrumChart"></canvas></div>`;

    html += `<div class="normalize">
        <div class="card-head"><h2>Normalize to target</h2></div>
        <div class="n-fields">
            <div class="field"><label>Target LUFS</label><input id="normTarget" type="number" step="0.5" min="-30" max="-5" value="-14"></div>
            <div class="field"><label>TP ceiling (dBTP)</label><input id="normCeiling" type="number" step="0.1" min="-6" max="0" value="-1"></div>
            <label class="check"><input type="checkbox" id="normLimiter" checked> Use limiter if needed</label>
            <button id="normBtn" class="btn primary">Normalize</button>
        </div>
        <div id="normResult" class="n-result"></div>
    </div></div>`;

    container.innerHTML = html;
    drawTimeline($("timelineChart"), result, state.reference);
    drawWaveform($("waveformChart"), result.waveform.min, result.waveform.max, result.duration_s);
    drawSpectrum($("spectrumChart"), result.spectrum, state.reference);
    wireNormalize(result);
}

/* ---------------- normalize ---------------- */

function wireNormalize(result) {
    const fileEntry = state.files.find(
        (f) => f.file.name === result.filename.replace(/^[0-9a-f]{32}_/, "") ||
              f.file.name === result.filename
    );
    $("normBtn").addEventListener("click", () => {
        const file = fileEntry ? fileEntry.file : null;
        if (!file) {
            $("normResult").innerHTML = `<span class="v-bad">Original file no longer available in this session.</span>`;
            return;
        }
        const formData = new FormData();
        formData.append("file", file, file.name);
        formData.append("target_lufs", $("normTarget").value);
        formData.append("max_tp_dbtp", $("normCeiling").value);
        formData.append("use_limiter", $("normLimiter").checked ? "1" : "0");
        const btn = $("normBtn");
        btn.disabled = true;
        btn.textContent = "Processing...";
        fetch("/normalize", { method: "POST", body: formData })
            .then((resp) => resp.json().then((data) => ({ resp, data })))
            .then(({ resp, data }) => {
                if (!resp.ok) throw new Error(data.error || "Normalization failed");
                const d = data;
                $("normResult").innerHTML = `
                    <span class="chip"><span class="c-label">Before</span><span class="c-value">${fmt(d.before.loudness_integrated_lufs)} LUFS</span></span>
                    <span class="chip"><span class="c-label">After</span><span class="c-value">${fmt(d.after.loudness_integrated_lufs)} LUFS</span></span>
                    <span class="chip"><span class="c-label">Gain</span><span class="c-value">${d.gain_db.toFixed(2)} dB</span></span>
                    <span class="chip"><span class="c-label">Limiter</span><span class="c-value">${d.limiter_applied ? "used" : "not needed"}</span></span>
                    <span class="chip"><span class="c-label">Final TP</span><span class="c-value ${d.after.true_peak_dbtp > d.max_tp_dbtp ? "v-bad" : "v-ok"}">${fmt(d.after.true_peak_dbtp)} dBTP</span></span>
                    <a class="btn primary" href="${d.download_url}">Download WAV</a>`;
            })
            .catch((err) => {
                $("normResult").innerHTML = `<span class="v-bad">${esc(err.message)}</span>`;
            })
            .finally(() => {
                btn.disabled = false;
                btn.textContent = "Normalize";
            });
    });
}

/* ---------------- export ---------------- */

function downloadBlob(blob, filename) {
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    setTimeout(() => window.URL.revokeObjectURL(url), 1000);
}

function postBlob(path, body, filename, label) {
    fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    })
        .then((resp) => {
            if (!resp.ok) return resp.json().then((d) => { throw new Error(d.error || label + " failed"); });
            return resp.blob();
        })
        .then((blob) => downloadBlob(blob, filename))
        .catch((err) => showError(err.message));
}

function downloadPdf() {
    if (!state.payload) return;
    postBlob("/export/pdf", { results: state.payload.results, album: state.payload.album }, "truepeak_report.pdf", "PDF export");
}

function downloadCsv() {
    if (!state.payload) return;
    postBlob("/export/csv", { results: state.payload.results }, "truepeak_analysis.csv", "CSV export");
}

/* ---------------- reference track ---------------- */

function analyzeReference(file) {
    const formData = new FormData();
    formData.append("file", file, file.name);
    const status = $("refStatus");
    status.classList.remove("hidden");
    status.textContent = "Analyzing reference...";
    fetch("/analyze", { method: "POST", body: formData })
        .then((resp) => resp.json())
        .then((data) => {
            const result = data.results && data.results[0];
            if (!result || result.error) {
                status.textContent = "Reference analysis failed";
                return;
            }
            state.reference = result;
            status.textContent = "Reference: " + shortName(result.filename, 20);
            if (state.payload) {
                renderTrack(state.activeIndex);
                renderAlbum(state.payload);
            }
        })
        .catch(() => { status.textContent = "Reference analysis failed"; });
}

/* ---------------- init ---------------- */

function init() {
    const dz = $("dropzone");
    const fileInput = $("fileInput");
    const refInput = $("refInput");

    dz.addEventListener("click", () => fileInput.click());
    dz.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); }
    });
    fileInput.addEventListener("change", () => { addFiles(fileInput.files); fileInput.value = ""; });
    ["dragenter", "dragover"].forEach((ev) =>
        dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("dragover"); }));
    ["dragleave", "drop"].forEach((ev) =>
        dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("dragover"); }));
    dz.addEventListener("drop", (e) => { if (e.dataTransfer && e.dataTransfer.files) addFiles(e.dataTransfer.files); });

    $("analyzeBtn").addEventListener("click", submitAnalysis);
    $("clearBtn").addEventListener("click", () => { state.files = []; renderQueue(); });
    $("downloadPdf").addEventListener("click", downloadPdf);
    $("downloadCsv").addEventListener("click", downloadCsv);

    refInput.addEventListener("change", () => {
        if (refInput.files && refInput.files[0]) analyzeReference(refInput.files[0]);
        refInput.value = "";
    });
}

document.addEventListener("DOMContentLoaded", init);
