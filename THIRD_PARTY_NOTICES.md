# Сторонні компоненти і їхні ліцензії

Цей файл лише **перелічує** сторонні компоненти, які входять до репозиторію або до збірки CPS, і вказує назву ліцензії та
офіційну сторінку. Тексти ліцензій тут не відтворюються: діє той текст, який лежить поруч із самим компонентом (шляхи нижче),
або той, що на офіційній сторінці. Це не юридична консультація; перед поширенням збірок звірте умови самостійно.

Ліцензія самого форку — `license.txt` у корені (див. нижче «OpenGD77»). Вона **не є GPL** і містить заборону комерційного
використання.

## Прошивка (каталог `MDUV380_firmware/`)

| Компонент | Де в репозиторії | Версія (де вказана) | Ліцензія (за файлами репозиторію) | Офіційна сторінка |
|---|---|---|---|---|
| **OpenGD77** — основа прошивки | `MDUV380_firmware/application/`, `license.txt` | R20260131 (за `README.md`) | BSD-3-Clause-подібна, **з пунктом 4: заборонено використання вихідного коду й бінарних релізів у комерційних цілях** (повний текст — `license.txt`; такий самий заголовок у вихідних файлах). Копірайт: «OpenGD77 firmware developers»; частина файлів — Kai Ludwig, DG4KLU | <https://opengd77.com> |
| Блок кодека AMBE (передкомпільований; `codec_bin.S` вбудовує `application/source/linkerdata/codec_bin_section_1.bin`) | `application/source/dmr_codec/`, `application/source/linkerdata/` | з OpenGD77 (версія блока не зафіксована в репозиторії) | умови заголовка файла (ті самі, що в OpenGD77, з пунктом 4). Сам бінарний блок успадковано з OpenGD77; цей файл його ліцензію й патентний статус не змінює | <https://opengd77.com> |
| **tiny-AES-c** (скорочена копія, лише шлях шифрування) | `application/source/crypto/dmr_aes.c` | не зафіксована (у коментарі файла: «trimmed tiny-AES (kokke/tiny-AES-c)») | public domain — так сказано в коментарі файла | <https://github.com/kokke/tiny-AES-c> |
| **FreeRTOS Kernel** | `Middlewares/Third_Party/FreeRTOS/` | V10.3.1 (за `tasks.c`) | MIT — `Middlewares/Third_Party/FreeRTOS/Source/LICENSE` | <https://www.freertos.org> |
| **CMSIS** (ARM) | `Drivers/CMSIS/` | не зафіксована | Apache License 2.0 — `Drivers/CMSIS/LICENSE.txt` | <https://www.apache.org/licenses/> (текст ліцензії) |
| **STM32F4xx HAL Driver** (STMicroelectronics) | `Drivers/STM32F4xx_HAL_Driver/` | не зафіксована | BSD-3-Clause — `Drivers/STM32F4xx_HAL_Driver/LICENSE.txt` | <https://opensource.org/licenses/BSD-3-Clause> |
| **STM32 USB Device Library** (STMicroelectronics) | `Middlewares/ST/STM32_USB_Device_Library/` | не зафіксована | SLA0044 — `Middlewares/ST/STM32_USB_Device_Library/LICENSE.txt` | сторінка STMicroelectronics |
| **SEGGER RTT** | `SeggerRTT/` | (c) 1995–2019 SEGGER Microcontroller GmbH (за заголовком) | умови в заголовку `SeggerRTT/RTT/SEGGER_RTT.c` (одна умова: зберегти копірайт, умову й відмову від гарантій) | <https://www.segger.com> |

## CPS для Windows (`TYT MD-UV390UKR.exe`, збирається PyInstaller-ом)

Версії — закріплені в `MDUV380_firmware/tools/requirements-cps.txt` (визначені `pip` у чистому середовищі Python 3.12 2026-11-24;
з логом зеленої збірки CI не звірені). Ліцензії — за метаданими цих пакетів.

| Компонент | Версія | Ліцензія (за метаданими пакета) | Офіційна сторінка |
|---|---|---|---|
| **libusb** (рідна бібліотека libusb-1.0, яку тягне обгортка `libusb` з PyPI) | обгортка `libusb` 1.0.30.post2 (документація пакета посилається на libusb 1.0.30) | **LGPL-2.1** — ліцензія самої бібліотеки libusb (у метаданих обгортки це не вказано, окремо не перевірялось); сама Python-обгортка з PyPI — Zlib за метаданими. Зверніть увагу: .exe з PyInstaller (onefile) поширюється разом із цією бібліотекою — вимоги LGPL (вихідний код/можливість заміни) перевіряйте самостійно | <https://libusb.info/> |
| **PyUSB** | 1.3.1 | BSD (за класифікатором пакета) | <https://pyusb.github.io/pyusb> |
| **pySerial** | 3.5 | BSD | <https://github.com/pyserial/pyserial> |
| **cryptography** | 50.0.2 | Apache-2.0 або BSD (файли `LICENSE.APACHE` і `LICENSE.BSD` у пакеті) | <https://cryptography.io/> |
| **PyInstaller** | 6.22.3 | GPL-2.0-or-later зі спеціальним винятком, що дозволяє збирати й поширювати програми, зокрема не вільні (за метаданими пакета) | <https://pyinstaller.org> |
| pyinstaller-hooks-contrib | 2026.10 | Apache-2.0 / GPL-2.0 (за класифікаторами пакета) | <https://github.com/pyinstaller/pyinstaller-hooks-contrib> |
| Pillow, numpy, scipy (лише для тестів і службових скриптів, у прошивку й .exe не входять) | не закріплені | не перевірялись у цьому файлі | — |

## Що НЕ перевірялось

- Точні версії CMSIS, HAL і USB Device Library не зазначені у файлах репозиторію.
- Ліцензії транзитивних Python-залежностей (altgraph, packaging, setuptools, cffi та ін.), які PyInstaller може вбудувати в
  .exe, окремо не перелічено.
- Чи сумісні умови LGPL-2.1 (libusb) і пункт 4 ліцензії OpenGD77 з вашим способом поширення — це питання до власника
  проєкту/юриста.
