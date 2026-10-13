"""separate.py — cut a subject (aircraft, ship, person) out of a clip with SAM 2, on this PC's GPU.

From the Barty-Bart `object-separation` skill (tested 2026-10-13: an E-7A in a 3.3 s RAAF shot, 99 frames in
65 s = 0.66 s/frame on the RTX 5070, sam2.1-hiera-large, clean edges). SAM 2 needs torch+CUDA, which the CDev
venv (Python 3.14) does not carry, so the model runs in its own venv via sam2_worker.py:
    SAM2_PYTHON in keys.env (default D:/CDev/_skills_eval/.object-separation/Scripts/python.exe)
    deps there: torch + torchvision (cu128 wheels — the skill's list forgot torchvision), transformers,
    opencv-python-headless, pillow, numpy. Model ~900 MB in %USERPROFILE%/.cache/huggingface (first run only).
Heavy: GPU-bound, ~0.7 s/frame. Run it only on the shots that get a cut-out device, never on a whole library.

API
    masks_dir = separate(clip, points=[(x,y),...], labels=[1,...,0], start=0, end=None, out_dir=...)
        points are in 960-px-wide coordinates of the clip's first frame (1 = subject, 0 = leave out);
        points=None -> one point at the frame centre (fine for a hero shot of one aircraft/ship).
    text_behind(clip, masks_dir, text_png, out_mp4, fade=(0.2, 0.7))
        composites an RGBA 1920x1080 title layer BEHIND the subject (text over picture, subject back on top).
        Lesson from the test: the subject hides what it overlaps — place the words where the subject is thin.
"""
from __future__ import annotations
import json, os, subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
try:
    import config  # noqa: F401  (loads keys.env into the environment)
except Exception:
    pass
SAM2_PYTHON = os.getenv("SAM2_PYTHON", "D:/CDev/_skills_eval/.object-separation/Scripts/python.exe")


def available() -> bool:
    return Path(SAM2_PYTHON).exists()


def separate(clip, points=None, labels=None, start=0, end=None, out_dir=None) -> Path:
    if not available():
        raise RuntimeError(f"SAM 2 venv not found at {SAM2_PYTHON} (see separate.py header)")
    clip = Path(clip).resolve()
    out_dir = Path(out_dir or clip.with_suffix("")).resolve() / "masks"
    out_dir.mkdir(parents=True, exist_ok=True)
    job = {"video": str(clip), "start": start, "end": end, "points": points, "labels": labels, "out": str(out_dir)}
    r = subprocess.run([SAM2_PYTHON, str(HERE / "sam2_worker.py"), json.dumps(job)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("sam2_worker failed:\n" + r.stderr[-2000:])
    print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "sam2: done")
    return out_dir


def text_behind(clip, masks_dir, text_png, out_mp4, fade=(0.2, 0.7), fps=30):
    """Pure numpy/cv2 composite (runs in the CDev venv)."""
    import cv2, numpy as np
    T = cv2.imread(str(text_png), cv2.IMREAD_UNCHANGED).astype(np.float32)
    T_rgb, T_a = T[..., :3], T[..., 3:4] / 255.0
    masks = sorted(Path(masks_dir).glob("*.png"))
    cap = cv2.VideoCapture(str(clip))
    W, H = int(cap.get(3)), int(cap.get(4))
    ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
                           "-r", str(fps), "-i", "-", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", str(out_mp4)],
                          stdin=subprocess.PIPE)
    for k, mp in enumerate(masks):
        ok, img = cap.read()
        if not ok:
            break
        img = img.astype(np.float32)
        m = cv2.GaussianBlur(cv2.resize(cv2.imread(str(mp), 0).astype(np.float32) / 255, (W, H)), (5, 5), 0)[..., None]
        a = T_a * min(1.0, max(0.0, (k / fps - fade[0]) / max(0.01, fade[1] - fade[0])))
        comp = img * (1 - a) + T_rgb * a
        ff.stdin.write(np.clip(comp * (1 - m) + img * m, 0, 255).astype(np.uint8).tobytes())
    ff.stdin.close(); ff.wait()
    return Path(out_mp4)
