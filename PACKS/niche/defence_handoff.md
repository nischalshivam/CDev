# Defence niche — handoff from the main CDev chat (2026-10-10)

Read this after CDEV_MASTER.md. It is everything already measured and built for defence, so the new chat does
not redo it.

## Reference channels (the owner's choice)
- https://www.youtube.com/@dominiondefencereview/videos  (Canada)
- https://www.youtube.com/@TasmanDefenceReview/videos    (Australia / New Zealand)
Same owner/editor (Matthew). Measured on 4 videos (`_defence_ref/stats.json`, contact sheets `_defence_ref/*_hook.jpg`
/ `*_body.jpg`):
- 8-13 min, ~10-11 cuts/min, median shot 2-3 s; long holds on official footage.
- Footage = official: DVIDS, Defence Australia, DND Canada, Saab, Mitsubishi Heavy, Babcock, Thales, Naval Group —
  credit shown top-right. Company promo graphics (HUD, radar networks) are borrowed, not their own.
- Their OWN graphics are few: navy DATE box + white one-line caption lower-left (the main device), white-textured
  spec-comparison cards (flags + ship/jet cutouts + specs), caps quote text over footage, a logo intro on a country
  silhouette at ~30 s, occasional question lines. Best-viewed video (126K) = a head-to-head spec comparison.
- Almost NO maps -> animated maps / routes / range rings are our upgrade.

## Editing templates that fit (Frontier pack, `D:/Imp Files/Frontier-Templates/Frontier-Editing-Templates/`)
- Style 11 Deep (military: two-tone maps, route chart, cutaway, sonar, classified readout)
- Style 1 Documentary (full map grammar: region, pin, route, several places, satellite dive)
- Style 12 News (range ring, country heat map), Style 17 Horizon (data charts)
Owner rule from the Hollywood side: no fixed template ROTATION; pick devices by line meaning.

## HyperFrames
Installed globally, v0.8.143 (+ skills updated). Renders ~1x-realtime on this PC (a 1:46 edit = ~4.5 min).
Registry blocks worth using: data-chart, chart-story, mk-specs-list, comparison-split, lt-stack-bars,
north-korea-locked-down (map zoom). Lint rules learnt: never tween letterSpacing; gsap.set full-frame scenes to
opacity 0 before their reveal.

## What is already built
- `_defence_ref/hf_map/` — 10 s HyperFrames map demo (Australia -> Japan route, pins, date box).
- `_wedgetail/` — 1:46 test sample (competitor's own voice, TEST ONLY — never upload):
  - `gather.py`: 15 official uploads -> 183 vision-catalogued assets in 4 min, collections
    `PROJECT:defence:wedgetail-sample` + `DOMAIN:defence` (source_id prefix `SRC_DFYT_`).
  - `build.py`: hand EDL -> HyperFrames composition (title lockup, date-box labels, split card, 2 maps with
    coverage rings, chapter list + chapter card, year card, size-comparison bars, requirement list) -> mix -> QC.
  - Output `_wedgetail/out/WEDGETAIL_SAMPLE.mp4`. QC: all pass except dark_runs on the (deliberately dark) maps.

## Lessons (measured)
- Watermarks: `video.defence.gov.au` / AiirSource need a 1.16-1.22 crop (1.08 is not enough); spotter clips are
  letterboxed (1.32). Corner logos on company promos cannot be removed, only cropped.
- The same flight shot appears in several official uploads -> dedupe by picture, not by source.
- Talking heads dropped at catalog time is right for this niche.
- Facts on screen (dates, numbers, lengths) must come from the script's sources; defence viewers check.

## Open (to do in the defence chat)
1. Style pack `PACKS/style/defence.yaml` from the above.
2. Wire the HyperFrames devices (date box, maps, spec card, requirement list, size bars) as reusable code, driven
   by the EDL — not hand-built per video.
3. Add DVIDS as a source (free API, mostly public domain).
4. Own voice (TTS) -> exact word timings (the test used YouTube auto-subs, ±0.5 s).
