#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Запис сирих відліків I2S RX з екрана «APRS проба» на ПК (R4) -> WAV + текстовий звіт.

Потрібна прошивка з ENABLE_APRS_RX_PROBE (тимчасово -- звичайна українська з CI, починаючи
з R4) і ВІДКРИТИЙ екран Налаштування -> Опції рації -> «APRS проба» на FM-каналі. Рація
підключена USB-кабелем як для CPS (той самий порт 1FC9:0094, той самий драйвер).

Протокол -- опкод CPS 'C' 0xB5 (опис формату -- aprsRxProbeUsb() у
application/source/functions/aprs_rx_probe.c):
    ['C', 0xB5, 0]                -- стан
    ['C', 0xB5, 1, режим, сек_hi, сек_lo] -- старт (режим 0 -- L, 16 біт; 1 -- L,R як у кадрі I2S)
    ['C', 0xB5, 2]                -- забрати готові блоки (по 20 мс), повторювати
    ['C', 0xB5, 3]                -- стоп
Рація НЕ зберігає запис -- віддає потоком з невеликого кільця (L -- 280 мс, L,R -- 140 мс).
Якщо ПК не встигає, блок губиться: у звіті -- кількість і номери, у WAV на його місці тиша.

ВАЖЛИВО: скрипт НЕ шле команду «показати CPS» (['C', 0]) -- вона відкрила б екран CPS на рації
і закрила б пробу.

Вжиток:
    python3 tools/aprs_capture.py                 # 15 с, канал L -> aprs_ГГГГММДД_ГГХХСС.wav
    python3 tools/aprs_capture.py -s 30 --stereo -o ~/rec.wav
Те саме -- кнопкою «Записати звук APRS (15 с)» у tools/gui_flasher.py (і у Windows .exe з CI).
Аналіз запису -- tools/aprs_offline.py.
"""
import argparse
import os
import struct
import sys
import time
import wave

APP_VID, APP_PID = 0x1FC9, 0x0094
OPCODE = 0xB5
FS = 8000
BLOCK = 160               # відліків L у блоці (20 мс)
HDR = 20                  # байтів заголовка відповіді

STATUS_TEXT = {
    0: "гаразд",
    1: "екран «APRS проба» не відкрито (Налаштування -> Опції рації -> APRS проба)",
    2: "канал не FM -- переключи рацію на аналоговий канал",
    3: "I2S не йде (немає такту WS або голосова підказка) -- зачекай секунду й спробуй ще",
    4: "запису немає",
}


class CaptureError(Exception):
    pass


def find_port():
    from serial.tools import list_ports
    for p in list_ports.comports():
        if p.vid == APP_VID and p.pid == APP_PID:
            return p.device
    return None


def _read_exact(ser, n, timeout=1.0):
    out = b""
    t0 = time.time()
    while len(out) < n:
        chunk = ser.read(n - len(out))
        if chunk:
            out += chunk
        elif time.time() - t0 > timeout:
            break
    return out


def _cmd(ser, payload):
    """Надіслати ['C', 0xB5, ...] і прочитати відповідь -> (заголовок dict, дані bytes)."""
    ser.write(bytes([ord("C"), OPCODE]) + bytes(payload))
    ser.flush()
    first = _read_exact(ser, 1)
    if not first:
        raise CaptureError("рація не відповідає (кабель? режим CPS? прошивка?)")
    if first == b"-":
        raise CaptureError("рація не знає опкоду 0xB5 -- потрібна прошивка R4 з «APRS пробою» "
                           "(звичайна українська з CI)")
    if first != b"C":
        rest = ser.read(256)
        raise CaptureError("несподівана відповідь: %s" % (first + rest).hex())
    ln = _read_exact(ser, 2)
    if len(ln) < 2:
        raise CaptureError("обірвана відповідь (довжина)")
    n = (ln[0] << 8) | ln[1]
    body = _read_exact(ser, n, timeout=2.0)
    if len(body) < n or n < HDR:
        raise CaptureError("обірвана відповідь: %d з %d Б" % (len(body), n))
    ver, status, flags, variant, nblk = struct.unpack_from("<BBBBH", body, 0)
    sent, lost = struct.unpack_from("<II", body, 6)
    total, fs = struct.unpack_from("<HH", body, 14)
    hdr = dict(ver=ver, status=status, active=bool(flags & 1), done=bool(flags & 2),
               stereo=bool(flags & 4), variant=variant, nblk=nblk, sent=sent, lost=lost,
               total=total, fs=fs)
    return hdr, body[HDR:]


def capture(seconds=15, stereo=False, port=None, log=print, progress=None):
    """Записати seconds секунд. Повертає dict: samples (list[int] або list[(l, r)]), channels,
    report (str), hdr (останній заголовок). log(str) -- журнал, progress(частка 0..1)."""
    import serial
    port = port or find_port()
    if not port:
        raise CaptureError("рацію не знайдено (USB 1FC9:0094). Підключи кабель; драйвер -- як для CPS.")
    words = (2 * BLOCK) if stereo else BLOCK
    bsize = 4 + 2 * words
    blocks = {}
    t_start = time.time()
    with serial.Serial(port, 115200, timeout=0.2) as ser:
        ser.reset_input_buffer()
        hdr, _ = _cmd(ser, [0])
        if hdr["status"] != 0:
            raise CaptureError(STATUS_TEXT.get(hdr["status"], "стан %d" % hdr["status"]))
        hdr, _ = _cmd(ser, [1, 1 if stereo else 0, (seconds >> 8) & 0xFF, seconds & 0xFF])
        if hdr["status"] != 0:
            raise CaptureError(STATUS_TEXT.get(hdr["status"], "стан %d" % hdr["status"]))
        total = hdr["total"]
        log("Запис: %d с (%d блоків по 20 мс), %s, варіант А%d, порт %s"
            % (seconds, total, "L,R" if stereo else "L", hdr["variant"], port))
        last_report = 0.0
        try:
            while True:
                hdr, data = _cmd(ser, [2])
                if hdr["status"] not in (0,):
                    raise CaptureError(STATUS_TEXT.get(hdr["status"], "стан %d" % hdr["status"]))
                for i in range(hdr["nblk"]):
                    off = i * bsize
                    seq = struct.unpack_from("<I", data, off)[0]
                    vals = struct.unpack_from("<%dh" % words, data, off + 4)
                    blocks[seq] = vals
                if progress:
                    progress(min(1.0, hdr["sent"] / float(max(1, total))))
                now = time.time()
                if now - last_report > 2.0:
                    log("  ... %d/%d блоків, втрачено %d" % (hdr["sent"], total, hdr["lost"]))
                    last_report = now
                if hdr["done"] and hdr["nblk"] == 0:
                    break
                if hdr["nblk"] == 0:
                    time.sleep(0.005)
                if now - t_start > seconds + 20:
                    raise CaptureError("запис затягнувся (рація перестала віддавати блоки)")
        except KeyboardInterrupt:
            log("перервано -- стоп")
            _cmd(ser, [3])
    return assemble(blocks, stereo, total, hdr, seconds, port, time.time() - t_start)


def assemble(blocks, stereo, total, hdr, seconds, port, elapsed):
    seqs = sorted(blocks)
    n_expected = (seqs[-1] + 1) if seqs else 0
    missing = [s for s in range(n_expected) if s not in blocks]
    zero = (0,) * ((2 * BLOCK) if stereo else BLOCK)
    flat = []
    for s in range(n_expected):
        flat.extend(blocks.get(s, zero))
    if stereo:
        samples = list(zip(flat[0::2], flat[1::2]))
        left = flat[0::2]
    else:
        samples = flat
        left = flat
    lines = []
    lines.append("APRS проба -- запис I2S RX (tools/aprs_capture.py)")
    lines.append("час: %s; порт: %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), port))
    lines.append("замовлено: %d с = %d блоків; отримано: %d блоків; пропущено номерів: %d; "
                 "рація: втрачено в кільці %d" % (seconds, total, len(blocks), len(missing), hdr["lost"]))
    if missing:
        lines.append("пропущені блоки (номер, 20 мс кожен): %s%s"
                     % (", ".join(str(m) for m in missing[:40]), " ..." if len(missing) > 40 else ""))
    lines.append("режим: %s; варіант: А%d; fs на рації: %s; тривалість передачі: %.1f с"
                 % ("L,R (як у кадрі I2S)" if stereo else "L, 16 біт", hdr["variant"],
                    ("%d Гц" % hdr["fs"]) if hdr["fs"] else "ще не виміряна", elapsed))
    if left:
        mean = sum(left) / float(len(left))
        rms = (sum((v - mean) ** 2 for v in left) / float(len(left))) ** 0.5
        lines.append("канал L: відліків %d, DC %.1f, RMS %.1f, мін %d, макс %d"
                     % (len(left), mean, rms, min(left), max(left)))
    return dict(samples=samples, channels=2 if stereo else 1, report="\n".join(lines), hdr=hdr,
                missing=missing)


def save(result, wav_path):
    with wave.open(wav_path, "wb") as w:
        w.setnchannels(result["channels"])
        w.setsampwidth(2)
        w.setframerate(FS)
        if result["channels"] == 2:
            flat = [v for pair in result["samples"] for v in pair]
        else:
            flat = result["samples"]
        w.writeframes(struct.pack("<%dh" % len(flat), *flat))
    txt = os.path.splitext(wav_path)[0] + ".txt"
    with open(txt, "w", encoding="utf-8") as f:
        f.write(result["report"] + "\n")
    return txt


def main():
    ap = argparse.ArgumentParser(description="Запис сирих відліків «APRS проби» -> WAV")
    ap.add_argument("-s", "--seconds", type=int, default=15)
    ap.add_argument("--stereo", action="store_true", help="обидва канали, як у кадрі I2S")
    ap.add_argument("-o", "--out", default=None, help="WAV (типово aprs_ДАТА_ЧАС.wav)")
    ap.add_argument("-p", "--port", default=None)
    a = ap.parse_args()
    out = a.out or time.strftime("aprs_%Y%m%d_%H%M%S.wav")
    try:
        res = capture(a.seconds, a.stereo, a.port)
    except CaptureError as e:
        sys.exit("ПОМИЛКА: %s" % e)
    txt = save(res, out)
    print(res["report"])
    print("збережено: %s і %s" % (out, txt))


if __name__ == "__main__":
    main()
