/*
 * Copyright (C) 2019      Kai Ludwig, DG4KLU
 * Copyright (C) 2019-2025 Roger Clark, VK3KYY / G4KYF
 *                         Daniel Caujolle-Bert, F1RMB
 *
 *
 * Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions
 * are met:
 *
 * 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
 *
 * 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer
 *    in the documentation and/or other materials provided with the distribution.
 *
 * 3. Neither the name of the copyright holder nor the names of its contributors may be used to endorse or promote products derived
 *    from this software without specific prior written permission.
 *
 * 4. Use of this source code or binary releases for commercial purposes is strictly forbidden. This includes, without limitation,
 *    incorporation in a commercial product or incorporation into a product or project which allows commercial use.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 * LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
 * HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 * LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
 * ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE
 * USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 *
 */

#include <stdint.h>
#include <stdio.h>
#include "functions/codeplug.h"
#if defined(CODEPLUG_MENU_ENABLED)
#include <stddef.h>   /* R44: offsetof(CodeplugChannel_t, contact) */
#endif
#include "functions/codeplug_zone.h"
#include "hardware/EEPROM.h"
#include "hardware/SPI_Flash.h"
#include "functions/trx.h"
#include "usb/usb_com.h"
#include "user_interface/uiLocalisation.h"
#include "user_interface/uiGlobals.h"
#include "interfaces/settingsStorage.h"
#if defined(APRS_R21_NAMES)
#include "functions/aprs_rx_parse.h"
#endif
#if defined(CHANNEL_DELETE_ENABLED)
#include "functions/codeplug_chandel.h"   /* R41: чиста логіка видалення каналу */
#endif
#if defined(ZONE_EDIT_ENABLED)
#include "functions/codeplug_zoneedit.h"  /* R43: чиста логіка редагування зон */
#endif


const int CODEPLUG_ADDR_EX_ZONE_BASIC = 0x8000;
const int CODEPLUG_ADDR_EX_ZONE_INUSE_PACKED_DATA = 0x8010;
#define CODEPLUG_EX_ZONE_INUSE_PACKED_DATA_SIZE  32
const int CODEPLUG_ADDR_EX_ZONE_LIST = 0x8030;

const int CODEPLUG_ZONE_MAX_COUNT = 250;
const int CODEPLUG_ADDR_CHANNEL_EEPROM = 0x3790;
const int CODEPLUG_ADDR_CHANNEL_HEADER_EEPROM = 0x3780; // CODEPLUG_ADDR_CHANNEL_EEPROM - 16
const int CODEPLUG_ADDR_CHANNEL_FLASH = 0x7B1C0;
const int CODEPLUG_ADDR_CHANNEL_HEADER_FLASH = 0x7B1B0; // CODEPLUG_ADDR_CHANNEL_FLASH - 16

const int CODEPLUG_ADDR_SIGNALLING_DTMF = 0x1400;
const int CODEPLUG_ADDR_SIGNALLING_DTMF_DURATIONS = (CODEPLUG_ADDR_SIGNALLING_DTMF + 0x72); // offset to grab the DTMF durations
const int CODEPLUG_SIGNALLING_DTMF_DURATIONS_SIZE = 4;

const int CODEPLUG_ADDR_RX_GROUP_LEN = 0x8D620;  // 76 TG lists
const int CODEPLUG_ADDR_RX_GROUP = 0x8D6A0;//

const int CODEPLUG_ADDR_CONTACTS = 0x87620;

const int CODEPLUG_ADDR_DTMF_CONTACTS = 0x02f88;

const int CODEPLUG_ADDR_USER_DMRID = 0x00E8;
const int CODEPLUG_ADDR_USER_CALLSIGN = 0x00E0;

const int CODEPLUG_ADDR_GENERAL_SETTINGS = 0x00E0;

const int CODEPLUG_ADDR_BOOT_INTRO_SCREEN = 0x7518;// 0x01 = Chars 0x00 = Picture
const int CODEPLUG_ADDR_BOOT_PASSWORD_ENABLE= 0x7519;// 0x00 = password disabled 0x01 = password enable
const int CODEPLUG_ADDR_BOOT_PASSWORD_AREA = 0x751C;// Seems to be 3 bytes coded as BCD e.f. 0x12 0x34 0x56
const int CODEPLUG_BOOT_PASSWORD_LEN = 3;
const int CODEPLUG_ADDR_BOOT_LINE1 = 0x7540;
const int CODEPLUG_ADDR_BOOT_LINE2 = 0x7550;
const int CODEPLUG_ADDR_VFO_A_CHANNEL = 0x7590;
const int CPS_CODEPLUG_SECTION_2_START = 0x7500;

const int CODEPLUG_ADDR_APRS_CONFIGS = 0x1588;// Address of start of APRS configs (formerly Emergency Systems)

int codeplugChannelsPerZone = 16;

const int VFO_FREQ_STEP_TABLE[8] = {250,500,625,1000,1250,2500,3000,5000};
const int VFO_SWEEP_SCAN_RANGE_SAMPLE_STEP_TABLE[7] = {78,157,313,625, 1250,2500,5000};


const int CODEPLUG_MAX_VARIABLE_SQUELCH = 21U;
const int CODEPLUG_MIN_VARIABLE_SQUELCH = 1U;

const int CODEPLUG_MIN_PER_CHANNEL_POWER  = 1;

const int CODEPLUG_ADDR_DEVICE_INFO = 0x80;
const int CODEPLUG_ADDR_DEVICE_INFO_READ_SIZE = 96;// (sizeof struct_codeplugDeviceInfo_t)

const int CODEPLUG_ADDR_BOOT_PASSWORD_PIN = 0x7518;

const uint16_t APRS_MAGIC_VERSION = 0x4153;


static uint16_t allChannelsTotalNumOfChannels = 0;
static uint16_t allChannelsHighestChannelIndex = 0;

typedef struct
{
	uint32_t tgOrPCNum;
	uint16_t index;
} codeplugContactCache_t;


typedef struct
{
	uint8_t index;
} codeplugDTMFContactCache_t;

typedef struct
{
	int numTGContacts;
	int numPCContacts;
	int numALLContacts;
	int numDTMFContacts;
	codeplugContactCache_t contactsLookupCache[CODEPLUG_CONTACTS_MAX];
	codeplugDTMFContactCache_t contactsDTMFLookupCache[CODEPLUG_DTMF_CONTACTS_MAX];
} codeplugContactsCache_t;

typedef struct
{
	int 	numOfConfigs;
} codeplugAPRSConfigsCache_t;

typedef struct
{
	int dataType;
	int dataLength;
} codeplugCustomDataBlockHeader_t;

__attribute__((section(".data.$RAM2"))) codeplugContactsCache_t codeplugContactsCache;

__attribute__((section(".data.$RAM2"))) uint8_t codeplugRXGroupCache[CODEPLUG_RX_GROUPLIST_MAX];
__attribute__((section(".data.$RAM2"))) uint8_t codeplugAllChannelsCache[128];
__attribute__((section(".data.$RAM2"))) uint8_t codeplugZonesInUseCache[CODEPLUG_EX_ZONE_INUSE_PACKED_DATA_SIZE];
__attribute__((section(".data.$RAM2"))) uint16_t quickKeysCache[CODEPLUG_QUICKKEYS_SIZE];

__attribute__((section(".data.$RAM2"))) uint8_t lastUsedChannelInZoneData[CODEPLUG_ALL_ZONES_MAX + 1]; // All zones (0..79) + AllChannel 0..1023 (hence one extra byte to store this value)
static bool lastUsedChannelInZoneHasChanged = false;

__attribute__((section(".data.$RAM2"))) codeplugAPRSConfigsCache_t codeplugAPRSCache;

static bool codeplugContactGetReserve1ByteForIndex(int index, CodeplugContact_t *contact);

static uint32_t byteSwap32(uint32_t n)
{
    return ((((n) & 0x000000FFU) << 24U) | (((n) & 0x0000FF00U) << 8U) | (((n) & 0x00FF0000U) >> 8U) | (((n) & 0xFF000000U) >> 24U));// from usb_misc.h
}

#if 0
uint16_t byteSwap16(uint16_t n)
{
    return (((n) & 0x00FFU) << 8U) | (((n) & 0xFF00U) >> 8U);
}
#endif

// BCD encoding to integer conversion
uint32_t bcd2int(uint32_t i)
{
    uint32_t result = 0;
    int multiplier = 1;
    while (i)
    {
        result += (i & 0x0f) * multiplier;
        multiplier *= 10;
        i = i >> 4;
    }
    return result;
}

// Needed to convert the legacy DMR ID data which uses BCD encoding for the DMR ID numbers
uint32_t int2bcd(uint32_t i)
{
	uint32_t result = 0;
    int shift = 0;

    while (i)
    {
        result +=  (i % 10) << shift;
        i = i / 10;
        shift += 4;
    }
    return result;
}

uint16_t bcd2uint16(uint16_t i)
{
    int result = 0;
    int multiplier = 1;
    while (i)
    {
        result += (i & 0x0f) * multiplier;
        multiplier *= 10;
        i = i >> 4;
    }
    return result;
}

CodeplugCSSTypes_t codeplugGetCSSType(uint16_t tone)
{
	if ((tone == CODEPLUG_CSS_TONE_NONE) || (tone == 0x0))
	{
		return CSS_TYPE_NONE;
	}
	else if((tone != CODEPLUG_CSS_TONE_NONE) && (tone != 0x0))
	{
		if ((tone & CSS_TYPE_DCS_MASK) == 0)
		{
			return CSS_TYPE_CTCSS;
		}
		else if (tone & CSS_TYPE_DCS_INVERTED)
		{
			return (CSS_TYPE_DCS | CSS_TYPE_DCS_INVERTED);
		}

		return CSS_TYPE_DCS;
	}

	return CSS_TYPE_NONE;
}

// Converts a codeplug coded-squelch system value to int (with flags if DCS)
uint16_t codeplugCSSToInt(uint16_t tone)
{
	CodeplugCSSTypes_t type = codeplugGetCSSType(tone);

	// Only the CTCSS needs convertion
	if (type == CSS_TYPE_CTCSS)
	{
		return bcd2int(tone);
	}

	return ((tone == 0x0) ? CODEPLUG_CSS_TONE_NONE : tone);
}

// Converts an int (with flags if DCS) to codeplug coded-squelch system value
uint16_t codeplugIntToCSS(uint16_t tone)
{
	CodeplugCSSTypes_t type = codeplugGetCSSType(tone);

	// Only the CTCSS needs convertion
	if (type == CSS_TYPE_CTCSS)
	{
		return int2bcd(tone);
	}

	return ((tone == 0x0) ? CODEPLUG_CSS_TONE_NONE : tone);
}

#if defined(APRS_R21_NAMES)
/* R34 N2: довжина назви в 16-байтовому (або 8-байтовому) полі кодплага. Спершу відкидаємо ХВОСТОВІ 0xFF (дописка, яку пише стокова CPS і яку пишемо ми), потім
 * хвостові 0x00 (так записує назву codeplugUtilConvertStringToBuf за CODEPLUG_NAME_ZERO_TAIL і так лишає її OpenGD77 CPS). Порядок саме такий і без чергування:
 * назва «Зоря» з хвостом 0x00 -- це З о р я 00 00 ..., її кінцеве 0xFF (мала «я» в cp1251) стоїть ПЕРЕД нулями і лишається літерою.
 * Внутрішні 0xFF (мала «я» посеред назви, «Поляна») не чіпаємо -- раніше КОЖЕН 0xFF ставав нулем і назва обрізалась до «Пол». */
static int codeplugUtilNameLen(const char *buf, int len)
{
	int n = len;

	while ((n > 0) && (((uint8_t)buf[n - 1]) == 0xFF))
	{
		n--;
	}
	while ((n > 0) && (buf[n - 1] == 0x00))
	{
		n--;
	}
	return n;
}

bool codeplugUtilNameBufEqualsString(const char *codeplugBuf, const char *str, int len)
{
	int n = codeplugUtilNameLen(codeplugBuf, len);

	return ((int)strlen(str) == n) && (memcmp(codeplugBuf, str, (size_t)n) == 0);
}

/* R34 N2.2: вхідний буфер НЕ змінюється (стокова версія записувала нуль замість кожного 0xFF у сам codeplugBuf, тобто псувала живі currentChannelData,
 * currentContactData, currentZone). Виняток -- виклики з outBuf == codeplugBuf (читання позивного й рядків вітання на місці): там буфер і є результатом, у ньому
 * після назви лишаються нулі. outBuf має вміщати len + 1 байтів. */
void codeplugUtilConvertBufToString(char *codeplugBuf, char *outBuf, int len)
{
	int n = codeplugUtilNameLen(codeplugBuf, len);

	if (outBuf != codeplugBuf)
	{
		memcpy(outBuf, codeplugBuf, (size_t)n);
	}
	memset(&outBuf[n], 0, (size_t)(len - n) + 1U);
}
#else
void codeplugUtilConvertBufToString(char *codeplugBuf, char *outBuf, int len)
{
	for(int i = 0; i < len; i++)
	{
		if (codeplugBuf[i] == 0xff)
		{
			codeplugBuf[i] = 0;
		}
		outBuf[i] = codeplugBuf[i];
	}
	outBuf[len] = 0;
}
#endif

#if defined(APRS_R21_NAMES)
void codeplugUtilConvertBufToDisplayString(char *codeplugBuf, char *outBuf, int len)
{
	codeplugUtilConvertBufToString(codeplugBuf, outBuf, len);
	aprsNameToDisplay(outBuf);   /* R21 З3: UTF-8 -> cp1251 лише для показу */
}
#endif

#if defined(APRS_R21_NAMES) && defined(CODEPLUG_NAME_ZERO_TAIL)
/* R34 N3: назва, що ЗАКІНЧУЄТЬСЯ на 0xFF (мала «я» cp1251: «Зоря», «Надія»), з хвостом 0xFF невідрізнима від дописки -- читання обрізало б останню літеру.
 * Для такої назви хвіст -- 0x00. Усі інші назви (а також порожня: прошивка вважає запис порожнім за name[0] == 0xFF, codeplug.c, menuContactDetails.c,
 * uiTxTgPcContactOwnId.c) пишемо як раніше, з хвостом 0xFF -- байт-у-байт те, що пише стокова CPS. Вузьке правило свідомо: стокова CPS з хвостом 0x00
 * не перевірялась (крок CK3), тож не підставляємо його там, де без нього можна обійтися. Ввімкнено лише з CODEPLUG_NAME_ZERO_TAIL (codeplug.h). */
void codeplugUtilConvertStringToBuf(char *inBuf, char *outBuf, int len)
{
	int n = 0;
	uint8_t pad;

	while ((n < len) && (inBuf[n] != 0x00))
	{
		n++;
	}
	pad = ((n > 0) && (n < len) && (((uint8_t)inBuf[n - 1]) == 0xFF)) ? 0x00 : 0xFF;
	memset(outBuf, pad, (size_t)len);
	memcpy(outBuf, inBuf, (size_t)n);
}
#else
void codeplugUtilConvertStringToBuf(char *inBuf, char *outBuf, int len)
{
	memset(outBuf,0xff,len);
	for (int i = 0; i < len; i++)
	{
		if (inBuf[i] == 0x00)
		{
			break;
		}
		outBuf[i] = inBuf[i];
	}
}
#endif

void codeplugZonesInitCache(void)
{
	EEPROM_Read(CODEPLUG_ADDR_EX_ZONE_INUSE_PACKED_DATA, (uint8_t *)&codeplugZonesInUseCache, CODEPLUG_EX_ZONE_INUSE_PACKED_DATA_SIZE);
}

/* codeplug_zone.h: ліміт бітів маски зон мусить збігатись з CODEPLUG_ZONES_MAX */
_Static_assert(CODEPLUG_ZONE_MASK_BITS == CODEPLUG_ZONES_MAX, "CODEPLUG_ZONE_MASK_BITS != CODEPLUG_ZONES_MAX");

int codeplugZonesGetCount(void)
{
	/* R22 Z1.2: рахуємо лише перші CODEPLUG_ZONES_MAX (68) бітів маски. Маска в EEPROM -- 256 бітів, і сміттєві
	 * біти за межею 68 завищували кількість зон (і переповнювали s_zoneMap[69] у меню «Зони»). +1 -- віртуальна
	 * зона «Всі канали». */
	return 1 + codeplugZoneMaskCount(codeplugZonesInUseCache);
}

bool codeplugZoneGetDataForNumber(int zoneNum, CodeplugZone_t *returnBuf)
{
	if (zoneNum == (codeplugZonesGetCount() - 1)) //special case: return a special Zone called 'All Channels'
	{
		int nameLen = SAFE_MIN(((int)sizeof(returnBuf->name)), ((int)strlen(currentLanguage->all_channels)));

		// Codeplug name is 0xff filled, codeplugUtilConvertBufToString() handles the conversion
		memset(returnBuf->name, 0xff, sizeof(returnBuf->name));
		memcpy(returnBuf->name, currentLanguage->all_channels, nameLen);

		// set all channels to zero, All Channels is handled separately
		memset(returnBuf->channels, 0, codeplugChannelsPerZone);

		returnBuf->NOT_IN_CODEPLUGDATA_numChannelsInZone = allChannelsTotalNumOfChannels;
		returnBuf->NOT_IN_CODEPLUGDATA_highestIndex = allChannelsHighestChannelIndex;
		returnBuf->NOT_IN_CODEPLUGDATA_indexNumber = -1;// Set as -1 as this is not a real zone. Its the "All Channels" zone
		return true;
	}
	else
	{
		// Need to find the index into the Zones data for the specific Zone number.
		// Because the Zones data is not guaranteed to be packed by the CPS (though we should attempt to make the CPS always pack the Zones)
		// R22 Z1.2: n-а зона маски -- лише серед перших CODEPLUG_ZONES_MAX бітів (було: усі 256)
		int foundIndex = codeplugZoneMaskNthBit(codeplugZonesInUseCache, zoneNum);

		if (foundIndex != -1)
		{
			// Save this in case we need to add channels to a zone and hence need the index number so it can be saved back to the codeplug memory
			returnBuf->NOT_IN_CODEPLUGDATA_indexNumber = foundIndex;

			// IMPORTANT. Write size is different from the size of the data, because it the zone struct contains properties not in the codeplug data
			EEPROM_Read(CODEPLUG_ADDR_EX_ZONE_LIST + (foundIndex * (16 + (sizeof(uint16_t) * codeplugChannelsPerZone))),
					(uint8_t *)returnBuf, ((codeplugChannelsPerZone == 16) ? CODEPLUG_ZONE_DATA_ORIGINAL_STRUCT_SIZE : CODEPLUG_ZONE_DATA_OPENGD77_STRUCT_SIZE));


			for(int i = 0; i < codeplugChannelsPerZone; i++)
			{
				// Empty channels seem to be filled with zeros, and zone could be full of channels.
				if ((returnBuf->channels[i] == 0) || (i == (codeplugChannelsPerZone - 1)))
				{
					returnBuf->NOT_IN_CODEPLUGDATA_highestIndex = returnBuf->NOT_IN_CODEPLUGDATA_numChannelsInZone = (i + ((returnBuf->channels[i] == 0) ? 0 : 1));
					return true;
				}
			}
		}

		memset(returnBuf->channels, 0, codeplugChannelsPerZone);
		returnBuf->NOT_IN_CODEPLUGDATA_highestIndex = returnBuf->NOT_IN_CODEPLUGDATA_numChannelsInZone = 0;
		returnBuf->NOT_IN_CODEPLUGDATA_indexNumber = -2; // we could not use '-1' on error, as -1 is All Channel zone
	}

	return false;
}

/* R22 Z1.1: ЄДИНЕ правило «справжня зона» для меню «Зони» і валкодера SK2+енкодер. «Всі канали» (остання, віртуальна)
 * -- завжди придатна. Решта: дані зони прочитано, є канали, перший канал реально існує (див. codeplug_zone.h).
 * z може бути NULL -- тоді дані читаються в тимчасовий буфер. При поверненні false вміст *z -- «порожня» зона. */
bool codeplugZoneIsUsable(int zoneNum, CodeplugZone_t *z)
{
	CodeplugZone_t tmp;
	bool ok;

	if (z == NULL)
	{
		z = &tmp;
	}

	ok = codeplugZoneGetDataForNumber(zoneNum, z);

	if (zoneNum == (codeplugZonesGetCount() - 1))
	{
		return ok;   /* «Всі канали» -- завжди */
	}

	return codeplugZoneUsableCheck(ok, z->NOT_IN_CODEPLUGDATA_numChannelsInZone, codeplugAllChannelsIndexIsInUse(z->channels[0]));
}

#if defined(ZONE_RENAME_ENABLED)
/* R42: пишемо ЛИШЕ 16 байтів назви в запис зони -- список каналів зони й решта записів не зачіпаються. Запис назви -- той самий codeplugUtilConvertStringToBuf, що й для
 * каналів і контактів (R34/R36): хвіст 0xFF, а для назви, що закінчується на 0xFF («я»), -- 0x00, тож літера переживає читання. */
/* Перевірка назви зони й перетворення на 16 байтів кодплага (спільне для перейменування R42 і створення зони R43). buf -- рівно 16 байтів. */
static CodeplugZoneRenameResult_t codeplugZoneNameToBuf(const char *name, char *buf)
{
	int n = 0;

	while ((n <= 16) && (name[n] != 0))
	{
		n++;
	}

	if (n == 0)
	{
		return CODEPLUG_ZONE_RENAME_EMPTY;
	}
	if (n > 16)
	{
		return CODEPLUG_ZONE_RENAME_TOO_LONG;
	}
	if ((n == 16) && (((uint8_t)name[15]) == 0xFF))
	{
		return CODEPLUG_ZONE_RENAME_AMBIGUOUS_TAIL;
	}

	codeplugUtilConvertStringToBuf((char *)name, buf, 16);
	return CODEPLUG_ZONE_RENAME_OK;
}

CodeplugZoneRenameResult_t codeplugZoneRename(int zoneNum, const char *name)
{
	char buf[16];
	CodeplugZoneRenameResult_t nameRes;
	int bit;

	// Остання з codeplugZonesGetCount() -- віртуальна «Всі канали» (її назва береться з мовної таблиці): перейменувати нічого
	if ((zoneNum < 0) || (zoneNum >= (codeplugZonesGetCount() - 1)))
	{
		return CODEPLUG_ZONE_RENAME_NOT_REAL;
	}

	bit = codeplugZoneMaskNthBit(codeplugZonesInUseCache, zoneNum);
	if (bit < 0)
	{
		return CODEPLUG_ZONE_RENAME_NOT_REAL;
	}

	nameRes = codeplugZoneNameToBuf(name, buf);
	if (nameRes != CODEPLUG_ZONE_RENAME_OK)
	{
		return nameRes;
	}

	if (!EEPROM_Write(CODEPLUG_ADDR_EX_ZONE_LIST + (bit * (16 + (sizeof(uint16_t) * codeplugChannelsPerZone))), (uint8_t *)buf, 16))
	{
		return CODEPLUG_ZONE_RENAME_WRITE_ERROR;
	}

	if (currentZone.NOT_IN_CODEPLUGDATA_indexNumber == bit)
	{
		memcpy(currentZone.name, buf, 16);   // зона на екрані каналу: показуємо нову назву без перечитування
	}

	return CODEPLUG_ZONE_RENAME_OK;
}
#endif

#if defined(ZONE_EDIT_ENABLED)
/* ---- R43: редагування зон з рації ------------------------------------------------------------------------------------------------------------------------------
 * Усі функції беруть «номер у списку зон» (zoneNum, як codeplugZoneGetDataForNumber), а ПИШУТЬ за номером біта маски (бітів і номерів у списку не збігається: у масці
 * бувають дірки). Нової статичної пам'яті нема: списки каналів читаються з кодплага по одній зоні на стеку. */

static int codeplugZoneRecordAddr(int bit)
{
	return CODEPLUG_ADDR_EX_ZONE_LIST + (bit * (16 + (int)(sizeof(uint16_t) * codeplugChannelsPerZone)));
}

static int codeplugZoneRecordSize(void)
{
	return (codeplugChannelsPerZone == 16) ? CODEPLUG_ZONE_DATA_ORIGINAL_STRUCT_SIZE : CODEPLUG_ZONE_DATA_OPENGD77_STRUCT_SIZE;
}

/* zoneNum -> біт; -1, якщо це не справжня зона (віртуальна «Всі канали» теж) */
static int codeplugZoneRealBit(int zoneNum)
{
	if ((zoneNum < 0) || (zoneNum >= (codeplugZonesGetCount() - 1)))
	{
		return -1;
	}
	return codeplugZoneMaskNthBit(codeplugZonesInUseCache, zoneNum);
}

/* Якщо змінена зона зараз на екрані каналу -- перечитати її, щоб екран бачив новий список без перезапуску */
static void codeplugZoneRefreshCurrent(int bit, int zoneNum)
{
	if (currentZone.NOT_IN_CODEPLUGDATA_indexNumber == bit)
	{
		codeplugZoneGetDataForNumber(zoneNum, &currentZone);
	}
}

/*
 * Додати канал у КІНЕЦЬ списку зони. Пишемо ЛИШЕ 2 байти порожньої позиції списку -- запис атомарний: обрив живлення лишає або старий список, або список із новим каналом.
 * Канал, що вже є в зоні, не додаємо (дубль не має сенсу, а виймання видаляє один запис).
 */
CodeplugZoneEditResult_t codeplugZoneAddChannel(int zoneNum, int channelIndex)
{
	CodeplugZone_t z;
	int bit = codeplugZoneRealBit(zoneNum);
	int num;
	uint16_t ch = (uint16_t)channelIndex;

	if (bit < 0)
	{
		return CODEPLUG_ZONE_EDIT_NOT_REAL;
	}
	if (!codeplugAllChannelsIndexIsInUse(channelIndex))
	{
		return CODEPLUG_ZONE_EDIT_CHANNEL_NOT_IN_USE;
	}
	if (!codeplugZoneGetDataForNumber(zoneNum, &z))
	{
		return CODEPLUG_ZONE_EDIT_NOT_REAL;
	}

	num = z.NOT_IN_CODEPLUGDATA_numChannelsInZone;
	if (codeplugZoneListFind(z.channels, num, ch) >= 0)
	{
		return CODEPLUG_ZONE_EDIT_ALREADY_IN_ZONE;
	}
	if (codeplugZoneListAppend(z.channels, num, codeplugChannelsPerZone, ch) < 0)
	{
		return CODEPLUG_ZONE_EDIT_ZONE_FULL;
	}

	if (!EEPROM_Write(codeplugZoneRecordAddr(bit) + 16 + (int)(sizeof(uint16_t) * num), (uint8_t *)&ch, sizeof(uint16_t)))
	{
		return CODEPLUG_ZONE_EDIT_WRITE_ERROR;
	}

	// «Останній канал у зоні» мусить вказувати в межах списку (після обриву живлення при створенні там могло лишитись сміття від попередньої зони з цим бітом)
	if (codeplugGetLastUsedChannelInZone(bit) > num)
	{
		codeplugSetLastUsedChannelInZone(bit, 0);
		codeplugSaveLastUsedChannelInZone();
	}

	codeplugZoneRefreshCurrent(bit, zoneNum);
	return CODEPLUG_ZONE_EDIT_OK;
}

/*
 * Вийняти запис списку на позиції pos. Список ЩІЛЬНИЙ, тож решта зсувається вліво, а не обнуляється -- інакше навігація по зоні зупинилась би на дірці (кінець списку --
 * перший нуль). Сам канал лишається в масці «в роботі», у «Всіх каналах» і в інших зонах.
 * Порядок: спершу хвіст списку (одним записом від pos до кінця), потім LUCZ. Обрив посеред запису хвоста лишає валідні номери каналів (можливий дубль сусіда), а не сміття.
 */
CodeplugZoneEditResult_t codeplugZoneRemoveChannelAt(int zoneNum, int pos)
{
	CodeplugZone_t z;
	int bit = codeplugZoneRealBit(zoneNum);
	int num;
	int oldIdx;
	int newIdx;

	if (bit < 0)
	{
		return CODEPLUG_ZONE_EDIT_NOT_REAL;
	}
	if (!codeplugZoneGetDataForNumber(zoneNum, &z))
	{
		return CODEPLUG_ZONE_EDIT_NOT_REAL;
	}

	num = z.NOT_IN_CODEPLUGDATA_numChannelsInZone;
	if ((pos < 0) || (pos >= num))
	{
		return CODEPLUG_ZONE_EDIT_BAD_POSITION;
	}

	oldIdx = codeplugGetLastUsedChannelInZone(bit);
	newIdx = codeplugZoneIndexAfterRemoveAt(num, pos, oldIdx);
	codeplugZoneListRemoveAt(z.channels, num, pos);

	if (!EEPROM_Write(codeplugZoneRecordAddr(bit) + 16 + (int)(sizeof(uint16_t) * pos), (uint8_t *)&z.channels[pos], (int)(sizeof(uint16_t) * (num - pos))))
	{
		return CODEPLUG_ZONE_EDIT_WRITE_ERROR;
	}

	if (newIdx != oldIdx)
	{
		codeplugSetLastUsedChannelInZone(bit, (int16_t)newIdx);
		codeplugSaveLastUsedChannelInZone();
	}

	codeplugZoneRefreshCurrent(bit, zoneNum);
	return CODEPLUG_ZONE_EDIT_OK;
}

#if defined(ZONE_MOVE_ENABLED)
/*
 * R66C: обмін двох СУСІДНІХ каналів списку зони (dir -1 -- вгору, +1 -- вниз). Список ЩІЛЬНИЙ, тож обмін двох елементів лишає його щільним; ОДИН запис 4 байтів
 * (два сусідні uint16) -> один прогін сектора. Порядок: спершу список, потім LUCZ (позиція «останнього каналу в зоні» мусить іти за тим самим каналом: поміняли p і p+1
 * місцями -- LUCZ p стає p+1 і навпаки). Обрив між ними: список уже новий, LUCZ вказує на сусідній канал зони -- нешкідливо (при вході в зону відкриється сусід).
 * Якщо 4 байти перетинають межу 4 КіБ сектора, обмін НЕ атомарний (два прогони: між ними канал був би двічі, а сусід загубився б) -- такий обмін відхиляємо
 * (CODEPLUG_ZONE_EDIT_SECTOR_EDGE), щоб після обриву живлення кожен канал лишався в зоні рівно один раз.
 */
CodeplugZoneEditResult_t codeplugZoneMoveChannel(int zoneNum, int pos, int dir)
{
	CodeplugZone_t z;
	uint16_t pair[2];
	int bit = codeplugZoneRealBit(zoneNum);
	int num;
	int to = pos + dir;
	int lo;
	int addr;
	int idx;
	int newIdx;

	if (bit < 0)
	{
		return CODEPLUG_ZONE_EDIT_NOT_REAL;
	}
	if (((dir != -1) && (dir != 1)) || !codeplugZoneGetDataForNumber(zoneNum, &z))
	{
		return CODEPLUG_ZONE_EDIT_NOT_REAL;
	}

	num = z.NOT_IN_CODEPLUGDATA_numChannelsInZone;
	if ((pos < 0) || (pos >= num) || (to < 0) || (to >= num))
	{
		return CODEPLUG_ZONE_EDIT_BAD_POSITION;
	}

	lo = (pos < to) ? pos : to;
	addr = codeplugZoneRecordAddr(bit) + 16 + (int)(sizeof(uint16_t) * lo);
	if (((addr / 4096) != ((addr + 3) / 4096)))
	{
		return CODEPLUG_ZONE_EDIT_SECTOR_EDGE;
	}

	pair[0] = z.channels[lo + 1];
	pair[1] = z.channels[lo];
	if (!EEPROM_Write(addr, (uint8_t *)pair, (int)sizeof(pair)))
	{
		return CODEPLUG_ZONE_EDIT_WRITE_ERROR;
	}

	idx = codeplugGetLastUsedChannelInZone(bit);
	newIdx = (idx == lo) ? (lo + 1) : ((idx == (lo + 1)) ? lo : idx);
	if (newIdx != idx)
	{
		codeplugSetLastUsedChannelInZone(bit, (int16_t)newIdx);
		codeplugSaveLastUsedChannelInZone();
	}

	codeplugZoneRefreshCurrent(bit, zoneNum);
	return CODEPLUG_ZONE_EDIT_OK;
}
#endif

/* Перерахунок збереженої поточної зони після зміни маски: див. codeplugZoneCurrentAfterChange. oldMask -- маска ДО зміни. */
static void codeplugZoneFixCurrent(const uint8_t *oldMask, int16_t *curZoneOrdinal)
{
	int curBit = -1;

	if (curZoneOrdinal == NULL)
	{
		return;
	}
	if ((*curZoneOrdinal >= 0) && (*curZoneOrdinal < codeplugZoneMaskCount(oldMask)))
	{
		curBit = codeplugZoneMaskNthBit(oldMask, *curZoneOrdinal);
	}
	*curZoneOrdinal = (int16_t)codeplugZoneCurrentAfterChange(codeplugZonesInUseCache, curBit);
}

/* Записати байт маски зон (EEPROM 0x8010 + bit/8); кеш міняємо лише після успішного запису */
static bool codeplugZoneMaskWrite(const uint8_t *newMask, int bit)
{
	if (!EEPROM_Write(CODEPLUG_ADDR_EX_ZONE_INUSE_PACKED_DATA + (bit >> 3), (uint8_t *)&newMask[bit >> 3], 1))
	{
		return false;
	}
	codeplugZonesInUseCache[bit >> 3] = newMask[bit >> 3];
	return true;
}

/*
 * Створити зону з порожнім списком каналів у першому вільному біті маски (дірку займаємо першою). ПОРЯДОК, стійкий до обриву живлення:
 *   1. записати ВЕСЬ запис зони (назва + нулі замість каналів) -- поки біт у масці не стоїть, зона невидима, тож обрив тут нічого не псує;
 *   2. поставити біт у масці -- тут зона з'являється (порожня);
 *   3. обнулити LUCZ цього біта (там міг лишитись номер від зони, що стояла тут раніше).
 * Нова зона може стати ЛІВОРУЧ від поточної за ординалом -- тоді ординал поточної зсувається, і функція його перераховує.
 */
CodeplugZoneEditResult_t codeplugZoneCreate(const char *name, int16_t *curZoneOrdinal, int *newOrdinal)
{
	CodeplugZone_t z;
	uint8_t oldMask[CODEPLUG_EX_ZONE_INUSE_PACKED_DATA_SIZE];
	uint8_t newMask[CODEPLUG_EX_ZONE_INUSE_PACKED_DATA_SIZE];
	int bit = codeplugZoneMaskFirstFree(codeplugZonesInUseCache);

	if (bit < 0)
	{
		return CODEPLUG_ZONE_EDIT_NO_FREE_ZONE;
	}

	memset(&z, 0, sizeof(z));
	switch (codeplugZoneNameToBuf(name, z.name))
	{
		case CODEPLUG_ZONE_RENAME_OK:
			break;
		case CODEPLUG_ZONE_RENAME_EMPTY:
			return CODEPLUG_ZONE_EDIT_NAME_EMPTY;
		default:
			return CODEPLUG_ZONE_EDIT_NAME_TOO_LONG;
	}

	// 1. Запис зони. УВАГА: байти запису НЕ заповнюємо 0xFF -- автовизначення «16 чи 80 каналів у зоні» (codeplugInitChannelsPerZone) читає байт 0x806F
	// (у розкладці з 80 каналами це старший байт каналу зони №0 -- мусить бути 0..4). Нулі в списку цього не псують.
	if (!EEPROM_Write(codeplugZoneRecordAddr(bit), (uint8_t *)&z, codeplugZoneRecordSize()))
	{
		return CODEPLUG_ZONE_EDIT_WRITE_ERROR;
	}

	// 2. Маска
	memcpy(oldMask, codeplugZonesInUseCache, sizeof(oldMask));
	memcpy(newMask, codeplugZonesInUseCache, sizeof(newMask));
	codeplugZoneMaskSetBit(newMask, bit);
	if (!codeplugZoneMaskWrite(newMask, bit))
	{
		return CODEPLUG_ZONE_EDIT_WRITE_ERROR;
	}

	// 3. LUCZ
	codeplugSetLastUsedChannelInZone(bit, 0);
	codeplugSaveLastUsedChannelInZone();

	codeplugZoneFixCurrent(oldMask, curZoneOrdinal);
	if (newOrdinal != NULL)
	{
		*newOrdinal = codeplugZoneOrdinalOfBit(codeplugZonesInUseCache, bit);
	}
	return CODEPLUG_ZONE_EDIT_OK;
}

/*
 * Видалити зону: ЗНЯТИ БІТ у масці (спершу маска, потім решта, за зразком R41). Канали НЕ чіпаються -- вони лишаються в масці каналів, у «Всіх каналах» і в інших зонах.
 * Записи інших зон не зсуваються: кодплаг дозволяє дірки в нумерації зон (codeplugZoneMaskNthBit шукає n-ту ПОСТАВЛЕНУ позицію).
 * Сам запис зони НЕ стираємо: стирання 0xFF (як і нулями) зламало б автовизначення розкладки за байтом 0x806F (див. codeplugZoneCreate); без біта в масці запис ніким
 * не читається, а наступне створення зони в цьому біті перепише його цілком.
 * Якщо видалено поточну зону, curZoneOrdinal стає «Всі канали» (= кількість зон, що лишились).
 */
CodeplugZoneEditResult_t codeplugZoneDelete(int zoneNum, int16_t *curZoneOrdinal)
{
	uint8_t oldMask[CODEPLUG_EX_ZONE_INUSE_PACKED_DATA_SIZE];
	uint8_t newMask[CODEPLUG_EX_ZONE_INUSE_PACKED_DATA_SIZE];
	int bit = codeplugZoneRealBit(zoneNum);

	if (bit < 0)
	{
		return CODEPLUG_ZONE_EDIT_NOT_REAL;
	}

	memcpy(oldMask, codeplugZonesInUseCache, sizeof(oldMask));
	memcpy(newMask, codeplugZonesInUseCache, sizeof(newMask));
	codeplugZoneMaskClearBit(newMask, bit);
	if (!codeplugZoneMaskWrite(newMask, bit))
	{
		return CODEPLUG_ZONE_EDIT_WRITE_ERROR;
	}

	codeplugSetLastUsedChannelInZone(bit, 0);
	codeplugSaveLastUsedChannelInZone();

	codeplugZoneFixCurrent(oldMask, curZoneOrdinal);
	return CODEPLUG_ZONE_EDIT_OK;
}

/* Список вибору каналу читає канали ПО ОДНОМУ: n-й за порядком канал із маски «в роботі» (1..1024; 0 -- n поза межами) і їх кількість. Копії списку в пам'яті нема. */
int codeplugZoneEditChannelCount(void)
{
	return codeplugChanMaskPopcount(codeplugAllChannelsCache);
}

int codeplugZoneEditNthChannel(int n)
{
	return codeplugChanMaskNth(codeplugAllChannelsCache, n);
}
#endif /* ZONE_EDIT_ENABLED */

bool codeplugZoneAddChannelToZoneAndSave(int channelIndex, CodeplugZone_t *zoneBuf)
{
	if ((zoneBuf->NOT_IN_CODEPLUGDATA_numChannelsInZone < codeplugChannelsPerZone) && (zoneBuf->NOT_IN_CODEPLUGDATA_indexNumber != -1))
	{
		zoneBuf->channels[zoneBuf->NOT_IN_CODEPLUGDATA_numChannelsInZone++] = channelIndex;// add channel to zone, and increment numb channels in zone
		zoneBuf->NOT_IN_CODEPLUGDATA_highestIndex = zoneBuf->NOT_IN_CODEPLUGDATA_numChannelsInZone;

		// IMPORTANT. Write size is different from the size of the data, because it the zone struct contains properties not in the codeplug data
		return EEPROM_Write(CODEPLUG_ADDR_EX_ZONE_LIST + (zoneBuf->NOT_IN_CODEPLUGDATA_indexNumber * (16 + (sizeof(uint16_t) * codeplugChannelsPerZone))),
				(uint8_t *)zoneBuf, ((codeplugChannelsPerZone == 16) ? CODEPLUG_ZONE_DATA_ORIGINAL_STRUCT_SIZE : CODEPLUG_ZONE_DATA_OPENGD77_STRUCT_SIZE));
	}

	return false;
}

static uint16_t codeplugAllChannelsGetCount(void)
{
	uint16_t c = 0;

	//                         v-- This is a bit verbose, but it does make it clear
	for (uint16_t i = 0; i < ((CODEPLUG_CHANNELS_BANKS_MAX * CODEPLUG_CHANNELS_PER_BANK) / 8); i++)
	{
		c += __builtin_popcount(codeplugAllChannelsCache[i]);
	}

	return c;
}

static bool codeplugAllChannelsReadHeaderBank(int channelBank, uint8_t *bitArray)
{
	if(channelBank == 0)
	{
		return EEPROM_Read(CODEPLUG_ADDR_CHANNEL_HEADER_EEPROM, bitArray, 16);
	}

	return SPI_Flash_read(FLASH_ADDRESS_OFFSET + CODEPLUG_ADDR_CHANNEL_HEADER_FLASH + ((channelBank - 1) *
			(CODEPLUG_CHANNELS_PER_BANK * CODEPLUG_CHANNEL_DATA_STRUCT_SIZE + 16)), bitArray, 16);
}

bool codeplugAllChannelsIndexIsInUse(int index)
{
	if ((index >= CODEPLUG_CHANNELS_MIN) && (index <= CODEPLUG_CHANNELS_MAX))
	{
		index--;
		return (((codeplugAllChannelsCache[index / 8] >> (index % 8)) & 0x01) != 0);
	}

	return false;
}

void codeplugAllChannelsIndexSetUsed(int index)
{
	if ((index >= CODEPLUG_CHANNELS_MIN) && (index <= CODEPLUG_CHANNELS_MAX))
	{
		index--;
		int channelBank = (index / CODEPLUG_CHANNELS_PER_BANK);
		int byteno = (index % CODEPLUG_CHANNELS_PER_BANK) / 8;
		int cacheOffset = index / 8;

		codeplugAllChannelsCache[cacheOffset] |= (1 << (index % 8));

		if(channelBank == 0)
		{
			EEPROM_Write(CODEPLUG_ADDR_CHANNEL_HEADER_EEPROM + byteno, &codeplugAllChannelsCache[cacheOffset], 1);
		}
		else
		{
			SPI_Flash_write(FLASH_ADDRESS_OFFSET + (CODEPLUG_ADDR_CHANNEL_HEADER_FLASH + ((channelBank - 1) *
					(CODEPLUG_CHANNELS_PER_BANK * CODEPLUG_CHANNEL_DATA_STRUCT_SIZE + 16))) + byteno, &codeplugAllChannelsCache[cacheOffset], 1);
		}

		allChannelsTotalNumOfChannels++;
		if ((index + 1) > allChannelsHighestChannelIndex)
		{
			allChannelsHighestChannelIndex = (index + 1);
		}
	}
}

#if defined(CHANNEL_DELETE_ENABLED)
/* ---- R41: видалення каналу з меню рації ---------------------------------------------------------------------------------------- */

/* Перерахунок лічильників «усіх каналів» із кешу маски (після зміни біта). */
static void codeplugAllChannelsRecount(void)
{
	allChannelsTotalNumOfChannels = (uint16_t)codeplugChanMaskCount(codeplugAllChannelsCache);
	allChannelsHighestChannelIndex = (uint16_t)codeplugChanMaskHighest(codeplugAllChannelsCache);
}

int codeplugChannelCountInUse(void)
{
	return codeplugChanMaskCount(codeplugAllChannelsCache);
}

int codeplugChannelNextInUse(int afterIndex)
{
	return codeplugChanMaskNextInUse(codeplugAllChannelsCache, afterIndex);
}

/* У скількох справжніх зонах (без віртуальної «Всі канали») стоїть канал. Зона, де канал записано двічі, рахується один раз. */
int codeplugChannelCountZones(int channelIndex)
{
	CodeplugZone_t z;
	int n = 0;
	int realZones = codeplugZonesGetCount() - 1;

	for (int zn = 0; zn < realZones; zn++)
	{
		if (codeplugZoneGetDataForNumber(zn, &z) &&
				(codeplugZoneListCount(z.channels, z.NOT_IN_CODEPLUGDATA_numChannelsInZone, (uint16_t)channelIndex) > 0))
		{
			n++;
		}
	}

	return n;
}

/*
 * Видалення каналу. НОМЕРИ інших каналів не змінюються (зони посилаються на канали за номером). ПОРЯДОК КРОКІВ -- за стійкістю до обриву живлення:
 *   1. прибрати канал з УСІХ зон (без цього зона вказувала б на «неіснуючий» канал: навігація по зоні маску не перевіряє й завантажила б сміття);
 *   2. очистити біт у масці «в роботі» -- ось тут канал логічно зникає;
 *   3. поправити «останній канал у зоні» (LUCZ);
 *   4. стерти сам запис (0xFF) -- необов'язково для коректності, тому збій тут не робить видалення невдалим.
 * Обрив після кроку 1 лишає живий канал, якого нема в зонах (його видно в «Всі канали»); обрив після 2 -- видалений канал зі «сміттям» у записі, невидимий.
 */
CodeplugChannelDeleteResult_t codeplugChannelDelete(int channelIndex)
{
	CodeplugZone_t z;
	int realZones = codeplugZonesGetCount() - 1;
	bool luczChanged = false;
	bool inFlash;
	int cacheOffset;
	int addr;
	uint8_t maskByte;
	uint8_t blank[CODEPLUG_CHANNEL_DATA_STRUCT_SIZE];

	if (!codeplugAllChannelsIndexIsInUse(channelIndex))
	{
		return CODEPLUG_CHANNEL_DELETE_NOT_IN_USE;
	}

	if (codeplugChanMaskCount(codeplugAllChannelsCache) <= 1)
	{
		return CODEPLUG_CHANNEL_DELETE_LAST;
	}

	// 1. Зони
	for (int zn = 0; zn < realZones; zn++)
	{
		int num;
		int bit;
		int oldIdx;
		int newIdx;

		if (!codeplugZoneGetDataForNumber(zn, &z))
		{
			continue;
		}

		num = z.NOT_IN_CODEPLUGDATA_numChannelsInZone;
		if (codeplugZoneListCount(z.channels, num, (uint16_t)channelIndex) == 0)
		{
			continue;
		}

		bit = z.NOT_IN_CODEPLUGDATA_indexNumber;
		oldIdx = codeplugGetLastUsedChannelInZone(bit);
		newIdx = codeplugZoneIndexAfterRemove(z.channels, num, (uint16_t)channelIndex, oldIdx);
		codeplugZoneListRemove(z.channels, num, (uint16_t)channelIndex);

		// Розмір запису -- як у codeplugZoneAddChannelToZoneAndSave (структура в пам'яті більша, ніж у кодплазі)
		if (!EEPROM_Write(CODEPLUG_ADDR_EX_ZONE_LIST + (bit * (16 + (sizeof(uint16_t) * codeplugChannelsPerZone))),
				(uint8_t *)&z, ((codeplugChannelsPerZone == 16) ? CODEPLUG_ZONE_DATA_ORIGINAL_STRUCT_SIZE : CODEPLUG_ZONE_DATA_OPENGD77_STRUCT_SIZE)))
		{
			return CODEPLUG_CHANNEL_DELETE_WRITE_ERROR;
		}

		if (newIdx != oldIdx)
		{
			codeplugSetLastUsedChannelInZone(bit, (int16_t)newIdx);
			luczChanged = true;
		}
	}

	// 2. Маска «в роботі»: байт пишемо в EEPROM (канали 1..128) або флеш (129..1024), кеш міняємо лише після успішного запису
	addr = codeplugChanMaskByteAddr(channelIndex, CODEPLUG_ADDR_CHANNEL_HEADER_EEPROM, CODEPLUG_ADDR_CHANNEL_HEADER_FLASH, &inFlash, &cacheOffset);
	maskByte = codeplugAllChannelsCache[cacheOffset] & (uint8_t)~(1U << ((channelIndex - 1) % 8));
	if (!(inFlash ? SPI_Flash_write(FLASH_ADDRESS_OFFSET + addr, &maskByte, 1) : EEPROM_Write(addr, &maskByte, 1)))
	{
		return CODEPLUG_CHANNEL_DELETE_WRITE_ERROR;
	}
	codeplugChanMaskClear(codeplugAllChannelsCache, channelIndex);
	codeplugAllChannelsRecount();

	// 3. «Всі канали»: якщо останнім був видалений -- переставити на найближчий далі
	if (codeplugGetLastUsedChannelInZone(-1) == channelIndex)
	{
		codeplugSetLastUsedChannelInZone(-1, (int16_t)codeplugChanMaskNextInUse(codeplugAllChannelsCache, channelIndex));
		luczChanged = true;
	}
	if (luczChanged)
	{
		codeplugSaveLastUsedChannelInZone();
	}

	// 4. Стерти запис каналу (best effort)
	addr = codeplugChanRecordAddr(channelIndex, CODEPLUG_ADDR_CHANNEL_EEPROM, CODEPLUG_ADDR_CHANNEL_FLASH, &inFlash);
	memset(blank, 0xFF, sizeof(blank));
	if (inFlash)
	{
		SPI_Flash_write(FLASH_ADDRESS_OFFSET + addr, blank, sizeof(blank));
	}
	else
	{
		EEPROM_Write(addr, blank, sizeof(blank));
	}

	return CODEPLUG_CHANNEL_DELETE_OK;
}
#endif /* CHANNEL_DELETE_ENABLED */

void codeplugAllChannelsInitCache(void)
{
	// There are 8 banks
	for (uint16_t bank = 0; bank < CODEPLUG_CHANNELS_BANKS_MAX; bank++)
	{
		// Of 128 channels
		codeplugAllChannelsReadHeaderBank(bank, &codeplugAllChannelsCache[bank * 16]);
	}

	allChannelsHighestChannelIndex = 0;
	for (uint16_t index = CODEPLUG_CHANNELS_MAX; index >= CODEPLUG_CHANNELS_MIN ; index--)
	{
		if (codeplugAllChannelsIndexIsInUse(index))
		{
			allChannelsHighestChannelIndex = index;
			break;
		}
	}

	allChannelsTotalNumOfChannels = codeplugAllChannelsGetCount();
}

uint32_t codeplugChannelGetOptionalDMRID(CodeplugChannel_t *channelBuf)
{
	uint32_t retVal = 0;

	if (codeplugChannelGetFlag(channelBuf, CHANNEL_FLAG_OPTIONAL_DMRID) != 0)
	{
		retVal = ((channelBuf->rxSignaling << 16) | (channelBuf->artsInterval << 8) | channelBuf->encrypt);
	}

	return retVal;
}

void codeplugChannelSetOptionalDMRID(CodeplugChannel_t *channelBuf, uint32_t dmrID)
{
	uint32_t tmpID = 0x00001600;
	bool dmrIDIsValid = ((dmrID >= MIN_TG_OR_PC_VALUE) && (dmrID <= MAX_TG_OR_PC_VALUE));

	//  Default values are:
	//
	//	rxSignaling = 0x00  e.g. SignalingSystemE.Off
	//  artsInterval = 22 = 0x16
	//  encrypt = 0x00;
	//

	// Set DMRId and flag, if valid.
	if (dmrIDIsValid)
	{
		tmpID = dmrID;
	}

	codeplugChannelSetFlag(channelBuf, CHANNEL_FLAG_OPTIONAL_DMRID, (dmrIDIsValid ? 1 : 0));

	channelBuf->rxSignaling = (tmpID >> 16) & 0xFF;
	channelBuf->artsInterval = (tmpID >> 8) & 0xFF;
	channelBuf->encrypt = tmpID & 0xFF;
}

// -----------------------------------
// -- Codeplug channel flag helpers --
// -----------------------------------
typedef uint8_t *(*flagGetter_t)(CodeplugChannel_t *chan);
static uint8_t *_getLDMRFlag1(CodeplugChannel_t *chan)
{
	return &chan->LibreDMR_flag1;
}
static uint8_t *_getFlag2(CodeplugChannel_t *chan)
{
	return &chan->flag2;
}
static uint8_t *_getFlag3(CodeplugChannel_t *chan)
{
	return &chan->flag3;
}
static uint8_t *_getFlag4(CodeplugChannel_t *chan)
{
	return &chan->flag4;
}

struct
{
		flagGetter_t getter;
		uint8_t      mask;
		uint8_t      shift;
} flagAccessor[] = // The order of this array HAS to follow ChannelFlag_t enum
{
		// LibreDMR_flag1
		{ _getLDMRFlag1, CODEPLUG_CHANNEL_LIBREDMR_FLAG1_OPTIONAL_DMRID,      7 }, // CHANNEL_FLAG_OPTIONAL_DMRID
		{ _getLDMRFlag1, CODEPLUG_CHANNEL_LIBREDMR_FLAG1_NO_BEEP,             6 }, // CHANNEL_FLAG_NO_BEEP,
		{ _getLDMRFlag1, CODEPLUG_CHANNEL_LIBREDMR_FLAG1_NO_ECO,              5 }, // CHANNEL_FLAG_NO_ECO,
		{ _getLDMRFlag1, CODEPLUG_CHANNEL_LIBREDMR_FLAG1_OUT_OF_BAND,         4 }, // CHANNEL_FLAG_OUT_OF_BAND,
		{ _getLDMRFlag1, CODEPLUG_CHANNEL_LIBREDMR_FLAG1_USE_LOCATION,        3 }, // CHANNEL_FLAG_USE_LOCATION
		{ _getLDMRFlag1, CODEPLUG_CHANNEL_LIBREDMR_FLAG1_FORCE_DMO,           2 }, // CHANNEL_FLAG_FORCE_DMO
		{ _getLDMRFlag1, CODEPLUG_CHANNEL_LIBREDMR_FLAG1_ROAMING,             0 }, // CHANNEL_FLAG_ROAMING
		// flag2
		{ _getFlag2,     CODEPLUG_CHANNEL_FLAG2_TIMESLOT_TWO,                 6 }, // CHANNEL_FLAG_TIMESLOT_TWO,
		// flag3
		{ _getFlag3,     CODEPLUG_CHANNEL_FLAG3_STE,                          6 }, // CHANNEL_FLAG_STE,
		{ _getFlag3,     CODEPLUG_CHANNEL_FLAG3_NON_STE,                      5 }, // CHANNEL_FLAG_NON_STE,
		// flag4
		{ _getFlag4,     CODEPLUG_CHANNEL_FLAG4_POWER,                        7 }, // CHANNEL_FLAG_POWER,
		{ _getFlag4,     CODEPLUG_CHANNEL_FLAG4_VOX,                          6 }, // CHANNEL_FLAG_VOX,
		{ _getFlag4,     CODEPLUG_CHANNEL_FLAG4_ZONE_SKIP,                    5 }, // CHANNEL_FLAG_ZONE_SKIP,
		{ _getFlag4,     CODEPLUG_CHANNEL_FLAG4_ALL_SKIP,                     4 }, // CHANNEL_FLAG_ALL_SKIP,
		// Talkaround is unused (bit #3)
		{ _getFlag4,     CODEPLUG_CHANNEL_FLAG4_RX_ONLY,                      2 }, // CHANNEL_FLAG_RX_ONLY,
		{ _getFlag4,     CODEPLUG_CHANNEL_FLAG4_BW_25K,                       1 }, // CHANNEL_FLAG_BW_25K,
		{ _getFlag4,     CODEPLUG_CHANNEL_FLAG4_SQUELCH,                      0 }  // CHANNEL_FLAG_SQUELCH,
};

//
// Returns 0, 1 or the value (e.g. CODEPLUG_CHANNEL_FLAG3_STE), right shifted
//
uint8_t codeplugChannelGetFlag(CodeplugChannel_t *channelBuf, ChannelFlag_t flag)
{
	return ((*flagAccessor[flag].getter(channelBuf) & flagAccessor[flag].mask) >> flagAccessor[flag].shift);
}

//
// Returns unshifted value
//
uint8_t codeplugChannelSetFlag(CodeplugChannel_t *channelBuf, ChannelFlag_t flag, uint8_t value)
{
	uint8_t *data = flagAccessor[flag].getter(channelBuf);

	*data &= ~flagAccessor[flag].mask;

	if (value)
	{
		*data |= (value << flagAccessor[flag].shift);
	}

	return value;
}
// ----------------------------------------
// -- END: Codeplug channel flag helpers --
// ----------------------------------------

void codeplugChannelGetDataWithOffsetAndLengthForIndex(int index, CodeplugChannel_t *channelBuf, uint8_t offset, int length)
{
	// lower 128 channels are in EEPROM. Remaining channels are in Flash ! (What a mess...)
	index--; // I think the channel index numbers start from 1 not zero.
	if (index < 128)
	{
		EEPROM_Read((CODEPLUG_ADDR_CHANNEL_EEPROM + index * CODEPLUG_CHANNEL_DATA_STRUCT_SIZE) + offset, ((uint8_t *)channelBuf) + offset, length);
	}
	else
	{
		int flashReadPos = CODEPLUG_ADDR_CHANNEL_FLASH;

		index -= 128;// First 128 channels are in the EEPROM, so subtract 128 from the number when looking in the Flash

		// Every 128 bytes there seem to be 16 bytes gaps. I don't know why,bits since 16*8 = 128 bits, its likely they are flag bytes to indicate which channel in the next block are in use
		flashReadPos += 16 * (index / 128);// we just need to skip over that these flag bits when calculating the position of the channel data in memory

		SPI_Flash_read(FLASH_ADDRESS_OFFSET + (flashReadPos + index * CODEPLUG_CHANNEL_DATA_STRUCT_SIZE) + offset, ((uint8_t *)channelBuf) + offset, length);
	}
}

void codeplugChannelGetDataForIndex(int index, CodeplugChannel_t *channelBuf)
{
	// Read the whole channel
	codeplugChannelGetDataWithOffsetAndLengthForIndex(index, channelBuf, 0, CODEPLUG_CHANNEL_DATA_STRUCT_SIZE);

	channelBuf->chMode = (channelBuf->chMode == 0) ? RADIO_MODE_ANALOG : RADIO_MODE_DIGITAL;
	// Convert legacy codeplug tx and rx freq values into normal integers
	channelBuf->txFreq = bcd2int(channelBuf->txFreq);
	channelBuf->rxFreq = bcd2int(channelBuf->rxFreq);
	channelBuf->txTone = codeplugCSSToInt(channelBuf->txTone);
	channelBuf->rxTone = codeplugCSSToInt(channelBuf->rxTone);

	channelBuf->NOT_IN_CODEPLUG_flag = 0x00;
	channelBuf->NOT_IN_CODEPLUG_CALCULATED_DISTANCE_X10 = -1;

	// Sanity check the sql value, because its not used by the official firmware and may contain random value e.g. 255
	if (channelBuf->sql > 21)
	{
		channelBuf->sql = 10;
	}
	/* 2020.10.27 vk3kyy - I don't think this is necessary as the function which loads the contact treats index = 0 as a special case and always loads TG 9
	 *
	// Sanity check the digital contact and set it to 1 is its not been assigned, even for FM channels, as the user could switch to DMR on this channel
	if (channelBuf->contact == 0)
	{
		channelBuf->contact = 1;
	}*/
}

bool codeplugChannelSaveDataForIndex(int index, CodeplugChannel_t *channelBuf)
{
	bool retVal = true;
#if defined(PLATFORM_MD9600)
	bool outOfBandFlag = ((channelBuf->LibreDMR_flag1 & CODEPLUG_CHANNEL_LIBREDMR_FLAG1_OUT_OF_BAND) != 0);

	// Clear the out of band flag, blindly.
	channelBuf->LibreDMR_flag1 &= ~CODEPLUG_CHANNEL_LIBREDMR_FLAG1_OUT_OF_BAND;
#endif

	channelBuf->chMode = (channelBuf->chMode == RADIO_MODE_ANALOG) ? 0 : 1;
	// Convert normal integers into legacy codeplug tx and rx freq values
	channelBuf->txFreq = int2bcd(channelBuf->txFreq);
	channelBuf->rxFreq = int2bcd(channelBuf->rxFreq);
	channelBuf->txTone = codeplugIntToCSS(channelBuf->txTone);
	channelBuf->rxTone = codeplugIntToCSS(channelBuf->rxTone);

	// lower 128 channels are in EEPROM. Remaining channels are in Flash ! (What a mess...)
	index--; // I think the channel index numbers start from 1 not zero.
	if (index < 128)
	{
		retVal = EEPROM_Write(CODEPLUG_ADDR_CHANNEL_EEPROM + index * CODEPLUG_CHANNEL_DATA_STRUCT_SIZE, (uint8_t *)channelBuf, CODEPLUG_CHANNEL_DATA_STRUCT_SIZE);
	}
	else
	{
		int flashWritePos = CODEPLUG_ADDR_CHANNEL_FLASH;
		int flashSector;
		int flashEndSector;
		int bytesToWriteInCurrentSector = CODEPLUG_CHANNEL_DATA_STRUCT_SIZE;

		index -= 128;// First 128 channels are in the EEPOM, so subtract 128 from the number when looking in the Flash

		// Every 128 bytes there seem to be 16 bytes gaps. I don't know why,bits since 16*8 = 128 bits, its likely they are flag bytes to indicate which channel in the next block are in use
		flashWritePos += 16 * (index / 128);// we just need to skip over that these flag bits when calculating the position of the channel data in memory
		flashWritePos += index * CODEPLUG_CHANNEL_DATA_STRUCT_SIZE;// go to the position of the specific index

		flashSector 	= flashWritePos / 4096;
		flashEndSector 	= (flashWritePos + CODEPLUG_CHANNEL_DATA_STRUCT_SIZE) / 4096;

		if (flashSector != flashEndSector)
		{
			bytesToWriteInCurrentSector = (flashEndSector * 4096) - flashWritePos;
		}

		SPI_Flash_read(FLASH_ADDRESS_OFFSET + (flashSector * 4096), SPI_Flash_sectorbuffer, 4096);
		uint8_t *writePos = SPI_Flash_sectorbuffer + flashWritePos - (flashSector * 4096);
		memcpy(writePos, channelBuf, bytesToWriteInCurrentSector);

		retVal = SPI_Flash_eraseSector(FLASH_ADDRESS_OFFSET + (flashSector * 4096));
		if (!retVal)
		{
			goto errorExit;
		}

		for (int i = 0; i < 16; i++)
		{
			retVal = SPI_Flash_writePage(FLASH_ADDRESS_OFFSET + (flashSector * 4096) + (i * 256), SPI_Flash_sectorbuffer + (i * 256));
			if (!retVal)
			{
				goto errorExit;
			}
		}

		if (flashSector != flashEndSector)
		{
			uint8_t *channelBufPusOffset = (uint8_t *)channelBuf + bytesToWriteInCurrentSector;
			bytesToWriteInCurrentSector = CODEPLUG_CHANNEL_DATA_STRUCT_SIZE - bytesToWriteInCurrentSector;

			SPI_Flash_read(FLASH_ADDRESS_OFFSET + (flashEndSector * 4096), SPI_Flash_sectorbuffer, 4096);
			memcpy(SPI_Flash_sectorbuffer, (uint8_t *)channelBufPusOffset, bytesToWriteInCurrentSector);

			retVal = SPI_Flash_eraseSector(FLASH_ADDRESS_OFFSET + (flashEndSector * 4096));

			if (!retVal)
			{
				goto errorExit;
			}
			for (int i = 0; i < 16; i++)
			{
				retVal = SPI_Flash_writePage(FLASH_ADDRESS_OFFSET + (flashEndSector * 4096) + (i * 256), SPI_Flash_sectorbuffer + (i * 256));

				if (!retVal)
				{
					goto errorExit;
				}
			}

		}
	}

errorExit:
#if defined(PLATFORM_MD9600)
	if (outOfBandFlag)
	{
		channelBuf->LibreDMR_flag1 |= CODEPLUG_CHANNEL_LIBREDMR_FLAG1_OUT_OF_BAND;
	}
#endif

	// Need to restore the values back to what we need for the operation of the firmware rather than the BCD values the codeplug uses
	channelBuf->chMode = (channelBuf->chMode == 0) ? RADIO_MODE_ANALOG : RADIO_MODE_DIGITAL;
	// Convert the the legacy codeplug tx and rx freq values into normal integers
	channelBuf->txFreq = bcd2int(channelBuf->txFreq);
	channelBuf->rxFreq = bcd2int(channelBuf->rxFreq);
	channelBuf->txTone = codeplugCSSToInt(channelBuf->txTone);
	channelBuf->rxTone = codeplugCSSToInt(channelBuf->rxTone);

	return retVal;
}

static void codeplugRxGroupInitCache(void)
{
	SPI_Flash_read(FLASH_ADDRESS_OFFSET + CODEPLUG_ADDR_RX_GROUP_LEN, (uint8_t*) &codeplugRXGroupCache[0], CODEPLUG_RX_GROUPLIST_MAX);
}

bool codeplugRxGroupGetDataForIndex(int index, CodeplugRxGroup_t *rxGroupBuf)
{
	int i = 0;
	CodeplugContact_t contactData;

	if ((index >= 1) && (index <= CODEPLUG_RX_GROUPLIST_MAX))
	{
		index--; // Index numbers start from 1 not zero

		if (codeplugRXGroupCache[index] > 0)
		{
			// Not our struct contains an extra property to hold the number of TGs in the group
			SPI_Flash_read(FLASH_ADDRESS_OFFSET + CODEPLUG_ADDR_RX_GROUP + (index * CODEPLUG_RXGROUP_DATA_STRUCT_SIZE), (uint8_t *) rxGroupBuf, CODEPLUG_RXGROUP_DATA_STRUCT_SIZE);

			for (i = 0; i < 32; i++)
			{
				codeplugContactGetDataForIndex(rxGroupBuf->contacts[i], &contactData);
				rxGroupBuf->NOT_IN_CODEPLUG_contactsTG[i] = contactData.tgNumber;
				// Empty groups seem to be filled with zeros
				if (rxGroupBuf->contacts[i] == 0)
				{
					break;
				}
			}

			rxGroupBuf->NOT_IN_CODEPLUG_numTGsInGroup = i;
			return true;
		}
	}

	rxGroupBuf->name[0] = 0;
	rxGroupBuf->NOT_IN_CODEPLUG_numTGsInGroup = 0;
	return false;
}

#if defined(ENABLE_DUAL_CHANNEL) && defined(LANGUAGE_BUILD_UKRAINIAN) && defined(PLATFORM_MDUV380)   /* = DUAL_CHANNEL_ENABLED (dual_channel.h) */
// R97-FIX7: індекс контакту в списку прийому каналу за позицією -- для екрана «Подвійного прийому» (призначення передачі). Читає лише 64 байти
// списку контактів (а не 212-байтову CodeplugRxGroup_t зі 32 запитами контактів). Правило позиції -- як у стоковому завантаженні каналу:
// позиція поза списком -> перший. Повертає 0, якщо списку нема або він порожній (тоді діє контакт самого каналу); *numTGs -- кількість ТГ.
int codeplugRxGroupGetContactAt(int index, int pos, int *numTGs)
{
	uint16_t contacts[32];
	int n = 0;

	*numTGs = 0;

	if ((index < 1) || (index > CODEPLUG_RX_GROUPLIST_MAX) || (codeplugRXGroupCache[index - 1] == 0))
	{
		return 0;
	}

	SPI_Flash_read(FLASH_ADDRESS_OFFSET + CODEPLUG_ADDR_RX_GROUP + ((index - 1) * CODEPLUG_RXGROUP_DATA_STRUCT_SIZE) + 16, (uint8_t *)contacts, sizeof(contacts));

	while ((n < 32) && (contacts[n] != 0))
	{
		n++;
	}

	*numTGs = n;

	if (n == 0)
	{
		return 0;
	}

	return contacts[((pos < 0) || (pos >= n)) ? 0 : pos];
}
#endif

int codeplugDTMFContactsGetCount(void)
{
	return codeplugContactsCache.numDTMFContacts;
}

int codeplugContactsGetCount(uint32_t callType) // 0:TG 1:PC 2:ALL
{
	switch (callType)
	{
		case CONTACT_CALLTYPE_TG:
			return codeplugContactsCache.numTGContacts;
			break;
		case CONTACT_CALLTYPE_PC:
			return codeplugContactsCache.numPCContacts;
			break;
		case CONTACT_CALLTYPE_ALL:
			return codeplugContactsCache.numALLContacts;
			break;
	}

	return 0; // Should not happen
}

// Returns contact's index, or 0 on failure.
int codeplugDTMFContactGetDataForNumber(int number, CodeplugDTMFContact_t *contact)
{
	if ((number >= CODEPLUG_DTMF_CONTACTS_MIN) && (number <= CODEPLUG_DTMF_CONTACTS_MAX))
	{
		if (codeplugDTMFContactGetDataForIndex(codeplugContactsCache.contactsDTMFLookupCache[number - 1].index, contact))
		{
			return codeplugContactsCache.contactsDTMFLookupCache[number - 1].index;
		}
	}

	return 0;
}

// Returns contact's index, or 0 on failure.
int codeplugContactGetDataForNumberInType(int number, uint32_t callType, CodeplugContact_t *contact)
{
	int numContacts = codeplugContactsCache.numTGContacts + codeplugContactsCache.numALLContacts + codeplugContactsCache.numPCContacts;

	for (int i = 0; i < numContacts; i++)
	{
		if ((codeplugContactsCache.contactsLookupCache[i].tgOrPCNum >> 24) == callType)
		{
			number--;
		}

		if (number == 0)
		{
			if (codeplugContactGetDataForIndex(codeplugContactsCache.contactsLookupCache[i].index, contact))
			{
				return codeplugContactsCache.contactsLookupCache[i].index;
			}
		}
	}

	return 0;
}

// optionalTS: 0 = no TS checking, 1..2 = TS
int codeplugContactIndexByTGorPCFromNumber(int number, uint32_t tgorpc, ContactCalltype_t callType, CodeplugContact_t *contact, uint8_t optionalTS)
{
	int numContacts = codeplugContactsCache.numTGContacts + codeplugContactsCache.numALLContacts + codeplugContactsCache.numPCContacts;
	int firstMatch = -1;

	for (int i = number; i < numContacts; i++)
	{
		if (((codeplugContactsCache.contactsLookupCache[i].tgOrPCNum & 0xFFFFFF) == tgorpc) &&
				/* All Call, hence ignore callType */
				((tgorpc == ALL_CALL_VALUE) || ((codeplugContactsCache.contactsLookupCache[i].tgOrPCNum >> 24) == callType)))
		{
			// Check for the contact TS override
			if (optionalTS > 0)
			{
				// Just read the reserve1 byte for now
				codeplugContactGetReserve1ByteForIndex(codeplugContactsCache.contactsLookupCache[i].index, contact);

				if (((contact->reserve1 & CODEPLUG_CONTACT_FLAG_NO_TS_OVERRIDE) == 0x00) && (((contact->reserve1 & CODEPLUG_CONTACT_FLAG_TS_OVERRIDE_TIMESLOT_MASK) >> 1) == (optionalTS - 1)))
				{
					codeplugContactGetDataForIndex(codeplugContactsCache.contactsLookupCache[i].index, contact);
					return i;
				}
				else
				{
					if (firstMatch < 0)
					{
						firstMatch = i;
					}
				}
			}
			else
			{
				codeplugContactGetDataForIndex(codeplugContactsCache.contactsLookupCache[i].index, contact);
				return i;
			}
		}
	}

	if (firstMatch >= 0)
	{
		codeplugContactGetDataForIndex(codeplugContactsCache.contactsLookupCache[firstMatch].index, contact);
		return firstMatch;
	}

	return -1;
}

// optionalTS: 0 = no TS checking, 1..2 = TS
int codeplugContactIndexByTGorPC(uint32_t tgorpc, ContactCalltype_t callType, CodeplugContact_t *contact, uint8_t optionalTS)
{
	return codeplugContactIndexByTGorPCFromNumber(0, tgorpc, callType, contact, optionalTS);
}

bool codeplugContactsContainsPC(uint32_t pc)
{
	int numContacts =  codeplugContactsCache.numTGContacts + codeplugContactsCache.numALLContacts + codeplugContactsCache.numPCContacts;
	pc = pc & 0x00FFFFFF;
	pc = pc | (CONTACT_CALLTYPE_PC << 24);

	for (int i = 0; i < numContacts; i++)
	{
		if (codeplugContactsCache.contactsLookupCache[i].tgOrPCNum == pc)
		{
			return true;
		}
	}
	return false;
}

static void codeplugInitContactsCache(void)
{
	CodeplugContact_t contact;
	uint8_t                  c;
	int                      codeplugNumContacts = 0;

	codeplugContactsCache.numTGContacts = 0;
	codeplugContactsCache.numPCContacts = 0;
	codeplugContactsCache.numALLContacts = 0;
	codeplugContactsCache.numDTMFContacts = 0;

	for(int i = 0; i < CODEPLUG_CONTACTS_MAX; i++)
	{
		if (SPI_Flash_read(FLASH_ADDRESS_OFFSET + (CODEPLUG_ADDR_CONTACTS + (i * CODEPLUG_CONTACT_DATA_SIZE)), (uint8_t *)&contact, 16 + 4 + 1))// Name + TG/ID + Call type
		{
			if (contact.name[0] != 0xFF)
			{
				codeplugContactsCache.contactsLookupCache[codeplugNumContacts].tgOrPCNum = bcd2int(byteSwap32(contact.tgNumber));
				codeplugContactsCache.contactsLookupCache[codeplugNumContacts].index = i + 1;// Contacts are numbered from 1 to 1024
				codeplugContactsCache.contactsLookupCache[codeplugNumContacts].tgOrPCNum |= (contact.callType << 24);// Store the call type in the upper byte
				if (contact.callType == CONTACT_CALLTYPE_PC)
				{
					codeplugContactsCache.numPCContacts++;
				}
				else if (contact.callType == CONTACT_CALLTYPE_TG)
				{
					codeplugContactsCache.numTGContacts++;
				}
				else if (contact.callType == CONTACT_CALLTYPE_ALL)
				{
					codeplugContactsCache.numALLContacts++;
				}

				codeplugNumContacts++;
			}
		}
	}

	for (int i = 0; i < CODEPLUG_DTMF_CONTACTS_MAX; i++)
	{
		if (EEPROM_Read(CODEPLUG_ADDR_DTMF_CONTACTS + (i * CODEPLUG_DTMF_CONTACT_DATA_STRUCT_SIZE), (uint8_t *)&c, 1))
		{
			// Empty DTMF contacts normally begin with 0xFF, but when expanding to use 64 DTMF contacts, the old Zone
			// basic data is in the last contact and this contains 0x00 in the first byte, until the codeplug is updated
			if ((c != 0xFF) && (c != 0x00))
			{
				codeplugContactsCache.contactsDTMFLookupCache[codeplugContactsCache.numDTMFContacts++].index = i + 1; // Contacts are numbered from 1 to 32
			}
		}
	}
}

void codeplugContactsCacheUpdateOrInsertContactAt(int index, CodeplugContact_t *contact)
{
	int numContacts =  codeplugContactsCache.numTGContacts + codeplugContactsCache.numALLContacts + codeplugContactsCache.numPCContacts;
	int numContactsMinus1 = numContacts - 1;

	for(int i = 0; i < numContacts; i++)
	{
		// Check if the contact is already in the cache, and is being modified
		if (codeplugContactsCache.contactsLookupCache[i].index == index)
		{
			uint8_t callType = codeplugContactsCache.contactsLookupCache[i].tgOrPCNum >> 24;// get call type from cache

			if (callType != contact->callType)
			{
				switch (callType)
				{
					case CONTACT_CALLTYPE_TG:
						codeplugContactsCache.numTGContacts--;
						break;
					case CONTACT_CALLTYPE_PC:
						codeplugContactsCache.numPCContacts--;
						break;
					case CONTACT_CALLTYPE_ALL:
						codeplugContactsCache.numALLContacts--;
						break;
				}

				switch (contact->callType)
				{
					case CONTACT_CALLTYPE_TG:
						codeplugContactsCache.numTGContacts++;
						break;
					case CONTACT_CALLTYPE_PC:
						codeplugContactsCache.numPCContacts++;
						break;
					case CONTACT_CALLTYPE_ALL:
						codeplugContactsCache.numALLContacts++;
						break;
				}
			}
			//update the
			codeplugContactsCache.contactsLookupCache[i].tgOrPCNum = bcd2int(byteSwap32(contact->tgNumber));
			codeplugContactsCache.contactsLookupCache[i].tgOrPCNum |= (contact->callType << 24);// Store the call type in the upper byte

			return;
		}
		else
		{
			if((i < numContactsMinus1) && (codeplugContactsCache.contactsLookupCache[i].index < index) && (codeplugContactsCache.contactsLookupCache[i + 1].index > index))
			{
				if (contact->callType == CONTACT_CALLTYPE_PC)
				{
					codeplugContactsCache.numPCContacts++;
				}
				else if (contact->callType == CONTACT_CALLTYPE_TG)
				{
					codeplugContactsCache.numTGContacts++;
				}
				else if (contact->callType == CONTACT_CALLTYPE_ALL)
				{
					codeplugContactsCache.numALLContacts++;
				}

				numContacts++;// Total contacts increases by 1

				// Note . Need to use memmove as the source and destination overlap.
				memmove(&codeplugContactsCache.contactsLookupCache[i + 2], &codeplugContactsCache.contactsLookupCache[i + 1], (numContacts - 2 - i) * sizeof(codeplugContactCache_t));

				codeplugContactsCache.contactsLookupCache[i + 1].tgOrPCNum = bcd2int(byteSwap32(contact->tgNumber));
				codeplugContactsCache.contactsLookupCache[i + 1].index = index;// Contacts are numbered from 1 to 1024
				codeplugContactsCache.contactsLookupCache[i + 1].tgOrPCNum |= (contact->callType << 24);// Store the call type in the upper byte
				return;
			}
		}
	}

	// Did not find the index in the cache or a gap between 2 existing indexes. So the new contact needs to be added to the end of the cache

	if (contact->callType == CONTACT_CALLTYPE_PC)
	{
		codeplugContactsCache.numPCContacts++;
	}
	else if (contact->callType == CONTACT_CALLTYPE_TG)
	{
		codeplugContactsCache.numTGContacts++;
	}
	else if (contact->callType == CONTACT_CALLTYPE_ALL)
	{
		codeplugContactsCache.numALLContacts++;
	}

	// Note. We can use numContacts as the the index as the array is zero indexed but the number of contacts is starts from 1
	// Hence is already in some ways pre incremented in terms of being an array index
	codeplugContactsCache.contactsLookupCache[numContacts].tgOrPCNum = bcd2int(byteSwap32(contact->tgNumber));
	codeplugContactsCache.contactsLookupCache[numContacts].index = index;// Contacts are numbered from 1 to 1024
	codeplugContactsCache.contactsLookupCache[numContacts].tgOrPCNum |= (contact->callType << 24);// Store the call type in the upper byte
}

void codeplugContactsCacheRemoveContactAt(int index)
{
	int numContacts = codeplugContactsCache.numTGContacts + codeplugContactsCache.numALLContacts + codeplugContactsCache.numPCContacts;
	for(int i = 0; i < numContacts; i++)
	{
		if(codeplugContactsCache.contactsLookupCache[i].index == index)
		{
			uint8_t callType = codeplugContactsCache.contactsLookupCache[i].tgOrPCNum >> 24;

			if (callType == CONTACT_CALLTYPE_PC)
			{
				codeplugContactsCache.numPCContacts--;
			}
			else if (callType == CONTACT_CALLTYPE_TG)
			{
				codeplugContactsCache.numTGContacts--;
			}
			else if (callType == CONTACT_CALLTYPE_ALL)
			{
				codeplugContactsCache.numALLContacts--;
			}
			// Note memcpy should work here, because memcpy normally copys from the lowest memory location upwards
			memcpy(&codeplugContactsCache.contactsLookupCache[i], &codeplugContactsCache.contactsLookupCache[i + 1], (numContacts - 1 - i) * sizeof(codeplugContactCache_t));
			return;
		}
	}
}

uint32_t codeplugContactGetPackedId(CodeplugContact_t *contact)
{
	return ((contact->callType == CONTACT_CALLTYPE_PC) ? (contact->tgNumber | (PC_CALL_FLAG << 24)) : contact->tgNumber);
}

int codeplugContactGetFreeIndex(void)
{
	int numContacts = codeplugContactsCache.numTGContacts + codeplugContactsCache.numALLContacts + codeplugContactsCache.numPCContacts;
	int lastIndex = 0;
	int i;

	for (i = 0; i < numContacts; i++)
	{
		if (codeplugContactsCache.contactsLookupCache[i].index != lastIndex + 1)
		{
			return lastIndex + 1;
		}
		lastIndex = codeplugContactsCache.contactsLookupCache[i].index;
	}

	if (i < CODEPLUG_CONTACTS_MAX)
	{
		return codeplugContactsCache.contactsLookupCache[i - 1].index + 1;
	}

	return 0;
}

bool codeplugDTMFContactGetDataForIndex(int index, CodeplugDTMFContact_t *contact)
{
	if ((codeplugContactsCache.numDTMFContacts > 0) &&  (index >= CODEPLUG_DTMF_CONTACTS_MIN) && (index <= CODEPLUG_DTMF_CONTACTS_MAX))
	{
		index--;
		if(EEPROM_Read(CODEPLUG_ADDR_DTMF_CONTACTS + (index * CODEPLUG_DTMF_CONTACT_DATA_STRUCT_SIZE), (uint8_t *)contact, CODEPLUG_DTMF_CONTACT_DATA_STRUCT_SIZE))
		{
			return true;
		}
	}

	memset(contact, 0xff, CODEPLUG_DTMF_CONTACT_DATA_STRUCT_SIZE);
	return false;
}

static bool codeplugContactGetReserve1ByteForIndex(int index, CodeplugContact_t *contact)
{
	if (((codeplugContactsCache.numTGContacts > 0) || (codeplugContactsCache.numPCContacts > 0) || (codeplugContactsCache.numALLContacts > 0)) &&
			(index >= CODEPLUG_CONTACTS_MIN) && (index <= CODEPLUG_CONTACTS_MAX))
	{
		index--;
		SPI_Flash_read(FLASH_ADDRESS_OFFSET + CODEPLUG_ADDR_CONTACTS + (index * CODEPLUG_CONTACT_DATA_SIZE) + 23 , (uint8_t *)contact + 23, 1);
		return true;
	}
	return false;
}

bool codeplugContactGetDataForIndex(int index, CodeplugContact_t *contact)
{
	char buf[SCREEN_LINE_BUFFER_SIZE];

	if (((codeplugContactsCache.numTGContacts > 0) || (codeplugContactsCache.numPCContacts > 0) || (codeplugContactsCache.numALLContacts > 0)) &&
			(index >= CODEPLUG_CONTACTS_MIN) && (index <= CODEPLUG_CONTACTS_MAX))
	{
		index--;
		SPI_Flash_read(FLASH_ADDRESS_OFFSET + CODEPLUG_ADDR_CONTACTS + index * CODEPLUG_CONTACT_DATA_SIZE, (uint8_t *)contact, CODEPLUG_CONTACT_DATA_SIZE);
		contact->NOT_IN_CODEPLUGDATA_indexNumber = index + 1;
		contact->tgNumber = bcd2int(byteSwap32(contact->tgNumber));
		return true;
	}

	// If an invalid contact number has been requested, return a TG 9 contact
	contact->tgNumber = 9;
	contact->callType = CONTACT_CALLTYPE_TG;
	contact->reserve1 = 0xff;
	contact->NOT_IN_CODEPLUGDATA_indexNumber = -1;
	snprintf(buf, SCREEN_LINE_BUFFER_SIZE, "%s 9", currentLanguage->tg);
	codeplugUtilConvertStringToBuf(buf, contact->name, 16);
	return false;
}

int codeplugContactSaveDataForIndex(int index, CodeplugContact_t *contact)
{
	int retVal;
	int flashWritePos = CODEPLUG_ADDR_CONTACTS;
	int flashSector;
	int flashEndSector;
	int bytesToWriteInCurrentSector = CODEPLUG_CONTACT_DATA_SIZE;
	uint32_t unconvertedTgNumber = contact->tgNumber;

	index--;
	contact->tgNumber = byteSwap32(int2bcd(contact->tgNumber));

	flashWritePos += index * CODEPLUG_CONTACT_DATA_SIZE;// go to the position of the specific index

	flashSector 	= flashWritePos / 4096;
	flashEndSector 	= (flashWritePos + CODEPLUG_CONTACT_DATA_SIZE) / 4096;

	if (flashSector != flashEndSector)
	{
		bytesToWriteInCurrentSector = (flashEndSector * 4096) - flashWritePos;
	}

	SPI_Flash_read(FLASH_ADDRESS_OFFSET + (flashSector * 4096), SPI_Flash_sectorbuffer, 4096);
	uint8_t *writePos = SPI_Flash_sectorbuffer + flashWritePos - (flashSector * 4096);
	memcpy(writePos, contact, bytesToWriteInCurrentSector);

	retVal = SPI_Flash_eraseSector(FLASH_ADDRESS_OFFSET + (flashSector * 4096));
	if (!retVal)
	{
		goto hasFailed;
	}

	for (int i = 0; i < 16; i++)
	{
		retVal = SPI_Flash_writePage(FLASH_ADDRESS_OFFSET + (flashSector * 4096) + (i * 256), SPI_Flash_sectorbuffer + (i * 256));
		if (!retVal)
		{
			goto hasFailed;
		}
	}

	if (flashSector != flashEndSector)
	{
		uint8_t *channelBufPusOffset = (uint8_t *)contact + bytesToWriteInCurrentSector;
		bytesToWriteInCurrentSector = CODEPLUG_CONTACT_DATA_SIZE - bytesToWriteInCurrentSector;

		SPI_Flash_read(FLASH_ADDRESS_OFFSET + (flashEndSector * 4096), SPI_Flash_sectorbuffer, 4096);
		memcpy(SPI_Flash_sectorbuffer, (uint8_t *)channelBufPusOffset, bytesToWriteInCurrentSector);

		retVal = SPI_Flash_eraseSector(FLASH_ADDRESS_OFFSET + (flashEndSector * 4096));

		if (!retVal)
		{
			goto hasFailed;
		}

		for (int i = 0; i < 16; i++)
		{
			retVal = SPI_Flash_writePage(FLASH_ADDRESS_OFFSET + (flashEndSector * 4096) + (i * 256), SPI_Flash_sectorbuffer + (i * 256));

			if (!retVal)
			{
				goto hasFailed;
			}
		}

	}
	if ((contact->name[0] == 0xff) || (contact->callType == 0xFF))
	{
		codeplugContactsCacheRemoveContactAt(index + 1);// index was decremented at the start of the function
	}
	else
	{
		codeplugContactsCacheUpdateOrInsertContactAt(index + 1, contact);
		//initCodeplugContactsCache();// Update the cache
	}


	hasFailed:

	// Restore contact's TG number
	contact->tgNumber = unconvertedTgNumber;

	return retVal;
}

bool codeplugContactGetRXGroup(int index)
{
	CodeplugRxGroup_t rxGroupBuf;
	int i;

	for (i = 1; i <= CODEPLUG_RX_GROUPLIST_MAX; i++)
	{
		if (codeplugRxGroupGetDataForIndex(i, &rxGroupBuf))
		{
			for (int j = 0; j < 32; j++)
			{
				if (rxGroupBuf.contacts[j] == index)
				{
					return true;
				}
			}
		}
	}
	return false;
}

#if defined(CODEPLUG_MENU_ENABLED)
/* ---- R44: видалення контакту з каскадом ------------------------------------------------------------------------------------------ */

/* Поле «контакт» каналу (2 байти, індекс 1..1024; 0 -- «Немає»). Читаємо лише його: канали по одному, без копії списку. */
static uint16_t codeplugChannelContactField(int channelIndex)
{
	CodeplugChannel_t ch;

	codeplugChannelGetDataWithOffsetAndLengthForIndex(channelIndex, &ch, (uint8_t)offsetof(CodeplugChannel_t, contact), (int)sizeof(ch.contact));
	return ch.contact;
}

int codeplugContactCountChannels(int contactIndex)
{
	int n = 0;

	if ((contactIndex < CODEPLUG_CONTACTS_MIN) || (contactIndex > CODEPLUG_CONTACTS_MAX))
	{
		return 0;
	}

	for (int ch = CODEPLUG_CHDEL_CHANNELS_MIN; ch <= CODEPLUG_CHDEL_CHANNELS_MAX; ch++)
	{
		if (codeplugAllChannelsIndexIsInUse(ch) && (codeplugChannelContactField(ch) == (uint16_t)contactIndex))
		{
			n++;
		}
	}
	return n;
}

/* Пише «Немає» (0) лише в 2 байти поля «контакт» -- решту запису каналу не чіпаємо (як і R41/R43, що пишуть мінімум). 1 -> 0 лише знімає біти. */
static bool codeplugChannelClearContactField(int channelIndex)
{
	bool inFlash;
	uint8_t zero[2] = { 0, 0 };
	int addr = codeplugChanRecordAddr(channelIndex, CODEPLUG_ADDR_CHANNEL_EEPROM, CODEPLUG_ADDR_CHANNEL_FLASH, &inFlash);

	if (addr < 0)
	{
		return false;
	}
	addr += (int)offsetof(CodeplugChannel_t, contact);
	return inFlash ? SPI_Flash_write(FLASH_ADDRESS_OFFSET + addr, zero, 2) : EEPROM_Write(addr, zero, 2);
}

/*
 * Видалення контакту. ПОРЯДОК -- за стійкістю до обриву живлення:
 *   1. канали, що посилаються на контакт, -> «Немає» (контакт ще живий: обрив лишає частину каналів без контакту, нічого зламаного);
 *   2. стирання слота контакту (так само, як стокове: ім'я 0xFF, TG 0, тип 0xFF) і виймання з кешу.
 * Без кроку 1 канал читав би зі стертого слота ім'я 0xFF, TG 0 і тип 0xFF -- тобто «сміття», а не контакт.
 */
bool codeplugContactDelete(int contactIndex)
{
	CodeplugContact_t c;

	if ((contactIndex < CODEPLUG_CONTACTS_MIN) || (contactIndex > CODEPLUG_CONTACTS_MAX) || !codeplugContactGetDataForIndex(contactIndex, &c))
	{
		return false;
	}

	for (int ch = CODEPLUG_CHDEL_CHANNELS_MIN; ch <= CODEPLUG_CHDEL_CHANNELS_MAX; ch++)
	{
		if (codeplugAllChannelsIndexIsInUse(ch) && (codeplugChannelContactField(ch) == (uint16_t)contactIndex) && !codeplugChannelClearContactField(ch))
		{
			return false;
		}
	}

	memset(c.name, 0xff, 16);
	c.tgNumber = 0;
	c.callType = 0xff;
	return codeplugContactSaveDataForIndex(contactIndex, &c) != 0;
}
#if defined(RXGROUP_EDIT_ENABLED)
/* ---- R65B: редактор списків прийому ----------------------------------------------------------------------------------------------
 * Нової статичної пам'яті НЕМАЄ (кеш довжин codeplugRXGroupCache існував). Записи списків лежать так, що жоден НЕ перетинає межу 4 КБ сектора: запис №30 (з нуля) починається
 * рівно з межі сектора, а CODEPLUG_RXGROUP_DATA_STRUCT_SIZE * 30 = 2400 = 0x960, тобто 0x8D6A0 + 0x960 = 0x8E000. Таблиця довжин (0x8D620..0x8D66B) лежить у тому самому секторі,
 * що й записи 0..29. Тож кожен виклик SPI_Flash_write тут -- ОДИН прохід «прочитати сектор -> стерти -> записати» (а для запису, що закінчується рівно на межі, SPI_Flash_write
 * робить ще й даремний другий прохід тим самим вмістом). Жоден запис не захищений від зникнення живлення: сектор стирається і пишеться заново. */

static int codeplugRxGroupBodyAddr(int slot)
{
	return FLASH_ADDRESS_OFFSET + CODEPLUG_ADDR_RX_GROUP + ((slot - 1) * CODEPLUG_RXGROUP_DATA_STRUCT_SIZE);
}

static bool codeplugRxGroupSlotOk(int slot)
{
	return (slot >= 1) && (slot <= CODEPLUG_RX_GROUPLIST_MAX);
}

bool codeplugRxGroupExists(int slot)
{
	return codeplugRxGroupSlotOk(slot) && (codeplugRXGroupCache[slot - 1] > 0);
}

int codeplugRxGroupCount(void)
{
	int n = 0;

	for (int i = 0; i < CODEPLUG_RX_GROUPLIST_MAX; i++)
	{
		if (codeplugRXGroupCache[i] > 0)
		{
			n++;
		}
	}
	return n;
}

int codeplugRxGroupNthSlot(int ordinal)
{
	for (int i = 0; i < CODEPLUG_RX_GROUPLIST_MAX; i++)
	{
		if (codeplugRXGroupCache[i] > 0)
		{
			if (ordinal == 0)
			{
				return i + 1;
			}
			ordinal--;
		}
	}
	return 0;
}

void codeplugRxGroupGetName(int slot, char *out17)
{
	char raw[CODEPLUG_RXGROUP_NAME_LEN];

	out17[0] = 0;
	if (!codeplugRxGroupExists(slot))
	{
		return;
	}
	SPI_Flash_read((uint32_t)codeplugRxGroupBodyAddr(slot), (uint8_t *)raw, CODEPLUG_RXGROUP_NAME_LEN);
	codeplugUtilConvertBufToDisplayString(raw, out17, CODEPLUG_RXGROUP_NAME_LEN);   /* назву з CPS в UTF-8 показуємо й редагуємо в cp1251, як назви зон */
}

int codeplugRxGroupGetMembers(int slot, uint16_t *out32)
{
	int n = 0;

	memset(out32, 0, CODEPLUG_RXGROUP_MEMBERS_MAX * sizeof(uint16_t));
	if (!codeplugRxGroupExists(slot))
	{
		return 0;
	}
	SPI_Flash_read((uint32_t)(codeplugRxGroupBodyAddr(slot) + CODEPLUG_RXGROUP_NAME_LEN), (uint8_t *)out32, CODEPLUG_RXGROUP_MEMBERS_MAX * (int)sizeof(uint16_t));
	while ((n < CODEPLUG_RXGROUP_MEMBERS_MAX) && (out32[n] != 0))
	{
		n++;
	}
	return n;
}

/* Назва -> 16 байтів запису. Правила ті самі, що в зон (R42) і CPS: порожня -- відмова; рівно 16 байтів з кінцевим 0xFF («я») -- відмова (хвоста 0x00 нема де поставити). */
static CodeplugRxGroupResult_t codeplugRxGroupNameToBuf(const char *name, char *buf16)
{
	int n = 0;
	bool blank = true;

	while ((n <= CODEPLUG_RXGROUP_NAME_LEN) && (name[n] != 0))
	{
		if (name[n] != ' ')
		{
			blank = false;
		}
		n++;
	}
	if ((n == 0) || blank)
	{
		return CODEPLUG_RXGROUP_NAME_EMPTY;
	}
	if (n > CODEPLUG_RXGROUP_NAME_LEN)
	{
		return CODEPLUG_RXGROUP_BAD_ARG;
	}
	if ((n == CODEPLUG_RXGROUP_NAME_LEN) && (((uint8_t)name[CODEPLUG_RXGROUP_NAME_LEN - 1]) == 0xFF))
	{
		return CODEPLUG_RXGROUP_NAME_TAIL;
	}
	codeplugUtilConvertStringToBuf((char *)name, buf16, CODEPLUG_RXGROUP_NAME_LEN);
	return CODEPLUG_RXGROUP_OK;
}

CodeplugRxGroupResult_t codeplugRxGroupNameCheck(const char *name, int exceptSlot)
{
	char buf[CODEPLUG_RXGROUP_NAME_LEN];
	char other[CODEPLUG_RXGROUP_NAME_LEN + 1];
	CodeplugRxGroupResult_t r = codeplugRxGroupNameToBuf(name, buf);

	if (r != CODEPLUG_RXGROUP_OK)
	{
		return r;
	}
	for (int slot = 1; slot <= CODEPLUG_RX_GROUPLIST_MAX; slot++)
	{
		if ((slot != exceptSlot) && codeplugRxGroupExists(slot))
		{
			codeplugRxGroupGetName(slot, other);
			if (strcmp(other, name) == 0)
			{
				return CODEPLUG_RXGROUP_NAME_DUP;
			}
		}
	}
	return CODEPLUG_RXGROUP_OK;
}

/* склад: 1..32 різних номерів контактів 1..1024 */
static CodeplugRxGroupResult_t codeplugRxGroupMembersCheck(const uint16_t *members, int n)
{
	if ((n < 1) || (n > CODEPLUG_RXGROUP_MEMBERS_MAX))
	{
		return CODEPLUG_RXGROUP_BAD_ARG;
	}
	for (int i = 0; i < n; i++)
	{
		if ((members[i] < CODEPLUG_CONTACTS_MIN) || (members[i] > CODEPLUG_CONTACTS_MAX))
		{
			return CODEPLUG_RXGROUP_BAD_ARG;
		}
		for (int j = 0; j < i; j++)
		{
			if (members[j] == members[i])
			{
				return CODEPLUG_RXGROUP_DUP_MEMBER;
			}
		}
	}
	return CODEPLUG_RXGROUP_OK;
}

/* Записати байт довжини слота і ПЕРЕЧИТАТИ кеш із флеша: кеш завжди = правда, навіть якщо запис не вдався (сектор міг бути стертий). */
static bool codeplugRxGroupWriteLen(int slot, uint8_t len)
{
	bool ok = SPI_Flash_write(FLASH_ADDRESS_OFFSET + CODEPLUG_ADDR_RX_GROUP_LEN + (slot - 1), &len, 1);

	codeplugRxGroupInitCache();
	return ok && (codeplugRXGroupCache[slot - 1] == len);
}

CodeplugRxGroupResult_t codeplugRxGroupCreate(const char *name, const uint16_t *members, int n, int *slotOut)
{
	uint8_t rec[CODEPLUG_RXGROUP_DATA_STRUCT_SIZE];
	CodeplugRxGroupResult_t r = codeplugRxGroupMembersCheck(members, n);
	int slot = 0;

	if (r != CODEPLUG_RXGROUP_OK)
	{
		return r;
	}
	r = codeplugRxGroupNameCheck(name, 0);
	if (r != CODEPLUG_RXGROUP_OK)
	{
		return r;
	}
	for (int i = 1; i <= CODEPLUG_RX_GROUPLIST_MAX; i++)
	{
		if (codeplugRXGroupCache[i - 1] == 0)
		{
			slot = i;
			break;
		}
	}
	if (slot == 0)
	{
		return CODEPLUG_RXGROUP_FULL;
	}

	memset(rec, 0, sizeof(rec));
	(void)codeplugRxGroupNameToBuf(name, (char *)rec);
	memcpy(&rec[CODEPLUG_RXGROUP_NAME_LEN], members, (size_t)n * sizeof(uint16_t));

	/* ПОРЯДОК: спершу тіло (слот ще «вільний» -- довжина 0), потім довжина: обрив між ними лишає вільний слот з сміттям у тілі, а не список без тіла. */
	if (!SPI_Flash_write(codeplugRxGroupBodyAddr(slot), rec, (int)sizeof(rec)))
	{
		return CODEPLUG_RXGROUP_WRITE_ERROR;
	}
	if (!codeplugRxGroupWriteLen(slot, (uint8_t)n))
	{
		return CODEPLUG_RXGROUP_WRITE_ERROR;
	}
	if (slotOut != NULL)
	{
		*slotOut = slot;
	}
	return CODEPLUG_RXGROUP_OK;
}

CodeplugRxGroupResult_t codeplugRxGroupRename(int slot, const char *name)
{
	char buf[CODEPLUG_RXGROUP_NAME_LEN];
	CodeplugRxGroupResult_t r;

	if (!codeplugRxGroupExists(slot))
	{
		return CODEPLUG_RXGROUP_BAD_ARG;
	}
	r = codeplugRxGroupNameCheck(name, slot);
	if (r != CODEPLUG_RXGROUP_OK)
	{
		return r;
	}
	(void)codeplugRxGroupNameToBuf(name, buf);
	return SPI_Flash_write(codeplugRxGroupBodyAddr(slot), (uint8_t *)buf, CODEPLUG_RXGROUP_NAME_LEN) ? CODEPLUG_RXGROUP_OK : CODEPLUG_RXGROUP_WRITE_ERROR;
}

CodeplugRxGroupResult_t codeplugRxGroupSetMembers(int slot, const uint16_t *members, int n)
{
	uint16_t buf[CODEPLUG_RXGROUP_MEMBERS_MAX];
	CodeplugRxGroupResult_t r;

	if (!codeplugRxGroupExists(slot))
	{
		return CODEPLUG_RXGROUP_BAD_ARG;
	}
	r = codeplugRxGroupMembersCheck(members, n);
	if (r != CODEPLUG_RXGROUP_OK)
	{
		return r;
	}
	memset(buf, 0, sizeof(buf));
	memcpy(buf, members, (size_t)n * sizeof(uint16_t));

	/* ПОРЯДОК: номери контактів, потім довжина (лише якщо змінилась). Обрив між ними: довжина лише вмикає/вимикає слот (>0), склад читається до першого нуля -- нічого не ламається. */
	if (!SPI_Flash_write(codeplugRxGroupBodyAddr(slot) + CODEPLUG_RXGROUP_NAME_LEN, (uint8_t *)buf, (int)sizeof(buf)))
	{
		return CODEPLUG_RXGROUP_WRITE_ERROR;
	}
	if ((codeplugRXGroupCache[slot - 1] != (uint8_t)n) && !codeplugRxGroupWriteLen(slot, (uint8_t)n))
	{
		return CODEPLUG_RXGROUP_WRITE_ERROR;
	}
	return CODEPLUG_RXGROUP_OK;
}

/* R66C: обмін двох СУСІДНІХ контактів у складі (dir -1 -- вгору, +1 -- вниз). ОДИН запис 4 байтів у межах запису 80 Б (запис не перетинає межу сектора, див. G1 у
 * test_codeplug_rxgroup.c) -> один прогін сектора. Довжина не змінюється, кеш довжин не чіпаємо. Обрив живлення: або старий порядок, або новий (4 байти -- одна
 * сторінка запису), дублів і втрат контакту нема. */
CodeplugRxGroupResult_t codeplugRxGroupMoveMember(int slot, int pos, int dir)
{
	uint16_t m[CODEPLUG_RXGROUP_MEMBERS_MAX];
	uint16_t pair[2];
	int n;
	int to = pos + dir;
	int lo;

	if (!codeplugRxGroupExists(slot) || ((dir != -1) && (dir != 1)))
	{
		return CODEPLUG_RXGROUP_BAD_ARG;
	}
	n = codeplugRxGroupGetMembers(slot, m);
	if ((pos < 0) || (pos >= n) || (to < 0) || (to >= n))
	{
		return CODEPLUG_RXGROUP_BAD_ARG;
	}
	lo = (pos < to) ? pos : to;
	pair[0] = m[lo + 1];
	pair[1] = m[lo];
	return SPI_Flash_write(codeplugRxGroupBodyAddr(slot) + CODEPLUG_RXGROUP_NAME_LEN + (lo * (int)sizeof(uint16_t)), (uint8_t *)pair, (int)sizeof(pair)) ? CODEPLUG_RXGROUP_OK : CODEPLUG_RXGROUP_WRITE_ERROR;
}

/* Поле «список прийому» каналу (1 байт; 0 -- «Немає»). */
static uint8_t codeplugChannelRxGroupField(int channelIndex)
{
	CodeplugChannel_t ch;

	codeplugChannelGetDataWithOffsetAndLengthForIndex(channelIndex, &ch, (uint8_t)offsetof(CodeplugChannel_t, rxGroupList), (int)sizeof(ch.rxGroupList));
	return ch.rxGroupList;
}

/* Пише 0 лише в цей один байт запису каналу (1 -> 0 лише знімає біти; решта запису не чіпається). */
static bool codeplugChannelClearRxGroupField(int channelIndex)
{
	bool inFlash;
	uint8_t zero = 0;
	int addr = codeplugChanRecordAddr(channelIndex, CODEPLUG_ADDR_CHANNEL_EEPROM, CODEPLUG_ADDR_CHANNEL_FLASH, &inFlash);

	if (addr < 0)
	{
		return false;
	}
	addr += (int)offsetof(CodeplugChannel_t, rxGroupList);
	return inFlash ? SPI_Flash_write(FLASH_ADDRESS_OFFSET + addr, &zero, 1) : EEPROM_Write(addr, &zero, 1);
}

int codeplugRxGroupCountChannels(int slot)
{
	int n = 0;

	if (!codeplugRxGroupSlotOk(slot))
	{
		return 0;
	}
	for (int ch = CODEPLUG_CHDEL_CHANNELS_MIN; ch <= CODEPLUG_CHDEL_CHANNELS_MAX; ch++)
	{
		if (codeplugAllChannelsIndexIsInUse(ch) && (codeplugChannelRxGroupField(ch) == (uint8_t)slot))
		{
			n++;
		}
	}
	return n;
}

/*
 * Видалення списку. ПОРЯДОК -- за стійкістю до обриву живлення (як R44 для контакту):
 *   1. канали, що посилаються на список, -> «Немає» (список ще живий: обрив лишає частину каналів без списку, нічого зламаного);
 *   2. обидва VFO у кодплазі (EEPROM) -> «Немає» (RAM-копії й кеші править екран);
 *   3. довжина = 0 (від цього моменту списку нема), кеш перечитано;
 *   4. тіло -> нулі (прибирання; слот уже вільний, тож обрив тут безпечний).
 * Кожен канал із флеш-банку -- окремий прохід «прочитати сектор -> стерти -> записати» (канали 1..128 -- EEPROM, дешево).
 */
CodeplugRxGroupResult_t codeplugRxGroupDelete(int slot)
{
	uint8_t zeros[CODEPLUG_RXGROUP_DATA_STRUCT_SIZE];

	if (!codeplugRxGroupExists(slot))
	{
		return CODEPLUG_RXGROUP_BAD_ARG;
	}

	for (int ch = CODEPLUG_CHDEL_CHANNELS_MIN; ch <= CODEPLUG_CHDEL_CHANNELS_MAX; ch++)
	{
		if (codeplugAllChannelsIndexIsInUse(ch) && (codeplugChannelRxGroupField(ch) == (uint8_t)slot) && !codeplugChannelClearRxGroupField(ch))
		{
			return CODEPLUG_RXGROUP_WRITE_ERROR;
		}
	}

	for (int v = 0; v < 2; v++)
	{
		uint8_t g = 0;
		int addr = CODEPLUG_ADDR_VFO_A_CHANNEL + (CODEPLUG_CHANNEL_DATA_STRUCT_SIZE * v) + (int)offsetof(CodeplugChannel_t, rxGroupList);

		if (EEPROM_Read(addr, &g, 1) && (g == (uint8_t)slot))
		{
			g = 0;
			if (!EEPROM_Write(addr, &g, 1))
			{
				return CODEPLUG_RXGROUP_WRITE_ERROR;
			}
		}
	}

	if (!codeplugRxGroupWriteLen(slot, 0))
	{
		return CODEPLUG_RXGROUP_WRITE_ERROR;
	}

	memset(zeros, 0, sizeof(zeros));
	return SPI_Flash_write(codeplugRxGroupBodyAddr(slot), zeros, (int)sizeof(zeros)) ? CODEPLUG_RXGROUP_OK : CODEPLUG_RXGROUP_WRITE_ERROR;
}
#endif /* RXGROUP_EDIT_ENABLED */
#endif /* CODEPLUG_MENU_ENABLED */

uint32_t codeplugGetUserDMRID(void)
{
	uint32_t dmrId;
	EEPROM_Read(CODEPLUG_ADDR_USER_DMRID, (uint8_t *)&dmrId, 4);
	return bcd2int(byteSwap32(dmrId));
}

void codeplugSetUserDMRID(uint32_t dmrId)
{
	dmrId = byteSwap32(int2bcd(dmrId));
	EEPROM_Write(CODEPLUG_ADDR_USER_DMRID, (uint8_t *)&dmrId, 4);
}

// Max length the user can enter is 8. Hence buf must be 16 chars to allow for the termination
void codeplugGetRadioName(char *buf)
{
	memset(buf, 0, 9);
	EEPROM_Read(CODEPLUG_ADDR_USER_CALLSIGN, (uint8_t *)buf, 8);
	codeplugUtilConvertBufToString(buf, buf, 8);
}

// Max length the user can enter is 16. Hence buf must be 17 chars to allow for the termination
void codeplugGetBootScreenData(char *line1, char *line2, uint8_t *displayType)
{
	memset(line1, 0, SCREEN_LINE_BUFFER_SIZE);
	memset(line2, 0, SCREEN_LINE_BUFFER_SIZE);

	EEPROM_Read(CODEPLUG_ADDR_BOOT_LINE1, (uint8_t *)line1, (SCREEN_LINE_BUFFER_SIZE - 1));
	codeplugUtilConvertBufToString(line1, line1, (SCREEN_LINE_BUFFER_SIZE - 1));
	EEPROM_Read(CODEPLUG_ADDR_BOOT_LINE2, (uint8_t *)line2, (SCREEN_LINE_BUFFER_SIZE - 1));
	codeplugUtilConvertBufToString(line2, line2, (SCREEN_LINE_BUFFER_SIZE - 1));

	EEPROM_Read(CODEPLUG_ADDR_BOOT_INTRO_SCREEN, displayType, 1);// read the display type
}

void codeplugGetVFO_ChannelData(CodeplugChannel_t *vfoBuf, Channel_t VFONumber)
{
	EEPROM_Read(CODEPLUG_ADDR_VFO_A_CHANNEL + (CODEPLUG_CHANNEL_DATA_STRUCT_SIZE * (int)VFONumber), (uint8_t *)vfoBuf, CODEPLUG_CHANNEL_DATA_STRUCT_SIZE);

	// Convert the the legacy codeplug tx and rx freq values into normal integers
	vfoBuf->chMode = (vfoBuf->chMode == 0) ? RADIO_MODE_ANALOG : RADIO_MODE_DIGITAL;
	vfoBuf->txFreq = bcd2int(vfoBuf->txFreq);
	vfoBuf->rxFreq = bcd2int(vfoBuf->rxFreq);
	vfoBuf->txTone = codeplugCSSToInt(vfoBuf->txTone);
	vfoBuf->rxTone = codeplugCSSToInt(vfoBuf->rxTone);
	vfoBuf->NOT_IN_CODEPLUG_flag = ((VFONumber == CHANNEL_VFO_A) ? 0x01 : ((VFONumber == CHANNEL_VFO_B) ? 0x03 : 0x00));
	vfoBuf->NOT_IN_CODEPLUG_CALCULATED_DISTANCE_X10 = -1;

	if (vfoBuf->sql > 21U)
	{
		vfoBuf->sql = 10U;
	}
}

void codeplugSetVFO_ChannelData(CodeplugChannel_t *vfoBuf, Channel_t VFONumber)
{
	CodeplugChannel_t tmpChannel;

	memcpy(&tmpChannel, vfoBuf, CODEPLUG_CHANNEL_DATA_STRUCT_SIZE);// save current VFO data as we need to modify

	codeplugConvertChannelInternalToCodeplug(&tmpChannel, vfoBuf);

	EEPROM_Write(CODEPLUG_ADDR_VFO_A_CHANNEL + (CODEPLUG_CHANNEL_DATA_STRUCT_SIZE * (int)VFONumber), (uint8_t *)&tmpChannel, CODEPLUG_CHANNEL_DATA_STRUCT_SIZE);
}

void codeplugConvertChannelInternalToCodeplug(CodeplugChannel_t *codeplugChannel, CodeplugChannel_t *internalChannel)
{
	codeplugChannel->chMode = (internalChannel->chMode == RADIO_MODE_ANALOG) ? 0 : 1;
	codeplugChannel->txFreq = int2bcd(internalChannel->txFreq);
	codeplugChannel->rxFreq = int2bcd(internalChannel->rxFreq);
	codeplugChannel->txTone = codeplugIntToCSS(internalChannel->txTone);
	codeplugChannel->rxTone = codeplugIntToCSS(internalChannel->rxTone);
}

void codeplugInitChannelsPerZone(void)
{
	uint8_t buf[16];
	// 0x806F is the last byte of the name of the second Zone if 16 channels per zone
	// And because the CPS terminates the zone name with 0xFF, this will be 0xFF if its a 16 channel per zone schema
	// If the zone has 80 channels per zone this address will be the upper byte of the channel number and because the max channels is 1024
	// this value can never me 0xff if its a channel number

	// Note. I tried to read just 1 byte but it crashed. So I am now reading 16 bytes and checking the last one
	EEPROM_Read(0x8060, (uint8_t *)buf, 16);
	if ((buf[15] >= 0x00) && (buf[15] <= 0x04))
	{
		codeplugChannelsPerZone = 80;// Must be the new 80 channel per zone format
	}
}

static uint32_t codeplugGetOpenGD77CustomDataStartAddressForType(CodeplugCustomDataType_t dataType, codeplugCustomDataBlockHeader_t *blockHeader)
{
	const uint32_t MAX_BLOCK_ADDRESS = 0x10000;
	uint32_t dataHeaderAddress = 12;
	uint8_t tmpBuf[12];

	SPI_Flash_read(FLASH_ADDRESS_OFFSET + 0, tmpBuf, 12);

	if (memcmp("OpenGD77", tmpBuf, 8) == 0)
	{
		do
		{
			SPI_Flash_read(FLASH_ADDRESS_OFFSET + dataHeaderAddress, (uint8_t *)blockHeader, sizeof(codeplugCustomDataBlockHeader_t));

			if (blockHeader->dataType == dataType)
			{
				return dataHeaderAddress;
			}

			if ((blockHeader->dataLength == 0) || (blockHeader->dataLength == 0xFFFFFFFF))
			{
				return 0;
			}

			dataHeaderAddress += sizeof(codeplugCustomDataBlockHeader_t) + blockHeader->dataLength;

		} while (dataHeaderAddress < MAX_BLOCK_ADDRESS);
	}

	return 0;
}

static uint32_t codeplugGetOpenGD77CustomDataFirstEmptySlot(int len)
{
	const uint32_t MAX_BLOCK_ADDRESS = 0x10000;
	codeplugCustomDataBlockHeader_t blockHeader;
	uint32_t dataHeaderAddress;

	if ((dataHeaderAddress = codeplugGetOpenGD77CustomDataStartAddressForType(CODEPLUG_CUSTOM_DATA_TYPE_EMPTY, &blockHeader)) > 0)
	{
		if ((blockHeader.dataLength == 0xFFFFFFFF) &&
				((dataHeaderAddress + sizeof(codeplugCustomDataBlockHeader_t) + len) < MAX_BLOCK_ADDRESS))
		{
			return dataHeaderAddress;
		}
	}

	return 0;
}

// ЄДИНИЙ спосіб прочитати кастомний блок кодплага. Необмежений
// codeplugGetOpenGD77CustomData() прибрано (2026-09-04): він копіював стільки байт, скільки
// казав заголовок блока у ФЛЕШІ, тож кодплаг із чужим або пошкодженим блоком наказував
// прочитати більше, ніж вміщає буфер виклику. Найвразливіші були буфери НА СТЕКУ --
// melodyBuf (512 Б, читається на КОЖНОМУ ввімкненні), themingTmp (64 Б, теж на старті),
// TLE супутників (2520 Б) -- і сховище повідомлень у секції CCM, поруч з яким лежать
// AES-ключі. Ніколи не копіює більше за maxLen байт у dataBuf.
bool codeplugGetOpenGD77CustomDataBounded(CodeplugCustomDataType_t dataType, uint8_t *dataBuf, int maxLen)
{
	codeplugCustomDataBlockHeader_t blockHeader;
	uint32_t dataHeaderAddress;

	if ((maxLen > 0) && ((dataHeaderAddress = codeplugGetOpenGD77CustomDataStartAddressForType(dataType, &blockHeader)) > 0))
	{
		uint32_t len = blockHeader.dataLength;
		if (len > (uint32_t)maxLen) { len = (uint32_t)maxLen; }   // clamp to the caller's buffer

		SPI_Flash_read(FLASH_ADDRESS_OFFSET + dataHeaderAddress + sizeof(codeplugCustomDataBlockHeader_t), dataBuf, len);
		return true;
	}

	return false;
}

bool codeplugSetOpenGD77CustomData(CodeplugCustomDataType_t dataType, uint8_t *dataBuf, int len)
{
	codeplugCustomDataBlockHeader_t blockHeader;
	uint32_t dataHeaderAddress;

	if ((dataHeaderAddress = codeplugGetOpenGD77CustomDataStartAddressForType(dataType, &blockHeader)) == 0)
	{
		if ((dataHeaderAddress = codeplugGetOpenGD77CustomDataFirstEmptySlot(len)) == 0)
		{
			return false;
		}

		// We got a location for this new storage, validate the header.
		blockHeader.dataType = dataType;
		blockHeader.dataLength = len;
	}

	if (blockHeader.dataLength == len) // it's not permitted to change the block size, it has to be equal.
	{
		SPI_Flash_write(FLASH_ADDRESS_OFFSET + dataHeaderAddress, (uint8_t *)&blockHeader, sizeof(codeplugCustomDataBlockHeader_t));
		SPI_Flash_write(FLASH_ADDRESS_OFFSET + dataHeaderAddress + sizeof(codeplugCustomDataBlockHeader_t), dataBuf, len);
		return true;
	}

	return false;
}

bool codeplugGetGeneralSettings(CodeplugGeneralSettings_t *generalSettingsBuffer)
{
	return EEPROM_Read(CODEPLUG_ADDR_GENERAL_SETTINGS, (uint8_t *)generalSettingsBuffer, CODEPLUG_GENERAL_SETTINGS_DATA_STRUCT_SIZE);
}

bool codeplugGetSignallingDTMF(CodeplugSignallingDTMF_t *signallingDTMFBuffer)
{
	return EEPROM_Read(CODEPLUG_ADDR_SIGNALLING_DTMF, (uint8_t *)signallingDTMFBuffer, CODEPLUG_SIGNALLING_DTMF_DATA_STRUCT_SIZE);
}

bool codeplugGetSignallingDTMFDurations(CodeplugSignallingDTMFDurations_t *signallingDTMFDurationsBuffer)
{
	if (EEPROM_Read(CODEPLUG_ADDR_SIGNALLING_DTMF_DURATIONS, (uint8_t *)signallingDTMFDurationsBuffer, SIGNALLING_DTMF_DURATIONS_DATA_STRUCT_SIZE))
	{
		// Default codeplug value was 128(0x80). Override any value above 1000ms
		if (signallingDTMFDurationsBuffer->libreDMR_Tail > 10)
		{
			signallingDTMFDurationsBuffer->libreDMR_Tail = 5;
		}

		return true;
	}
	else
	{
		// Avoid division-by-zero
		signallingDTMFDurationsBuffer->rate = 2; // 250ms/250ms
	}

	return false;
}


bool codeplugGetDeviceInfo(CodeplugDeviceInfo_t *deviceInfoBuffer)
{
	bool readOK = EEPROM_Read(CODEPLUG_ADDR_DEVICE_INFO, (uint8_t *)deviceInfoBuffer, sizeof(CodeplugDeviceInfo_t));//CODEPLUG_ADDR_DEVICE_INFO_READ_SIZE);
	if (readOK)
	{
		deviceInfoBuffer->minUHFFreq = bcd2uint16(deviceInfoBuffer->minUHFFreq);
		deviceInfoBuffer->maxUHFFreq = bcd2uint16(deviceInfoBuffer->maxUHFFreq);

		deviceInfoBuffer->minVHFFreq = bcd2uint16(deviceInfoBuffer->minVHFFreq);
		deviceInfoBuffer->maxVHFFreq = bcd2uint16(deviceInfoBuffer->maxVHFFreq);

		return true;
	}
	return false;
}

static void codeplugQuickKeyInitCache(void)
{
	EEPROM_Read(CODEPLUG_ADDR_QUICKKEYS, (uint8_t *)&quickKeysCache, (CODEPLUG_QUICKKEYS_SIZE * sizeof(uint16_t)));
}

uint16_t codeplugGetQuickkeyFunctionID(char key)
{
	uint16_t functionId = 0;

	if ((key >= '0') && (key <= '9'))
	{
		key = key - '0';
		functionId = quickKeysCache[(int) key];
	}

	return functionId;
}

static bool quickkeyIsEmpty(char key, uint16_t functionId)
{
	// Wants to clear a slot, so consider it empty
	if (functionId == 0x8000)
	{
		return true;
	}

	uint16_t data = codeplugGetQuickkeyFunctionID(key);

	if ((data == 0x8000) || QUICKKEY_SLOT_UNWRITTEN(data) ||   // R96/А5: 0xFFFF -- незаписаний слот EEPROM, вважаємо порожнім
			(((data & 0x8000) == 0) && ((data < CODEPLUG_CONTACTS_MIN) || (data > CODEPLUG_CONTACTS_MAX))))
	{
		return true;
	}

	return false;
}

bool codeplugSetQuickkeyFunctionID(char key, uint16_t functionId)
{
	// Only permit to store QuickKey in empty slots
	if (quickkeyIsEmpty(key, functionId) && (key >= '0' && key <= '9'))
	{
		key = key - '0';
		EEPROM_Write(CODEPLUG_ADDR_QUICKKEYS + (sizeof(uint16_t) * (int)key), (uint8_t *)&functionId, sizeof(uint16_t));
		quickKeysCache[(int) key] = functionId;

		return true;
	}

	return false;
}

int codeplugGetRepeaterWakeAttempts(void)
{
	return 4;// Hard coded. In the future we may read this from the codeplug.
}

static void codeplugAPRSInitCache(void)
{
	CodeplugAPRSConfig_t aprsBuff;
	int aprsIdx = 1;

	do
	{
		memset(&aprsBuff, 0x00, CODEPLUG_APRS_CONFIG_DATA_STRUCT_SIZE);

		codeplugAPRSCache.numOfConfigs = aprsIdx; // Cheating the read function

		if (codeplugAPRSGetDataForIndex(aprsIdx, &aprsBuff) == false)
		{
			break;
		}

		aprsIdx++;
		codeplugAPRSCache.numOfConfigs++;

	} while(aprsIdx <= 8);

	codeplugAPRSCache.numOfConfigs = (aprsIdx - 1);
}

void codeplugInitCaches(void)
{
	codeplugInitContactsCache();

	codeplugAllChannelsInitCache();

	codeplugZonesInitCache();
	codeplugRxGroupInitCache();
	codeplugQuickKeyInitCache();

	codeplugInitLastUsedChannelInZone();

	codeplugAPRSInitCache();
}

// Returns pin length or 0 if no pin. Pin code is passed as pointer to int32_t
int codeplugGetPasswordPin(int32_t *pinCode)
{
	int pinLength = 0;
	uint8_t buf[6];

	if (EEPROM_Read(CODEPLUG_ADDR_BOOT_PASSWORD_PIN + 1, (uint8_t *)buf, 6))
	{
		if ((buf[0] & 0x01) == 0)
		{
			return pinLength;
		}

		uint8_t nibble;
		*pinCode = 0;
		for(int i = 0 ; i < 6 ; i++)
		{
			nibble = buf[(i/2)+3] >> ((1-(i % 2)) * 4) & 0x0F;
			if (nibble != 0x0f)
			{
				*pinCode = (*pinCode * 10) + nibble;
				pinLength++;
			}
			else
			{
				break;
			}
		}
	}
	return pinLength;
}

void codeplugSetTATxForTS(CodeplugChannel_t *channelBuf, uint8_t ts, CodeplugTATxDestination_t taTx)
{
	bool isTS1 = (ts == 0);
	channelBuf->flag1 &= (isTS1 ? 0xFC : 0xF3);
	channelBuf->flag1 |= (taTx << (isTS1 ? 0 : 2));
}

CodeplugTATxDestination_t codeplugGetTATxForTS(CodeplugChannel_t *channelBuf, uint8_t ts)
{
	return (channelBuf->flag1 >> ((ts == 0) ? 0 : 2)) & 0x03;
}

void codeplugInitLastUsedChannelInZone(void)
{
#if ! defined(PLATFORM_RD5R)
	uint8_t tmpBuf[4];

	EEPROM_Read(CODEPLUG_ADDR_LUCZ, tmpBuf, 4);

	if (memcmp("LUCZ", tmpBuf, 4) == 0) // Check for the header tag
	{
		EEPROM_Read((CODEPLUG_ADDR_LUCZ + 4), (uint8_t *)&lastUsedChannelInZoneData, sizeof(lastUsedChannelInZoneData));
	}
	else
#endif
	{
		// There is no CustomData available, set all last channels to 0
		memset(&lastUsedChannelInZoneData, 0, sizeof(lastUsedChannelInZoneData));

#if defined(PLATFORM_RD5R)
		codeplugSetLastUsedChannelInZone(-1, nonVolatileSettings.currentChannelIndexInAllZone);
		codeplugSetLastUsedChannelInZone(nonVolatileSettings.currentZone, nonVolatileSettings.currentChannelIndexInZone);
#endif
	}
}

int16_t codeplugGetLastUsedChannelInZone(int zoneNum)
{
	int offset = SAFE_MIN(zoneNum, (CODEPLUG_ALL_ZONES_MAX - 1));
	uint8_t *p = (uint8_t *)&lastUsedChannelInZoneData[offset];

	return ((zoneNum >= 0) ? ((int16_t)*p) : (*((int16_t *)p) + 1));
}

int16_t codeplugGetLastUsedChannelInCurrentZone(void)
{
	return (codeplugGetLastUsedChannelInZone(currentZone.NOT_IN_CODEPLUGDATA_indexNumber));
}

int16_t codeplugGetLastUsedChannelNumberInCurrentZone(void)
{
	int16_t index = codeplugGetLastUsedChannelInZone(currentZone.NOT_IN_CODEPLUGDATA_indexNumber);

	return ((currentZone.NOT_IN_CODEPLUGDATA_indexNumber >= 0) ? currentZone.channels[index] : index);
}

int16_t codeplugSetLastUsedChannelInZone(int zoneNum, int16_t channelNum)
{
	int offset = SAFE_MIN(zoneNum, (CODEPLUG_ALL_ZONES_MAX - 1));
	uint8_t *p = (uint8_t *)&lastUsedChannelInZoneData[offset];

	if (zoneNum >= 0) // Channels 0..79
	{
		*p = (uint8_t)channelNum;
#if defined(PLATFORM_RD5R)
		settingsSet(nonVolatileSettings.currentChannelIndexInZone, (int16_t) channelNum);
#endif
	}
	else // AllChannels (channels 1..1024)
	{
		*((int16_t *)p) = (channelNum - 1);
#if defined(PLATFORM_RD5R)
		settingsSet(nonVolatileSettings.currentChannelIndexInAllZone, (int16_t) channelNum);
#endif
	}

	lastUsedChannelInZoneHasChanged = true;

	return channelNum;
}

int16_t codeplugSetLastUsedChannelInCurrentZone(int16_t channelNum)
{
	return (codeplugSetLastUsedChannelInZone(currentZone.NOT_IN_CODEPLUGDATA_indexNumber, channelNum));
}

bool codeplugSaveLastUsedChannelInZone(void)
{
#if ! defined(PLATFORM_RD5R)
	if (lastUsedChannelInZoneHasChanged)
	{
		uint8_t header[4] = { 'L', 'U', 'C', 'Z' };

		lastUsedChannelInZoneHasChanged = ! (EEPROM_Write(CODEPLUG_ADDR_LUCZ, (uint8_t *)&header, 4) &&
				EEPROM_Write(CODEPLUG_ADDR_LUCZ + 4,
						(uint8_t *)&lastUsedChannelInZoneData, sizeof(lastUsedChannelInZoneData)));

		return !lastUsedChannelInZoneHasChanged;
	}
#endif

	return true;
}

int codeplugAPRSConfigGetCount(void)
{
	return codeplugAPRSCache.numOfConfigs;
}

bool codeplugAPRSGetDataForIndex(int index, CodeplugAPRSConfig_t *APRS_Buf)
{
	if ((index > 0) && (index <= codeplugAPRSCache.numOfConfigs))
	{
		index--;
		EEPROM_Read(CODEPLUG_ADDR_APRS_CONFIGS + (index * CODEPLUG_APRS_CONFIG_DATA_STRUCT_SIZE), (uint8_t *)APRS_Buf, CODEPLUG_APRS_CONFIG_DATA_STRUCT_SIZE);
	}
	else
	{
		memset(APRS_Buf, 0x00, CODEPLUG_APRS_CONFIG_DATA_STRUCT_SIZE);
	}

	if (APRS_Buf->magicVer == 0x4152) // Ambiguity move left by 1 bit
	{
		APRS_Buf->flags = (((APRS_Buf->flags & 0xF0) << 1) | (APRS_Buf->flags & 0x0F));
		APRS_Buf->magicVer = APRS_MAGIC_VERSION;
	}

	return !((APRS_Buf->name[0] == 0xFF) || (APRS_Buf->magicVer != APRS_MAGIC_VERSION));
}

#if defined(ENABLE_APRS_RX)
bool codeplugAPRSSetDataForIndex(int index, const CodeplugAPRSConfig_t *APRS_Buf, bool *changed)
{
	CodeplugAPRSConfig_t out;
	uint8_t cur[CODEPLUG_APRS_CONFIG_DATA_STRUCT_SIZE];
	int addr;

	if (changed != NULL)
	{
		*changed = false;
	}
	if ((index < 1) || (index > 8) || (index > (codeplugAPRSCache.numOfConfigs + 1)))
	{
		return false;
	}
	memcpy(&out, APRS_Buf, sizeof(out));
	if (out.magicVer == 0U)
	{
		out.magicVer = APRS_MAGIC_VERSION;
	}
	if (out.name[0] == (char)0xFF)
	{
		return false;   // порожня назва = слот недійсний для codeplugAPRSGetDataForIndex()
	}
	addr = CODEPLUG_ADDR_APRS_CONFIGS + ((index - 1) * CODEPLUG_APRS_CONFIG_DATA_STRUCT_SIZE);
	if (EEPROM_Read(addr, cur, sizeof(cur)) && (memcmp(cur, &out, sizeof(cur)) == 0))
	{
		return true;
	}
	if (EEPROM_Write(addr, (uint8_t *)&out, sizeof(out)) == false)
	{
		return false;
	}
	if (changed != NULL)
	{
		*changed = true;
	}
	if (index > codeplugAPRSCache.numOfConfigs)
	{
		codeplugAPRSCache.numOfConfigs = index;
	}
	return true;
}

bool codeplugSetRadioName(const char *name, bool *changed)
{
	char buf[8];
	char cur[8];

	if (changed != NULL)
	{
		*changed = false;
	}
	codeplugUtilConvertStringToBuf((char *)name, buf, 8);   // 0xFF-дописка; name -- NUL-кінцевий, до 8 символів
	if (EEPROM_Read(CODEPLUG_ADDR_USER_CALLSIGN, (uint8_t *)cur, 8) && (memcmp(cur, buf, 8) == 0))
	{
		return true;
	}
	if (EEPROM_Write(CODEPLUG_ADDR_USER_CALLSIGN, (uint8_t *)buf, 8) == false)
	{
		return false;
	}
	if (changed != NULL)
	{
		*changed = true;
	}
	return true;
}
#endif

int codeplugAPRSGetIndexOfName(char *configName)
{
	uint8_t APRSConfigName[8];
	char convertedConfigName[8];

	codeplugUtilConvertStringToBuf(configName, convertedConfigName, 8);

	for(int i = 0; i < codeplugAPRSCache.numOfConfigs; i++)
	{
		if (!EEPROM_Read(CODEPLUG_ADDR_APRS_CONFIGS + (i * CODEPLUG_APRS_CONFIG_DATA_STRUCT_SIZE), (uint8_t *) &APRSConfigName, sizeof(APRSConfigName)))
		{
			return 0;
		}

		if (memcmp(APRSConfigName, convertedConfigName, 8) == 0)
		{
			return (i + 1);
		}
	}

	return 0;
}
