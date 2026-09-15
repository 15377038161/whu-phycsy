/* Session ticket (_sid) propagation.
 *
 * The platform proxy strips cookies in both directions, so the server-side
 * session ticket must travel in the URL. This script:
 *  1. reads the ticket from the current URL (or window.__SID injected by the
 *     template),
 *  2. appends it to all internal links and hidden form fields,
 *  3. patches fetch() so API calls carry it via the X-Session-Id header,
 *  4. keeps the ticket in the address bar so refresh/navigation stays logged in.
 */
(function () {
  "use strict";
  var sid = "";
  try {
    sid = new URLSearchParams(location.search).get("_sid") || window.__SID || "";
  } catch (e) {
    sid = window.__SID || "";
  }
  if (!sid) return;
  window.__SID = sid;

  function withSid(raw) {
    if (typeof raw !== "string" || !raw || raw.charAt(0) !== "/" || raw.indexOf("//") === 0) return raw;
    if (raw.indexOf("_sid=") !== -1) return raw;
    var hashIndex = raw.indexOf("#");
    var hash = hashIndex === -1 ? "" : raw.slice(hashIndex);
    var base = hashIndex === -1 ? raw : raw.slice(0, hashIndex);
    return base + (base.indexOf("?") === -1 ? "?" : "&") + "_sid=" + encodeURIComponent(sid) + hash;
  }

  function propagate(root) {
    var scope = root && root.querySelectorAll ? root : document;
    var links = scope.querySelectorAll("a[href]");
    for (var i = 0; i < links.length; i++) {
      var href = links[i].getAttribute("href");
      var patched = withSid(href);
      if (patched !== href) links[i].setAttribute("href", patched);
    }
    var forms = scope.querySelectorAll("form");
    for (var j = 0; j < forms.length; j++) {
      if (!forms[j].querySelector('input[name="_sid"]')) {
        var input = document.createElement("input");
        input.type = "hidden";
        input.name = "_sid";
        input.value = sid;
        input.setAttribute("data-sid-injected", "1");
        forms[j].appendChild(input);
      }
    }
    var media = scope.querySelectorAll("img[src], video[src], audio[src], source[src], iframe[src]");
    for (var k = 0; k < media.length; k++) {
      var src = media[k].getAttribute("src");
      var fixed = withSid(src);
      if (fixed !== src) media[k].setAttribute("src", fixed);
    }
  }

  function start() {
    propagate(document);
    if (window.MutationObserver && document.body) {
      var pending = false;
      new MutationObserver(function () {
        if (pending) return;
        pending = true;
        setTimeout(function () { pending = false; propagate(document); }, 0);
      }).observe(document.body, { childList: true, subtree: true });
    }
    // Keep the ticket visible in the address bar so refresh stays logged in.
    try {
      if (!new URLSearchParams(location.search).get("_sid")) {
        history.replaceState(null, "", withSid(location.pathname + location.search + location.hash));
      }
    } catch (e) { /* history API unavailable */ }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }

  if (window.fetch) {
    var nativeFetch = window.fetch;
    window.fetch = function (input, init) {
      init = init || {};
      var headers = new Headers(init.headers || (input && input.headers) || {});
      headers.set("X-Session-Id", sid);
      init.headers = headers;
      if (typeof input === "string" && input.charAt(0) === "/") input = withSid(input);
      return nativeFetch.call(this, input, init);
    };
  }
  if (window.XMLHttpRequest) {
    var nativeOpen = XMLHttpRequest.prototype.open;
    var nativeSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (method, url) {
      this.__sidUrl = typeof url === "string" && url.charAt(0) === "/" ? withSid(url) : url;
      return nativeOpen.apply(this, [method, this.__sidUrl].concat([].slice.call(arguments, 2)));
    };
    XMLHttpRequest.prototype.send = function () {
      try { this.setRequestHeader("X-Session-Id", sid); } catch (e) { /* not open yet */ }
      return nativeSend.apply(this, arguments);
    };
  }
  window.__withSid = withSid;
})();
