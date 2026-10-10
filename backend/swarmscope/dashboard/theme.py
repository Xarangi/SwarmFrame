"""The look of the dashboard: one theme for the whole app, chosen by people or by the designer agent.

A theme is a small, checked description, never CSS. It names a preset and changes a few things on top of it: light
or dark, the accent colour, the three typefaces (from a fixed list), density, corner radius, how panels are drawn,
the background, the navigation rail, the size of headlines, motion, and, if wanted, individual colours.

Every change goes through `ThemeStore.apply`, which resolves the theme for both light and dark and checks it: text
must stay readable on its background (WCAG contrast ratios), the accent must stand out, and the colours that carry
meaning (finding levels, evidence status, the categorical palette for charts) are not editable at all, so a finding
reads the same whatever the look. A change that fails a check is refused with the reason, so an agent can fix it
and try again. Every applied change is versioned and can be undone.
"""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from swarmscope.ingest.packs import ROOT

THEME_PATH = ROOT / "data" / "theme.json"
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

# ------------------------------------------------------------------ typefaces (Google Fonts), by role
FONTS: dict[str, dict[str, str]] = {
    # serif display faces
    "Newsreader": {"kind": "serif", "css": "Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;1,6..72,400"},
    "Fraunces": {"kind": "serif", "css": "Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;1,9..144,400"},
    "Source Serif 4": {"kind": "serif", "css": "Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400"},
    "Instrument Serif": {"kind": "serif", "css": "Instrument+Serif:ital@0;1"},
    "Spectral": {"kind": "serif", "css": "Spectral:ital,wght@0,400;0,500;1,400"},
    # sans faces (UI, and display for plainer looks)
    "Instrument Sans": {"kind": "sans", "css": "Instrument+Sans:wght@400;500;600"},
    "Inter": {"kind": "sans", "css": "Inter:wght@400;500;600"},
    "Manrope": {"kind": "sans", "css": "Manrope:wght@400;500;600;700"},
    "Source Sans 3": {"kind": "sans", "css": "Source+Sans+3:wght@400;500;600"},
    "IBM Plex Sans": {"kind": "sans", "css": "IBM+Plex+Sans:wght@400;500;600"},
    "Work Sans": {"kind": "sans", "css": "Work+Sans:wght@400;500;600"},
    "Space Grotesk": {"kind": "sans", "css": "Space+Grotesk:wght@400;500;600"},
    "DM Sans": {"kind": "sans", "css": "DM+Sans:wght@400;500;600"},
    "Atkinson Hyperlegible": {"kind": "sans", "css": "Atkinson+Hyperlegible:ital,wght@0,400;0,700;1,400"},
    # mono faces (labels, numbers, data)
    "IBM Plex Mono": {"kind": "mono", "css": "IBM+Plex+Mono:wght@400;500"},
    "JetBrains Mono": {"kind": "mono", "css": "JetBrains+Mono:wght@400;500"},
    "Source Code Pro": {"kind": "mono", "css": "Source+Code+Pro:wght@400;500"},
    "DM Mono": {"kind": "mono", "css": "DM+Mono:wght@400;500"},
    "Space Mono": {"kind": "mono", "css": "Space+Mono:wght@400;700"},
}
FALLBACK = {"serif": '"Iowan Old Style", Georgia, serif', "sans": 'system-ui, -apple-system, "Segoe UI", sans-serif',
            "mono": 'ui-monospace, "SFMono-Regular", Menlo, monospace'}
ROLE_KINDS = {"display": ("serif", "sans"), "ui": ("sans",), "mono": ("mono",)}

# ------------------------------------------------------------------ colours people and agents may set
TOKENS = {
    "bg": "the page background", "surface": "panels and cards", "raised": "inputs, menus and raised cards",
    "sunken": "wells, tracks and hover", "ink": "main text", "ink2": "secondary text", "ink3": "muted text and labels",
    "ink4": "faint marks and disabled", "line": "borders", "line2": "dividers inside panels",
    "accent": "the one signal colour: actions, the current page, what needs a decision",
    "data": "plain bars and single-series charts",
}
# fixed on purpose: what a colour means must not change with the look
FIXED = ["finding levels (act, look, watch)", "evidence status (observed, derived, self-reported, inferred, "
         "contradicted)", "the categorical palette used to tell series apart in charts"]

ENUMS: dict[str, dict[str, str]] = {
    "mode": {"system": "follow the computer's setting", "light": "always light", "dark": "always dark"},
    "density": {"compact": "more on screen, smaller type", "comfortable": "the default",
                "roomy": "larger type and more space"},
    "surface": {"plate": "hairline panels with small registration marks in two corners (an instrument look)",
                "card": "soft cards with a light shadow", "flat": "flat panels with a border, no shadow",
                "outline": "outlined panels on the page colour, no fill"},
    "canvas": {"dots": "a faint dot grid behind the panels", "grid": "a faint line grid", "plain": "a plain background"},
    "nav": {"dark": "a dark navigation rail in both modes", "light": "the rail matches the page"},
    "nav_style": {"full": "icons and names", "icons": "icons only, names on hover"},
    "headline": {"small": "modest headings", "medium": "the default", "large": "big editorial headings"},
    "motion": {"full": "the live swarm field and transitions", "reduced": "transitions only",
               "none": "no animation at all"},
    "labels": {"mono": "small mono capitals for labels (an instrument feel)", "sans": "plain sentence-case labels"},
}


class ThemeSpec(BaseModel):
    preset: str = "observatory"
    mode: Literal["system", "light", "dark"] | None = None   # None = the preset's (system, or dark for Console)
    accent: str | None = None                       # a hex, or a name in NAMED_ACCENTS (tuned per mode); None = the preset's
    fonts: dict[str, str] = Field(default_factory=dict)   # display / ui / mono -> a name in FONTS
    density: Literal["compact", "comfortable", "roomy"] | None = None
    radius: int | None = None                       # 0..18 px; None = the preset's
    surface: Literal["plate", "card", "flat", "outline"] | None = None
    canvas: Literal["dots", "grid", "plain"] | None = None
    nav: Literal["dark", "light"] | None = None
    nav_style: Literal["full", "icons"] = "full"
    headline: Literal["small", "medium", "large"] = "medium"
    motion: Literal["full", "reduced", "none"] = "full"
    labels: Literal["mono", "sans"] | None = None
    colors: dict[str, dict[str, str]] = Field(default_factory=dict)  # {"light": {token: hex}, "dark": {...}}
    version: int = 0
    by: str = "default"
    rationale: str = ""
    updated: str | None = None


# ------------------------------------------------------------------ presets
_OBS_RAIL = {"rail": "#121519", "rail2": "#1c2026", "rail3": "#262b32", "rail_line": "#252a30",
             "rail_ink": "#ece9e2", "rail_ink2": "#a2a8b0", "rail_ink3": "#7c838c"}
PRESETS: dict[str, dict[str, Any]] = {
    "observatory": {
        "title": "Observatory", "blurb": "Warm paper, graphite ink, one vermilion signal and a graphite rail. "
                                         "Serif headlines, mono labels. The default.",
        "fonts": {"display": "Newsreader", "ui": "Instrument Sans", "mono": "IBM Plex Mono"},
        "density": "comfortable", "radius": 10, "surface": "plate", "canvas": "dots", "nav": "dark", "labels": "mono",
        "light": {"bg": "#f1eee7", "surface": "#fbfaf6", "raised": "#ffffff", "sunken": "#e9e5dc", "ink": "#14171b",
                  "ink2": "#3c424a", "ink3": "#646b75", "ink4": "#a6abb1", "line": "#d9d4c8", "line2": "#e6e2d8",
                  "accent": "#d4471c", "data": "#59636f"},
        "dark": {"bg": "#0e1114", "surface": "#151a1f", "raised": "#1b2127", "sunken": "#11151a", "ink": "#ebe8e2",
                 "ink2": "#b6bbc2", "ink3": "#8a929b", "ink4": "#4d555e", "line": "#262d34", "line2": "#1f252b",
                 "accent": "#f0643a", "data": "#8b95a1"},
        "rail_dark": _OBS_RAIL,
    },
    "paper": {
        "title": "Paper", "blurb": "An editorial page: cream paper, ink-blue accent, flat ruled panels and a light "
                                   "rail. Calm, for reading and reports.",
        "fonts": {"display": "Source Serif 4", "ui": "Source Sans 3", "mono": "Source Code Pro"},
        "density": "comfortable", "radius": 6, "surface": "flat", "canvas": "plain", "nav": "light", "labels": "sans",
        "light": {"bg": "#f6f3ec", "surface": "#fffdf8", "raised": "#ffffff", "sunken": "#efeae0", "ink": "#1d1a16",
                  "ink2": "#48423a", "ink3": "#6b6358", "ink4": "#b0a797", "line": "#e0d8c9", "line2": "#ece6da",
                  "accent": "#1f5fa8", "data": "#6b6358"},
        "dark": {"bg": "#16140f", "surface": "#1d1a15", "raised": "#24211b", "sunken": "#12100c", "ink": "#eee8dc",
                 "ink2": "#c4bcad", "ink3": "#9a917f", "ink4": "#5a5246", "line": "#332e26", "line2": "#29251f",
                 "accent": "#7fadea", "data": "#a89f8e"},
        "rail_dark": {"rail": "#1d1a16", "rail2": "#2a2620", "rail3": "#37322a", "rail_line": "#2f2a23",
                      "rail_ink": "#f1ebdf", "rail_ink2": "#c4bcad", "rail_ink3": "#948b7b"},
    },
    "console": {
        "title": "Console", "blurb": "An operations console: near-black, a green signal, outlined panels on a line "
                                     "grid, tight spacing and a technical sans. Dark by default.",
        "fonts": {"display": "Space Grotesk", "ui": "IBM Plex Sans", "mono": "JetBrains Mono"},
        "density": "compact", "radius": 4, "surface": "outline", "canvas": "grid", "nav": "dark", "mode": "dark",
        "labels": "mono",
        "light": {"bg": "#eef1ef", "surface": "#f8faf9", "raised": "#ffffff", "sunken": "#e3e8e5", "ink": "#0d1411",
                  "ink2": "#33403a", "ink3": "#56635c", "ink4": "#9aa6a0", "line": "#cbd4cf", "line2": "#dde4e0",
                  "accent": "#0c7a5b", "data": "#4f5e57"},
        "dark": {"bg": "#0a0d0c", "surface": "#0f1412", "raised": "#151b18", "sunken": "#070a09", "ink": "#dbe7e1",
                 "ink2": "#a9bbb2", "ink3": "#7d9087", "ink4": "#3d4a44", "line": "#1f2a25", "line2": "#18211d",
                 "accent": "#3ddc97", "data": "#7f958b"},
        "rail_dark": {"rail": "#070a09", "rail2": "#111714", "rail3": "#1c2420", "rail_line": "#16201b",
                      "rail_ink": "#dbe7e1", "rail_ink2": "#a2b4ab", "rail_ink3": "#73867d"},
    },
    "clinic": {
        "title": "Clinic", "blurb": "Clean and neutral: white cards with soft shadows, a blue accent, a light rail "
                                    "and a plain modern sans throughout.",
        "fonts": {"display": "Manrope", "ui": "Inter", "mono": "JetBrains Mono"},
        "density": "comfortable", "radius": 12, "surface": "card", "canvas": "plain", "nav": "light", "labels": "sans",
        "light": {"bg": "#f4f5f8", "surface": "#ffffff", "raised": "#ffffff", "sunken": "#eef0f4", "ink": "#111827",
                  "ink2": "#374151", "ink3": "#5f6775", "ink4": "#9ca3af", "line": "#e2e5ea", "line2": "#eef0f3",
                  "accent": "#2563eb", "data": "#5f6775"},
        "dark": {"bg": "#0b0f17", "surface": "#111827", "raised": "#172033", "sunken": "#0d121c", "ink": "#f3f4f6",
                 "ink2": "#d1d5db", "ink3": "#9ca3af", "ink4": "#4b5563", "line": "#1f2937", "line2": "#182131",
                 "accent": "#60a5fa", "data": "#9ca3af"},
        "rail_dark": {"rail": "#0f172a", "rail2": "#1e293b", "rail3": "#334155", "rail_line": "#1e293b",
                      "rail_ink": "#f1f5f9", "rail_ink2": "#cbd5e1", "rail_ink3": "#94a3b8"},
    },
    "signal": {
        "title": "Signal", "blurb": "High contrast for bright rooms and tired eyes: black on white (or white on "
                                    "black), strong outlines and a very legible typeface.",
        "fonts": {"display": "Atkinson Hyperlegible", "ui": "Atkinson Hyperlegible", "mono": "IBM Plex Mono"},
        "density": "roomy", "radius": 6, "surface": "outline", "canvas": "plain", "nav": "dark", "labels": "sans",
        "light": {"bg": "#ffffff", "surface": "#ffffff", "raised": "#ffffff", "sunken": "#efefef", "ink": "#000000",
                  "ink2": "#1c1c1c", "ink3": "#3d3d3d", "ink4": "#767676", "line": "#7a7a7a", "line2": "#c4c4c4",
                  "accent": "#0033cc", "data": "#333333"},
        "dark": {"bg": "#000000", "surface": "#0a0a0a", "raised": "#141414", "sunken": "#000000", "ink": "#ffffff",
                 "ink2": "#f0f0f0", "ink3": "#cfcfcf", "ink4": "#8a8a8a", "line": "#7a7a7a", "line2": "#3a3a3a",
                 "accent": "#ffd400", "data": "#d0d0d0"},
        "rail_dark": {"rail": "#000000", "rail2": "#1a1a1a", "rail3": "#333333", "rail_line": "#333333",
                      "rail_ink": "#ffffff", "rail_ink2": "#e0e0e0", "rail_ink3": "#b0b0b0"},
    },
}

# named accents a person (or the free designer) can ask for, tuned for each mode
NAMED_ACCENTS: dict[str, tuple[str, str]] = {
    "vermilion": ("#d4471c", "#f0643a"), "orange": ("#c2550b", "#f08a3a"), "red": ("#c0262d", "#f2605f"),
    "crimson": ("#b3123f", "#f0577f"), "pink": ("#c03a7a", "#ee7ab0"), "magenta": ("#a7298f", "#e273cf"),
    "purple": ("#7c3aed", "#b294f7"), "violet": ("#6d3fd1", "#a98cf0"), "indigo": ("#4338ca", "#8f8cf5"),
    "blue": ("#2563eb", "#60a5fa"), "ink": ("#1f5fa8", "#7fadea"), "sky": ("#0b72b5", "#56b4ec"),
    "cyan": ("#08788c", "#3fc6dc"), "teal": ("#0d7f74", "#36c2b2"), "green": ("#1a7f37", "#4cc46d"),
    "emerald": ("#0c7a5b", "#3ddc97"), "olive": ("#5f6b12", "#b6c84a"), "amber": ("#9a6700", "#e7b53c"),
    "gold": ("#8c6a00", "#e2bd3a"), "yellow": ("#8a6d00", "#ffd400"), "brown": ("#8a4b20", "#d39363"),
    "graphite": ("#3c424a", "#c3c8ce"), "black": ("#111111", "#f2f2f2"),
}

DENSITY = {"compact": {"fs": 13, "space": 0.82}, "comfortable": {"fs": 14, "space": 1.0},
           "roomy": {"fs": 15.5, "space": 1.16}}
HEADLINE = {"small": 0.8, "medium": 1.0, "large": 1.18}

# readable-text rules, checked in both modes
RULES = [("ink", "surface", 7.0, "main text on panels"), ("ink", "bg", 7.0, "main text on the page"),
         ("ink2", "surface", 4.5, "secondary text on panels"), ("ink3", "surface", 4.0, "muted text and labels on "
                                                                                      "panels"),
         ("ink3", "bg", 3.6, "muted text on the page"), ("accent", "surface", 3.0, "the accent against panels"),
         ("accent_ink", "surface", 4.5, "accent-coloured text on panels"),
         ("rail_ink", "rail", 7.0, "names in the navigation rail"), ("rail_ink2", "rail", 4.5, "the rail's "
                                                                                              "secondary text")]


class ThemeError(ValueError):
    pass


# ------------------------------------------------------------------ colour helpers
def _rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in rgb)


def _lum(h: str) -> float:
    def ch(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return round((la + 0.05) / (lb + 0.05), 2)


def mix(a: str, b: str, t: float) -> str:
    """t of a, 1-t of b."""
    ra, rb = _rgb(a), _rgb(b)
    return _hex(tuple(x * t + y * (1 - t) for x, y in zip(ra, rb)))  # type: ignore[arg-type]


def _readable(accent: str, surface: str, toward: str, need: float = 4.6) -> str:
    """The accent, moved toward `toward` until it reads as text on `surface`."""
    if contrast(accent, surface) >= need:
        return accent
    for i in range(1, 21):
        c = mix(toward, accent, i / 20)
        if contrast(c, surface) >= need:
            return c
    return toward


# ------------------------------------------------------------------ resolve
def resolve(spec: ThemeSpec) -> dict[str, Any]:
    """The theme made concrete for both modes: CSS custom properties per mode, fonts, and structural choices."""
    if spec.preset not in PRESETS:
        raise ThemeError(f"unknown preset {spec.preset!r}; presets: {', '.join(PRESETS)}")
    p = PRESETS[spec.preset]
    fonts = {**p["fonts"], **{k: v for k, v in spec.fonts.items() if v}}
    nav = spec.nav or p["nav"]
    out: dict[str, Any] = {}
    for mode in ("light", "dark"):
        t = dict(p[mode])
        light = mode == "light"
        if spec.accent in NAMED_ACCENTS:
            t["accent"] = NAMED_ACCENTS[spec.accent][0 if light else 1]
        elif spec.accent:
            # one hex for both modes: in dark mode it is lifted until it stands out on the dark panels
            t["accent"] = spec.accent if light else _readable(spec.accent, t["surface"], "#ffffff", 3.4)
        t.update(spec.colors.get(mode) or {})
        t["accent_ink"] = _readable(t["accent"], t["surface"], "#000000" if light else "#ffffff")
        t["accent_soft"] = mix(t["accent"], t["surface"], 0.13 if light else 0.2)
        t["tick"] = mix(t["ink"], t["bg"], 0.24 if light else 0.2)
        r = _rgb(t["ink"])
        t["grid_dot"] = f"rgba({round(r[0] * 255)}, {round(r[1] * 255)}, {round(r[2] * 255)}, {0.08 if light else 0.065})"
        if nav == "dark":
            t.update(p["rail_dark"])
        else:
            t.update({"rail": t["surface"], "rail2": t["sunken"], "rail3": t["line"], "rail_line": t["line"],
                      "rail_ink": t["ink"], "rail_ink2": t["ink2"], "rail_ink3": t["ink3"]})
        t["rail_accent"] = _readable(t["accent"], t["rail"], "#000000" if _lum(t["rail"]) > 0.4 else "#ffffff", 3.2)
        out[mode] = t
    d = DENSITY[spec.density or p["density"]]
    radius = p["radius"] if spec.radius is None else spec.radius
    families = []
    for role in ("display", "ui", "mono"):
        f = FONTS[fonts[role]]["css"]
        if f not in families:
            families.append(f)
    return {
        "modes": out, "mode": spec.mode or p.get("mode", "system"),
        "fonts": {role: f'"{fonts[role]}", {FALLBACK[FONTS[fonts[role]]["kind"]]}' for role in ("display", "ui", "mono")},
        "font_names": fonts, "font_url": "https://fonts.googleapis.com/css2?" + "&".join(f"family={f}" for f in families)
                                        + "&display=swap",
        "vars": {"radius": f"{radius}px", "radius_sm": f"{max(2, round(radius * 0.7))}px", "fs": f"{d['fs']}px",
                 "space": str(d["space"]), "headline": str(HEADLINE[spec.headline])},
        "attrs": {"surface": spec.surface or p["surface"], "canvas": spec.canvas or p["canvas"], "nav": nav,
                  "nav_style": spec.nav_style, "motion": spec.motion, "headline": spec.headline,
                  "labels": spec.labels or p["labels"],
                  "display_kind": FONTS[fonts["display"]]["kind"]},
    }


def check(spec: ThemeSpec) -> list[str]:
    """Readability problems with a theme, in plain words (empty when it passes)."""
    problems = []
    res = resolve(spec)
    for mode, t in res["modes"].items():
        for fg, bg, need, what in RULES:
            r = contrast(t[fg], t[bg])
            if r < need:
                problems.append(f"{mode} mode: {what} ({fg} {t[fg]} on {bg} {t[bg]}) has contrast {r}:1; it needs "
                                f"{need}:1")
    return problems


def _validate_changes(ch: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in ch.items():
        if k == "preset":
            if v not in PRESETS:
                raise ThemeError(f"preset is one of {', '.join(PRESETS)}")
            out[k] = v
        elif k == "accent":
            if v in (None, "", "default"):
                out[k] = None
            elif isinstance(v, str) and v.lower() in NAMED_ACCENTS:
                out[k] = v.lower()
            elif isinstance(v, str) and HEX.match(v):
                out[k] = v.lower()
            else:
                raise ThemeError(f"accent is a hex colour like #2563eb, or one of {', '.join(NAMED_ACCENTS)}")
        elif k == "fonts":
            if not isinstance(v, dict):
                raise ThemeError("fonts is {display, ui, mono}")
            f = {}
            for role, name in v.items():
                if role not in ROLE_KINDS:
                    raise ThemeError(f"font roles are display, ui and mono, not {role!r}")
                if name in (None, "", "default"):
                    f[role] = ""
                    continue
                if name not in FONTS:
                    raise ThemeError(f"{name!r} is not an available typeface; choose from {', '.join(FONTS)}")
                if FONTS[name]["kind"] not in ROLE_KINDS[role]:
                    allowed = [n for n, x in FONTS.items() if x["kind"] in ROLE_KINDS[role]]
                    raise ThemeError(f"{name} is a {FONTS[name]['kind']} face; the {role} face must be one of "
                                     f"{', '.join(allowed)}")
                f[role] = name
            out[k] = f
        elif k == "radius":
            if v is None:
                out[k] = None
            else:
                r = int(v)
                if not 0 <= r <= 18:
                    raise ThemeError("radius is 0 to 18 (pixels)")
                out[k] = r
        elif k == "colors":
            if not isinstance(v, dict):
                raise ThemeError('colors is {"light": {token: "#rrggbb"}, "dark": {...}}')
            c: dict[str, dict[str, str]] = {}
            for mode, toks in v.items():
                if mode not in ("light", "dark") or not isinstance(toks, dict):
                    raise ThemeError("colors has a light and/or a dark map of token -> hex")
                for tok, hx in toks.items():
                    if tok not in TOKENS:
                        raise ThemeError(f"{tok!r} cannot be set; settable colours: {', '.join(TOKENS)}. "
                                         f"Fixed on purpose: {'; '.join(FIXED)}")
                    if not (isinstance(hx, str) and HEX.match(hx)):
                        raise ThemeError(f"{mode}.{tok} must be a hex colour like #1a2b3c")
                c.setdefault(mode, {}).update({t: h.lower() for t, h in toks.items()})
            out[k] = c
        elif k in ENUMS:
            if v is None and k in ("density", "surface", "canvas", "nav", "mode", "labels"):
                out[k] = None
            elif v not in ENUMS[k]:
                raise ThemeError(f"{k} is one of {', '.join(ENUMS[k])}")
            else:
                out[k] = v
        elif k == "reset":
            continue
        else:
            raise ThemeError(f"unknown theme setting {k!r}; settings: preset, accent, fonts, radius, colors, "
                             f"{', '.join(ENUMS)}")
    return out


def options() -> dict[str, Any]:
    """Everything a designer may choose from, with what each choice means. This is the whole design space."""
    return {
        "presets": {k: {"title": p["title"], "blurb": p["blurb"], "fonts": p["fonts"], "accent": p["light"]["accent"],
                        "surface": p["surface"], "canvas": p["canvas"], "nav": p["nav"], "density": p["density"],
                        "labels": p["labels"], "mode": p.get("mode", "system"),
                        "radius": p["radius"], "swatches": {m: [p[m]["bg"], p[m]["surface"], p[m]["ink"], p[m]["accent"]]
                                                            for m in ("light", "dark")}}
                    for k, p in PRESETS.items()},
        "settings": {**{k: v for k, v in ENUMS.items()},
                     "accent": "a hex colour, or a name: " + ", ".join(NAMED_ACCENTS),
                     "radius": "corner radius in pixels, 0 to 18",
                     "fonts": {role: [n for n, f in FONTS.items() if f["kind"] in kinds]
                               for role, kinds in ROLE_KINDS.items()},
                     "colors": {"tokens": TOKENS, "per_mode": True}},
        "named_accents": {k: {"light": v[0], "dark": v[1]} for k, v in NAMED_ACCENTS.items()},
        "fixed": FIXED,
        "rules": [f"{what}: at least {need}:1" for _, _, need, what in RULES],
        "how": "Change only what was asked. Start from a preset when the request is a whole new look; otherwise adjust "
               "settings on top of the current one. Colours are checked in light and dark; a change that fails is "
               "refused with the reason, so adjust and try again. Layout (pages, panels, the Brief) is changed with "
               "dashboard_edit, not here.",
    }


class ThemeStore:
    """The app's one theme, with its history (undo), on disk at data/theme.json. path=False keeps it in memory."""

    def __init__(self, path: Path | None | bool = None):
        self.path = None if path is False else (path or THEME_PATH)
        self.spec = ThemeSpec()
        self.history: list[dict[str, Any]] = []
        if self.path is not None and self.path.exists():
            try:
                d = json.loads(self.path.read_text(encoding="utf-8"))
                self.spec = ThemeSpec(**d.get("spec", {}))
                self.history = d.get("history", [])[-40:]
            except Exception:
                self.spec, self.history = ThemeSpec(), []

    def save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"spec": self.spec.model_dump(), "history": self.history[-40:]}, indent=1),
                                 encoding="utf-8")
        except OSError:
            pass

    def preview(self, changes: dict[str, Any]) -> ThemeSpec:
        ch = _validate_changes(changes or {})
        base = ThemeSpec(preset=ch.get("preset", self.spec.preset)) if changes.get("reset") else copy.deepcopy(self.spec)
        if "preset" in ch and ch["preset"] != self.spec.preset and not changes.get("keep"):
            # a new preset is a new look: drop the old one's per-setting changes, keep mode and accessibility choices
            base = ThemeSpec(preset=ch["preset"], mode=self.spec.mode, motion=self.spec.motion,
                             nav_style=self.spec.nav_style, version=self.spec.version)
        for k, v in ch.items():
            if k == "fonts":
                base.fonts = {**base.fonts, **v}
                base.fonts = {r: n for r, n in base.fonts.items() if n}
            elif k == "colors":
                merged = copy.deepcopy(base.colors)
                for mode, toks in v.items():
                    merged.setdefault(mode, {}).update(toks)
                base.colors = merged
            else:
                setattr(base, k, v)
        return base

    def apply(self, changes: dict[str, Any], by: str = "human", rationale: str = "") -> dict[str, Any]:
        new = self.preview(changes)
        problems = check(new)
        if problems:
            raise ThemeError("not applied, some text would be hard to read: " + "; ".join(problems[:4]))
        self.history.append(self.spec.model_dump())
        new.version = self.spec.version + 1
        new.by, new.rationale = by, (rationale or describe(changes))[:400]
        new.updated = datetime.utcnow().isoformat(timespec="seconds")
        self.spec = new
        self.save()
        return self.state()

    def undo(self) -> dict[str, Any]:
        if not self.history:
            raise ThemeError("nothing to undo")
        prev = ThemeSpec(**self.history.pop())
        prev.version = self.spec.version + 1
        self.spec = prev
        self.save()
        return self.state()

    def state(self) -> dict[str, Any]:
        return {"spec": self.spec.model_dump(), "resolved": resolve(self.spec),
                "history": [{"version": h.get("version", 0), "by": h.get("by", ""), "rationale": h.get("rationale", "")}
                            for h in self.history[-12:]]}


def describe(changes: dict[str, Any]) -> str:
    parts = []
    for k, v in changes.items():
        if k == "fonts" and isinstance(v, dict):
            parts += [f"{r} face {n or 'default'}" for r, n in v.items()]
        elif k == "colors" and isinstance(v, dict):
            parts += [f"{m} {', '.join(t)}" for m, t in v.items()]
        elif k not in ("reset", "keep"):
            parts.append(f"{k} {v}")
    return "set " + "; ".join(parts) if parts else "no change"


# ------------------------------------------------------------------ the free designer: plain requests, no model
_COLOR_WORDS = "|".join(sorted(NAMED_ACCENTS, key=len, reverse=True))


def interpret(text: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Read a plain request ("dark, compact, with a teal accent and no animation") into theme changes and Brief ops.
    Returns (theme changes, dashboard ops, what was understood). Words it does not know are left alone."""
    t = " " + text.lower().replace("-", " ") + " "
    ch: dict[str, Any] = {}
    ops: list[dict[str, Any]] = []
    said: list[str] = []
    has = lambda *ws: any(re.search(rf"\b{w}\b", t) for w in ws)  # noqa: E731
    rail_dark = has("dark sidebar", "dark rail", "dark nav", "dark navigation")
    rail_light = has("light sidebar", "light rail", "light nav", "light navigation", "white sidebar")
    t_mode = re.sub(r"\b(dark|light|white) (sidebar|rail|nav|navigation)\b", " ", t)
    has_m = lambda *ws: any(re.search(rf"\b{w}\b", t_mode) for w in ws)  # noqa: E731
    for key, words in {"observatory": ["observatory", "default look", "original look"],
                       "paper": ["paper", "editorial", "newspaper", "print"],
                       "console": ["console", "terminal", "hacker", "ops", "operations"],
                       "clinic": ["clinic", "clean", "minimal", "neutral", "saas", "corporate", "modern"],
                       "signal": ["signal", "high contrast", "accessible", "accessibility", "legible"]}.items():
        if has(*words):
            ch["preset"] = key
            said.append(f"the {PRESETS[key]['title']} look")
            break
    if has_m("dark mode", "dark theme", "dark", "night"):
        ch["mode"] = "dark"; said.append("dark")
    elif has_m("light mode", "light theme", "light", "bright"):
        ch["mode"] = "light"; said.append("light")
    elif has_m("system", "automatic", "follow my computer"):
        ch["mode"] = "system"; said.append("follow the system")
    m = re.search(rf"\b({_COLOR_WORDS})\b(?:\s+(?:accent|highlight|colou?r))?", t)
    hx = re.search(r"#[0-9a-f]{6}\b", t)
    if hx:
        ch["accent"] = hx.group(0); said.append(f"accent {hx.group(0)}")
    elif m and (has("accent", "highlight", "colou?r", "color", "colour") or m.group(1) not in ("black", "ink")):
        name = m.group(1)
        ch["accent"] = name; said.append(f"a {name} accent")
    if has("compact", "dense", "denser", "tighter", "smaller", "more on screen"):
        ch["density"] = "compact"; said.append("compact")
    elif has("roomy", "spacious", "airy", "bigger", "larger text", "larger type", "more space"):
        ch["density"] = "roomy"; said.append("roomy")
    if has("square", "sharp", "no rounded", "boxy"):
        ch["radius"] = 2; said.append("square corners")
    elif has("rounder", "rounded", "round", "soft corners", "pill"):
        ch["radius"] = 14; said.append("rounder corners")
    for key, words in {"flat": ["flat"], "outline": ["outline", "outlined", "wireframe"],
                       "card": ["cards", "shadow", "shadows", "elevated"], "plate": ["plates", "registration marks",
                                                                                      "instrument"]}.items():
        if has(*words):
            ch["surface"] = key; said.append(f"{key} panels")
            break
    if has("no dots", "plain background", "plain canvas", "no grid", "remove the dots"):
        ch["canvas"] = "plain"; said.append("a plain background")
    elif has("grid background", "line grid", "graph paper"):
        ch["canvas"] = "grid"; said.append("a grid background")
    elif has("dot grid", "dots"):
        ch["canvas"] = "dots"; said.append("a dot grid")
    if rail_light:
        ch["nav"] = "light"; said.append("a light rail")
    elif rail_dark:
        ch["nav"] = "dark"; said.append("a dark rail")
    if has("icons only", "icon only", "collapse the sidebar", "collapsed sidebar", "narrow sidebar", "slim sidebar"):
        ch["nav_style"] = "icons"; said.append("an icon-only rail")
    elif has("full sidebar", "show the names", "expand the sidebar"):
        ch["nav_style"] = "full"; said.append("a full rail")
    if has("no animation", "no motion", "stop the animation", "static", "still"):
        ch["motion"] = "none"; said.append("no animation")
    elif has("less animation", "reduce motion", "reduced motion", "calmer", "calm"):
        ch["motion"] = "reduced"; said.append("less motion")
    if has("mono labels", "monospace labels", "instrument labels"):
        ch["labels"] = "mono"; said.append("mono labels")
    elif has("plain labels", "sentence case", "no mono labels", "no capitals", "no all caps"):
        ch["labels"] = "sans"; said.append("plain labels")
    if has("big headlines", "large headlines", "bigger headings", "larger headings"):
        ch["headline"] = "large"; said.append("larger headlines")
    elif has("small headlines", "smaller headings", "smaller headlines", "modest headings"):
        ch["headline"] = "small"; said.append("smaller headlines")
    fonts: dict[str, str] = {}
    for name in FONTS:
        if re.search(rf"\b{re.escape(name.lower())}\b", t):
            kind = FONTS[name]["kind"]
            role = "mono" if kind == "mono" else ("display" if kind == "serif" or has("heading", "headline", "title")
                                                  else "ui")
            fonts[role] = name
            said.append(f"{name} for {'headings' if role == 'display' else 'labels and numbers' if role == 'mono' else 'text'}")
    if has("sans headings", "sans serif headings", "no serif", "sans serif titles"):
        fonts.setdefault("display", "Instrument Sans" if not fonts.get("ui") else fonts["ui"]); said.append("sans headings")
    elif has("serif headings", "serif titles"):
        fonts.setdefault("display", "Newsreader"); said.append("serif headings")
    if fonts:
        ch["fonts"] = fonts
    # the Brief's sections
    if has("hide the world", "remove the world", "no world", "without the world"):
        ops.append({"op": "set_brief", "world": False}); said.append("the World off the Brief")
    elif has("show the world", "add the world"):
        ops.append({"op": "set_brief", "world": True}); said.append("the World on the Brief")
    if has("hide what.s going on", "remove what.s going on", "hide the overview", "no overview"):
        ops.append({"op": "set_brief", "overview": False}); said.append("“What's going on” hidden")
    elif has("show what.s going on", "show the overview"):
        ops.append({"op": "set_brief", "overview": True}); said.append("“What's going on” shown")
    if has("hide what changed", "remove what changed", "no changes list"):
        ops.append({"op": "set_brief", "show_changes": False}); said.append("“What changed” hidden")
    n = re.search(r"\b(?:show|list|only)\s+(\d{1,2})\s+findings?\b", t)
    if n:
        ops.append({"op": "set_brief", "attention_rows": min(12, int(n.group(1)))}); said.append(f"{n.group(1)} findings")
    if has("only act", "only what needs a decision", "only urgent"):
        ops.append({"op": "set_brief", "min_severity": "ACT"}); said.append("only findings that need a decision")
    if has("show the machinery", "show machinery"):
        ops.append({"op": "set_machinery", "on": True}); said.append("the machinery page")
    return ch, ops, said


_STORE: ThemeStore | None = None


def store() -> ThemeStore:
    """The app's theme (persisted under data/theme.json). Tests swap in ThemeStore(False)."""
    global _STORE
    if _STORE is None:
        _STORE = ThemeStore()
    return _STORE
