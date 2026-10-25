# -*- coding: utf-8 -*-
"""Запис у SPI-флеш рації з жорсткою перевіркою меж (R31).

Усі нові записи R31 (ключі AES, база позивних) ідуть ЛИШЕ через `write_span`: вона відхиляє запис, що виходить за межі «свого» вікна, ДО першого
звернення до флеша. Саме запис робить `aes_key_store.flash_write_block` (X 1 -> X 2 -> X 3) окремо на кожен 4-КіБ сектор -- той самий sector-safe
шлях, що в `custom_data.flash_write_span` (R30).

Вікна (сирі адреси SPI-флеша, усе з коду прошивки; обґрунтування -- claude/codeplug-map.md):
  keys   0xDA000..0xDA5DB  слоти ключів AES 1..15 (запис keyId = 0xD9F9C + 100*keyId; слот 0 прошивка не використовує і ми його не пишемо)
  dmrdb  0x50000..0x8FFFF  область №1 бази позивних (DMRID_MEMORY_LOCATION_1 + 0x40000)
Захищені зони, у які не може потрапити жодне вікно (перевіряється `check_windows`, тест Z6):
  калібрування 0x10000..0x10FFF, область custom-data 0x20000..0x2FFFF, флеш-кодплаг, голосові підказки, ключі AES (для вікна бази), база (для вікна ключів)."""
import aes_key_store as aks
import cps_link as cl

SECTOR = 4096


class GuardError(ValueError):
    """Запис відхилено охоронцем меж (нічого не записано)."""


# (ім'я, початок, кінець-не-включно)
ZONES = {
    "calibration": (0x10000, 0x11000),
    "customdata": (0x20000, 0x30000),
    "dmrdb1": (0x30000 + cl.FLASH_ADDRESS_OFFSET, 0x30000 + cl.FLASH_ADDRESS_OFFSET + 0x40000),
    "codeplug": (0x9B000, 0xAF000),
    "voiceprompts": (0xAF400, 0xD8000),
    "dmrdb2head": (0xB8000 + cl.FLASH_ADDRESS_OFFSET, cl.AES_KEYS_RAW_START),           # область №2 бази: від 0xD8000 до таблиці ключів
    "aeskeys": (cl.AES_KEYS_RAW_START, cl.AES_KEYS_RAW_START + cl.AES_KEYS_RAW_LEN),
}
SLOT_AREA = (cl.AES_KEYS_RAW_START + cl.AES_KEYS_ENTRY_LEN, cl.AES_KEYS_RAW_START + cl.AES_KEYS_RAW_LEN)   # слоти 1..15
WINDOWS = {
    "keys": SLOT_AREA,
    "dmrdb": ZONES["dmrdb1"],
}
# які зони вікно має право перетинати (лише власну)
OWN_ZONE = {"keys": "aeskeys", "dmrdb": "dmrdb1"}


def check_windows(windows=None, zones=None):
    """Самоперевірка таблиць: жодне вікно не перетинає захищену зону, крім власної. Повертає список порушень (порожній -- гаразд)."""
    windows = WINDOWS if windows is None else windows
    zones = ZONES if zones is None else zones
    bad = []
    for w, (lo, hi) in windows.items():
        for z, (zlo, zhi) in zones.items():
            if z == OWN_ZONE.get(w):
                continue
            if lo < zhi and zlo < hi:
                bad.append("вікно %s (0x%X..0x%X) перетинає зону %s (0x%X..0x%X)" % (w, lo, hi, z, zlo, zhi))
    return bad


def check_span(addr, n, window):
    """Кидає GuardError, якщо [addr, addr+n) не лежить повністю у вікні."""
    if window not in WINDOWS:
        raise GuardError("невідоме вікно запису %r" % (window,))
    lo, hi = WINDOWS[window]
    if n < 0 or addr < lo or addr + n > hi:
        raise GuardError("запис 0x%X..0x%X виходить за вікно «%s» 0x%X..0x%X -- відхилено, у флеш нічого не записано" % (addr, addr + n, window, lo, hi))
    problems = check_windows()
    if problems:
        raise GuardError("таблиця меж суперечлива: " + "; ".join(problems))


def write_span(ser, addr, data, window, on_sector=None):
    """Sector-safe запис [addr, addr+len(data)) у вікно `window`: розбиття по межах секторів, кожен сектор -- окремий X 1/2/3 (прошивка читає сектор,
    підміняє байти, стирає й пише назад, тож решта сектора зберігається). `on_sector(k, total)` викликається ПЕРЕД кожним сектором; якщо кине
    виняток (наприклад, скасування) -- запис зупиняється на межі сектора."""
    data = bytes(data)
    check_span(addr, len(data), window)
    chunks = []
    pos = 0
    while pos < len(data):
        end = ((addr + pos) // SECTOR + 1) * SECTOR
        n = min(len(data) - pos, end - (addr + pos))
        chunks.append((addr + pos, data[pos:pos + n]))
        pos += n
    for k, (a, chunk) in enumerate(chunks):
        if on_sector is not None:
            on_sector(k, len(chunks))
        aks.flash_write_block(ser, a, chunk)
    return len(chunks)
