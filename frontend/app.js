(() => {
  const $ = (id) => document.getElementById(id);
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* storage unavailable */ } },
  };
  const CHECK_NAMES = {
    FOLIO_IDENTITY: "Folio identity", KYC_STATUS: "KYC status", THIRD_PARTY_PAYMENT: "Third-party payment",
    BANK_MANDATE: "Bank mandate", COB_COOLING: "Change-of-bank cooling", DISTRIBUTOR_CODE: "Distributor code",
    MINOR_RULES: "Minor rules", REFERRAL: "Referral triggers",
  };
  let samples = [];
  let attachments = []; // {file_name, content_type, content_base64}

  // ---------------------------------------------------------------- API base + health
  const apiBase = () => ($("apiBase").value || "").trim().replace(/\/+$/, "");
  $("apiBase").value = store.get("tccApiBase") || window.TCC_API_BASE || "";

  async function checkHealth() {
    const dot = $("health");
    dot.className = "dot"; dot.title = "checking…";
    try {
      const r = await fetch(apiBase() + "/health", { cache: "no-store" });
      const j = await r.json();
      const ok = r.ok && j.status === "ok";
      dot.className = "dot " + (ok ? "ok" : "bad");
      dot.title = ok ? "API reachable" : "API responded but not healthy";
    } catch (e) {
      dot.className = "dot bad";
      dot.title = "API not reachable: " + e.message;
    }
  }
  $("saveApi").addEventListener("click", () => { store.set("tccApiBase", apiBase()); checkHealth(); });
  checkHealth();

  // ---------------------------------------------------------------- samples
  fetch("samples.json").then((r) => r.json()).then((list) => {
    samples = list;
    const sel = $("sample");
    list.forEach((s, i) => {
      const o = document.createElement("option");
      o.value = String(i);
      o.textContent = `${s.request_id} · ${s.subject.slice(0, 60)}`;
      sel.appendChild(o);
    });
  }).catch(() => { /* samples optional */ });

  $("sample").addEventListener("change", (e) => {
    const s = samples[Number(e.target.value)];
    if (!s) return;
    $("request_id").value = s.request_id;
    $("received_at").value = s.received_at;
    $("from").value = s.from;
    $("subject").value = s.subject;
    $("body").value = s.body;
    attachments = (s.attachments || []).map((a) => ({ ...a }));
    $("files").value = "";
    renderAtts();
  });

  // ---------------------------------------------------------------- attachments
  function renderAtts() {
    const ul = $("attList");
    ul.innerHTML = "";
    attachments.forEach((a) => {
      const li = document.createElement("li");
      li.textContent = `📎 ${a.file_name}`;
      ul.appendChild(li);
    });
  }
  const toB64 = (file) => new Promise((res, rej) => {
    const fr = new FileReader();
    fr.onload = () => res(String(fr.result).split(",")[1] || "");
    fr.onerror = () => rej(fr.error);
    fr.readAsDataURL(file);
  });
  $("files").addEventListener("change", async (e) => {
    const added = await Promise.all([...e.target.files].map(async (f) => ({
      file_name: f.name, content_type: f.type || "application/octet-stream", content_base64: await toB64(f),
    })));
    attachments = attachments.concat(added);
    renderAtts();
  });

  function defaults() {
    if (!$("request_id").value) $("request_id").value = "UI-" + Date.now().toString(36).toUpperCase();
    if (!$("received_at").value) {
      const d = new Date(Date.now() + 330 * 60000).toISOString().slice(0, 19); // IST wall time
      $("received_at").value = d + "+05:30";
    }
  }
  defaults();

  $("clear").addEventListener("click", () => {
    ["request_id", "received_at", "from", "subject", "body"].forEach((id) => { $(id).value = ""; });
    attachments = []; $("files").value = ""; $("sample").value = "";
    renderAtts(); defaults();
  });

  // ---------------------------------------------------------------- submit
  $("form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      request_id: $("request_id").value.trim(), received_at: $("received_at").value.trim(), channel: "email",
      from: $("from").value.trim(), to: "TCC Desk <tcc.desk@validus-rta.example>", cc: "",
      subject: $("subject").value, body: $("body").value, attachments,
    };
    $("empty").hidden = true; $("out").hidden = true; $("error").hidden = true; $("loading").hidden = false;
    $("submit").disabled = true;
    try {
      const r = await fetch(apiBase() + "/requests", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      });
      const j = await r.json();
      render(j);
      if (j.error) showError("The service returned its safe fallback: " + j.error);
    } catch (err) {
      showError(`Could not reach the API at ${apiBase() || "(not set)"}.\n${err.message}\n\nCheck the API URL in the header (and that the backend allows this origin via CORS_ORIGINS).`);
      $("empty").hidden = false;
    } finally {
      $("loading").hidden = true; $("submit").disabled = false;
    }
  });

  function showError(msg) { const b = $("error"); b.textContent = msg; b.hidden = false; }

  // ---------------------------------------------------------------- render
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };

  function render(j) {
    $("out").hidden = false;
    const o = $("outcome");
    o.textContent = (j.outcome || "").replaceAll("_", " ");
    o.className = "badge o-" + j.outcome;
    $("approval").textContent = j.human_approval_required
      ? (j.approver_role === "OPS_MANAGER" ? "Operations Manager" : "TCC Checker") + " must approve"
      : "None (maker outcome)";
    $("rtype").textContent = (j.request_type || "").replaceAll("_", " ");

    const chips = $("reasons"); chips.innerHTML = "";
    (j.reason_codes || []).forEach((c) => chips.appendChild(el("span", "chip", c)));
    if (!(j.reason_codes || []).length) chips.appendChild(el("span", "chip", "no reason codes"));

    const res = $("resolved"); res.innerHTML = "";
    const r = j.resolved || {};
    [["Folio", r.folio_no], ["AMC", r.amc_code], ["First holder PAN", r.first_holder_pan_masked], ["Transaction", r.txn_id]]
      .forEach(([k, v]) => { const d = el("div"); d.append(el("dt", null, k), el("dd", null, v || "—")); res.appendChild(d); });

    const box = $("checks"); box.innerHTML = "";
    (j.checks || []).forEach((c) => {
      const d = el("details", "check");
      if (c.result === "FAIL" || c.result === "UNABLE_TO_VERIFY") d.open = true;
      const s = el("summary");
      s.append(el("span", "r r-" + c.result, c.result.replaceAll("_", " ")), el("span", "cid", CHECK_NAMES[c.check_id] || c.check_id),
        el("span", "clause", c.sop_clause || ""));
      d.appendChild(s);
      const ul = el("ul", "ev");
      (c.evidence || []).forEach((e) => {
        const li = el("li");
        li.append(el("span", "src", `${e.source} · ${e.ref}`), document.createElement("br"), document.createTextNode(e.value));
        ul.appendChild(li);
      });
      d.appendChild(ul);
      box.appendChild(d);
    });

    const dr = j.draft_reply || {};
    $("rto").textContent = dr.to || ""; $("rsubj").textContent = dr.subject || ""; $("rbody").textContent = dr.body || "";

    const w = j.warnings || [];
    $("warnBlock").hidden = !w.length;
    const wl = $("warnings"); wl.innerHTML = ""; w.forEach((x) => wl.appendChild(el("li", null, x)));

    const t = j.trace || {};
    const calls = t.model_calls || [];
    const tin = calls.reduce((a, c) => a + (c.input_tokens || 0), 0), tout = calls.reduce((a, c) => a + (c.output_tokens || 0), 0);
    const kv = el("dl", "kv");
    const add = (k, v) => kv.append(el("dt", null, k), el("dd", null, v));
    const pol = j.policy_selection || {};
    add("Policy", [pol.sop ? `TCC-SOP v${pol.sop.version}` : null, ...(pol.addenda || []).map((a) => a.doc)].filter(Boolean).join(" + ") || (t.documents_used || []).map((d) => `${d.document} v${d.version}`).join(", "));
    add("Model calls", calls.length ? calls.map((c) => `${c.purpose || "call"} (${c.model}: ${c.input_tokens}→${c.output_tokens})`).join("; ") : "none (rules + templates)");
    add("Tokens", `${tin} in / ${tout} out`);
    add("Cost", `$${(t.cost_usd || 0).toFixed(6)}`);
    add("Latency", t.latency_ms != null ? `${t.latency_ms} ms` : "—");
    add("Tools", (t.tools_called || []).join(", "));
    add("Extraction", j.extraction_method || "—");
    add("Reply", (j.reply_method && j.reply_method.method) || "—");
    add("Decision", (j.decision_rationale || []).join("  ·  "));
    $("trace").innerHTML = ""; $("trace").appendChild(kv);
    $("raw").textContent = JSON.stringify(j, null, 2);
  }

  $("copyReply").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText($("rbody").textContent); $("copyReply").textContent = "Copied"; }
    catch { $("copyReply").textContent = "Copy failed"; }
    setTimeout(() => { $("copyReply").textContent = "Copy reply"; }, 1500);
  });
})();
