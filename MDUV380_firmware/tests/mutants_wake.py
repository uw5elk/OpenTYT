#!/usr/bin/env python3
"""
mutants_wake.py -- R58/R59: мутаційна перевірка тестів журналу пробудження, вибору каналу зі списку роумінгу й формату блоку налаштувань.

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
HOP = ("test_wake_hop.c", "source/functions/wake_hop_sel.c", ["-DENABLE_ROAM_RETRY", "-DWAKE_HOP_HOST_TEST", "-DROAM_CFG_HOST_TEST"])
CFG = ("test_roam_cfg.c", "source/functions/roam_cfg.c", ["-DENABLE_ROAM_RETRY", "-DROAM_CFG_HOST_TEST"])

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
    # --- R59: вибір зі списку роумінгу ---
    ("hop: без ліміту стрибків", HOP, "return (hopsDone < lim);", "return true;"),
    ("hop: ліміт стрибків <=", HOP, "return (hopsDone < lim);", "return (hopsDone <= lim);"),
    ("hop: ліміт без верхньої межі 5", HOP, "if (lim > ROAM_HOPS_MAX)\n\t{\n\t\tlim = ROAM_HOPS_MAX;\n\t}", ""),
    ("hop: без дублікатів (rx,tx,cc) -- Has завжди false", HOP, "\t\tif ((t->rx[i] == rx) && (t->tx[i] == tx) && (t->cc[i] == cc))", "\t\tif (false)"),
    ("hop: дублікат без колір-коду", HOP, " && (t->cc[i] == cc))", ")"),
    ("hop: CandidateOk не дивиться на випробуваних", HOP, " && (wakeHopTriedHas(t, c->rxFreq, c->txFreq, c->colourCode) == false));", ");"),
    ("hop: CandidateOk без перевірки придатності", HOP, "return (wakeHopChannelUsable(c) && (wakeHopTriedHas", "return (true && (wakeHopTriedHas"),
    ("hop: FORCE_DMO дозволено", HOP, "(c->forceDmo == false) && ", ""),
    ("hop: лише-приймання дозволено", HOP, "(c->rxOnly == false) && ", ""),
    ("hop: заблоковану рацію дозволено", HOP, "(c->inhibited == false) && ", ""),
    ("hop: rx == tx дозволено", HOP, " && (c->rxFreq != c->txFreq)", ""),
    ("hop: аналоговий дозволено", HOP, "return (c->digital && ", "return (true && "),
    ("hop: заборону передачі ігноруємо", HOP, "c->txAllowed &&\n", "true &&\n"),
    ("hop: поза діапазоном дозволено", HOP, "c->inBand && ", "true && "),
    ("hop: більше одного оберту", HOP, "for (unsigned k = 1U; k < span; k++)", "for (unsigned k = 1U; k <= span; k++)"),
    ("hop: на один оберт менше", HOP, "for (unsigned k = 1U; k < span; k++)", "for (unsigned k = 1U; k < (span - 1U); k++)"),
    ("hop: кільце без обертання", HOP, "(((startNum - minNum) + k) % span)", "(((startNum - minNum) + k) % (span + 1U))"),
    ("hop: порядок за спаданням", HOP, "minNum + (((startNum - minNum) + k) % span)", "minNum + (((startNum - minNum) + (span - k)) % span)"),
    ("hop: роум, коли поточний НЕ в списку", HOP, "return (cfgEnabled && (currentList >= 1U) && (currentList <= ROAM_LISTS_COUNT));", "return cfgEnabled;"),
    ("hop: роум, коли функція вимкнена", HOP, "return (cfgEnabled && (currentList >= 1U) && (currentList <= ROAM_LISTS_COUNT));", "return ((currentList >= 1U) && (currentList <= ROAM_LISTS_COUNT));"),
    ("hop: роум для списку 11+", HOP, "return (cfgEnabled && (currentList >= 1U) && (currentList <= ROAM_LISTS_COUNT));", "return (cfgEnabled && (currentList >= 1U));"),
    # --- R60: 10 списків ---
    ("list: ігнорувати номер списку (кандидат із чужого)", HOP, "return ((curList >= 1U) && (curList <= ROAM_LISTS_COUNT) && (curList == candList));", "return ((curList >= 1U) && (curList <= ROAM_LISTS_COUNT));"),
    ("list: працювати для списку 0", HOP, "return ((curList >= 1U) && (curList <= ROAM_LISTS_COUNT) && (curList == candList));", "return (curList == candList);"),
    ("list: збіг без перевірки поточного 1..10", HOP, "return ((curList >= 1U) && (curList <= ROAM_LISTS_COUNT) && (curList == candList));", "return ((curList >= 1U) && (curList == candList));"),
    ("list: збіг за 'не більше', а не рівність", HOP, "(curList == candList));", "(curList <= candList));"),
    ("list: збіг завжди false", HOP, "return ((curList >= 1U) && (curList <= ROAM_LISTS_COUNT) && (curList == candList));", "return false;"),
    # --- R60: формат байта списку ---
    ("list-byte: мітка не перевіряється", CFG, "if (((b & ROAM_LIST_TAG_MASK) != ROAM_LIST_TAG) || (n < 1U) || (n > ROAM_LISTS_COUNT))", "if ((n < 1U) || (n > ROAM_LISTS_COUNT))"),
    ("list-byte: верхня межа 15 замість 10", CFG, "|| (n < 1U) || (n > ROAM_LISTS_COUNT))\n\t{\n\t\treturn 0U;", "|| (n < 1U) || (n > 15U))\n\t{\n\t\treturn 0U;"),
    ("list-byte: ToByte без мітки", CFG, "return (uint8_t)(ROAM_LIST_TAG | list);", "return list;"),
    ("list-byte: ToByte приймає 11", CFG, "if ((list < 1U) || (list > ROAM_LISTS_COUNT))\n\t{\n\t\treturn 0U;\n\t}\n\n\treturn (uint8_t)(ROAM_LIST_TAG", "if (list < 1U)\n\t{\n\t\treturn 0U;\n\t}\n\n\treturn (uint8_t)(ROAM_LIST_TAG"),
    ("hop: повернення вихідного і після успіху", HOP, "return (away && (success == false));", "return away;"),
    ("hop: не повертаємо вихідний без успіху", HOP, "return (away && (success == false));", "return false;"),
    ("hop: множина випробуваних без обмеження місткості", HOP, "(t->n >= WAKE_HOP_TRIED_MAX)", "false"),
    ("hop: старт поза діапазоном приймається", HOP, " ||\n\t\t\t(startNum < minNum) || (startNum > maxNum))", ")"),
    # --- R59: формат блоку налаштувань ---
    ("cfg: magic не перевіряється", CFG, "(memcmp(raw->magic, ROAM_CFG_MAGIC, 4) != 0) || ", ""),
    ("cfg: версія не перевіряється", CFG, " || (raw->version != ROAM_CFG_VERSION)", ""),
    ("cfg: enabled = ==1 замість !=0", CFG, "*enabled = (raw->enabled != 0U);", "*enabled = (raw->enabled == 1U);"),
    ("cfg: ліміт стрибків без нижньої межі", CFG, "(hops < ROAM_HOPS_MIN) || ", ""),
    ("cfg: ліміт стрибків без верхньої межі", CFG, " || (hops > ROAM_HOPS_MAX)", ""),
    ("cfg: типове значення 3", CFG, "return (uint8_t)ROAM_HOPS_DEFAULT;", "return 3U;"),
    ("cfg: Build не обмежує стрибки", CFG, "raw->maxHops = roamCfgClampHops(maxHops);", "raw->maxHops = maxHops;"),
    ("cfg: Build пише enabled навпаки", CFG, "raw->enabled = (enabled ? 1U : 0U);", "raw->enabled = (enabled ? 0U : 1U);"),
    ("cfg: Build пише іншу версію", CFG, "raw->version = (uint8_t)ROAM_CFG_VERSION;", "raw->version = 2U;"),
]


def run(cmd):
    # Таймаут: мутант може зациклити тест -- це теж «вбито», але не повинно вішати скрипт.
    try:
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=30)
    except subprocess.TimeoutExpired:
        class _T:
            returncode = 124
            stdout = "таймаут (зациклення)"
        return _T()


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
    for test, rel, flags in (DIAG, HOP, CFG):
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
