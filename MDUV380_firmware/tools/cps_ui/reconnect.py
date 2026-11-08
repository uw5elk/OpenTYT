# -*- coding: utf-8 -*-
"""R73: повторний пошук рації після перезавантаження ОПИТУВАННЯМ замість сліпого очікування (раніше: рівно reconnect_ms = 6000 мс, потім одна спроба).

Правила (чиста логіка без Tk і без порту, щоб перевіряти з підробленим годинником):
  * перша спроба не раніше MIN_FIRST_MS (рація щойно отримала «C 6 1»; USB-пристрій ще може бути старий) -- пауза, потрібна, щоб вона встигла перезавантажитись, лишилась;
  * далі спроба кожні STEP_MS замість очікування до кінця ліміту;
  * «знайдено» приймається, коли рація відповіла CONFIRM разів ПІДРЯД і до того вона або зникала з порту (бачили «нема»), або минуло SETTLE_MS від команди -- щоб не
    сприйняти ще не перезавантажену рацію за вже готову;
  * верхня межа та сама, що була (limit_ms): на ній береться підсумок останньої спроби, як і раніше.
Не змінює протокол і нічого не пише в рацію: опитування -- лише пошук порту й читання RADIO_INFO (cps_ui/connection.py)."""

MIN_FIRST_MS = 2000
STEP_MS = 500
CONFIRM = 2
SETTLE_MS = 3500


class ReconnectPolicy:
    def __init__(self, limit_ms, clock):
        self.limit_ms = limit_ms
        self.clock = clock
        self.t0 = clock()
        self.ok = 0
        self.saw_absent = False
        self.tries = 0

    def elapsed_ms(self):
        return (self.clock() - self.t0) * 1000.0

    def first_delay_ms(self):
        return min(MIN_FIRST_MS, self.limit_ms)

    def feed(self, found):
        """Результат спроби -> ("done", None) | ("retry", затримка_мс). На межі limit_ms завжди ("done", ...) -- підсумок останньої спроби."""
        self.tries += 1
        el = self.elapsed_ms()
        if found:
            self.ok += 1
            if self.ok >= CONFIRM and (self.saw_absent or el >= SETTLE_MS):
                return "done", None
        else:
            self.ok = 0
            self.saw_absent = True
        if el + STEP_MS > self.limit_ms:
            return "done", None
        return "retry", STEP_MS
