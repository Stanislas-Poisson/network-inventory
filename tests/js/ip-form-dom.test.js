// Runs the page script against a minimal fake DOM, to check the behaviour of the form.
const test = require("node:test");
const assert = require("node:assert");

function element(extra = {}) {
  const listeners = {};
  return Object.assign(
    {
      value: "",
      textContent: "",
      placeholder: "",
      hidden: true,
      validity: "",
      addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
      fire(type, event = {}) { (listeners[type] || []).forEach((fn) => fn(Object.assign({ target: this }, event))); },
      setCustomValidity(message) { this.validity = message; },
      focus() { this.focused = true; },
    },
    extra,
  );
}

function page() {
  const data = {
    groups: [
      { id: 1, name: "PC", ranges: [{ first: "192.0.2.10", last: "192.0.2.19" }] },
      { id: 3, name: "Free", ranges: [{ first: "192.0.2.100", last: "192.0.2.199" }] },
    ],
    used: { "192.0.2.10": "Desk" },
    group: null,
  };
  const group = element({ value: "1" });
  const ip = element();
  const mac = element();
  const name = element();
  const feedback = element();
  const connectedSelect = element();
  const box = element({ querySelector: () => connectedSelect });
  const form = {
    getAttribute: () => JSON.stringify(data),
    querySelector(selector) {
      const found = {
        "select[name=group_id]": group,
        "input[name=ip]": ip,
        "input[name=mac]": mac,
        "input[name=name]": name,
        ".ip-feedback": feedback,
        "[data-connected]": box,
      };
      return found[selector] || null;
    },
  };
  globalThis.document = { querySelectorAll: () => [form] };
  require("../../src/network_inventory/web/static/ip-form.js");
  return { group, ip, mac, name, feedback, box, connectedSelect };
}

const { group, ip, mac, name, feedback, box, connectedSelect } = page();

function choose(value, seenIp) {
  connectedSelect.selectedOptions = [{ value, getAttribute: () => seenIp }];
  connectedSelect.fire("change", { target: connectedSelect });
}

test("the menu is shown by the script", () => {
  assert.strictEqual(box.hidden, false);
});

test("changing the group proposes the first free IP of that group", () => {
  group.value = "3";
  group.fire("change");
  assert.strictEqual(ip.value, "192.0.2.100");
  group.value = "1";
  group.fire("change");
  assert.strictEqual(ip.value, "192.0.2.11");
});

test("choosing a connected device fills the MAC, keeps its IP and selects its group", () => {
  choose("de:ad:be:ef:00:01", "192.0.2.150");
  assert.strictEqual(mac.value, "de:ad:be:ef:00:01");
  assert.strictEqual(ip.value, "192.0.2.150");
  assert.strictEqual(group.value, "3");
  assert.strictEqual(ip.validity, "");
  assert.strictEqual(name.focused, true);
});

test("changing the group afterwards does not rewrite the IP of the connected device", () => {
  group.value = "1";
  group.fire("change");
  assert.strictEqual(ip.value, "192.0.2.150");
  assert.match(ip.validity, /Outside the range of PC/);
  assert.match(feedback.textContent, /Outside the range of PC/);
});

test("a device outside every group keeps its IP and the current group", () => {
  group.value = "1";
  choose("de:ad:be:ef:00:02", "192.0.2.50");
  assert.strictEqual(ip.value, "192.0.2.50");
  assert.strictEqual(group.value, "1");
  assert.match(ip.validity, /Outside the range/);
});

test("an IP already used is reported with its owner", () => {
  ip.value = "192.0.2.10";
  ip.fire("input");
  assert.match(ip.validity, /already used by Desk/);
});
