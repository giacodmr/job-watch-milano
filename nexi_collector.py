"""Nexi Oracle CE: only role-specific, first-party external-JD city evidence.

Oracle's global requisition listing and detail resource sometimes expose
PrimaryLocation='Italy' without any structured work city. Never infer Milan
from a company headquarters/address. Allow positive location recovery only
when the *role description* explicitly says the role/position is based in
Milano/Milan or Roma/Rome, after matching the official per-ID detail response.
No complete-inventory certification comes from textual location evidence.
"""
from __future__ import annotations

import re
import requests
import collector as c

ROLE_CITY = re.compile(
    r"\b(?:in\s+this\s+role\s+based\s+in|"
    r"(?:this|the)\s+(?:role|position)\s+(?:is\s+)?based\s+in|"
    r"(?:role|position|work)\s+location\s*:|"
    r"sede\s+di\s+lavoro\s*:)\s*"
    r"(Milan|Milano|Rome|Roma)\b", re.I
)

def _published_detail(host:str, site:str, row:dict):
    sid=c.oracle_source_id(row)
    if not sid or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}",str(sid)):
        raise c.NotCheckable("Nexi candidate job lacks valid first-party ID")
    if host!="fa-ewwx-saasfaprod1.fa.ocs.oraclecloud.com" or site!="CX_1":
        raise c.NotCheckable("Nexi official Oracle host/site no longer matches documented board")
    url=f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
    headers={"Accept":"application/vnd.oracle.adf.resourcecollection+json, application/json",
             "Ora-Irc-Language":"en","REST-Framework-Version":"1"}
    try:
        response=c.get_session().get(
            url,params={"finder":f'ById;Id="{sid}",siteNumber={site}',
                        "onlyData":"true","expand":"secondaryLocations,otherWorkLocations"},
            headers=headers,timeout=c.TIMEOUT,
        )
        response.raise_for_status()
        payload=response.json()
    except (requests.RequestException,ValueError) as exc:
        raise c.NotCheckable(f"Nexi official Oracle details unavailable for requisition {sid}") from exc
    records=payload.get("items") if isinstance(payload,dict) else None
    if not isinstance(records,list) or len(records)!=1 or not isinstance(records[0],dict):
        raise c.NotCheckable(f"Nexi first-party Oracle detail missing/ambiguous for {sid}")
    detail=records[0]
    if str(detail.get("Id"))!=str(sid) or c.clean_text(detail.get("Title"))!=c.clean_text(row.get("Title")):
        raise c.NotCheckable(f"Nexi Oracle detail ID/title mismatch for {sid}")
    if str(detail.get("PrimaryLocationCountry") or "").casefold() not in {"it","italy","italia"}:
        raise c.NotCheckable(f"Nexi detail country mismatch for {sid}")
    return detail

def confirmed_target_city(row:dict, host:str, site:str)->str|None:
    """Return 'Milan'/'Rome' only from explicit role-location sentence, else None.

    Other city mentions such as 'headquartered in Milan' are not proof.
    """
    detail=_published_detail(host,site,row)
    # Prefer structured detail location if the role site later enables it.
    structured=c.oracle_location(detail)
    if structured and c.location_matches(structured,"Nexi"):
        return structured
    # This text is an externally published job description (never internal JDs).
    jd=c.html_to_text(detail.get("ExternalDescriptionStr")) or ""
    cities=set()
    for m in ROLE_CITY.finditer(jd):
        city=m.group(1).casefold()
        cities.add("Milan" if city.startswith("mil") else "Rome")
    if not cities:
        return None
    return " | ".join(sorted(cities))
