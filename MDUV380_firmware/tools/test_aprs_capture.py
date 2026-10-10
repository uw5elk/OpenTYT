#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Самоперевірка tools/aprs_capture.py (R4) без рації: підставний «serial», що відповідає на
опкод 0xB5 так, як описано в aprsRxProbeUsb() (application/source/functions/aprs_rx_probe.c),
з пропущеним блоком посередині. Перевіряє розбір відповідей, склеювання за номерами блоків,
тишу на місці пропуску, WAV і звіт. pyserial не потрібен.
"""
import os
import struct
import sys
import tempfile
import types
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

BLOCK = 160


class FakeRadio:
    """Поводиться як рація з відкритою «APRS пробою»: блоки -- пилка зі зростаючим зсувом."""

    def __init__(self, port=None, baud=None, timeout=None):
        self.out = b""
        self.total = 0
        self.sent = 0
        self.stereo = False
        self.lost = 0
        self.active = False
        self.done = False
        self.next_seq = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def reset_input_buffer(self):
        self.out = b""

    def flush(self):
        pass

    def _block(self, seq):
        if self.stereo:
            vals = []
            for i in range(BLOCK):
                vals += [seq * 10 + (i % 7), -(seq * 10 + (i % 7))]
        else:
            vals = [seq * 10 + (i % 7) for i in range(BLOCK)]
        return struct.pack("<I", seq) + struct.pack("<%dh" % len(vals), *vals)

    def write(self, data):
        assert data[0] == ord("C") and data[1] == 0xB5, data
        sub = data[2]
        blocks = b""
        nblk = 0
        if sub == 1:
            self.stereo = bool(data[3] & 1)
            self.total = ((data[4] << 8) | data[5]) * 50
            self.sent = 0
            self.active, self.done = True, False
        elif sub == 2 and self.active:
            for _ in range(3):
                if self.sent >= self.total:
                    break
                seq = self.next_seq
                self.next_seq += 1
                if seq == 7:          # рація загубила блок 7 (кільце переповнилось)
                    self.lost += 1
                    seq = self.next_seq
                    self.next_seq += 1
                blocks += self._block(seq)
                nblk += 1
                self.sent += 1
            if self.sent >= self.total:
                self.active, self.done = False, True
        elif sub == 3:
            self.active, self.done = False, True
        flags = (1 if self.active else 0) | (2 if self.done else 0) | (4 if self.stereo else 0)
        body = struct.pack("<BBBBHIIHHH", 1, 0, flags, 1, nblk, self.sent, self.lost, self.total, 8000, 0) + blocks
        self.out += bytes([ord("C"), (len(body) >> 8) & 0xFF, len(body) & 0xFF]) + body

    def read(self, n):
        r, self.out = self.out[:n], self.out[n:]
        return r


def main():
    fake = types.ModuleType("serial")
    fake.Serial = FakeRadio
    sys.modules["serial"] = fake
    import aprs_capture as cap

    fails = 0
    for stereo in (False, True):
        res = cap.capture(2, stereo=stereo, port="FAKE", log=lambda t: None)
        ch = 2 if stereo else 1
        n_blocks = len(res["samples"]) // BLOCK
        # 100 блоків замовлено; рація пропустила номер 7, тож останній номер -- 100
        ok = (n_blocks == 101) and (res["missing"] == [7]) and ("пропущено номерів: 1" in res["report"])
        first = res["samples"][7 * BLOCK]
        ok = ok and (first == ((0, 0) if stereo else 0))
        after = res["samples"][8 * BLOCK]
        ok = ok and (after == ((80, -80) if stereo else 80))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.wav")
            txt = cap.save(res, path)
            with wave.open(path, "rb") as w:
                ok = ok and w.getnchannels() == ch and w.getframerate() == 8000 and w.getnframes() == 101 * BLOCK
            ok = ok and os.path.exists(txt)
        print("  %s  %s: блоків %d, пропущено %s" % ("ok  " if ok else "FAIL", "L,R" if stereo else "L", n_blocks, res["missing"]))
        fails += 0 if ok else 1
    print("ПРОЙДЕНО" if fails == 0 else "ПРОВАЛЕНО: %d" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
