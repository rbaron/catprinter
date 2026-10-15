// Web Bluetooth connection to the printer: a port of PrinterConnection in
// catprinter/ble.py. Emits "status", "connected" and "disconnected" events.
import {
  BUSY_NOTIFICATION, CMD_DEV_STATE, GET_BATTERY, GET_DEV_STATE, READY_NOTIFICATION,
  parseNotification,
} from "./protocol.js";

const SERVICES = [0xae30, 0xaf30, 0xae00];
const TX_CHARACTERISTIC = 0xae01;
const RX_CHARACTERISTIC = 0xae02;
const NAME_PREFIXES = ["GB0", "GT01", "MX", "YT01", "PD01", "SC03", "_ZZ00"];

// Largest packet the official app sends; some browsers only allow 20 bytes.
const PACKET_SIZE = 177;
const SMALL_PACKET_SIZE = 20;
const WAIT_AFTER_PACKET_MS = 20;
const STATUS_WAIT_MS = 1500;
const DONE_TIMEOUT_MS = 30000;
const RECONNECT_DELAYS_MS = [1000, 3000, 10000];

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const sameBytes = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);

// A promise that can be resolved from outside, like asyncio.Event.
class Signal {
  constructor() { this.reset(); this.set(); }
  reset() { this.done = false; this.promise = new Promise((r) => { this.resolve = r; }); }
  set() { this.done = true; this.resolve(); }
  wait(timeoutMs) {
    if (this.done) return Promise.resolve(true);
    return Promise.race([this.promise.then(() => true), sleep(timeoutMs).then(() => false)]);
  }
}

export class Printer extends EventTarget {
  static get supported() {
    return "bluetooth" in navigator;
  }

  constructor() {
    super();
    this.device = null;
    this.tx = null;
    this.status = {};
    this.packetSize = PACKET_SIZE;
    this.canSend = new Signal();
    this.stateReceived = new Signal();
    this.queue = Promise.resolve();
    this.wantConnection = false;
  }

  get connected() {
    return Boolean(this.device?.gatt.connected && this.tx);
  }

  get name() {
    return this.device?.name || "Impresora";
  }

  // Shows the browser's device chooser. Must be called from a user gesture.
  async choose() {
    const device = await navigator.bluetooth.requestDevice({
      filters: [
        ...SERVICES.map((service) => ({ services: [service] })),
        ...NAME_PREFIXES.map((namePrefix) => ({ namePrefix })),
      ],
      optionalServices: SERVICES,
    });
    await this.useDevice(device);
  }

  // Reconnects to a printer chosen in a previous visit, if the browser allows it.
  async restore() {
    if (!navigator.bluetooth.getDevices) return false;
    const devices = await navigator.bluetooth.getDevices();
    const device = devices.find((d) => NAME_PREFIXES.some((p) => d.name?.startsWith(p)));
    if (!device) return false;
    await this.useDevice(device);
    return true;
  }

  async useDevice(device) {
    if (this.device && this.device !== device) this.disconnect();
    this.device = device;
    this.wantConnection = true;
    device.addEventListener("gattserverdisconnected", this.onDisconnected);
    try {
      await this.open();
    } catch (error) {
      this.wantConnection = false;
      throw error;
    }
  }

  async open() {
    const server = await this.device.gatt.connect();
    const service = await findService(server);
    this.tx = await service.getCharacteristic(TX_CHARACTERISTIC);
    const rx = await service.getCharacteristic(RX_CHARACTERISTIC);
    rx.addEventListener("characteristicvaluechanged", this.onNotification);
    await rx.startNotifications();
    this.dispatchEvent(new Event("connected"));
    await this.queryStatus();
  }

  disconnect() {
    this.wantConnection = false;
    if (this.device?.gatt.connected) this.device.gatt.disconnect();
    this.tx = null;
  }

  onDisconnected = async () => {
    this.tx = null;
    this.dispatchEvent(new Event("disconnected"));
    for (const delay of RECONNECT_DELAYS_MS) {
      if (!this.wantConnection) return;
      await sleep(delay);
      try {
        await this.open();
        return;
      } catch {
        // Not in range yet; try again later.
      }
    }
  };

  onNotification = (event) => {
    const data = new Uint8Array(event.target.value.buffer);
    parseNotification(data, this.status);
    if (sameBytes(data, READY_NOTIFICATION)) {
      this.canSend.set();
    } else if (sameBytes(data, BUSY_NOTIFICATION)) {
      this.canSend.reset();
    } else if (data[2] === CMD_DEV_STATE) {
      this.stateReceived.set();
      this.dispatchEvent(new CustomEvent("status", { detail: { ...this.status } }));
    }
  };

  // Runs printer operations one after another.
  exclusive(task) {
    const run = this.queue.then(task, task);
    this.queue = run.catch(() => {});
    return run;
  }

  queryStatus() {
    return this.exclusive(async () => {
      this.stateReceived.reset();
      await this.write(GET_DEV_STATE);
      await this.write(GET_BATTERY);
      await this.stateReceived.wait(STATUS_WAIT_MS);
      return { ...this.status };
    });
  }

  // Sends data from printCommands() and waits until the printer has processed
  // it. onProgress is called with the fraction of data sent so far.
  print(data, onProgress) {
    return this.exclusive(async () => {
      this.canSend.set();
      let offset = 0;
      while (offset < data.length) {
        const size = Math.min(this.packetSize, data.length - offset);
        if (offset + size >= data.length) {
          // The data ends with a state query; its answer means "done".
          this.stateReceived.reset();
        }
        if (!(await this.canSend.wait(DONE_TIMEOUT_MS))) {
          throw new Error("La impresora no respondió a tiempo.");
        }
        try {
          await this.write(data.subarray(offset, offset + size));
        } catch (error) {
          if (this.packetSize === SMALL_PACKET_SIZE || offset > 0) throw error;
          // This browser can't send large packets: retry with small ones.
          this.packetSize = SMALL_PACKET_SIZE;
          continue;
        }
        offset += size;
        onProgress?.(offset / data.length);
        await sleep(WAIT_AFTER_PACKET_MS);
      }
      await this.stateReceived.wait(DONE_TIMEOUT_MS);
      return { ...this.status };
    });
  }

  async write(bytes) {
    if (!this.connected) throw new Error("La impresora no está conectada.");
    const value = bytes instanceof Uint8Array ? bytes : Uint8Array.from(bytes);
    if (this.tx.writeValueWithoutResponse) {
      await this.tx.writeValueWithoutResponse(value);
    } else {
      await this.tx.writeValue(value);
    }
  }
}

async function findService(server) {
  for (const uuid of SERVICES) {
    try {
      const service = await server.getPrimaryService(uuid);
      await service.getCharacteristic(TX_CHARACTERISTIC);
      return service;
    } catch {
      // Not this one.
    }
  }
  throw new Error("Este dispositivo no parece una impresora compatible.");
}
