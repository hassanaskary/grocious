"""Shared English/Norwegian translations for rendered pages and browser UI."""

import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path


TRANSLATIONS = json.loads((Path(__file__).parent / "translations.json").read_text(encoding="utf-8"))
LANGUAGES = ("en", "no")
_ATTRIBUTES = {"alt", "aria-label", "placeholder", "title"}
_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"
}
_RAW_TAGS = {"code", "pre", "script", "style", "textarea"}
_ATTRIBUTE_CASE = {"viewbox": "viewBox"}


def language(value):
    return value if value in LANGUAGES else "en"


def translate(value, locale="en"):
    """Translate one visible string while leaving user supplied values alone."""
    if language(locale) == "no" or not value:
        return value
    leading = value[: len(value) - len(value.lstrip())]
    trailing = value[len(value.rstrip()) :]
    core = value.strip()
    exact = TRANSLATIONS.get(core)
    if exact is not None:
        return leading + exact + trailing

    for pattern, replacement in (
        (r"^(Brukt i|Opptjent bonus i|Tilbud og rabatter i|Kuponger i)\s*(\d{4})?$", None),
        (r"^(\d+) kvitteringer$", r"\1 receipts"),
        (r"^(\d+) venter på gjennomgang · (\d+) bekreftet$", r"\1 awaiting review · \2 confirmed"),
        (r"^Sum (.+?)( · bonus .+)?( · rabatt .+)?$", None),
        (r"^Viser (.+)–(.+) av (\d+)$", r"Showing \1–\2 of \3"),
        (
            r"^Arkivert (.+)\. Dokumenter kontrolleres mot SHA-256 ved nedlasting\.$",
            r"Archived \1. Documents are checked against SHA-256 when downloaded.",
        ),
        (
            r"^Opplysninger hentet fra (.+)\. Å åpne tilbudet aktiverer det ikke\.$",
            r"Information retrieved from \1. Opening an offer does not activate it.",
        ),
        (
            r"^Butikk: (.+) · Husholdningsmedlem: (.+) · Mottatt via: (.+) · Status: (.+)$",
            r"Store: \1 · Household member: \2 · Received via: \3 · Status: \4",
        ),
        (r"^Kunne ikke hente varelinjer \((.+)\)\.$", r"Could not load line items (\1)."),
        (r"^Butikk / forhandler · (.+)$", r"Store / retailer · \1"),
        (r"^Leverandørbilder · (.+) · (.+)$", r"Retailer images · \1 · \2"),
        (r"^For eksempel (.+)$", r"For example, \1"),
        (r"^Hele (\d{4})$", r"All of \1"),
        (r"^Aktiv: (.+)$", r"Active: \1"),
        (r"^(.+) · (\d+) inn / (\d+) ut · (.+)$", r"\1 · \2 in / \3 out · \4"),
        (r"^(\d+)–(\d+) av (\d+)$", r"\1–\2 of \3"),
        (r"^Koblede bilag \((\d+)\)$", r"Linked receipts (\1)"),
        (r"^Flere bilag til samme kjøp\? \((\d+)\)$", r"Multiple receipts for the same purchase? (\1)"),
        (r"^Bruk (.+) \(denne\) som bilag$", r"Use \1 (this one) as receipt"),
        (r"^Bruk (.+) som bilag$", r"Use \1 as receipt"),
        (r"^Innboks(?: \((\d+)\))?$", None),
        (r"^eksport (\d{4}-\d{2})$", r"export \1"),
        (r"^Aktiver · (.+)$", r"Activate · \1"),
        (r"^(.+) · innboks · grocious$", r"\1 · Inbox · grocious"),
        (r"^(.+)– kvitteringsarkiv( · grocious)?$", r"\1– receipt archive\2"),
        (r"^\+?([\d,.]+)\s*kr$", r"\1 NOK"),
        (r"^(\d+) arkiverte kjøp(.*)$", r"\1 archived purchases\2"),
        (
            r"^Saldoen inkluderer (.+?) kr medlemsinnskudd, som tilbakebetales ved avslutning\. "
            r"Startsaldo (.+?) kr før handel (\d{2})\.(\d{2})\.(\d{4}), oppgitt av deg, "
            r"pluss (.+?) kr bonus fra kvitteringer fra og med denne datoen\. "
            r"Kjøpeutbytte og kortbonus telles samlet; prisrabatter er ikke med\. "
            r"Dette er beregnet saldo inkludert opptjent bonus, ikke bekreftet disponibelt beløp\. "
            r"Ved uttak eller andre kontobevegelser må startsaldoen oppdateres\."
            r"(?: Bonus mangler på (\d+) kvitteringer\.)?$",
            None,
        ),
    ):
        match = re.match(pattern, core)
        if not match:
            continue
        if replacement is None and pattern.startswith("^(Brukt"):
            return leading + TRANSLATIONS[match.group(1)] + (" " + match.group(2) if match.group(2) else "") + trailing
        if replacement is None and pattern.startswith("^Sum"):
            total, bonus, discount = match.groups()
            result = "Total " + re.sub(r"\bkr\b", "NOK", total)
            if bonus:
                result += re.sub(r"\bkr\b", "NOK", bonus)
            if discount:
                result += re.sub(r"\bkr\b", "NOK", discount.replace("rabatt", "discount"))
            return leading + result + trailing
        if replacement is None and pattern.startswith("^Saldoen"):
            deposit, opening, day, month, year, earned, missing = match.groups()
            numbers = [number.replace(",", ".") for number in (deposit, opening, earned)]
            result = (
                f"Balance includes NOK {numbers[0]} in member deposits, which are repaid when membership ends. "
                f"Opening balance NOK {numbers[1]} before purchases on {day}/{month}/{year}, as reported by you, "
                f"plus NOK {numbers[2]} in receipt bonuses from that date onward. Member dividends and card bonus "
                "are counted together; price discounts are excluded. This is a calculated balance including earned "
                "bonus, not a confirmed available amount. Update the opening balance after withdrawals or other "
                "account activity."
            )
            if missing:
                result += f" Bonus is missing from {missing} receipts."
            return leading + result + trailing
        if replacement is None and pattern.startswith("^Innboks"):
            return leading + "Inbox" + (f" ({match.group(1)})" if match.group(1) else "") + trailing
        return leading + match.expand(replacement) + trailing
    core = core.replace("kontrollavvik", "validation issue")
    core = core.replace(" · samme beløp og valuta", " · same amount and currency")
    if "Innboks" in core:
        core = core.replace("Innboks", "Inbox")
    return leading + core + trailing


class _PageTranslator(HTMLParser):
    def __init__(self, locale):
        super().__init__(convert_charrefs=True)
        self.locale = language(locale)
        self.parts = []
        self.stack = []

    def _tag(self, tag, attrs, closed=False):
        rendered = []
        attrs = list(attrs)
        if tag == "html":
            attrs = [
                (key, "nb" if self.locale == "no" else "en") if key == "lang" else (key, value)
                for key, value in attrs
            ]
            if not any(key == "lang" for key, _ in attrs):
                attrs.append(("lang", "nb" if self.locale == "no" else "en"))
        for key, value in attrs:
            key = _ATTRIBUTE_CASE.get(key, key)
            if value is not None and key in _ATTRIBUTES and self.locale == "en":
                value = translate(value, self.locale)
            rendered.append(" " + key + ("=\"" + html.escape(value, quote=True) + "\"" if value is not None else ""))
        self.parts.append("<" + tag + "".join(rendered) + ("/>" if closed else ">"))

    def handle_starttag(self, tag, attrs):
        self._tag(tag, attrs)
        if tag not in _VOID_TAGS:
            inherited = self.stack[-1][1] if self.stack else False
            no_translate = inherited or any(key == "translate" and value == "no" for key, value in attrs)
            self.stack.append((tag, no_translate))

    def handle_startendtag(self, tag, attrs):
        self._tag(tag, attrs, closed=True)

    def handle_endtag(self, tag):
        self.parts.append("</" + tag + ">")
        matching = next((index for index in range(len(self.stack) - 1, -1, -1) if self.stack[index][0] == tag), None)
        if matching is not None:
            self.stack = self.stack[:matching]

    def handle_data(self, data):
        raw = any(tag in _RAW_TAGS for tag, _ in self.stack)
        skip_translation = raw or any(skip for _, skip in self.stack)
        if self.locale == "en" and not skip_translation:
            data = translate(data, self.locale)
        rendered = data if any(tag in {"script", "style"} for tag, _ in self.stack) else html.escape(data, quote=False)
        self.parts.append(rendered)

    def handle_entityref(self, name):
        self.parts.append("&" + name + ";")

    def handle_charref(self, name):
        self.parts.append("&#" + name + ";")

    def handle_comment(self, data):
        self.parts.append("<!--" + data + "-->")

    def handle_decl(self, decl):
        self.parts.append("<!" + decl + ">")

    def unknown_decl(self, data):
        self.parts.append("<![" + data + "]>")


def translate_html(source, locale="en"):
    parser = _PageTranslator(locale)
    parser.feed(source)
    parser.close()
    return "".join(parser.parts)
