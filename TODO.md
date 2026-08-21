# CDev — TODO

## Phase 1: Foundation (Current)

- [x] Project structure created
- [x] Data models (ClipEntry, Beat, Job, Segment)
- [x] Library database (JSON-based)
- [x] Queue manager (JSON-based batch processing)
- [x] CLI (argument parsing, status, library stats)
- [x] Universal Clue Script prompt
- [x] Defence niche pack (template)
- [x] Style packs (clean_doc, cinematic)
- [x] Sample script for testing
- [x] Core processing pipeline (process_job)
- [x] Asset retrieval with hard identity gates
- [x] Timeline builder
- [x] Basic FFmpeg renderer
- [x] PROCESS.md (system manual)
- [x] CHANGELOG.md (decision log)
- [x] README.md

## Phase 2: Asset Pipeline (Next)

- [ ] yt-dlp scraper integration (SourceHunter)
- [ ] FFmpeg scene-change detection + clip extraction
- [ ] Wikimedia Commons image harvester
- [ ] Gemini Flash AI cataloger (video + image)
- [ ] Metadata-first filtering (before AI scan)
- [ ] Hard gate implementation (entity/action/context/quality)
- [ ] Full FFmpeg filter_complex renderer
  - [ ] Multi-track video compositing
  - [ ] Image with Ken Burns effect
  - [ ] Animated map transitions
  - [ ] Text card rendering
  - [ ] Smooth dissolves/fades
- [ ] Audio mixing (narration + music + SFX)
- [ ] Color grading (LUTs + filters)
- [ ] Proxy render → QC → full render workflow
- [ ] Render queue (background processing)
- [ ] Quality metrics per output

## Phase 3: Polish (Planned)

- [ ] Map system (animated globe → zoom → pin drop)
- [ ] Diagram/graphic generator (for technical content)
- [ ] Typewriter text animation
- [ ] Multi-camera angle switching
- [ ] Thumbnail generator
- [ ] Feedback loop (like/dislike affects scoring)
- [ ] JSON → SQLite migration (when library > 5000)
- [ ] Web UI for queue management
- [ ] Playlist generation (YouTube/TikTok export)

## Phase 4: Production (Planned)

- [ ] First real video end-to-end
- [ ] Library growth testing (50 videos)
- [ ] Cost tracking and optimization
- [ ] Performance benchmarking
- [ ] Error recovery (resume failed jobs)
- [ ] Multi-language support
- [ ] Template system for common video structures

## Nice to Have

- [ ] Electron GUI
- [ ] Integration with DaVinci Resolve (XML export)
- [ ] AI thumbnail selection
- [ ] Auto-chapter generation
- [ ] Subtitle generation (SRT)
- [ ] Multi-resolution output (1080p, 720p, vertical)
- [ ] Direct YouTube/TikTok upload
- [ ] View analytics integration
- [ ] A/B testing (different B-roll for same script)

---

## Blocked / Needs Decision

| ID | Topic | Blocked By |
|----|-------|------------|
| F001 | Map system | Choose approach |
| F002 | Render complexity | Performance testing |
| F003 | Thumbnail | Design decision |
| F004 | Music source | Budget/legal |
| F005 | Audio cleanup | Tool selection |
| F006 | Multi-camera | Library requirements |
