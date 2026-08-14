# 🔎 Retention Autopsy

**Diagnose *why* viewers drop off your YouTube videos — not just where.**

YouTube Studio shows you a retention graph with a dip at 2:14. It never tells you
*why* people left. Retention Autopsy correlates your retention curve with your
video's transcript and uses an LLM to diagnose each steep drop — weak hook, slow
intro, tangent, repetition, ad/CTA fatigue, confusing explanation — and gives you
a concrete edit suggestion for each one.

🎬 **Video demo:** [Watch on YouTube](https://www.youtube.com/watch?v=D2n8HJ3oXtY)


## What it does

1. **Parse** a YouTube Studio "Audience retention" CSV export
2. **Detect** steep drop-off zones on the curve automatically
3. **Align** each drop zone to the matching transcript segment (by timestamp)
4. **Diagnose** each drop with an LLM (Groq / Llama 3.3 70B), returning a
   category, a plain-English explanation citing the actual transcript text,
   and a suggested edit
5. **Visualize** everything in a Streamlit dashboard with the flagged zones
   highlighted directly on the retention curve

No YouTube API calls are made — it works entirely from files a creator already
has (retention CSV export + transcript), so there's nothing to authenticate
and nothing that can be rate-limited.

## Demo (no files needed)

```bash
pip install -r requirements.txt
python demo_data.py        # generates synthetic sample_data/ files
streamlit run app.py
```

Then click **"▶ Load demo data"** in the sidebar. This loads a synthetic but
realistic retention curve with 4 deliberately injected drop patterns (weak
hook, tangent, repetition, ad fatigue) and a matching transcript, so you can
see a full autopsy report immediately without needing a real export.

## Using it on a real video

1. In YouTube Studio: **Analytics → Engagement → Audience retention → Export → CSV**
2. Get your transcript — either:
   - Export from YouTube Studio (**Subtitles → Download → .srt**, then reformat
     lines as `[seconds] text`, one per line), or
   - Use `youtube-transcript-api` locally to pull it, or
   - Paste one you already have (auto-caption transcripts work fine)
3. Upload both files in the app, enter your video's duration, and optionally
   add a [Groq API key](https://console.groq.com/keys) (free tier available)
   for AI-powered diagnosis. Without a key, the app falls back to a
   rule-based heuristic diagnosis, so it still works offline.

## How it works (technical)

- `retention_core.py` — all core logic: CSV parsing, sliding-window drop
  detection, transcript timestamp alignment, and the LLM diagnosis call
  (Groq's OpenAI-compatible `/chat/completions` with `response_format:
  json_object` for strict structured output)
- `demo_data.py` — generates a synthetic retention curve + matching
  transcript with intentional drop patterns, for demoing without real data
- `app.py` — Streamlit UI: file uploaders, an interactive Plotly chart with
  drop zones highlighted, and a per-zone autopsy report

**Drop detection**: a sliding window scans the retention curve; any window
where retention falls by more than a configurable threshold (default 4
percentage points) is flagged as a drop zone. Adjacent flagged windows are
merged, and only the steepest N zones are surfaced so the report stays
readable rather than flagging every minor wobble.

**Offline fallback**: if no API key is provided (or the LLM call fails), a
rule-based heuristic still classifies each drop using simple lexical cues
(e.g. phrases like "as I mentioned" → repetition, "sponsor"/"subscribe" →
ad/CTA fatigue, drop in the first 15s → weak hook). This means the tool
never fully dead-ends and still produces a usable report offline.

## Tech stack

Python · Streamlit · Pandas · Plotly · Groq (Llama 3.3 70B) via REST API

## What's next

- Direct pull of retention CSV + captions via the official YouTube Data API
  (requires OAuth + creator's own channel access — currently manual export
  to stay clearly within API terms during the hackathon window)
- Auto-generate an EDL/cut list file for direct import into editing software
- Aggregate autopsy patterns across a creator's whole channel to catch
  recurring habits (e.g. "you lose viewers to tangents in 6 of your last 10 videos")

## Team

- _[Your name(s) here — add who built what: core pipeline, LLM prompting,
  Streamlit UI, demo data, etc.]_

## Problem / Solution / Tech (short write-up for submission)

**Problem:** Creators can see *where* viewers drop off in YouTube Analytics,
but never *why* — leaving them to guess at edits instead of fixing the actual
cause.

**Solution:** Retention Autopsy cross-references the retention curve against
the video's own transcript and uses an LLM to diagnose each steep drop with a
specific, evidence-based reason and a concrete edit suggestion.

**Tech:** Python, Streamlit, Pandas, Plotly for the app and visualization;
Groq (Llama 3.3 70B) for structured-JSON diagnosis generation; no YouTube API
dependency, so it works entirely from Studio exports a creator already has.
