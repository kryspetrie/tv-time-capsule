"""Multi-source alert feeds queued into one marquee stream.

Built-in adapters (no paid API keys required):

* **nws** — ``api.weather.gov`` active alerts for the configured point.
  Weather watches/warnings stay ``category=weather``; civil / IPAWS-style
  event codes (Civil Emergency Message, Amber Alert, etc.) are tagged
  ``emergency``.
* **flashalert** — FlashAlert / Craig Walker style ``flashnews`` XML used by
  many TV stations for school and organization closings (HTTP URL or local
  file dropped via FTP).
* **rss** / **atom** — generic RSS 2.0 or Atom feeds (school boards, local
  EMA pages, CAP *indexes*, etc.).
* **cap** — Atom/RSS CAP *index* feeds whose entries link to CAP 1.2 XML
  (fetched and summarized).

FEMA's IPAWS All-Hazards feed requires a free MOA / portal registration, so
it is not hard-wired; point a ``cap`` or ``rss`` feed at that URL after you
have access. School closings likewise have no single national free API —
configure a FlashAlert XML path/URL or a local RSS feed for your market.
"""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Sequence
from xml.etree.ElementTree import Element

from ..models import Alert, Location
from ..ports import AlertClient

LOG = logging.getLogger(__name__)

_UA = "tv-time-capsule/weather (https://github.com/kryspetrie/tv-time-capsule)"

# NWS event names that are civil / public-safety rather than meteorology.
_NWS_EMERGENCY_EVENTS = frozenset(
    {
        "911 Telephone Outage",
        "Administrative Message",
        "Blue Alert",
        "Child Abduction Emergency",
        "Civil Danger Warning",
        "Civil Emergency Message",
        "Earthquake Warning",
        "Evacuation Immediate",
        "Fire Warning",
        "Hazardous Materials Warning",
        "Law Enforcement Warning",
        "Local Area Emergency",
        "Nuclear Power Plant Warning",
        "Radiological Hazard Warning",
        "Shelter In Place Warning",
    }
)

# FlashAlert operating_code → short status (TV CGS convention).
_FLASHALERT_STATUS: dict[str, str] = {
    "1": "Closed",
    "2": "Early release / activities canceled",
    "3": "Opening late",
    "4": "1 hour late",
    "5": "2 hours late",
    "6": "Buses on snow routes",
    "7": "Test",
}

_CATEGORY_PRIORITY = {"emergency": 0, "school": 1, "weather": 2, "other": 3}


def _get_bytes(url: str, *, timeout: float = 18.0) -> bytes | None:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _UA,
            "Accept": "application/xml, text/xml, application/atom+xml, "
            "application/rss+xml, application/cap+xml, */*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        LOG.info("Alert feed fetch failed %s: %s", url, exc)
        return None


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _child_text(el: Element, *names: str) -> str:
    want = {n.lower() for n in names}
    for child in list(el):
        if _local_name(child.tag).lower() in want:
            return (child.text or "").strip()
    return ""


def _find_all(el: Element, name: str) -> list[Element]:
    name_l = name.lower()
    return [c for c in el.iter() if _local_name(c.tag).lower() == name_l]


def nws_alert_category(event: str) -> str:
    text = (event or "").strip()
    if text in _NWS_EMERGENCY_EVENTS:
        return "emergency"
    low = text.lower()
    if "abduction" in low or "amber" in low or "civil emergency" in low:
        return "emergency"
    if "school" in low and "clos" in low:
        return "school"
    return "weather"


def parse_nws_alert_features(alerts: dict[str, Any]) -> list[Alert]:
    """Parse api.weather.gov GeoJSON alerts into tagged :class:`Alert` rows."""
    out: list[Alert] = []
    for feat in alerts.get("features") or []:
        p = feat.get("properties") or {}
        event = str(p.get("event") or "")
        out.append(
            Alert(
                severity=str(p.get("severity") or "Unknown"),
                headline=str(p.get("headline") or p.get("event") or "Alert"),
                description=str(p.get("description") or "")[:800],
                event=event,
                category=nws_alert_category(event),
                source="nws",
            )
        )
    return out


class NwsAlertClient:
    """Active NWS alerts for a point (weather + civil emergency event codes)."""

    def fetch_alerts(self, location: Location) -> list[Alert]:
        from .forecast_nws import _get_json

        alerts = _get_json(
            "https://api.weather.gov/alerts/active"
            f"?point={location.latitude:.4f},{location.longitude:.4f}"
        )
        if not alerts:
            raise RuntimeError("NWS alerts fetch failed")
        return parse_nws_alert_features(alerts)


def parse_flashalert_xml(data: bytes) -> list[Alert]:
    """Parse FlashAlert ``flashnews`` XML into school/emergency alerts."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise RuntimeError(f"FlashAlert XML parse failed: {exc}") from exc
    out: list[Alert] = []
    for category in _find_all(root, "emergency_category"):
        cat_name = (category.get("name") or "").strip()
        for report in category.findall("emergency_report"):
            testing = str(report.attrib.get("testing") or "0")
            if testing not in ("0", "false", ""):
                continue
            op = str(report.attrib.get("operating_code") or "").strip()
            if op == "7":
                continue
            school = str(report.attrib.get("schoolrelated") or "0") in ("1", "true")
            org = _child_text(report, "orgname") or "Organization"
            detail = _child_text(report, "detail")
            status = _FLASHALERT_STATUS.get(op, detail or "Status update")
            if detail and len(detail) < 120 and detail.lower() not in status.lower():
                headline = f"{org}: {detail}"
            else:
                headline = f"{org}: {status}"
            if school or "school" in cat_name.lower():
                alert_category = "school"
            else:
                alert_category = "emergency"
            out.append(
                Alert(
                    severity="Severe" if op == "1" else "Moderate",
                    headline=headline,
                    description=detail[:800],
                    event=cat_name or ("School Closing" if school else "Closing"),
                    category=alert_category,
                    source="flashalert",
                )
            )
    return out


class FlashAlertClient:
    """FlashAlert / station CGS XML (HTTP URL and/or local file path)."""

    def __init__(self, *, url: str | None = None, path: str | None = None) -> None:
        self._url = (url or "").strip() or None
        self._path = Path(path).expanduser() if path else None

    def fetch_alerts(self, location: Location) -> list[Alert]:
        del location
        data: bytes | None = None
        if self._path is not None and self._path.is_file():
            try:
                data = self._path.read_bytes()
            except OSError as exc:
                raise RuntimeError(f"FlashAlert file read failed: {exc}") from exc
        elif self._url:
            data = _get_bytes(self._url, timeout=45.0)
            if data is None:
                raise RuntimeError("FlashAlert URL fetch failed")
        else:
            return []
        return parse_flashalert_xml(data)


def parse_rss_atom(data: bytes, *, category: str, source: str) -> list[Alert]:
    """Parse RSS 2.0 or Atom into alerts (headline = title, description = summary)."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise RuntimeError(f"RSS/Atom parse failed: {exc}") from exc
    out: list[Alert] = []
    for item in _find_all(root, "item"):
        title = _child_text(item, "title")
        if not title:
            continue
        desc = _child_text(item, "description", "summary")
        out.append(
            Alert(
                severity="Unknown",
                headline=title[:240],
                description=re.sub(r"<[^>]+>", "", desc)[:800],
                event=category.title(),
                category=category,
                source=source,
            )
        )
    for entry in _find_all(root, "entry"):
        title = _child_text(entry, "title")
        if not title:
            continue
        desc = _child_text(entry, "summary", "content", "description")
        out.append(
            Alert(
                severity="Unknown",
                headline=title[:240],
                description=re.sub(r"<[^>]+>", "", desc)[:800],
                event=category.title(),
                category=category,
                source=source,
            )
        )
    return out


class RssAtomAlertClient:
    """Generic RSS/Atom headline feed."""

    def __init__(
        self,
        url: str,
        *,
        category: str = "other",
        source: str = "rss",
    ) -> None:
        self._url = url.strip()
        self._category = (category or "other").strip().lower() or "other"
        self._source = source or "rss"

    def fetch_alerts(self, location: Location) -> list[Alert]:
        del location
        data = _get_bytes(self._url)
        if data is None:
            raise RuntimeError(f"RSS/Atom fetch failed: {self._url}")
        return parse_rss_atom(data, category=self._category, source=self._source)


def _parse_cap_alert(data: bytes, *, source: str) -> Alert | None:
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None
    info = None
    for el in root.iter():
        if _local_name(el.tag).lower() == "info":
            info = el
            break
    scope = info if info is not None else root
    event = _child_text(scope, "event") or "Alert"
    headline = _child_text(scope, "headline") or event
    desc = _child_text(scope, "description")
    severity = _child_text(scope, "severity") or "Unknown"
    category = nws_alert_category(event)
    if category == "weather" and event:
        low = f"{event} {headline}".lower()
        if "school" in low and ("clos" in low or "delay" in low):
            category = "school"
        elif any(
            k in low
            for k in ("emergency", "evacuate", "shelter", "amber", "hazardous")
        ):
            category = "emergency"
    return Alert(
        severity=severity,
        headline=headline[:240],
        description=desc[:800],
        event=event,
        category=category,
        source=source,
    )


class CapIndexAlertClient:
    """CAP Atom/RSS *index* — follow entry links to CAP 1.2 XML (capped)."""

    def __init__(self, url: str, *, max_items: int = 12, source: str = "cap") -> None:
        self._url = url.strip()
        self._max_items = max(1, min(40, int(max_items)))
        self._source = source

    def fetch_alerts(self, location: Location) -> list[Alert]:
        del location
        data = _get_bytes(self._url)
        if data is None:
            raise RuntimeError(f"CAP index fetch failed: {self._url}")
        try:
            root = ET.fromstring(data)
        except ET.ParseError as exc:
            raise RuntimeError(f"CAP index parse failed: {exc}") from exc

        links: list[str] = []
        for entry in list(_find_all(root, "entry")) + list(_find_all(root, "item")):
            href = ""
            for child in list(entry):
                name = _local_name(child.tag).lower()
                if name == "link":
                    href = (child.attrib.get("href") or child.text or "").strip()
                    if href:
                        break
                if name in ("id", "guid") and not href:
                    href = (child.text or "").strip()
            if href.startswith("http"):
                links.append(href)
            if len(links) >= self._max_items:
                break

        out: list[Alert] = []
        for link in links:
            raw = _get_bytes(link, timeout=12.0)
            if not raw:
                continue
            alert = _parse_cap_alert(raw, source=self._source)
            if alert is not None:
                out.append(alert)
        return out


def queue_alerts(groups: Sequence[list[Alert]]) -> list[Alert]:
    """Concatenate feed results, dedupe, and order for the marquee."""
    seen: set[str] = set()
    merged: list[Alert] = []
    for group in groups:
        for alert in group:
            key = f"{alert.category}|{alert.headline.strip().lower()}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(alert)

    def _sort_key(a: Alert) -> tuple[int, int, str]:
        sev = (a.severity or "").lower()
        sev_rank = {
            "extreme": 0,
            "severe": 1,
            "moderate": 2,
            "minor": 3,
            "unknown": 4,
        }.get(sev, 4)
        return (_CATEGORY_PRIORITY.get(a.category, 9), sev_rank, a.headline.lower())

    return sorted(merged, key=_sort_key)


class QueuedAlertClient:
    """Fetch every configured feed and queue results into one alert list."""

    def __init__(self, clients: Sequence[AlertClient]) -> None:
        self._clients = list(clients)

    def fetch_alerts(self, location: Location) -> list[Alert]:
        groups: list[list[Alert]] = []
        errors: list[str] = []
        succeeded = 0
        for client in self._clients:
            name = type(client).__name__
            try:
                groups.append(list(client.fetch_alerts(location)))
                succeeded += 1
            except Exception as exc:
                LOG.info("Alert feed %s failed: %s", name, exc)
                errors.append(f"{name}: {exc}")
        merged = queue_alerts(groups)
        if succeeded == 0 and errors:
            raise RuntimeError(
                "All alert feeds failed (" + "; ".join(errors) + ")"
            )
        return merged


def build_alert_client(weather_cfg: dict[str, Any] | None = None) -> AlertClient:
    """Build the default multi-feed :class:`QueuedAlertClient` from config."""
    cfg = weather_cfg if isinstance(weather_cfg, dict) else {}
    alerts_cfg = cfg.get("alerts") if isinstance(cfg.get("alerts"), dict) else {}
    raw_feeds = alerts_cfg.get("feeds")
    feeds: list[dict[str, Any]]
    if isinstance(raw_feeds, list) and raw_feeds:
        feeds = [f for f in raw_feeds if isinstance(f, dict)]
    else:
        feeds = [{"type": "nws", "enabled": True}]

    clients: list[AlertClient] = []
    for feed in feeds:
        if feed.get("enabled") is False:
            continue
        kind = str(feed.get("type") or feed.get("kind") or "nws").strip().lower()
        if kind in ("nws", "weather"):
            clients.append(NwsAlertClient())
        elif kind in ("flashalert", "flash", "closings"):
            url = feed.get("url")
            path = feed.get("path") or feed.get("file")
            clients.append(
                FlashAlertClient(
                    url=str(url) if url else None,
                    path=str(path) if path else None,
                )
            )
        elif kind in ("rss", "atom"):
            url = str(feed.get("url") or "").strip()
            if not url:
                LOG.warning("Alert feed type=%s missing url; skipped", kind)
                continue
            category = str(feed.get("category") or "other").strip().lower()
            source = str(feed.get("source") or kind).strip() or kind
            clients.append(
                RssAtomAlertClient(url, category=category, source=source)
            )
        elif kind in ("cap", "cap_atom", "cap_index"):
            url = str(feed.get("url") or "").strip()
            if not url:
                LOG.warning("Alert feed type=cap missing url; skipped")
                continue
            try:
                max_items = int(feed.get("max_items") or 12)
            except (TypeError, ValueError):
                max_items = 12
            clients.append(CapIndexAlertClient(url, max_items=max_items))
        else:
            LOG.warning("Unknown alert feed type %r; skipped", kind)

    if not clients:
        clients = [NwsAlertClient()]
    return QueuedAlertClient(clients)
