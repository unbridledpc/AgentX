from __future__ import annotations

import random
import re
import time
from typing import Any
from xml.etree import ElementTree as ET

from agentx.tools.base import Tool, ToolArgument, ToolExecutionError


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(int(v), hi))


def _title_from_words(words: list[str]) -> str:
    cleaned: list[str] = []
    for w in words:
        w2 = re.sub(r"[^a-zA-Z0-9]+", "", w)
        if not w2:
            continue
        cleaned.append(w2[:1].upper() + w2[1:].lower())
    return " ".join(cleaned) or "Monster"


def _derive_ranges(*, examples: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    hp: list[int] = []
    exp: list[int] = []
    armor: list[int] = []
    speed: list[int] = []
    for ex in examples:
        if not isinstance(ex, dict):
            continue
        stats = ex.get("stats") if isinstance(ex.get("stats"), dict) else {}
        if isinstance(stats, dict):
            if isinstance(stats.get("health_max"), int):
                hp.append(int(stats["health_max"]))
            if isinstance(stats.get("experience"), int):
                exp.append(int(stats["experience"]))
            if isinstance(stats.get("armor"), int):
                armor.append(int(stats["armor"]))
            if isinstance(stats.get("speed"), int):
                speed.append(int(stats["speed"]))

    def rng(vals: list[int], fallback: tuple[int, int]) -> tuple[int, int]:
        if not vals:
            return fallback
        lo = min(vals)
        hi = max(vals)
        # Expand slightly to allow novelty but stay close to observed data.
        pad = max(1, int((hi - lo) * 0.15))
        return max(1, lo - pad), max(lo + 1, hi + pad)

    return {
        "health_max": rng(hp, (200, 1500)),
        "experience": rng(exp, (50, 1200)),
        "armor": rng(armor, (5, 35)),
        "speed": rng(speed, (160, 320)),
    }


def _difficulty_scale(difficulty: str) -> float:
    d = (difficulty or "").strip().lower()
    if d in {"low", "easy", "beginner"}:
        return 0.75
    if d in {"high", "hard", "elite"}:
        return 1.25
    return 1.0


class MonsterGenerateTool(Tool):
    name = "monster.generate"
    description = "Generate a new Tibia monster XML using local memory examples (optional) for guidance"
    args = (
        ToolArgument("base_race", str, "Base race (e.g. undead, humanoid)", required=True),
        ToolArgument("difficulty", str, "Difficulty: low|mid|high (default mid)", required=False, default="mid"),
        ToolArgument("style", str, "Style: melee|ranged|magic (default melee)", required=False, default="melee"),
        ToolArgument("inspiration", list, "List of inspiration keywords", required=False, default=[]),
        ToolArgument("examples", list, "Optional parsed monsters for guidance (leave empty; Agent fills)", required=False, default=[]),
        ToolArgument("reason", str, "Reason for generation", required=False, default=""),
    )
    safety_flags: tuple[str, ...] = ()

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        base_race = (args.get("base_race") or "").strip()
        if not base_race:
            raise ToolExecutionError("base_race is required.")
        difficulty = (args.get("difficulty") or "mid").strip().lower()
        style = (args.get("style") or "melee").strip().lower()
        inspiration = args.get("inspiration") if isinstance(args.get("inspiration"), list) else []
        inspiration_s = [str(x) for x in inspiration if isinstance(x, (str, int, float, bool)) and str(x).strip()]
        examples = args.get("examples") if isinstance(args.get("examples"), list) else []

        ranges = _derive_ranges(examples=examples)
        scale = _difficulty_scale(difficulty)

        def pick(name: str, lo_floor: int, hi_cap: int) -> int:
            lo, hi = ranges.get(name, (lo_floor, hi_cap))
            v = random.randint(int(lo), int(hi))
            return _clamp(int(v * scale), lo_floor, hi_cap)

        hp = pick("health_max", 50, 50_000)
        exp = pick("experience", 0, 1_000_000)
        armor = pick("armor", 0, 200)
        speed = pick("speed", 50, 600)

        # Name: keep it deterministic-ish across runs for the same inspirations.
        words = inspiration_s[:3] or [base_race, style]
        base_name = _title_from_words(words + ["Spawn"])
        monster_name = base_name
        if len(monster_name) > 40:
            monster_name = monster_name[:40].rstrip()

        root = ET.Element("monster", {"name": monster_name, "race": base_race})
        ET.SubElement(root, "health", {"now": str(hp), "max": str(hp)})
        ET.SubElement(root, "experience", {"value": str(exp)})
        ET.SubElement(root, "speed", {"value": str(speed)})
        ET.SubElement(root, "armor", {"value": str(armor)})

        # Minimal combat scaffolding.
        attacks = ET.SubElement(root, "attacks")
        if style == "magic":
            ET.SubElement(attacks, "attack", {"name": "energy", "interval": "2000", "chance": "20", "min": "0", "max": str(max(10, hp // 40))})
        elif style == "ranged":
            ET.SubElement(attacks, "attack", {"name": "distance", "interval": "2000", "chance": "25", "min": "0", "max": str(max(8, hp // 60)), "range": "7"})
        else:
            ET.SubElement(attacks, "attack", {"name": "melee", "interval": "2000", "chance": "100", "min": "0", "max": str(max(5, hp // 80))})

        defenses = ET.SubElement(root, "defenses")
        ET.SubElement(defenses, "defense", {"armor": str(armor)})

        flags = ET.SubElement(root, "flags")
        ET.SubElement(flags, "summonable", {"value": "0"})
        ET.SubElement(flags, "attackable", {"value": "1"})
        ET.SubElement(flags, "hostile", {"value": "1"})

        xml = ET.tostring(root, encoding="unicode")
        return {
            "name": monster_name,
            "xml": xml,
            "explanation": {
                "base_race": base_race,
                "difficulty": difficulty,
                "style": style,
                "inspiration": inspiration_s,
                "derived_ranges": {k: {"min": v[0], "max": v[1]} for (k, v) in ranges.items()},
                "chosen": {"health_max": hp, "experience": exp, "armor": armor, "speed": speed},
            },
            "ts": time.time(),
        }

