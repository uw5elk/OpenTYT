#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R77A (хост, без заліза): «Гучн. проба» не потрапляє в основну збірку й не чіпає зайвого. Перевіряє ВИХІДНИЙ КОД (логіку екрана перевіряє
tests/test_volume_probe.c зі справжнім volume_probe.c):
  1  усі згадки volumeProbe*/volumeProbeDmrShift у sound.c, trx.c, menuSystem.c, menuRadioOptions.c -- лише всередині #if ...VOLUME_PROBE...;
  2  у build.yml ENABLE_VOLUME_PROBE є ЛИШЕ в задачі build-ukrainian-volprobe (не в build-ukrainian і не в інших);
  3  множник DMR стоїть ПІСЛЯ АРУ: пік для АРУ береться з swapper.byte16 (до множення), а ослаблення застосовується до результату;
  4  volume_probe.c пише лише регістр 0x44 із високим байтом 0x06 (VP_FM_HIGH) через наявну radioWriteReg2byte; жодного прямого SPI/I2C, жодного DMR-значення;
  5  нічого не зберігається: у volume_probe.c, menuVolumeProbe.c нема settings*/EEPROM/flash/custom-data;
  6  volprobe_ua.h -- cp1251 (не UTF-8), у кожного нового мовного рядка довжина <= 16 символів з найгіршими підстановками (R77B; на фото рації обрізались довші);
  7  Makefile: прапорець лише додає -DENABLE_VOLUME_PROBE.
Запуск: python3 tools/test_r77a.py"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HERE)
APP = os.path.join(FW, "application")
FAILS = []
N = [0]


def check(c, m):
    N[0] += 1
    if not c:
        FAILS.append(m)
        print("ПРОВАЛ:", m)


def rd(p, enc="utf-8"):
    with open(p, encoding=enc, errors="surrogateescape") as f:
        return f.read()


def guarded_lines(text, needle_re):
    """Рядки, що збігаються з needle_re, але стоять поза будь-яким #if, що містить VOLUME_PROBE."""
    stack = []
    bad = []
    for i, line in enumerate(text.split("\n"), 1):
        s = line.strip()
        if re.match(r"#\s*if", s):
            stack.append("VOLUME_PROBE" in s)
        elif re.match(r"#\s*else", s):
            pass            # гілка #else -- вже НЕ під прапорцем
            if stack:
                stack[-1] = False
        elif re.match(r"#\s*endif", s):
            if stack:
                stack.pop()
        if re.search(needle_re, line) and not any(stack):
            if not re.match(r"\s*(//|/\*|\*)", line) and not s.startswith("#include"):
                bad.append((i, s))
    return bad


def main():
    needle = r"volumeProbe|vpDmrApply"
    for rel in ("source/functions/sound.c", "source/functions/trx.c", "source/user_interface/menuSystem.c", "source/user_interface/menuRadioOptions.c"):
        t = rd(os.path.join(APP, rel))
        bad = guarded_lines(t, needle)
        check(not bad, "%s: згадки volumeProbe поза #if VOLUME_PROBE: %r" % (rel, bad[:3]))
        check(re.search(needle, t) is not None, "%s: хук R77A на місці" % rel)
    # мутант перевірки 1
    check(guarded_lines("void f(void)\n{\n\tvolumeProbeClose();\n}\n", needle) != [], "мутант: виклик без #if ловиться")

    # 2: build.yml
    y = rd(os.path.join(os.path.dirname(FW), ".github", "workflows", "build.yml"))
    jobs = re.split(r"\n  (?=[A-Za-z0-9_-]+:\n    )", y)
    with_flag = [j.split(":", 1)[0].strip() for j in jobs if "ENABLE_VOLUME_PROBE" in re.sub(r"(?m)^\s*#.*$", "", j)]
    check(with_flag == ["build-ukrainian-volprobe"], "build.yml: ENABLE_VOLUME_PROBE лише в build-ukrainian-volprobe (є: %r)" % with_flag)

    # 3: після АРУ
    s = rd(os.path.join(APP, "source/functions/sound.c"))
    i = s.index("#if defined(VOLUME_PROBE)\n				// R77A")
    blk = s[i:i + 900]
    check("swapper.byte16 * dmrRxAgcGain" in blk and "vpDmrApply(out, volumeProbeDmrShift)" in blk, "sound.c: множник застосовується до результату АРУ")
    check("samp = abs(swapper.byte16);" in s[i:i + 1600], "sound.c: пік для АРУ береться з вхідного відліку (до множення)")
    check("dmrRxAgcGain *= " in s and "probe" not in s[s.index("dmrRxAgcGain  = DMR_RX_AGC_DEFAULT_PEAK_SAMPLES"):s.index("dmrRxAgcGain  = DMR_RX_AGC_DEFAULT_PEAK_SAMPLES") + 300],
          "sound.c: сам розрахунок АРУ про пробу не знає")
    check("voicePromptsIsPlaying() == false" in s[s.index("const bool probeAttenuate"):s.index("const bool probeAttenuate") + 300], "sound.c: підказки/мелодії не ослаблюються")

    # 4, 5: volume_probe.c
    v = rd(os.path.join(APP, "source/functions/volume_probe.c"))
    code = "\n".join(l for l in v.split("\n") if not l.strip().startswith(("//", "/*", "*")))
    writes = re.findall(r"radioWriteReg2byte\(([^;]*)\);", code)
    check(len(writes) >= 3 and all(w.startswith("VP_FM_REG, VP_FM_HIGH, ") for w in writes), "volume_probe.c: усі записи -- 0x44 з високим байтом 0x06: %r" % writes)
    check(not re.search(r"SPI0|I2C|HAL_|0x07|0xFF\b|AT1846sWrite|trxSetModeAndBandwidth", code), "volume_probe.c: нема прямого запису в кодек і DMR-значень")
    for rel in ("source/functions/volume_probe.c", "source/user_interface/menuVolumeProbe.c"):
        c = rd(os.path.join(APP, rel))
        c = "\n".join(l for l in c.split("\n") if not l.strip().startswith(("//", "/*", "*")))
        check(not re.search(r"settingsSet|settingsSave|nonVolatileSettings|EEPROM|flash|custom_?[dD]ata|SPI_Flash", c), "%s: нічого не зберігається" % rel)

    # 6: рядки
    raw = open(os.path.join(APP, "include/user_interface/languages/volprobe_ua.h"), "rb").read()
    ok_utf8 = True
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        ok_utf8 = False
    check(not ok_utf8, "volprobe_ua.h не є UTF-8 (cp1251)")
    txt = raw.decode("cp1251")
    check("Гучн. проба" in txt, "volprobe_ua.h читається як cp1251")
    for m in re.finditer(r'#define (VOLPROBE_\w+)\s+"([^"]*)"', txt):
        name, val = m.groups()
        # R77B: межа 16 символів (на фото рації обрізались рядки довші за ~16-17); найгірший випадок підстановок: %c 1, %s 4, %d/%u 3, %02X 2
        plain = re.sub(r"%[-+0-9.]*[a-zA-Z%]", lambda mm: {"c": "x", "s": "xxxx", "X": "xx", "%": "%"}.get(mm.group(0)[-1], "999"), val)
        if name not in ("VOLPROBE_MENU_NAME", "VOLPROBE_MENU_ENTER"):
            check(len(plain) <= 16, "%s: %d символів (> 16): %r" % (name, len(plain), val))

    # 7: Makefile
    mk = rd(os.path.join(FW, "Makefile"))
    check(re.search(r"ifeq \(\$\(ENABLE_VOLUME_PROBE\),1\)\nDEFS \+= -DENABLE_VOLUME_PROBE\nendif", mk) is not None, "Makefile: прапорець лише додає -DENABLE_VOLUME_PROBE")

    if FAILS:
        print("test_r77a: %d провалів" % len(FAILS))
        return 1
    print("test_r77a: усе гаразд (%d перевірок)" % N[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
