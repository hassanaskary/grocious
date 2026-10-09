/* Translates text added after the server rendered the selected language. */
(function () {
  "use strict";
  var locale = document.documentElement.dataset.language === "no" ? "no" : "en";
  var translations = window.grociousTranslations || {};
  var ignored = new Set(["CODE", "PRE", "SCRIPT", "STYLE", "TEXTAREA"]);

  function translate(value) {
    if (locale === "no" || !value) return value;
    var lead = value.match(/^\s*/)[0], tail = value.match(/\s*$/)[0], core = value.trim();
    if (Object.prototype.hasOwnProperty.call(translations, core)) return lead + translations[core] + tail;
    core = core.replace(/^(Brukt i|Opptjent bonus i|Tilbud og rabatter i|Kuponger i)\s*(\d{4})?$/, function (_, prefix, year) {
      return translations[prefix] + (year ? " " + year : "");
    });
    core = core.replace(/^(\d+) kvitteringer$/, "$1 receipts");
    core = core.replace(/^(\d+) venter på gjennomgang · (\d+) bekreftet$/, "$1 awaiting review · $2 confirmed");
    core = core.replace(/^Sum (.+?)( · bonus .+)?( · rabatt .+)?$/, function (_, total, bonus, discount) {
      return "Total " + total.replace(/\bkr\b/g, "NOK") + (bonus ? bonus.replace(/\bkr\b/g, "NOK") : "") +
        (discount ? discount.replace("rabatt", "discount").replace(/\bkr\b/g, "NOK") : "");
    });
    core = core.replace(/kontrollavvik/g, "validation issue");
    core = core.replace(/^\+?([\d,.]+)\s*kr$/, "$1 NOK");
    core = core.replace(/^Viser (.+)–(.+) av (\d+)$/, "Showing $1–$2 of $3");
    core = core.replace(/^Hele (\d{4})$/, "All of $1");
    core = core.replace(/^Aktiver · (.+)$/, "Activate · $1");
    core = core.replace(/^Arkivert (.+)\. Dokumenter kontrolleres mot SHA-256 ved nedlasting\.$/, "Archived $1. Documents are checked against SHA-256 when downloaded.");
    core = core.replace(/^For eksempel (.+)$/, "For example, $1");
    core = core.replace(/^Butikk \/ forhandler · (.+)$/, "Store / retailer · $1");
    core = core.replace(/^Leverandørbilder · (.+) · (.+)$/, "Retailer images · $1 · $2");
    core = core.replace(/^Opplysninger hentet fra (.+)\. Å åpne tilbudet aktiverer det ikke\.$/, "Information retrieved from $1. Opening an offer does not activate it.");
    core = core.replace(/^Butikk: (.+) · Husholdningsmedlem: (.+) · Mottatt via: (.+) · Status: (.+)$/, "Store: $1 · Household member: $2 · Received via: $3 · Status: $4");
    core = core.replace(/^Kunne ikke hente varelinjer \((.+)\)\.$/, "Could not load line items ($1).");
    core = core.replace(/^Aktiv: (.+)$/, "Active: $1");
    core = core.replace(/^(.+) · (\d+) inn \/ (\d+) ut · (.+)$/, "$1 · $2 in / $3 out · $4");
    core = core.replace(/^(\d+)–(\d+) av (\d+)$/, "$1–$2 of $3");
    core = core.replace(/^Koblede bilag \((\d+)\)$/, "Linked receipts ($1)");
    core = core.replace(/^Flere bilag til samme kjøp\? \((\d+)\)$/, "Multiple receipts for the same purchase? ($1)");
    core = core.replace(/^Bruk (.+) \(denne\) som bilag$/, "Use $1 (this one) as receipt");
    core = core.replace(/^Bruk (.+) som bilag$/, "Use $1 as receipt");
    core = core.replace(/^Innboks(?: \((\d+)\))?$/, function (_, count) { return "Inbox" + (count ? " (" + count + ")" : ""); });
    core = core.replace(/^eksport (\d{4}-\d{2})$/, "export $1");
    core = core.replace(/^(.+) · innboks · grocious$/, "$1 · Inbox · grocious");
    core = core.replace(/^(.+)– kvitteringsarkiv( · grocious)?$/, "$1– receipt archive$2");
    core = core.replace(/^(\d+) arkiverte kjøp(.*)$/, "$1 archived purchases$2");
    core = core.replace(/ · samme beløp og valuta/g, " · same amount and currency");
    return lead + (translations[core] || core) + tail;
  }

  function localize(node) {
    if (node.nodeType === Node.TEXT_NODE) {
      if (node.parentElement && node.parentElement.closest('[translate="no"]')) return;
      var value = translate(node.nodeValue);
      if (value !== node.nodeValue) node.nodeValue = value;
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    if (node.hasAttribute("translate") && node.getAttribute("translate") === "no") return;
    ["alt", "aria-label", "placeholder", "title"].forEach(function (name) {
      var original = node.getAttribute(name);
      if (original !== null) {
        var translated = translate(original);
        if (translated !== original) node.setAttribute(name, translated);
      }
    });
    if (ignored.has(node.tagName)) return;
    node.childNodes.forEach(localize);
  }

  if (locale === "en") {
    localize(document.body);
    new MutationObserver(function (records) {
      records.forEach(function (record) {
        record.addedNodes.forEach(localize);
        if (record.type === "attributes") localize(record.target);
      });
    }).observe(document.body, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
      attributeFilter: ["alt", "aria-label", "placeholder", "title"]
    });
  }
  window.grociousLocale = locale;
  window.grociousTranslate = translate;
}());
