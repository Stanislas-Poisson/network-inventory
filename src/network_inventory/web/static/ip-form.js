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

  // The first address of the group's range that nobody expects, or null when it is full.
  function firstFree(group, used) {
    var first = toInt(group.first);
    var last = toInt(group.last);
    for (var value = first; value <= last; value++) {
      if (!Object.prototype.hasOwnProperty.call(used, toIp(value))) return toIp(value);
    }
    return null;
  }

  // An empty string when the IP is acceptable, else the message to show.
  function check(ip, group, used) {
    if (String(ip).trim() === "") return "";
    var value = toInt(ip);
    if (value === null) return "This is not a valid IPv4 address.";
    if (value < toInt(group.first) || value > toInt(group.last)) {
      return "Outside the range of " + group.name + " (" + group.first + " to " + group.last + ").";
    }
    var normal = toIp(value);
    if (Object.prototype.hasOwnProperty.call(used, normal)) {
      return normal + " is already used by " + used[normal] + ".";
    }
    return "";
  }

  var logic = { toInt: toInt, toIp: toIp, firstFree: firstFree, check: check };

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
      if (g) input.placeholder = g.first + " to " + g.last;
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
  }

  // The menu of connected devices fills the MAC field.
  function setupConnected(form) {
    var box = form.querySelector("[data-connected]");
    var mac = form.querySelector("input[name=mac]");
    if (!box || !mac) return;
    box.hidden = false;
    box.querySelector("select").addEventListener("change", function (event) {
      if (!event.target.value) return;
      mac.value = event.target.value;
      var name = form.querySelector("input[name=name]");
      if (name && name.value === "") name.focus();
    });
  }

  document.querySelectorAll("form[data-ip-form]").forEach(function (form) {
    setup(form);
    setupConnected(form);
  });
})();
