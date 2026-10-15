// Turns files into rows of black and white dots: a port of catprinter_gui's
// render.py and process.py. Rows are Uint8Arrays of PRINT_WIDTH values, 1 = black.
import { PRINT_WIDTH } from "./protocol.js";

const PAGE_GAP = 24;
const TEXT_MARGIN = 4;
const TEXT_LINES_PER_CHUNK = 120;
const PDF_LONG_SIDE = 1400;
const CROP_THRESHOLD = 220;
const CROP_PADDING = 0.02;
const TRIM_PADDING_ROWS = 8;

const PDFJS_URL = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js";
const PDFJS_WORKER_URL = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";

const TEXT_EXTENSIONS = /\.(txt|md|csv|log|json|xml|ya?ml|ini|conf|cfg|py|js|ts|c|h|cpp|java|sh|html?|css)$/i;
const PLAIN_TEXT = /\.(txt|md)$/i;

export const MODES = ["auto", "photo", "sharp", "atkinson"];

export class UnsupportedFileError extends Error {}

// Returns the pages of a file: [{ kind, name, gap, load: async () => canvas }].
// kind is "image", "document" or "text".
export async function loadFile(file) {
  const name = file.name;
  if (file.type === "application/pdf" || /\.pdf$/i.test(name)) return loadPdf(file);
  if (file.type.startsWith("image/")) {
    const canvas = await imageToCanvas(file);
    return [{ kind: "image", name, gap: PAGE_GAP, load: async () => canvas }];
  }
  if (file.type.startsWith("text/") || TEXT_EXTENSIONS.test(name)) {
    return [{ kind: "text-source", name, text: await file.text(), mono: !PLAIN_TEXT.test(name) }];
  }
  throw new UnsupportedFileError(
    `No se puede imprimir «${name}» desde el navegador. Conviértelo a PDF o imagen.`);
}

// Text is laid out when processing, because it depends on the font size.
export function expandText(pages, textSize) {
  return pages.flatMap((page) => (page.kind === "text-source"
    ? renderText(page.text, textSize, page.mono, page.name)
    : [page]));
}

async function imageToCanvas(file) {
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    // SVGs without a size decode as 0x0 in some browsers.
    const width = img.naturalWidth || PRINT_WIDTH * 3;
    const height = img.naturalHeight || PRINT_WIDTH * 3;
    const canvas = createCanvas(width, height);
    canvas.getContext("2d").drawImage(img, 0, 0, width, height);
    return canvas;
  } catch {
    throw new UnsupportedFileError(`No se pudo abrir la imagen «${file.name}».`);
  } finally {
    URL.revokeObjectURL(url);
  }
}

let pdfjs = null;

async function loadPdfJs() {
  if (pdfjs) return pdfjs;
  await new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = PDFJS_URL;
    script.onload = resolve;
    script.onerror = () => reject(new Error("No se pudo cargar el lector de PDF. ¿Hay conexión?"));
    document.head.append(script);
  });
  pdfjs = window.pdfjsLib;
  pdfjs.GlobalWorkerOptions.workerSrc = PDFJS_WORKER_URL;
  return pdfjs;
}

async function loadPdf(file) {
  const lib = await loadPdfJs();
  const pdf = await lib.getDocument({ data: await file.arrayBuffer() }).promise;
  const pages = [];
  for (let n = 1; n <= pdf.numPages; n++) {
    pages.push({
      kind: "document",
      name: file.name,
      gap: PAGE_GAP,
      load: async () => {
        const page = await pdf.getPage(n);
        const base = page.getViewport({ scale: 1 });
        const viewport = page.getViewport(
          { scale: PDF_LONG_SIDE / Math.max(base.width, base.height) });
        const canvas = createCanvas(Math.round(viewport.width), Math.round(viewport.height));
        const ctx = canvas.getContext("2d");
        ctx.fillStyle = "#fff";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        await page.render({ canvasContext: ctx, viewport }).promise;
        return canvas;
      },
    });
  }
  return pages;
}

function renderText(text, size, mono, name) {
  const font = `${size}px ${mono ? "monospace" : "sans-serif"}`;
  const measure = createCanvas(1, 1).getContext("2d");
  measure.font = font;
  const maxWidth = PRINT_WIDTH - 2 * TEXT_MARGIN;
  const lines = text.replace(/\t/g, "    ").split(/\r?\n/).flatMap(
    (line) => wrapLine(line, measure, maxWidth));
  const lineHeight = Math.ceil(size * 1.25);

  const pages = [];
  for (let start = 0; start < lines.length; start += TEXT_LINES_PER_CHUNK) {
    const chunk = lines.slice(start, start + TEXT_LINES_PER_CHUNK);
    pages.push({
      kind: "text",
      name,
      gap: 0,
      load: async () => {
        const canvas = createCanvas(PRINT_WIDTH, chunk.length * lineHeight);
        const ctx = canvas.getContext("2d");
        ctx.fillStyle = "#fff";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = "#000";
        ctx.font = font;
        ctx.textBaseline = "top";
        chunk.forEach((line, i) => ctx.fillText(line, TEXT_MARGIN, i * lineHeight));
        return canvas;
      },
    });
  }
  if (pages.length) pages[pages.length - 1].gap = PAGE_GAP;
  return pages;
}

// Wraps at spaces when possible, otherwise anywhere (like Pango's WORD_CHAR).
function wrapLine(line, ctx, maxWidth) {
  if (!line) return [""];
  const out = [];
  let rest = line;
  while (ctx.measureText(rest).width > maxWidth) {
    let cut = rest.length;
    while (cut > 1 && ctx.measureText(rest.slice(0, cut)).width > maxWidth) cut--;
    const space = rest.lastIndexOf(" ", cut);
    if (space > 0) cut = space + 1;
    out.push(rest.slice(0, cut).trimEnd());
    rest = rest.slice(cut);
  }
  out.push(rest);
  return out;
}

function createCanvas(width, height) {
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, width);
  canvas.height = Math.max(1, height);
  return canvas;
}

function rotate(canvas) {
  const out = createCanvas(canvas.height, canvas.width);
  const ctx = out.getContext("2d");
  ctx.translate(out.width, 0);
  ctx.rotate(Math.PI / 2);
  ctx.drawImage(canvas, 0, 0);
  return out;
}

// Draws canvas (or a part of it) at width x height over a white background.
function flatten(canvas, width, height, sx = 0, sy = 0, sw = canvas.width, sh = canvas.height) {
  const out = createCanvas(width, height);
  const ctx = out.getContext("2d", { willReadFrequently: true });
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, width, height);
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(canvas, sx, sy, sw, sh, 0, 0, width, height);
  return out;
}

function toGray(canvas) {
  const { data } = canvas.getContext("2d", { willReadFrequently: true })
    .getImageData(0, 0, canvas.width, canvas.height);
  const gray = new Uint8Array(canvas.width * canvas.height);
  for (let i = 0, j = 0; i < gray.length; i++, j += 4) {
    gray[i] = (77 * data[j] + 150 * data[j + 1] + 29 * data[j + 2]) >> 8;
  }
  return gray;
}

// Crops white margins so the content uses the whole paper width.
// Returns the source rectangle [x, y, width, height].
function contentBox(canvas) {
  const sw = Math.min(canvas.width, 600);
  const sh = Math.max(1, Math.round(canvas.height * sw / canvas.width));
  const gray = toGray(flatten(canvas, sw, sh));
  let top = -1, bottom = -1, left = sw, right = -1;
  for (let y = 0; y < sh; y++) {
    for (let x = 0; x < sw; x++) {
      if (gray[y * sw + x] < CROP_THRESHOLD) {
        if (top < 0) top = y;
        bottom = y;
        if (x < left) left = x;
        if (x > right) right = x;
      }
    }
  }
  if (top < 0) return [0, 0, canvas.width, canvas.height];
  const sx = canvas.width / sw, sy = canvas.height / sh;
  const pad = Math.round(Math.max(canvas.width, canvas.height) * CROP_PADDING);
  const x0 = Math.max(0, Math.floor(left * sx) - pad);
  const y0 = Math.max(0, Math.floor(top * sy) - pad);
  const x1 = Math.min(canvas.width, Math.floor((right + 1) * sx) + pad);
  const y1 = Math.min(canvas.height, Math.floor((bottom + 1) * sy) + pad);
  return [x0, y0, x1 - x0, y1 - y0];
}

function toneTable(brightness, contrast) {
  const c = contrast * 2.55;
  const factor = (259 * (c + 255)) / (255 * (259 - c));
  return Uint8Array.from({ length: 256 }, (_, v) =>
    Math.max(0, Math.min(255, Math.round(factor * (v - 128) + 128 + brightness * 2.55))));
}

function threshold(gray) {
  return gray.map((v) => (v < 128 ? 1 : 0));
}

function floydSteinberg(gray, w, h) {
  const px = Int16Array.from(gray);
  const out = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = y * w + x;
      const old = px[i];
      const err = old < 128 ? old : old - 255;
      if (old < 128) out[i] = 1;
      if (!err) continue;
      if (x + 1 < w) px[i + 1] += (err * 7) >> 4;
      if (y + 1 < h) {
        if (x > 0) px[i + w - 1] += (err * 3) >> 4;
        px[i + w] += (err * 5) >> 4;
        if (x + 1 < w) px[i + w + 1] += err >> 4;
      }
    }
  }
  return out;
}

function atkinson(gray, w, h) {
  const px = Int16Array.from(gray);
  const out = new Uint8Array(w * h);
  const n = w * h;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = y * w + x;
      const old = px[i];
      if (old < 128) out[i] = 1;
      const err = (old < 128 ? old : old - 255) >> 3;
      if (!err) continue;
      if (x + 1 < w) px[i + 1] += err;
      if (x + 2 < w) px[i + 2] += err;
      for (const j of [x > 0 ? i + w - 1 : -1, i + w, x + 1 < w ? i + w + 1 : -1, i + 2 * w]) {
        if (j >= 0 && j < n) px[j] += err;
      }
    }
  }
  return out;
}

// Thickens strokes by one dot to the right, so thin text prints darker.
function embolden(bits, w, h) {
  const out = bits.slice();
  for (let y = 0; y < h; y++) {
    for (let x = 1; x < w; x++) {
      if (bits[y * w + x - 1]) out[y * w + x] = 1;
    }
  }
  return out;
}

export function resolveMode(mode, kind) {
  if (mode !== "auto") return mode;
  return kind === "image" ? "photo" : "sharp";
}

// options: { mode, brightness, contrast, rotate, crop, bold }
export async function processPage(page, options) {
  let canvas = await page.load();
  const isText = page.kind === "text";
  if (!isText && options.rotate) canvas = rotate(canvas);
  const box = !isText && options.crop ? contentBox(canvas) : [0, 0, canvas.width, canvas.height];

  const w = PRINT_WIDTH;
  const h = Math.max(1, Math.round(box[3] * w / box[2]));
  let gray = toGray(flatten(canvas, w, h, ...box));
  if (options.brightness || options.contrast) {
    const table = toneTable(options.brightness, options.contrast);
    gray = gray.map((v) => table[v]);
  }

  const mode = resolveMode(options.mode, page.kind);
  let bits = mode === "photo" ? floydSteinberg(gray, w, h)
    : mode === "atkinson" ? atkinson(gray, w, h)
      : threshold(gray);
  if (options.bold) bits = embolden(bits, w, h);

  let rows = Array.from({ length: h }, (_, y) => bits.subarray(y * w, (y + 1) * w));
  if (options.crop && !isText) rows = trimBlankRows(rows);
  return rows;
}

function trimBlankRows(rows) {
  const marked = rows.map((row, i) => (row.some((v) => v) ? i : -1)).filter((i) => i >= 0);
  if (!marked.length) return rows;
  return rows.slice(Math.max(0, marked[0] - TRIM_PADDING_ROWS),
    Math.min(rows.length, marked[marked.length - 1] + 1 + TRIM_PADDING_ROWS));
}

export function blankRows(count) {
  return Array.from({ length: count }, () => new Uint8Array(PRINT_WIDTH));
}

// Draws rows on a canvas, black on white, exactly as they will be printed.
export function previewCanvas(rows) {
  const canvas = createCanvas(PRINT_WIDTH, rows.length);
  const ctx = canvas.getContext("2d");
  const image = ctx.createImageData(PRINT_WIDTH, Math.max(1, rows.length));
  rows.forEach((row, y) => {
    for (let x = 0; x < PRINT_WIDTH; x++) {
      const i = (y * PRINT_WIDTH + x) * 4;
      const v = row[x] ? 0 : 255;
      image.data[i] = image.data[i + 1] = image.data[i + 2] = v;
      image.data[i + 3] = 255;
    }
  });
  ctx.putImageData(image, 0, 0);
  return canvas;
}

// "1-3, 5" -> [0, 1, 2, 4]. Empty means all pages. Throws if not valid.
export function parsePageRange(text, count) {
  text = text.trim();
  if (!text) return Array.from({ length: count }, (_, i) => i);
  const pages = [];
  for (let part of text.replace(/;/g, ",").split(",")) {
    part = part.trim();
    if (!part) continue;
    let start, end;
    if (part.includes("-")) {
      const [a, b] = part.split("-", 2).map((s) => s.trim());
      start = a ? Number(a) : 1;
      end = b ? Number(b) : count;
    } else {
      start = end = Number(part);
    }
    if (!Number.isInteger(start) || !Number.isInteger(end) || start < 1 || start > end || end > count) {
      throw new RangeError(part);
    }
    for (let i = start - 1; i < end; i++) pages.push(i);
  }
  return pages;
}
