# CHANGELOG — Every Decision, Why, When

> This file records every significant decision made during CDev's development. Every entry has: DATE, WHAT changed, WHY, and IMPACT.

---

## 2026-08-22

### D001: Project Created

**WHAT:** Created CDev as a separate project from ProStudio (Lib). Moved documentary video automation into its own system.

**WHY:** ProStudio is for movies/TV (high input, no B-roll, analysis-first). CDev is for narration documentaries (high throughput, B-roll dependent, script-first). Different problems need different tools.

**IMPACT:** Two separate repos, separate systems, separate approaches.

---

### D002: B-roll-first Rejected

**WHAT:** Decided NOT to use "find B-roll first, write script around it."

**WHY:** This is how the 1000-channel trap works. Content availability drives script choices → scripts become generic → viewers become numb.

**IMPACT:** All scripts are written first. B-roll comes second. If B-roll doesn't match the narration, use still or text card (fail-closed).

---

### D003: Clue Script uses Search Keys, Not Timestamps

**WHAT:** Clue Script describes WHAT to show. The tool searches the library. No timestamps.

**WHY:** LLMs can't accurately find timestamps in 10-minute videos for 3-second narration beats. 4/5 guesses are wrong. Wrong clip = wrong variant = bad video.

**IMPACT:** Eliminates timestamp error class. Enables library matching and reuse.

---

### D004: Hard Identity Gates Before Ranking

**WHAT:** Library search uses entity/action/context as hard gates. Wrong entity = reject, no matter the relevance score.

**WHY:** Soft ranking allows wrong variants to win. Example: "Boxer APC" scored higher than "Boxer CRV" because more words matched. The ranking thought APC was closer to the query.

**IMPACT:** Zero wrong-variant errors. Slightly more clips needed for rare variants. Quality guarantee.

---

### D005: 3-Pack System (Niche + Format + Style)

**WHAT:** Every video controlled by 3 packs:
1. Niche Pack — what entities/actions are valid
2. Format Pack — video structure (built into Clue Script prompt)
3. Style Pack — color grade, typography, motion, audio

**WHY:** Separating concerns prevents config explosion. Adding a new style doesn't require changing niche definitions. Adding a new niche doesn't require changing rendering logic.

**IMPACT:** Easy to add cyberpunk style without touching defence pack. Easy to add animals niche without touching renderer.

---

### D006: JSON Library (Phase 1), SQLite at Phase 2

**WHAT:** Library is JSON files in Phase 1. Migrate to SQLite when entries exceed 5000.

**WHY:** JSON is simpler for Phase 1 development. SQLite provides better query performance at scale.

**IMPACT:** Simple code, fast iteration. Migration path documented.

---

### D007: Need-Driven Library Growth

**WHAT:** Don't scrape 100 random videos. Analyze 50 scripts, extract keywords, check library for gaps, scrape only what's missing.

**WHY:** Random scraping is expensive ($2-5 per video). Gap-based scraping is efficient ($0.50-2 per video). Library grows cumulatively — cost drops over time.

**IMPACT:** 70% cost reduction on initial library build. After 50 videos, marginal cost drops to $0.10-0.20/video.

---

### D008: Gemini Flash for Cataloging (Not Pro)

**WHAT:** Use Gemini Flash ($0.02/clip) instead of Pro ($0.05-0.10/clip) for cataloging.

**WHY:** Flash is good enough for descriptions. Pro is overkill and 2-5x more expensive.

**IMPACT:** 58% cost reduction on cataloging. No quality loss for this use case.

---

### D009: Fail-Closed Rendering

**WHAT:** If no library match, render still image or text card. Never force moving footage of the wrong thing.

**WHY:** Viewers notice wrong content immediately. Still + clear text is better than wrong B-roll. Quality over quantity.

**IMPACT:** Some videos have more text cards early on. Quality perception: HIGH. Builds trust with viewers.

---

### D010: Universal Clue Script Prompt

**WHAT:** Single prompt template works for ALL niches. Input template is filled per video.

**WHY:** Separate prompts per niche = maintenance nightmare. Universal prompt = add niche pack, prompt adapts automatically.

**IMPACT:** One prompt to maintain. Add new niche = add YAML pack, prompt works automatically.

---

### D011: Metadata-First Filtering Before AI Cataloging

**WHAT:** Step 1: Filter by YouTube metadata (free). Step 2: Quick visual check (30% sample). Step 3: AI catalog only remaining.

**WHY:** Scanning every clip with AI is expensive. Most clips are obvious from metadata alone (title, channel, duration).

**IMPACT:** 70% of clips skip AI scan. $0.70 savings per 100 clips.

---

### D012: Smart Scraper with Whitelisted Channels

**WHAT:** Scraper prefers trusted channels (Defence Australia, US Army, etc.) and filters by minimum quality (1080p, 10K views).

**WHY:** Random YouTube results are unreliable. Trusted channels produce consistent, high-quality content.

**IMPACT:** Better quality scraped content. Fewer rejections. Cleaner library.

---

### D013: Scene-Change Detection for Clip Extraction

**WHAT:** Use FFmpeg scene-change detection to cut videos into clips at natural scene boundaries.

**WHY:** Fixed-duration cutting (every 8 seconds) often splits scenes awkwardly. Scene detection produces cleaner clips.

**IMPACT:** Better quality clips. More usable clips per video (30% increase).

---

### D014: Auto-Check for New Content on New Scripts

**WHAT:** When processing new scripts, automatically check library for gaps and scrape if needed.

**WHY:** Manual gap analysis for every batch is tedious. Automated checking is frictionless.

**IMPACT:** System self-updates. More videos processed with less manual intervention.

---

### D015: Project Split from ProStudio

**WHAT:** CDev is completely separate from ProStudio (the movie/TV essay system). Different repos, different problems, different solutions.

**WHY:** ProStudio has totally different requirements: time-coded transcript, high-fidelity video analysis, cross-reference system. The architectures diverge significantly.

**IMPACT:** No shared code. Each system optimized for its use case. No confusion about which tool to use when.

---

## Decisions To Make

| # | Topic | Options | Status |
|---|-------|---------|--------|
| F001 | Map system | Google Maps API vs. pre-made vs. generated | Phase 2 |
| F002 | Render complexity | FFmpeg filter_complex vs. Blender | Phase 2 |
| F003 | Thumbnail | AI-generated vs. screenshot vs. custom | Phase 3 |
| F004 | Music source | Stock vs. AI-generated vs. licensed | Phase 3 |
| F005 | Audio cleanup | Manual vs. FFmpeg filters vs. AI denoise | Phase 2 |
| F006 | Multi-camera | Single vs. alternative angles | Phase 3 |
