#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R78 (хост, без заліза): «Мін.гучність» (ENABLE_VOLUME_LOW) не потрапляє в збірки без прапорця й не чіпає зайвого. Перевіряє ВИХІДНИЙ КОД (крива й захисти --
tests/test_volume_low.c зі справжнім volume_low.c):
  1  усі згадки volumeLow*/vl*/VOLLOW_ у sound.c, trx.c, applicationMain.c -- лише всередині #if ...VOLUME_LOW...;
  2  build.yml: ENABLE_VOLUME_LOW=1 у КОЖНОМУ make-рядку користувацької української збірки (там, де ENABLE_SAT_TONE_SYNC=1), і лише там;
  3  Makefile: прапорець лише додає -DENABLE_VOLUME_LOW; syntax_check.sh має конфігурації з прапорцем;
  4  блок: номер 17 однаковий у codeplug.h, custom_region.BLOCK_TYPES (налаштування), doc_region.DOC_TYPES; довжина 1 байт; жодних змін nonVolatileSettings;
  5  таблиці в заголовку збігаються з формулами (DMR Q15 за 10^(-x/20); FM low-byte за 0xCC·10^(-x/20), не нижче 0x0F);
  6  sound.c: множник DMR ПІСЛЯ АРУ, пік для АРУ -- з вхідного відліку; підказки/мелодії/«Переслухати» не ослаблюються; рампа;
  7  volume_low.c: єдиний шлях запису в кодек -- radioWriteReg2byte(0x44, 0x06, ...); жодного DMR-значення, SPI/I2C напряму; блок пишеться лише через custom-data;
  8  R81: vollow_ua.h і рядків «Мін.гучн.» немає ніде (пункт меню прибрано, режим фіксований K = 16);
  9  збірка без ENABLE_VOLUME_LOW: токени препроцесора (gcc -E -P) sound.c, trx.c, applicationMain.c, codeplug.c збігаються з комітом R77B у усіх конфігураціях.
  10 R81: режим фіксований K = 16 (VOLLOW_FIXED_MODE = 2, vlEffectiveMode, Load не читає блок 17) + мутанти.
Запуск: python3 tools/test_r78.py   (база для 9: коміт з темою «R77B:», або змінна R78_BASE)"""
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HERE)
APP = os.path.join(FW, "application")
sys.path.insert(0, HERE)
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
    """Рядки з needle_re поза будь-яким #if, що містить VOLUME_LOW."""
    stack = []
    bad = []
    for i, line in enumerate(text.split("\n"), 1):
        s = line.strip()
        if re.match(r"#\s*if", s):
            stack.append("VOLUME_LOW" in s)
        elif re.match(r"#\s*else", s):
            if stack:
                stack[-1] = False
        elif re.match(r"#\s*endif", s):
            if stack:
                stack.pop()
        if re.search(needle_re, line) and not any(stack):
            if not re.match(r"\s*(//|/\*|\*)", line) and not s.startswith("#include"):
                bad.append((i, s))
    return bad


def find_base():
    if os.environ.get("R78_BASE"):
        return os.environ["R78_BASE"]
    if not shutil.which("git"):
        return None
    r = subprocess.run(["git", "-C", FW, "log", "--format=%H", "--grep=^R77B:", "-1"], capture_output=True, text=True)
    return r.stdout.strip() or None


def tokens_of(root, rel, incs, defs):
    r = subprocess.run(["gcc", "-E", "-P", "-std=gnu11", "-w"] + incs + defs + [rel], cwd=root, capture_output=True)
    if r.returncode != 0:
        return None
    # R82: два нові UA-поля в кінці stringsTable_t (channels_protect, satellite_mode) законно змінюють токени файлів, що підключають uiLanguage.h; вирізаємо їх (їх перевіряє test_r82.py)
    out = r.stdout.replace(b"const char channels_protect[17];", b"").replace(b"const char satellite_mode[17];", b"").replace(b"const char talkaround_menu[17];", b"").replace(b"const char talker_beep[17];", b"").replace(b"const char contact_lines[17];", b"").replace(b"const char contact_order_0[17];", b"").replace(b"const char contact_order_1[17];", b"").replace(b"const char contact_order_2[17];", b"").replace(b"const char contact_order_3[17];", b"")
    return out.split()


def main():
    needle = r"volumeLow|vlKnee|vlExtraDb|vlRamp|vlApply|vlDmrGain|VOLLOW_|s_volumeLowGain|dmrAttenuate"
    for rel in ("source/functions/sound.c", "source/functions/trx.c", "source/applicationMain.c"):
        t = rd(os.path.join(APP, rel))
        bad = guarded_lines(t, needle)
        check(not bad, "%s: згадки R78 поза #if VOLUME_LOW: %r" % (rel, bad[:3]))
        check(re.search(needle, t) is not None, "%s: хук R78 на місці" % rel)
    # R81: пункту меню немає ні в «Опціях рації», ні в жодному іншому меню/мовному файлі
    for dp, _, fs in os.walk(os.path.join(APP, "source", "user_interface")):
        for f in fs:
            if f.endswith(".c"):
                t = rd(os.path.join(dp, f))
                check(re.search(needle + r"|VOLUME_LOW|VOL_LOW|volume_low", t) is None, "R81: %s не містить згадок «Мін.гучність» (пункту меню немає)" % f)
    check(guarded_lines("void f(void)\n{\n\tvolumeLowTick();\n}\n", needle) != [], "мутант: виклик без #if ловиться")

    # 2: build.yml
    y = rd(os.path.join(os.path.dirname(FW), ".github", "workflows", "build.yml"))
    lines = [l for l in y.split("\n") if "make " in l and "LANGUAGE_UKRAINIAN=1" in l]
    user = [l for l in lines if "ENABLE_SAT_TONE_SYNC=1" in l]
    check(len(user) >= 3 and all("ENABLE_VOLUME_LOW=1" in l for l in user), "build.yml: ENABLE_VOLUME_LOW=1 у кожному make-рядку користувацької збірки (%d)" % len(user))
    check(all(("ENABLE_VOLUME_LOW=1" not in l) for l in lines if "ENABLE_SAT_TONE_SYNC=1" not in l), "build.yml: прапорця нема в інших make-рядках")
    check(not any("ENABLE_VOLUME_LOW" in l for l in y.split("\n") if "make " in l and "LANGUAGE_UKRAINIAN=1" not in l), "build.yml: прапорця нема в неукраїнських збірках")

    # 3: Makefile, syntax_check
    mk = rd(os.path.join(FW, "Makefile"))
    check(re.search(r"ifeq \(\$\(ENABLE_VOLUME_LOW\),1\)\nDEFS \+= -DENABLE_VOLUME_LOW\nendif", mk) is not None, "Makefile: прапорець лише додає -DENABLE_VOLUME_LOW")
    sc = rd(os.path.join(HERE, "syntax_check.sh"))
    check("-DENABLE_VOLUME_LOW" in sc and "VOLLOWEN" in sc and "VOLLOWBARE" in sc and "VOLLOWAPRS" in sc, "syntax_check.sh: конфігурації з ENABLE_VOLUME_LOW")

    # 4: блок 17
    import custom_region as cr
    import doc_region as dr
    h = rd(os.path.join(APP, "include/functions/codeplug.h"))
    check(re.search(r"#if defined\(ENABLE_VOLUME_LOW\)\s*\n\s*CODEPLUG_CUSTOM_DATA_TYPE_VOLUME_LOW_CFG = 17,", h) is not None, "codeplug.h: тип 17 під ENABLE_VOLUME_LOW, номер явний")
    check(cr.BLOCK_TYPES.get(17, (None,))[0] == "VOLUME_LOW_CFG" and cr.BLOCK_TYPES[17][4] == "setting", "custom_region: тип 17 -- VOLUME_LOW_CFG, налаштування")
    check(dr.TYPE_VOLUME_LOW_CFG == 17 and 17 in dr.DOC_TYPES and 17 in dr.DOC_TITLES and 17 not in dr.NEVER_TYPES, "doc_region: тип 17 у документі, з назвою")
    vl = rd(os.path.join(APP, "source/functions/volume_low.c"))
    check("CODEPLUG_CUSTOM_DATA_TYPE_VOLUME_LOW_CFG" not in re.sub(r"/\*.*?\*/", "", vl, flags=re.S) and "codeplugSetOpenGD77CustomData" not in vl, "R81: volume_low.c блок 17 не читає і не пише (значення не діє)")
    code = "\n".join(l for l in vl.split("\n") if not l.strip().startswith(("//", "/*", "*")))
    check(not re.search(r"nonVolatileSettings|settingsSet|settingsSave|SPI_Flash|EEPROM", code), "volume_low.c: розкладку nonVolatileSettings не чіпає")

    # 5: таблиці
    lg = rd(os.path.join(APP, "include/functions/volume_low_logic.h"))
    g = [int(x) for x in re.findall(r"(\d+)U", re.search(r"static const uint16_t g\[[^\]]*\] = \{(.*?)\};", lg, re.S).group(1))]
    l = [int(x) for x in re.findall(r"(\d+)U", re.search(r"static const uint8_t l\[[^\]]*\] = \{(.*?)\};", lg, re.S).group(1))]
    check(g == [int(math.floor(32768 * 10 ** (-x / 20.0) + 0.5)) for x in range(37)], "таблиця DMR Q15 == round(32768*10^(-x/20)), 37 значень")
    check(l == [max(int(math.floor(204 * 10 ** (-x / 20.0) + 0.5)), 15) for x in range(24)], "таблиця FM low-byte == round(0xCC*10^(-x/20)) не нижче 0x0F, 24 значення")
    check(l[0] == 0xCC and l[-1] == 0x0F and min(l) == 0x0F and g[36] == 519, "краї таблиць: 0xCC..0x0F, Q15 [36] = 519")

    # 6: sound.c
    s = rd(os.path.join(APP, "source/functions/sound.c"))
    i = s.index("#if defined(VOLUME_PROBE) || defined(VOLUME_LOW)\n				// R77A/R78")
    blk = s[i:i + 1700]
    check("swapper.byte16 * dmrRxAgcGain" in blk and blk.index("swapper.byte16 * dmrRxAgcGain") < blk.index("vlApply(out, s_volumeLowGain)"), "sound.c: множник R78 застосовується до результату АРУ")
    check("vlRamp(s_volumeLowGain, volumeLowDmrGainQ15)" in blk, "sound.c: рампа до цілі")
    check("samp = abs(swapper.byte16);" in s[i:i + 2600], "sound.c: пік для АРУ -- з вхідного відліку")
    d = s.index("const bool dmrAttenuate")
    check("voicePromptsIsPlaying() == false" in s[d:d + 300] and "soundMelodyIsPlaying() == false" in s[d:d + 300] and "callReplayIsPlaying() == false" in s[d:d + 400], "sound.c: підказки, мелодії, «Переслухати» не ослаблюються")
    check("dmrAttenuate" in blk, "sound.c: умова dmrAttenuate використана")

    # 7: запис у кодек
    writes = re.findall(r"radioWriteReg2byte\(([^;]*)\);", code)
    check(len(writes) >= 3 and all(w.startswith("VOLLOW_FM_REG, VOLLOW_FM_HIGH, ") for w in writes), "volume_low.c: усі записи -- 0x44 з високим байтом 0x06: %r" % writes)
    check(not re.search(r"SPI0|I2C|HAL_|0x07|AT1846sWrite|trxSetModeAndBandwidth", code), "volume_low.c: нема прямого запису в кодек і DMR-значень")
    check("trxTransmissionEnabled" in code and "aprsRxIsRunning" in code and "volumeProbeIsOn" in code and "USB_MODE_CPS" in code, "volume_low.c: захисти (TX, APRS, проба, хотспот) на місці")
    tr = rd(os.path.join(APP, "source/functions/trx.c"))
    check(tr.count("volumeLowStopForTx();") == 2, "trx.c: volumeLowStopForTx() і в trxSetTX(), і в trxActivateTx()")
    am = rd(os.path.join(APP, "source/applicationMain.c"))
    check("volumeLowPotSettled(lastVolume);" in am[am.index("static void updateVolumeGain"):am.index("static void updateVolumeGain") + 400], "applicationMain.c: перерахунок у updateVolumeGain() -- у той самий момент, що й стокове підсилення")
    check(am.count("volumeLowTick();") == 1 and am.count("volumeLowLoad();") == 1, "applicationMain.c: Tick у циклі й Load на старті по одному разу")

    # 8 (R81): рядків «Мін.гучн.» немає ніде; vollow_ua.h прибрано
    check(not os.path.exists(os.path.join(APP, "include/user_interface/languages/vollow_ua.h")), "R81: vollow_ua.h прибрано")
    for dp, _, fs in os.walk(APP):
        for f in fs:
            if f.endswith((".c", ".h")):
                data = open(os.path.join(dp, f), "rb").read()
                for enc in ("utf-8", "cp1251"):
                    try:
                        txt = data.decode(enc)
                        break
                    except UnicodeDecodeError:
                        continue
                check(re.search(r'"[^"\n]*Мін\.гучн\.[^"\n]*"', txt) is None, "R81: рядкового літерала пункту «Мін.гучн.» немає у %s" % f)

    # 10 (R81): режим ФІКСОВАНИЙ K = 16 -- вихідний код і мутанти
    lgc = rd(os.path.join(APP, "include/functions/volume_low_logic.h"))

    def fixed_k_ok(logic, vlc):
        m = re.search(r"#define VOLLOW_FIXED_MODE\s+(\d+)U", logic)
        k = re.search(r"static const uint8_t k\[VOLLOW_MODES\] = \{([^}]*)\}", logic)
        e = re.search(r"static inline uint8_t vlEffectiveMode\(uint8_t raw\)\s*\{(.*?)\}", logic, re.S)
        ld = re.search(r"void volumeLowLoad\(void\)\s*\{(.*?)\n\}", vlc, re.S)
        if not (m and k and e and ld):
            return False
        ks = [int(x) for x in re.findall(r"(\d+)U", k.group(1))]
        return (int(m.group(1)) == 2 and ks[2] == 16 and "return VOLLOW_FIXED_MODE;" in e.group(1) and "raw" not in re.sub(r"\(void\)raw;", "", e.group(1))
                and "s_mode = vlEffectiveMode(" in ld.group(1) and "codeplugGet" not in ld.group(1))
    check(fixed_k_ok(lgc, vl), "R81: K = 16 (режим 2) зашито; Load не читає блок")
    check(not fixed_k_ok(lgc.replace("VOLLOW_FIXED_MODE       2U", "VOLLOW_FIXED_MODE       1U"), vl), "мутант: K 8 ловиться")
    check(not fixed_k_ok(lgc.replace("{ 0U, 8U, 16U, 24U }", "{ 0U, 8U, 12U, 24U }"), vl), "мутант: крива/коліно не 16 ловиться")
    check(not fixed_k_ok(lgc.replace("return VOLLOW_FIXED_MODE;", "return raw;"), vl), "мутант: режим береться з блока ловиться")
    check(not fixed_k_ok(lgc, vl.replace("s_mode = vlEffectiveMode(0U);", "s_mode = vlModeSanitize(raw);")), "мутант: Load читає значення блока ловиться")
    check(re.search(r"VOLLOW_DEPTH_DMR_DB\s+36U", lgc) and re.search(r"VOLLOW_DEPTH_FM_DB\s+23U", lgc) and re.search(r"VOLLOW_FM_FLOOR_LOW\s+0x0FU", lgc), "R81: D_DMR 36, D_FM 23, підлога 0x0F не змінились")
    check(not re.search(r"VOLLOW_DEPTH_DMR_DB\s+36U", lgc.replace("36U", "30U")), "мутант: D_DMR != 36 ловиться")

    # 9: збірки без прапорця не змінились
    base = find_base()
    if not base or not shutil.which("gcc"):
        print("test_r78: бази R77B нема (або нема gcc) -- пункт 9 пропущено (задай R78_BASE)")
    else:
        import check_menu_tables as cmt
        incs, cfgs = cmt.load_configs(FW)
        root = tempfile.mkdtemp(prefix="r78_base_")
        try:
            tar = subprocess.run(["git", "-C", FW, "archive", base, "application"], capture_output=True)
            if tar.returncode != 0:
                print("test_r78: git archive не вдався -- пункт 9 пропущено")
            else:
                subprocess.run(["tar", "-x", "-C", root], input=tar.stdout, check=True)
                for entry in os.listdir(FW):
                    if entry != "application" and not os.path.exists(os.path.join(root, entry)):
                        os.symlink(os.path.join(FW, entry), os.path.join(root, entry))
                n = 0
                for name, defs in cfgs:
                    nd = [x for x in defs if x != "-DENABLE_VOLUME_LOW"]
                    for rel in ("source/functions/sound.c", "source/functions/trx.c", "source/applicationMain.c", "source/functions/codeplug.c"):   # R81: menuRadioOptions.c змінено свідомо (пункти прибрано) -- його перевіряє test_r81.py
                        if rel.endswith("applicationMain.c") and "-DLANGUAGE_BUILD_UKRAINIAN" in defs:
                            continue       # R91A: «Гучність» (картка гучності) в українській збірці завжди On -- макрос SETTINGS_VISUAL_VOLUME_EFFECTIVE() законно змінює токени; перевіряє test_r91a
                        if rel.endswith("sound.c") and "-DENABLE_VOLUME_PROBE" in defs:
                            continue       # діагностична збірка: блок R77A у sound.c законно спільний із R78 (перероблено в один; поведінку проби перевіряє test_volume_probe)
                        p = os.path.join("application", rel)
                        a, b = tokens_of(FW, p, incs, nd), tokens_of(root, p, incs, nd)
                        if a is None and b is None:
                            continue
                        n += 1
                        check(a is not None and a == b, "конфігурація %s, %s -- без ENABLE_VOLUME_LOW токени збігаються з %s" % (name, rel, base[:7]))
                check(n > 100, "порівняно достатньо пар файл/конфігурація (%d)" % n)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    if FAILS:
        print("test_r78: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
        return 1
    print("test_r78: усе гаразд (%d перевірок)" % N[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
