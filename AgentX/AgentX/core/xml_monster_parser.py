from __future__ import annotations

import re
from typing import Any
from xml.etree import ElementTree as ET


class MonsterXmlParseError(ValueError):
    pass


def _as_int(value: str | None) -> int | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return int(float(s))
    except Exception:
        return None


def _norm_text(s: str | None) -> str:
    t = (s or "").strip()
    t = re.sub(r"\s+", " ", t)
    return t


def parse_monster_xml(xml: str) -> dict[str, Any]:
    """Parse a Forgotten Server-style monster XML into a structured dict.

    This is best-effort and intended for *offline* analysis and generation guidance.
    It does not execute anything and only uses stdlib ElementTree.
    """

    raw = (xml or "").strip()
    if not raw:
        raise MonsterXmlParseError("Empty XML.")

    try:
        root = ET.fromstring(raw)
    except Exception as e:
        raise MonsterXmlParseError(f"XML parse failed: {e}") from e

    if root.tag.lower() != "monster":
        raise MonsterXmlParseError("Root element must be <monster>.")

    name = _norm_text(root.attrib.get("name"))
    race = _norm_text(root.attrib.get("race") or root.attrib.get("raceid"))

    def find_one(tag: str) -> ET.Element | None:
        for el in root.iter():
            if el.tag.lower() == tag.lower():
                return el
        return None

    health_el = find_one("health")
    experience_el = find_one("experience")
    armor_el = find_one("armor")
    speed_el = find_one("speed")

    hp_now = _as_int(health_el.attrib.get("now") if health_el is not None else None)
    hp_max = _as_int(health_el.attrib.get("max") if health_el is not None else None)
    experience = _as_int(experience_el.attrib.get("value") if experience_el is not None else (experience_el.text if experience_el is not None else None))
    armor = _as_int(armor_el.attrib.get("value") if armor_el is not None else (armor_el.text if armor_el is not None else None))
    speed = _as_int(speed_el.attrib.get("value") if speed_el is not None else (speed_el.text if speed_el is not None else None))

    flags: list[str] = []
    flags_el = find_one("flags")
    if flags_el is not None:
        for f in list(flags_el):
            if not isinstance(f.tag, str):
                continue
            flags.append(f.tag)

    immunities: list[str] = []
    immunities_el = find_one("immunities")
    if immunities_el is not None:
        for imm in list(immunities_el):
            name_attr = _norm_text(imm.attrib.get("name"))
            if name_attr:
                immunities.append(name_attr)
            elif isinstance(imm.tag, str):
                immunities.append(imm.tag)

    attacks: list[dict[str, Any]] = []
    attacks_el = find_one("attacks")
    if attacks_el is not None:
        for atk in list(attacks_el):
            if not isinstance(atk.tag, str):
                continue
            attacks.append(
                {
                    "tag": atk.tag,
                    "name": _norm_text(atk.attrib.get("name")) or None,
                    "interval": _as_int(atk.attrib.get("interval")),
                    "chance": _as_int(atk.attrib.get("chance")),
                    "min": _as_int(atk.attrib.get("min")),
                    "max": _as_int(atk.attrib.get("max")),
                    "type": _norm_text(atk.attrib.get("type")) or None,
                    "range": _as_int(atk.attrib.get("range")),
                }
            )

    defenses: list[dict[str, Any]] = []
    defenses_el = find_one("defenses")
    if defenses_el is not None:
        for d in list(defenses_el):
            if not isinstance(d.tag, str):
                continue
            defenses.append({"tag": d.tag, "name": _norm_text(d.attrib.get("name")) or None, "chance": _as_int(d.attrib.get("chance"))})

    loot: list[dict[str, Any]] = []
    loot_el = find_one("loot")
    if loot_el is not None:
        for it in list(loot_el):
            if not isinstance(it.tag, str):
                continue
            if it.tag.lower() != "item":
                continue
            loot.append(
                {
                    "id": _norm_text(it.attrib.get("id")) or None,
                    "name": _norm_text(it.attrib.get("name")) or None,
                    "chance": _as_int(it.attrib.get("chance")),
                    "countmax": _as_int(it.attrib.get("countmax")),
                }
            )

    return {
        "name": name or None,
        "race": race or None,
        "stats": {
            "health_now": hp_now,
            "health_max": hp_max,
            "experience": experience,
            "armor": armor,
            "speed": speed,
            "flags": flags,
        },
        "combat": {
            "attacks": attacks,
            "defenses": defenses,
            "immunities": immunities,
        },
        "loot": loot,
        "raw_xml": raw,
    }

