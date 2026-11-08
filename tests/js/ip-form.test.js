const test = require("node:test");
const assert = require("node:assert");
const { toInt, toIp, firstFree, check, groupFor } = require("../../src/network_inventory/web/static/ip-form.js");

const group = { id: 1, name: "PC", first: "192.0.2.10", last: "192.0.2.12" };

test("toInt and toIp are inverse and reject bad input", () => {
  assert.strictEqual(toIp(toInt("192.0.2.10")), "192.0.2.10");
  for (const bad of ["", "1.2.3", "1.2.3.256", "a.b.c.d", "1.2.3.4.5"]) assert.strictEqual(toInt(bad), null);
});

test("firstFree skips the used addresses", () => {
  assert.strictEqual(firstFree(group, {}), "192.0.2.10");
  assert.strictEqual(firstFree(group, { "192.0.2.10": "A", "192.0.2.11": "B" }), "192.0.2.12");
});

test("firstFree is null when the group is full", () => {
  const used = { "192.0.2.10": "A", "192.0.2.11": "B", "192.0.2.12": "C" };
  assert.strictEqual(firstFree(group, used), null);
});

test("check accepts a free address in the range and an empty field", () => {
  assert.strictEqual(check("192.0.2.11", group, {}), "");
  assert.strictEqual(check("  ", group, {}), "");
});

test("check explains what is wrong", () => {
  assert.match(check("nope", group, {}), /not a valid/);
  assert.match(check("192.0.2.99", group, {}), /Outside the range of PC/);
  assert.match(check("192.0.2.11", group, { "192.0.2.11": "Desk" }), /already used by Desk/);
});

test("groupFor finds the group that holds the IP", () => {
  const groups = [group, { id: 2, name: "Free", first: "192.0.2.100", last: "192.0.2.199" }];
  assert.strictEqual(groupFor("192.0.2.150", groups).name, "Free");
  assert.strictEqual(groupFor("192.0.2.11", groups).name, "PC");
  assert.strictEqual(groupFor("192.0.2.50", groups), null);
  assert.strictEqual(groupFor("nope", groups), null);
});
