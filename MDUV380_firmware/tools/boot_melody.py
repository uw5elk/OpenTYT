# -*- coding: utf-8 -*-
"""R35, частина C: мелодія вмикання (custom-data блок BEEP = тип 2).

ФОРМАТ -- ЛИШЕ З КОДУ ПРОШИВКИ (user_interface/uiSplashScreen.c, functions/sound.c soundCreateSong(), таблиця freqs[64]):

  * Блок -- послідовність ПАР байтів {нота, тривалість}. Нота -- ІНДЕКС 0..63 у таблиці freqs[64] (ЧАСТОТА НЕ ЗАПИСУЄТЬСЯ -- лише номер з 64 фіксованих тонів;
    індекс 0 = пауза, 0 Гц; решта -- 104..3729 Гц, півтони, формула round(98 * 2^(k/12)), тобто k = 1 -- соль#2). Індекс > 63 прошивка обмежує до 63 (CLAMP).
  * Тривалість -- ОДИН байт, одиниця 27 мс (melody[2*i+1] * 27): 27..6885 мс. Тривалість 0 = КІНЕЦЬ мелодії (цикл `break`). Максимум 255 пар (цикл i < 255).
  * uiSplashScreen читає блок у melodyBuf[512] НА СТЕКУ з обмеженням у 512 байтів (codeplugGetOpenGD77CustomDataBounded) і НЕ обнуляє буфер перед читанням: байти
    після кінця блока -- сміття стека. Тому в блоці ОБОВ'ЯЗКОВИЙ термінатор (пара з тривалістю 0), якщо нот менше 255.
  * Особливий випадок: ПЕРШІ ДВА БАЙТИ блока == 0 ("Zero length boot melody") -- заставка й мелодія пропускаються взагалі, рація одразу переходить у робочий екран.
  * Мелодія грається, поки не скінчиться або не натиснуть клавішу: коли melody_play стає NULL, заставка закривається. Мелодія з однієї паузи
    тому означає «тиша N секунд, потім далі», а не «без мелодії».
  * Блока нема -- грається вбудована MELODY_POWER_ON (880 Гц: довга-коротка-довга-коротка-довга).
  * ДОВЖИНУ НАЯВНОГО БЛОКА МІНЯТИ НЕ МОЖНА (codeplugSetOpenGD77CustomData), тому новий блок створюється довжиною рівно 512 Б (максимум, що прошивка читає) і добивається
    нулями; в наявний блок іншої довжини мелодія пишеться лише якщо вміщується разом із термінатором -- інакше потрібно «вилучити» старий блок і створити новий
    (custom_data.retire_block). «Без мелодії» в сенсі «стокова» = вилучити блок.

Модуль без Tk і без рації. Програвання на комп'ютері -- лише через winsound (stdlib, Windows); без нього показуємо ноти."""
import math
import struct
import time

BLOCK_TYPE = 2                    # CODEPLUG_CUSTOM_DATA_TYPE_BEEP
UNIT_MS = 27                      # sound.c: melody[2*i+1] * 27
MAX_NOTES = 255                   # for (i < 255)
BLOCK_LEN = 512                   # розмір melodyBuf у uiSplashScreen.c

# sound.c: static const int16_t freqs[64]
FREQS = (0, 104, 110, 117, 123, 131, 139, 147, 156, 165, 175, 185, 196, 208, 220, 233, 247, 262, 277, 294, 311, 330, 349, 370, 392, 415, 440, 466, 494, 523, 554,
         587, 622, 659, 698, 740, 784, 831, 880, 932, 988, 1047, 1109, 1175, 1245, 1319, 1397, 1480, 1568, 1661, 1760, 1865, 1976, 2093, 2217, 2349, 2489, 2637,
         2794, 2960, 3136, 3322, 3520, 3729)
assert len(FREQS) == 64

# вбудована MELODY_POWER_ON (sound.c): DIT_LENGTH 60 мс, DAH_LENGTH 180 мс; пауза між знаками 60 мс
STOCK_POWER_ON = ((880, 180), (0, 60), (880, 60), (0, 60), (880, 180), (0, 60), (880, 60), (0, 60), (880, 180))

NOTE_NAMES = ("до", "до#", "ре", "ре#", "мі", "фа", "фа#", "соль", "соль#", "ля", "ля#", "сі")


class MelodyError(ValueError):
    """Мелодію неможливо записати або прочитати (пояснення словами)."""


def note_name(idx):
    """Назва ноти за індексом 0..63 (0 -- пауза). Індекс 1 = соль#2 (104 Гц): MIDI 43 + k, соль2 = MIDI 43."""
    if idx == 0:
        return "пауза"
    midi = 43 + idx
    return "%s%d" % (NOTE_NAMES[midi % 12], midi // 12 - 1)


def nearest_note(hz):
    """Частота (Гц) -> найближчий індекс 1..63 (за відношенням частот); 0 Гц -> 0 (пауза)."""
    if hz <= 0:
        return 0
    best, bd = 1, None
    for k in range(1, 64):
        d = abs(math.log(FREQS[k] / float(hz)))
        if bd is None or d < bd:
            best, bd = k, d
    return best


def ms_to_units(ms):
    """Мс -> одиниці 27 мс (1..255), округлення до найближчої."""
    return max(1, min(255, int(round(ms / float(UNIT_MS)))))


class Tone:
    """Один тон: нота 0..63 і тривалість в одиницях 27 мс (1..255)."""

    def __init__(self, note, units):
        if not (0 <= note <= 63):
            raise MelodyError("нота має бути від 0 до 63 (є %s)" % note)
        if not (1 <= units <= 255):
            raise MelodyError("тривалість має бути від 1 до 255 одиниць по 27 мс (є %s)" % units)
        self.note, self.units = int(note), int(units)

    @classmethod
    def from_hz_ms(cls, hz, ms):
        return cls(nearest_note(hz), ms_to_units(ms))

    @property
    def hz(self):
        return FREQS[self.note]

    @property
    def ms(self):
        return self.units * UNIT_MS

    def __eq__(self, other):
        return isinstance(other, Tone) and (self.note, self.units) == (other.note, other.units)

    def __repr__(self):
        return "Tone(%d, %d)" % (self.note, self.units)

    def text(self):
        return "%s, %d Гц, %d мс" % (note_name(self.note), self.hz, self.ms)


def total_ms(tones):
    return sum(t.ms for t in tones)


def build(tones, length=BLOCK_LEN, skip_splash=False):
    """Тони -> байти блока рівно `length` (добивка нулями). skip_splash=True -- блок «пропустити заставку»: перші два байти 0.
    MelodyError, якщо не вміщується разом із термінатором."""
    if skip_splash:
        return bytes(length)
    if not tones:
        raise MelodyError("мелодія порожня (для «без заставки» використайте окремий режим)")
    if len(tones) > MAX_NOTES:
        raise MelodyError("тонів %d, а прошивка грає не більше %d" % (len(tones), MAX_NOTES))
    body = b"".join(struct.pack("BB", t.note, t.units) for t in tones)
    need = len(body) + (0 if len(tones) == MAX_NOTES else 2)       # термінатор потрібен, якщо нот менше 255
    if need > length:
        raise MelodyError("мелодія займає %d Б (з термінатором), а блок у рації має лише %d Б; довжину наявного блока міняти не можна" % (need, length))
    return body.ljust(length, b"\x00")


def parse(data):
    """Байти блока -> (список Tone, skip_splash, зауваження). Читає так само, як прошивка: у межах перших 512 Б, до пари з нульовою тривалістю або 255 пар."""
    data = bytes(data)[:BLOCK_LEN]
    notes = []
    if len(data) >= 2 and data[0] == 0 and data[1] == 0:
        return [], True, ["перші два байти нульові: рація пропускає заставку й мелодію"]
    warns = []
    i = 0
    ended = False
    while i < MAX_NOTES and 2 * i + 1 < len(data):
        n, d = data[2 * i], data[2 * i + 1]
        if d == 0:
            ended = True
            break
        if n > 63:
            warns.append("нота %d > 63 -- прошивка обмежить її до 63" % n)
            n = 63
        notes.append(Tone(n, d))
        i += 1
    if not ended and i < MAX_NOTES:
        warns.append("блок закінчується без термінатора (нульової тривалості): прошивка прочитає за його межею сміття зі стека")
    return notes, False, warns


# ---------------------------------------------------------------------------------------------------------------------------------
#  Готові мелодії
# ---------------------------------------------------------------------------------------------------------------------------------

MORSE = {"A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.", "G": "--.", "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..",
         "M": "--", "N": "-.", "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.", "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
         "Y": "-.--", "Z": "--..", "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-", "5": ".....", "6": "-....", "7": "--...",
         "8": "---..", "9": "----.", "/": "-..-.", "?": "..--.."}


def morse_tones(text, hz=880, dit_ms=60):
    """Текст -> тони азбуки Морзе (крапка = dit, тире = 3 dit, пауза між знаками = dit, між літерами = 3 dit, між словами = 7 dit; одиниця 27 мс округлюється)."""
    out = []

    def add(h, ms):
        out.append(Tone.from_hz_ms(h, ms))
    for w, word in enumerate(text.upper().split()):
        for k, ch in enumerate(word):
            code = MORSE.get(ch)
            if code is None:
                raise MelodyError("символу «%s» нема в таблиці Морзе (є літери A-Z, цифри, / і ?)" % ch)
            for j, s in enumerate(code):
                add(hz, dit_ms if s == "." else 3 * dit_ms)
                if j < len(code) - 1:
                    add(0, dit_ms)
            if k < len(word) - 1:
                add(0, 3 * dit_ms)
        if w < len(text.split()) - 1:
            add(0, 7 * dit_ms)
    return out


def _seq(*pairs):
    return [Tone.from_hz_ms(h, ms) for h, ms in pairs]


PRESETS = (
    ("stock", "Вбудована (наближено)", "Те саме, що грає рація без блока, але з тривалостями, округленими до 27 мс: 180 -> 189 мс, 60 -> 54 мс.",
     lambda: _seq(*STOCK_POWER_ON)),
    ("rise", "Три тони вгору", "до-мі-соль, по 150 мс.", lambda: _seq((523, 150), (659, 150), (784, 300))),
    ("hello", "Привітання", "Чотири ноти вгору й довга.", lambda: _seq((440, 120), (554, 120), (659, 120), (880, 400))),
    ("bell", "Дзвінок", "Два тони по черзі.", lambda: _seq((988, 200), (0, 54), (784, 200), (0, 54), (988, 200), (0, 54), (784, 400))),
    ("siren", "Сирена", "Вгору-вниз.", lambda: _seq((440, 200), (587, 200), (784, 200), (587, 200), (440, 200))),
    ("morse73", "Морзе «73»", "Вітання радіоаматорів, 880 Гц.", lambda: morse_tones("73")),
    ("silence", "Тиша на 2 с", "Одна пауза: заставка видна 2 с без звуку, потім рація переходить далі.", lambda: [Tone(0, ms_to_units(2000))]),
)


def preset(key):
    for k, _t, _d, make in PRESETS:
        if k == key:
            return make()
    raise MelodyError("невідома готова мелодія «%s»" % key)


# ---------------------------------------------------------------------------------------------------------------------------------
#  Програвання на комп'ютері (лише winsound)
# ---------------------------------------------------------------------------------------------------------------------------------

def player():
    """Функція beep(hz, ms) з winsound або None, якщо його нема (не Windows) -- тоді програвання недоступне, показуємо лише ноти."""
    try:
        import winsound
        return winsound.Beep
    except ImportError:
        return None


def play(tones, beep=None, sleep=time.sleep, should_stop=None):
    """Зіграти тони. beep(hz, ms) -- winsound.Beep; пауза (нота 0) -- sleep. Повертає скільки тонів зіграно. Без beep кидає MelodyError."""
    beep = beep or player()
    if beep is None:
        raise MelodyError("програвання на цьому комп'ютері недоступне (потрібен Windows і модуль winsound з Python); ноти показано в списку")
    played = 0
    for t in tones:
        if should_stop is not None and should_stop():
            break
        if t.note == 0:
            sleep(t.ms / 1000.0)
        else:
            beep(max(37, t.hz), t.ms)
        played += 1
    return played


# ---------------------------------------------------------------------------------------------------------------------------------
#  Рація
# ---------------------------------------------------------------------------------------------------------------------------------

ST_OK, ST_ABSENT, ST_NOREGION = "ok", "absent", "noregion"
STATE_TEXT = {
    ST_OK: "мелодія є в рації",
    ST_ABSENT: "мелодії в рації нема (грає вбудована)",
    ST_NOREGION: "область custom-data у рації не знайдено (немає заголовка OpenGD77) -- записати не можна",
}


def read_melody(ser):
    """-> (стан, довжина блока|None, сирі байти|None)."""
    import custom_data as cd
    kind, addr, ln = cd.find_or_alloc_block(ser, BLOCK_TYPE, 0)
    if kind is None:
        return ST_NOREGION, None, None
    if kind == "empty":
        return ST_ABSENT, None, None
    return ST_OK, ln, cd._read_region(ser, addr + cd.HDR_LEN, ln)


def write_melody(ser, tones, skip_splash=False, replace=False):
    """Записати мелодію. Довжина: рівно довжина наявного блока, або 512, якщо блока нема. Якщо вона не вміщується в наявний блок -- RuntimeError з поясненням
    (а з replace=True старий блок вилучається й створюється новий на 512 Б). Звірка читанням. Повертає текст."""
    import custom_data as cd
    state, ln, _raw = read_melody(ser)
    if state == ST_NOREGION:
        raise RuntimeError("мелодія не записана: " + STATE_TEXT[state])
    notes = ""
    length = ln if state == ST_OK else BLOCK_LEN
    try:
        payload = build(tones, length, skip_splash)
    except MelodyError as e:
        if state == ST_OK and replace:
            payload = build(tones, BLOCK_LEN, skip_splash)
            ok, msg = cd.retire_block(ser, BLOCK_TYPE)
            if not ok:
                raise RuntimeError("старий блок мелодії не вилучено: " + msg)
            notes = " Старий блок (%d Б) вилучено, створено новий на %d Б." % (ln, BLOCK_LEN)
        else:
            raise RuntimeError("мелодія не записана: %s" % e)
    ok, msg = cd.write_block(ser, BLOCK_TYPE, payload)
    if not ok:
        raise RuntimeError("мелодія не записана: " + msg)
    back = cd.read_block(ser, BLOCK_TYPE, len(payload))
    if back != payload:
        raise RuntimeError("мелодія записана, але звірка читанням НЕ збіглася -- повторіть запис")
    return "Мелодія записана (%s).%s Звірка читанням: OK." % (msg, notes)


def remove_melody(ser):
    """Повернути вбудовану мелодію: вилучити блок."""
    import custom_data as cd
    ok, msg = cd.retire_block(ser, BLOCK_TYPE)
    if not ok:
        raise RuntimeError("блок мелодії не вилучено: " + msg)
    return "Блок мелодії вилучено (%s). Рація знову грає вбудовану мелодію." % msg
