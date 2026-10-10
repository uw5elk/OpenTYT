#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Офлайн-аналіз запису «APRS проби» (R4): WAV 8000 Гц, 16 біт (з tools/aprs_capture.py або
кнопки «Записати звук APRS» у gui_flasher.py).

Що робить:
  1. Рівень: DC, RMS, пік, пік/RMS, обмеження (кліпінг).
  2. Формат відліків: частка парних значень, по кожному біту -- P(1) і P(не змінився від
     попереднього відліку). Якщо молодші біти «випадкові» (0,50 / 0,50), а сигнал малий --
     ознака, що в них не звук; компандування видно за «дірками» в гістограмі.
  3. Межі блоків по 160 (DMA-половини; запис вирівняний по них): середній |x[n] - x[n-1]|
     на межах і всередині. Розриви потоку на межах дають відношення >> 1.
  4. Спектр (якщо є numpy): частки потужності по смугах 0-300 / 300-900 / 900-2500 / 2500-3400 /
     3400-4000 Гц і «чи білий» фон.
  5. Пакети: блоки 20 мс, де тони 1200/2200 сильні (Goertzel); перекіс 2200 відносно 1200 (дБ)
     і SNR у смузі 0-4000 Гц (як у хост-тесті: RMS сигналу / RMS фону).
  6. Демодулятор: ТОЙ САМИЙ C-код, що в прошивці (tools/aprs_demod_cli.c збирається системним
     cc/gcc/clang), на записі як є, з авто-режекцією і з корекцією перекосу (передспотворення
     +6 дБ/окт: 2200 відносно 1200 +5 дБ) -- щоб перевірити гіпотезу про деемфазис.
  7. multimon-ng (якщо встановлено): той самий запис, передискретизований до 22050 Гц.

Вжиток:
    python3 tools/aprs_offline.py запис.wav [--channel 0|1]
    python3 tools/aprs_offline.py --selftest      # еталонний кадр з tools/aprs_afsk_ref.py
Потрібні лише стандартна бібліотека й C-компілятор; numpy/scipy -- для спектра і multimon-ng.
"""
import array
import math
import os
import shutil
import subprocess
import sys
import tempfile
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HERE)
FS = 8000
BLOCK = 160


# ---- читання ----------------------------------------------------------------------------
def read_wav(path, channel=0):
    with wave.open(path, "rb") as w:
        nch, sw, fr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if sw != 2:
        raise SystemExit("потрібен WAV 16 біт (є %d)" % (8 * sw))
    a = array.array("h")
    a.frombytes(raw)
    if sys.byteorder != "little":
        a.byteswap()
    if nch > 1:
        a = a[channel::nch]
    if fr != FS:
        print("УВАГА: частота %d Гц, очікується 8000" % fr)
    return list(a), nch, fr


# ---- 1-3: рівень, формат, межі блоків -------------------------------------------------------
def level_report(x):
    n = len(x)
    mean = sum(x) / float(n)
    rms = math.sqrt(sum((v - mean) ** 2 for v in x) / n)
    pk = max(abs(v - mean) for v in x)
    clip = sum(1 for v in x if v in (32767, -32768))
    out = ["Рівень: %d відліків (%.1f с); DC %.1f; RMS %.1f; пік %.0f; пік/RMS %.2f; кліпінг %d"
           % (n, n / float(FS), mean, rms, pk, pk / rms if rms else 0, clip)]
    out.append("  (білий гауссів шум має пік/RMS ~4 на кількох тисячах відліків; ~1,4 -- синусоїда; "
               "~1,7 -- рівномірний розподіл, як у випадкових молодших бітів)")
    return out, mean, rms


def format_report(x):
    n = len(x)
    out = ["Формат відліків:"]
    even = sum(1 for v in x if (v & 1) == 0) / float(n)
    out.append("  парних значень: %.3f (0,5 -- норма; 1,0 -- молодший біт завжди 0)" % even)
    ones, same = [], []
    for b in range(16):
        m = 1 << b
        o = sum(1 for v in x if (v & m)) / float(n)
        s = sum(1 for i in range(1, n) if ((x[i] ^ x[i - 1]) & m) == 0) / float(n - 1)
        ones.append(o)
        same.append(s)
    out.append("  біт:      " + " ".join("%4d" % b for b in range(15, -1, -1)))
    out.append("  P(1):     " + " ".join("%.2f" % ones[b] for b in range(15, -1, -1)))
    out.append("  P(=попер):" + " ".join("%.2f" % same[b] for b in range(15, -1, -1)))
    out.append("  (0,50/0,50 -- біт випадковий; у звуку з RMS ~700 це нормально для бітів 0..~7)")
    hist = {}
    for v in x:
        hist[v] = hist.get(v, 0) + 1
    lo, hi = min(x), max(x)
    span = hi - lo + 1
    used = len(hist)
    out.append("  різних значень: %d з діапазону %d..%d (%d); заповненість %.2f "
               "(для 16-біт звуку з цим RMS -- близько 1; набагато менше -- компандування/зсув)"
               % (used, lo, hi, span, used / float(span)))
    return out


def boundary_report(x):
    db, di, nb, ni = 0.0, 0.0, 0, 0
    for i in range(1, len(x)):
        d = abs(x[i] - x[i - 1])
        if i % BLOCK == 0:
            db += d
            nb += 1
        else:
            di += d
            ni += 1
    if nb == 0 or ni == 0:
        return ["Межі блоків: замало даних"]
    rb, ri = db / nb, di / ni
    return ["Межі блоків по 160: середній |x[n]-x[n-1]| на межі %.1f, всередині %.1f, відношення %.2f "
            "(~1 -- розривів немає; >> 1 -- стрибки на межах DMA-половин)" % (rb, ri, rb / ri if ri else 0)]


# ---- 4: спектр -------------------------------------------------------------------------------
def spectrum_report(x):
    try:
        import numpy as np
    except ImportError:
        return ["Спектр: пропущено (немає numpy)"]
    a = np.asarray(x, dtype=float)
    a -= a.mean()
    nfft = 256
    win = np.hanning(nfft)
    segs = [a[i:i + nfft] * win for i in range(0, len(a) - nfft, nfft // 2)]
    if not segs:
        return ["Спектр: замало даних"]
    psd = np.mean([np.abs(np.fft.rfft(s)) ** 2 for s in segs], axis=0)
    f = np.fft.rfftfreq(nfft, 1.0 / FS)
    tot = psd[1:].sum()
    bands = [(0, 300), (300, 900), (900, 2500), (2500, 3400), (3400, 4001)]
    parts = []
    for lo, hi in bands:
        sel = (f >= lo) & (f < hi)
        parts.append("%d-%d: %.0f%%" % (lo, min(hi, 4000), 100.0 * psd[sel].sum() / tot))
    hf = psd[(f >= 3000) & (f < 3900)].mean()
    mf = psd[(f >= 1000) & (f < 2000)].mean()
    return ["Спектр (частки потужності): " + "; ".join(parts),
            "  3-3,9 кГц відносно 1-2 кГц: %+.1f дБ (тракт HR-C6000 з фільтром 3 кГц мав би давати "
            "спад; ~0 дБ -- шум «цифровий»/білий, не з приймача)" % (10 * math.log10(hf / mf) if mf > 0 and hf > 0 else 0)]


# ---- 5: пакети, перекіс, SNR ---------------------------------------------------------------------
def goertzel_amp(blk, f):
    w = 2 * math.pi * f / FS
    c = 2 * math.cos(w)
    q1 = q2 = 0.0
    m = sum(blk) / float(len(blk))
    for v in blk:
        q0 = (v - m) + c * q1 - q2
        q2, q1 = q1, q0
    p = q1 * q1 + q2 * q2 - c * q1 * q2
    return 2 * math.sqrt(max(p, 0)) / len(blk)


def twist_short(x):
    """Перекіс 2200/1200, дБ: короткі вікна по 8 відліків (1 мс, менше біта), кожне -- до того тону,
    що в ньому втричі сильніший; середні амплітуди. Goertzel на блоках 20 мс тут не годиться:
    тон пакета щобіта змінюється з довільною фазою, і когерентна сума «завищує» один із тонів
    (на рівному еталоні давала +6 дБ). Цей спосіб на еталоні: 0 / +6 / -6 / -12 дБ -> 0,0 / +5,1 /
    -5,2 / -11,2 (трохи стискає)."""
    L = 8
    wm = [complex(math.cos(2 * math.pi * 1200 * k / FS), -math.sin(2 * math.pi * 1200 * k / FS)) for k in range(L)]
    ws = [complex(math.cos(2 * math.pi * 2200 * k / FS), -math.sin(2 * math.pi * 2200 * k / FS)) for k in range(L)]
    em, es = [], []
    for i in range(0, len(x) - L, 2):
        seg = x[i:i + L]
        m = abs(sum(a * b for a, b in zip(seg, wm)))
        s = abs(sum(a * b for a, b in zip(seg, ws)))
        if m > 3 * s:
            em.append(m)
        elif s > 3 * m:
            es.append(s)
    if len(em) < 20 or len(es) < 20:
        return None
    return 20 * math.log10((sum(es) / len(es)) / (sum(em) / len(em)))


def packets_report(x):
    blocks = [x[i:i + BLOCK] for i in range(0, len(x) - BLOCK + 1, BLOCK)]
    if len(blocks) < 10:
        return ["Пакети: замало даних"]
    rows = []
    for b in blocks:
        m = sum(b) / float(BLOCK)
        p = sum((v - m) ** 2 for v in b) / BLOCK
        rows.append((goertzel_amp(b, 1200), goertzel_amp(b, 2200), p))
    e = sorted(a * a + c * c for a, c, _ in rows)
    med = e[len(e) // 2]
    pk = [r for r in rows if r[0] ** 2 + r[1] ** 2 > 6 * med]
    quiet = [r for r in rows if r[0] ** 2 + r[1] ** 2 <= 2 * med]
    if not pk:
        return ["Пакети: блоків із сильними 1200/2200 не знайдено (медіана амплітуд %.0f)" % math.sqrt(med)]
    a12 = sum(r[0] for r in pk) / len(pk)
    a22 = sum(r[1] for r in pk) / len(pk)
    ppk = sum(r[2] for r in pk) / len(pk)
    pq = (sum(r[2] for r in quiet) / len(quiet)) if quiet else 0.0
    out = ["Пакети (блоки 20 мс із сильними тонами): %d з %d (%.1f с)" % (len(pk), len(rows), len(pk) * 0.02)]
    seg = []
    for i, b in enumerate(blocks):
        r = rows[i]
        if r[0] ** 2 + r[1] ** 2 > 6 * med:
            seg.extend(b)
    tw = twist_short(seg)
    out.append("  амплітуди Goertzel (20 мс): 1200 -- %.0f, 2200 -- %.0f" % (a12, a22))
    if tw is None:
        out.append("  перекіс 2200/1200: замало чистих вікон тону, щоб оцінити")
    else:
        out.append("  перекіс 2200/1200 (вікна 1 мс): %+.1f дБ (демодулятор тримає +-12 дБ)" % tw)
    if pq > 0 and ppk > pq:
        snr = 10 * math.log10((ppk - pq) / pq)
        out.append("  SNR (0-4000 Гц): %.1f дБ = RMS пакета %.0f проти RMS фону %.0f (поріг демодулятора на "
                   "хост-тесті ~6,5 дБ)" % (snr, math.sqrt(ppk - pq), math.sqrt(pq)))
    return out


# ---- 6-7: демодулятори ---------------------------------------------------------------------------
def build_cli():
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if not cc:
        return None, "немає C-компілятора (cc/gcc/clang)"
    outdir = os.path.join(tempfile.gettempdir() if os.access(tempfile.gettempdir(), os.W_OK)
                          else os.path.expanduser("~"), "opentyt_aprs")
    os.makedirs(outdir, exist_ok=True)
    exe = os.path.join(outdir, "aprs_demod_cli" + (".exe" if os.name == "nt" else ""))
    src = [os.path.join(HERE, "aprs_demod_cli.c"),
           os.path.join(FW, "application", "source", "functions", "aprs_afsk.c"),
           os.path.join(FW, "application", "source", "functions", "aprs_probe_dsp.c")]
    if os.path.exists(exe) and all(os.path.getmtime(exe) > os.path.getmtime(s) for s in src):
        return exe, None
    cmd = [cc, "-O2", "-std=gnu11", "-DENABLE_APRS_RX_PROBE", "-I", os.path.join(FW, "application", "include"),
           "-o", exe] + src + ["-lm"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return None, "збірка не вдалась: " + r.stderr[-400:]
    return exe, None


def run_cli(exe, x, extra=()):
    with tempfile.NamedTemporaryFile(suffix=".s16", delete=False) as f:
        a = array.array("h", [max(-32768, min(32767, int(v))) for v in x])
        if sys.byteorder != "little":
            a.byteswap()
        f.write(a.tobytes())
        path = f.name
    try:
        r = subprocess.run([exe, path] + list(extra), capture_output=True, text=True)
    finally:
        os.unlink(path)
    return r.stdout


def preemph(x, gain_db_2200=5.0):
    """Перший порядок y = x - k*x[n-1]: k підібрано, щоб 2200 відносно 1200 піднявся на ~gain дБ."""
    best, bk = 1e9, 0.0
    for i in range(0, 96):
        k = i / 100.0
        def mag(f):
            w = 2 * math.pi * f / FS
            return math.hypot(1 - k * math.cos(w), k * math.sin(w))
        d = abs(20 * math.log10(mag(2200) / mag(1200)) - gain_db_2200)
        if d < best:
            best, bk = d, k
    y = [x[0]] + [x[i] - bk * x[i - 1] for i in range(1, len(x))]
    m = max(1.0, max(abs(v) for v in y) / 30000.0)
    return [v / m for v in y], bk


def demod_report(x):
    exe, err = build_cli()
    if not exe:
        return ["Наш демодулятор: пропущено (%s)" % err], None
    out = []
    first = None
    for title, data, extra in (("як є, авто-режекція", x, ["--auto-notch"]),
                               ("корекція перекосу +5 дБ", preemph(x, 5.0)[0], ["--auto-notch"]),
                               ("корекція перекосу +10 дБ", preemph(x, 10.0)[0], ["--auto-notch"])):
        txt = run_cli(exe, data, extra)
        if first is None:
            first = txt
        summ = [l for l in txt.splitlines() if l.startswith("SUMMARY")]
        out.append("Наш демодулятор (%s): %s" % (title, summ[0][8:] if summ else "?"))
        for l in txt.splitlines():
            if l.startswith("OK") or l.startswith("BAD"):
                out.append("    " + l)
            if l.startswith("PLL"):
                out.append("    фаза тактів (8 бінів по 1/8 біта, ідеал -- 3/4): " + l[4:])
    return out, first


def multimon_report(x):
    mm = shutil.which("multimon-ng")
    if not mm:
        return ["multimon-ng: не встановлено -- пропущено"]
    try:
        import numpy as np
        from scipy import signal
    except ImportError:
        return ["multimon-ng: пропущено (для передискретизації потрібні numpy+scipy)"]
    y = signal.resample_poly(np.asarray(x, dtype=float), 441, 160)
    with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as f:
        f.write(np.clip(y, -32768, 32767).astype("<i2").tobytes())
        path = f.name
    try:
        r = subprocess.run([mm, "-q", "-t", "raw", "-a", "AFSK1200", path], capture_output=True, text=True)
    finally:
        os.unlink(path)
    frames = [l for l in r.stdout.splitlines() if l.startswith("AFSK1200")]
    return ["multimon-ng: кадрів %d" % len(frames)] + ["    " + l for l in r.stdout.splitlines() if l.strip()][:20]


def analyze(path, channel=0):
    x, nch, fr = read_wav(path, channel)
    lines = ["Файл: %s (каналів %d, %d Гц, аналізую канал %d)" % (path, nch, fr, channel)]
    lv, _, _ = level_report(x)
    lines += lv
    lines += format_report(x)
    lines += boundary_report(x)
    lines += spectrum_report(x)
    lines += packets_report(x)
    dm, raw = demod_report(x)
    lines += dm
    lines += multimon_report(x)
    return "\n".join(lines), raw


def selftest():
    sys.path.insert(0, HERE)
    import aprs_afsk_ref as ref
    fr, fcs = ref.frame()
    s = [0] * 4000 + ref.afsk(fr, amp=6000) + [0] * 4000
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(FS)
        a = array.array("h", s)
        if sys.byteorder != "little":
            a.byteswap()
        w.writeframes(a.tobytes())
    try:
        report, raw = analyze(path)
    finally:
        os.unlink(path)
    print(report)
    if raw is None:
        print("ПРОПУЩЕНО: немає C-компілятора")
        return 0
    ok = [l for l in raw.splitlines() if l.startswith("OK")]
    good = len(ok) == 1 and "UR5EAA-9>APDR16" in ok[0] and "OpenTYT R3 test 73" in ok[0]
    # перекіс рівного еталона має бути ~0 (оцінка не вигадує «twist»)
    tw = twist_short(ref.afsk(fr, amp=6000))
    tw_ok = (tw is not None) and abs(tw) < 1.5
    print("перекіс рівного еталона: %s дБ -- %s" % ("%.1f" % tw if tw is not None else "?", "гаразд" if tw_ok else "ПРОВАЛ"))
    good = good and tw_ok
    print("САМОПЕРЕВІРКА: %s (еталонний кадр, FCS 0x%04X)" % ("ПРОЙДЕНО" if good else "ПРОВАЛ", fcs))
    return 0 if good else 1


def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    ch = 0
    if "--channel" in sys.argv:
        ch = int(sys.argv[sys.argv.index("--channel") + 1])
    report, _ = analyze(sys.argv[1], ch)
    print(report)


if __name__ == "__main__":
    main()
