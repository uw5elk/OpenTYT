# -*- coding: utf-8 -*-
"""R76: автоматичне виявлення рації за СПИСКОМ портів. Без Tk і без відкриття портів.

Раз на ~1,5 с дивимось лише у список послідовних портів ОС (pyserial list_ports) -- порт при цьому НЕ відкривається. Коли порт із ознаками
рації (VID/PID 1fc9:0094, ті самі, що в cps_link.find_port) з'являється, а застосунок вважає, що рації нема, застосунок запускає наявну
процедуру пошуку («Оновити»: RadioConnection.probe), яка вже сама відкриває порт на мить. Коли порт зникає -- рація «не знайдена».

Запобіжники (усі в PortDetector, перевіряє test_r76.py):
  * огляд не стартує, поки зайнято (`blocked()`: операція, повторний пошук R73 після запису, модальне вікно) -- і результат огляду, що завершився
    вже під час такої зайнятості, відкидається;
  * дебаунс: зміна визнається лише після того, як два огляди ПІДРЯД дали однаковий список (мерехтіння порту при перезавантаженні не рахується);
  * не більше однієї спроби підключення на одну зміну списку портів; жодних циклів повторів;
  * помилка огляду (немає pyserial, збій ОС) пишеться в журнал один раз і не зациклюється: період огляду збільшується.
"""
import cps_link as cl

SCAN_MS = 1500                # період огляду списку портів
SCAN_MS_AFTER_ERROR = 10000   # після помилки огляду
DEBOUNCE = 2                  # скільки однакових оглядів підряд потрібно для визнання зміни


def scan_radio_ports():
    """Кортеж (відсортований) імен портів із ознаками рації. Лише читає список ОС, порти не відкриває."""
    try:
        from serial.tools import list_ports
    except ImportError:
        raise cl.CpsError("потрібен pyserial: pip install pyserial")
    return tuple(sorted(p.device for p in list_ports.comports() if p.vid == cl.RADIO_VID and p.pid == cl.RADIO_PID))


class PortDetector:
    """Логіка виявлення. scan() -> кортеж портів (або кидає виняток); blocked() -> True, якщо зараз не можна втручатись; log(text)."""

    def __init__(self, scan, blocked, log=print, debounce=DEBOUNCE):
        self.scan = scan
        self.blocked = blocked
        self.log = log
        self.debounce = max(1, debounce)
        self.stable = None            # останній підтверджений кортеж портів (None -- ще не знаємо)
        self._cand = None
        self._streak = 0
        self._inflight = False
        self._last_error = None
        self.errors = 0

    def next_delay_ms(self):
        return SCAN_MS_AFTER_ERROR if self.errors else SCAN_MS

    def begin(self):
        """True, якщо можна запускати огляд зараз (і позначає його як такий, що триває)."""
        if self._inflight:
            return False
        if self.blocked():
            self._cand, self._streak = None, 0          # серія оглядів перервана: рахуємо знову, коли звільниться
            return False
        self._inflight = True
        return True

    def scan_safely(self):
        """Виконати огляд (можна з потоку). Повертає кортеж або виняток (не кидає)."""
        try:
            return tuple(self.scan())
        except Exception as e:  # noqa: BLE001 -- помилка огляду не повинна валити застосунок
            return e

    def finish(self, result, conn_found, conn_port):
        """Прийняти результат огляду. Повертає 'appeared' (запустити пошук рації), 'vanished' (рація зникла) або None."""
        self._inflight = False
        if isinstance(result, Exception):
            self.errors += 1
            self._cand, self._streak = None, 0
            if str(result) != self._last_error:
                self._last_error = str(result)
                self.log("Автопошук рації: не вдалося переглянути список портів: %s" % result)
            return None
        self.errors, self._last_error = 0, None
        if self.blocked():                              # поки огляд ішов, почалась операція -- результат застарів
            self._cand, self._streak = None, 0
            return None
        if result == self._cand:
            self._streak += 1
        else:
            self._cand, self._streak = result, 1
        if self._streak != self.debounce:               # реакція рівно один раз: коли серія досягла дебаунсу
            return None
        changed = result != self.stable
        self.stable = result
        if not changed:
            return None
        if result:
            # порт є: підключаємось, якщо рації нема в стані «знайдено» або вона знайдена на іншому порту
            if not conn_found or (conn_port is not None and conn_port not in result):
                return "appeared"
            return None
        return "vanished" if conn_found else None

    def tick_sync(self, conn_found, conn_port):
        """Один синхронний цикл (для тестів): begin -> scan -> finish."""
        if not self.begin():
            return None
        return self.finish(self.scan_safely(), conn_found, conn_port)
