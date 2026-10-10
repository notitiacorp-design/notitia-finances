/* DuoSpend: no executable HTML from user or model messages. */
(function () {
  'use strict';
  var allowed = new Set(['P', 'BR', 'STRONG', 'EM', 'B', 'I', 'UL', 'OL', 'LI', 'BLOCKQUOTE', 'CODE', 'PRE', 'H2', 'H3', 'H4', 'HR', 'A', 'TABLE', 'THEAD', 'TBODY', 'TR', 'TH', 'TD']);
  var discard = new Set(['SCRIPT', 'STYLE', 'IFRAME', 'OBJECT', 'EMBED', 'SVG', 'MATH', 'FORM', 'INPUT', 'TEXTAREA', 'BUTTON', 'LINK', 'META', 'BASE', 'IMG', 'VIDEO', 'AUDIO', 'SOURCE']);
  function escape(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'}[c]; });
  }
  function sanitize(html) {
    var template = document.createElement('template');
    template.innerHTML = String(html);
    function walk(parent) {
      Array.from(parent.childNodes).forEach(function (node) {
        if (node.nodeType === 8) { node.remove(); return; }
        if (node.nodeType !== 1) return;
        if (discard.has(node.tagName)) { node.remove(); return; }
        walk(node);
        if (!allowed.has(node.tagName)) {
          node.replaceWith.apply(node, Array.from(node.childNodes));
          return;
        }
        var link = node.tagName === 'A' ? node.getAttribute('href') : null;
        Array.from(node.attributes).forEach(function (attr) { node.removeAttribute(attr.name); });
        if (link) {
          try {
            var url = new URL(link, window.location.origin);
            if (url.protocol === 'https:' || url.protocol === 'http:') {
              node.setAttribute('href', url.href);
              node.setAttribute('target', '_blank');
              node.setAttribute('rel', 'noopener noreferrer');
            }
          } catch (e) {}
        }
      });
    }
    walk(template.content);
    return template.innerHTML;
  }
  function markdown(raw) {
    var text = String(raw == null ? '' : raw);
    // Raw HTML is shown as text; Markdown formatting remains available.
    var safe = escape(text);
    if (window.marked && typeof window.marked.parse === 'function') {
      try { return sanitize(window.marked.parse(safe, {gfm: true, breaks: true})); } catch (e) {}
    }
    return safe.replace(/\n/g, '<br>');
  }
  window.DuoSafe = Object.freeze({markdown: markdown, sanitize: sanitize, escape: escape});
})();
