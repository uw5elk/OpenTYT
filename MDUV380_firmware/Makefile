# Auto-generated Makefile to build OpenGD77 MD-UV390 PLUS 10W firmware
# (mirrors STM32CubeIDE config MDUV380_10W_PLUS_FW). arm-none-eabi-gcc.
TARGET   = openuv380-10w
BUILD    = build
CROSS    = arm-none-eabi-
CC       = $(CROSS)gcc
OBJCOPY  = $(CROSS)objcopy
SIZE     = $(CROSS)size

CPU   = -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard
ENABLE_AES ?= 0
GITVERSION := $(shell git rev-parse --short HEAD 2>/dev/null || echo UNKNOWN)
DEFS  = -DGITVERSION=$(GITVERSION) -DUSE_HAL_DRIVER -DSTM32F405xx -DPLATFORM_MDUV380 -DPLATFORM_VARIANT_UV380_PLUS_10W -DNDEBUG
INCS  = -I. -ICore/Inc \
        -IDrivers/CMSIS/Device/ST/STM32F4xx/Include -IDrivers/CMSIS/Include \
        -IDrivers/STM32F4xx_HAL_Driver/Inc -IDrivers/STM32F4xx_HAL_Driver/Inc/Legacy \
        -IMiddlewares/ST/STM32_USB_Device_Library/Class/CDC/Inc \
        -IMiddlewares/ST/STM32_USB_Device_Library/Core/Inc \
        -IMiddlewares/Third_Party/FreeRTOS/Source/CMSIS_RTOS_V2 \
        -IMiddlewares/Third_Party/FreeRTOS/Source/include \
        -IMiddlewares/Third_Party/FreeRTOS/Source/portable/GCC/ARM_CM4F \
        -IUSB_DEVICE/App -IUSB_DEVICE/Target -Iapplication/include

ifeq ($(ENABLE_AES),1)
DEFS += -DENABLE_AES
endif

ifeq ($(ENABLE_DMR_DATA),1)
DEFS += -DENABLE_DMR_DATA
endif

# Діагностика SMS (cleanup1, 2026-10-05): екрани «Діагностика» 2-4, перемикачі, знімок PDU,
# лічильники, USB 0x93/0x94/0x95/0x97/0xB2/0xB3. Лише для розборів; у CI НЕ вмикати.
# Має сенс тільки разом з ENABLE_AES=1 ENABLE_DMR_DATA=1.
ifeq ($(ENABLE_SMS_DIAG),1)
DEFS += -DENABLE_SMS_DIAG
endif

# R58: діагностика пробудження ретранслятора -- журнал сеансів (час до AWAKEN/FAILED, кількість пакетів WAKE_1),
# пункт «Журнал пробудж.» і USB-команда 0xB7 (tools/wake_diag.py). Лише діагностична збірка; у користувацьких НЕ вмикати.
# Потребує ENABLE_AES=1 ENABLE_DMR_DATA=1. З R59 пункт живе в меню «Роумінг» (menuRoam.c; раніше -- «Повідомлення»), тож без
# ENABLE_ROAM_RETRY=1 журнал збирається, читається по USB, але на екрані його нема.
ifeq ($(ENABLE_WAKE_DIAG),1)
ifneq ($(ENABLE_AES),1)
$(error ENABLE_WAKE_DIAG=1 потребує ENABLE_AES=1 і ENABLE_DMR_DATA=1)
endif
ifneq ($(ENABLE_DMR_DATA),1)
$(error ENABLE_WAKE_DIAG=1 потребує ENABLE_AES=1 і ENABLE_DMR_DATA=1)
endif
DEFS += -DENABLE_WAKE_DIAG
endif

# R59: «Роумінг» -- пункт головного меню і автоперехід на наступний канал зі СПИСКУ РОУМІНГУ (канали з прапорцем ROAMING), коли
# ретранслятор не відповів на пробудження під утримуваним PTT (R57 §2-§3, прототип R58 -- ENABLE_WAKE_HOP_TEST -- прибрано).
# Не залежить від ENABLE_WAKE_DIAG (журнал лише додає в меню пункт і стрибки в записи сеансів). Функція за замовчуванням ВИМКНЕНА
# в самій рації (меню «Роумінг»). У звичайній користувацькій збірці поки НЕ вмикати: RAM/CCM/прошивка -- за звітом CI (tools/mem_report.py).
ifeq ($(ENABLE_ROAM_RETRY),1)
DEFS += -DENABLE_ROAM_RETRY
endif

# AES-fix1 A2: у late entry передавати MI ПОТОЧНОГО суперфрейму (типово -- наступного, look-ahead).
# Збірка-кандидат для польової звірки зі стоковою; потребує ENABLE_AES=1 (поза ним нічого не змінює).
ifeq ($(AES_TX_MI_CURRENT),1)
DEFS += -DAES_TX_MI_CURRENT
endif

# AES-fix2: фаза шифрування TX за ефіром (dmrAesTxSkipBurst). AES_TX_PHASE_FIX=0 ВИМИКАЄ її -- лише для вимірювання
# «до фіксу» (BO2) в діагностичній збірці; у збірках для користування лишати типове значення 1.
AES_TX_PHASE_FIX ?= 1
ifeq ($(AES_TX_PHASE_FIX),0)
DEFS += -DAES_TX_PHASE_FIX_OFF
endif

ifeq ($(DMR_AES_DIAG_PATTERN),1)
DEFS += -DDMR_AES_DIAG_PATTERN
endif

ifeq ($(DMR_AES_DIAG_ENCPAT),1)
DEFS += -DDMR_AES_DIAG_ENCPAT
endif

ifeq ($(DMR_AES_DIAG_RX),1)
DEFS += -DDMR_AES_DIAG_RX
endif

# Dev-only: USB display mirror + remote key injection (fbmirror.py / rkey.py).
# Lets a PC drive the UI and read the framebuffer over USB. Never enable in a
# release build. Independent of ENABLE_AES.
ifeq ($(ENABLE_KEY_INJECTION),1)
DEFS += -DENABLE_KEY_INJECTION
endif

# Dev-only: swept-RSSI receiver driven over USB (tools/sweep.py). NOT an SDR --
# the AT1846S has no IQ output, only an RSSI register. Never enable in a release
# build. Independent of ENABLE_AES / ENABLE_DMR_DATA / ENABLE_KEY_INJECTION.
ifeq ($(ENABLE_SPECTRUM),1)
DEFS += -DENABLE_SPECTRUM
endif

# Dev-only: DWT scan-step profiler (CPS 0xA9, tools/scanprof.py). Costs 544 bytes of RAM
# for the slot table, which is a lot on a target with under 2 KB spare, so it is separate
# from ENABLE_SPECTRUM -- the sweep tooling is worth keeping when the profiler is not.
# Requires ENABLE_SPECTRUM: the implementation lives in spectrum.c.
ifeq ($(ENABLE_SCAN_PROFILER),1)
DEFS += -DENABLE_SCAN_PROFILER
endif

# Faster ANALOG scanning: adds sub-30 ms steps (20/15/10/6 ms) to the existing
# "Scan dwell time" setting, selectable on the radio and via CHIRP. Digital scanning is
# unchanged (it takes the larger of this and its own DMR timeslot minimum). Unlike
# ENABLE_SPECTRUM this is a user-facing feature flag, not a dev one -- but it is still a
# flag so that a build without it stays byte-identical to stock.
ifeq ($(ENABLE_FAST_SCAN),1)
DEFS += -DENABLE_FAST_SCAN
endif

# Українська мова інтерфейсу: окремий кириличний шрифт (HX8353E_charset_UA.h)
# + скомпільований у прошивку ukrainian.h замість "User"-слоту, що звично
# пишеться CPS. Той самий підхід, що й LANGUAGE_BUILD_JAPANESE. Стандартний
# HX8353E_charset.h цим прапорцем не зачіпається -- інші мови (польська,
# чеська і т.д.) від нього не залежать.
ifeq ($(LANGUAGE_UKRAINIAN),1)
DEFS += -DLANGUAGE_BUILD_UKRAINIAN
endif

# Dev-only: рантайм-діагностика вільної пам'яті (USB CPS 0xB4, tools/mem_diag.py).
# Додано 2026-09-19 як передумову до docs/recording-feasibility.md -- показує
# РЕАЛЬНИЙ (не статичний) запас купи FreeRTOS і стеків hrc6000Task/головної задачі
# під навантаженням. Незалежний від ENABLE_AES/ENABLE_DMR_DATA -- саме тому й
# окремий прапорець: потрібен і на "голій" конфігурації, щоб порівняти запас між
# усіма збірками матриці. Типова збірка без цього прапорця -- байт-у-байт без змін.
ifeq ($(ENABLE_MEM_DIAG),1)
DEFS += -DENABLE_MEM_DIAG
endif

# "Переслухати": кільцевий буфер CCM з останніми ~30 с прийнятого RX DMR-голосу на
# ВІДКРИТИХ каналах (docs/recording-feasibility.md, сценарій A). Захоплення -- один
# memcpy у задачі hrc6000TaskFunction (не в перериванні), відтворення -- тим самим
# кодек-шляхом, що й голосові підказки. Незалежний від ENABLE_AES/ENABLE_DMR_DATA --
# сама фіча про AES не знає нічого, крім "пропустити кадри активного дешифрування".
# Типово вимкнено -- звичайна збірка байт-у-байт як стоковий OpenGD77.
ifeq ($(ENABLE_CALL_REPLAY),1)
DEFS += -DENABLE_CALL_REPLAY
endif

# R41: «Видалити канал» у швидкому меню каналу (SK1 + зелена на екрані каналу). Діє лише разом з LANGUAGE_UKRAINIAN=1 (рядки меню живуть у
# українському мовному блоці). Незалежний від ENABLE_AES/ENABLE_DMR_DATA. Типово вимкнено -- звичайна збірка байт-у-байт як стоковий OpenGD77.
ifeq ($(ENABLE_CHANNEL_DELETE),1)
DEFS += -DENABLE_CHANNEL_DELETE
endif

# R42: затримка відкриття шумодава FM (Опції рації) і перейменування зони (список «Зони», клавіша «#»). Діють лише разом з LANGUAGE_UKRAINIAN=1; перейменування зони
# -- ще й з ENABLE_APRS_RX (редактор назви й правила хвоста 0x00 живуть у збірці APRS_R21_NAMES). Незалежні одне від одного й від ENABLE_AES/ENABLE_DMR_DATA.
# Типово вимкнено -- звичайна збірка байт-у-байт як стоковий OpenGD77.
ifeq ($(ENABLE_SQL_OPEN_DELAY),1)
DEFS += -DENABLE_SQL_OPEN_DELAY
endif
ifeq ($(ENABLE_ZONE_RENAME),1)
DEFS += -DENABLE_ZONE_RENAME
endif

# R43: редагування зон з рації -- «Додати канал», «Вийняти із зони», «Нова зона», «Видалити зону» (без ENABLE_CODEPLUG_MENU -- у швидкому меню каналу й списку «Зони»; з ним -- у розділі «Кодплаг»). Потребує ENABLE_ZONE_RENAME (назва нової зони
# набирається тим самим редактором) і тому діє лише в українській збірці з ENABLE_APRS_RX. Типово вимкнено -- звичайна збірка байт-у-байт як стоковий OpenGD77.
ifeq ($(ENABLE_ZONE_EDIT),1)
DEFS += -DENABLE_ZONE_EDIT
endif

# R44: єдиний розділ «Кодплаг» у головному меню (Канали / Зони / Контакти) замість окремих входів R41-R43 (швидке меню каналу, «#» і «Нова зона» у списку зон). Потребує ВСІХ трьох
# прапорців вище (ENABLE_CHANNEL_DELETE, ENABLE_ZONE_RENAME, ENABLE_ZONE_EDIT) -- без якогось із них розділу нема, а R41-R43 лишаються як були. Додає й каскад видалення контакту
# (канали з цим контактом -> «Немає»). Типово вимкнено -- звичайна збірка байт-у-байт як стоковий OpenGD77.
ifeq ($(ENABLE_CODEPLUG_MENU),1)
DEFS += -DENABLE_CODEPLUG_MENU
endif

# R64C: імена слотів AES-ключів (показ у списку ключів, «#» -- перейменувати; ім'я лежить у стоковому записі таблиці ключів). Потребує ENABLE_AES і українську збірку з
# multitap. Типово вимкнено -- збірки ENABLE_AES=* без прапорця байт-у-байт як були.
ifeq ($(ENABLE_AES_KEY_NAMES),1)
DEFS += -DENABLE_AES_KEY_NAMES
endif
# R65B: редактор списків прийому з рації (створити/перейменувати/склад/видалити). Потребує ENABLE_CODEPLUG_MENU (+ENABLE_CHANNEL_DELETE/ZONE_EDIT) і українську збірку; без прапорця збірка не змінюється.
ifeq ($(ENABLE_RXGROUP_EDIT),1)
DEFS += -DENABLE_RXGROUP_EDIT
endif
# R66D: тон передачі супутника перераховується при зміні набору 1/2/3 (стокове OpenGD77 виставляє його лише при виборі супутника). Без прапорця збірка не змінюється.
ifeq ($(ENABLE_SAT_TONE_SYNC),1)
DEFS += -DENABLE_SAT_TONE_SYNC
endif

# R2/R3 (2026-10-09/10), ТИМЧАСОВО: діагностичний екран «APRS проба» (Опції рації, останній
# пункт): прийом APRS з I2S від HR-C6000 -- демодулятор AFSK 1200 + AX.25, лічильники кадрів для
# 6 варіантів регістрів кодека, розгортка фону (docs/aprs-rx-feasibility.md, розділи 6-7). Екран є
# лише в українській збірці. У CI ввімкнено ЛИШЕ в build-ukrainian; прибрати після експериментів
# (STATUS.md). Типова збірка без прапорця -- байт-у-байт без змін.
ifeq ($(ENABLE_APRS_RX_PROBE),1)
DEFS += -DENABLE_APRS_RX_PROBE
endif

# R77A (2026-10-12), ТИМЧАСОВО: діагностичний екран «Гучн. проба» (Опції рації, останній пункт): додаткове ослаблення звуку нижче мінімуму
# потенціометра -- DMR множником відліків перед I2S, FM -- AT1846S 0x44. Нічого не зберігається, усе скидається при виході. Лише українська
# збірка UV380 Plus 10W; у CI -- окрема діагностична робота, НЕ в build-ukrainian. Типова збірка без прапорця -- байт-у-байт без змін.
# R78: «Мін.гучність» -- постійний тихий нижній рівень гучності (лише українська збірка, UV380 Plus 10W; код сам вимикається в інших). Увімкнено в CI у основній українській збірці.
ifeq ($(ENABLE_VOLUME_LOW),1)
DEFS += -DENABLE_VOLUME_LOW
endif

# R97: «Подвійний прийом» по каналах кодплага (A = поточний канал, B = закріплений; custom-data блок 18). Лише українська збірка UV380
# (сам код вимикається в інших). У CI ввімкнено в основній українській збірці. Типова збірка без прапорця -- байт-у-байт без змін.
ifeq ($(ENABLE_DUAL_CHANNEL),1)
DEFS += -DENABLE_DUAL_CHANNEL
endif

# R99-TONE: «Тон-відгук» -- після закриття шумодава FM рація відповідає тоном (частота/тривалість/затримка -- custom-data блок 19). Лише українська
# збірка UV380 (код сам вимикається в інших). У CI ввімкнено в основній українській збірці. Типова збірка без прапорця -- байт-у-байт без змін.
ifeq ($(ENABLE_TONE_REPLY),1)
DEFS += -DENABLE_TONE_REPLY
endif

ifeq ($(ENABLE_VOLUME_PROBE),1)
DEFS += -DENABLE_VOLUME_PROBE
endif

# R88: ДІАГНОСТИКА сирого Talker Alias і GPS-блока LC (екран «TA diag», останній пункт «Опцій рації»). Лише окрема діагностична
# збірка (CI: build-ukrainian-tadiag), НЕ в build-ukrainian. Нічого не пише у кодплаг/флеш. Типова збірка без прапорця -- байт-у-байт без змін.
ifeq ($(ENABLE_TA_DIAG),1)
DEFS += -DENABLE_TA_DIAG
endif

# R91C: відстань і азимут до кореспондента за GPS-блоком LC 0x08 (замість Maidenhead у шапці виклику, коли задана своя позиція). Діє лише разом з ENABLE_APRS_RX
# (формат відстані -- aprsRxFormatGeo) і українською збіркою. Типова збірка без прапорця -- байт-у-байт без змін.
ifeq ($(ENABLE_LC_DISTANCE),1)
DEFS += -DENABLE_LC_DISTANCE
endif

# R8 (2026-10-11): справжній фоновий приймач APRS (aprs_rx.c) -- користувацька українська збірка.
# На каналі APRS (аналоговий FM, RX-частота == частота APRS із налаштувань APRS) слухає ефір
# у фоні й показує станції (Опції рації -> «APRS станції»), банер при прийомі та повідомлення
# нам («Повідомлення»). ENABLE_APRS_RX_PROBE ВКЛЮЧАЄ приймач (діагностична збірка: проба + приймач).
# Типова збірка без прапорців -- байт-у-байт без змін.
ifeq ($(ENABLE_APRS_RX),1)
DEFS += -DENABLE_APRS_RX
endif

# APRS-fix N3: відкат смуги маяка на 12,5 кГц -- `make ... ENABLE_APRS_RX=1 APRS_TX_BW_25K=0` (типово 25 кГц, див. aprs.h). Без цього параметра нічого не додається.
ifdef APRS_TX_BW_25K
DEFS += -DAPRS_TX_BW_25K=$(APRS_TX_BW_25K)
endif

# R10-fix4 (2026-10-11): ОПЦІЙНО апаратний сторож IWDG (~2 с) поверх програмного (TIM7) сторожа «Режиму APRS».
# ЗА ТИПОВИМ ЗНАЧЕННЯМ ВИМКНЕНО й у CI не вмикається. Причина: запущений IWDG не зупиняється нічим, крім скидання, а
# вимкнення/сон рації (HAL_PWR_EnterSTANDBYMode) може його не зупинити -- рація б «воскресала» після вимкнення.
# Корисно лише для лабораторної перевірки зависань із вимкненими перериваннями (PRIMASK), яких TIM7-сторож не бачить.
# Діє тільки разом з ENABLE_APRS_RX=1 і українською збіркою (APRS_RX).
ifeq ($(ENABLE_APRS_IWDG),1)
DEFS += -DAPRS_FAULT_IWDG
endif

CFLAGS  = $(CPU) $(DEFS) $(INCS) -Os -g3 -ffunction-sections -fdata-sections -Wall -MMD -MP
LDSCRIPT = STM32F405VGTX_FLASH.ld
# R63C: ТЕСТОВА збірка -- .rodata ПІСЛЯ блока кодека (див. шапку STM32F405VGTX_FLASH_RODATA_AFTER_CODEC.ld). Без прапорця лінкер-скрипт і .bin ті самі.
ifeq ($(ENABLE_RODATA_AFTER_CODEC),1)
LDSCRIPT = STM32F405VGTX_FLASH_RODATA_AFTER_CODEC.ld
endif
LDFLAGS = $(CPU) -T$(LDSCRIPT) --specs=nano.specs -Wl,--gc-sections -Wl,-Map=$(BUILD)/$(TARGET).map -lc -lm -lnosys

C_SRCS   = $(shell find Core Drivers Middlewares USB_DEVICE application -name *.c ! -name languages_builder.c ! -name *_template.c)
ASM_SRCS = Core/Startup/startup_stm32f405vgtx.s
ASM_SRCS_S = $(shell find application -name *.S)
OBJS = $(addprefix $(BUILD)/,$(C_SRCS:.c=.o)) $(addprefix $(BUILD)/,$(ASM_SRCS:.s=.o)) $(addprefix $(BUILD)/,$(ASM_SRCS_S:.S=.o))
DEPS = $(OBJS:.o=.d)

.DEFAULT_GOAL := all
LINKERDATA_BIN = application/source/linkerdata/codec_bin_section_1.bin
$(LINKERDATA_BIN):
	@chmod +x tools/codec_cleaner.Linux
	cd application/source/linkerdata && ../../../tools/codec_cleaner.Linux -C

$(BUILD)/application/source/dmr_codec/codec_bin.o: $(LINKERDATA_BIN)

all: $(BUILD)/$(TARGET).bin $(BUILD)/$(TARGET).hex

$(BUILD)/%.o: %.c
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD)/%.o: %.s
	@mkdir -p $(dir $@)
	$(CC) $(CPU) -c $< -o $@

$(BUILD)/%.o: %.S
	@mkdir -p $(dir $@)
	$(CC) $(CPU) -I. -Iapplication -c $< -o $@

$(BUILD)/$(TARGET).elf: $(OBJS)
	$(CC) $(OBJS) $(LDFLAGS) -o $@
	$(SIZE) $@

$(BUILD)/$(TARGET).bin: $(BUILD)/$(TARGET).elf
	$(OBJCOPY) -O binary $< $@

$(BUILD)/$(TARGET).hex: $(BUILD)/$(TARGET).elf
	$(OBJCOPY) -O ihex $< $@

clean:
	rm -rf $(BUILD)

-include $(DEPS)
