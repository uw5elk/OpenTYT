#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_ccm_init.py -- кожна змінна в CCM мусить мати ЯВНУ ініціалізацію (R10-fix5; з R12 -- на ВЕСЬ код прошивки).

ЧОМУ. CCM-RAM (0x10000000) при старті прошивки -- СМІТТЯ: лінкер-скрипт кладе .ccmram `>CCMRAM AT> FLASH`, але стартап
не копіює початкові значення й не обнуляє секцію (див. коментар у STM32F405VGTX_FLASH.ld та dmrAesInit()/aprsRxInit()).
Тому `static const char *s_modeCall __attribute__((section(".aes_ccmram")));` НЕ є NULL. Саме це дало на залізі Precise Bus
Fault (strncpy зі сміттєвої адреси, R10-fix5) -- а помилку не видно ні в коді, ні в хост-тестах (на хості статики нульові).
R12-аудит знайшов ще одну таку: callReplayBorrowed (позичене кільце «Переслухати») ніхто не обнуляв.

ЩО ПЕРЕВІРЯЄ. По ВСІХ .c у application/source кожне оголошення змінної, що йде в секцію .ccmram / .aes_ccmram (прямо, через
BPTRAMLOCATION або макрос на кшталт APRS_MODE_CCM, DMR_AES_CCM), включно зі static-локальними, мусить мати ОДНЕ з:
  1) у тому ж оголошенні коментар  CCM-INIT(функція)  -- функція існує, і змінна ЗГАДУЄТЬСЯ в її тілі або в тілі будь-якої
     функції, яку вона (транзитивно, за іменем) викликає: memset(&s_x...), s_x = ..., s_x.поле = ...;
  2) у файлі є директива  CCM-INIT-FILE(функція1, функція2)  -- те саме правило, але для всіх змінних файла, що не мають
     власної позначки (щоб не писати 100 коментарів у dmr_sms.c);
  3) у тому ж оголошенні  CCM-OK(причина)  -- змінна ЗАВЖДИ пишеться раніше, ніж читається; причина обов'язкова й конкретна;
  4) запис у tools/ccm_registry.txt  (`шлях/відносно/application/source.c:ім'я | причина`) -- для стокових змінних OpenGD77,
     у чиїх файлах ми не додаємо коментарів (merge з upstream). Запис, якому не відповідає жодне оголошення, -- теж помилка.
Нове оголошення без жодного з чотирьох -- помилка. Блоки `#if 0` ігноруються.

ЗАПУСК:  python3 MDUV380_firmware/tools/check_ccm_init.py   (код виходу 0 -- гаразд). Входить у tests/run_tests.sh.
         python3 MDUV380_firmware/tools/check_ccm_init.py --list   -- повна таблиця змінних і як кожна покрита.
         python3 MDUV380_firmware/tools/check_ccm_init.py --selftest
"""
import os
import re
import sys

FW = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
SRC = os.environ.get('CCM_SRC') or os.path.join(FW, 'application', 'source')
INC = os.path.join(FW, 'application', 'include') if not os.environ.get('CCM_SRC') else None
REGISTRY = os.environ.get('CCM_REGISTRY') or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ccm_registry.txt')

SECTION_RE = re.compile(r'section\s*\(\s*(?:"\.(?:aes_)?ccmram[^"]*"|BPTRAMLOCATION)\s*\)')
KNOWN_MACROS = {'DMR_AES_CCM'}
INIT_RE = re.compile(r'CCM-INIT\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)')
OK_RE = re.compile(r'CCM-OK\(([^)]*)\)')
FILE_RE = re.compile(r'CCM-INIT-FILE\(([^)]*)\)')
KEYWORDS = {'if', 'for', 'while', 'switch', 'return', 'sizeof', 'else', 'do', 'case'}
ATTR_RE = re.compile(r'__attribute__\s*\(\(.*?\)\)')
DEF_RE = re.compile(r'(?m)^[A-Za-z_][\w \t\*]*?\b([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{')


def strip_comments(text):
    # зберігаємо кількість рядків (заміна на пробіли/нові рядки), щоб номери збігались
    def blank(m):
        return re.sub(r'[^\n]', ' ', m.group(0))
    text = re.sub(r'/\*.*?\*/', blank, text, flags=re.S)
    text = re.sub(r'//[^\n]*', blank, text)
    return text


def strip_if0(code):
    """Порожнить блоки `#if 0 ... #endif` (з урахуванням вкладених #if), зберігаючи нумерацію рядків."""
    out = []
    depth = 0
    skip_depth = None
    for ln in code.split('\n'):
        s = ln.strip()
        if s.startswith('#'):
            d = s[1:].strip()
            if re.match(r'if(def|ndef)?\b', d):
                depth += 1
                if skip_depth is None and re.match(r'if\s+0\s*$', d):
                    skip_depth = depth
            elif re.match(r'endif\b', d):
                if skip_depth is not None and depth == skip_depth:
                    skip_depth = None
                    depth -= 1
                    out.append('')
                    continue
                depth -= 1
        out.append('' if skip_depth is not None else ln)
    return '\n'.join(out)


def build_index(codes):
    """ім'я функції -> список тіл (усі визначення в усіх файлах)."""
    idx = {}
    for code in codes.values():
        for m in DEF_RE.finditer(code):
            name = m.group(1)
            if name in KEYWORDS:
                continue
            i = m.end()
            depth = 1
            while i < len(code) and depth:
                c = code[i]
                depth += (c == '{') - (c == '}')
                i += 1
            idx.setdefault(name, []).append(code[m.end():i])
    return idx


def closure_text(index, fn, cache):
    """Усі тіла функції fn і всього, що вона транзитивно викликає (за іменем)."""
    if fn in cache:
        return cache[fn]
    seen = set()
    stack = [fn]
    parts = []
    while stack:
        f = stack.pop()
        if f in seen:
            continue
        seen.add(f)
        for b in index.get(f, []):
            parts.append(b)
            for g in re.findall(r'\b([A-Za-z_]\w*)\s*\(', b):
                if g not in seen and g in index:
                    stack.append(g)
    cache[fn] = '\n'.join(parts)
    return cache[fn]


def read_registry():
    ent = {}
    if not os.path.exists(REGISTRY):
        return ent
    with open(REGISTRY, encoding='utf-8') as f:
        for n, ln in enumerate(f, 1):
            ln = ln.strip()
            if not ln or ln.startswith('#'):
                continue
            if '|' not in ln or ':' not in ln.split('|', 1)[0]:
                print("check_ccm_init: ccm_registry.txt:%d -- очікується `шлях.c:ім'я | причина`" % n)
                sys.exit(1)
            key, why = ln.split('|', 1)
            ent[key.strip()] = (why.strip(), n)
    return ent


def collect_macros(paths):
    macros = set(KNOWN_MACROS)
    for p in paths:
        with open(p, encoding='utf-8', errors='replace') as fh:
            code = strip_comments(fh.read())
        for m in re.finditer(r'#\s*define\s+([A-Za-z_]\w*)\b[^\n]*', code):
            if SECTION_RE.search(m.group(0)):
                macros.add(m.group(1))
    return macros


def clean_decl(head, mac_re):
    head = ATTR_RE.sub(' ', head)
    head = SECTION_RE.sub(' ', head)
    head = mac_re.sub(' ', head)
    return re.sub(r'\[[^\]]*\]', ' ', head)


def scan(src_root, inc_root):
    """Повертає (оголошення, codes, raws). Оголошення: dict(file, line, names, raw)."""
    cfiles, hfiles = [], []
    for root, _d, files in os.walk(src_root):
        for f in files:
            if f.endswith('.c'):
                cfiles.append(os.path.join(root, f))
            elif f.endswith('.h'):
                hfiles.append(os.path.join(root, f))
    if inc_root and os.path.isdir(inc_root):
        for root, _d, files in os.walk(inc_root):
            for f in files:
                if f.endswith('.h'):
                    hfiles.append(os.path.join(root, f))
    macros = collect_macros(cfiles + hfiles)
    mac_re = re.compile(r'\b(' + '|'.join(re.escape(x) for x in sorted(macros)) + r')\b')
    decls, codes, raws = [], {}, {}
    for p in sorted(cfiles):
        with open(p, encoding='utf-8', errors='replace') as fh:
            raw = fh.read()
        raws[p] = raw
        code = strip_if0(strip_comments(raw))
        codes[p] = code
        raw_lines = raw.split('\n')
        lines = code.split('\n')
        i = 0
        while i < len(lines):
            ln = lines[i]
            if ln.lstrip().startswith('#') or not (SECTION_RE.search(ln) or mac_re.search(ln)):
                i += 1
                continue
            j = i
            while ';' not in lines[j] and j + 1 < len(lines) and j < i + 6:
                j += 1
            stmt = ' '.join(lines[i:j + 1])
            head = re.split(r'[=;]', stmt, 1)[0]
            decl = clean_decl(head, mac_re)
            if '(' in decl:      # виклик/прототип функції, а не оголошення змінної
                i = j + 1
                continue
            names = []
            for part in decl.split(','):
                ids = re.findall(r'[A-Za-z_]\w*', part)
                if ids:
                    names.append(ids[-1])
            if names:
                decls.append({'file': p, 'line': i + 1, 'names': names, 'raw': ' '.join(raw_lines[i:j + 1])})
            i = j + 1
    return decls, codes, raws


def analyze(src_root, inc_root, registry):
    decls, codes, raws = scan(src_root, inc_root)
    index = build_index(codes)
    cache = {}
    errors, rows = [], []
    used_reg = set()
    for d in decls:
        rel = os.path.relpath(d['file'], src_root).replace(os.sep, '/')
        where = '%s:%d' % (rel, d['line'])
        im = INIT_RE.search(d['raw'])
        ok = OK_RE.search(d['raw'])
        fdirs = []
        for m in FILE_RE.finditer(raws[d['file']]):
            fdirs += [x.strip() for x in m.group(1).split(',') if x.strip()]
        for name in d['names']:
            how = None
            pat = re.compile(r'\b' + re.escape(name) + r'\b')
            if im:
                fn = im.group(1)
                if fn not in index:
                    errors.append('%s  %s: функції %s() не знайдено' % (where, name, fn))
                    continue
                if pat.search(closure_text(index, fn, cache)):
                    how = 'CCM-INIT(%s)' % fn
                else:
                    errors.append('%s  %s: %s() (і все, що вона викликає) не згадує змінну -- вона її не ініціалізує' % (where, name, fn))
                    continue
            elif ok:
                if len(ok.group(1).strip()) < 8:
                    errors.append('%s  %s: CCM-OK(...) без конкретної причини' % (where, name))
                    continue
                how = 'CCM-OK'
            else:
                for fn in fdirs:
                    if fn in index and pat.search(closure_text(index, fn, cache)):
                        how = 'CCM-INIT-FILE(%s)' % fn
                        break
                if how is None:
                    key = '%s:%s' % (rel, name)
                    if key in registry:
                        used_reg.add(key)
                        how = 'реєстр'
            if how is None:
                if fdirs:
                    errors.append('%s  %s: файл має CCM-INIT-FILE(%s), але змінну вони не ініціалізують -- додай ініціалізацію або CCM-OK(причина)' % (where, name, ', '.join(fdirs)))
                else:
                    errors.append('%s  %s: немає ні CCM-INIT(функція), ні CCM-OK(причина), ні запису в ccm_registry.txt -- CCM при старті сміття' % (where, name))
                continue
            rows.append((where, name, how))
    for key, (_why, n) in sorted(registry.items()):
        if key not in used_reg:
            errors.append('tools/ccm_registry.txt:%d  %s: запису не відповідає жодне оголошення в CCM (застарів?)' % (n, key))
    return rows, errors


def main():
    rows, errors = analyze(SRC, INC, read_registry())
    if '--list' in sys.argv:
        for w, n, h in rows:
            print('%-52s %-28s %s' % (w, n, h))
    if errors:
        print('check_ccm_init: ПОМИЛКИ (%d):' % len(errors))
        for e in errors:
            print('  ' + e)
        return 1
    print('check_ccm_init: усе гаразд (змінних у CCM перевірено: %d)' % len(rows))
    return 0


def selftest():
    """Самоперевірка: сміттєвий вказівник без ініціалізації МАЄ бути спійманий (це і був баг R10-fix5)."""
    import subprocess
    import tempfile
    base = ('#define APRS_MODE_CCM  __attribute__((section(".aes_ccmram")))\n'
            'static const char *s_modeCall APRS_MODE_CCM;\n'
            'void aprsBeaconingInit(void)\n{\n\tint x = 0;\n}\n')
    mark = base.replace('APRS_MODE_CCM;\n', 'APRS_MODE_CCM;   /* CCM-INIT(aprsBeaconingInit) */\n', 1)
    good = mark.replace('int x = 0;', 's_modeCall = NULL;')
    via = good.replace('s_modeCall = NULL;', 'helper();').replace(
        'void aprsBeaconingInit', 'void helper(void)\n{\n\ts_modeCall = NULL;\n}\nvoid aprsBeaconingInit')
    okm = base.replace('APRS_MODE_CCM;\n', 'APRS_MODE_CCM;   /* CCM-OK(пишеться першим у enter) */\n', 1)
    okbad = base.replace('APRS_MODE_CCM;\n', 'APRS_MODE_CCM;   /* CCM-OK() */\n', 1)
    filed = base + '/* CCM-INIT-FILE(aprsBeaconingInit) */\n'
    filed_ok = filed.replace('int x = 0;', 's_modeCall = NULL;')
    local = 'void f(void)\n{\n\tstatic unsigned char q[8] __attribute__((section(".ccmram")));\n\tq[0] = 1;\n}\n'
    dead = '#if 0\n__attribute__((section(".ccmram"))) int junk;\n#endif\n'
    multi = ('#define DMR_AES_CCM __attribute__((section(".aes_ccmram")))\n'
             'static int a DMR_AES_CCM, b DMR_AES_CCM;   /* CCM-INIT(init) */\nvoid init(void)\n{\n\ta = 0;\n}\n')
    cases = [
        (base, 1, 'без позначки'),
        (mark, 1, 'позначка без ініціалізації'),
        (good, 0, 'з ініціалізацією'),
        (via, 0, 'ініціалізація через викликану функцію'),
        (okm, 0, 'CCM-OK з причиною'),
        (okbad, 1, 'CCM-OK без причини'),
        (filed, 1, 'CCM-INIT-FILE без ініціалізації'),
        (filed_ok, 0, 'CCM-INIT-FILE з ініціалізацією'),
        (local, 1, 'static-локальна без позначки'),
        (dead, 0, 'блок #if 0 ігнорується'),
        (multi, 1, 'a, b: b не ініціалізована'),
    ]

    def run(text, regtext, what, want):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, 'functions'))
            with open(os.path.join(d, 'functions', 'x.c'), 'w', encoding='utf-8') as f:
                f.write(text)
            reg = os.path.join(d, 'reg.txt')
            with open(reg, 'w', encoding='utf-8') as f:
                f.write(regtext)
            env = dict(os.environ, CCM_SRC=d, CCM_REGISTRY=reg)
            r = subprocess.run([sys.executable, os.path.abspath(__file__)], env=env, capture_output=True, text=True)
            if r.returncode != want:
                print('selftest ПРОВАЛ (%s): код %d, очікувався %d\n%s%s' % (what, r.returncode, want, r.stdout, r.stderr))
                return False
        return True

    for text, want, what in cases:
        if not run(text, '', what, want):
            return 1
    if not run(base, 'functions/x.c:s_modeCall | пишеться першим\n', 'реєстр дозволяє', 0):
        return 1
    if not run(base, 'functions/x.c:s_modeCall | ok\nfunctions/x.c:nema | ok\n', 'застарілий запис реєстру', 1):
        return 1
    print('check_ccm_init --selftest: гаразд (%d сценаріїв + 2 для реєстру)' % len(cases))
    return 0


if __name__ == '__main__':
    sys.exit(selftest() if '--selftest' in sys.argv else main())
