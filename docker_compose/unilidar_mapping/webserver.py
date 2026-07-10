#!/usr/bin/env python3
import json
import os
import re
import shlex
import subprocess
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COMPOSE_NAME = os.environ.get("UNILIDAR_COMPOSE_NAME", "unilidar_collection")
DEFAULT_CONTAINER_NAME = os.environ.get("UNILIDAR_CONTAINER_NAME", "UniLidarSdk")
DEFAULT_HOST = os.environ.get("UNILIDAR_WEB_HOST", "0.0.0.0")
DEFAULT_PORT = int(os.environ.get("UNILIDAR_WEB_PORT", "8080"))
START_SCRIPT = Path(
    os.environ.get(
        "UNILIDAR_START_SCRIPT",
        REPO_ROOT / "docker_compose" / "unilidar_mapping" / "arm64_start_unilidar.sh",
    )
)
STOP_SCRIPT = Path(
    os.environ.get(
        "UNILIDAR_STOP_SCRIPT",
        REPO_ROOT / "docker_compose" / "unilidar_mapping" / "arm64_stop_unilidar.sh",
    )
)
COPY_SCRIPT = Path(
    os.environ.get(
        "UNILIDAR_COPY_SCRIPT",
        REPO_ROOT / "tools" / "copy_to_drive.sh",
    )
)
CHECK_CPU_FREQ_SCRIPT = Path(
    os.environ.get(
        "UNILIDAR_CHECK_CPU_FREQ_SCRIPT",
        REPO_ROOT / "tools" / "check_current_cpu_freq.sh",
    )
)
SET_CPU_FREQ_MAX_SCRIPT = Path(
    os.environ.get(
        "UNILIDAR_SET_CPU_FREQ_MAX_SCRIPT",
        REPO_ROOT / "tools" / "set_cpu_freq_max.sh",
    )
)
COMPOSE_PARAM_NAMES = ("alpha_bais_bias", "range_fix_a0", "range_fix_a1")
RECORDER_BAG_SUFFIX_RE = re.compile(r'(?m)^(?P<prefix>\s*BAG_NAME_SUFFIX=")(?P<suffix>[^"]*)(?P<suffix_end>")\s*$')

PARAM_LINE_RE = re.compile(
    r"(?P<prefix>--alpha_bais_bias=)(?P<alpha_bais_bias>\S+)"
    r"(?P<mid1>\s+--range_fix_a0=)(?P<range_fix_a0>\S+)"
    r"(?P<mid2>\s+(?:--)?range_fix_a1=)(?P<range_fix_a1>\S+)"
)


INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>UniLidar Control</title>
  <style>
    :root {
      --bg: #0d1117;
      --panel: #161b22;
      --well: #0b0f14;
      --text: #e6edf3;
      --muted: #8b949e;
      --border: #30363d;
      --green: #3fb950;
      --green-dark: #238636;
      --red: #f85149;
      --blue: #58a6ff;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 16px;
      background: var(--bg);
      color: var(--text);
      font-family: system-ui, "Segoe UI", sans-serif;
      font-size: 15px;
      line-height: 1.45;
    }
    .layout {
      max-width: 920px;
      margin: 0 auto;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px;
    }
    h1 { margin: 0; font-size: 22px; }
    h2 { margin: 0; font-size: 16px; }
    .muted { color: var(--muted); font-size: 13px; }

    /* Header */
    .headbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }
    .meta { color: var(--muted); font-size: 12px; word-break: break-all; }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 8px 16px;
      font-weight: 700;
      font-size: 15px;
      background: var(--well);
      white-space: nowrap;
    }
    .pill .dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--muted);
    }
    .pill.running { color: #7ee787; border-color: #2ea04366; }
    .pill.running .dot { background: var(--green); box-shadow: 0 0 8px var(--green); }
    .pill.stopped { color: #ff7b72; border-color: #f8514966; }
    .pill.stopped .dot { background: var(--red); }

    /* Buttons */
    button {
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px 16px;
      font-size: 15px;
      font-weight: 600;
      color: var(--text);
      background: var(--well);
      cursor: pointer;
    }
    button:hover { filter: brightness(1.2); }
    button:active { transform: translateY(1px); }
    button:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
    .btn-start { background: var(--green-dark); border-color: #2ea043; color: #fff; }
    .btn-stop { background: #b62324; border-color: var(--red); color: #fff; }
    .btn-primary { background: #1f4d80; border-color: var(--blue); color: #fff; }
    .row {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
    }
    .cardhead {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 12px;
    }

    /* Message */
    .message {
      margin-top: 10px;
      min-height: 20px;
      font-size: 14px;
      color: var(--muted);
    }
    .message.error { color: var(--red); }

    /* Log tabs */
    .tabs {
      display: flex;
      gap: 6px;
      overflow-x: auto;
      padding: 4px;
      background: var(--well);
      border: 1px solid var(--border);
      border-radius: 10px;
      margin-bottom: 10px;
    }
    .tab {
      flex: 1;
      border: 1px solid transparent;
      background: transparent;
      color: var(--muted);
      padding: 8px 14px;
      font-size: 14px;
      white-space: nowrap;
    }
    .tab.active {
      background: var(--panel);
      border-color: var(--border);
      color: var(--text);
      font-weight: 700;
    }

    /* Log panes */
    pre.logs {
      margin: 0;
      background: var(--well);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 14px;
      min-height: 300px;
      max-height: 60vh;
      overflow: auto;
      white-space: pre-wrap;
      font-family: ui-monospace, "SFMono-Regular", Consolas, monospace;
      font-size: 13px;
    }
    pre.logs.small { min-height: 80px; max-height: 240px; }

    /* Settings */
    details > summary {
      cursor: pointer;
      font-size: 16px;
      font-weight: 600;
      list-style: none;
    }
    details > summary::before { content: "▸ "; color: var(--muted); }
    details[open] > summary::before { content: "▾ "; }
    .field-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 12px;
      margin: 14px 0;
    }
    .field { display: flex; flex-direction: column; gap: 6px; }
    .field label { font-size: 13px; color: var(--muted); }
    .field input {
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--well);
      color: var(--text);
      padding: 10px 12px;
      font-size: 15px;
      outline: none;
      width: 100%;
    }
    .field input:focus { border-color: var(--blue); }
    .divider { border: 0; border-top: 1px solid var(--border); margin: 16px 0; }
  </style>
</head>
<body>
  <div class="layout">

    <header class="card headbar">
      <div>
        <h1>UniLidar Control</h1>
        <div class="meta" id="composeFile"></div>
      </div>
      <div class="pill" id="statusPill"><span class="dot"></span><span id="runningStatus">Checking…</span></div>
    </header>

    <div class="card">
      <div class="row">
        <button class="btn-start" id="startBtn">&#9654; Start</button>
        <button class="btn-stop" id="stopBtn">&#9632; Stop</button>
      </div>
      <div class="message" id="message"></div>
    </div>

    <div class="card">
      <div class="cardhead">
        <h2>Logs</h2>
        <button id="refreshBtn">Refresh</button>
      </div>
      <div class="tabs" id="logTabs">
        <button class="tab active" data-container="UniLidarSdk">UniLidarSdk</button>
        <button class="tab" data-container="Recorder">Recorder</button>
        <button class="tab" data-container="RtkPublisher">RtkPublisher</button>
        <button class="tab" data-container="CameraPublisher">CameraPublisher</button>
      </div>
      <pre class="logs" id="logs">Loading logs...</pre>
    </div>

    <div class="card">
      <div class="cardhead"><h2>Tools</h2></div>
      <div class="row">
        <button class="btn-primary" id="copyBtn">Copy to Drive</button>
        <button id="topicsBtn">List Topics</button>
        <button id="checkCpuFreqBtn">Check CPU Freq</button>
        <button id="setCpuFreqMaxBtn">Set CPU Max</button>
      </div>
      <pre class="logs small" id="toolLogs" style="margin-top: 12px;">No tool has run yet.</pre>
    </div>

    <div class="card">
      <details>
        <summary>Settings</summary>

        <p class="muted" style="margin: 12px 0 0;">Calibration parameters are written into the compose file. Restart the stack after saving to apply them.</p>
        <div class="field-grid">
          <div class="field">
            <label for="alphaBaisBias">alpha_bais_bias</label>
            <input id="alphaBaisBias" type="number" step="any" inputmode="decimal">
          </div>
          <div class="field">
            <label for="rangeFixA0">range_fix_a0</label>
            <input id="rangeFixA0" type="number" step="any" inputmode="decimal">
          </div>
          <div class="field">
            <label for="rangeFixA1">range_fix_a1</label>
            <input id="rangeFixA1" type="number" step="any" inputmode="decimal">
          </div>
        </div>
        <div class="row">
          <button class="btn-primary" id="saveParamsBtn">Save Parameters</button>
          <button id="defaultParamsBtn">Load Defaults</button>
          <button id="zeroParamsBtn">All Zeros</button>
        </div>

        <hr class="divider">

        <p class="muted" style="margin: 0;">Optional postfix appended to recorder bag names, for example <code>_postfix</code>.</p>
        <div class="field-grid">
          <div class="field">
            <label for="bagNameSuffix">bag postfix</label>
            <input id="bagNameSuffix" type="text" spellcheck="false" placeholder="_postfix">
          </div>
        </div>
        <div class="row">
          <button class="btn-primary" id="saveBagSuffixBtn">Save Bag Postfix</button>
        </div>
      </details>
    </div>

  </div>

  <script>
    const startBtn = document.getElementById("startBtn");
    const stopBtn = document.getElementById("stopBtn");
    const refreshBtn = document.getElementById("refreshBtn");
    const copyBtn = document.getElementById("copyBtn");
    const topicsBtn = document.getElementById("topicsBtn");
    const checkCpuFreqBtn = document.getElementById("checkCpuFreqBtn");
    const setCpuFreqMaxBtn = document.getElementById("setCpuFreqMaxBtn");
    const defaultParamsBtn = document.getElementById("defaultParamsBtn");
    const zeroParamsBtn = document.getElementById("zeroParamsBtn");
    const saveParamsBtn = document.getElementById("saveParamsBtn");
    const saveBagSuffixBtn = document.getElementById("saveBagSuffixBtn");
    const statusPill = document.getElementById("statusPill");
    const runningStatus = document.getElementById("runningStatus");
    const composeFile = document.getElementById("composeFile");
    const logTabs = document.getElementById("logTabs");
    const logs = document.getElementById("logs");
    const toolLogs = document.getElementById("toolLogs");
    const message = document.getElementById("message");
    const alphaBaisBias = document.getElementById("alphaBaisBias");
    const rangeFixA0 = document.getElementById("rangeFixA0");
    const rangeFixA1 = document.getElementById("rangeFixA1");
    const bagNameSuffix = document.getElementById("bagNameSuffix");

    let actionInFlight = false;
    let logContainer = "UniLidarSdk";
    const defaultCalibrationParams = {
      alpha_bais_bias: "-0.014",
      range_fix_a0: "-0.0095",
      range_fix_a1: "-0.007",
    };

    async function fetchJson(url, options) {
      const response = await fetch(url, options);
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "Request failed");
      }
      return data;
    }

    function setMessage(text, isError = false) {
      message.textContent = text;
      message.className = "message" + (isError ? " error" : "");
    }

    function setBusy(busy) {
      actionInFlight = busy;
      document.querySelectorAll("button").forEach((b) => { b.disabled = busy; });
    }

    function setLogContainer(name) {
      logContainer = name;
      logTabs.querySelectorAll(".tab").forEach((tab) => {
        tab.classList.toggle("active", tab.dataset.container === name);
      });
    }

    function setLogText(pane, text) {
      const nearBottom = pane.scrollHeight - pane.scrollTop - pane.clientHeight < 40;
      pane.textContent = text;
      if (nearBottom) {
        pane.scrollTop = pane.scrollHeight;
      }
    }

    async function refreshStatus() {
      try {
        const data = await fetchJson("/api/status");
        const running = Boolean(data.running);
        runningStatus.textContent = running ? "Running" : "Stopped";
        statusPill.className = "pill " + (running ? "running" : "stopped");
        composeFile.textContent = (data.container_name || "-") + " · " + (data.compose_file || "-");
      } catch (error) {
        setMessage(error.message, true);
      }
    }

    async function refreshLogs() {
      try {
        const data = await fetchJson("/api/logs?tail=50&container=" + encodeURIComponent(logContainer));
        setLogText(logs, data.logs || "No logs yet.");
      } catch (error) {
        logs.textContent = error.message;
      }
    }

    function setParameterInputs(params) {
      alphaBaisBias.value = params.alpha_bais_bias ?? "";
      rangeFixA0.value = params.range_fix_a0 ?? "";
      rangeFixA1.value = params.range_fix_a1 ?? "";
    }

    function getParameterInputs() {
      return {
        alpha_bais_bias: alphaBaisBias.value,
        range_fix_a0: rangeFixA0.value,
        range_fix_a1: rangeFixA1.value,
      };
    }

    async function refreshParameters() {
      try {
        const data = await fetchJson("/api/params");
        setParameterInputs(data.params || {});
      } catch (error) {
        setMessage(error.message, true);
      }
    }

    async function refreshBagSuffix() {
      try {
        const data = await fetchJson("/api/bag_suffix");
        bagNameSuffix.value = data.bag_name_suffix || "";
      } catch (error) {
        setMessage(error.message, true);
      }
    }

    async function runAction(path, outputTarget = null, busyText = null) {
      if (actionInFlight) return;
      setBusy(true);
      setMessage(busyText || ("Running " + path.replace("/api/", "") + "..."));
      try {
        const data = await fetchJson(path, { method: "POST" });
        if (outputTarget) {
          outputTarget.textContent = [data.stdout, data.stderr].filter(Boolean).join("\\n\\n") || "No output.";
          outputTarget.scrollTop = outputTarget.scrollHeight;
          setMessage("Done.");
        } else {
          setMessage(data.stdout || "Command finished.");
        }
      } catch (error) {
        if (outputTarget) {
          outputTarget.textContent = error.message;
        }
        setMessage(error.message, true);
      } finally {
        setBusy(false);
        await refreshStatus();
        await refreshLogs();
      }
    }

    async function saveParameters(overrides = null) {
      if (actionInFlight) return;
      setBusy(true);
      setMessage("Saving parameters...");
      try {
        const payload = overrides || getParameterInputs();
        const data = await fetchJson("/api/params", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        setMessage(data.stdout || "Parameters saved.");
        setParameterInputs(data.params || payload);
      } catch (error) {
        setMessage(error.message, true);
      } finally {
        setBusy(false);
        await refreshStatus();
      }
    }

    async function saveBagSuffix() {
      if (actionInFlight) return;
      setBusy(true);
      setMessage("Saving bag postfix...");
      try {
        const payload = { bag_name_suffix: bagNameSuffix.value };
        const data = await fetchJson("/api/bag_suffix", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        setMessage(data.stdout || "Bag postfix saved.");
        bagNameSuffix.value = data.bag_name_suffix ?? payload.bag_name_suffix;
      } catch (error) {
        setMessage(error.message, true);
      } finally {
        setBusy(false);
        await refreshStatus();
      }
    }

    startBtn.addEventListener("click", () => runAction("/api/start", null, "Starting UniLidar..."));
    stopBtn.addEventListener("click", () => runAction("/api/stop", null, "Stopping UniLidar..."));
    copyBtn.addEventListener("click", () => runAction("/api/copy", toolLogs, "Copying to drive..."));
    topicsBtn.addEventListener("click", () => runAction("/api/topics", toolLogs, "Listing ROS 2 topics..."));
    checkCpuFreqBtn.addEventListener("click", () => runAction("/api/cpu_freq", toolLogs));
    setCpuFreqMaxBtn.addEventListener("click", () => runAction("/api/cpu_freq_max", toolLogs));
    saveParamsBtn.addEventListener("click", () => saveParameters());
    defaultParamsBtn.addEventListener("click", () => {
      setParameterInputs(defaultCalibrationParams);
      saveParameters(defaultCalibrationParams);
    });
    zeroParamsBtn.addEventListener("click", () => {
      const zeros = { alpha_bais_bias: "0", range_fix_a0: "0", range_fix_a1: "0" };
      setParameterInputs(zeros);
      saveParameters(zeros);
    });
    saveBagSuffixBtn.addEventListener("click", saveBagSuffix);
    logTabs.addEventListener("click", async (event) => {
      const tab = event.target.closest(".tab");
      if (!tab || actionInFlight) return;
      setLogContainer(tab.dataset.container);
      logs.textContent = "Loading logs...";
      await refreshLogs();
    });
    refreshBtn.addEventListener("click", async () => {
      await refreshStatus();
      await refreshParameters();
      await refreshBagSuffix();
      await refreshLogs();
    });

    refreshStatus();
    refreshParameters();
    refreshBagSuffix();
    refreshLogs();
    setInterval(refreshStatus, 3000);
    setInterval(refreshLogs, 2000);
  </script>
</body>
</html>
"""


def run_command(command):
    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    return {
        "returncode": process.returncode,
        "stdout": process.stdout.strip(),
        "stderr": process.stderr.strip(),
    }


def compose_file_path(compose_name):
    return str(REPO_ROOT / "docker_compose" / "unilidar_mapping" / f"{compose_name}.compose.yml")


def read_compose_parameters():
    compose_path = Path(compose_file_path(DEFAULT_COMPOSE_NAME))
    if not compose_path.is_file():
        raise FileNotFoundError(f"compose file not found: {compose_path}")

    content = compose_path.read_text(encoding="utf-8")
    match = PARAM_LINE_RE.search(content)
    if not match:
        raise ValueError("Could not find calibration parameters in compose file.")

    params = {name: match.group(name) for name in COMPOSE_PARAM_NAMES}
    return params


def read_bag_name_suffix():
    compose_path = Path(compose_file_path(DEFAULT_COMPOSE_NAME))
    if not compose_path.is_file():
        raise FileNotFoundError(f"compose file not found: {compose_path}")

    content = compose_path.read_text(encoding="utf-8")
    match = RECORDER_BAG_SUFFIX_RE.search(content)
    if not match:
        raise ValueError("Could not find bag postfix in compose file.")
    return match.group("suffix")


def write_compose_parameters(values):
    compose_path = Path(compose_file_path(DEFAULT_COMPOSE_NAME))
    if not compose_path.is_file():
        raise FileNotFoundError(f"compose file not found: {compose_path}")

    content = compose_path.read_text(encoding="utf-8")
    match = PARAM_LINE_RE.search(content)
    if not match:
        raise ValueError("Could not find calibration parameters in compose file.")

    def replace_value(name):
        raw_value = values[name]
        try:
            return format(float(raw_value), ".15g")
        except (TypeError, ValueError):
            raise ValueError(f"Invalid numeric value for {name}: {raw_value!r}")

    replacement = (
        f"--alpha_bais_bias={replace_value('alpha_bais_bias')}"
        f"{match.group('mid1')}{replace_value('range_fix_a0')}"
        f" --range_fix_a1={replace_value('range_fix_a1')}"
    )
    updated = content[: match.start()] + replacement + content[match.end() :]
    compose_path.write_text(updated, encoding="utf-8")
    return {name: replace_value(name) for name in COMPOSE_PARAM_NAMES}


def write_bag_name_suffix(value):
    compose_path = Path(compose_file_path(DEFAULT_COMPOSE_NAME))
    if not compose_path.is_file():
        raise FileNotFoundError(f"compose file not found: {compose_path}")

    content = compose_path.read_text(encoding="utf-8")
    match = RECORDER_BAG_SUFFIX_RE.search(content)
    if not match:
        raise ValueError("Could not find bag postfix in compose file.")

    suffix = "" if value is None else str(value)
    if "\n" in suffix or "\r" in suffix:
        raise ValueError("bag postfix must be a single line.")
    escaped_suffix = (
        suffix.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("`", "\\`")
    )

    replacement = f'{match.group("prefix")}{escaped_suffix}{match.group("suffix_end")}'
    updated = content[: match.start()] + replacement + content[match.end() :]
    compose_path.write_text(updated, encoding="utf-8")
    return suffix


def get_status():
    inspect = run_command(
        [
            "docker",
            "inspect",
            "-f",
            "{{.State.Running}}",
            DEFAULT_CONTAINER_NAME,
        ]
    )
    running = inspect["returncode"] == 0 and inspect["stdout"].lower() == "true"
    return {
        "running": running,
        "container_name": DEFAULT_CONTAINER_NAME,
        "compose_file": compose_file_path(DEFAULT_COMPOSE_NAME),
        "docker_available": run_command(["docker", "version"])["returncode"] == 0,
        "inspect_error": inspect["stderr"] if inspect["returncode"] != 0 else "",
    }


def get_logs(tail, container_name=DEFAULT_CONTAINER_NAME):
    return run_command(
        [
            "docker",
            "logs",
            f"--tail={tail}",
            container_name,
        ]
    )


def combine_output(result):
    return "\n".join(part for part in [result["stdout"], result["stderr"]] if part)


def format_command_error(result, fallback):
    message = result["stderr"] or result["stdout"] or fallback
    return {
        "error": message,
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
    }


class UniLidarHandler(BaseHTTPRequestHandler):
    server_version = "UniLidarRemote/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))

    def _write_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_html(self, body, status=HTTPStatus.OK):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._write_html(INDEX_HTML)
            return
        if parsed.path == "/api/status":
            self._write_json(get_status())
            return
        if parsed.path == "/api/bag_suffix":
            try:
                self._write_json({"bag_name_suffix": read_bag_name_suffix()})
            except Exception as error:
                self._write_json({"error": str(error)}, HTTPStatus.BAD_GATEWAY)
            return
        if parsed.path == "/api/logs":
            query = parse_qs(parsed.query)
            raw_tail = query.get("tail", ["300"])[0]
            container_name = query.get("container", [DEFAULT_CONTAINER_NAME])[0] or DEFAULT_CONTAINER_NAME
            try:
                tail = max(1, min(1000, int(raw_tail)))
            except ValueError:
                tail = 300
            result = get_logs(tail, container_name)
            status = get_status()
            if result["returncode"] != 0:
                missing_container = "No such container" in result["stderr"]
                message = (
                    f"{container_name} is not running yet."
                    if missing_container
                    else combine_output(result) or "Unable to read docker logs."
                )
                payload = {
                    "logs": message,
                    "running": status["running"],
                    "container_name": container_name,
                }
                self._write_json(payload)
                return
            payload = {
                "logs": combine_output(result),
                "running": status["running"],
                "container_name": container_name,
            }
            self._write_json(payload)
            return
        if parsed.path == "/api/params":
            try:
                params = read_compose_parameters()
                self._write_json({"params": params})
            except Exception as error:
                self._write_json({"error": str(error)}, HTTPStatus.BAD_GATEWAY)
            return
        self._write_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/start":
            result = run_command([str(START_SCRIPT), DEFAULT_COMPOSE_NAME])
            if result["returncode"] == 0:
                self._write_json(result)
            else:
                self._write_json(
                    format_command_error(result, "Failed to start UniLidar."),
                    HTTPStatus.BAD_GATEWAY,
                )
            return
        if parsed.path == "/api/stop":
            result = run_command([str(STOP_SCRIPT), DEFAULT_COMPOSE_NAME])
            if result["returncode"] == 0:
                self._write_json(result)
            else:
                self._write_json(
                    format_command_error(result, "Failed to stop UniLidar."),
                    HTTPStatus.BAD_GATEWAY,
                )
            return
        if parsed.path == "/api/copy":
            result = run_command([str(COPY_SCRIPT)])
            if result["returncode"] == 0:
                self._write_json(result)
            else:
                self._write_json(
                    format_command_error(result, "Failed to copy data to drive."),
                    HTTPStatus.BAD_GATEWAY,
                )
            return
        if parsed.path == "/api/cpu_freq":
            result = run_command([str(CHECK_CPU_FREQ_SCRIPT)])
            if result["returncode"] == 0:
                self._write_json(result)
            else:
                self._write_json(
                    format_command_error(result, "Failed to read CPU frequency."),
                    HTTPStatus.BAD_GATEWAY,
                )
            return
        if parsed.path == "/api/cpu_freq_max":
            result = run_command([str(SET_CPU_FREQ_MAX_SCRIPT)])
            if result["returncode"] == 0:
                self._write_json(result)
            else:
                self._write_json(
                    format_command_error(result, "Failed to set CPU frequency to max."),
                    HTTPStatus.BAD_GATEWAY,
                )
            return
        if parsed.path == "/api/topics":
            result = run_command(
                [
                    "docker",
                    "exec",
                    DEFAULT_CONTAINER_NAME,
                    "bash",
                    "-lc",
                    "source /opt/ros/humble/setup.bash && ros2 topic list",
                ]
            )
            if result["returncode"] == 0:
                self._write_json(result)
            else:
                self._write_json(
                    format_command_error(result, "Failed to list ROS 2 topics."),
                    HTTPStatus.BAD_GATEWAY,
                )
            return
        if parsed.path == "/api/params":
            try:
                raw_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raw_length = 0
            raw_body = self.rfile.read(max(0, raw_length)) if raw_length else b""
            try:
                payload = json.loads(raw_body.decode("utf-8") or "{}")
            except json.JSONDecodeError as error:
                self._write_json({"error": f"Invalid JSON payload: {error}"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                params = write_compose_parameters(payload)
                self._write_json({"stdout": "Parameters saved.", "params": params})
            except Exception as error:
                self._write_json({"error": str(error)}, HTTPStatus.BAD_GATEWAY)
            return
        if parsed.path == "/api/bag_suffix":
            try:
                raw_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raw_length = 0
            raw_body = self.rfile.read(max(0, raw_length)) if raw_length else b""
            try:
                payload = json.loads(raw_body.decode("utf-8") or "{}")
            except json.JSONDecodeError as error:
                self._write_json({"error": f"Invalid JSON payload: {error}"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                bag_name_suffix = write_bag_name_suffix(payload.get("bag_name_suffix", ""))
                self._write_json({"stdout": "Bag postfix saved.", "bag_name_suffix": bag_name_suffix})
            except Exception as error:
                self._write_json({"error": str(error)}, HTTPStatus.BAD_GATEWAY)
            return
        self._write_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)


def main():
    if not START_SCRIPT.is_file():
        raise FileNotFoundError(f"start script not found: {START_SCRIPT}")
    if not STOP_SCRIPT.is_file():
        raise FileNotFoundError(f"stop script not found: {STOP_SCRIPT}")
    if not COPY_SCRIPT.is_file():
        raise FileNotFoundError(f"copy script not found: {COPY_SCRIPT}")
    if not CHECK_CPU_FREQ_SCRIPT.is_file():
        raise FileNotFoundError(f"check cpu freq script not found: {CHECK_CPU_FREQ_SCRIPT}")
    if not SET_CPU_FREQ_MAX_SCRIPT.is_file():
        raise FileNotFoundError(f"set cpu freq max script not found: {SET_CPU_FREQ_MAX_SCRIPT}")

    server = ThreadingHTTPServer((DEFAULT_HOST, DEFAULT_PORT), UniLidarHandler)
    print(
        "Serving UniLidar web control on "
        f"http://{DEFAULT_HOST}:{DEFAULT_PORT} "
        f"(container={shlex.quote(DEFAULT_CONTAINER_NAME)}, compose={shlex.quote(DEFAULT_COMPOSE_NAME)})"
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
