// Cat printer protocol: a port of catprinter/cmds.py and catprinter/status.py.
// Every command is 51 78 <cmd> 00 <len lo> <len hi> <payload...> <crc8> ff.

export const PRINT_WIDTH = 384;

// Flow control notifications: the printer asks us to pause when its buffer is full.
export const READY_NOTIFICATION = [0x51, 0x78, 0xae, 0x01, 0x01, 0x00, 0x00, 0x00, 0xff];
export const BUSY_NOTIFICATION = [0x51, 0x78, 0xae, 0x01, 0x01, 0x00, 0x10, 0x70, 0xff];

export const CMD_DEV_STATE = 0xa3;
const CMD_SET_QUALITY = 0xa4;
const CMD_LATTICE = 0xa6;
const CMD_UPDATE_DEVICE = 0xa9;
const CMD_FEED_PAPER = 0xa1;
const CMD_SET_ENERGY = 0xaf;
const CMD_DRAWING_MODE = 0xbe;
const CMD_SET_SPEED = 0xbd;
const CMD_BITMAP_ROW = 0xa2;
const CMD_RLE_ROW = 0xbf;
const CMD_BATTERY = 0xba;

// The official app re-sends the speed every this many rows, and sets this
// speed before feeding the paper at the end.
const SPEED_RESEND_ROWS = 200;
const FEED_SPEED = 25;
const FEED_LINES = 48;

const CRC_TABLE = (() => {
  const table = new Uint8Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let bit = 0; bit < 8; bit++) {
      c = c & 0x80 ? ((c << 1) ^ 0x07) & 0xff : (c << 1) & 0xff;
    }
    table[i] = c;
  }
  return table;
})();

export function crc8(bytes) {
  let crc = 0;
  for (const b of bytes) crc = CRC_TABLE[(crc ^ b) & 0xff];
  return crc;
}

export function command(cmd, payload) {
  return [0x51, 0x78, cmd, 0x00, payload.length & 0xff, payload.length >> 8,
    ...payload, crc8(payload), 0xff];
}

export const GET_DEV_STATE = command(CMD_DEV_STATE, [0x00]);
export const GET_BATTERY = command(CMD_BATTERY, [0x00]);
const SET_QUALITY_200_DPI = command(CMD_SET_QUALITY, [0x32]);
const UPDATE_DEVICE = command(CMD_UPDATE_DEVICE, [0x00]);
const PRINT_IMAGE_MODE = command(CMD_DRAWING_MODE, [0x00]);
const PRINT_TEXT_MODE = command(CMD_DRAWING_MODE, [0x01]);
const FEED_PAPER = command(CMD_FEED_PAPER, [FEED_LINES, 0x00]);
const LATTICE_START = command(CMD_LATTICE,
  [0xaa, 0x55, 0x17, 0x38, 0x44, 0x5f, 0x5f, 0x5f, 0x44, 0x38, 0x2c]);
const LATTICE_END = command(CMD_LATTICE,
  [0xaa, 0x55, 0x17, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x17]);

// Energy is little-endian, as the official app sends it.
export const setEnergy = (value) => command(CMD_SET_ENERGY, [value & 0xff, (value >> 8) & 0xff]);

// Higher values print slower and darker.
export const setSpeed = (value) => command(CMD_SET_SPEED, [value & 0xff]);

function encodeRepetition(count, value, out) {
  while (count > 0x7f) {
    out.push(0x7f | (value << 7));
    count -= 0x7f;
  }
  if (count > 0) out.push((value << 7) | count);
}

function runLengthEncode(row) {
  const out = [];
  let count = 0;
  let last = -1;
  for (const value of row) {
    if (value === last) {
      count++;
    } else {
      encodeRepetition(count, last, out);
      count = 1;
    }
    last = value;
  }
  encodeRepetition(count, last, out);
  return out;
}

function bitmapEncode(row) {
  const out = [];
  for (let start = 0; start < row.length; start += 8) {
    let byte = 0;
    for (let bit = 0; bit < 8; bit++) {
      if (row[start + bit]) byte |= 1 << bit;
    }
    out.push(byte);
  }
  return out;
}

// row: PRINT_WIDTH values, 1 = black. Uses run-length encoding when it is shorter.
export function printRow(row) {
  const rle = runLengthEncode(row);
  if (rle.length > PRINT_WIDTH / 8) return command(CMD_BITMAP_ROW, bitmapEncode(row));
  return command(CMD_RLE_ROW, rle);
}

// Builds the commands to print rows, the same sequence as the official app.
export function printCommands(rows, { energy, speed, textMode }) {
  const parts = [
    GET_DEV_STATE,
    SET_QUALITY_200_DPI,
    setEnergy(energy),
    textMode ? PRINT_TEXT_MODE : PRINT_IMAGE_MODE,
    setSpeed(speed),
    UPDATE_DEVICE,
    LATTICE_START,
  ];
  rows.forEach((row, i) => {
    if (i && i % SPEED_RESEND_ROWS === 0) parts.push(setSpeed(speed));
    parts.push(printRow(row));
  });
  parts.push(setSpeed(FEED_SPEED), FEED_PAPER, FEED_PAPER, FEED_PAPER, LATTICE_END, GET_DEV_STATE);

  const data = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let offset = 0;
  for (const part of parts) {
    data.set(part, offset);
    offset += part.length;
  }
  return data;
}

// Updates status from a notification. The state answer of an SC03h looks like
// 51 78 a3 01 03 00 <flags> <battery %> <temperature> <crc> ff.
export function parseNotification(data, status) {
  if (data.length < 8 || data[0] !== 0x51 || data[1] !== 0x78) return;
  const length = data[4] | (data[5] << 8);
  const payload = data.slice(6, 6 + length);
  if (!payload.length) return;
  if (data[2] === CMD_DEV_STATE) {
    const flags = payload[0];
    status.noPaper = Boolean(flags & 0x01);
    status.coverOpen = Boolean(flags & 0x02);
    status.overheat = Boolean(flags & 0x04);
    status.lowBattery = Boolean(flags & 0x08);
    status.charging = Boolean(flags & 0x10);
    if (payload.length >= 2 && payload[1] <= 100) status.battery = payload[1];
  } else if (data[2] === CMD_BATTERY && payload[0] <= 100) {
    status.battery = payload[0];
  }
}
