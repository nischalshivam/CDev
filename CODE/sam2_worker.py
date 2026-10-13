"""sam2_worker.py — runs INSIDE the SAM 2 venv (torch + CUDA). Called by separate.py with one JSON arg:
{"video","start","end","points","labels","out"}. Writes one PNG mask per frame (white = subject).
Code follows the Barty-Bart object-separation skill: model size by GPU memory, 60-frame chunks seeded by the
previous chunk's last mask so memory stays flat."""
import json, sys, time
import numpy as np, torch, cv2
from transformers import Sam2VideoModel, Sam2VideoProcessor

job = json.loads(sys.argv[1])
VIDEO, W = job["video"], 960
cap0 = cv2.VideoCapture(VIDEO)
n_frames = int(cap0.get(cv2.CAP_PROP_FRAME_COUNT)); cap0.release()
START = int(job.get("start") or 0)
END = int(job["end"]) if job.get("end") is not None else n_frames - 1
if torch.cuda.is_available():
    gb = torch.cuda.get_device_properties(0).total_memory / 1e9
    dev, MODEL = "cuda", "facebook/sam2.1-hiera-" + ("large" if gb >= 12 else "base-plus")
else:
    dev, MODEL = "cpu", "facebook/sam2.1-hiera-tiny"
model = Sam2VideoModel.from_pretrained(MODEL).to(dev).eval()
proc = Sam2VideoProcessor.from_pretrained(MODEL)


def read_frames(a, b):
    cap = cv2.VideoCapture(VIDEO); cap.set(cv2.CAP_PROP_POS_FRAMES, a); out = []
    for _ in range(a, b + 1):
        ok, im = cap.read()
        if not ok:
            break
        out.append(cv2.cvtColor(cv2.resize(im, (W, int(im.shape[0] * W / im.shape[1]))), cv2.COLOR_BGR2RGB))
    return out


def chunk(frames, points=None, labels=None, mask=None):
    H = frames[0].shape[0]
    s = proc.init_video_session(video=frames, inference_device=dev, video_storage_device="cpu",
                                inference_state_device="cpu", dtype=torch.float32)
    if mask is None:
        proc.add_inputs_to_inference_session(inference_session=s, frame_idx=0, obj_ids=1,
                                             input_points=[[points]], input_labels=[[labels]])
    else:
        proc.add_inputs_to_inference_session(inference_session=s, frame_idx=0, obj_ids=1, input_masks=mask.astype(np.uint8))
    res = {}
    with torch.inference_mode():
        model(inference_session=s, frame_idx=0)
        for o in model.propagate_in_video_iterator(s, start_frame_idx=0):
            m = proc.post_process_masks([o.pred_masks], original_sizes=[[H, W]], binarize=True)[0]
            res[o.frame_idx] = m.squeeze().cpu().numpy().astype(bool)
    return res


t0 = time.time()
first = read_frames(START, START)[0]
pts = job.get("points") or [[W // 2, first.shape[0] // 2]]
lbl = job.get("labels") or [1] * len(pts)
a, seed, n = START, None, 0
while a < END:
    b = min(END, a + 60)
    fr = read_frames(a, b)
    r = chunk(fr, points=pts, labels=lbl) if seed is None else chunk(fr, mask=seed)
    for k, m in r.items():
        cv2.imwrite(f"{job['out']}/{a + k:05d}.png", m.astype(np.uint8) * 255); n += 1
    seed, a = r[len(fr) - 1], b
print(f"sam2 {MODEL} on {dev}: {n} masks in {time.time() - t0:.1f}s")
