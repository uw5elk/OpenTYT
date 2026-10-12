#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_ccm_init.py -- R10-fix5: кожна APRS-змінна в CCM мусить мати ЯВНУ ініціалізацію.

ЧОМУ. CCM-RAM (0x10000000) при старті прошивки -- СМІТТЯ: лінкер-скрипт кладе .ccmram `>CCMRAM AT> FLASH`, але стартап
не копіює початкові значення й не обнуляє секцію (див. коментар у STM32F405VGTX_FLASH.ld та dmrAesInit()/aprsRxInit()).
Тому `static const char *s_modeCall __attribute__((section(".aes_ccmram")));` НЕ є NULL. Саме це дало на залізі Precise Bus
Fault (strncpy зі сміттєвої адреси, R10-fix5) -- а помилку не видно ні в коді, ні в хост-тестах (на хості статики нульові).

ЩО ПЕРЕВІРЯЄ. У файлах application/source/functions/aprs*.c та user_interface/menuAprs*.c кожне оголошення змінної, що йде в
секцію .ccmram / .aes_ccmram (прямо або через макрос на кшталт APRS_MODE_CCM, DMR_AES_CCM), має в тому ж рядку коментар
    CCM-INIT(ім'я_функції)
і тіло цієї функції МАЄ згадувати змінну (memset(&s_x...), s_x = ..., s_x.поле = ...). Для змінних, які точно пишуться раніше,
ніж читаються, теж називається функція, що пише першою. Функція мусить існувати. Нове оголошення без позначки -- помилка.

ЗАПУСК:  python3 MDUV380_firmware/tools/check_ccm_init.py   (код виходу 0 -- гаразд). Входить у tests/run_tests.sh.
"""
import os
import re
import sys

FW = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
SRC = os.environ.get('CCM_SRC') or os.path.join(FW, 'application', 'source')
FILES_GLOBS = [
    (os.path.join(SRC, 'functions'), re.compile(r'^aprs.*\.c$')),
    (os.path.join(SRC, 'user_interface'), re.compile(r'^menuAprs.*\.c$')),
]
SECTION_RE = re.compile(r'section\s*\(\s*"\.(?:aes_)?ccmram[^"]*"\s*\)')
# макроси, що самі розгортаються в секцію CCM (спільні заголовки)
KNOWN_MACROS = {'DMR_AES_CCM'}
INIT_RE = re.compile(r'CCM-INIT\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)')
FOREIGN_FILES = []


def strip_comments(text):
    # зберігаємо кількість рядків (заміна на пробіли/нові рядки), щоб номери збігались
    def blank(m):
        return re.sub(r'[^\n]', ' ', m.group(0))
    text = re.sub(r'/\*.*?\*/', blank, text, flags=re.S)
    text = re.sub(r'//[^\n]*', blank, text)
    return text


def function_body(code, name):
    """Тіло функції `name` (без коментарів). None -- функції нема."""
    m = re.search(r'(?m)^[A-Za-z_][\w\s\*]*\b' + re.escape(name) + r'\s*\([^;{]*\)\s*\{', code)
    if not m:
        return None
    i = m.end()
    depth = 1
    while i < len(code) and depth:
        c = code[i]
        depth += (c == '{') - (c == '}')
        i += 1
    return code[m.end():i]


def all_codes():
    out = {}
    for root, _dirs, files in os.walk(SRC):
        for f in files:
            if f.endswith('.c'):
                p = os.path.join(root, f)
                with open(p, encoding='utf-8', errors='replace') as fh:
                    out[p] = strip_comments(fh.read())
    return out


def main():
    codes = all_codes()
    errors = []
    checked = 0
    for d, rx in FILES_GLOBS:
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not rx.match(f):
                continue
            p = os.path.join(d, f)
            with open(p, encoding='utf-8', errors='replace') as fh:
                raw = fh.read()
            raw_lines = raw.split('\n')
            code = strip_comments(raw)
            lines = code.split('\n')
            macros = set(KNOWN_MACROS)
            for m in re.finditer(r'#\s*define\s+([A-Za-z_]\w*)\b[^\n]*', code):
                if SECTION_RE.search(m.group(0)):
                    macros.add(m.group(1))
            mac_re = re.compile(r'\b(' + '|'.join(re.escape(x) for x in sorted(macros)) + r')\b') if macros else None
            i = 0
            while i < len(lines):
                ln = lines[i]
                # оголошення змінної: має `;` і секцію/макрос; #define-рядки пропускаємо
                if ln.lstrip().startswith('#'):
                    i += 1
                    continue
                stmt_start = i
                stmt = ln
                # оголошення може займати кілька рядків (struct {...} s_x DMR_AES_CCM;)
                hit = bool(SECTION_RE.search(ln)) or bool(mac_re and mac_re.search(ln))
                if not hit:
                    i += 1
                    continue
                j = i
                while ';' not in lines[j] and j + 1 < len(lines) and j < i + 6:
                    j += 1
                stmt = ' '.join(lines[i:j + 1])
                if '(' in stmt.split('=')[0] and 'section' not in stmt.split('=')[0] and not (mac_re and mac_re.search(stmt)):
                    i = j + 1
                    continue
                # ім'я змінної: останній ідентифікатор оголошення після вилучення __attribute__((...)), макросів і [розмірів]
                decl = re.split(r'[=;]', stmt, 1)[0]
                decl = re.sub(r'__attribute__\s*\(\(.*?\)\)', ' ', decl)
                if mac_re:
                    decl = mac_re.sub(' ', decl)
                decl = re.sub(r'\[[^\]]*\]', ' ', decl)
                ids = re.findall(r'[A-Za-z_]\w*', decl)
                name = ids[-1] if ids else None
                # позначка CCM-INIT -- у сирому тексті тих самих рядків (коментар)
                raw_stmt = ' '.join(raw_lines[stmt_start:j + 1])
                im = INIT_RE.search(raw_stmt)
                checked += 1
                where = '%s:%d' % (os.path.relpath(p, FW), stmt_start + 1)
                if im is None:
                    errors.append('%s  %s: немає позначки /* CCM-INIT(функція) */ -- CCM при старті сміття' % (where, name))
                else:
                    fn = im.group(1)
                    body = None
                    for cp, cc in codes.items():
                        body = function_body(cc, fn)
                        if body is not None:
                            break
                    if body is None:
                        errors.append('%s  %s: функції %s() не знайдено' % (where, name, fn))
                    elif name and not re.search(r'\b' + re.escape(name) + r'\b', body):
                        errors.append('%s  %s: функція %s() не згадує змінну -- вона її не ініціалізує' % (where, name, fn))
                i = j + 1
    if errors:
        print('check_ccm_init: ПОМИЛКИ (%d):' % len(errors))
        for e in errors:
            print('  ' + e)
        return 1
    print('check_ccm_init: усе гаразд (змінних у CCM перевірено: %d)' % checked)
    return 0


def selftest():
    """Самоперевірка: сміттєвий вказівник без ініціалізації МАЄ бути спійманий (це і був баг R10-fix5)."""
    import subprocess
    import tempfile
    bad = ('#define APRS_MODE_CCM  __attribute__((section(".aes_ccmram")))\n'
           'static const char *s_modeCall APRS_MODE_CCM;\n'
           'void aprsBeaconingInit(void)\n{\n\tint x = 0;\n}\n')
    bad2 = bad.replace('APRS_MODE_CCM;\n', 'APRS_MODE_CCM;   /* CCM-INIT(aprsBeaconingInit) */\n', 1)
    good = bad2.replace('int x = 0;', 's_modeCall = NULL;')
    for text, want in ((bad, 1), (bad2, 1), (good, 0)):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, 'functions'))
            os.makedirs(os.path.join(d, 'user_interface'))
            with open(os.path.join(d, 'functions', 'aprs_x.c'), 'w', encoding='utf-8') as f:
                f.write(text)
            env = dict(os.environ, CCM_SRC=d)
            r = subprocess.run([sys.executable, os.path.abspath(__file__)], env=env, capture_output=True, text=True)
            if r.returncode != want:
                print('selftest ПРОВАЛ: код %d, очікувався %d\n%s%s' % (r.returncode, want, r.stdout, r.stderr))
                return 1
    print('check_ccm_init --selftest: гаразд (без позначки -- помилка; позначка без ініціалізації -- помилка; з ініціалізацією -- гаразд)')
    return 0


if __name__ == '__main__':
    sys.exit(selftest() if '--selftest' in sys.argv else main())
