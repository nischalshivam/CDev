#!/usr/bin/env python3
"""
audio_design.py — the layer that separates "narration over pictures" from a documentary.

Three parts, all built with ffmpeg (no licensing questions, nothing to source):

  bed(duration)        a dark sustained score bed: sub drone + fifth + slow swell, heavily
                       low-passed so it sits UNDER a voice instead of fighting it
  impact(out)          a one-shot hit for section breaks (filtered noise burst + falling sine)
  build_mix(...)       assembles narration + punch-ins + bed + hits into one track, with the bed
                       side-chain ducked by the narration so speech always wins

PUNCH-INS are the structural idea: the narration stops for 3-4 seconds and the ORIGINAL match
audio plays — crowd, corner, the punch. It is the cheapest way to make a cut feel live, and it is
why the intro works. The narration timeline is split at beat boundaries and the source audio is
spliced in, so the video timeline lengthens by exactly the punch-in durations.
"""
from __future__ import annotations
import os
import subprocess
from pathlib import Path

SR = 48000


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-400:])
    return r


def bed(duration: float, out, key_hz: float = 55.0) -> str:
    """Dark score bed, in a band the listener's speakers can actually reproduce.

    THE BUG THIS REPLACES: the first bed was a 55Hz sub, a fifth, an octave and brown noise, all
    low-passed to 380Hz. Its total level measured -20dB, which looked correct, so it was declared
    working. But measured ABOVE 300Hz — the only band a laptop or phone speaker reproduces at all —
    it was -47dB, i.e. 33dB beneath the narration. Not quiet. Inaudible. Measuring total energy was
    measuring the wrong thing.

    The fix is spectral, not a level change. An A-minor drone is voiced across the MIDRANGE with
    real upper partials (220 / 262 / 330 / 440 / 523Hz) plus a quiet 1-3kHz air band, so there is
    something in 300-4000Hz to hear. The 55Hz sub stays for weight on speakers that have it, but
    the bed no longer depends on it."""
    d, root = duration, key_hz
    # A-minor voiced upward: root, fifth, octave, then the audible triad and its upper octave.
    # amplitude falls with frequency so it reads as one dark pad, not a stack of tones.
    # Weighted so most of the ENERGY sits at 220Hz and above. A first attempt kept the sub loud
    # (0.42 at 55Hz) and still measured 15dB down above 300Hz — the sub dominates the total and
    # starves the audible band. The low voices are support here, not the body of the sound.
    voices = [(root, 0.20), (root * 1.5, 0.09), (root * 2, 0.13),
              (root * 4, 0.26), (root * 4.756, 0.21), (root * 6, 0.18),
              (root * 8, 0.13), (root * 9.51, 0.095), (root * 12, 0.07)]
    parts, labels = [], []
    for i, (hz, amp) in enumerate(voices):
        # a few cents of detune per voice keeps the pad from sounding like a test signal
        parts.append(f"sine=frequency={hz*(1+0.0007*(i%3-1)):.3f}:sample_rate={SR}:"
                     f"duration={d}[v{i}];[v{i}]volume={amp}[v{i}a]")
        labels.append(f"[v{i}a]")
    # AIR: the band small speakers are loudest in. Without this the pad is still felt-not-heard.
    parts.append(f"anoisesrc=color=pink:sample_rate={SR}:duration={d}:amplitude=0.5[air];"
                 f"[air]highpass=f=900,lowpass=f=3200,volume=0.16,"
                 f"tremolo=f=0.19:d=0.5[aira]")
    labels.append("[aira]")
    parts.append(f"anoisesrc=color=brown:sample_rate={SR}:duration={d}:amplitude=0.30[lo];"
                 f"[lo]lowpass=f=200,volume=0.16[loa]")
    labels.append("[loa]")
    f = (";".join(parts) + ";" + "".join(labels) +
         f"amix=inputs={len(labels)}:normalize=0[m];"
         # breathing swell + a gentle top roll-off (4kHz, not 380Hz) so it sits under speech
         # without disappearing from the only band that can be heard
         f"[m]tremolo=f=0.12:d=0.30,highpass=f=34,lowpass=f=4200,"
         f"afade=t=in:st=0:d=3,afade=t=out:st={max(0.1,d-4):.2f}:d=4,"
         f"alimiter=limit=0.9,loudnorm=I=-22:TP=-3:LRA=7[out]")
    _run(["ffmpeg", "-y", "-loglevel", "error", "-filter_complex", f, "-map", "[out]",
          "-t", f"{d:.2f}", "-c:a", "pcm_s16le", str(out)])
    return str(out)


def impact(out, kind: str = "hit") -> str:
    """One-shot for a section break — built in three layers so it survives small speakers.

    THE BUG THIS REPLACES: the old hit was a 90Hz sine plus brown noise low-passed to 180Hz. Pure
    sub-bass: total level -23dB but only -44dB above 300Hz. On anything without a woofer it was
    silence, which is exactly what came back as "hits sunai nahi de rahe".

    What actually makes a hit audible is the TRANSIENT, and a transient lives high. Three layers:
      CRACK  1.2kHz+ noise, ~30ms  — the part you hear on a laptop; this is the attack
      BODY   250-900Hz noise, ~180ms — the weight you hear on any speaker
      SUB    90Hz sine, ~700ms      — felt, not heard; a bonus, never the whole sound"""
    if kind == "whoosh":
        f = (f"anoisesrc=color=white:sample_rate={SR}:duration=1.0:amplitude=0.7[n];"
             f"[n]highpass=f=450,lowpass=f=7000,afade=t=in:st=0:d=0.40:curve=exp,"
             f"afade=t=out:st=0.40:d=0.60,volume=0.62,alimiter=limit=0.92[out]")
    else:
        f = (
            f"anoisesrc=color=white:sample_rate={SR}:duration=1.0:amplitude=0.9[c];"
            f"anoisesrc=color=white:sample_rate={SR}:duration=1.0:amplitude=0.9[b];"
            f"sine=frequency=90:sample_rate={SR}:duration=1.0[s];"
            f"[c]highpass=f=1200,highpass=f=1200,afade=t=out:st=0:d=0.05:curve=exp,"
            f"volume=0.85[c1];"
            f"[b]highpass=f=250,lowpass=f=900,afade=t=out:st=0:d=0.22:curve=exp,"
            f"volume=0.95[b1];"
            f"[s]volume=0.55,afade=t=out:st=0:d=0.70:curve=exp[s1];"
            # 0.75 pre-limiter: the crack decays in ~5ms, faster than alimiter's attack, so it
            # sailed past the limiter and the file peaked at 0dBFS. Gain-stage it instead.
            f"[c1][b1][s1]amix=inputs=3:normalize=0,volume=0.75,alimiter=limit=0.89[out]")
    _run(["ffmpeg", "-y", "-loglevel", "error", "-filter_complex", f, "-map", "[out]",
          "-c:a", "pcm_s16le", str(out)])
    return str(out)


def cut_source_audio(video, start: float, dur: float, out) -> str:
    """Pull the ORIGINAL audio of a shot for a punch-in (crowd, corner, the punch itself)."""
    _run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.2f}", "-t", f"{dur:.2f}",
          "-i", str(video), "-vn", "-ac", "2", "-ar", str(SR),
          "-af", f"volume=1.0,afade=t=in:st=0:d=0.25,afade=t=out:st={max(0.05,dur-0.4):.2f}:d=0.4",
          "-c:a", "pcm_s16le", str(out)])
    return str(out)


def build_voice_track(narration_mp3: str, punch_ins: list, total_narration: float,
                      workdir, out) -> tuple:
    """Split the narration at each punch-in point and splice the source audio between.

    punch_ins: [{"at": seconds_into_narration, "audio": wav_path, "dur": seconds}]
    Returns (voice_wav, timeline) where timeline maps ORIGINAL narration time -> NEW time, so the
    video plan can be stretched to match."""
    workdir = Path(workdir); workdir.mkdir(parents=True, exist_ok=True)
    pts = sorted(punch_ins, key=lambda p: p["at"])
    pieces, timeline, prev, shift = [], [], 0.0, 0.0
    for i, p in enumerate(pts):
        seg = workdir / f"nar{i:02d}.wav"
        _run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{prev:.2f}",
              "-t", f"{p['at']-prev:.2f}", "-i", narration_mp3, "-ac", "2", "-ar", str(SR),
              "-c:a", "pcm_s16le", str(seg)])
        pieces.append(str(seg))
        timeline.append({"from": prev, "to": p["at"], "shift": shift})
        pieces.append(p["audio"])
        shift += p["dur"]
        prev = p["at"]
    tail = workdir / "nar_tail.wav"
    _run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{prev:.2f}",
          "-t", f"{max(0.1,total_narration-prev):.2f}", "-i", narration_mp3,
          "-ac", "2", "-ar", str(SR), "-c:a", "pcm_s16le", str(tail)])
    pieces.append(str(tail))
    timeline.append({"from": prev, "to": total_narration, "shift": shift})

    lst = workdir / "voice.txt"
    with open(lst, "w", encoding="utf-8") as f:
        for p in pieces:
            f.write(f"file '{Path(p).resolve().as_posix()}'\n")
    _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
          "-c:a", "pcm_s16le", str(out)])
    return str(out), timeline


def final_mix(voice_wav: str, duration: float, out, hits: list = None,
              bed_db: float = -3.5, hit_db: float = -2.0) -> str:
    """Voice + bed (side-chain ducked by the voice) + section hits. Speech always wins."""
    work = Path(out).parent
    bedwav = bed(duration, work / "_bed.wav")
    inputs = ["-i", voice_wav, "-i", bedwav]
    hits = hits or []
    hitfiles = []
    for i, h in enumerate(hits):
        hp = work / f"_hit{i}.wav"
        impact(hp, h.get("kind", "hit"))
        hitfiles.append((str(hp), h["at"]))
        inputs += ["-i", str(hp)]

    # bed ducked by the voice; hits delayed to their cue points
    # The bed is already loudnorm'd to -24 LUFS, so bed_db is the ONLY attenuation applied.
    # (Attenuating a already-quiet bed and THEN hard side-chaining it drove the bed to ~-47 dB and
    # made it inaudible — a narration gap measured -53 dB, i.e. silence.)
    fc = [f"[1:a]volume={bed_db}dB[bed0]",
          "[0:a]asplit=2[v1][vkey]",
          # gentle duck: speech wins, but the bed stays present underneath instead of vanishing
          "[bed0][vkey]sidechaincompress=threshold=0.08:ratio=2.5:attack=25:release=600[bedduck]"]
    mixins = ["[v1]", "[bedduck]"]
    for i, (_, at) in enumerate(hitfiles):
        fc.append(f"[{2+i}:a]adelay={int(at*1000)}|{int(at*1000)},volume=-2dB[h{i}]")
        mixins.append(f"[h{i}]")
    fc.append("".join(mixins) + f"amix=inputs={len(mixins)}:normalize=0,"
              f"alimiter=limit=0.95,volume=1.0[out]")
    _run(["ffmpeg", "-y", "-loglevel", "error"] + inputs +
         ["-filter_complex", ";".join(fc), "-map", "[out]", "-t", f"{duration:.2f}",
          "-c:a", "aac", "-b:a", "192k", str(out)])
    return str(out)


if __name__ == "__main__":
    import sys
    d = Path(sys.argv[1] if len(sys.argv) > 1 else "audio_demo"); d.mkdir(exist_ok=True)
    print(bed(12.0, d / "bed.wav"))
    print(impact(d / "hit.wav"))
    print(impact(d / "whoosh.wav", "whoosh"))
