// ClipForge frontend logic
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

// ---- tabs ----
$$(".tab").forEach((t) =>
  t.addEventListener("click", () => {
    $$(".tab").forEach((x) => x.classList.remove("active"));
    $$(".panel").forEach((x) => x.classList.remove("active"));
    t.classList.add("active");
    $("#panel-" + t.dataset.tab).classList.add("active");
  })
);

// ---- sliders ----
$("#clip-dur").addEventListener("input", (e) => ($("#clip-dur-val").textContent = e.target.value));
$("#ttv-dur").addEventListener("input", (e) => ($("#ttv-dur-val").textContent = e.target.value));

// ---- ttv mode segmented ----
let ttvMode = "image_story";
$$("#ttv-mode .seg").forEach((b) =>
  b.addEventListener("click", () => {
    $$("#ttv-mode .seg").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    ttvMode = b.dataset.mode;
  })
);

// ---- caption controls ----
function buildCaption(prefix) {
  return `<div class="cap">
    <h4>Caption options</h4>
    <label class="field"><span>Mode</span>
      <select id="${prefix}-cap-mode">
        <option value="auto">Auto (from content)</option>
        <option value="custom">Custom text</option>
        <option value="none">No captions</option>
      </select>
    </label>
    <div id="${prefix}-cap-custom" hidden>
      <label class="field"><span>Custom caption text</span>
        <input type="text" id="${prefix}-cap-text" placeholder="Type your caption..." />
      </label>
    </div>
    <div class="grid">
      <div><label>Font size</label>
        <input type="range" id="${prefix}-cap-size" min="14" max="48" value="28" /></div>
      <div><label>Color</label>
        <input type="color" id="${prefix}-cap-color" value="#ffffff" /></div>
    </div>
    <label class="field"><span>Position</span>
      <select id="${prefix}-cap-pos">
        <option value="bottom">Bottom</option>
        <option value="top">Top</option>
        <option value="center">Center</option>
      </select>
    </label>
  </div>`;
}
$("#clip-caption").innerHTML = buildCaption("clip");
$("#ttv-caption").innerHTML = buildCaption("ttv");

// toggle custom-text visibility
document.addEventListener("change", (e) => {
  if (e.target.id && e.target.id.endsWith("-cap-mode")) {
    const prefix = e.target.id.replace("-cap-mode", "");
    $("#" + prefix + "-cap-custom").hidden = e.target.value !== "custom";
  }
});

function readCaption(prefix) {
  return {
    mode: $("#" + prefix + "-cap-mode").value,
    text: $("#" + prefix + "-cap-text") ? $("#" + prefix + "-cap-text").value : "",
    size: +$("#" + prefix + "-cap-size").value,
    color: $("#" + prefix + "-cap-color").value,
    position: $("#" + prefix + "-cap-pos").value,
  };
}

// ---- result / progress ----
function showResult() { $("#result").hidden = false; $("#done-wrap").hidden = true; $("#err").hidden = true; $("#progress-wrap").hidden = false; }
function setProgress(pct, msg) {
  $("#bar-fill").style.width = pct + "%";
  $("#bar-pct").textContent = Math.round(pct) + "%";
  if (msg) $("#stage-msg").textContent = msg;
}
function showDone(fileUrl) {
  $("#progress-wrap").hidden = true;
  $("#done-wrap").hidden = false;
  const v = $("#player");
  v.src = fileUrl; v.load(); v.play().catch(() => {});
  $("#download").href = fileUrl;
}
function showError(msg) {
  $("#progress-wrap").hidden = true;
  $("#err").hidden = false;
  $("#err").textContent = msg;
}

// ---- job runner ----
let busy = false;
async function startJob(endpoint, payload, btn) {
  if (busy) return;
  busy = true; btn.disabled = true;
  showResult(); setProgress(2, "Submitting...");
  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await safeJson(res);
    if (data === null) { serverDown(); busy = false; btn.disabled = false; return; }
    if (data.error) { showError(data.error); busy = false; btn.disabled = false; return; }
    poll(data.job_id, data.file_url);
  } catch (e) {
    showError("Network error: " + e.message);
    busy = false; btn.disabled = false;
  }
}
// Parse JSON safely; if the response isn't JSON (e.g. the preview server is
// paused/unreachable and the proxy returned an HTML error page) return null.
async function safeJson(res) {
  const ct = res.headers.get("content-type") || "";
  if (!res.ok || !ct.includes("application/json")) return null;
  try { return await res.json(); } catch (e) { return null; }
}
function serverDown() {
  showError("Server not reachable. The in-workspace preview server may have been " +
            "paused between sessions — ask the assistant to relaunch it, or deploy " +
            "to Render/Railway for a stable public link.");
}
function poll(jobId, fileUrl) {
  fetch("/api/status/" + jobId)
    .then(safeJson)
    .then((j) => {
      if (j === null) { serverDown(); busy = false; $("#clip-go").disabled = false; $("#ttv-go").disabled = false; return; }
      setProgress(j.progress || 0, j.message || "Working...");
      if (j.status === "done") { showDone(fileUrl); busy = false; $("#clip-go").disabled = false; $("#ttv-go").disabled = false; }
      else if (j.status === "error") { showError(j.error || "Job failed"); busy = false; $("#clip-go").disabled = false; $("#ttv-go").disabled = false; }
      else { setTimeout(() => poll(jobId, fileUrl), 1500); }
    })
    .catch(() => setTimeout(() => poll(jobId, fileUrl), 2000));
}

// ---- buttons ----
$("#clip-go").addEventListener("click", () => {
  startJob("/api/clip", {
    url: $("#clip-url").value.trim(),
    duration: +$("#clip-dur").value,
    caption: readCaption("clip"),
  }, $("#clip-go"));
});
$("#ttv-go").addEventListener("click", () => {
  startJob("/api/ttv", {
    script: $("#ttv-script").value,
    mode: ttvMode,
    duration: +$("#ttv-dur").value,
    voice: $("#ttv-voice").value,
    music: $("#ttv-music").checked,
    caption: readCaption("ttv"),
  }, $("#ttv-go"));
});

// ---- hero CTAs: scroll to studio + activate the matching tab ----
function activateTab(name) {
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".panel").forEach((p) =>
    p.classList.toggle("active", p.id === "panel-" + name));
}
["hero-clip", "hero-ttv"].forEach((id) => {
  const el = document.getElementById(id);
  if (!el) return;
  el.addEventListener("click", (e) => {
    e.preventDefault();
    activateTab(id === "hero-clip" ? "clip" : "ttv");
    document.getElementById("tool").scrollIntoView({ behavior: "smooth" });
  });
});
