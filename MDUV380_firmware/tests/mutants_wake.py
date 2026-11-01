#!/usr/bin/env python3
"""
mutants_wake.py -- R58: мутаційна перевірка тестів журналу пробудження й вибору каналу.

Для кожного мутанта береться копія СПРАВЖНЬОГО джерела (wake_diag.c / wake_hop_sel.c), у ній
робиться одна заміна, збирається той самий тест і запускається. Мутант "вбито", якщо тест
ПРОВАЛИВСЯ під час виконання. Якщо тест пройшов -- тест нічого не ловить у цьому місці (провал
скрипта). Якщо мутант не зібрався або заміна не знайшлась рівно один раз -- теж провал
(інакше мутант "вбивається" помилкою збирання, нічого не довівши).

    python3 MDUV380_firmware/tests/mutants_wake.py
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "..", "application")
BUILD = os.path.join(HERE, ".build", "mut_wake")
CC = os.environ.get("CC", "gcc")

DIAG = ("test_wake_diag.c", "source/functions/wake_diag.c", ["-DENABLE_WAKE_DIAG"])
HOP = ("test_wake_hop.c", "source/functions/wake_hop_sel.c", ["-DENABLE_WAKE_HOP_TEST", "-DWAKE_HOP_HOST_TEST"])

# (назва, набір, що замінити, чим)
MUTANTS = [
    ("diag: prev OK -> FAIL", DIAG, "? WAKE_DIAG_PREV_OK :", "? WAKE_DIAG_PREV_FAIL :"),
    ("diag: relMs без насичення", DIAG, "(d >= (uint32_t)WAKE_DIAG_NONE)", "(d >= 0xFFFFFFFFU)"),
    ("diag: кільце на 1 більше", DIAG, "if (s_count < WAKE_DIAG_SESSIONS)", "if (s_count < WAKE_DIAG_SESSIONS + 1U)"),
    ("diag: вікно TX 20 c -> 200 c", DIAG, "< 20000U", "< 200000U"),
    ("diag: Hop не ставить HOP_START", DIAG, "s_hopPending = true;", "s_hopPending = false;"),
    ("diag: порядок байтів u16", DIAG, "*p++ = (uint8_t)v;\n\t*p++ = (uint8_t)(v >> 8);", "*p++ = (uint8_t)(v >> 8);\n\t*p++ = (uint8_t)v;"),
    ("diag: лічильник пакетів без насичення", DIAG, "if (s->pkts < 255U)", "if (s->pkts < 256U)"),
    ("diag: обрізання дампу обнуляє все", DIAG, "\t\tn--;\n", "\t\tn = 0U;\n"),
    ("diag: AWAKEN перезаписується", DIAG, "if ((s != NULL) && (s->tAwaken == WAKE_DIAG_NONE))", "if (s != NULL)"),
    ("diag: подія після закриття сеансу", DIAG, "wakeDiagSession_t *s = s_open ? curSession() : NULL;\n\n\tif (s == NULL)\n\t{\n\t\treturn;\n\t}\n\tif (s->pkts", "wakeDiagSession_t *s = curSession();\n\n\tif (s == NULL)\n\t{\n\t\treturn;\n\t}\n\tif (s->pkts"),
    ("hop: ліміт стрибків <=", HOP, "hopsDone < WAKE_HOP_MAX_HOPS", "hopsDone <= WAKE_HOP_MAX_HOPS"),
    ("hop: FORCE_DMO дозволено", HOP, "(c->forceDmo == false) && ", ""),
    ("hop: лише-приймання дозволено", HOP, "(c->rxOnly == false) && ", ""),
    ("hop: заблоковану рацію дозволено", HOP, "(c->inhibited == false) && ", ""),
    ("hop: rx == tx дозволено", HOP, " && (c->rxFreq != c->txFreq)", ""),
    ("hop: більше одного оберту", HOP, "unsigned steps = count - 1U;", "unsigned steps = count;"),
    ("hop: ліміт сканування +1", HOP, "steps = WAKE_HOP_SCAN_CAP;", "steps = WAKE_HOP_SCAN_CAP + 1U;"),
    ("hop: кільце без обертання", HOP, "(start + k) % count", "(start + k) % (count + 1U)"),
]


def run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)


def build_and_run(test, src_path, flags, tag):
    os.makedirs(BUILD, exist_ok=True)
    exe = os.path.join(BUILD, tag)
    cmd = [CC, "-O2", "-std=gnu11", "-DENABLE_AES", "-DENABLE_DMR_DATA"] + flags + [
        "-I", os.path.join(APP, "include"), "-I", os.path.join(APP, "include", "crypto"),
        "-o", exe, os.path.join(HERE, test), src_path]
    b = run(cmd)
    if b.returncode != 0:
        return None, b.stdout
    r = run([exe])
    return r.returncode, r.stdout


def main():
    bad = 0

    # 1. Контроль: немутований код проходить.
    for test, rel, flags in (DIAG, HOP):
        rc, out = build_and_run(test, os.path.join(APP, rel), flags, "orig_" + test)
        if rc != 0:
            print("ПРОВАЛ  контроль %s: rc=%s\n%s" % (test, rc, (out or "")[-600:]))
            bad += 1

    # 2. Мутанти.
    for i, (name, (test, rel, flags), old, new) in enumerate(MUTANTS):
        text = open(os.path.join(APP, rel), encoding="utf-8").read()
        if text.count(old) != 1:
            print("ПРОВАЛ  [%s] шаблон заміни знайдено %d разів (треба рівно 1)" % (name, text.count(old)))
            bad += 1
            continue
        mpath = os.path.join(BUILD, "mut%02d_%s" % (i, os.path.basename(rel)))
        os.makedirs(BUILD, exist_ok=True)
        open(mpath, "w", encoding="utf-8").write(text.replace(old, new))
        rc, out = build_and_run(test, mpath, flags, "mut%02d" % i)
        if rc is None:
            print("ПРОВАЛ  [%s] мутант не зібрався:\n%s" % (name, out[-600:]))
            bad += 1
        elif rc == 0:
            print("ПРОВАЛ  [%s] мутант ВИЖИВ -- тест його не ловить" % name)
            bad += 1
        else:
            print("ok      [%s] вбито" % name)

    print("Мутантів: %d, проблем: %d" % (len(MUTANTS), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
