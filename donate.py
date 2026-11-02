"""BO3 : que faire des pieces qu'on laisse partir ("Let go") ? Trouver les lieux de depot les plus proches.

Ce module ne sait PAS quelle organisation a le plus besoin des vetements : aucune donnee ouverte ne le dit. Il renvoie seulement
les lieux les plus proches qui acceptent ce type de depot, d'apres OpenStreetMap (donnees ouvertes, (c) contributeurs OpenStreetMap).

Vie privee : seuls une position (ou une adresse) et le type de cause sont envoyes aux services externes ; jamais les photos
ni la garde-robe.

    POST /api/donate/places  {"cause": "recycling|charity_shop|shelter", "lat": .., "lon": ..}   ou   {"cause": .., "address": "..."}
    GET  /api/donate/causes
"""
import math, os, time
from functools import lru_cache

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/donate", tags=["donate"])

# Les serveurs Overpass publics sont parfois satures : on les essaie l'un apres l'autre (le premier qui repond gagne).
OVERPASS_URLS = [u for u in (os.environ.get("OVERPASS_URL"),
                             "https://overpass-api.de/api/interpreter",
                             "https://overpass.kumi.systems/api/interpreter",
                             "https://overpass.private.coffee/api/interpreter",
                             "https://overpass.openstreetmap.fr/api/interpreter",
                             "https://overpass.osm.jp/api/interpreter") if u]
OVERPASS_TIMEOUT_S = 10
OVERPASS_ROUNDS = 2          # tours complets sur les serveurs, avec attente croissante (2 s) : les serveurs publics sont souvent satures
NOMINATIM_URL = os.environ.get("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
UA = {"User-Agent": "DressMe-capstone/1.0 (student project; open-data lookup)"}
RADII_KM = (5, 15)          # on cherche d'abord a 5 km, puis une seule fois a 15 km si rien
MAX_PLACES = 8

CAUSES = {
    "recycling": dict(
        label="Textile recycling containers", query='nwr["amenity"="recycling"]["recycling:clothes"="yes"]',
        hint="Bagged clothes, linen and shoes. Pieces are sorted for reuse or recycling, not given to a person directly."),
    "charity_shop": dict(
        label="Charity & second-hand shops", query='nwr["shop"="charity"]',
        hint="Pieces in good condition are resold or passed on. Ask what they accept before you go."),
    "shelter": dict(
        label="Shelters & social centres", query='nwr["amenity"="social_facility"]["social_facility"~"^(shelter|outreach)$"]',
        hint="Many do not take clothes at all. Call first."),
}
NOTE = ("Nearest places that accept this kind of drop-off, according to OpenStreetMap contributors. "
        "We cannot tell which organisation needs your pieces most. Check what they accept and their opening hours before you go.")


class Where(BaseModel):
    cause: str
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    address: str | None = Field(default=None, max_length=200)


def _haversine_m(a, b, c, d):
    p = math.pi / 180
    h = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


@lru_cache(maxsize=128)
def _geocode(address: str):
    """Adresse -> (lat, lon, libelle) via Nominatim ; None si introuvable."""
    r = requests.get(NOMINATIM_URL, params={"q": address, "format": "json", "limit": 1}, headers=UA, timeout=10)
    r.raise_for_status()
    j = r.json()
    return (float(j[0]["lat"]), float(j[0]["lon"]), j[0].get("display_name", address)) if j else None


@lru_cache(maxsize=256)
def _overpass(query: str):
    last = None
    for rnd in range(OVERPASS_ROUNDS):
        if rnd:
            time.sleep(2 * rnd)                                   # attente croissante entre deux tours
        for url in OVERPASS_URLS:
            try:
                r = requests.post(url, data={"data": query}, headers=UA, timeout=OVERPASS_TIMEOUT_S)
                r.raise_for_status()
                return r.json().get("elements", [])
            except (requests.RequestException, ValueError) as e:  # timeout, 429/502/504, reponse non JSON : serveur suivant
                last = e
    raise requests.RequestException(f"all Overpass servers failed: {last}")


NOMINATIM_TERMS = {"recycling": "recycling", "charity_shop": "charity shop", "shelter": "shelter"}
NOTE_FALLBACK = (" The main map service was busy, so this comes from a simpler search that finds fewer places. "
                 "Try again later for a fuller list.")


def _keep_for_cause(cause, tags):
    """Memes criteres que les requetes Overpass, appliques aux resultats de la recherche de secours."""
    if cause == "recycling":
        return tags.get("amenity") == "recycling" and tags.get("recycling:clothes") == "yes"
    if cause == "charity_shop":
        return tags.get("shop") == "charity"
    return tags.get("amenity") == "social_facility" and tags.get("social_facility") in ("shelter", "outreach")


@lru_cache(maxsize=256)
def _nominatim_nearby(cause: str, lat: float, lon: float, radius_km: int):
    """Recherche de secours quand tous les serveurs Overpass sont satures : Nominatim, dans un rectangle autour du point.
    Moins de resultats et moins de filtres qu'Overpass ; renvoie des elements au meme format."""
    dlat = radius_km / 111.0; dlon = dlat / max(math.cos(math.radians(lat)), 0.05)
    r = requests.get(NOMINATIM_URL, params={"q": NOMINATIM_TERMS[cause], "format": "jsonv2", "limit": 40, "bounded": 1, "extratags": 1, "addressdetails": 1,
                                            "viewbox": f"{lon - dlon:.5f},{lat + dlat:.5f},{lon + dlon:.5f},{lat - dlat:.5f}"}, headers=UA, timeout=15)
    r.raise_for_status()
    out = []
    for it in r.json():
        tags = dict(it.get("extratags") or {})
        if it.get("category") and it.get("type"):
            tags.setdefault(it["category"], it["type"])
        ad = it.get("address") or {}
        for k, v in (("addr:housenumber", ad.get("house_number")), ("addr:street", ad.get("road")), ("addr:postcode", ad.get("postcode")),
                     ("addr:city", ad.get("city") or ad.get("town") or ad.get("village"))):
            if v: tags[k] = v
        if it.get("name"): tags["name"] = it["name"]
        if _keep_for_cause(cause, tags):
            out.append({"lat": float(it["lat"]), "lon": float(it["lon"]), "tags": tags})
    return out


def build_query(cause: str, lat: float, lon: float, radius_km: int) -> str:
    return f'[out:json][timeout:15];({CAUSES[cause]["query"]}(around:{radius_km * 1000},{lat:.5f},{lon:.5f}););out center 80;'


def _address(t):
    street = " ".join(x for x in (t.get("addr:housenumber"), t.get("addr:street")) if x)
    town = " ".join(x for x in (t.get("addr:postcode"), t.get("addr:city")) if x)
    return ", ".join(x for x in (street, town) if x) or None


def parse_places(elements, lat0, lon0, limit=MAX_PLACES):
    """Elements Overpass -> lieux tries par distance (sans doublons de position)."""
    out, seen = [], set()
    for el in elements:
        t = el.get("tags", {})
        la = el.get("lat", (el.get("center") or {}).get("lat")); lo = el.get("lon", (el.get("center") or {}).get("lon"))
        if la is None or lo is None or (round(la, 4), round(lo, 4)) in seen:
            continue
        seen.add((round(la, 4), round(lo, 4)))
        out.append(dict(
            name=t.get("name") or t.get("operator") or t.get("brand") or "Collection point",
            address=_address(t), distance_m=int(_haversine_m(lat0, lon0, la, lo)), lat=la, lon=lo,
            opening_hours=t.get("opening_hours"), website=t.get("website") or t.get("contact:website"), phone=t.get("phone") or t.get("contact:phone"),
            accepts_shoes=(t["recycling:shoes"] == "yes") if "recycling:shoes" in t else None,
            map_url=f"https://www.openstreetmap.org/?mlat={la:.6f}&mlon={lo:.6f}#map=18/{la:.6f}/{lo:.6f}"))
    out.sort(key=lambda p: p["distance_m"])
    return out[:limit]


@router.get("/causes")
def causes():
    return [dict(id=k, label=v["label"], hint=v["hint"]) for k, v in CAUSES.items()]


@router.post("/places")
def places(b: Where):
    if b.cause not in CAUSES:
        raise HTTPException(400, f"unknown cause: {b.cause}")
    label = None
    if b.lat is not None and b.lon is not None:
        lat, lon = b.lat, b.lon
    elif b.address and b.address.strip():
        try:
            g = _geocode(b.address.strip())
        except requests.RequestException:
            raise HTTPException(502, "Address lookup is unavailable right now.")
        if not g:
            raise HTTPException(404, "Address not found.")
        lat, lon, label = g
    else:
        raise HTTPException(400, "Give an address or a position.")
    source = "overpass"
    for km in RADII_KM:
        try:
            found = parse_places(_overpass(build_query(b.cause, lat, lon, km)), lat, lon)
        except requests.RequestException:                       # tous les serveurs Overpass sont satures : recherche de secours
            try:
                found = parse_places(_nominatim_nearby(b.cause, round(lat, 4), round(lon, 4), km), lat, lon)
                source = "nominatim"
            except requests.RequestException:
                raise HTTPException(502, "The open map service is unavailable right now. Try again in a moment.")
        if found:
            break
    c = CAUSES[b.cause]
    return dict(cause=b.cause, label=c["label"], hint=c["hint"], radius_km=km, places=found, location=dict(lat=lat, lon=lon, label=label),
                source=source, note=NOTE + (NOTE_FALLBACK if source == "nominatim" else ""), attribution="© OpenStreetMap contributors")
