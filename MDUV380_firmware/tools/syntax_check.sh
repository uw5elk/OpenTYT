#!/usr/bin/env bash
#
# Швидка СИНТАКСИЧНА перевірка коду прошивки звичайним хостовим gcc (x86), без
# ARM-тулчейну. Запускати з будь-якої теки:
#
#     MDUV380_firmware/tools/syntax_check.sh                 # усі файли application/source
#     MDUV380_firmware/tools/syntax_check.sh path/to/file.c  # лише вказані файли
#
# НАВІЩО ЦЕ ІСНУЄ
# ---------------
# Двічі поспіль (коміти 8aab1f5 і fd1ef9a) збірка CI падала через помилку, яку не
# можна побачити ані оком, ані перевіркою балансу дужок: у коментарі rctl_ua.h був
# текст "RCFG_*/RCTL_*", де послідовність "*/" передчасно ЗАКРИВАЛА блочний коментар,
# і компілятор переставав бачити цілий enum у файлі, що його підключав. Такі речі
# ловить тільки справжній прохід компілятора.
#
# Виявилось, що для цього НЕ потрібен ARM-тулчейн: CMSIS, HAL і FreeRTOS вендеровані
# прямо в цьому репозиторії, тож хостовому gcc бракує рівно одного заголовка з newlib
# (<reent.h>) -- і той підкладається заглушкою з tools/hoststub/. Прохід по всіх ~90
# файлах application/source займає секунди й не потребує нічого, крім gcc.
#
# МЕЖІ ЗАСТОСУВАННЯ -- ЧИТАТИ ОБОВ'ЯЗКОВО
# ---------------------------------------
# Це НЕ заміна справжній збірці. Тут -fsyntax-only і хостовий x86-gcc, тому:
#   * НЕ генерується код, не лінкується, не рахується розмір прошивки;
#   * розміри/вирівнювання типів і поведінка, залежна від цілі, ІНШІ, ніж на Cortex-M4;
#   * помилки лінкування (напр. відсутнє визначення функції) тут не видно.
# Перевіряє: синтаксис, оголошення/типи, помилки в коментарях, аргументи функцій,
# формати printf тощо -- тобто рівно той клас багів, що ламав CI.
# Остаточне слово завжди за збіркою arm-none-eabi-gcc у GitHub Actions.
#
# Набори прапорців нижче навмисно збігаються з УСІМА трьома робочими job'ами збірки
# в .github/workflows/build.yml (build ENABLE_AES=0, build ENABLE_AES=1, build-ukrainian).
#
# ЩЕ ОДНА ПРИЧИНА ІСНУВАННЯ (2026-09-18): раніше тут був ОДИН жорстко заданий набір
# defines -- саме конфігурація build-ukrainian (LANGUAGE_BUILD_UKRAINIAN завжди
# ввімкнено). Коміт 90097cc (попап потужності) додав у uiNotification.c безумовне
# звертання до currentLanguage->power -- поля, що існує в stringsTable_t лише під
# LANGUAGE_BUILD_UKRAINIAN. Ця перевірка його не спіймала: вона й сама завжди
# компілювала з тим самим прапорцем, тож job'и build(ENABLE_AES=0) і
# build(ENABLE_AES=1) впали в CI, а syntax_check.sh локально був зелений. Тепер
# перевірка проганяє КОЖЕН файл через ВСІ конфігурації матриці -- саме той клас
# розбіжності "поле існує лише в одній конфігурації" тепер ловиться тут, за секунди,
# без ARM-тулчейну.

set -u

FW_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$FW_DIR" || exit 1

CC="${CC:-gcc}"

if ! command -v "$CC" >/dev/null 2>&1; then
	echo "ПОМИЛКА: не знайдено компілятор '$CC'." >&2
	exit 2
fi

INCS=(
	-Itools/hoststub                 # заглушка <reent.h>, див. коментар у тому файлі
	-include tools/hoststub/host_compat.h  # прототипи newlib, яких немає в glibc (itoa)
	-I. -ICore/Inc
	-IDrivers/CMSIS/Device/ST/STM32F4xx/Include -IDrivers/CMSIS/Include
	-IDrivers/STM32F4xx_HAL_Driver/Inc -IDrivers/STM32F4xx_HAL_Driver/Inc/Legacy
	-IMiddlewares/ST/STM32_USB_Device_Library/Class/CDC/Inc
	-IMiddlewares/ST/STM32_USB_Device_Library/Core/Inc
	-IMiddlewares/Third_Party/FreeRTOS/Source/CMSIS_RTOS_V2
	-IMiddlewares/Third_Party/FreeRTOS/Source/include
	-IMiddlewares/Third_Party/FreeRTOS/Source/portable/GCC/ARM_CM4F
	-IUSB_DEVICE/App -IUSB_DEVICE/Target -Iapplication/include
)

# Спільні для всіх трьох конфігурацій прапорці.
DEFS_COMMON=(
	-DUSE_HAL_DRIVER -DSTM32F405xx
	-DPLATFORM_MDUV380 -DPLATFORM_VARIANT_UV380_PLUS_10W -DNDEBUG
	-DGITVERSION=syntaxcheck
)

# Набори -- рівно ті самі прапорці, що й job'и збірки в build.yml. Порядок значення
# не має, але імена (перший стовпець у CONFIGS нижче) йдуть у звіт.
DEFS_AES0=("${DEFS_COMMON[@]}")                                            # build (ENABLE_AES=0)
DEFS_AES1=("${DEFS_COMMON[@]}" -DENABLE_AES)                               # build (ENABLE_AES=1)
DEFS_UA=("${DEFS_COMMON[@]}" -DENABLE_AES -DENABLE_DMR_DATA -DLANGUAGE_BUILD_UKRAINIAN)  # build-ukrainian
# 2026-09-19: ENABLE_MEM_DIAG (USB CPS 0xB4, розвідка docs/recording-feasibility.md)
# навмисно перевіряється на "голій" AES0-основі, БЕЗ ENABLE_AES/ENABLE_DMR_DATA --
# саме там, куди звичайний DEFS_UA не заглядає, і де новий опкод має жити незалежно.
DEFS_MEMDIAG=("${DEFS_COMMON[@]}" -DENABLE_MEM_DIAG)                       # build (ENABLE_AES=0) + ENABLE_MEM_DIAG
# 2026-09-19: "Переслухати" (callReplay.c/menuCallReplay.c, docs/recording-feasibility.md,
# сценарій A) -- прапорець сам по собі незалежний від ENABLE_AES/LANGUAGE_BUILD_UKRAINIAN
# (currentLanguage->call_replay* під власним #if ENABLE_CALL_REPLAY, за патерном
# messages/remote_control), але в CI (build.yml) УВІМКНЕНО лише разом із build-ukrainian --
# тож перевіряємо саме ту реальну комбінацію прапорців, а не окрему "голу" основу.
DEFS_CALLREPLAY=("${DEFS_UA[@]}" -DENABLE_CALL_REPLAY)                     # build-ukrainian + ENABLE_CALL_REPLAY
# 2026-10-05 (cleanup1): ENABLE_SMS_DIAG -- уся діагностика SMS (екрани «Діагностика» 2-4,
# перемикачі, знімок PDU, USB 0x93/0x94/0x95/0x97/0xB2/0xB3). У CI НЕ вмикається, тож без цієї
# конфігурації діагностичний код ніхто б не компілював і він тихо згнив би до наступного розбору.
DEFS_SMSDIAG=("${DEFS_CALLREPLAY[@]}" -DENABLE_SMS_DIAG)                    # build-ukrainian + CALL_REPLAY + ENABLE_SMS_DIAG
# 2026-10-05 (ui5): ті самі функції форка (AES + DMR_DATA + CALL_REPLAY), але АНГЛІЙСЬКОЮ. Без цієї
# конфігурації англійські відповідники рядків з languages/*_ua.h ніхто не компілював: з 8aab1f5
# у menuRCTLRemote.c бракувало RCTL_WAITING / RCTL_HINT_CANCEL / RCTL_ACK_AGE_FMT, і така збірка
# падала, а всі 6 конфігурацій вище були чисті.
DEFS_ENDATA=("${DEFS_COMMON[@]}" -DENABLE_AES -DENABLE_DMR_DATA -DENABLE_CALL_REPLAY)  # англійська + AES + DMR_DATA

DEFS_APRSPROBE=("${DEFS_CALLREPLAY[@]}" -DENABLE_APRS_RX_PROBE)             # build-ukrainian, як у CI з R2 (тимчасово)
DEFS_APRSPROBEEN=("${DEFS_ENDATA[@]}" -DENABLE_APRS_RX_PROBE)               # англійська + прапорець: екран має зникнути без помилок

# R8: справжній приймач APRS -- користувацька українська збірка (БЕЗ проби) і її англійський двійник
# (приймач має зникнути без помилок); окремо -- без AES/DMR_DATA (приймач без сховища «Повідомлення»).
DEFS_APRSRX=("${DEFS_CALLREPLAY[@]}" -DENABLE_APRS_RX)                     # build-ukrainian + ENABLE_APRS_RX (CI, користувацька)
DEFS_APRSRXEN=("${DEFS_ENDATA[@]}" -DENABLE_APRS_RX)                       # англійська + прапорець: приймач має зникнути
DEFS_APRSRXLITE=("${DEFS_COMMON[@]}" -DLANGUAGE_BUILD_UKRAINIAN -DENABLE_APRS_RX)   # українська БЕЗ AES/DMR_DATA + приймач

# R10: діагностична збірка CI (job build-diag) БЕЗ ENABLE_CALL_REPLAY -- «Режим APRS» тут тримає стан у статичній
# структурі в CCM, а не в позиченому буфері "Переслухати" (aprs_mode.c).
DEFS_APRSPROBENOCR=("${DEFS_UA[@]}" -DENABLE_APRS_RX_PROBE)                 # build-ukrainian + проба, без "Переслухати" (як у CI)

# AES-fix2: діагностика AES (DMR_AES_DIAG_RX) і збірка-кандидат AES_TX_MI_CURRENT -- у CI їх нема, а виклики з HR-C6000.c
# (dmrAesDiagTxBurst, dmrAesTxSkipBurst) іх мають бачити; AES_TX_PHASE_FIX_OFF -- перемикач «до фіксу» для вимірювання.
DEFS_AESDIAG=("${DEFS_AES1[@]}" -DDMR_AES_DIAG_RX -DAES_TX_MI_CURRENT -DAES_TX_PHASE_FIX_OFF)

# R41: «Видалити канал» -- користувацька українська збірка CI (з ENABLE_CHANNEL_DELETE), її англійський двійник (меню й код мають зникнути без
# помилок: рядки живуть лише в українському блоці) і українська без AES/DMR_DATA.
DEFS_CHDEL=("${DEFS_APRSRX[@]}" -DENABLE_CHANNEL_DELETE)                    # build-ukrainian (CI) + ENABLE_CHANNEL_DELETE
DEFS_CHDELEN=("${DEFS_ENDATA[@]}" -DENABLE_CHANNEL_DELETE)                  # англійська + прапорець: фіча має зникнути
DEFS_CHDELLITE=("${DEFS_COMMON[@]}" -DLANGUAGE_BUILD_UKRAINIAN -DENABLE_CHANNEL_DELETE)  # українська БЕЗ AES/DMR_DATA + видалення

# R42: затримка відкриття шумодава (ENABLE_SQL_OPEN_DELAY) і перейменування зони (ENABLE_ZONE_RENAME). Користувацька українська збірка CI з обома прапорцями; англійський
# двійник (обидві фічі мають зникнути без помилок); українська БЕЗ AES/DMR_DATA/APRS_RX (затримка є, перейменування -- ні: воно потребує APRS_R21_NAMES);
# окремо кожен прапорець на користувацькій збірці (одна фіча не тягне іншу).
DEFS_R42=("${DEFS_CHDEL[@]}" -DENABLE_SQL_OPEN_DELAY -DENABLE_ZONE_RENAME)           # build-ukrainian (CI) + обидві фічі
DEFS_R42EN=("${DEFS_ENDATA[@]}" -DENABLE_SQL_OPEN_DELAY -DENABLE_ZONE_RENAME)        # англійська + прапорці: фічі мають зникнути
DEFS_R42LITE=("${DEFS_COMMON[@]}" -DLANGUAGE_BUILD_UKRAINIAN -DENABLE_SQL_OPEN_DELAY -DENABLE_ZONE_RENAME)   # українська БЕЗ AES/DMR_DATA/APRS_RX
DEFS_R42SQL=("${DEFS_APRSRX[@]}" -DENABLE_SQL_OPEN_DELAY)                            # лише затримка шумодава
DEFS_R42ZONE=("${DEFS_APRSRX[@]}" -DENABLE_ZONE_RENAME)                              # лише перейменування зони

# R43: редагування зон (ENABLE_ZONE_EDIT). Користувацька українська збірка CI з усіма фічами; англійський двійник (все має зникнути); українська БЕЗ AES/APRS_RX (немає
# ZONE_RENAME_ENABLED -> немає й ZONE_EDIT_ENABLED); редагування БЕЗ ENABLE_CHANNEL_DELETE (пункти швидкого меню незалежні); прапорець без перейменування (фіча зникає).
DEFS_R43=("${DEFS_R42[@]}" -DENABLE_ZONE_EDIT)                                       # build-ukrainian (CI) + усі фічі
DEFS_R43EN=("${DEFS_R42EN[@]}" -DENABLE_ZONE_EDIT)                                   # англійська + прапорці: фічі мають зникнути
DEFS_R43LITE=("${DEFS_R42LITE[@]}" -DENABLE_ZONE_EDIT)                               # українська БЕЗ AES/APRS_RX
DEFS_R43EDIT=("${DEFS_APRSRX[@]}" -DENABLE_ZONE_RENAME -DENABLE_ZONE_EDIT)           # редагування зон без видалення каналу
DEFS_R43NOREN=("${DEFS_APRSRX[@]}" -DENABLE_ZONE_EDIT)                               # редагування без перейменування: код має зникнути

# R44: єдиний розділ «Кодплаг» (ENABLE_CODEPLUG_MENU). Потребує ВСІХ трьох: ENABLE_CHANNEL_DELETE + ENABLE_ZONE_RENAME + ENABLE_ZONE_EDIT. Користувацька українська збірка CI;
# англійський двійник (розділ має зникнути); українська БЕЗ AES/APRS_RX; прапорець без видалення каналу й без редагування зон (розділу нема -- R41-R43 лишаються як були).
DEFS_R44=("${DEFS_R43[@]}" -DENABLE_CODEPLUG_MENU)                                   # build-ukrainian (CI) + розділ «Кодплаг»
DEFS_R44EN=("${DEFS_R43EN[@]}" -DENABLE_CODEPLUG_MENU)                               # англійська + прапорці: розділ має зникнути
DEFS_R44LITE=("${DEFS_R43LITE[@]}" -DENABLE_CODEPLUG_MENU)                           # українська БЕЗ AES/APRS_RX
DEFS_R44NODEL=("${DEFS_R43EDIT[@]}" -DENABLE_CODEPLUG_MENU)                          # без ENABLE_CHANNEL_DELETE: розділу нема
DEFS_R44NOEDIT=("${DEFS_R42[@]}" -DENABLE_CODEPLUG_MENU)                             # без ENABLE_ZONE_EDIT: розділу нема

# R58/R59: діагностика пробудження (ENABLE_WAKE_DIAG) і «Роумінг» (ENABLE_ROAM_RETRY; прототип R58 ENABLE_WAKE_HOP_TEST прибрано).
# ROAMDIAG -- та сама комбінація, що в CI-джобі build-ukrainian-roam-diag (UA + AES + DMR_DATA, БЕЗ CALL_REPLAY/APRS_RX/проби); ROAM -- ПОВНА користувацька збірка CI (як build-ukrainian) + роумінг, без журналу, як у CI-джобі
# build-ukrainian-roam; WAKEDIAG -- лише журнал без роумінгу (екрана журналу нема, USB 0xB7 є); ROAMEN -- англійські формати з обома прапорцями;
# ROAMBARE -- ROAM_RETRY на мінімальній збірці без AES/DMR_DATA (функція не залежить від них; dmrRctlIsInhibited там не викликається).
DEFS_ROAMDIAG=("${DEFS_UA[@]}" -DENABLE_WAKE_DIAG -DENABLE_ROAM_RETRY)               # build-ukrainian-roam-diag (CI)
DEFS_ROAM=("${DEFS_R44[@]}" -DENABLE_ROAM_RETRY)                                    # build-ukrainian-roam (CI): ПОВНА користувацька збірка + роумінг, без журналу
DEFS_WAKEDIAG=("${DEFS_UA[@]}" -DENABLE_WAKE_DIAG)                                   # лише журнал
DEFS_ROAMEN=("${DEFS_ENDATA[@]}" -DENABLE_WAKE_DIAG -DENABLE_ROAM_RETRY)             # англійська + обидва прапорці
DEFS_ROAMBARE=("${DEFS_COMMON[@]}" -DENABLE_ROAM_RETRY)                              # англійська без AES/DMR_DATA + ROAM_RETRY
# R64C: імена слотів AES-ключів (ENABLE_AES_KEY_NAMES). AESNAMES -- build-ukrainian (CI) + імена; ROAMAESNAMES -- build-ukrainian-roam (CI) + імена; AESNAMESEN -- англійська + прапорець (імен
# має не бути: спільний редактор лише в українській збірці); AESNAMESBARE -- прапорець без українського редактора (UA без APRS_RX/DMR_DATA ... коду нема).
DEFS_AESNAMES=("${DEFS_R44[@]}" -DENABLE_AES_KEY_NAMES)
DEFS_ROAMAESNAMES=("${DEFS_ROAM[@]}" -DENABLE_AES_KEY_NAMES)
DEFS_AESNAMESEN=("${DEFS_ENDATA[@]}" -DENABLE_AES_KEY_NAMES)
DEFS_AESNAMESBARE=("${DEFS_AES1[@]}" -DENABLE_AES_KEY_NAMES)
# R65B: редактор списків прийому (ENABLE_RXGROUP_EDIT). RXG -- build-ukrainian (CI) + списки; FULLUSER -- build-ukrainian-roam (CI) з усіма трьома прапорцями (імена ключів, списки, роумінг);
# RXGEN -- англійська з прапорцем (екрана нема); RXGBARE -- прапорець без ENABLE_CODEPLUG_MENU (RXGROUP_EDIT_ENABLED не визначається).
DEFS_RXG=("${DEFS_R44[@]}" -DENABLE_RXGROUP_EDIT)
DEFS_FULLUSER=("${DEFS_ROAM[@]}" -DENABLE_AES_KEY_NAMES -DENABLE_RXGROUP_EDIT -DENABLE_SAT_TONE_SYNC -DENABLE_VOLUME_LOW)   # R78: + «Мін.гучність» (як у CI)
# R77A: «Гучн. проба» -- користувацька конфігурація + прапорець (як у CI build-ukrainian-volprobe); англійська (пункт мусить зникнути без помилок); українська без APRS-приймача
DEFS_VOLPROBE=("${DEFS_FULLUSER[@]}" -DENABLE_VOLUME_PROBE)
DEFS_VOLPROBEEN=("${DEFS_ENDATA[@]}" -DENABLE_VOLUME_PROBE)
DEFS_VOLPROBEBARE=("${DEFS_UA[@]}" -DENABLE_VOLUME_PROBE)
# R88: ДІАГНОСТИКА сирого Talker Alias / GPS-блока LC (ENABLE_TA_DIAG). TADIAG -- як у CI build-ukrainian-tadiag (користувацька конфігурація + прапорець);
# TADIAGEN -- англійська з прапорцем (екран «TA diag» усе одно компілюється: мовних файлів він не чіпає); TADIAGBARE -- прапорець без AES/DMR_DATA.
DEFS_TADIAG=("${DEFS_FULLUSER[@]}" -DENABLE_TA_DIAG)
DEFS_TADIAGEN=("${DEFS_ENDATA[@]}" -DENABLE_TA_DIAG)
DEFS_TADIAGBARE=("${DEFS_AES0[@]}" -DENABLE_TA_DIAG)
# R91C: відстань і азимут до кореспондента (ENABLE_LC_DISTANCE). LCDIST -- користувацька конфігурація + прапорець; LCDISTEN -- англійська з прапорцем (APRS_RX нема -- код має
# лишитись мертвим); LCDISTBARE -- прапорець без AES/мови.
DEFS_LCDIST=("${DEFS_FULLUSER[@]}" -DENABLE_LC_DISTANCE)
DEFS_LCDISTEN=("${DEFS_ENDATA[@]}" -DENABLE_LC_DISTANCE)
DEFS_LCDISTBARE=("${DEFS_AES0[@]}" -DENABLE_LC_DISTANCE)
# R97: «Подвійний прийом» (ENABLE_DUAL_CHANNEL). DUALCH -- як у CI build-ukrainian (користувацька конфігурація + відстань + прапорець); DUALCHEN -- англійська з прапорцем
# (код має лишитись мертвим); DUALCHBARE -- українська з прапорцем без AES/роумінгу/APRS-приймача.
DEFS_DUALCH=("${DEFS_LCDIST[@]}" -DENABLE_DUAL_CHANNEL)
DEFS_DUALCHEN=("${DEFS_ENDATA[@]}" -DENABLE_DUAL_CHANNEL)
DEFS_DUALCHBARE=("${DEFS_UA[@]}" -DENABLE_DUAL_CHANNEL)
# R78: «Мін.гучність» (ENABLE_VOLUME_LOW). Основна -- у FULLUSER/VOLPROBE (разом з пробою). VOLLOWEN -- англійська з прапорцем (пункт мусить зникнути без помилок);
# VOLLOWBARE -- українська з прапорцем без решти; VOLLOWAPRS -- з APRS-приймачем (захист 0x44), без проби.
DEFS_VOLLOWEN=("${DEFS_ENDATA[@]}" -DENABLE_VOLUME_LOW)
DEFS_VOLLOWBARE=("${DEFS_UA[@]}" -DENABLE_VOLUME_LOW)
DEFS_VOLLOWAPRS=("${DEFS_APRSRX[@]}" -DENABLE_VOLUME_LOW)
DEFS_RXGEN=("${DEFS_ENDATA[@]}" -DENABLE_RXGROUP_EDIT)
DEFS_RXGBARE=("${DEFS_AES1[@]}" -DENABLE_RXGROUP_EDIT)
# R66D: тон супутника (ENABLE_SAT_TONE_SYNC). SATTONE -- build-ukrainian (CI) + прапорець; SATTONEEN -- англійська з прапорцем; SATTONEBARE -- лише прапорець на типовій збірці.
DEFS_SATTONE=("${DEFS_R44[@]}" -DENABLE_SAT_TONE_SYNC)
DEFS_SATTONEEN=("${DEFS_ENDATA[@]}" -DENABLE_SAT_TONE_SYNC)
DEFS_SATTONEBARE=("${DEFS_COMMON[@]}" -DENABLE_SAT_TONE_SYNC)

CONFIGS=(AES0 AES1 UA MEMDIAG CALLREPLAY SMSDIAG ENDATA APRSPROBE APRSPROBEEN APRSRX APRSRXEN APRSRXLITE APRSPROBENOCR AESDIAG CHDEL CHDELEN CHDELLITE R42 R42EN R42LITE R42SQL R42ZONE R43 R43EN R43LITE R43EDIT R43NOREN R44 R44EN R44LITE R44NODEL R44NOEDIT ROAMDIAG ROAM WAKEDIAG ROAMEN ROAMBARE AESNAMES ROAMAESNAMES AESNAMESEN AESNAMESBARE RXG FULLUSER RXGEN RXGBARE SATTONE SATTONEEN SATTONEBARE VOLPROBE VOLPROBEEN VOLPROBEBARE TADIAG TADIAGEN TADIAGBARE LCDIST LCDISTEN LCDISTBARE VOLLOWEN VOLLOWBARE VOLLOWAPRS DUALCH DUALCHEN DUALCHBARE)

# Щоб побачити попередження ВЛАСНОГО коду, запускай: SHOW_WARNINGS=1 ...
# Три класи помилок, які МАЮТЬ валити перевірку.
#
# Навіщо: 2026-09-04 ми прибрали небезпечний codeplugGetOpenGD77CustomData() з розрахунку
# "якщо злиття з upstream поверне виклик, збірка впаде". Негативний тест показав, що НЕ
# впала б: у C неявний виклик невідомої функції -- лише попередження, а -w його ковтав.
# Тобто перевірка мовчки пропускала б рівно той клас помилок, заради якого функцію й
# прибрали.
#
# ВАЖЛИВО: -w перебиває -Werror=... НЕЗАЛЕЖНО ВІД ПОРЯДКУ прапорців (перевірено на gcc
# 13.3: `gcc -w -Werror=implicit-function-declaration` мовчить). Тому в режимі за
# замовчуванням -w більше не використовується взагалі. Шум вендерованих HAL/CMSIS однаково
# не видно: цикл нижче друкує вивід лише коли там є 'error:' або коли SHOW_WARNINGS=1.
#   implicit-function-declaration -- виклик функції, якої компілятор не бачив;
#   implicit-int                  -- оголошення без типу;
#   int-conversion                -- мовчазна конверсія вказівник <-> ціле.
WARN_FLAGS=()
if [ "${SHOW_WARNINGS:-0}" = "1" ]; then
	WARN_FLAGS=(-Wall)
fi
WARN_FLAGS+=(-Werror=implicit-function-declaration -Werror=implicit-int -Werror=int-conversion)

if [ "$#" -gt 0 ]; then
	FILES=("$@")
else
	mapfile -t FILES < <(find application/source -name '*.c' | sort)
fi

failed=0
total=0

for cfg in "${CONFIGS[@]}"; do
	declare -n cfg_defs="DEFS_${cfg}"
	for f in "${FILES[@]}"; do
		total=$((total + 1))
		out="$("$CC" -fsyntax-only -std=gnu11 "${WARN_FLAGS[@]}" "${INCS[@]}" "${cfg_defs[@]}" "$f" 2>&1)"
		if printf '%s' "$out" | grep -q 'error:'; then
			failed=$((failed + 1))
			echo "=== ПОМИЛКА [$cfg]: $f"
			printf '%s\n' "$out" | grep -A 2 'error:' | head -20
		elif [ -n "$out" ] && [ "${SHOW_WARNINGS:-0}" = "1" ]; then
			echo "--- попередження [$cfg]: $f"
			printf '%s\n' "$out" | head -20
		fi
	done
	unset -n cfg_defs
done

echo
echo "Перевірено файлів: $total (× ${#CONFIGS[@]} конфігурації: ${CONFIGS[*]}), з помилками: $failed"

if [ "$failed" -ne 0 ]; then
	echo "СИНТАКСИЧНА ПЕРЕВІРКА НЕ ПРОЙДЕНА -- ці помилки зламають і збірку CI."
	exit 1
fi

echo "Синтаксична перевірка пройдена (нагадування: це не заміна ARM-збірці в CI)."
exit 0
