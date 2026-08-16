/* Embeddable Skew voice widget — one <script> tag, no Node require/module. */
(function (root) {
  if (root.SkewVoiceWidget) return;
  function mount(target, opts) {
    opts = opts || {};
    var el = typeof target === "string" ? root.document.querySelector(target) : target;
    if (!el) {
      el = root.document.createElement("div");
      el.id = "skew-voice-widget";
      root.document.body.appendChild(el);
    }
    el.setAttribute("data-skew-widget", "1");
    el.textContent = "";
    var label = root.document.createElement("p");
    label.textContent = opts.label || "Skew voice — audited contact";
    var btn = root.document.createElement("button");
    btn.type = "button";
    btn.textContent = opts.cta || "Start contact";
    btn.addEventListener("click", function () {
      label.textContent = "Contact started (widget). Use /api/frontline to attach a live session.";
    });
    el.appendChild(label);
    el.appendChild(btn);
    return el;
  }
  root.SkewVoiceWidget = {
    version: "1.0.0",
    mount: mount,
    install: function (opts) {
      return mount((opts && opts.target) || "#skew-voice-widget", opts);
    },
  };
})(typeof window !== "undefined" ? window : this);
