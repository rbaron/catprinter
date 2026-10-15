import { Printer } from "./printer.js";
import { PRINT_WIDTH, printCommands } from "./protocol.js";
import {
  UnsupportedFileError, blankRows, expandText, loadFile, parsePageRange, previewCanvas,
  processPage, resolveMode,
} from "./imaging.js";

const SETTINGS_KEY = "catprinter-settings";
const DEFAULTS = {
  mode: "auto", brightness: 0, contrast: 0, bold: true, crop: true, rotate: false,
  textSize: 22, level: 4, speed: 10,
};
// Values the official iPrint app uses for the SC03h: a base energy of 5000
// for images and 8000 for text, and 15 % more or less per concentration level.
const IMAGE_ENERGY = 5000;
const TEXT_ENERGY = 8000;
const DEFAULT_LEVEL = 4;
const LOW_BATTERY = 20;
const DOTS_PER_MM = 8;
const KEEP_ALIVE_MS = 60000;
const REPROCESS_DELAY_MS = 250;

const $ = (id) => document.getElementById(id);

const state = {
  settings: loadSettings(),
  sources: [],      // Pages as loaded; text is laid out when processing.
  pages: [],        // Pages ready to process.
  rows: [],
  textMode: false,
  processing: 0,    // Generation counter: discards superseded results.
  printing: false,
};

const printer = new Printer();

if (!Printer.supported || !window.isSecureContext) {
  showUnsupported();
} else {
  start();
}

function showUnsupported() {
  const ua = navigator.userAgent;
  let reason = "Para conectarse a la impresora hace falta Web Bluetooth, y este navegador no lo tiene.";
  if (!window.isSecureContext) {
    reason = "Web Bluetooth solo funciona en páginas seguras (https).";
  } else if (/iPhone|iPad|iPod/.test(ua)) {
    reason = "Safari y los demás navegadores de iPhone y iPad no tienen Web Bluetooth.";
  } else if (/Firefox\//.test(ua)) {
    reason = "Firefox no tiene Web Bluetooth.";
  } else if (/Linux/.test(ua) && /Chrome\//.test(ua)) {
    reason = "En Linux, Chrome trae Web Bluetooth desactivado.";
  }
  $("unsupported-reason").textContent = reason;
  $("unsupported").hidden = false;
  $("connect").hidden = true;
  $("status-text").textContent = "No compatible";
}

function start() {
  $("app").hidden = false;
  bindSettings();
  bindFiles();
  bindPrinter();
  bindInstall();
  receiveLaunchedFiles();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js");
}

// ----------------------------------------------------------------- Settings

function loadSettings() {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(SETTINGS_KEY)) };
  } catch {
    return { ...DEFAULTS };
  }
}

function saveSettings() {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(state.settings));
  } catch {
    // Storage may be unavailable (private mode); settings just won't persist.
  }
}

function bindSettings() {
  for (const input of document.querySelectorAll("[data-setting]")) {
    const key = input.dataset.setting;
    if (input.type === "checkbox") input.checked = state.settings[key];
    else input.value = state.settings[key];
    showValue(key);

    input.addEventListener("input", () => {
      state.settings[key] = input.type === "checkbox" ? input.checked
        : input.type === "range" || input.type === "number" ? Number(input.value)
          : input.value;
      showValue(key);
      saveSettings();
      // Concentration and speed only affect the printer, not the preview.
      if (key !== "level" && key !== "speed") scheduleProcess();
    });
  }
  $("pages").addEventListener("input", () => scheduleProcess());
}

function showValue(key) {
  const output = document.querySelector(`output[data-for="${key}"]`);
  if (output) output.textContent = state.settings[key];
}

function energy() {
  const base = state.textMode ? TEXT_ENERGY : IMAGE_ENERGY;
  return Math.round(base * (1 + (state.settings.level - DEFAULT_LEVEL) * 0.15));
}

// -------------------------------------------------------------------- Files

function bindFiles() {
  $("file-input").addEventListener("change", (e) => openFiles([...e.target.files]));
  $("add-input").addEventListener("change", (e) => openFiles([...e.target.files], true));
  $("clear").addEventListener("click", clear);

  const preview = $("preview");
  window.addEventListener("dragover", (e) => {
    e.preventDefault();
    preview.classList.add("dragging");
  });
  window.addEventListener("dragleave", (e) => {
    if (!e.relatedTarget) preview.classList.remove("dragging");
  });
  window.addEventListener("drop", (e) => {
    e.preventDefault();
    preview.classList.remove("dragging");
    const files = [...e.dataTransfer.files];
    if (files.length) openFiles(files, state.sources.length > 0);
  });
  window.addEventListener("paste", (e) => {
    const files = [...e.clipboardData.files];
    if (files.length) openFiles(files, state.sources.length > 0);
  });
}

async function openFiles(files, append = false) {
  showSpinner(true);
  const sources = append ? [...state.sources] : [];
  for (const file of files) {
    try {
      sources.push(...await loadFile(file));
    } catch (error) {
      toast(error instanceof UnsupportedFileError ? error.message
        : `No se pudo abrir «${file.name}»: ${error.message}`);
    }
  }
  showSpinner(false);
  if (!sources.length) {
    clear();
    return;
  }
  state.sources = sources;
  await process();
}

function clear() {
  state.processing++;
  state.sources = [];
  state.pages = [];
  state.rows = [];
  $("pages").value = "";
  $("file-input").value = "";
  $("add-input").value = "";
  $("empty").hidden = false;
  $("paper").hidden = true;
  $("file-group").hidden = true;
  $("text-size-row").hidden = true;
  $("length").textContent = "";
  updatePrintButton();
}

function describeFiles() {
  const names = [...new Set(state.sources.map((p) => p.name))];
  const count = state.pages.length;
  if (names.length === 1) {
    $("file-title").textContent = names[0];
    $("file-subtitle").textContent = `${count} página${count === 1 ? "" : "s"}`;
  } else {
    $("file-title").textContent = `${names.length} archivos`;
    $("file-subtitle").textContent = names.slice(0, 3).join(", ") + (names.length > 3 ? "…" : "");
  }
  $("file-group").hidden = false;
  $("pages-row").hidden = count < 2;
  $("text-size-row").hidden = !state.sources.some((p) => p.kind === "text-source");
}

// --------------------------------------------------------------- Processing

let processTimer = 0;

function scheduleProcess() {
  if (!state.sources.length) return;
  clearTimeout(processTimer);
  processTimer = setTimeout(process, REPROCESS_DELAY_MS);
}

async function process() {
  const generation = ++state.processing;
  const s = state.settings;
  state.pages = expandText(state.sources, s.textSize);
  describeFiles();

  let selected;
  try {
    selected = parsePageRange($("pages").value, state.pages.length);
    $("pages").classList.remove("invalid");
  } catch {
    $("pages").classList.add("invalid");
    return;
  }

  const pages = selected.map((i) => state.pages[i]);
  // Like the official app: text mode and energy only if everything is sharp.
  const textMode = pages.length > 0 && pages.every((p) => resolveMode(s.mode, p.kind) === "sharp");
  showSpinner(true);
  const chunks = [];
  try {
    for (const page of pages) {
      const rows = await processPage(page, s);
      if (generation !== state.processing) return;
      chunks.push({ rows, gap: page.gap });
    }
  } catch (error) {
    toast(`Error al procesar: ${error.message}`);
    return;
  } finally {
    if (generation === state.processing) showSpinner(false);
  }
  // The printer feeds paper at the end, so drop the last page's gap.
  if (chunks.length) chunks[chunks.length - 1].gap = 0;

  const paper = $("paper");
  paper.replaceChildren();
  state.rows = [];
  state.textMode = textMode;
  for (const { rows, gap } of chunks) {
    state.rows.push(...rows, ...blankRows(gap));
    // One canvas per page: browsers limit the height of a canvas.
    const canvas = previewCanvas(rows);
    canvas.style.marginBottom = `${(gap * 100) / PRINT_WIDTH}%`;
    paper.append(canvas);
  }
  $("empty").hidden = true;
  paper.hidden = false;
  const cm = state.rows.length / DOTS_PER_MM / 10;
  $("length").textContent = `Largo aproximado: ${cm.toFixed(1)} cm de papel`;
  updatePrintButton();
}

function showSpinner(visible) {
  $("spinner").hidden = !visible;
}

// ------------------------------------------------------------------ Printer

function bindPrinter() {
  $("connect").addEventListener("click", async () => {
    if (printer.connected) {
      printer.disconnect();
      return;
    }
    setStatus("busy", "Conectando…");
    try {
      await printer.choose();
    } catch (error) {
      // NotFoundError means the user closed the chooser.
      if (error.name !== "NotFoundError") toast(bluetoothError(error));
      updateStatus();
    }
  });
  $("print").addEventListener("click", print);

  printer.addEventListener("connected", updateStatus);
  printer.addEventListener("status", updateStatus);
  printer.addEventListener("disconnected", () => {
    updateStatus();
    if (printer.wantConnection) toast("Se perdió la conexión con la impresora. Reconectando…");
  });

  setInterval(() => {
    if (printer.connected && !state.printing) printer.queryStatus().catch(() => {});
  }, KEEP_ALIVE_MS);

  navigator.bluetooth.getAvailability?.().then((available) => {
    if (!available) showBanner("El Bluetooth está apagado o este equipo no tiene Bluetooth.");
  });
  updateStatus();
  // Reconnect to the printer chosen in a previous visit, when the browser allows it.
  printer.restore().catch(() => updateStatus());
}

function setStatus(kind, text) {
  $("status-dot").className = `dot ${kind}`;
  $("status-text").textContent = text;
}

function updateStatus() {
  const status = printer.status;
  if (state.printing) {
    setStatus("busy", `Imprimiendo en ${printer.name}…`);
  } else if (printer.connected) {
    setStatus("connected", `${printer.name} conectada`);
  } else if (printer.wantConnection) {
    setStatus("busy", "Reconectando…");
  } else {
    setStatus("", "Sin conectar");
  }
  $("connect").textContent = printer.connected ? "Desconectar" : "Conectar";
  $("connect").classList.toggle("button--accent", !printer.connected);

  const battery = printer.connected ? status.battery : undefined;
  $("battery").hidden = battery === undefined;
  if (battery !== undefined) {
    const low = batteryLow(status);
    $("battery").classList.toggle("low", low);
    $("battery-level").setAttribute("width", String(Math.max(1, (14 * battery) / 100)));
    $("battery-text").textContent = `${battery} %${status.charging ? " ⚡" : ""}`;
    $("battery").title = `Batería de la impresora: ${battery} %${status.charging ? " (cargando)" : ""}`;
  }

  const problems = [];
  if (printer.connected) {
    if (status.noPaper) problems.push("Sin papel");
    if (status.coverOpen) problems.push("Tapa abierta");
    if (status.overheat) problems.push("Cabezal caliente: espera unos minutos");
    if (batteryLow(status)) problems.push("Batería baja: carga la impresora, puede imprimir en blanco");
  }
  showBanner(problems.join(" · "));
  updatePrintButton();
}

function batteryLow(status) {
  return !status.charging && (status.lowBattery
    || (status.battery !== undefined && status.battery <= LOW_BATTERY));
}

function updatePrintButton() {
  const button = $("print");
  button.disabled = !(printer.connected && state.rows.length && !state.printing);
  button.title = printer.connected ? "" : "Conecta la impresora primero";
}

async function print() {
  if (!printer.connected || !state.rows.length || state.printing) return;
  state.printing = true;
  const progress = $("progress");
  progress.value = 0;
  progress.hidden = false;
  updateStatus();
  try {
    const data = printCommands(state.rows,
      { energy: energy(), speed: state.settings.speed, textMode: state.textMode });
    await printer.print(data, (fraction) => { progress.value = fraction; });
    toast("¡Impreso!");
  } catch (error) {
    toast(`No se pudo imprimir: ${bluetoothError(error)}`);
  } finally {
    state.printing = false;
    progress.hidden = true;
    updateStatus();
  }
}

function bluetoothError(error) {
  if (error.name === "SecurityError") return "El navegador no permitió usar el Bluetooth.";
  if (error.name === "NetworkError") return "No se pudo conectar. ¿Está encendida y cerca?";
  return error.message || String(error);
}

// --------------------------------------------------------------------- PWA

function bindInstall() {
  let installPrompt = null;
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    installPrompt = e;
    $("install").hidden = false;
  });
  $("install").addEventListener("click", async () => {
    $("install").hidden = true;
    await installPrompt?.prompt();
    installPrompt = null;
  });
}

// Files opened with "Open With" (installed app) or shared from another app.
async function receiveLaunchedFiles() {
  if ("launchQueue" in window) {
    window.launchQueue.setConsumer(async ({ files }) => {
      if (files?.length) openFiles(await Promise.all(files.map((f) => f.getFile())));
    });
  }

  // The service worker keeps shared files in memory (never on disk) until we ask.
  const url = new URL(location.href);
  if (!url.searchParams.has("compartido") || !("serviceWorker" in navigator)) return;
  history.replaceState(null, "", url.pathname);
  navigator.serviceWorker.addEventListener("message", ({ data }) => {
    if (data?.type === "shared-files" && data.files.length) openFiles(data.files);
  });
  const registration = await navigator.serviceWorker.ready;
  registration.active.postMessage("shared-files");
}

// --------------------------------------------------------------------- Misc

function showBanner(text) {
  $("banner").textContent = text;
  $("banner").hidden = !text;
}

function toast(text) {
  const element = document.createElement("div");
  element.className = "toast";
  element.textContent = text;
  $("toasts").append(element);
  setTimeout(() => element.remove(), 5000);
}
