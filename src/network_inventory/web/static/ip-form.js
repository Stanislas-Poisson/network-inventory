// Progressive enhancement for the forms that ask for an IP: propose the first free IP of
// the chosen group and tell at once when an IP is outside the group or already used.
// The server checks everything again: this only saves a round trip.
(function () {
  "use strict";

  function toInt(ip) {
    var parts = String(ip).trim().split(".");
    if (parts.length !== 4) return null;
    var value = 0;
    for (var i = 0; i < 4; i++) {
      if (!/^\d{1,3}$/.test(parts[i]) || Number(parts[i]) > 255) return null;
      value = value * 256 + Number(parts[i]);
    }
    return value;
  }

  function toIp(value) {
    return [value >>> 24, (value >>> 16) & 255, (value >>> 8) & 255, value & 255].join(".");
  }

  function inRange(value, range) {
    return value >= toInt(range.first) && value <= toInt(range.last);
  }

  function describe(group) {
    return group.ranges.map(function (r) { return r.first + " to " + r.last; }).join(", ");
  }

  // The first address of the group's ranges that nobody expects, or null when it is full.
  function firstFree(group, used) {
    for (var r = 0; r < group.ranges.length; r++) {
      var first = toInt(group.ranges[r].first);
      var last = toInt(group.ranges[r].last);
      for (var value = first; value <= last; value++) {
        if (!Object.prototype.hasOwnProperty.call(used, toIp(value))) return toIp(value);
      }
    }
    return null;
  }

  // An empty string when the IP is acceptable, else the message to show.
  function check(ip, group, used) {
    if (String(ip).trim() === "") return "";
    var value = toInt(ip);
    if (value === null) return "This is not a valid IPv4 address.";
    if (!group.ranges.some(function (r) { return inRange(value, r); })) {
      return "Outside the range of " + group.name + " (" + describe(group) + ").";
    }
    var normal = toIp(value);
    if (Object.prototype.hasOwnProperty.call(used, normal)) {
      return normal + " is already used by " + used[normal] + ".";
    }
    return "";
  }

  // The group whose ranges hold the IP (the groups do not overlap), or null.
  function groupFor(ip, groups) {
    var value = toInt(ip);
    if (value === null) return null;
    for (var i = 0; i < groups.length; i++) {
      if (groups[i].ranges.some(function (r) { return inRange(value, r); })) return groups[i];
    }
    return null;
  }

  var logic = { toInt: toInt, toIp: toIp, firstFree: firstFree, check: check, groupFor: groupFor };

  if (typeof module !== "undefined" && module.exports) module.exports = logic;
  if (typeof document === "undefined") return;

  function setup(form) {
    var data = JSON.parse(form.getAttribute("data-ip-form"));
    var select = form.querySelector("select[name=group_id]");
    var input = form.querySelector("input[name=ip]");
    var feedback = form.querySelector(".ip-feedback");
    if (!input || !feedback) return;

    var groups = {};
    data.groups.forEach(function (g) { groups[String(g.id)] = g; });
    var lastSuggestion = input.value;

    function group() {
      return groups[select ? select.value : String(data.group)];
    }

    function validate() {
      var g = group();
      var message = g ? check(input.value, g, data.used) : "";
      input.setCustomValidity(message);
      feedback.textContent = message;
      if (g) input.placeholder = describe(g);
    }

    function suggest() {
      var g = group();
      if (!g) return;
      // Replace the IP only when the person did not type their own.
      if (input.value === "" || input.value === lastSuggestion) {
        var free = firstFree(g, data.used);
        input.value = free || "";
        lastSuggestion = input.value;
        if (!free) feedback.textContent = g.name + " is full.";
      }
      validate();
    }

    if (select) select.addEventListener("change", suggest);
    input.addEventListener("input", validate);
    validate();

    // A connected device is registered as it is seen: its MAC, its IP (never rewritten) and
    // the group that holds that IP.
    var box = form.querySelector("[data-connected]");
    var mac = form.querySelector("input[name=mac]");
    if (box && mac) {
      box.hidden = false;
      box.querySelector("select").addEventListener("change", function (event) {
        var option = event.target.selectedOptions[0];
        if (!option || !option.value) return;
        mac.value = option.value;
        var seen = option.getAttribute("data-ip");
        var found = groupFor(seen, data.groups);
        if (select && found) select.value = String(found.id);
        // Not the suggested IP any more: changing the group by hand will not replace it.
        input.value = seen;
        validate();
        var name = form.querySelector("input[name=name]");
        if (name && name.value === "") name.focus();
      });
    }
  }

  document.querySelectorAll("form[data-ip-form]").forEach(setup);
})();
