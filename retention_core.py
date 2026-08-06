"""
retention_core.py
------------------
Core logic for Retention Autopsy:
1. Parse a YouTube Studio "Audience retention" CSV export (or synthetic equivalent)
2. Detect steep drop-off zones in the retention curve
3. Align those timestamps to transcript segments
4. Ask an LLM to diagnose *why* each drop likely happened, using only the
   transcript text around that moment (no video/audio needed)

Everything here is pure-Python / pandas — no YouTube API calls, so it works
fully offline except for the final LLM diagnosis step.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


# ---------------------------------------------------------------------------
# 1. Retention CSV parsing
# ---------------------------------------------------------------------------

def parse_retention_csv(file_or_path) -> pd.DataFrame:
    """
    Parses a YouTube Studio 'Audience retention' export.

    YouTube Studio exports typically have two columns:
        - "Video position" (as a percentage OR mm:ss, depending on export type)
        - "Audience retention (%)"

    We normalize to a DataFrame with columns: ['position_pct', 'retention_pct'].
    If the position column looks like timestamps, they're converted to percent
    using the max value present (best-effort; pass video_duration_sec for exact).
    """
    df = pd.read_csv(file_or_path)
    df.columns = [c.strip().lower() for c in df.columns]

    # Try to find the position + retention columns under common naming variants
    pos_col = next((c for c in df.columns if "position" in c or "time" in c), df.columns[0])
    ret_col = next((c for c in df.columns if "retention" in c or "audience" in c), df.columns[1])

    positions = df[pos_col]
    # Detect if positions are mm:ss timestamps rather than raw percentages
    if positions.dtype == object and positions.astype(str).str.contains(":").any():
        def to_seconds(v):
            parts = [int(p) for p in str(v).split(":")]
            while len(parts) < 3:
                parts.insert(0, 0)
            h, m, s = parts[-3:]
            return h * 3600 + m * 60 + s

        secs = positions.map(to_seconds)
        max_secs = secs.max() or 1
        position_pct = (secs / max_secs) * 100
    else:
        position_pct = pd.to_numeric(positions, errors="coerce")

    retention_pct = pd.to_numeric(df[ret_col], errors="coerce")

    out = pd.DataFrame({
        "position_pct": position_pct,
        "retention_pct": retention_pct,
    }).dropna().sort_values("position_pct").reset_index(drop=True)

    return out


def position_pct_to_seconds(position_pct: float, duration_sec: float) -> float:
    return (position_pct / 100.0) * duration_sec


# ---------------------------------------------------------------------------
# 2. Drop detection
# ---------------------------------------------------------------------------

@dataclass
class DropZone:
    start_pct: float
    end_pct: float
    start_sec: float
    end_sec: float
    retention_before: float
    retention_after: float
    drop_amount: float  # percentage points lost across the zone


def detect_drop_zones(
    retention_df: pd.DataFrame,
    duration_sec: float,
    min_drop_points: float = 4.0,
    window: int = 3,
    max_zones: int = 6,
) -> list[DropZone]:
    """
    Slides a small window across the retention curve and flags spots where
    retention falls by more than `min_drop_points` percentage points within
    `window` samples. Adjacent flagged points are merged into a single zone.
    Returns the `max_zones` steepest drops, ordered by position (earliest first).
    """
    df = retention_df.reset_index(drop=True)
    n = len(df)
    if n < window + 1:
        return []

    raw_zones: list[DropZone] = []
    i = 0
    while i < n - window:
        before = df.loc[i, "retention_pct"]
        after = df.loc[i + window, "retention_pct"]
        drop = before - after
        if drop >= min_drop_points:
            start_pct = df.loc[i, "position_pct"]
            end_pct = df.loc[i + window, "position_pct"]
            raw_zones.append(DropZone(
                start_pct=start_pct,
                end_pct=end_pct,
                start_sec=position_pct_to_seconds(start_pct, duration_sec),
                end_sec=position_pct_to_seconds(end_pct, duration_sec),
                retention_before=before,
                retention_after=after,
                drop_amount=drop,
            ))
            i += window  # skip ahead past this zone to avoid overlapping dupes
        else:
            i += 1

    # merge zones that are very close together (within 2% of video length)
    merged: list[DropZone] = []
    for z in raw_zones:
        if merged and (z.start_pct - merged[-1].end_pct) < 2.0:
            prev = merged[-1]
            merged[-1] = DropZone(
                start_pct=prev.start_pct,
                end_pct=z.end_pct,
                start_sec=prev.start_sec,
                end_sec=z.end_sec,
                retention_before=prev.retention_before,
                retention_after=z.retention_after,
                drop_amount=prev.retention_before - z.retention_after,
            )
        else:
            merged.append(z)

    merged.sort(key=lambda z: z.drop_amount, reverse=True)
    top = merged[:max_zones]
    top.sort(key=lambda z: z.start_pct)
    return top


# ---------------------------------------------------------------------------
# 3. Transcript alignment
# ---------------------------------------------------------------------------

@dataclass
class TranscriptSegment:
    start_sec: float
    text: str


def parse_transcript(raw_text: str) -> list[TranscriptSegment]:
    """
    Accepts transcript text in either of two common shapes and returns a
    flat list of (start_sec, text) segments:

    1. youtube-transcript-api style lines:  "[12.5] some text here"
    2. Plain SRT-ish / timestamped lines:   "00:01:23 some text here"

    If no timestamps are detected at all, the whole transcript is treated as
    a single segment starting at 0 (still works, just can't be aligned to
    specific drop zones as precisely).
    """
    segments: list[TranscriptSegment] = []
    ts_bracket = re.compile(r"^\[?(\d+(?:\.\d+)?)\]?\s+(.*)$")
    ts_clock = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?\s+(.*)$")

    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = ts_bracket.match(line)
        if m:
            segments.append(TranscriptSegment(start_sec=float(m.group(1)), text=m.group(2)))
            continue
        m = ts_clock.match(line)
        if m:
            h_or_m, m_or_s, maybe_s, text = m.groups()
            if maybe_s is not None:
                secs = int(h_or_m) * 3600 + int(m_or_s) * 60 + int(maybe_s)
            else:
                secs = int(h_or_m) * 60 + int(m_or_s)
            segments.append(TranscriptSegment(start_sec=float(secs), text=text))
            continue
        # no timestamp on this line — attach to previous segment if present
        if segments:
            segments[-1].text += " " + line
        else:
            segments.append(TranscriptSegment(start_sec=0.0, text=line))

    return segments


def segment_text_for_range(
    segments: list[TranscriptSegment], start_sec: float, end_sec: float, pad_sec: float = 8.0
) -> str:
    """Grabs transcript text covering [start_sec - pad, end_sec + pad]."""
    lo, hi = start_sec - pad_sec, end_sec + pad_sec
    picked = [s.text for s in segments if lo <= s.start_sec <= hi]
    if not picked:
        # fall back to nearest single segment
        nearest = min(segments, key=lambda s: abs(s.start_sec - start_sec), default=None)
        picked = [nearest.text] if nearest else []
    return " ".join(picked).strip()


# ---------------------------------------------------------------------------
# 4. LLM diagnosis
# ---------------------------------------------------------------------------

DIAGNOSIS_CATEGORIES = [
    "slow_intro",
    "tangent",
    "repetition",
    "weak_hook",
    "pacing_lull",
    "cta_ad_fatigue",
    "confusing_explanation",
    "other",
]

DIAGNOSIS_SYSTEM_PROMPT = """You are a YouTube retention analyst. You will be given a transcript \
segment from a video and the audience retention drop that happened during that segment \
(e.g. "lost 9.2 percentage points of viewers"). Diagnose the MOST LIKELY reason viewers left, \
choosing exactly one category from this list: slow_intro, tangent, repetition, weak_hook, \
pacing_lull, cta_ad_fatigue, confusing_explanation, other.

Respond with STRICT JSON only, no markdown fences, no preamble, in this exact shape:
{"category": "<one of the categories>", "explanation": "<1-2 plain-English sentences citing \
specific words/phrases from the transcript segment as evidence>", "suggested_fix": "<one \
concrete, actionable edit suggestion, e.g. 'Cut 0:32-1:04, this repeats the intro point'>"}
"""


def build_diagnosis_prompt(zone: DropZone, transcript_snippet: str) -> str:
    return (
        f"Video retention dropped from {zone.retention_before:.1f}% to "
        f"{zone.retention_after:.1f}% (a loss of {zone.drop_amount:.1f} points) "
        f"between {zone.start_sec:.0f}s and {zone.end_sec:.0f}s.\n\n"
        f"Transcript around this moment:\n\"\"\"\n{transcript_snippet}\n\"\"\"\n\n"
        f"Diagnose why viewers likely left here."
    )


def diagnose_with_groq(api_key: str, zone: DropZone, transcript_snippet: str, model: str = "llama-3.3-70b-versatile") -> dict:
    """Calls the Groq API (OpenAI-compatible) to diagnose one drop zone."""
    import requests

    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": DIAGNOSIS_SYSTEM_PROMPT},
                {"role": "user", "content": build_diagnosis_prompt(zone, transcript_snippet)},
            ],
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
        },
        timeout=30,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return json.loads(content)


def diagnose_zone(
    zone: DropZone,
    segments: list[TranscriptSegment],
    api_key: Optional[str] = None,
    use_llm: bool = True,
) -> dict:
    """
    Returns a diagnosis dict for one drop zone. Falls back to a rule-based
    heuristic if no API key is provided, so the tool still produces useful
    (if less nuanced) output offline.
    """
    snippet = segment_text_for_range(segments, zone.start_sec, zone.end_sec)

    if use_llm and api_key:
        try:
            result = diagnose_with_groq(api_key, zone, snippet)
            result["transcript_snippet"] = snippet
            return result
        except Exception as e:  # noqa: BLE001
            return _heuristic_diagnosis(zone, snippet, error=str(e))

    return _heuristic_diagnosis(zone, snippet)


def _heuristic_diagnosis(zone: DropZone, snippet: str, error: str | None = None) -> dict:
    """Simple offline fallback so the tool never fully dead-ends without an API key."""
    text_lower = snippet.lower()
    if zone.start_sec < 15:
        category, fix = "weak_hook", "Tighten the first 15 seconds — get to the payoff faster."
    elif any(w in text_lower for w in ["like i said", "as mentioned", "again,", "to repeat"]):
        category, fix = "repetition", f"Cut the repeated point around {zone.start_sec:.0f}s."
    elif any(w in text_lower for w in ["sponsor", "subscribe", "before we", "quick word"]):
        category, fix = "cta_ad_fatigue", f"Consider moving/trimming the CTA/ad read near {zone.start_sec:.0f}s."
    else:
        category, fix = "pacing_lull", f"Tighten or cut {zone.start_sec:.0f}s–{zone.end_sec:.0f}s; energy likely dips here."

    return {
        "category": category,
        "explanation": f"[Offline heuristic — no LLM key provided{': ' + error if error else ''}] "
                        f"Retention dropped {zone.drop_amount:.1f} pts in this segment.",
        "suggested_fix": fix,
        "transcript_snippet": snippet,
    }
