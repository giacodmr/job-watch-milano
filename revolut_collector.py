"""Revolut official Next.js public careers board collector.

Revolut server-renders the complete public positions array in __NEXT_DATA__.
Certification requires full count parity, valid stable IDs/location metadata,
per-target official position detail ID verification, and a stable second board
snapshot. No paid APIs, browser protection bypass or source-status overrides.
"""
from __future__ import annotations
from html.parser import HTMLParser
import re
import time
import uuid
from urllib.parse import urlparse

import collector as c


BOARD = "https://www.revolut.com/careers/"
ID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z",re.I)
H1_COUNT = re.compile(r"\bWe\s+have\s+([\d,]+)\s+open\s+positions\b",re.I)


class _NextData(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.in_json = False
        self.json_fragments = []
        self.matches = 0

    def handle_starttag(self,tag,attrs):
        if tag.lower()=="script" and dict(attrs).get("id")=="__NEXT_DATA__":
            self.in_json=True
            self.matches+=1

    def handle_data(self,data):
        if self.in_json:
            self.json_fragments.append(data)

    def handle_endtag(self,tag):
        if tag.lower()=="script":
            self.in_json=False


def _next_data(body):
    import json
    p=_NextData()
    p.feed(body)
    if p.matches != 1 or not p.json_fragments:
        raise c.NotCheckable("Revolut public page lacks one intact __NEXT_DATA__ payload")
    try:
        root=json.loads("".join(p.json_fragments))
    except (TypeError, ValueError) as exc:
        raise c.NotCheckable("Revolut public page contains invalid Next.js JSON") from exc
    if not isinstance(root,dict) or not isinstance(root.get("props"),dict):
        raise c.NotCheckable("Revolut public Next.js state is not a JSON object")
    props=root["props"].get("pageProps")
    if not isinstance(props,dict):
        raise c.NotCheckable("Revolut public Next.js state has no pageProps")
    return props


def _uuid(value):
    value=str(value or "").lower()
    if not ID_PATTERN.fullmatch(value):
        raise c.NotCheckable("Revolut requisition has invalid stable UUID")
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise c.NotCheckable("Revolut requisition has invalid UUID") from exc


def _locations(raw):
    locations=raw.get("locations")
    if not isinstance(locations,list) or not locations:
        raise c.NotCheckable("Revolut requisition is missing its location array")
    normalized=[]
    for item in locations:
        if not isinstance(item,dict):
            raise c.NotCheckable("Revolut requisition contains an invalid location")
        place=c.clean_text(item.get("name"))
        country=c.clean_text(item.get("country"))
        kind=c.clean_text(item.get("type"))
        if not place or kind not in ("remote","office"):
            raise c.NotCheckable("Revolut requisition has incomplete official location metadata")
        text=f"{place}, {country}" if country and country.casefold() not in place.casefold() else place
        if text not in normalized:
            normalized.append(text)
    return " | ".join(normalized)


def _board_snapshot():
    try:
        body,final_url=c.get_html(BOARD)
    except Exception as exc:
        raise c.NotCheckable(f"Revolut official board not accessible: {type(exc).__name__}") from exc
    if urlparse(final_url).hostname not in {"www.revolut.com","revolut.com"}:
        raise c.NotCheckable("Revolut official board redirected outside approved domain")
    props=_next_data(body)
    positions=props.get("positions")
    widget=(props.get("widgetData") or {}).get("careers-teams-widget") or {}
    header=H1_COUNT.search(c.html_to_text(body) or "")
    if not header or not isinstance(positions,list) or not isinstance(widget,dict):
        raise c.NotCheckable("Revolut inventory lacks separate UI count and positions array")
    try:
        count=int(header.group(1).replace(",",""))
        widget_total=int(widget.get("total"))
    except (TypeError,ValueError) as exc:
        raise c.NotCheckable("Revolut embedded board total is not numeric") from exc
    if count != widget_total or count != len(positions):
        raise c.NotCheckable(f"Revolut inventory mismatch: heading={count}, widget={widget_total}, rows={len(positions)}")
    observed={}
    for raw in positions:
        if not isinstance(raw,dict):
            raise c.NotCheckable("Revolut embedded board contains malformed posting")
        sid=_uuid(raw.get("id"))
        title=c.clean_text(raw.get("text"))
        if not title or sid in observed:
            raise c.NotCheckable("Revolut board has missing title or duplicate requisition UUID")
        location=_locations(raw)
        observed[sid]={"title":title,"location":location,"team":c.clean_text(raw.get("team"))}
    return observed,count


def _validate_detail(sid,title):
    url=f"https://www.revolut.com/careers/position/{sid}/"
    try:
        body,final_url=c.get_html(url)
    except Exception as exc:
        raise c.NotCheckable(f"Revolut official detail unavailable for {sid}: {type(exc).__name__}") from exc
    if urlparse(final_url).hostname not in {"www.revolut.com","revolut.com"}:
        raise c.NotCheckable(f"Revolut official detail redirected off-domain for {sid}")
    item=_next_data(body).get("position")
    if not isinstance(item,dict) or _uuid(item.get("id")) != sid:
        raise c.NotCheckable(f"Revolut detail did not confirm requisition ID {sid}")
    if c.clean_text(item.get("text")) != title:
        raise c.NotCheckable(f"Revolut detail title changed for {sid}")
    return url


def collect_revolut(company):
    if company.get("company")!="Revolut":
        raise c.NotCheckable("Wrong owner for Revolut-specific adapter")
    first,total=_board_snapshot()
    jobs=[]
    for sid,raw in first.items():
        if not c.location_matches(raw["location"],company["company"]):
            continue
        official=_validate_detail(sid,raw["title"])
        jobs.append(c.compact_job(
            "Revolut",sid,title=raw["title"],location=raw["location"],
            department=raw["team"],canonical=official,apply_url=official,
        ))
        # Respect low request cadence; request retries use shared collector session.
        time.sleep(0.12)
    later,later_total=_board_snapshot()
    if total!=later_total or set(first)!=set(later):
        raise c.NotCheckable(
            f"Revolut board changed during collection: initial={total}, latest={later_total}, "
            f"id_overlap={len(set(first)&set(later))}"
        )
    return {
        "coverage":"VERIFIED",
        "collector":"revolut_first_party_next_data_id_parity_v1",
        "inventory_count":total,
        "source_url":BOARD,
        "jobs":jobs,
        "reconciliation":{
            "heading_count":total,
            "next_data_count":len(first),
            "validated_target_job_count":len(jobs),
            "stable_snapshot":True,
        },
    }
