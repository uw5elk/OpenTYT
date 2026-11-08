#!/usr/bin/env python3
"""custom_data.py — правильний (не спрощений) читач/писар "OpenGD77" custom-data
регіону в SPI-флеші (FLASH_ADDRESS_OFFSET=0x20000..+0x10000, тобто 64 КБ), який ЦІЛИЙ
розділяється між БАГАТЬМА типами блоків одночасно: зображення заставки, тема дня/ночі,
AES-ключі (лише селектор), повідомлення+пресети SMS, і тепер RCTL-конфіг.

Побайтова Python-копія алгоритму прошивки (codeplug.c):
  codeplugGetOpenGD77CustomDataStartAddressForType() — послідовне сканування заголовків
    [dataType:int32][dataLength:int32] від зміщення 12, доки не знайде потрібний тип
    АБО не натрапить на порожній ("0xFFFFFFFF"/EMPTY) слот;
  codeplugGetOpenGD77CustomDataFirstEmptySlot() — перший порожній слот, з перевіркою,
    що новий блок влізе до MAX_BLOCK_ADDRESS (0x10000);
  codeplugSetOpenGD77CustomData() — записує лише В ІСНУЮЧИЙ блок ТІЄЇ Ж довжини, або
    в перший порожній слот; довжину існуючого блоку міняти НЕ можна.

*** Чому цей файл існує окремо, а не просто копіює підхід aes_key_store.py: ***
Оригінальний aes_key_store.py записує свій AESK-блок БЕЗУМОВНО за адресою FLASH_BASE
(тобто вважає, що це ЄДИНИЙ або ПЕРШИЙ блок у регіоні) — це працювало, бо на практиці
AES-блок майже завжди був першим записаним. Але регіон реально спільний з темами,
заставкою, повідомленнями тощо; сліпе записування "з початку" могло б ЗАТЕРТИ будь-який
блок, що фізично лежить після точки запису. Для RCTL-конфігу (майже напевно НЕ перший
блок на вже налаштованій рації — теми/повідомлення там, скоріш за все, вже є) так робити
не можна. Тому: правильний scan-find-or-append + запис, що зачіпає ЛИШЕ адреси свого
блоку (через sector-safe flash_write_span, що коректно розбиває запис по МЕЖАХ 4КБ
секторів -- на відміну від flash_write_block(), який готує лише ОДИН сектор і не
призначений для запису, що перетинає межу).
"""
import struct
import aes_key_store as aks

FLASH_BASE = aks.FLASH_BASE          # 0x20000 (FLASH_ADDRESS_OFFSET)
MAX_BLOCK_ADDRESS = 0x10000          # той самий ліміт, що й MAX_BLOCK_ADDRESS у codeplug.c
HDR_LEN = 8                          # sizeof(codeplugCustomDataBlockHeader_t): int32+int32
REGION_MAGIC = b"OpenGD77"

TYPE_EMPTY = -1  # CODEPLUG_CUSTOM_DATA_TYPE_EMPTY (0xFFFFFFFF) - як int32 зі знаком


def _read_region(ser, addr, length):
    """addr тут -- зміщення ВІД FLASH_BASE (як у прошивці), не абсолютна адреса."""
    return aks.flash_read(ser, FLASH_BASE + addr, length)


# ---------------------------------------------------------------------------------------------------------------------------------
#  R71: кеш РОЗТАШУВАННЯ блоків (не даних!)
# ---------------------------------------------------------------------------------------------------------------------------------
# Раніше кожне читання/запис блока заново обходило область: 1 запит на магію + по запиту на кожен заголовок до потрібного (для RCTL -- ~11 запитів).
# Тепер обхід запам'ятовує, де (адреса, довжина) лежить кожен знайдений блок, і наступне звернення перевіряє ЛИШЕ заголовок за збереженою адресою.
# Збіг {тип, довжина} -- блок там; розбіжність або відсутність у кеші -- повний обхід, як і раніше (тож зміна області самою рацією, заміна рації на
# тому ж порту чи відновлення з бекапу не дають хибної адреси: нічого не береться на віру). ДАНІ з кешу не віддаються ніколи -- вони читаються
# з рації щоразу (інакше гонка «ПК пише / рація теж змінює» віддавала б застаріле). Кеш скидається при КОЖНОМУ записі у флеш області (хук aks), при
# відновленні, ущільненні й повторному відкритті документа з рації (cd.invalidate()).
SCAN_WINDOW = 256                      # скільки байтів брати за один запит під час обходу (дрібні блоки йдуть підряд -- один запит покриває кілька заголовків)
_LOCS = {}                             # ключ порту -> {тип: (зміщення, довжина)}


def _key(ser):
    port = getattr(ser, "port", None)
    return port if isinstance(port, str) else id(ser)


def invalidate(ser=None):
    """Скинути кеш розташування (для порту ser або повністю)."""
    if ser is None:
        _LOCS.clear()
    else:
        _LOCS.pop(_key(ser), None)


def _on_flash_write(addr, length):
    # будь-який запис, що зачепив область custom-data, скидає кеш (заголовки могли змінитись); решту флешу (таблиця AES, кодплаг) кеш не стосується
    if addr < FLASH_BASE + MAX_BLOCK_ADDRESS and addr + length > FLASH_BASE:
        _LOCS.clear()


aks.WRITE_LISTENERS.append(_on_flash_write)


def _remember(ser, data_type, addr, dlen):
    _LOCS.setdefault(_key(ser), {})[data_type] = (addr, dlen)


def _cached_header(ser, data_type):
    """Кеш -> (зміщення, довжина), якщо заголовок за збереженою адресою досі {data_type, довжина}; інакше None (запис кешу видаляється)."""
    loc = _LOCS.get(_key(ser), {}).get(data_type)
    if loc is None:
        return None
    addr, dlen = loc
    try:
        hdr = _read_region(ser, addr, HDR_LEN)
    except Exception:  # noqa: BLE001
        invalidate(ser)
        return None
    if len(hdr) == HDR_LEN and struct.unpack("<ii", hdr) == (data_type, dlen):
        return loc
    invalidate(ser)
    return None


def _scan(ser, data_type, new_len):
    """Обхід області (побайтова копія двох функцій codeplug.c) вікнами по SCAN_WINDOW байтів; по дорозі запам'ятовує всі знайдені блоки."""
    win_base = 0
    win = _read_region(ser, 0, SCAN_WINDOW)
    if win[:8] != REGION_MAGIC:
        return (None, None, None)
    addr = 12
    seen = {}
    while addr < MAX_BLOCK_ADDRESS:
        if not (win_base <= addr and addr + HDR_LEN <= win_base + len(win)):
            win_base = addr
            win = _read_region(ser, addr, min(SCAN_WINDOW, MAX_BLOCK_ADDRESS - addr))
            if len(win) < HDR_LEN:
                return (None, None, None)
        dtype, dlen = struct.unpack("<ii", win[addr - win_base:addr - win_base + HDR_LEN])
        if dtype != TYPE_EMPTY and dlen != 0 and dlen != TYPE_EMPTY:
            seen.setdefault(dtype, (addr, dlen))
        if dtype == data_type:
            for t, loc in seen.items():
                _remember(ser, t, loc[0], loc[1])
            return ("existing", addr, dlen)
        if dlen == 0 or dlen == TYPE_EMPTY:
            for t, loc in seen.items():
                _remember(ser, t, loc[0], loc[1])
            if (addr + HDR_LEN + new_len) < MAX_BLOCK_ADDRESS:
                return ("empty", addr, None)
            return (None, None, None)   # порожній слот є, але новий блок туди не влізе
        addr += HDR_LEN + dlen
    return (None, None, None)


def find_or_alloc_block(ser, data_type, new_len):
    """Побайтова копія двох функцій codeplug.c разом. Повертає (kind, addr, existLen):
      ("existing", addr, existLen) -- блок цього типу вже є (existLen -- його поточна
          довжина; якщо existLen != new_len, ЗАПИС ЗАБОРОНЕНО -- прошивка теж це не
          дозволяє, довжину блоку міняти не можна);
      ("empty", addr, None)        -- вільний слот знайдено, є місце для new_len байт;
      (None, None, None)           -- регіон не в форматі "OpenGD77", або місця немає.
    R71: спершу перевірка заголовка за збереженою адресою (1 запит), інакше обхід вікнами.
    """
    loc = _cached_header(ser, data_type)
    if loc is not None:
        return ("existing", loc[0], loc[1])
    return _scan(ser, data_type, new_len)


def flash_write_span(ser, addr, data):
    """Sector-safe запис: розбиває [addr, addr+len(data)) по межах 4КБ-секторів і
    викликає aes_key_store.flash_write_block() окремо на кожен сектор -- та функція
    готує/стирає РІВНО ОДИН сектор і не призначена для запису, що його перетинає.
    addr тут -- АБСОЛЮТНА адреса SPI-флешу (вже з урахуванням FLASH_BASE).

    R30: будь-який запис, що виходить за область custom-data [FLASH_BASE, FLASH_BASE+MAX_BLOCK_ADDRESS), відхиляється ДО першого звернення до флеша
    -- насамперед щоб помилка в обчисленні адреси ніколи не дісталась сектора калібрування (0x10000..0x10FFF) чи сусідніх ділянок."""
    pos = 0
    n = len(data)
    if addr < FLASH_BASE or addr + n > FLASH_BASE + MAX_BLOCK_ADDRESS:
        raise ValueError("запис 0x%X..0x%X виходить за область custom-data 0x%X..0x%X -- відхилено" % (
            addr, addr + n, FLASH_BASE, FLASH_BASE + MAX_BLOCK_ADDRESS))
    while pos < n:
        sector_base = ((addr + pos) // 4096) * 4096
        sector_end = sector_base + 4096
        room_in_sector = sector_end - (addr + pos)
        chunk_len = min(n - pos, room_in_sector)
        chunk = data[pos: pos + chunk_len]
        aks.flash_write_block(ser, addr + pos, chunk)
        pos += chunk_len


# R37: необов'язковий обробник «не вистачає місця»: функція(ser, data_type, new_len) -> True, якщо місце з'явилось (після ущільнення області), або RuntimeError
# з поясненням. Ставить GUI (cps_ui/app.py), бо лише він може спитати користувача; без нього write_block повертає пояснення з числами.
ROOM_HOOK = None


def _magic_ok(ser):
    try:
        return _read_region(ser, 0, 8) == REGION_MAGIC
    except Exception:  # noqa: BLE001 -- помилка читання -> вважаємо, що області нема (тоді запис і так не піде)
        return False


def _no_room_text(ser, data_type, new_len):
    """Пояснення, чому блок не вміщається, з числами, прочитаними з області (довго лише на цьому, аварійному шляху)."""
    import cps_link
    import custom_compact as cc
    import custom_region as cr
    try:
        data = cr.read_radio_region(cps_link.CpsLink(ser))
        rc = cc.room_check(data, data_type, new_len)
        return rc.text + " Розділ «Усі налаштування» -> «Ущільнити область» прибирає вилучені блоки й звільняє місце."
    except Exception:  # noqa: BLE001
        return "немає вільного місця в області custom-data (потрібно %d Б даних + %d Б заголовка)" % (new_len, HDR_LEN)


def write_block(ser, data_type, payload):
    """Записати/оновити один custom-data блок типу data_type з вмістом payload.
    Дозволяє лише запис ТІЄЇ Ж довжини в існуючий блок (як і прошивка) або створення
    нового блоку в першому вільному слоті. Повертає (True, "") або (False, "причина")."""
    new_len = len(payload)
    kind, addr, existLen = find_or_alloc_block(ser, data_type, new_len)
    if kind is None and _magic_ok(ser):
        # R37 U3: область є, але новий блок не вміщається -- замість глухої помилки: ущільнення (якщо воно допоможе) або пояснення з числами
        if ROOM_HOOK is not None:
            try:
                if ROOM_HOOK(ser, data_type, new_len):
                    kind, addr, existLen = find_or_alloc_block(ser, data_type, new_len)
            except RuntimeError as e:
                return False, str(e)
        if kind is None:
            return False, _no_room_text(ser, data_type, new_len)
    if kind is None:
        return False, "регіон не в форматі OpenGD77 (немає заголовка), тож записати блок нікуди"
    if kind == "existing" and existLen != new_len:
        return False, ("існуючий блок типу %d має іншу довжину (%d, а не %d) -- "
                        "прошивка так само забороняє міняти довжину блоку" % (data_type, existLen, new_len))

    header = struct.pack("<ii", data_type, new_len)
    flash_write_span(ser, FLASH_BASE + addr, header + payload)
    _remember(ser, data_type, addr, new_len)      # запис скинув кеш -- тут відомо точно, де тепер цей блок
    return True, ("оновлено існуючий блок @+%d" % addr) if kind == "existing" else ("створено новий блок @+%d" % addr)


def read_block(ser, data_type, max_len):
    """Прочитати вміст блоку (без заголовка) або None, якщо блоку немає.
    R71: якщо розташування відоме, заголовок і дані беруться ОДНИМ запитом і заголовок звіряється (тип і довжина); розбіжність -- повний обхід."""
    loc = _LOCS.get(_key(ser), {}).get(data_type)
    if loc is not None:
        addr, dlen = loc
        n = min(dlen, max_len)
        try:
            raw = _read_region(ser, addr, HDR_LEN + n)
        except Exception:  # noqa: BLE001
            raw = b""
        if len(raw) == HDR_LEN + n and struct.unpack("<ii", raw[:HDR_LEN]) == (data_type, dlen):
            return raw[HDR_LEN:]
        invalidate(ser)
    kind, addr, existLen = _scan(ser, data_type, 0)
    if kind != "existing":
        return None
    n = min(existLen, max_len)
    return _read_region(ser, addr + HDR_LEN, n)


# ---------------------------------------------------------------------------------------------------------------------------------
#  R35: «вилучення» блока
# ---------------------------------------------------------------------------------------------------------------------------------
# Прошивка не вміє видаляти блок: область -- послідовність {тип, довжина}+дані, і скануються вони підряд (codeplugGetOpenGD77CustomDataStartAddressForType).
# Блок з ІНШИМ типом просто пропускається за довжиною -- тож «вилучити» блок можна, змінивши в його заголовку лише тип на невикористовуваний (довжина й дані
# лишаються, наступні блоки не рухаються). Прошивка перестає бачити блок: заставка й мелодія повертаються до вбудованих. Місце блока не звільняється (нова картинка
# піде в перший вільний слот у кінці), тож повторне додавання/вилучення поступово заповнює область -- про це сказано в панелях. Тип = RETIRED_BASE + колишній тип.
RETIRED_BASE = 0x7E000000


def is_retired(data_type):
    return RETIRED_BASE <= data_type < RETIRED_BASE + 0x100000


def retire_block(ser, data_type):
    """Вилучити блок типу data_type (див. вище). Повертає (True, текст) або (False, причина). Пише ЛИШЕ 4 байти типу в заголовку блока."""
    kind, addr, ln = find_or_alloc_block(ser, data_type, 0)
    if kind is None:
        return False, "області OpenGD77 нема"
    if kind != "existing":
        return False, "такого блока в рації нема"
    flash_write_span(ser, FLASH_BASE + addr, struct.pack("<i", RETIRED_BASE + data_type))
    kind2, _a, _l = find_or_alloc_block(ser, data_type, 0)
    if kind2 == "existing":
        return False, "блок вилучено не було: після запису прошивка його ще бачить -- повторіть"
    return True, "блок типу %d вилучено (заголовок @+%d, довжина %d Б лишається зайнятою)" % (data_type, addr, ln)

