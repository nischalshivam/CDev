# MIGRATION — moving to a new PC

> Verified on the current machine: Claude Code sessions are **local files**, not cloud. The whole
> `.claude` folder is ~58 MB, so moving it is trivial. But the system itself does NOT depend on chat
> history — repo + SSD is all you actually need.

---

## The 5-minute version (works even with zero chat history)

```
1. git clone https://github.com/nischalshivam/CDev     # branch: foundation
2. Plug in the SSD that holds the library
3. Set the library root (one value):
      setx CDEV_LIBRARY_ROOT "E:/CDevData/library"     # or config/library.toml
4. Recreate keys.env  (it is gitignored on purpose — never committed)
5. Install deps:  pip install -U yt-dlp faster-whisper pillow numpy instaloader
                  pip install "praw>=7.7,<8" bdfr
6. Open a chat, paste the block from NEW_CHANNEL_KIT.md
```

Everything the system needs is in the repo: `FOUNDATION.md` (design + decisions), `CHANNELS.md`
(what exists and its status), `NEW_CHANNEL_KIT.md` (how to start), `library_index.jsonl` (what the
library holds), `DOWNLOADERS.md` (source tools), and all the code.

---

## Optional: carry the chat history across

Chats are files under `C:\Users\<you>\.claude\` (~58 MB total):

| Folder / file | What it holds | Copy? |
|---|---|---|
| `projects\` | session transcripts, tool results, **memory** | yes |
| `sessions\` | session keys | yes |
| `settings.json` | env, workflows, notification prefs | yes |
| `settings.local.json` | tool permissions | yes |
| `backups\`, `shell-snapshots\`, `telemetry\` | scratch/diagnostics | optional |

```
robocopy "C:\Users\<old>\.claude" "\\newpc\C$\Users\<new>\.claude" /E
```

⚠️ **Session folders are keyed by working directory** (`C--Users-Dell`, `D--`, …). If the new PC has
a different username or you work from different paths, old sessions may not map into the sidebar.
Keeping the same username and folder layout avoids this entirely.

Login is tied to your Anthropic account — just sign in on the new machine.

---

## What must NOT be assumed to travel

| Thing | Why | Action |
|---|---|---|
| `keys.env` | gitignored (secrets) | recreate by hand |
| `library/objects/` (media) | hundreds of GB | lives on the SSD — plug it in |
| `catalog.sqlite` | binary, on the SSD | plug the SSD in; nothing to restore |
| Installed CLI tools | machine-local | reinstall (step 5 above) |

---

## Before you switch machines

```
python CODE/sync.py -m "pre-migration snapshot"
```

That exports the library index and pushes every tracked change, so the repo is current. Then also
take an ordinary backup copy of the SSD (media + `catalog.sqlite`) — the repo does not and cannot
hold those.
