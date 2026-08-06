"""
demo_data.py
------------
Generates a realistic-looking (but synthetic) retention CSV + matching
transcript so you can demo Retention Autopsy live without needing a real
YouTube Studio export on hand.

Run directly to write sample_data/demo_retention.csv and
sample_data/demo_transcript.txt:

    python demo_data.py
"""

import csv
import math
import os
import random

OUT_DIR = os.path.join(os.path.dirname(__file__), "sample_data")


def generate_retention_curve(duration_sec: int = 600, n_points: int = 120, seed: int = 7):
    """
    Builds a synthetic retention curve (percent viewers remaining vs. video
    position) with a few deliberately injected drop zones so the tool has
    something interesting to diagnose in a demo.
    """
    random.seed(seed)
    points = []
    retention = 100.0
    # Baseline natural decay curve (typical YouTube shape: fast early drop,
    # long tail, small end-screen bump)
    for i in range(n_points):
        pct = (i / (n_points - 1)) * 100
        sec = (pct / 100) * duration_sec

        # baseline gentle decay
        baseline_decay = 0.35 if pct < 20 else 0.12

        # injected drop zones (start_pct, end_pct, extra_drop_per_step)
        injected_zones = [
            (3, 8, 1.1),    # weak hook right after intro
            (28, 34, 1.6),  # mid-roll tangent
            (55, 60, 1.3),  # repeated explanation
            (78, 82, 0.9),  # ad read / CTA fatigue
        ]
        extra = 0.0
        for lo, hi, rate in injected_zones:
            if lo <= pct <= hi:
                extra = rate

        noise = random.uniform(-0.15, 0.15)
        retention -= (baseline_decay + extra + noise)
        retention = max(retention, 8.0)  # floor so it doesn't go negative

        # small end-screen recovery bump for realism
        if pct > 96:
            retention += 0.05

        points.append((round(pct, 2), round(retention, 2)))

    return points, duration_sec


def generate_transcript(duration_sec: int = 600):
    """
    Produces a synthetic timestamped transcript (youtube-transcript-api style:
    "[seconds] text") with content deliberately written to line up with the
    injected drop zones above, so the diagnosis step has real signal to find.
    """
    beats = [
        (0, "Hey everyone, welcome back to the channel."),
        (5, "So today I want to talk about a topic that honestly took me way too long to figure out."),
        (12, "But before we get into it, let me just explain a bit about my background and why I even started this channel."),
        (20, "Okay so a little bit more context, I've been doing this for about three years now."),
        (30, "Anyway, let's actually get into the real content."),
        (45, "The first thing you need to understand is the core concept here."),
        (70, "This is actually pretty simple once you see it visually."),
        (100, "Now let me go on a bit of a tangent here about a related topic that's kind of interesting."),
        (130, "Okay so that tangent aside, back to the main point."),
        (150, "Let's move to the second key idea."),
        (200, "As I mentioned earlier, like I said before, this connects back to the first point."),
        (230, "To repeat what I covered a minute ago, the core idea is the same pattern."),
        (260, "Alright, moving on to the third section."),
        (300, "This next part is where it gets really practical."),
        (330, "Quick word from today's sponsor before we continue."),
        (360, "Okay, subscribe if you haven't already, now back to the video."),
        (400, "Let's wrap up the core technique with a real example."),
        (430, "Here's the example in action, step by step."),
        (470, "Now for the results and what this actually means for you."),
        (500, "Let's talk about some edge cases people run into."),
        (540, "Bringing it all together now."),
        (570, "Thanks so much for watching, hit subscribe for more like this."),
        (590, "See you in the next one."),
    ]
    return beats


def write_demo_files():
    os.makedirs(OUT_DIR, exist_ok=True)
    points, duration = generate_retention_curve()

    retention_path = os.path.join(OUT_DIR, "demo_retention.csv")
    with open(retention_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Video position (%)", "Audience retention (%)"])
        for pct, ret in points:
            writer.writerow([pct, ret])

    transcript_path = os.path.join(OUT_DIR, "demo_transcript.txt")
    with open(transcript_path, "w") as f:
        for sec, text in generate_transcript(duration):
            f.write(f"[{sec}] {text}\n")

    meta_path = os.path.join(OUT_DIR, "demo_meta.txt")
    with open(meta_path, "w") as f:
        f.write(f"duration_sec={duration}\n")

    print(f"Wrote {retention_path}")
    print(f"Wrote {transcript_path}")
    print(f"Wrote {meta_path}")


if __name__ == "__main__":
    write_demo_files()
