#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R70 A4: мутанти зняття затухання без GPS (aprs_mode.c). Кожен має валити tests/test_aprs_settings_ui.c; файл після кожного мутанта відновлюється."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, "..", "application", "source", "functions", "aprs_mode.c"))
DECAY = "	st->state = (aprsBeaconingStates_t)((uint8_t)st->state & (uint8_t)~(APRS_BEACONING_STATE_DECAY_ALGO_ENABLED));\n"
MUTANTS = [
    ("helper не знімає затухання", DECAY, ""),
    ("cfgToSettings не викликає helper", "	noGpsForce(st);\n", ""),
    ("відкриття сесії не викликає helper", "	noGpsForce(&aprsSettingsCopy);", "	((void)0);"),
    ("гілка «блока нема» не знімає затухання", "		noGpsForce(&cur);\n", ""),
]


def run():
    r = subprocess.run(["bash", os.path.join(HERE, "run_tests.sh"), "aprs_settings_ui"], capture_output=True, text=True)
    return r.returncode == 0 and "провалено: 0" in r.stdout


def main():
    orig = open(SRC, encoding="utf-8").read()
    bad = 0
    try:
        if not run():
            print("ПРОВАЛ: без мутанта тест не проходить")
            return 1
        for name, old, new in MUTANTS:
            if orig.count(old) != 1:
                print("ПРОВАЛ: мутант «%s»: фрагмент зустрічається %d раз(ів)" % (name, orig.count(old)))
                bad += 1
                continue
            open(SRC, "w", encoding="utf-8").write(orig.replace(old, new))
            if run():
                print("ПРОВАЛ: мутант «%s» НЕ піймано" % name)
                bad += 1
            else:
                print("ok: мутант «%s» піймано" % name)
    finally:
        open(SRC, "w", encoding="utf-8").write(orig)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
