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

# AES-fix1 A2: у late entry передавати MI ПОТОЧНОГО суперфрейму (типово -- наступного, look-ahead).
# Збірка-кандидат для польової звірки зі стоковою; потребує ENABLE_AES=1 (поза ним нічого не змінює).
ifeq ($(AES_TX_MI_CURRENT),1)
DEFS += -DAES_TX_MI_CURRENT
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

# R2/R3 (2026-10-09/10), ТИМЧАСОВО: діагностичний екран «APRS проба» (Опції рації, останній
# пункт): прийом APRS з I2S від HR-C6000 -- демодулятор AFSK 1200 + AX.25, лічильники кадрів для
# 6 варіантів регістрів кодека, розгортка фону (docs/aprs-rx-feasibility.md, розділи 6-7). Екран є
# лише в українській збірці. У CI ввімкнено ЛИШЕ в build-ukrainian; прибрати після експериментів
# (STATUS.md). Типова збірка без прапорця -- байт-у-байт без змін.
ifeq ($(ENABLE_APRS_RX_PROBE),1)
DEFS += -DENABLE_APRS_RX_PROBE
endif

# R8 (2026-10-11): справжній фоновий приймач APRS (aprs_rx.c) -- користувацька українська збірка.
# На каналі APRS (аналоговий FM, RX-частота == частота APRS із налаштувань APRS) слухає ефір
# у фоні й показує станції (Опції рації -> «APRS станції»), банер при прийомі та повідомлення
# нам («Повідомлення»). ENABLE_APRS_RX_PROBE ВКЛЮЧАЄ приймач (діагностична збірка: проба + приймач).
# Типова збірка без прапорців -- байт-у-байт без змін.
ifeq ($(ENABLE_APRS_RX),1)
DEFS += -DENABLE_APRS_RX
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
