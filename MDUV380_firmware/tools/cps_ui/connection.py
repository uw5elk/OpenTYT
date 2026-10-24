# -*- coding: utf-8 -*-
"""Єдине підключення до рації для всього застосунку (етап 1, P2).

Рацію шукаємо ОДИН раз (при старті) і ще раз лише за кнопкою «Оновити» (та після дій, що перезавантажують рацію); результат
кешуємо. Порт відкривається тільки на час самої операції -- тут він відкривається на мить, щоб прочитати RADIO_INFO.
Жодних команд, що змінюють рацію (зокрема 'C',0 з екраном CPS), пошук не надсилає: open_radio() їх не шле, radio_info() лише читає.

Заряд акумулятора CPS-протокол НЕ віддає (у RADIO_INFO такого поля нема) -- це правда, а не недогляд; прошивку ми не змінюємо.
"""
import cps_link as cps

# Тип рації з usb_com.c (radioType у RADIO_INFO)
RADIO_TYPE_NAMES = {0: "GD-77", 1: "GD-77S", 2: "DM-1801", 3: "RD-5R", 4: "DM-1801A", 5: "MD-9600",
                    6: "MD-UV380/UV390 (MDUV380)", 7: "MD-380", 8: "DM-1701", 9: "MD-2017", 10: "DM-1701"}

BATTERY_NOTE = "недоступно: CPS-протокол не передає заряд акумулятора"
NOT_FOUND_REASON = ("Рацію не знайдено. Підключи USB-кабель, увімкни рацію звичайним способом (НЕ в DFU) і натисни «Оновити» "
                    "у розділі «Підключення і стан».")
SEARCHING_REASON = "Шукаю рацію..."


class RadioConnection:
    """state: 'unknown' (ще не шукали / шукаємо), 'found', 'absent'."""

    def __init__(self):
        self.state = "unknown"
        self.port = None
        self.info = None           # словник cps.CpsLink.radio_info() або None
        self.error = None          # текст, якщо порт знайдено, а прочитати RADIO_INFO не вдалося
        self.searched = False

    @property
    def found(self):
        return self.state == "found"

    def model_name(self):
        if not self.info:
            return None
        t = self.info.get("radioType")
        return RADIO_TYPE_NAMES.get(t, "невідомий тип %s" % t)

    def is_expected_model(self):
        return bool(self.info) and self.info.get("radioType") == cps.RADIO_TYPE_MDUV380

    def reason(self):
        """Чому дії, що потребують рації, зараз вимкнені (None -- рацію знайдено)."""
        if self.state == "found":
            return None
        return SEARCHING_REASON if self.state == "unknown" else NOT_FOUND_REASON

    def invalidate(self):
        self.state = "unknown"

    def mark_absent(self):
        self.state = "absent"
        self.port = None
        self.info = None
        self.searched = True

    def probe(self, log=print):
        """Знайти порт і прочитати RADIO_INFO. Викликається з робочого потоку (відкриває послідовний порт). Не кидає винятків."""
        self.error = None
        try:
            port = cps.find_port()
        except cps.CpsError as e:          # напр. нема pyserial
            self.mark_absent()
            self.error = str(e)
            log("Пошук рації: %s" % e)
            return self
        if not port:
            self.mark_absent()
            log("Рацію не знайдено у звичайному режимі.")
            return self
        self.port = port
        self.state = "found"
        self.searched = True
        self.info = None
        try:
            ser = cps.open_radio(port)
            try:
                self.info = cps.CpsLink(ser).radio_info()
            finally:
                ser.close()
        except Exception as e:  # noqa: BLE001 -- порт є, а відповіді нема: покажемо причину, але рацію вважаємо знайденою
            self.error = str(e)
            log("Рацію знайдено на %s, але прочитати версію не вдалося: %s" % (port, e))
            return self
        log("Рація на %s: %s, прошивка %s (збірка %s)." % (port, self.model_name(), self.info.get("gitRevision") or "?",
                                                         self.info.get("buildDateTime") or "?"))
        return self
