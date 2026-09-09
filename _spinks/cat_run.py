
import sys, os, json, base64, subprocess, tempfile, re
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, f"{ROOT}/CODE")
os.environ["CDEV_LIBRARY_ROOT"] = f"{ROOT}/_tyson/library"   # SHARED library
import config, catalog_db, urllib.request

# Repo root, derived from THIS file. Never hard-code an absolute path: a machine change (or a
# different drive letter) silently sends every read and write somewhere else. One earlier build
# wrote 719 files into the wrong library for exactly this reason, and the same mistake was already
# sitting in two other files at the time.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")

RAW = f"{ROOT}/_spinks/raw/"
KEY, BASE, MODEL = config.GEMINI_RELAY_KEY, config.GEMINI_RELAY_BASE, "gemini-2.5-flash"
SRC_FILE = "qKNGyEjxFTY.mp4"; SID = "SRC_SPINKS_1988"
COLS = ["COL_PROJECT_TYSON-SPINKS", "COL_DOMAIN_BOXING", "COL_ENTITY_TYSON", "COL_ENTITY_SPINKS"]

PROMPT = ("Cataloging archival boxing footage (Tyson vs Michael Spinks, 27 June 1988, Atlantic City). "
 'Return ONLY JSON: {"description":"1 literal line — who is on screen and what happens",'
 '"keywords":["8-14: subject, shot-type, camera, light, colour, use"],'
 '"shot":"wide|medium|close-up|extreme close-up","camera":"static|pan|tilt|push|handheld",'
 '"people":["ONLY people clearly VISIBLE: Mike Tyson, Michael Spinks, referee, crowd, cornermen"],'
 '"serves":["what a narrator could say over this — e.g. the fall, the fear, the crowd waits"],'
 '"objects":[things],"places":[setting],'
 '"talking_head":true_if_someone_speaks_straight_to_camera_or_studio_pundit,'
 '"quality":"low|medium|high","clean_status":"clean|fixable|unusable","match_conf":0.0_to_1.0}. '
 "clean_status='fixable' for a corner broadcast bug; 'unusable' only if text covers the fighters. "
 "Do not name a boxer you cannot actually see.")

def frame(t):
    fp = tempfile.mktemp(suffix=".jpg")
    subprocess.run(["ffmpeg","-y","-loglevel","error","-ss",f"{t:.2f}","-i",RAW+SRC_FILE,
                    "-frames:v","1","-vf","scale=720:-2",fp], capture_output=True)
    if os.path.exists(fp):
        b=open(fp,"rb").read(); os.remove(fp); return b
    return None

def describe(img):
    body={"model":MODEL,"max_tokens":420,"messages":[{"role":"user","content":[
        {"type":"text","text":PROMPT},
        {"type":"image_url","image_url":{"url":"data:image/jpeg;base64,"+base64.b64encode(img).decode()}}]}]}
    req=urllib.request.Request(BASE+"/chat/completions",data=json.dumps(body).encode(),
        headers={"Authorization":"Bearer "+KEY,"Content-Type":"application/json"})
    d=json.load(urllib.request.urlopen(req,timeout=120))
    m=re.search(r"\{.*\}", d["choices"][0]["message"]["content"], re.S)
    return json.loads(m.group(0)) if m else {}

def job(seg):
    img=frame(seg["start"]+(seg["end"]-seg["start"])*0.45)
    if not img: return None
    try: return {"seg":seg,"meta":describe(img)}
    except Exception as e: return {"err":str(e)[:60]}

def main():
    local=json.load(open(f"{ROOT}/_spinks/local_segments.json"))
    segs=[s for s in local[SRC_FILE]["segments"] if s["usable"]]
    print(f"cataloging {len(segs)} Spinks segments into the SHARED library", flush=True)
    c=catalog_db.Catalog()
    c.upsert_entity("ENT_SPINKS","person","Michael Spinks",["Spinks","Michael Spinks"])
    for cid,layer in [("COL_PROJECT_TYSON-SPINKS","PROJECT"),("COL_ENTITY_SPINKS","ENTITY")]:
        c.ensure_collection(cid,layer)
    obj=c.ingest_file(RAW+SRC_FILE)
    c.add_source(SID,"youtube:qKNGyEjxFTY","video",content_hash=obj["sha256"],channel="archive",
                 meta={"title":"Tyson vs Spinks, 27 June 1988"})
    done=err=gated=0
    with ThreadPoolExecutor(max_workers=7) as ex:
        for fu in as_completed([ex.submit(job,s) for s in segs]):
            r=fu.result()
            if not r or r.get("err"): err+=1; continue
            seg,meta=r["seg"],r["meta"]
            if meta.get("talking_head") or meta.get("clean_status")=="unusable": gated+=1; continue
            people=meta.get("people",[]) or []
            blob=" ".join(people).lower()
            ents=[]
            if "tyson" in blob: ents.append("ENT_TYSON")
            if "spinks" in blob: ents.append("ENT_SPINKS")
            aid=f"AST_SPINKS_{int(seg['start']*1000)}"
            ok=c.add_asset(aid,"video",source_id=SID,start_ms=int(seg["start"]*1000),
                end_ms=int(seg["end"]*1000),description=(meta.get("description") or "")[:300],
                era_from=1988,era_to=1988,quality=meta.get("quality","medium"),
                clean_status=meta.get("clean_status","clean"),
                match_conf=float(meta.get("match_conf",0.8) or 0.8),review_status="needs_review",
                entities=ents,collections=COLS,
                catalog={"keywords":meta.get("keywords",[]),"serves":meta.get("serves",[]),
                         "objects":meta.get("objects",[]),"places":meta.get("places",[]),
                         "people":people,"shot":meta.get("shot",""),"camera":meta.get("camera",""),
                         "motion":seg.get("motion"),"src_title":"Tyson vs Spinks 1988","model":MODEL})
            if ok: c.auto_approve(aid); done+=1
    print(f"DONE: {done} cataloged, {gated} gated, {err} err")
    print("SHARED LIBRARY NOW:", c.stats())
main()
