#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R65B: мутанти редактора списків прийому (codeplug.c, блок RXGROUP_EDIT_ENABLED). Кожен мутант -- одна правка тексту справжнього codeplug.c; test_codeplug_rxgroup мусить на ньому
ПРОВАЛИТИСЬ (збірка не вдалась -- теж провал мутанта-вижившого лише якщо не зібралось, тож збірку перевіряємо окремо на оригіналі). Прапори й джерела беруться з tests/run_tests.sh."""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.normpath(os.path.join(HERE, ".."))
APP = os.path.join(FW, "application")
CP = os.path.join(APP, "source", "functions", "codeplug.c")

MUTANTS = [
    ("видалення без каскаду каналів", "(codeplugChannelRxGroupField(ch) == (uint8_t)slot) && !codeplugChannelClearRxGroupField(ch)", "(codeplugChannelRxGroupField(ch) == 250) && !codeplugChannelClearRxGroupField(ch)"),
    ("видалення не чистить VFO", "if (EEPROM_Read(addr, &g, 1) && (g == (uint8_t)slot))", "if (EEPROM_Read(addr, &g, 1) && (g == 250))"),
    ("видалення не обнуляє довжину", "if (!codeplugRxGroupWriteLen(slot, 0))\n\t{\n\t\treturn CODEPLUG_RXGROUP_WRITE_ERROR;\n\t}\n\n\tmemset(zeros", "memset(zeros"),
    ("видалення не обнуляє тіло", "return SPI_Flash_write(codeplugRxGroupBodyAddr(slot), zeros, (int)sizeof(zeros)) ? CODEPLUG_RXGROUP_OK : CODEPLUG_RXGROUP_WRITE_ERROR;", "return CODEPLUG_RXGROUP_OK;"),
    ("створення: довжина раніше тіла", "if (!SPI_Flash_write(codeplugRxGroupBodyAddr(slot), rec, (int)sizeof(rec)))", "if (!codeplugRxGroupWriteLen(slot, (uint8_t)n) || !SPI_Flash_write(codeplugRxGroupBodyAddr(slot), rec, (int)sizeof(rec)))"),
    ("перейменування дозволяє дубль", "if ((slot != exceptSlot) && codeplugRxGroupExists(slot))", "if (codeplugRxGroupExists(slot))"),
    ("нема перевірки хвоста 0xFF", "if ((n == CODEPLUG_RXGROUP_NAME_LEN) && (((uint8_t)name[CODEPLUG_RXGROUP_NAME_LEN - 1]) == 0xFF))", "if (0)"),
    ("нема перевірки дубля контакту", "if (members[j] == members[i])", "if (0)"),
    ("склад не оновлює довжину", "if ((codeplugRXGroupCache[slot - 1] != (uint8_t)n) && !codeplugRxGroupWriteLen(slot, (uint8_t)n))", "if (0)"),
    ("кеш не перечитується", "\tcodeplugRxGroupInitCache();\n\treturn ok && (codeplugRXGroupCache[slot - 1] == len);", "\tcodeplugRXGroupCache[slot - 1] = len;\n\treturn ok;"),
    ("пробіли = не порожня назва", "if ((n == 0) || blank)", "if (n == 0)"),
    ("33 контакти дозволено", "if ((n < 1) || (n > CODEPLUG_RXGROUP_MEMBERS_MAX))", "if ((n < 1) || (n > 33))"),
    ("порожній склад дозволено", "if ((n < 1) || (n > CODEPLUG_RXGROUP_MEMBERS_MAX))", "if ((n < 0) || (n > CODEPLUG_RXGROUP_MEMBERS_MAX))"),
    ("лічильник рахує канали поза маскою", "if (codeplugAllChannelsIndexIsInUse(ch) && (codeplugChannelRxGroupField(ch) == (uint8_t)slot))\n\t\t{\n\t\t\tn++;", "if ((codeplugChannelRxGroupField(ch) == (uint8_t)slot))\n\t\t{\n\t\t\tn++;"),
    ("контакт 1025 дозволено", "(members[i] > CODEPLUG_CONTACTS_MAX)", "(members[i] > 1025)"),
    ("створення бере не перший вільний слот", "if (codeplugRXGroupCache[i - 1] == 0)\n\t\t{\n\t\t\tslot = i;\n\t\t\tbreak;", "if (codeplugRXGroupCache[i - 1] == 0)\n\t\t{\n\t\t\tslot = i;"),
    ("склад пише 80 байтів", "(uint8_t *)buf, (int)sizeof(buf)))", "(uint8_t *)buf, (int)sizeof(buf) + 1))"),
    ("R66C: переміщення TG не міняє місцями", "pair[0] = m[lo + 1];\n\tpair[1] = m[lo];\n\treturn SPI_Flash_write", "pair[0] = m[lo];\n\tpair[1] = m[lo + 1];\n\treturn SPI_Flash_write"),
    ("R66C: переміщення TG пише не туди (позиція pos, а не lo)", "CODEPLUG_RXGROUP_NAME_LEN + (lo * (int)sizeof(uint16_t)), (uint8_t *)pair", "CODEPLUG_RXGROUP_NAME_LEN + (pos * (int)sizeof(uint16_t)), (uint8_t *)pair"),
    ("R66C: переміщення TG без перевірки кроку", "if (!codeplugRxGroupExists(slot) || ((dir != -1) && (dir != 1)))", "if (!codeplugRxGroupExists(slot))"),
    ("R66C: переміщення TG пише 6 байтів", "(uint8_t *)pair, (int)sizeof(pair)) ? CODEPLUG_RXGROUP_OK", "(uint8_t *)pair, (int)sizeof(pair) + 2) ? CODEPLUG_RXGROUP_OK"),
    ("R66C: переміщення TG дозволяє вихід за кінець", "if ((pos < 0) || (pos >= n) || (to < 0) || (to >= n))\n\t{\n\t\treturn CODEPLUG_RXGROUP_BAD_ARG;\n\t}\n\tlo =", "if ((pos < 0) || (pos >= n) || (to < 0))\n\t{\n\t\treturn CODEPLUG_RXGROUP_BAD_ARG;\n\t}\n\tlo ="),
]


def build_cmd(src, exe):
    s = open(os.path.join(HERE, "run_tests.sh"), encoding="utf-8").read()
    fw = s[s.index('FW_INCS="'):]
    fw = fw[:fw.index('"\n', 10) + 2].replace("$FW", FW)
    m = re.search(r'FW_INCS="(.*?)"\n', fw, re.S)
    incs = m.group(1).replace("\\\n", " ")
    incs = incs.replace("$FW", FW)
    xf = re.search(r'\[test_codeplug_rxgroup\]="\$FW_INCS ([^"]*)"', s).group(1).split("#")[0]
    cmd = ["gcc", "-O1", "-w"] + incs.split() + xf.split() + [os.path.join(HERE, "test_codeplug_rxgroup.c"), src,
                                                               os.path.join(APP, "source", "functions", "aprs_rx_parse.c"),
                                                               os.path.join(APP, "source", "functions", "aprs_mode_cfg.c"),
                                                               os.path.join(APP, "source", "functions", "dmr_sms_text.c"), "-lm",
                                                               "-I", os.path.join(APP, "include"), "-I", os.path.join(APP, "include", "crypto"), "-o", exe]
    return cmd


def run(src, td, tag):
    exe = os.path.join(td, "t_" + tag)
    b = subprocess.run(build_cmd(src, exe), capture_output=True, text=True, cwd=FW)
    if b.returncode != 0:
        return None, b.stderr[-300:]
    p = subprocess.run([exe], capture_output=True, text=True, errors="replace", timeout=300)
    return p.returncode, p.stdout


def main():
    code = open(CP, encoding="utf-8").read()
    bad = 0
    with tempfile.TemporaryDirectory() as td:
        rc, out = run(CP, td, "orig")
        if rc != 0:
            print("ПРОВАЛ: оригінал не проходить тест (%r): %s" % (rc, out[-300:]))
            return 1
        for i, (name, old, new) in enumerate(MUTANTS):
            if code.count(old) != 1:
                print("ПРОВАЛ: мутант «%s»: фрагмент зустрічається %d разів (мусить 1)" % (name, code.count(old)))
                bad += 1
                continue
            mp = os.path.join(td, "codeplug.c")
            open(mp, "w", encoding="utf-8").write(code.replace(old, new))
            rc, out = run(mp, td, "m%d" % i)
            if rc is None:
                print("ПРОВАЛ: мутант «%s» не збирається: %s" % (name, out))
                bad += 1
            elif rc == 0:
                print("ПРОВАЛ: мутант вижив: «%s»" % name)
                bad += 1
    if bad:
        print("mutants_rxgroup: %d проблем" % bad)
        return 1
    print("mutants_rxgroup: усі %d мутантів убито" % len(MUTANTS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
