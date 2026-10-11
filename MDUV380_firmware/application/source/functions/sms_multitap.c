/*
 * sms_multitap.c -- розкладки й логіка multitap для набору SMS (ui4). Опис -- у sms_multitap.h.
 *
 * Кирилиця -- ЛИШЕ шістнадцятковими байтами cp1251 (.c-файли в UTF-8; кириличний літерал
 * дав би по два байти на літеру і сміття на екрані). Сусідні рядкові літерали розділено
 * ("\xA5" "2"), бо \x жадібний: "\xA52" -- це один (неприпустимий) байт, а не Ґ і '2'.
 */
#include "functions/sms_multitap.h"

#if (defined(ENABLE_AES) && defined(ENABLE_DMR_DATA)) || defined(APRS_RX)

#include <stddef.h>

/* '*' у всіх режимах: спершу пробіл, далі спецсимволи, яких немає на '1'. */
/* ui8: «№» (cp1251 0xB9) прибрано: на клавіатурі рації його немає, а у font_6x8 гліф порожній --
 * у шпаргалці й підказці виходило порожнє місце. Тепер набір однаковий для всіх збірок. */
#define MT_STAR  " *+-/=:;()\"'@#%&_<>~$"

/* Клавіші: '0'..'9' -> 0..9, '*' -> 10. */
#define MT_KEYS  11

#if defined(LANGUAGE_BUILD_UKRAINIAN)
/* Українська розкладка (ui4): 2 АБВГҐ, 3 ДЕЄЖЗ, 4 ИІЇЙ, 5 КЛМН, 6 ОПРС, 7 ТУФХ, 8 ЦЧШЩ,
 * 9 ЬЮЯ', 0 пробіл/0, 1 . , ? ! - 1. Цифра клавіші -- останньою в кожному циклі. */
static const char * const s_mapUaUp[MT_KEYS] =
{
	" 0",
	".,?!-1",
	"\xC0\xC1\xC2\xC3\xA5" "2",   /* А Б В Г Ґ */
	"\xC4\xC5\xAA\xC6\xC7" "3",   /* Д Е Є Ж З */
	"\xC8\xB2\xAF\xC9" "4",       /* И І Ї Й */
	"\xCA\xCB\xCC\xCD" "5",       /* К Л М Н */
	"\xCE\xCF\xD0\xD1" "6",       /* О П Р С */
	"\xD2\xD3\xD4\xD5" "7",       /* Т У Ф Х */
	"\xD6\xD7\xD8\xD9" "8",       /* Ц Ч Ш Щ */
	"\xDC\xDE\xDF" "'9",          /* Ь Ю Я ' */
	MT_STAR
};
static const char * const s_mapUaLo[MT_KEYS] =
{
	" 0",
	".,?!-1",
	"\xE0\xE1\xE2\xE3\xB4" "2",   /* а б в г ґ */
	"\xE4\xE5\xBA\xE6\xE7" "3",   /* д е є ж з */
	"\xE8\xB3\xBF\xE9" "4",       /* и і ї й */
	"\xEA\xEB\xEC\xED" "5",       /* к л м н */
	"\xEE\xEF\xF0\xF1" "6",       /* о п р с */
	"\xF2\xF3\xF4\xF5" "7",       /* т у ф х */
	"\xF6\xF7\xF8\xF9" "8",       /* ц ч ш щ */
	"\xFC\xFE\xFF" "'9",          /* ь ю я ' */
	MT_STAR
};
#endif

/* Латиниця -- літери як у стоковому OpenGD77 (keyboard.c, keypadAlphaMap), але регістр --
 * окремим режимом, а не другою половиною циклу. '1' -- стоковий набір розділових знаків. */
static const char * const s_mapLatUp[MT_KEYS] =
{
	" 0",
	".!,@-:?()~/[]#<>=*+$%'`&|_^{}1",
	"ABC2", "DEF3", "GHI4", "JKL5", "MNO6", "PQRS7", "TUV8", "WXYZ9",
	MT_STAR
};
static const char * const s_mapLatLo[MT_KEYS] =
{
	" 0",
	".!,@-:?()~/[]#<>=*+$%'`&|_^{}1",
	"abc2", "def3", "ghi4", "jkl5", "mno6", "pqrs7", "tuv8", "wxyz9",
	MT_STAR
};
/* «123»: одна цифра на клавішу -- підтверджується одразу, без очікування. */
static const char * const s_mapNum[MT_KEYS] =
{
	"0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
	MT_STAR
};

static const char * const * const s_maps[SMS_MT_MODES] =
{
#if defined(LANGUAGE_BUILD_UKRAINIAN)
	s_mapUaUp, s_mapUaLo,
#endif
	s_mapLatUp, s_mapLatLo, s_mapNum
};

static const char * const s_labels[SMS_MT_MODES] =
{
#if defined(LANGUAGE_BUILD_UKRAINIAN)
	"\xC0\xC1\xC2",   /* АБВ */
	"\xE0\xE1\xE2",   /* абв */
#endif
	"ABC", "abc", "123"
};

uint8_t smsMtModeNext(uint8_t mode)
{
	if (mode >= SMS_MT_MODES) { return SMS_MT_DEFAULT; }
	return (uint8_t)((mode + 1) % SMS_MT_MODES);
}

const char *smsMtModeLabel(uint8_t mode)
{
	return s_labels[(mode < SMS_MT_MODES) ? mode : SMS_MT_DEFAULT];
}

const char *smsMtKeyMap(uint8_t mode, char key)
{
	int k;
	if ((key >= '0') && (key <= '9')) { k = key - '0'; }
	else if (key == '*')              { k = 10; }
	else                              { return NULL; }
	return s_maps[(mode < SMS_MT_MODES) ? mode : SMS_MT_DEFAULT][k];
}

void smsMtCommit(smsMt_t *st, int16_t *pos)
{
	if (st->key != 0)
	{
		(*pos)++;
		st->key = 0;
		st->idx = 0;
	}
}

int smsMtKey(smsMt_t *st, uint8_t mode, char key, bool sameWindow, char *buf, int16_t *pos, int cap)
{
	const char *map = smsMtKeyMap(mode, key);
	if (map == NULL) { return 0; }

	/* Та сама клавіша в межах вікна -- наступний символ циклу на тому ж місці. */
	if ((st->key == key) && sameWindow)
	{
		st->idx++;
		if (map[st->idx] == 0) { st->idx = 0; }
		buf[*pos] = map[st->idx];
		return 1;
	}

	/* Інша клавіша або вікно минуло: попередній символ лишається, новий -- на наступне місце. */
	smsMtCommit(st, pos);
	if (*pos >= cap) { return 0; }

	buf[*pos] = map[0];
	buf[*pos + 1] = 0;
	if (map[1] == 0)          /* єдиний варіант -- гортати нічого */
	{
		(*pos)++;
		return 2;
	}
	st->key = key;
	st->idx = 0;
	return 1;
}

void smsMtBackspace(smsMt_t *st, char *buf, int16_t *pos)
{
	if (st->key != 0)
	{
		buf[*pos] = 0;
		st->key = 0;
		st->idx = 0;
		return;
	}
	if (*pos > 0)
	{
		(*pos)--;
		buf[*pos] = 0;
	}
}

#endif
