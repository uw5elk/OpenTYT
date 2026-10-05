/*
 * dmr_sms.c — on-radio encrypted DMR SMS service. See dmr_sms.h.
 *
 * Compiles to nothing unless built -DENABLE_AES -DENABLE_DMR_DATA (stock = byte-identical).
 *
 * Cipher + framing are the RE'd, on-air-validated stock-TYT scheme (a factory radio decrypts
 * our TX): AES-256-ECB over an IPv4/UDP/TMS plaintext (each 16-byte block independent, no IV),
 * carried in an Unconfirmed data PDU with a Motorola ENC extended header (ALG05 AES256). This
 * is the C port of tools/dmr_enc_sms.py (TX) and the inverse for RX, reusing crypto/dmr_aes.c.
 */
#include "functions/dmr_sms.h"

#if defined(ENABLE_DMR_DATA) && defined(ENABLE_AES)

#include "functions/dmr_data.h"
#include "functions/dmr_sms_pdu.h"   /* чисті CRC/PDU-білдери (спільні з хост-тестами) */
#include "functions/dmr_sms_fix.h"   /* fix7: корекція трибітів rate-3/4 (чиста, спільна з хост-тестами) */
#include "functions/trx.h"
#include "functions/ticks.h"
#include "functions/codeplug.h"
#include "functions/settings.h"   /* currentChannelData (per-channel encrypt byte, voice logic) */
#include "crypto/dmr_aes.h"
#include "crypto/dmr_aes_hook.h"
#include "user_interface/menuSystem.h"   /* uiNotificationShow + NOTIFICATION_* */
#include "user_interface/uiGlobals.h"    /* currentRxGroupData + *_ALL_CALL_VALUE: адресний фільтр RX */
#include "hardware/HR-C6000.h"           /* PC_CALL_FLAG: тип виклику в старшому байті trxTalkGroupOrPcId */
#include "functions/sound.h"             /* soundSetMelody: audible RX alert */
#include <string.h>

/* cleanup1 (2026-10-05): уся діагностика SMS (екрани «Діагностика» 2-4, перемикачі, знімок PDU,
 * лічильники s_dg... і s_diag..., розклад затримки квитанції, USB 0x93/0x94/0x95/0x97/0xB2/0xB3) --
 * лише з ENABLE_SMS_DIAG. Без нього перевірені налаштування -- константи DMR_SMS_DEFAULT_*,
 * а з лічильників лишається мінімум для польових скарг (бач/черг, PDU ок/пог, корекція). */
#if defined(ENABLE_SMS_DIAG)
#define SMS_DG(x) do { x; } while (0)
#else
#define SMS_DG(x) do { } while (0)
#endif

/* ETSI slot data types as reported in HR-C6000 reg 0x51 [7:4]. */
#define DT_DATA_HEADER   6
#define DT_RATE12_DATA   7
#define DT_RATE34_DATA   8   /* rate-3/4 data: 18 інфо-байтів/burst (стокова шле SMS саме так) */
/* Burst slot-type bytes we write on TX (page 0x04 reg 0x50: type<<4). */


/* ============================ message store ============================== */
/* Variable-length packed store: the MSGS custom-data block holds a small header plus a
 * byte area of back-to-back entries, so a message uses only the space its text needs
 * (stock-like: many short messages OR a few long ones share the same fixed block). A CCM
 * working copy (DMR_AES_CCM -> no net-new main RAM) is the live store. Block stays 1352 B
 * (== the old fixed 24x56 array) so it drops into an existing codeplug slot.
 * Entry layout in data[]:  [0]=flags [1]=textLen [2..3]=seq(LE) [4..7]=peerId(LE) [8..]=text */
#define SMS_ENTRY_HDR  8
typedef struct
{
	char     magic[4];                 /* "MSGV" (v2 variable-length; old "MSGS" is ignored) */
	uint8_t  version;                  /* 2 */
	uint8_t  rsvd;
	uint16_t used;                     /* bytes in use in data[] */
	uint16_t nextSeq;                  /* next message ordering id */
	uint8_t  data[DMR_SMS_STORE_DATA];
} dmrSmsStore_t;

static dmrSmsStore_t   s_store   DMR_AES_CCM;
static uint8_t         s_loaded  DMR_AES_CCM;  /* CCM is not zeroed at boot -> guard init */
static dmrSmsMessage_t s_scratch;                /* copy-out buffer for dmrSmsGet (main RAM, not CCM) */

static void runtimeReset(void);
static void cfg_invalidate(void);

static int entry_size(int off) { return SMS_ENTRY_HDR + s_store.data[off + 1]; }
static uint16_t entry_seq(int off) { return (uint16_t)(s_store.data[off + 2] | (s_store.data[off + 3] << 8)); }
static int entry_matches(int off, int outgoing)
{
	int want = outgoing ? DMR_SMS_FLAG_OUTGOING : 0;
	return (s_store.data[off] & DMR_SMS_FLAG_OUTGOING) == want;
}

static void store_blank(void)
{
	memset(&s_store, 0, sizeof s_store);
	memcpy(s_store.magic, "MSGV", 4);
	s_store.version = 2;
	s_store.used = 0;
	s_store.nextSeq = 1;
}

/* Walk the packed entry chain: every entry must lie fully inside used[] with a sane
 * textLen, and the chain must tile data[] exactly up to used. Rejects a corrupted
 * flash block whose lengths would otherwise index garbage entry boundaries. */
static int store_chain_valid(void)
{
	int o = 0;
	while (o < (int)s_store.used)
	{
		if ((o + SMS_ENTRY_HDR > (int)s_store.used) ||
				(s_store.data[o + 1] > DMR_SMS_TEXT_MAX) ||
				(o + entry_size(o) > (int)s_store.used))
		{
			return 0;
		}
		o += entry_size(o);
	}
	return 1;
}

void dmrSmsInit(void)
{
	runtimeReset();     /* clear CCM runtime state (counters, flags) before first use */
	dmrSmsReloadStore();
}

/* Перечитати сховище повідомлень і MSGC-конфіг із флеша, НЕ чіпаючи стан прийому/квитанції.
 * Меню «Повідомлення» раніше кликало на кожному вході dmrSmsInit(), а той робив
 * runtimeReset(): скидав відкладену квитанцію (s_ackPending), адресата очікуваного ACK
 * (s_txPendingDst), лічильник N(S), дедуп, незібраний PDU і всі лічильники діагностики. */
void dmrSmsReloadStore(void)
{
	uint8_t *blk = (uint8_t *)&s_store;
	cfg_invalidate();   /* пресети/отримувач із CPS -- перечитати, як і раніше при вході в меню */
	s_loaded = 1;
	dmrAesLoadKeys();   /* ensure the key store is populated for RX decrypt */
	// Обмежене читання. Довжина блока береться з ЗАГОЛОВКА У ФЛЕШІ (blockHeader.dataLength),
	// тож кодплаг із чужим або пошкодженим блоком MESSAGES міг наказати прочитати більше за
	// sizeof s_store і затерти сусідню пам'ять -- а поруч у тій самій секції CCM лежить
	// сховище AES-ключів. Обмежену версію ми вже мали й застосували до ключів, MSGC і RCTL,
	// але саме тут -- забули.
	if (codeplugGetOpenGD77CustomDataBounded(CODEPLUG_CUSTOM_DATA_TYPE_MESSAGES, blk, (int)sizeof s_store) &&
			(memcmp(s_store.magic, "MSGV", 4) == 0) && (s_store.version == 2) &&
			(s_store.used <= DMR_SMS_STORE_DATA) && store_chain_valid())
	{
		return;   /* valid variable-length store loaded from flash */
	}
	store_blank();      /* fresh, corrupted, or an old "MSGS" v1 block -> start empty */
}

static void store_ensure(void) { if (!s_loaded) { dmrSmsInit(); } }

static void store_save(void)
{
	dmrAesEnsureCustomDataRegion();   /* OpenGD77 magic must exist for the block chain */
	codeplugSetOpenGD77CustomData(CODEPLUG_CUSTOM_DATA_TYPE_MESSAGES,
			(uint8_t *)&s_store, (int)sizeof s_store);
}

/* Byte offset of the idx-th newest entry of a folder (newest = idx 0), or -1. Selection
 * scan (no large stack array): rank 0 = highest seq, each next rank = highest seq below it. */
static int off_for(int outgoing, int idx)
{
	uint32_t prevSeq = 0x10000;   /* above any 16-bit seq */
	int chosen = -1;
	for (int rank = 0; rank <= idx; rank++)
	{
		int bestOff = -1; uint32_t bestSeq = 0;
		for (int o = 0; o + SMS_ENTRY_HDR <= (int)s_store.used; o += entry_size(o))
		{
			if (!entry_matches(o, outgoing)) { continue; }
			uint32_t sq = entry_seq(o);
			if (sq < prevSeq && (bestOff < 0 || sq > bestSeq)) { bestSeq = sq; bestOff = o; }
		}
		if (bestOff < 0) { return -1; }
		chosen = bestOff; prevSeq = bestSeq;
	}
	return chosen;
}

int dmrSmsCount(int outgoing)
{
	store_ensure();
	int n = 0;
	for (int o = 0; o + SMS_ENTRY_HDR <= (int)s_store.used; o += entry_size(o))
	{
		if (entry_matches(o, outgoing)) { n++; }
	}
	return n;
}

const dmrSmsMessage_t *dmrSmsGet(int outgoing, int idx)
{
	store_ensure();
	int o = off_for(outgoing, idx);
	if (o < 0) { return NULL; }
	memset(&s_scratch, 0, sizeof s_scratch);
	s_scratch.flags   = (uint8_t)(s_store.data[o] | DMR_SMS_FLAG_USED);
	s_scratch.textLen = s_store.data[o + 1];
	s_scratch.seq     = entry_seq(o);
	s_scratch.peerId  = (uint32_t)s_store.data[o + 4] | ((uint32_t)s_store.data[o + 5] << 8) |
	                    ((uint32_t)s_store.data[o + 6] << 16) | ((uint32_t)s_store.data[o + 7] << 24);
	int tl = s_scratch.textLen; if (tl > DMR_SMS_TEXT_MAX) { tl = DMR_SMS_TEXT_MAX; }
	memcpy(s_scratch.text, &s_store.data[o + SMS_ENTRY_HDR], tl);
	return &s_scratch;
}

/* ui2 (2026-10-05): вхідне, за яке ми щойно квитували, пишеться у флеш ВІДКЛАДЕНО (s_pendInbox,
 * dmrSmsTxPersistTick) -- а банер «ще N непрочит.» і значок на головному екрані малюються раніше.
 * Без цього показане повідомлення ще не в сховищі, і «-1» у банері віднімав його вдруге (поле:
 * 10 SMS -> «ще 8»). Тепер відкладене непрочитане вхідне рахується одразу. */
static int  pendInboxUnread(void);
static void pendInboxMarkRead(void);

int dmrSmsUnreadCount(void)
{
	store_ensure();
	int n = 0;
	for (int o = 0; o + SMS_ENTRY_HDR <= (int)s_store.used; o += entry_size(o))
	{
		if (((s_store.data[o] & DMR_SMS_FLAG_OUTGOING) == 0) && (s_store.data[o] & DMR_SMS_FLAG_UNREAD)) { n++; }
	}
	return n + pendInboxUnread();
}

void dmrSmsMarkRead(int outgoing, int idx)
{
	store_ensure();
	int o = off_for(outgoing, idx);
	if (o >= 0 && (s_store.data[o] & DMR_SMS_FLAG_UNREAD))
	{
		s_store.data[o] &= (uint8_t)~DMR_SMS_FLAG_UNREAD;
		store_save();
	}
}

void dmrSmsMarkAllRead(void)
{
	store_ensure();
	int changed = 0;
	for (int o = 0; o + SMS_ENTRY_HDR <= (int)s_store.used; o += entry_size(o))
	{
		if (((s_store.data[o] & DMR_SMS_FLAG_OUTGOING) == 0) && (s_store.data[o] & DMR_SMS_FLAG_UNREAD))
		{
			s_store.data[o] &= (uint8_t)~DMR_SMS_FLAG_UNREAD; changed = 1;
		}
	}
	if (changed) { store_save(); }
	pendInboxMarkRead();   /* ui2: і ще не записане вхідне -- інакше воно «оживе» непрочитаним */
}

/* Remove the entry at byte offset o, compacting the block down. */
static void entry_remove(int o)
{
	int sz = entry_size(o);
	int tail = (int)s_store.used - (o + sz);
	if (tail > 0) { memmove(&s_store.data[o], &s_store.data[o + sz], (size_t)tail); }
	s_store.used = (uint16_t)(s_store.used - sz);
}

void dmrSmsDelete(int outgoing, int idx)
{
	store_ensure();
	int o = off_for(outgoing, idx);
	if (o >= 0) { entry_remove(o); store_save(); }
}

void dmrSmsDeleteAll(int outgoing)
{
	store_ensure();
	int changed = 0;
	int o = 0;
	while (o + SMS_ENTRY_HDR <= (int)s_store.used)
	{
		int match = (outgoing < 0) ||
				(((s_store.data[o] & DMR_SMS_FLAG_OUTGOING) != 0) == (outgoing != 0));
		if (match) { entry_remove(o); changed = 1; }   /* next entry shifted into o; don't advance */
		else { o += entry_size(o); }
	}
	if (changed) { store_save(); }
}

/* Renumber every entry's seq to 1..N preserving age order (oldest = 1). Called when the
 * 16-bit nextSeq wraps, so "newest = highest seq" ordering and lowest-seq eviction stay
 * correct across the wrap. Flag bit 0x80 is a transient "renumbered" marker (cleared
 * before returning, never persisted set). */
#define SMS_FLAG_TMP_MARK  0x80
static void seq_renumber(void)
{
	int count = 0;
	for (int o = 0; o + SMS_ENTRY_HDR <= (int)s_store.used; o += entry_size(o))
	{
		s_store.data[o] &= (uint8_t)~SMS_FLAG_TMP_MARK;
		count++;
	}
	for (int newSeq = count; newSeq >= 1; newSeq--)
	{
		int bestOff = -1; uint16_t bestSq = 0;
		for (int o = 0; o + SMS_ENTRY_HDR <= (int)s_store.used; o += entry_size(o))
		{
			if (s_store.data[o] & SMS_FLAG_TMP_MARK) { continue; }
			uint16_t sq = entry_seq(o);
			if (bestOff < 0 || sq >= bestSq) { bestSq = sq; bestOff = o; }
		}
		if (bestOff < 0) { break; }
		s_store.data[bestOff + 2] = (uint8_t)(newSeq & 0xFF);
		s_store.data[bestOff + 3] = (uint8_t)(newSeq >> 8);
		s_store.data[bestOff] |= SMS_FLAG_TMP_MARK;
	}
	for (int o = 0; o + SMS_ENTRY_HDR <= (int)s_store.used; o += entry_size(o))
	{
		s_store.data[o] &= (uint8_t)~SMS_FLAG_TMP_MARK;
	}
	s_store.nextSeq = (uint16_t)(count + 1);
}

/* Insert a new message, evicting the globally-oldest (lowest seq) until it fits. */
static void store_add(uint8_t flags, uint32_t peerId, const char *text, int textLen)
{
	store_ensure();
	if (textLen > DMR_SMS_TEXT_MAX) { textLen = DMR_SMS_TEXT_MAX; }
	if (textLen < 0) { textLen = 0; }
	int need = SMS_ENTRY_HDR + textLen;
	if (need > DMR_SMS_STORE_DATA) { return; }   /* can't ever fit */

	while ((int)s_store.used + need > DMR_SMS_STORE_DATA)
	{
		int oldest = -1; uint16_t lo = 0xFFFF;
		for (int o = 0; o + SMS_ENTRY_HDR <= (int)s_store.used; o += entry_size(o))
		{
			uint16_t sq = entry_seq(o);
			if (sq <= lo) { lo = sq; oldest = o; }
		}
		if (oldest < 0) { break; }
		entry_remove(oldest);
	}

	int o = s_store.used;
	if (s_store.nextSeq == 0) { seq_renumber(); }   /* 16-bit seq wrapped -> renumber by age */
	uint16_t seq = s_store.nextSeq++;
	s_store.data[o + 0] = (uint8_t)(DMR_SMS_FLAG_USED | flags);
	s_store.data[o + 1] = (uint8_t)textLen;
	s_store.data[o + 2] = (uint8_t)(seq & 0xFF);
	s_store.data[o + 3] = (uint8_t)(seq >> 8);
	s_store.data[o + 4] = (uint8_t)(peerId & 0xFF);
	s_store.data[o + 5] = (uint8_t)((peerId >> 8) & 0xFF);
	s_store.data[o + 6] = (uint8_t)((peerId >> 16) & 0xFF);
	s_store.data[o + 7] = (uint8_t)((peerId >> 24) & 0xFF);
	memcpy(&s_store.data[o + SMS_ENTRY_HDR], text, (size_t)textLen);
	s_store.used = (uint16_t)(o + need);
	store_save();
}

/* ============================ config (MSGC block) ======================= */
/* Read-only from the firmware's side; written by the CHIRP module. Layout is
 * shared byte-for-byte (opengd77_aes.py MsgConfig). */
#define MSGC_PRESET_LEN  48
typedef struct
{
	char     magic[4];                 /* "MSGC" */
	uint8_t  version;
	uint8_t  numPresets;
	uint8_t  defaultGroup;
	uint8_t  maxLen;                 /* CHIRP-set max compose length (0 = default 144) */
	uint32_t defaultDst;               /* little-endian on the wire == native */
	char     preset[DMR_SMS_NUM_PRESETS][MSGC_PRESET_LEN];
	uint8_t  smsEncrypt;             /* SMS-encrypt master gate: 0 = default (on), 1 = off/clear, 2 = on.
	                                  * Appended last so an old (shorter) MSGC block reads as 0 = default. */
} dmrSmsCfg_t;

static dmrSmsCfg_t s_cfg DMR_AES_CCM;
static uint8_t     s_cfgLoaded DMR_AES_CCM;

static void cfg_load(void)
{
	s_cfgLoaded = 1;
	memset(&s_cfg, 0, sizeof s_cfg);   /* default any field a shorter/absent block omits (smsEncrypt=0) */
	/* Bounded read: dataLength comes from flash — a corrupt/oversized block must not overrun s_cfg. */
	if (codeplugGetOpenGD77CustomDataBounded(CODEPLUG_CUSTOM_DATA_TYPE_MSG_CONFIG, (uint8_t *)&s_cfg, (int)sizeof s_cfg) &&
			(memcmp(s_cfg.magic, "MSGC", 4) == 0))
	{
		/* Force-terminate every preset row: dmrSmsPresetGet() returns these as C strings
		 * and the compose copy reads up to dmrSmsMaxLen() (144) chars, so an unterminated
		 * 48-byte row written by CHIRP must not run into the next row / off the struct. */
		for (int i = 0; i < DMR_SMS_NUM_PRESETS; i++) { s_cfg.preset[i][MSGC_PRESET_LEN - 1] = 0; }
		return;
	}
	memset(&s_cfg, 0, sizeof s_cfg);
}

static void cfg_ensure(void) { if (!s_cfgLoaded) { cfg_load(); } }
static void cfg_invalidate(void) { s_cfgLoaded = 0; }

int dmrSmsPresetCount(void)
{
	cfg_ensure();
	int n = 0;
	for (int i = 0; i < DMR_SMS_NUM_PRESETS; i++)
	{
		if (s_cfg.preset[i][0] != 0) { n++; }
	}
	return n;
}

const char *dmrSmsPresetGet(int idx)
{
	cfg_ensure();
	if (idx < 0 || idx >= DMR_SMS_NUM_PRESETS || s_cfg.preset[idx][0] == 0) { return 0; }
	return s_cfg.preset[idx];
}

void dmrSmsDefaultRecipient(uint32_t *dst, int *group)
{
	cfg_ensure();
	if (dst)   { *dst = s_cfg.defaultDst & 0x00FFFFFF; }
	if (group) { *group = s_cfg.defaultGroup ? 1 : 0; }
}

int dmrSmsMaxLen(void)
{
	cfg_ensure();
	int m = s_cfg.maxLen;
	if (m <= 0 || m > DMR_SMS_TEXT_MAX) { m = DMR_SMS_TEXT_MAX; }
	return m;
}

/* SMS-encrypt master gate (CHIRP "Encrypt SMS"): 1 = encrypt-per-channel-like-voice,
 * 0 = always cleartext. Default (unset MSGC byte) = 1 to preserve the encrypted behaviour. */
int dmrSmsEncryptEnabled(void)
{
	cfg_ensure();
	return (s_cfg.smsEncrypt == 1) ? 0 : 1;   /* 1 = force clear; 0(default)/2 = encrypt */
}

/* ---- Режим TX SMS (Task #31): 0=Без підтв. 1=Підтв.½ 2=Підтв.¾ ------------------- */
/* ui2 (2026-10-05): у меню два режими -- 0 «Без підтв.» і 2 «З підтв.» (CONFIRMED rate-3/4,
 * перевірено на залізі). Режим 1 (CONFIRMED rate-1/2) стокова не приймає -- це експеримент, тож
 * він є лише з ENABLE_SMS_DIAG; у звичайній збірці збережене 1 читається як 2. Блок не записаний
 * (нова установка) або значення невідоме -> 2 «З підтв.». Довжина custom-data -- той самий 1 байт. */
int dmrSmsTxMode(void)
{
	uint8_t buf = 0;
	if (!codeplugGetOpenGD77CustomDataBounded(CODEPLUG_CUSTOM_DATA_TYPE_SMS_TX_MODE, &buf, 1)) { return 2; }
	if (buf == 0) { return 0; }
#if defined(ENABLE_SMS_DIAG)
	if (buf == 1) { return 1; }
#endif
	return 2;
}

void dmrSmsTxModeSet(uint8_t mode)
{
#if defined(ENABLE_SMS_DIAG)
	if (mode > 2) { mode = 2; }
#else
	if (mode != 0) { mode = 2; }
#endif
	codeplugSetOpenGD77CustomData(CODEPLUG_CUSTOM_DATA_TYPE_SMS_TX_MODE, &mode, 1);
}

/* AES TX key for the current channel — a mirror of hrc6000ResolveAesTxKeyId (HR-C6000.c) so
 * SMS encryption follows the exact same per-channel logic as voice: the global TX selector,
 * overridden by the channel encrypt byte (0xFF -> clear, 1..15 -> key slot, 0 -> inherit).
 * Byte 41 is shared with optional-DMR-ID; на такому каналі слот лежить у _UNUSED_2 з міткою,
 * тож читаємо через codeplugChannelGetAesKeySlot(), щоб SMS шифрувались і там теж. */
static uint8_t smsResolveTxKeyId(void)
{
	uint8_t keyId = dmrAesTxKeyId();
	if (currentChannelData != NULL)
	{
		uint8_t chEnc = codeplugChannelGetAesKeySlot(currentChannelData);
		if (chEnc == 0xFF) { keyId = 0; }
		else if ((chEnc >= 1) && (chEnc < DMR_AES_MAX_KEYS)) { keyId = chEnc; }
	}
	return keyId;
}

/* ============================ TX ======================================== */
/* Контрольні суми, IPv4/UDP/TMS, черга burst-ів (stride 19) і режим «Без підтвердження»
 * -- у functions/dmr_sms_pdu.c (чистий код, спільний із хост-тестами). */
#if defined(ENABLE_SMS_DIAG)
/* ui2: CONFIRMED rate-1/2 (режим 1) стокова не приймає -- лише експеримент, тільки з ENABLE_SMS_DIAG. */
/* CRC-9 для Rate-1/2 CONFIRMED data blocks (ETSI TS 102 361-1 §B.3.10).
 * Поліном 0x059, init=0. Дані: payload10[0..9] (MSB кожного байта вперед) + 7-бітний DBSN
 * (MSB вперед). Фінал: (~reg & 0x1FF) ^ 0x0F0 (маска Rate12DataContinuation).
 * Для ЗВИЧАЙНОГО блока payload10 = 10 байт навантаження.
 * Для ОСТАННЬОГО блока payload10 = 6 байт навантаження + 4 байти CRC32 (разом 10 байт). */
static uint16_t crc9_confirmed(const uint8_t *payload10, uint8_t dbsn)
{
	uint16_t reg = 0;
	for (int i = 0; i < 10; i++)
	{
		for (int b = 7; b >= 0; b--)
		{
			uint16_t msb = (reg >> 8) & 1;
			reg = (uint16_t)((reg << 1) & 0x1FF);
			if (msb ^ ((payload10[i] >> b) & 1)) { reg ^= 0x059; }
		}
	}
	for (int b = 6; b >= 0; b--)
	{
		uint16_t msb = (reg >> 8) & 1;
		reg = (uint16_t)((reg << 1) & 0x1FF);
		if (msb ^ ((dbsn >> b) & 1)) { reg ^= 0x059; }
	}
	return (uint16_t)((~reg & 0x1FF) ^ 0x0F0);
}

/* Заповнити 12-байтний Rate-1/2 CONFIRMED data block.
 * payload10: 10 байт (нормальний блок: 10 Б навантаження; останній: 6 Б даних + 4 Б CRC32).
 * dbsn: 7-бітний Data Block Sequence Number.
 * Розкладка: [7 біт DBSN][9 біт CRC9 БІТ-РЕВЕРСНУТИЙ][10 байт навантаження]. */
static void confirmed_block_fill(uint8_t *p12, const uint8_t *payload10, uint8_t dbsn)
{
	uint16_t c9 = crc9_confirmed(payload10, dbsn);
	/* DBSN (7 біт) + CRC9 bit-reversed (9 біт) = 16 біт = 2 байти.
	 * Байт 0: DBSN[6..0] | CRC9[0] (LSB CRC9 -- перший у потоці).
	 * Байт 1: CRC9[1..8], де CRC9[1] → біт 7, CRC9[8] → біт 0. */
	p12[0] = (uint8_t)((dbsn << 1) | (c9 & 1));
	uint8_t b1 = 0;
	for (int i = 1; i <= 8; i++) { b1 |= (uint8_t)(((c9 >> i) & 1) << (8 - i)); }
	p12[1] = b1;
	memcpy(p12 + 2, payload10, 10);
}
#endif /* ENABLE_SMS_DIAG: rate-1/2 CONFIRMED */

/* CRC-9 для Rate-3/4 CONFIRMED data blocks. Той самий poly=0x059, init=0, маска 0x1FF --
 * payload 16 байт.  ETSI TS 102 361-1 §B.3.12 (Rate34DataContinuation).
 * Примітка: Rate-1/2 (§B.3.10) використовує маску 0x0F0 -- вони різні. */
static uint16_t crc9_r34(const uint8_t *payload16, uint8_t dbsn)
{
	uint16_t reg = 0;
	for (int i = 0; i < 16; i++)
	{
		for (int b = 7; b >= 0; b--)
		{
			uint16_t msb = (reg >> 8) & 1;
			reg = (uint16_t)((reg << 1) & 0x1FF);
			if (msb ^ ((payload16[i] >> b) & 1)) { reg ^= 0x059; }
		}
	}
	for (int b = 6; b >= 0; b--)
	{
		uint16_t msb = (reg >> 8) & 1;
		reg = (uint16_t)((reg << 1) & 0x1FF);
		if (msb ^ ((dbsn >> b) & 1)) { reg ^= 0x059; }
	}
	return (uint16_t)((~reg & 0x1FF) ^ 0x1FF);   /* §B.3.12: маска 0x1FF (не 0x0F0 як у rate-1/2) */
}

/* Заповнити 18-байтний Rate-3/4 CONFIRMED data block.
 * payload16: 16 байт (нормальний: 16 Б навантаження; останній: 12 Б даних + 4 Б CRC32).
 * dbsn: 7-бітний Data Block Sequence Number.
 * Розкладка: [7 біт DBSN][9 біт CRC9 БІТ-РЕВЕРСНУТИЙ][16 байт навантаження]. */
static void confirmed_block_fill_r34(uint8_t *p18, const uint8_t *payload16, uint8_t dbsn)
{
	uint16_t c9 = crc9_r34(payload16, dbsn);
	p18[0] = (uint8_t)((dbsn << 1) | (c9 & 1));
	uint8_t b1 = 0;
	for (int i = 1; i <= 8; i++) { b1 |= (uint8_t)(((c9 >> i) & 1) << (8 - i)); }
	p18[1] = b1;
	memcpy(p18 + 2, payload16, 16);
}

/* DIAGNOSTIC (USB 0x97): lets the host invoke the REAL dmrSmsSend() menu path directly,
 * optionally skipping the Sent-folder flash write, to A/B-test TX behaviour without pushing
 * radio buttons. This was used to hunt bug #3 (see below) -- the store_add() write turned out
 * to be innocent, but the harness is kept as a general on-demand SMS-TX diagnostic. Plain .bss;
 * the physical menu path never sets it. */
#if defined(ENABLE_SMS_DIAG)
static uint8_t s_diagSkipStore;
void dmrSmsDiagSetSkipStore(int skip) { s_diagSkipStore = (skip != 0) ? 1 : 0; }
#define SMS_SKIP_STORE() (s_diagSkipStore)
#else
#define SMS_SKIP_STORE() (0)
#endif

/* ---- deferred Sent-folder persist (defensive hygiene, not the bug #3 fix) ---
 * store_add() does a BLOCKING SPI-flash sector erase+write (~100s of ms). Investigating bug #3
 * (see s_txMsgCounter below for the actual root cause) an A/B test initially looked like this
 * write disrupted the on-air burst timing -- but a follow-up test with the write fully skipped
 * STILL failed after the first send, which exonerated it. Kept anyway as good practice: doing a
 * blocking flash op anywhere in the TX-keying window is fragile regardless, so dmrSmsSend stashes
 * the outgoing message and dmrSmsRxTick() flushes it to flash only once the data call has fully
 * un-keyed (dmrDataTxActive()==0 && !trxIsTransmitting). */
static uint8_t  s_pendSent;                    /* 1 = a Sent-folder write is queued */
static uint8_t  s_pendFlags;
static uint32_t s_pendPeer;
static int      s_pendTextLen;
static char     s_pendText[DMR_SMS_TEXT_MAX + 1];

/* Per-message IP-ID / TMS-sequence counter (bug #3 root cause). A stock TYT tracks these like a
 * real SMS client and DROPS a message that repeats the previous IP-ID + TMS-seq as a duplicate
 * retransmission. The firmware used to hardcode ipid=0x0001, seq=0x90 on EVERY send, so only the
 * first of a run reached the stock inbox while every later (byte-identical) send was silently
 * dropped -- HW root-caused: raw 0x91 sends with per-send-varied ipid/seq always landed; identical
 * menu sends did not, though the frame was byte-perfect on air. Seed from the boot tick so the
 * sequence doesn't restart at the same value each power-up and collide with a stock that still
 * remembers the previous session's traffic. */
static uint16_t s_txMsgCounter;
static uint8_t  s_txMsgSeeded;

/* TX-ACK (CONFIRMED SMS): прапорець і адресат останнього відправленого CONFIRMED-повідомлення.
 * s_txAcked виставляє ISR (dmrSmsRxBurst) при отриманні Response-заголовка (DPF=1) від
 * нашого адресата; зчитується (і скидається) через dmrSmsTxAcked() в основному циклі.
 * Не в .bss -- CCM; скидаємо в runtimeReset(). */
static volatile uint8_t  s_txAcked     DMR_AES_CCM;
static volatile uint32_t s_txPendingDst DMR_AES_CCM;
/* N(S) -- 3-бітний лічильник відправлених CONFIRMED SMS (Task #32).
 * s_txNS: поточне значення 0..7; збільшується на 1 щоразу після відправки.
 * s_txNSSent: 0 до першого відправлення (S=1 у першому кадрі), після -- 1. */
static uint8_t s_txNS     DMR_AES_CCM;
static uint8_t s_txNSSent DMR_AES_CCM;
/* N(S) з останнього отриманого CONFIRMED data-заголовка (Task #33).
 * ISR пише, buildAndLoadSmsAck() читає (обидва -- основний потік або ISR-захищені). */
static volatile uint8_t s_rxLastNS DMR_AES_CCM;

/* One-shot: повертає 1 і скидає прапорець, якщо отримали link-layer ACK (Response DPF=1)
 * від адресата нашого останнього CONFIRMED SMS. Безпечно викликати щоразу у головному циклі. */
int dmrSmsTxAcked(void)
{
	if (!s_txAcked) { return 0; }
	s_txAcked = 0;
	return 1;
}

/* ---- Квитанція на вхідне CONFIRMED SMS (link-layer ACK, реверс #11, ефір BBD_0005) --------
 * Стокова TYT / RT4D шлють текст CONFIRMED data-заголовком (DPF=3, біт A=1 -> «прошу
 * підтвердження»). Отримавши всі блоки (CRC32 PDU сходиться), приймач має відповісти
 * Response data header (DPF=1): відправник тоді показує «доставлено», інакше сигналить
 * помилку й ретрансмітить -- рівно як було з монітором до реверсу його квитанції.
 *
 * Знято з ефіру (BBD_0005, стокова 0x26EA3D квитує RT4D 0x26EA1B):
 *   01 40 <кому:3=початк.відправник> <від кого:3=ми> 00 08 <CRC16^0xCCCC>
 *   o0=0x01: G/I=0 (індивід.), A=0, DPF=1 (Response)
 *   o1=0x40: SAP=4 (IP based packet data) -- той самий SAP, що й у нашому тексті
 *   o8=0x00: Blocks-to-Follow = 0 (гола квитанція, за нею блоків немає)
 *   o9=0x08: Class=00 (ACK), Type=001, Status=000
 * ОБИДВА байти -- КОНСТАНТИ, нічого туди не підставляти. Перша реалізація (2026-09-12)
 * трактувала їх навпаки (o8=код, o9=луна к-сті блоків) і слала в полі `00 04` -- тобто
 * Status=4 замість ACK. Квитанція йшла в ефір (лічильники: вефір=3), але стокова її не
 * приймала й ретрансмітила повідомлення 3 рази. Не «винаходити» ці байти: шлемо рівно те,
 * що знято з ефіру.
 * CRC заголовка -- той самий, що для всіх data-заголовків (dmrSmsPduCrc16 ^ 0xCCCC).
 *
 * Ключуємо з невеликою затримкою після завершення прийому (стокова відповідала ~80 мс по
 * кінці), і лише коли канал звільнився (!dmrDataTxActive && !trxIsTransmitting) -- щоб не
 * зіткнутися з хвостом передачі відправника. */
static uint8_t  s_ackPending;   /* 1 = винні квитанцію */
static uint32_t s_ackTo;        /* кому (початковий відправник) */
static uint32_t s_ackAtMs;      /* найраніший момент ключування */
static uint32_t s_ackDeadlineMs;/* після цього квитанція протухла (канал так і не звільнився) */

/* Час останнього ПРИЙНЯТОГО data-burst (будь-якого типу) -- проксі «канал зайнятий».
 * Заповнюється в dmrSmsRxDiagBurst(), який HR-C6000 кличе на КОЖЕН data-sync burst.
 * Квитанцію ключуємо лише після паузи: інакше влучаємо у хвіст/термінатор відправника,
 * він у цей момент ще передає (отже глухий) -- і замість «доставлено» шле все наново. */
static volatile uint32_t s_lastRxBurstMs;
#define SMS_ACK_KEY_DELAY_MS 15  /* замість типових 100 мс: стокова слухає вузьке вікно */
#define SMS_ACK_MAX_WAIT_MS 2500 /* не тягнути квитанцію вічно, якщо канал не звільняється */
#define SMS_ACK_MAX_REPEATS  6   /* межа буфера черги */
#define SMS_ACK_MAX_PREAMBLES 16 /* стільки ж, скільки шле стокова перед повідомленням */

/* ПІДБІРНІ ПАРАМЕТРИ (USB 0xB2) -- щоб не перебирати прошивками по одній.
 * Типово = рівно як у стокової, знято з ефіру (BBD_0005): ОДИН burst через ~80 мс після
 * того, як відправник домовк. Ми ж слали 3 повтори через 30 мс -- і форма, і таймінг були
 * «правильні», але саме ЦИМ від стокової й відрізнялись: три Response header підряд вона
 * цілком могла зарахувати як дублікати/сміття, а 30 мс -- влучити в її перехід
 * передача->прийом. */
/* 1 = квитанція ON за замовчуванням: один Response-заголовок після отримання CONFIRMED SMS.
 * Стокова (BBD_0005) чекає квитанції; без неї вона ретрансмітить.
 * N(S) з вхідного CONFIRMED-заголовка відлунюється в o9 квитанції (Task #33). */
#if defined(ENABLE_SMS_DIAG)
static uint8_t  s_ackRepeats = 1;
static uint16_t s_ackTargetMs = 80;    /* цільова пауза після тиші в каналі, мс */
/* CSBK-преамбули перед квитанцією. ТИПОВО 6 -- і ось чому.
 * Еталоном я довго вважав те, що стокова НАДСИЛАЄ (її квитанція йде без преамбул). Але
 * правильний еталон -- те, що вона успішно ПРИЙМАЄ, і такий приклад є власний: наше
 * звичайне SMS стокова приймає, а воно йде з 6 преамбулами (dmrSmsSend). Схоже, її приймач
 * просто не «заводить» data-виклик без преамбули; RT4D виявився поблажливішим, тому її
 * власна безпреамбульна квитанція йому зайшла. Коли преамбули були в нас (rev<=4), тоді
 * стояв хибний код 00 04 -- тож поєднання «преамбули + правильний код» не перевірялось. */
static uint8_t  s_ackPreambles = 6;
/* fix3 (2026-10-02): ПІД ЧАС СТАРТУ (runtimeReset) виставляється DMR_SMS_DEFAULT_ACK_PREAMBLES = 0 --
 * запис BBD_0004 показав, що 6 преамбул (360 мс) відсувають наш заголовок на ~620 мс після кінця
 * передачі стокової, а сама стокова квитує через ~120 мс без преамбул. Ініціалізатор 6 лишено
 * навмисно: заміна на 0 перенесла б змінну з .data у .bss і зсунула б розкладку main RAM.
 * Перемикач 6/0 -- на 2-й сторінці екрана «Діагностика»; USB 0xB2 (dmrSmsAckSetTuning) теж діє. */

void dmrSmsAckSetTuning(uint8_t repeats, uint16_t delayMs, uint8_t preambles)
{
	if (repeats > SMS_ACK_MAX_REPEATS) { repeats = SMS_ACK_MAX_REPEATS; }   /* 0 = вимкнено */
	if (delayMs > 2000) { delayMs = 2000; }
	if (preambles > SMS_ACK_MAX_PREAMBLES) { preambles = SMS_ACK_MAX_PREAMBLES; }
	s_ackRepeats = repeats;
	s_ackTargetMs = delayMs;
	s_ackPreambles = preambles;
}
#define SMS_ACK_REPEATS()   ((int)s_ackRepeats)
#define SMS_ACK_PAUSE_MS()  ((uint32_t)s_ackTargetMs)
#define SMS_ACK_PREAMBLES() ((int)s_ackPreambles)
#else
/* cleanup1: перевірено на залізі 2026-10-05 -- один Response-заголовок, без CSBK-преамбул,
 * пауза 80 мс від тиші в каналі. Константи замість змінних (.data/USB 0xB2 -- лише з
 * ENABLE_SMS_DIAG). */
#define SMS_ACK_REPEATS()   (1)
#define SMS_ACK_PAUSE_MS()  ((uint32_t)DMR_SMS_DEFAULT_ACK_PAUSE_MS)
#define SMS_ACK_PREAMBLES() (DMR_SMS_DEFAULT_ACK_PREAMBLES)
#endif

/* Ревізія формату/подачі квитанції -- видно в діагностиці (sms_diag.py), щоб не гадати,
 * яка саме прошивка залита:
 *   1 = перша реалізація: 2 преамбули + заголовок, у o9 підставлявся лічильник блоків (00 04);
 *   2 = ключування по тиші в каналі + лічильники;
 *   3 = квитуємо будь-який CONFIRMED (без вимоги біта A);
 *   4 = ВИПРАВЛЕНО o8/o9 = 00 08 (ACK) -- до цього стокова законно не приймала;
 *   5 = подача як у RCTL: 3 повтори заголовка, без преамбул; гейт тиші 40 мс;
 *   6 = ТАЙМІНГ: квитанція йшла НЕГАЙНО по CRC32 -- але це ще до термінатора відправника,
 *       тобто в ефір лізли, поки він передає (глухий). РАНО;
 *   7 = вікно з обох боків: чекаємо тиші 30 мс + ключування 15 мс, блокуючий запис у флеш
 *       відкладено. Таймінг і форма стали правильні -- стокова ВСЕ ОДНО пише помилку;
 *   8 = ОДИН burst через ~80 мс (як шле стокова) + підбір по USB. Жодне зі значень сітки
 *       (1/60..150, 2/100) стокову не влаштувало -> подача ні до чого;
 *   9 = перевертаємо еталон: копіюємо не те, що стокова НАДСИЛАЄ, а те, що вона успішно
 *       ПРИЙМАЄ -- наше власне SMS із 6 CSBK-преамбулами. Преамбули тепер теж підбірні. */
#define SMS_ACK_FORMAT_REV  9

/* Лічильники для польової діагностики (USB 0x93, хвіст відповіді). Саме вони мають сказати,
 * де рветься ланцюг: чи бачили ми взагалі CONFIRMED-заголовок із проханням квитанції,
 * чи поставили її в чергу, чи реально віддали в ефір. s_ackLastHdr0/1 -- перші два байти
 * останнього вхідного data-заголовка (тобто що НАСПРАВДІ шле стокова). */
#if defined(ENABLE_SMS_DIAG)
static volatile uint32_t s_ackSeen;      /* заголовків CONFIRMED + біт A */
static volatile uint32_t s_ackQueued;    /* разів поставили квитанцію в чергу */
static volatile uint32_t s_ackSent;      /* разів реально віддали в ефір (dmrDataTxLoad) */
static volatile uint32_t s_ackStale;     /* разів кинули, бо канал не звільнився */
static volatile uint8_t  s_ackLastHdr0;  /* p[0] останнього вхідного data-заголовка */
static volatile uint8_t  s_ackLastHdr1;  /* p[1] -- SAP/блоки */
static volatile uint8_t  s_ackLastGroup; /* останнє повідомлення було груповим? */
static volatile uint8_t  s_ackLastForUs; /* останнє повідомлення адресоване нам? */
static volatile uint32_t s_ackLastDelayMs;/* мс від ост. прийнятого burst-а до віддачі квитанції */
/* Екран «Діагностика» (меню Повідомлення, 2026-09-30) -- де рветься ланцюг квитанції, без ПК.
 * У CCM (main RAM на межі); CCM не обнуляється стартапом -> скидаються в runtimeReset().
 * uint16: переповнення за польовий тест не буде, а CCM економимо. */
static volatile uint16_t s_dgHdrHwOk    DMR_AES_CCM;  /* data-заголовків (тип 6) з апаратним CRC ok */
static volatile uint16_t s_dgHdrSwOk    DMR_AES_CCM;  /* апаратний CRC «bad», програмний ok -> прийнято */
static volatile uint16_t s_dgHdrBad     DMR_AES_CCM;  /* обидва CRC погані -> відкинуто */
static volatile uint16_t s_dgRespAll    DMR_AES_CCM;  /* Response-заголовків (DPF=1) прийнято усього */
static volatile uint16_t s_dgRespForUs  DMR_AES_CCM;  /* ... з них адресованих нам (to == наш ID) */
static volatile uint16_t s_dgRespMatch  DMR_AES_CCM;  /* ... і від адресата нашого CONFIRMED -> «доставлено» */
static volatile uint16_t s_dgTxConf     DMR_AES_CCM;  /* наших CONFIRMED SMS поставлено в ефір */
/* Перемикач з екрана «Діагностика» (НЕ зберігається; з fix3 типово УВІМК): слати наше CONFIRMED через
 * dmrDataTxLoadFast() -- без термінатора й довгого TX_END. Звичайний хвіст триває ~120 мс
 * (RCTL_COMPAT.md §5h), а квитанція стокової в BBD_0000 прийшла саме через ~120 мс після
 * нашого останнього блока -- можливо, ми ще передаємо або перелаштовуємось і не чуємо її. */
static uint8_t s_dgFastEnd DMR_AES_CCM;   /* fix3: типово 1 (DMR_SMS_DEFAULT_FAST_END), доведено M2 */

int  dmrSmsDiagFastEnd(void)       { return s_dgFastEnd; }
void dmrSmsDiagFastEndToggle(void) { s_dgFastEnd = s_dgFastEnd ? 0 : 1; }
#define SMS_FAST_END() ((int)s_dgFastEnd)
#else
#define SMS_FAST_END() (DMR_SMS_DEFAULT_FAST_END)   /* cleanup1: перевірено M2/U1 */
#endif

#if defined(ENABLE_SMS_DIAG)
/* ---- fix3 (2026-10-02): прийом усіх спроб стокової + вчасна квитанція -----------------
 * Усе в CCM, не зберігається; типові значення -- DMR_SMS_DEFAULT_* (dmr_sms_pdu.h). */
/* RX обхід: data-burst-и 6/7/8 іти в SMS-хук ДО фільтра RX-стану HR-C6000 (той відкидає все з
 * апаратно «поганим» CRC, а rate-3/4 HW так і позначає). Гіпотеза з BBD_0004: форк бачив
 * заголовок лише однієї спроби стокової з трьох. */
static volatile uint8_t  s_dgRxBypass   DMR_AES_CCM;
/* Квитанція з термінатором (1) чи без (0, типово -- як і наше CONFIRMED). */
static uint8_t           s_dgAckTerm    DMR_AES_CCM;
/* Лічильники ISR до будь-яких фільтрів (лише !transmissionEnabled і SYNC_CLASS_DATA): */
static volatile uint16_t s_dgIsr6       DMR_AES_CCM;  /* data-переривань типу 6 (заголовок) */
static volatile uint16_t s_dgIsr8       DMR_AES_CCM;  /* ... типу 8 (rate-3/4) */
static volatile uint16_t s_dgFilt6      DMR_AES_CCM;  /* з них відкинув би фільтр RX-стану, тип 6 */
static volatile uint16_t s_dgFilt8      DMR_AES_CCM;  /* ... тип 8 */
/* Фактична затримка квитанції: від тиші в каналі (останній прийнятий burst) до першого
 * burst-а квитанції в чипі, мс. Міряється в dmrSmsRxTick() за dmrDataTxLastStartMs(). */
static volatile uint16_t s_ackRealDelayMs DMR_AES_CCM;
static uint32_t          s_ackSilenceMs DMR_AES_CCM;  /* s_lastRxBurstMs на момент постановки */
static uint32_t          s_ackLoadMs    DMR_AES_CCM;  /* коли чергу віддали в dmr_data */
static uint8_t           s_ackAwaitStart DMR_AES_CCM; /* 1 = чекаємо старту передачі квитанції */
/* ui1/fix4: «Квит факт» розкладено на етапи, мс: тиша -> черга (s_ackLoadMs), черга ->
 * dmrDataKeyTx(), ключування -> старт TX_START_1 у HR-C6000, старт -> перший burst у чипі. */
static volatile uint16_t s_ackStgQ DMR_AES_CCM;
static volatile uint16_t s_ackStgK DMR_AES_CCM;
static volatile uint16_t s_ackStgS DMR_AES_CCM;
static volatile uint16_t s_ackStgB DMR_AES_CCM;
/* diag5 (2026-10-04, запис BBD_0004): де гине вхідний PDU. Стокова шле CONFIRMED тричі, усі
 * burst-и доходять до SMS-хука (ISR т6 3, т8 12), а PDU склався лише з 3-ї спроби. Хост-реплей
 * тих самих байтів (tests/test_dmr_sms_replay.c) збирає PDU з ПЕРШОЇ -- отже в полі щось
 * відрізняється від реплею. Ці лічильники кажуть, що саме. ISR пише, головний цикл читає. */
static volatile uint16_t s_dgBlkNoHdr  DMR_AES_CCM;  /* блок без заголовка (s_rxHaveHeader=0) -- відкинуто */
static volatile uint16_t s_dgBlkBusy   DMR_AES_CCM;  /* блок відкинуто: попередній PDU ще не забрав головний цикл */
static volatile uint16_t s_dgBlkOvf    DMR_AES_CCM;  /* блок не влазить у s_rxPdu (переповнення) */
static volatile uint16_t s_dgBlkExtra  DMR_AES_CCM;  /* блоків уже більше, ніж у заголовку (зайві/чужі) */
static volatile uint16_t s_dgTickNotUs DMR_AES_CCM;  /* головний цикл: PDU не нам (і монітор вимк) */
static volatile uint16_t s_dgTickBad   DMR_AES_CCM;  /* головний цикл: закороткий PDU або CRC32 знімка не зійшовся */
static volatile uint16_t s_dgPickMaxMs DMR_AES_CCM;  /* найбільша затримка «PDU готовий -> забрав головний цикл», мс */
static volatile uint32_t s_rxReadyMs   DMR_AES_CCM;  /* коли ISR виставив s_rxReady */
/* diag6 (2026-10-04): ЯКІ байти псуються. На залізі (diag5, 5 SMS) 3 з 8 повністю зібраних PDU
 * (рівно стільки блоків, скільки в заголовку) мали невалідний CRC32, а HackRF ті самі спроби
 * прийняв чисто. Тут -- знімок ОСТАННЬОГО такого PDU: сирі блоки (зі службовими DBSN+CRC9),
 * час кожного від заголовка, HW-CRC кожного, сирий заголовок, CRC32 очікуваний/фактичний.
 * Лише діагностика: прийом не змінено. ISR пише, екран «Діагностика 4» читає. */
#define SMS_SNAP_MAX 8
/* поточний PDU: навантаження вже лежить у s_rxPdu, тож тримаємо лише службові байти й час */
static uint8_t           s_curSvc[SMS_SNAP_MAX][2] DMR_AES_CCM;
static uint16_t          s_curMs[SMS_SNAP_MAX]     DMR_AES_CCM;
static uint8_t           s_curHwOk                 DMR_AES_CCM;  /* біт i = HW CRC блока i валідний */
static uint8_t           s_curHdr[12]              DMR_AES_CCM;
static uint32_t          s_curHdrMs                DMR_AES_CCM;
static volatile uint8_t  s_lastHwOk                DMR_AES_CCM;  /* HW CRC burst-а, що зараз у хуку */
/* знімок останнього PDU з «CRC пог» */
static uint8_t           s_badBlk[SMS_SNAP_MAX][18] DMR_AES_CCM;
static uint16_t          s_badMs[SMS_SNAP_MAX]      DMR_AES_CCM;
static uint8_t           s_badHdr[12]               DMR_AES_CCM;
static volatile uint8_t  s_badN                     DMR_AES_CCM;  /* блоків у знімку; 0 = знімка нема */
static uint8_t           s_badLen                   DMR_AES_CCM;  /* 18 (rate-3/4) або 12 (rate-1/2) */
static uint8_t           s_badHwOk                  DMR_AES_CCM;
static uint32_t          s_badWant, s_badGot        DMR_AES_CCM;
static uint16_t          s_badSeq                   DMR_AES_CCM;  /* яке це «CRC пог» від скидання */
static volatile uint16_t s_dgDbsnBad                DMR_AES_CCM;  /* rate-3/4 CONFIRMED: DBSN != порядковий номер */
static volatile uint16_t s_dg8HwOk                  DMR_AES_CCM;  /* блоків т8, які HW позначив CRC-валідними */
/* fix7 (2026-10-05): програмна корекція 1-2 сусідніх трибітів у rate-3/4 PDU (dmr_sms_fix.c).
 * ISR віддає головному циклу PDU, зібраний рівно під заголовок, але з невалідним CRC32
 * (s_rxPeerFix = 1); головний цикл пробує виправити. Лічильники -- стор. 3 «Діагностики». */
static volatile uint16_t s_dgFixLastMs              DMR_AES_CCM;  /* час останньої корекції, мс */
static volatile uint16_t s_dgFixMaxMs               DMR_AES_CCM;  /* найдовша корекція, мс */

/* diag6/fix7: записати знімок невиправленого PDU для «Діагностики 4». Кличуть ISR (rate-1/2)
 * і головний цикл (rate-3/4 після невдалої корекції). pdu -- навантаження блоків підряд. */
static void smsSnapStore(const uint8_t *pdu, int n, int raw34, const uint8_t svc[][2], const uint16_t *ms,
                         uint8_t hwOk, const uint8_t *hdr, uint32_t want, uint32_t got, uint16_t seq)
{
	if (n > SMS_SNAP_MAX) { n = SMS_SNAP_MAX; }
	s_badN = 0;   /* поки копіюємо -- знімка «нема» (екран читає з головного циклу) */
	for (int b = 0; b < n; b++)
	{
		uint8_t *d = s_badBlk[b];
		if (raw34)
		{
			d[0] = svc[b][0];
			d[1] = svc[b][1];
			memcpy(d + 2, pdu + b * 16, 16);
		}
		else
		{
			memcpy(d, pdu + b * 12, 12);
			memset(d + 12, 0, 6);
		}
		s_badMs[b] = ms[b];
	}
	memcpy(s_badHdr, hdr, 12);
	s_badLen  = (uint8_t)(raw34 ? 18 : 12);
	s_badHwOk = hwOk;
	s_badWant = want;
	s_badGot  = got;
	s_badSeq  = seq;
	s_badN    = (uint8_t)n;
}

int  dmrSmsRxBypass(void)              { return s_dgRxBypass; }
void dmrSmsDiagRxBypassToggle(void)    { s_dgRxBypass = s_dgRxBypass ? 0 : 1; }
int  dmrSmsDiagAckTerm(void)           { return s_dgAckTerm; }
void dmrSmsDiagAckTermToggle(void)     { s_dgAckTerm = s_dgAckTerm ? 0 : 1; }
int  dmrSmsDiagAckPreambles(void)      { return s_ackPreambles; }
void dmrSmsDiagAckPreamblesToggle(void){ s_ackPreambles = (s_ackPreambles != 0) ? 0 : 6; }
int  dmrSmsDiagAckPause(void)          { return s_ackTargetMs; }
void dmrSmsDiagAckPauseToggle(void)    { s_ackTargetMs = (uint16_t)dmrSmsPduNextAckPause((int)s_ackTargetMs); }

/* ISR: облік data-переривання ДО фільтрів. filterDrops = 1, якщо фільтр RX-стану HR-C6000
 * (slotState RX_1/RX_2 + PI/CRC/CC) цей burst відкинув би. */
void dmrSmsRxEarlyNote(int rxDataType, int filterDrops)
{
	if (rxDataType == 6)      { s_dgIsr6++; if (filterDrops) { s_dgFilt6++; } }
	else if (rxDataType == 8) { s_dgIsr8++; if (filterDrops) { s_dgFilt8++; } }
}
#define SMS_ACK_TERM()   ((int)s_dgAckTerm)
#define SMS_ACK_AWAIT()  (s_ackAwaitStart)
#else
/* cleanup1: «RX обхід» -- dmrSmsRxBypass() у dmr_sms.h (константа); квитанція без
 * термінатора; очікування старту квитанції (лише для розкладу етапів) не потрібне --
 * dmrDataTxBusy() у гейті запису у флеш і так тримає до кінця передачі. */
#define SMS_ACK_TERM()   (DMR_SMS_DEFAULT_ACK_TERM)
#define SMS_ACK_AWAIT()  (0)
#endif /* ENABLE_SMS_DIAG */

/* fix7 (2026-10-05): програмна корекція 1-2 сусідніх трибітів у rate-3/4 PDU (dmr_sms_fix.c). */
static volatile uint8_t  s_rxPeerFix   DMR_AES_CCM;  /* 1 = готовий PDU з невалідним CRC32 -- на корекцію */
#if defined(ENABLE_SMS_DIAG)
/* ui2: і ці лічильники (колишня спрощена «Діагностика») -- лише з ENABLE_SMS_DIAG; пункту
 * «Діагностика» у звичайній збірці більше немає. */
static volatile uint16_t s_dgPduOk     DMR_AES_CCM;  /* PDU з валідним CRC32 зібрано (ISR) */
static volatile uint16_t s_dgCrcFail   DMR_AES_CCM;  /* блоків стільки, скільки в заголовку, а CRC32 не зійшовся */
static volatile uint16_t s_dgFixOk     DMR_AES_CCM;  /* виправлено (рівно один кандидат) */
static volatile uint16_t s_dgFixAmb    DMR_AES_CCM;  /* кілька кандидатів -- відкинуто */
static volatile uint16_t s_dgFixNone   DMR_AES_CCM;  /* жодного -- відкинуто */
#endif

/* Рішення для data-заголовка (тип 6) з HR-C6000 ISR. Раніше брали лише з апаратним crcOk --
 * а запис BBD_0000 (2026-09-30) показав: стокова ШЛЕ квитанцію `01 40 ...` з валідним CRC через
 * ~120 мс після нашого останнього блока, а банера немає. Гіпотеза: відповідь одразу після
 * нашої передачі HW позначає CRC-невалідною (як уже було з CSBK-квитанцією RCTL). Тому:
 * апаратно валідний -- як і раніше; апаратно «поганий» -- приймаємо, якщо CRC16 ^ 0xCCCC
 * сходиться програмно (ті самі байти сторінки 0x02). Лічильники доводять або спростовують. */
int dmrSmsRxHdrAccept(int hwCrcOk, const uint8_t *p12)
{
	if (hwCrcOk) { SMS_DG(s_dgHdrHwOk++); return 1; }
	if (dmrSmsPduHdrCrcOk(p12, 0xCCCC)) { SMS_DG(s_dgHdrSwOk++); return 1; }
	SMS_DG(s_dgHdrBad++);
	return 0;
}

#if defined(ENABLE_SMS_DIAG)
void dmrSmsDiagScreenGet(dmrSmsDiagScreen_t *d)
{
	d->ackSeen      = (uint16_t)s_ackSeen;
	d->ackQueued    = (uint16_t)s_ackQueued;
	d->pduOk        = s_dgPduOk;
	d->crcFail      = s_dgCrcFail;
	d->fixOk        = s_dgFixOk;
	d->fixAmb       = s_dgFixAmb;
	d->fixNone      = s_dgFixNone;
#if defined(ENABLE_SMS_DIAG)
	d->ackSent      = (uint16_t)s_ackSent;
	d->ackStale     = (uint16_t)s_ackStale;
	d->ackDelayMs   = (uint16_t)((s_ackLastDelayMs > 65535u) ? 65535u : s_ackLastDelayMs);
	d->txConf       = s_dgTxConf;
	d->respAll      = s_dgRespAll;
	d->respForUs    = s_dgRespForUs;
	d->respMatch    = s_dgRespMatch;
	d->hdrHwOk      = s_dgHdrHwOk;
	d->hdrSwOk      = s_dgHdrSwOk;
	d->hdrBad       = s_dgHdrBad;
	uint16_t dd[4];
	dmrDataTxDiag(dd);
	d->dataRejected = dd[0];
	d->dataStarted  = dd[1];
	d->dataTimeout  = dd[2];
	d->dataNoStart  = dd[3];
	d->isr6         = s_dgIsr6;
	d->isr8         = s_dgIsr8;
	d->filt6        = s_dgFilt6;
	d->filt8        = s_dgFilt8;
	d->ackRealMs    = s_ackRealDelayMs;
	d->stgQ         = s_ackStgQ;
	d->stgK         = s_ackStgK;
	d->stgS         = s_ackStgS;
	d->stgB         = s_ackStgB;
	d->blkNoHdr     = s_dgBlkNoHdr;
	d->blkBusy      = s_dgBlkBusy;
	d->blkOvf       = s_dgBlkOvf;
	d->blkExtra     = s_dgBlkExtra;
	d->tickNotUs    = s_dgTickNotUs;
	d->tickBad      = s_dgTickBad;
	d->pickMaxMs    = s_dgPickMaxMs;
	d->dbsnBad      = s_dgDbsnBad;
	d->hw8Ok        = s_dg8HwOk;
	d->fixLastMs    = s_dgFixLastMs;
	d->fixMaxMs     = s_dgFixMaxMs;
#endif
}

#if defined(ENABLE_SMS_DIAG)
/* diag6: знімок останнього PDU з «CRC пог» для екрана «Діагностика 4». */
int dmrSmsBadSnapInfo(dmrSmsBadSnapInfo_t *i)
{
	i->n       = s_badN;
	i->len     = s_badLen;
	i->hwOk    = s_badHwOk;
	i->seq     = s_badSeq;
	i->crcWant = s_badWant;
	i->crcGot  = s_badGot;
	i->hdr     = s_badHdr;
	return s_badN;
}

const uint8_t *dmrSmsBadSnapBlock(int idx, uint16_t *ms)
{
	if ((idx < 0) || (idx >= (int)s_badN) || (idx >= SMS_SNAP_MAX)) { return NULL; }
	if (ms) { *ms = s_badMs[idx]; }
	return s_badBlk[idx];
}
#endif

void dmrSmsDiagScreenReset(void)
{
	s_ackSeen = s_ackQueued = 0;
	s_dgPduOk = s_dgCrcFail = 0;
	s_dgFixOk = s_dgFixAmb = s_dgFixNone = 0;
#if defined(ENABLE_SMS_DIAG)
	s_ackSent = s_ackStale = 0;
	s_ackLastDelayMs = 0;
	s_dgHdrHwOk = s_dgHdrSwOk = s_dgHdrBad = 0;
	s_dgRespAll = s_dgRespForUs = s_dgRespMatch = 0;
	s_dgTxConf = 0;
	s_dgIsr6 = s_dgIsr8 = s_dgFilt6 = s_dgFilt8 = 0;
	s_ackRealDelayMs = 0;
	s_ackStgQ = s_ackStgK = s_ackStgS = s_ackStgB = 0;
	s_dgBlkNoHdr = s_dgBlkBusy = s_dgBlkOvf = s_dgBlkExtra = 0;
	s_dgTickNotUs = s_dgTickBad = s_dgPickMaxMs = 0;
	s_dgDbsnBad = s_dg8HwOk = 0;
	s_dgFixLastMs = s_dgFixMaxMs = 0;
	s_badN = 0; s_badSeq = 0;
	dmrDataTxDiagReset();
#endif
}
#endif /* ENABLE_SMS_DIAG */

/* Flush the deferred Sent-folder entry if one is queued and the radio has finished transmitting.
 * Called from the main loop (dmrSmsRxTick). Safe to call every tick; a no-op when idle. */
/* Відкладений запис ВХІДНОГО у теку: те саме, що s_pendSent для «Надісланих», але для
 * прийнятого повідомлення, коли ми щойно віддали квитанцію в ефір -- блокуючий флеш не має
 * потрапити у вікно, поки квитанція летить. */
static uint8_t  s_pendInbox;
static uint8_t  s_pendInboxFlags;
static uint32_t s_pendInboxPeer;
static int      s_pendInboxLen;
static char     s_pendInboxText[DMR_SMS_TEXT_MAX + 1];

static int pendInboxUnread(void)
{
	return (s_pendInbox && ((s_pendInboxFlags & DMR_SMS_FLAG_OUTGOING) == 0) &&
			(s_pendInboxFlags & DMR_SMS_FLAG_UNREAD)) ? 1 : 0;
}

static void pendInboxMarkRead(void)
{
	if (s_pendInbox) { s_pendInboxFlags &= (uint8_t)~DMR_SMS_FLAG_UNREAD; }
}

static void dmrSmsTxPersistTick(void)
{
	/* diag5: «не передаємо» -- це ще й «черга вже завантажена, але ключування чекає таймера»
	 * (dmrDataTxBusy). Раніше запис у флеш (сотні мс, блокує головний цикл) влазив саме в це
	 * вікно між dmrDataTxLoadDelayedEx() і dmrDataKeyTx(): таймер ключування не обслуговувався,
	 * і квитанція виходила на ~228 мс пізніше (етап «черга->ключування» на стор. 2). */
	if (s_pendSent && !dmrDataTxBusy() && !trxIsTransmitting)
	{
		store_add(s_pendFlags, s_pendPeer, s_pendText, s_pendTextLen);
		s_pendSent = 0;
	}
	/* Вхідне пишемо у флеш лише коли квитанція ВЖЕ пішла (s_ackPending знято) і передача
	 * завершилась. Інакше блокуючий erase+write на сотні мс з'їдає те саме вікно, заради
	 * якого ми чекаємо тиші -- рівно те, що зламало rev 5. */
	if (s_pendInbox && !s_ackPending && !SMS_ACK_AWAIT() && !dmrDataTxBusy() && !trxIsTransmitting)
	{
		store_add(s_pendInboxFlags, s_pendInboxPeer, s_pendInboxText, s_pendInboxLen);
		s_pendInbox = 0;
	}
}

/* Поставити квитанцію в чергу (викликається з dmrSmsRxTick, коли прийнято адресоване нам
 * CONFIRMED повідомлення з проханням підтвердити). Це РЕЗЕРВНИЙ шлях -- коли негайно
 * віддати не вийшло (ми самі щось передавали). Основний шлях -- buildAndLoadSmsAck() одразу. */
static void buildAndLoadSmsAck(uint32_t dst);
static void queueSmsAck(uint32_t to)
{
	uint32_t now = ticksGetMillis();
	s_ackTo = to;
	s_ackAtMs = now;                    /* далі чекаємо не таймер, а ТИШУ в каналі */
	s_ackDeadlineMs = now + SMS_ACK_MAX_WAIT_MS;
	s_ackPending = 1;
	SMS_DG(s_ackQueued++);
}

/* Резервний шлях: віддати відкладену квитанцію, коли канал звільниться.
 * Черга = Response data header, ПОВТОРЕНИЙ SMS_ACK_REPEATS разів, БЕЗ CSBK-преамбул.
 * Саме так влаштована квитанція RCTL (dmr_rctl_stock_build_ack_tx: 3 повтори, без преамбул),
 * а вона з цією ж стоковою перевірена на залізі. Команди RCTL шлються з 16 преамбулами,
 * квитанції -- ні: відповідь має початися ЯКНАЙШВИДШЕ, поки відправник ще слухає.
 * Попередня версія слала 2 преамбули + заголовок, тобто сам заголовок виходив в ефір на
 * ~120 мс пізніше; в ефірному зразку (BBD_0005) преамбул перед квитанцією теж не знайшлось. */
static void dmrSmsAckTick(void)
{
	if (!s_ackPending) { return; }

	uint32_t now = ticksGetMillis();
	if ((int32_t)(now - s_ackDeadlineMs) >= 0)
	{
		/* Канал так і не звільнився (відправник молотить ретрансміти впритул) -- кидаємо,
		 * інакше квитанція вилетить у зовсім інший момент і тільки заважатиме. */
		s_ackPending = 0;
		SMS_DG(s_ackStale++);
		return;
	}
	if (dmrDataTxActive() || trxIsTransmitting) { return; }        /* ми самі передаємо */
	/* Головна умова: відправник має ЗАМОВКНУТИ. Поки в каналі ідуть data-burst-и (хвіст
	 * повідомлення, термінатор), він передає і нас не почує. */
	{
		uint32_t wait = (SMS_ACK_PAUSE_MS() > SMS_ACK_KEY_DELAY_MS)
				? (uint32_t)(SMS_ACK_PAUSE_MS() - SMS_ACK_KEY_DELAY_MS) : 1u;
		if ((uint32_t)(now - s_lastRxBurstMs) < wait) { return; }
	}
	/* На slotState НЕ гейтуємо навмисно: після прийому він тримається в RX-стані до
	 * END_TICK_TIMEOUT тиші, тож чекання на IDLE могло б з'їсти весь дедлайн і квитанція б
	 * не пішла ніколи. Детерміноване ключування все одно робить сам dmrDataTxLoad()
	 * (він кличе HRC6000ForceDMRIdleForTx()). */

	/* Самовимір: скільки минуло від ОСТАННЬОГО прийнятого burst-а відправника до моменту,
	 * коли ми віддали квитанцію. Еталон -- ~80 мс у стокової; 366 мс (rev 5) було пізно.
	 * Видно в sms_diag.py, тож наступну перевірку таймінгу можна робити без HackRF. */
	SMS_DG(s_ackLastDelayMs = now - s_lastRxBurstMs);
	buildAndLoadSmsAck(s_ackTo);
}

/* Зібрати й НЕГАЙНО віддати квитанцію в ефір. Виділено окремо, бо головний шлях -- саме
 * негайний: чекати тіка чи блокуючого запису у флеш не можна, вікно відправника вузьке. */
static void buildAndLoadSmsAck(uint32_t dst)
{
	uint32_t src = trxDMRID;        /* від кого: ми */
	/* [CSBK-преамбули x s_ackPreambles] + Response header x s_ackRepeats. Заголовок: BF=0,
	 * o9 = Class 00 | Type 001 (ACK) | Status = N(S) відправника (dmrSmsPduAckHeader).
	 * fix3: типово 0 преамбул (як у стокової) -- див. коментар біля s_ackPreambles. */
	static uint8_t q[(SMS_ACK_MAX_PREAMBLES + SMS_ACK_MAX_REPEATS) * BURST_STRIDE] DMR_AES_CCM;
	int n = dmrSmsPduBuildAckQueue(q, SMS_ACK_MAX_PREAMBLES + SMS_ACK_MAX_REPEATS, dst, src, s_rxLastNS,
	                               SMS_ACK_PREAMBLES(), SMS_ACK_REPEATS());
	if (n <= 0) { s_ackPending = 0; return; }
	/* Коротка затримка ключування замість типових 100 мс: відправник слухає вузьке вікно.
	 * fix3: без термінатора (s_dgAckTerm=0, типово) -- після нашого заголовка йшли 2 TERM_LC
	 * зі сміттям (LC ми не задаємо), і стокова в цей час уже мала б слухати.
	 * s_ackSent -- лише якщо dmr_data прийняв чергу (відмови видно в рядку «Дані»). */
	if (dmrDataTxLoadDelayedEx(q, (uint8_t)n, SMS_ACK_KEY_DELAY_MS, SMS_ACK_TERM() ? 0 : 1))
	{
#if defined(ENABLE_SMS_DIAG)
		s_ackSent++;
		s_ackSilenceMs = s_lastRxBurstMs;   /* відлік фактичної затримки -- від тиші в каналі */
		s_ackLoadMs = ticksGetMillis();
		s_ackAwaitStart = 1;
#endif
	}
	s_ackPending = 0;
}

/* Черга CONFIRMED-повідомлення (режими 1 = rate-1/2 і 2 = rate-3/4). Повертає к-сть burst-ів
 * або <0. Режим 0 будує dmrSmsPduBuildUnconf() (dmr_sms_pdu.c) -- там шлях 438ec23. */
static int buildConfirmedQueue(uint8_t *q, int txMode, const uint8_t *ct, int ctLen,
                               uint32_t src, uint32_t dst, int group, int encrypt, uint8_t keyId)
{
	/* --- Загальні параметри блочного розкладу --- */
	/* Розмір корисного навантаження в ОСТАННЬОМУ блоці: rate-1/2 -> 6 Б, rate-3/4 -> 12 Б. */
	int lastPayload = (txMode == 1) ? 6 : 12;   /* місце під payload у фінальному блоці */
	int blkSize     = (txMode == 1) ? 10 : 16;  /* корисне навантаження «нормального» блоку */
	int nNormal    = (ctLen > lastPayload) ? ((ctLen - lastPayload + blkSize - 1) / blkSize) : 0;
	int nDataBlocks = nNormal + 1;
	int ctPad      = nNormal * blkSize + lastPayload;  /* ємність навантаження (без 4 Б CRC32) */
	int poc        = ctPad - ctLen;                    /* нульовий хвіст перед CRC32 */
	uint8_t pdu[400];                                  /* ~390 Б для 144-симв. повідомлення */
	if (ctPad + 4 > (int)sizeof pdu) { return -4; }
	memcpy(pdu, ct, ctLen);
	if (poc > 0) { memset(pdu + ctLen, 0, poc); }
	/* CRC32: нулі на місці поля, потім dmrSmsPduCrc32() обробляє ctPad+4 байти.
	 * (dmrSmsPduCrc32 обробляє len*8-32 бітів -- ETSI CRC поле включено в довжину.) */
	memset(pdu + ctPad, 0, 4);
	uint32_t crc = dmrSmsPduCrc32(pdu, ctPad + 4);
	int nblocks = (encrypt ? 1 : 0) + nDataBlocks;  /* блоків після заголовка CONFIRMED */

	/* --- Будуємо чергу burst-ів --- */
	int n = 0;
	int preamble = 6;
	int tail = (encrypt ? 2 : 1) + nDataBlocks;
	uint8_t g = group ? 0x80 : 0x00;
	uint8_t gc = group ? 0xC0 : 0x80;
	/* CSBK-преамбули (6 шт.), як у стоковому TYT SMS. */
	for (int i = 0; i < preamble; i++)
	{
		uint8_t body[10];
		body[0] = 0xBD; body[1] = 0x00; body[2] = gc; body[3] = (uint8_t)((preamble - 1 - i) + tail);
		body[4] = (uint8_t)(dst >> 16); body[5] = (uint8_t)(dst >> 8); body[6] = (uint8_t)dst;
		body[7] = (uint8_t)(src >> 16); body[8] = (uint8_t)(src >> 8); body[9] = (uint8_t)src;
		uint8_t p12[12]; memcpy(p12, body, 10); dmrSmsPduHdrCrc(body, 10, 0xA5A5, p12 + 10);
		if (n >= DMR_DATA_MAX_BURSTS) { return -5; }
		n = dmrSmsPduAppendBurst(q, n, DTB_CSBK, p12, 12);
	}
	/* CONFIRMED data header (DPF=3, A-bit=0x40 -- запит link-layer квитанції).
	 * SAP 09 [EXTD HDR] якщо шифруємо (за ним іде ENC ext header); SAP 04 [IP] для cleartext.
	 * o9: S(7) | N(S)(6-4) | 0x08; S=1 для першого відправлення після ввімкнення. */
	{
		uint8_t ns   = s_txNS & 7;
		uint8_t sbit = s_txNSSent ? 0 : 1;
		s_txNS     = (uint8_t)((ns + 1) & 7);
		s_txNSSent = 1;
		uint8_t h[10];
		h[0] = (uint8_t)(g | 0x40 | 0x03);
		h[1] = (uint8_t)(((encrypt ? 9 : 4) << 4) | (poc & 0x0F));
		h[2] = (uint8_t)(dst >> 16); h[3] = (uint8_t)(dst >> 8); h[4] = (uint8_t)dst;
		h[5] = (uint8_t)(src >> 16); h[6] = (uint8_t)(src >> 8); h[7] = (uint8_t)src;
		h[8] = (uint8_t)(0x80 | (nblocks & 0x7F));
		h[9] = (uint8_t)(0x08 | (ns << 4) | (sbit << 7));  /* N(S) + S-bit */
		uint8_t p12[12]; memcpy(p12, h, 10); dmrSmsPduHdrCrc(h, 10, 0xCCCC, p12 + 10);
		if (n >= DMR_DATA_MAX_BURSTS) { return -5; }
		n = dmrSmsPduAppendBurst(q, n, DTB_DATA_HEADER, p12, 12);
	}
	/* ENC extended header (ALG05 AES256, key id) -- лише при шифруванні. */
	if (encrypt)
	{
		uint8_t e[10] = { 0x4F, 0x10, 0x51, keyId, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00 };
		uint8_t p12[12]; memcpy(p12, e, 10); dmrSmsPduHdrCrc(e, 10, 0xCCCC, p12 + 10);
		if (n >= DMR_DATA_MAX_BURSTS) { return -5; }
		n = dmrSmsPduAppendBurst(q, n, DTB_DATA_HEADER, p12, 12);
	}
	/* Data blocks: rate-1/2 (10 Б payload, DTB_RATE12_DATA) або rate-3/4 (16 Б, DTB_RATE34_DATA). */
#if defined(ENABLE_SMS_DIAG)
	if (txMode == 1)
	{
		/* Rate-1/2 CONFIRMED data blocks (ETSI §B.3.10): 12 Б = 2 Б hdr + 10 Б payload.
		 * Нормальні блоки: 10 Б навантаження кожен.
		 * Останній блок: 6 Б навантаження + 4 Б CRC32 = 10 Б у CRC9-зоні. */
		for (int b = 0; b < nNormal; b++)
		{
			if (n >= DMR_DATA_MAX_BURSTS) { return -5; }
			uint8_t p12[12];
			confirmed_block_fill(p12, pdu + b * 10, (uint8_t)b);
			n = dmrSmsPduAppendBurst(q, n, DTB_RATE12_DATA, p12, 12);
		}
		{
			if (n >= DMR_DATA_MAX_BURSTS) { return -5; }
			uint8_t last10[10];
			memcpy(last10, pdu + nNormal * 10, 6);
			last10[6] = (uint8_t)(crc >> 24); last10[7] = (uint8_t)(crc >> 16);
			last10[8] = (uint8_t)(crc >> 8);  last10[9] = (uint8_t)crc;
			uint8_t p12[12];
			confirmed_block_fill(p12, last10, (uint8_t)nNormal);
			n = dmrSmsPduAppendBurst(q, n, DTB_RATE12_DATA, p12, 12);
		}
	}
	else
#endif /* ENABLE_SMS_DIAG */
	{
		/* Rate-3/4 CONFIRMED блоки (режим 2): DTB_RATE34_DATA, 18 Б = 2 hdr + 16 payload.
		 * Нормальні блоки: 16 Б навантаження кожен.
		 * Останній блок: 12 Б + 4 Б CRC32. */
		for (int b = 0; b < nNormal; b++)
		{
			if (n >= DMR_DATA_MAX_BURSTS) { return -5; }
			uint8_t p18[18];
			confirmed_block_fill_r34(p18, pdu + b * 16, (uint8_t)b);
			n = dmrSmsPduAppendBurst(q, n, DTB_RATE34_DATA, p18, 18);
		}
		{
			if (n >= DMR_DATA_MAX_BURSTS) { return -5; }
			uint8_t last16[16];
			memcpy(last16, pdu + nNormal * 16, 12);
			last16[12] = (uint8_t)(crc >> 24); last16[13] = (uint8_t)(crc >> 16);
			last16[14] = (uint8_t)(crc >> 8);  last16[15] = (uint8_t)crc;
			uint8_t p18[18];
			confirmed_block_fill_r34(p18, last16, (uint8_t)nNormal);
			n = dmrSmsPduAppendBurst(q, n, DTB_RATE34_DATA, p18, 18);
		}
	}

	return n;
}

int dmrSmsSend(const char *text, uint32_t dst, int group, uint8_t keyId)
{
	store_ensure();
	if (text == NULL) { return -1; }
	int tlen = (int)strlen(text);
	if (tlen == 0) { return -1; }
	if (tlen > DMR_SMS_TEXT_MAX) { tlen = DMR_SMS_TEXT_MAX; }
	if (dmrDataTxActive()) { return -2; }   /* a data call is already keyed */

	/* Decide encrypt-or-clear, following the VOICE key-selection logic gated by the CHIRP
	 * "Encrypt SMS" master switch: gate OFF -> always cleartext (even on an encrypted channel);
	 * ON -> the per-channel encrypt byte exactly like voice (0xFF or no loaded key -> clear,
	 * 1..15 -> that key slot, 0 -> the global TX selector). An explicit caller keyId (CPS/bench)
	 * overrides the gate. When encrypting, the ENC ext header signals the key id to the receiver. */
	if (keyId == 0 && dmrSmsEncryptEnabled()) { keyId = smsResolveTxKeyId(); }
	const uint8_t *key = (keyId != 0) ? dmr_aes_key_ptr(keyId) : NULL;
	int encrypt = (key != NULL);             /* resolved to a loaded key -> encrypt; else cleartext */

	uint32_t src = trxDMRID;

	/* 1) plaintext. When encrypting, ECB-encrypt the WHOLE 16-byte blocks only; the trailing
	 *    partial block (< 16 B) stays CLEAR, exactly like a stock TYT. Cleartext SMS skips the
	 *    encryption (same IPv4/UDP/TMS structure, and no ENC header emitted below). Do NOT pad. */
	uint8_t pt[360];   /* IPv4(20)+UDP(8)+TMS(10)+2*144 = 326 B max */
	/* Advance the per-message counter and derive a unique IP-ID + TMS-seq so consecutive sends
	 * aren't dropped by the stock radio as duplicate retransmissions (bug #3). The TMS byte keeps
	 * the 0x9x "text message" high nibble (0x00 there makes a stock TYT read the text 4 bytes early
	 * and prepend the length field as a stray char) and varies the low nibble; the 16-bit IP-ID
	 * gives full per-datagram uniqueness (and changes the IP/UDP checksums + data CRC32 too). */
	if (!s_txMsgSeeded) { s_txMsgCounter = (uint16_t)ticksGetMillis(); s_txMsgSeeded = 1; }
	s_txMsgCounter++;
	uint16_t ipid = s_txMsgCounter;
	uint8_t  tmsSeq = (uint8_t)(0x90 | (s_txMsgCounter & 0x0F));
	int ptLen = dmrSmsPduBuildPlaintext(text, tlen, src, dst, tmsSeq, ipid, pt);
	if (encrypt) { for (int i = 0; i + 16 <= ptLen; i += 16) { aes256_ecb_encrypt(key, pt + i); } }
	int ctLen = ptLen;                       /* ct = whole enc blocks + clear tail (or all clear) */

	/* 2) Черга burst-ів -- за режимом TX SMS (меню «Повідомлення», CODEPLUG_CUSTOM_DATA_TYPE_SMS_TX_MODE):
	 *   0 = Без підтвердження -- рівно шлях 438ec23, що працював у полі:
	 *       Unconfirmed, сирі 12-байтні rate-1/2 блоки (dmrSmsPduBuildUnconf); групові -- завжди так;
	 *   2 = «З підтв.» (ТИПОВО з ui2) -- CONFIRMED rate-3/4 (buildConfirmedQueue);
	 *   1 = CONFIRMED rate-1/2 -- лише з ENABLE_SMS_DIAG.
	 * q -- у CCM: 40 x 19 = 760 байт, main RAM не зачеплено. */
	int txMode = dmrSmsTxMode();
	/* ui2: групові SMS -- завжди без підтвердження. Квитанцію на груповий CONFIRMED ніхто не шле
	 * (ми самі групові не квитуємо, smsIsForUs/ackReq), тож A-біт там лише змушував би чекати.
	 * Раніше в режимі «Підтв.» групові йшли CONFIRMED; тепер «З підтв.» типовий -- тому явно. */
	if (group) { txMode = 0; }
	static uint8_t q[DMR_DATA_MAX_BURSTS * BURST_STRIDE] DMR_AES_CCM;
	int n;
	if (txMode == 0)
	{
		n = dmrSmsPduBuildUnconf(q, DMR_DATA_MAX_BURSTS, pt, ctLen, src, dst, group, encrypt, keyId);
	}
	else
	{
		n = buildConfirmedQueue(q, txMode, pt, ctLen, src, dst, group, encrypt, keyId);
	}
	if (n < 0) { return n; }

	/* Queue the Sent-folder write for AFTER the TX finishes (see s_pendSent / dmrSmsTxPersistTick)
	 * -- keeps the blocking flash erase+write out of the TX-keying window on general principle
	 * (see the comment above s_pendSent for why this turned out not to be bug #3 itself). */
	if (!SMS_SKIP_STORE())
	{
		/* A prior send not yet flushed? The guard above ensured no active data call, so persist it
		 * now before reusing the single pending slot. In practice the main-loop tick already
		 * flushed it (menu sends are seconds apart). */
		if (s_pendSent)
		{
			store_add(s_pendFlags, s_pendPeer, s_pendText, s_pendTextLen);
			s_pendSent = 0;
		}
		s_pendFlags = (uint8_t)(DMR_SMS_FLAG_OUTGOING | (group ? DMR_SMS_FLAG_GROUP : 0));
		s_pendPeer = dst;
		s_pendTextLen = tlen;
		memcpy(s_pendText, text, tlen);
		s_pendText[tlen] = 0;
		s_pendSent = 1;
	}
	/* Зберігаємо dst, щоб перевірити Response-заголовок (ACK) від адресата. Режим 0 квитанції
	 * не просить -- 0 не збігається з жодним реальним ID, хибного «доставлено» не буде. */
	s_txPendingDst = (txMode != 0) ? dst : 0;
	s_txAcked = 0;
	if (txMode != 0) { SMS_DG(s_dgTxConf++); }
	/* CONFIRMED (режими 1/2) -- типово без термінатора (fix3, доведено M2: інакше наш хвіст
	 * перекриває квитанцію стокової). Режим 0 -- завжди звичайний кінець (шлях 438ec23). */
	if (dmrSmsPduUseFastEnd(txMode, SMS_FAST_END())) { dmrDataTxLoadFast(q, (uint8_t)n); }
	else                                          { dmrDataTxLoad(q, (uint8_t)n); }
	return 0;
}

/* ============================ RX ======================================== */
/* ISR-side reassembly state (CCM, not zeroed at boot -> reset in dmrSmsRxReset). */
static volatile uint8_t  s_rxHaveHeader DMR_AES_CCM;
static volatile uint8_t  s_rxHaveEnc DMR_AES_CCM;
static volatile uint8_t  s_rxExpBlocks DMR_AES_CCM;   /* rate-1/2 blocks expected (nblocks-1) */
static volatile uint8_t  s_rxHdrBlocks DMR_AES_CCM;   /* diag5: nblocks із заголовка як є */
static volatile uint8_t  s_rxCount DMR_AES_CCM;
static volatile uint8_t  s_rxGroup DMR_AES_CCM;
static volatile uint8_t  s_rxKeyId DMR_AES_CCM;
static volatile uint32_t s_rxSrc DMR_AES_CCM;
static volatile uint32_t s_rxDst DMR_AES_CCM;
/* Блоки навантаження пишемо ПРЯМО в s_rxPdu у міру надходження (замість окремого масиву
 * блоків -- економить CCM і природно підтримує і 12-байтні rate-1/2, і 18-байтні rate-3/4).
 * s_rxLen -- скільки байтів уже накопичено. */
static volatile uint16_t s_rxLen DMR_AES_CCM;
/* hand-off to main loop */
static volatile uint8_t  s_rxReady DMR_AES_CCM;       /* a complete PDU is waiting */
static uint8_t  s_rxPdu[384] DMR_AES_CCM;
static volatile uint16_t s_rxPduLen DMR_AES_CCM;
static volatile uint32_t s_rxPeer DMR_AES_CCM;
static volatile uint32_t s_rxPeerDst DMR_AES_CCM;   /* адресат із ВІДКРИТОГО заголовка -- для фільтра */
static volatile uint8_t  s_rxPeerGroup DMR_AES_CCM;
static volatile uint8_t  s_rxPeerKeyId DMR_AES_CCM;
static volatile uint8_t  s_rxPeerEnc DMR_AES_CCM;   /* 1 = PDU carried the ENC header (decrypt); 0 = cleartext */
static volatile uint8_t  s_rxAckReq DMR_AES_CCM;    /* вхідний data-заголовок = CONFIRMED + прохання квитанції */
static volatile uint8_t  s_rxPeerAckReq DMR_AES_CCM;/* знімок s_rxAckReq на момент готового PDU */
/* Дедуплікація вхідних SMS (Task #34).
 * Те ж саме повідомлення (той самий відправник + IP-ID + TMS-seq) в межах ~30 с відкидається:
 * не зберігається і не показується (але квитанцію відправляємо завжди). */
static volatile uint32_t s_dedupPeer   DMR_AES_CCM;   /* відправник */
static volatile uint16_t s_dedupIpId   DMR_AES_CCM;   /* IPv4 IP-ID pdu[4..5] */
static volatile uint8_t  s_dedupTmsSeq DMR_AES_CCM;   /* TMS-seq pdu[32] */
static volatile uint32_t s_dedupTs     DMR_AES_CCM;   /* tick часу останнього прийнятого (мс) */
#if defined(ENABLE_SMS_DIAG)
/* diagnostic counters (visible on the Messages home screen) to localise RX failures */
static volatile uint32_t s_diagData   DMR_AES_CCM; /* ALL data-sync-class bursts the chip delivered */
static volatile uint32_t s_diagHdrOk  DMR_AES_CCM; /* type-6 data-header, CRC OK   */
static volatile uint32_t s_diagHdrBad DMR_AES_CCM; /* type-6 data-header, CRC bad  */
static volatile uint32_t s_diagBlkOk  DMR_AES_CCM; /* type-7 rate-1/2,   CRC OK    */
static volatile uint32_t s_diagBlkBad DMR_AES_CCM; /* type-7 rate-1/2,   CRC bad   */
static volatile uint32_t s_diagPdu    DMR_AES_CCM; /* completed PDUs handed to main loop */
static volatile uint32_t s_diagMsg    DMR_AES_CCM; /* successfully decrypted + stored    */
static volatile uint32_t s_diagType[16] DMR_AES_CCM; /* гістограма rxDataType (0..15) усіх data-sync бурстів -- щоб бачити, яким типом стокова шле навантаження */
/* snapshot of the last reassembled (encrypted) PDU, for offline inspection over USB */
static uint8_t  s_diagLastPdu[120] DMR_AES_CCM;
static volatile uint16_t s_diagLastPduLen DMR_AES_CCM;
static volatile uint8_t  s_diagLastKeyId DMR_AES_CCM;
static volatile uint8_t  s_diagLastExp DMR_AES_CCM;
static volatile uint32_t s_diagLastPeer DMR_AES_CCM;
/* СИРІ блоки навантаження, як їх віддає чип -- РАЗОМ зі службовими байтами (DBSN+CRC9).
 * Потрібні, щоб реверснути CRC9 по реальному еталону, а не вигадувати його: без валідного
 * CRC9 наші власні CONFIRMED-блоки приймач відкине. Штатний шлях ці 2 байти відкидає, тож
 * тут зберігаємо блок цілим. */
#define SMS_RAWBLK_MAX   8
#define SMS_RAWBLK_SIZE  18
static uint8_t  s_rawBlk[SMS_RAWBLK_MAX][SMS_RAWBLK_SIZE] DMR_AES_CCM;
static volatile uint8_t s_rawBlkLen[SMS_RAWBLK_MAX] DMR_AES_CCM;
static volatile uint8_t s_rawBlkCount DMR_AES_CCM;

/* Fill out with [pduLen_hi,pduLen_lo, keyId, expBlocks, peer(4 LE), rawPdu...]. Returns bytes.
 * pduLen (and the raw bytes) are clamped to the snapshot buffer size: a PDU longer than
 * sizeof s_diagLastPdu is stored truncated, so only that many bytes exist to dump. */
int dmrSmsRxLastPdu(uint8_t *out, int maxlen)
{
	int n = s_diagLastPduLen;
	if (n > (int)sizeof s_diagLastPdu) { n = (int)sizeof s_diagLastPdu; }
	if (maxlen < 8 + n) { n = maxlen - 8; if (n < 0) n = 0; }
	out[0] = (uint8_t)(s_diagLastPduLen >> 8);
	out[1] = (uint8_t)(s_diagLastPduLen);
	out[2] = s_diagLastKeyId;
	out[3] = s_diagLastExp;
	out[4] = (uint8_t)(s_diagLastPeer);
	out[5] = (uint8_t)(s_diagLastPeer >> 8);
	out[6] = (uint8_t)(s_diagLastPeer >> 16);
	out[7] = (uint8_t)(s_diagLastPeer >> 24);
	for (int i = 0; i < n; i++) { out[8 + i] = s_diagLastPdu[i]; }
	return 8 + n;
}

void dmrSmsRxDiagReset(void)
{
	s_diagData = s_diagHdrOk = s_diagHdrBad = s_diagBlkOk = s_diagBlkBad = 0;
	s_diagPdu = s_diagMsg = 0;
	s_diagLastPduLen = 0;
	for (int i = 0; i < 16; i++) { s_diagType[i] = 0; }
	s_ackSeen = s_ackQueued = s_ackSent = s_ackStale = 0;
	s_ackLastHdr0 = s_ackLastHdr1 = s_ackLastGroup = s_ackLastForUs = 0;
	s_ackLastDelayMs = 0;
	s_rawBlkCount = 0;
	dmrSmsDiagScreenReset();
}

/* Дамп сирих блоків: [count, (len, bytes...) x count]. Повертає довжину. */
int dmrSmsRxRawBlocks(uint8_t *out, int maxlen)
{
	int n = 0;
	if (maxlen < 1) { return 0; }
	out[n++] = s_rawBlkCount;
	for (int b = 0; b < (int)s_rawBlkCount; b++)
	{
		int len = s_rawBlkLen[b];
		if (n + 1 + len > maxlen) { break; }
		out[n++] = (uint8_t)len;
		for (int i = 0; i < len; i++) { out[n++] = s_rawBlk[b][i]; }
	}
	return n;
}

/* Діагностика квитанції (USB 0x93, дописано в хвіст відповіді):
 *   [0]=заголовків CONFIRMED+A, [1]=поставлено в чергу, [2]=віддано в ефір,
 *   [3]=кинуто (канал не звільнився), [4]=p[0] ост. заголовка, [5]=p[1],
 *   [6]=ост. було груповим, [7]=ост. адресоване нам.
 * Читається: якщо [0]=0 -- стокова не просить квитанції (дивись [4]); якщо [0]>0, а [1]=0 --
 * відсіяв фільтр (груповий/не нам: [6]/[7]); якщо [1]>0, а [2]=0 -- канал не звільнявся. */
void dmrSmsAckDiag(uint32_t out[13])
{
	out[0] = s_ackSeen;   out[1] = s_ackQueued;
	out[2] = s_ackSent;   out[3] = s_ackStale;
	out[4] = s_ackLastHdr0; out[5] = s_ackLastHdr1;
	out[6] = s_ackLastGroup; out[7] = s_ackLastForUs;
	out[8] = SMS_ACK_FORMAT_REV;   /* яка саме прошивка залита -- щоб не гадати */
	out[9] = s_ackRepeats;
	out[10] = s_ackLastDelayMs;    /* виміряна пауза; еталон стокової ~80 мс */
	out[11] = s_ackTargetMs;       /* цільова пауза (підбірна) */
	out[12] = s_ackPreambles;      /* CSBK-преамбул перед квитанцією (підбірні) */
}

/* Гістограма rxDataType (16 значень) усіх прийнятих data-sync бурстів. */
void dmrSmsRxDiagTypes(uint32_t out[16])
{
	for (int i = 0; i < 16; i++) { out[i] = s_diagType[i]; }
}

void dmrSmsRxDiag(uint32_t out[7])
{
	out[0] = s_diagData;
	out[1] = s_diagHdrOk; out[2] = s_diagHdrBad;
	out[3] = s_diagBlkOk; out[4] = s_diagBlkBad;
	out[5] = s_diagPdu;   out[6] = s_diagMsg;
}
#endif /* ENABLE_SMS_DIAG: USB 0x93/0x94/0x95/0xB2/0xB3 */

/* Called for EVERY data-sync-class burst (any type, any CRC) so we can see exactly what
 * the HR-C6000 delivers during a stock SMS transmission. ISR context. ФУНКЦІЙНА частина
 * (будь-яка збірка): мітка s_lastRxBurstMs -- гейт тиші для квитанції. Решта -- лічильники
 * ENABLE_SMS_DIAG. */
void dmrSmsRxDiagBurst(int rxDataType, int crcOk)
{
	s_lastRxBurstMs = ticksGetMillis();   /* канал зайнятий ЗАРАЗ -- гейт тиші для квитанції */
#if defined(ENABLE_SMS_DIAG)
	s_diagData++;
	s_diagType[rxDataType & 0x0F]++;   /* гістограма типів -- бачити тип блоків навантаження */
	s_lastHwOk = (uint8_t)(crcOk ? 1 : 0);   /* diag6: хук кличе нас прямо перед dmrSmsRxBurst() */
	if ((rxDataType == DT_RATE34_DATA) && crcOk) { s_dg8HwOk++; }
	if (rxDataType == DT_DATA_HEADER) { if (crcOk) s_diagHdrOk++; else s_diagHdrBad++; }
	else if (rxDataType == DT_RATE12_DATA) { if (crcOk) s_diagBlkOk++; else s_diagBlkBad++; }
#else
	(void)rxDataType;
	(void)crcOk;
#endif
}

void dmrSmsRxReset(void)
{
	s_rxHaveHeader = 0; s_rxHaveEnc = 0; s_rxExpBlocks = 0; s_rxHdrBlocks = 0; s_rxCount = 0; s_rxLen = 0;
	s_rxAckReq = 0;
}

/* Готовий PDU -> головному циклу (ISR). fix = 1: CRC32 невалідний, спершу корекція (fix7). */
static void smsRxPublish(int total, uint8_t fix)
{
	s_rxPduLen = (uint16_t)total;
	s_rxPeer = s_rxSrc;
	s_rxPeerDst = s_rxDst;
	s_rxPeerGroup = s_rxGroup;
	s_rxPeerKeyId = s_rxKeyId;
	s_rxPeerEnc = s_rxHaveEnc;   /* decrypt if the ENC header was seen, else read cleartext */
	s_rxPeerAckReq = s_rxAckReq; /* чи винні ми квитанцію за це повідомлення */
	s_rxPeerFix = fix;
	s_rxReady = 1;          /* main loop will decrypt (or read cleartext) + store */
	SMS_DG(s_rxReadyMs = ticksGetMillis());
}

void dmrSmsRxBurst(int rxDataType, const uint8_t *p)
{
	if (rxDataType == DT_DATA_HEADER)
	{
		/* Response header (DPF=1): link-layer ACK від адресата нашого CONFIRMED SMS.
		 * Формат: [G|0x01][A][to:3][from:3][0x00][0x08][CRC16].
		 * Перевіряємо, що квитанція адресована нам і від нашого адресата. */
		if ((p[0] & 0x0F) == 0x01)
		{
			uint32_t to   = ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 8) | p[4];
			uint32_t from = ((uint32_t)p[5] << 16) | ((uint32_t)p[6] << 8) | p[7];
			SMS_DG(s_dgRespAll++);
			if (to == trxDMRID) { SMS_DG(s_dgRespForUs++); }
			if (to == trxDMRID && s_txPendingDst != 0 && from == s_txPendingDst)
			{
				SMS_DG(s_dgRespMatch++);
				s_txAcked = 1;
			}
			return;
		}
		if (p[0] == 0x4F && p[1] == 0x10 && (p[2] & 0x3F) == (0x51 & 0x3F))
		{
			/* Motorola ENC extended header: ALG/key/MI. It immediately precedes this
			 * message's data blocks, so restart block accumulation here — this prevents
			 * mixing leftover blocks from a previous (missed-terminator) retransmit. */
			s_rxKeyId = p[3];
			s_rxHaveEnc = 1;
			s_rxCount = 0;
			s_rxLen = 0;
		}
		else
		{
			/* Unconfirmed/UDT data header: start a fresh PDU */
			s_rxGroup = (p[0] & 0x80) ? 1 : 0;
			s_rxDst = ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 8) | p[4];
			s_rxSrc = ((uint32_t)p[5] << 16) | ((uint32_t)p[6] << 8) | p[7];
			uint8_t nblocks = (uint8_t)(p[8] & 0x7F);
			s_rxHdrBlocks = nblocks;                                        /* diag5: для «CRC32 не зійшовся» */
#if defined(ENABLE_SMS_DIAG)
			for (int i = 0; i < 12; i++) { s_curHdr[i] = p[i]; }           /* diag6: сирий заголовок */
			s_curHdrMs = ticksGetMillis();
			s_curHwOk = 0;
#endif
			s_rxExpBlocks = (uint8_t)((nblocks > 0) ? (nblocks - 1) : 0);  /* minus ENC header */
			s_rxCount = 0;
			s_rxLen = 0;
			s_rxHaveHeader = 1;
			s_rxHaveEnc = 0;
			/* CONFIRMED data (DPF=3) -> відправник чекає link-layer квитанцію. Біт A (0x40)
			 * НЕ вимагаємо навмисно: за ETSI сам CONFIRMED означає підтверджувану доставку,
			 * а в ефірі (BBD_0005) стокова слала 0x43, тобто A однаково стоїть. Якщо ж
			 * конкретна прошивка шле 0x03 -- краще відповісти, ніж мовчати (зайва квитанція
			 * нікому не шкодить, а її брак дає ретрансміти). Unconfirmed (DPF=2) і UDT -- ні.
			 * Реальний байт видно в діагностиці (s_ackLastHdr0). */
			s_rxAckReq = (((p[0] & 0x0F) == 0x03) ? 1 : 0);
			/* N(S) з CONFIRMED-заголовка (o9 біти 6-4) -> Status квитанції (o9 біти 2-0). */
			if (s_rxAckReq) { s_rxLastNS = (p[9] >> 4) & 7; }
			/* Діагностика: що НАСПРАВДІ прислала стокова (перші два байти заголовка). */
			SMS_DG(s_ackLastHdr0 = p[0]);
			SMS_DG(s_ackLastHdr1 = p[1]);
			if (s_rxAckReq) { SMS_DG(s_ackSeen++); }
		}
		return;
	}

	/* Блоки навантаження: rate-1/2 (12 байт) АБО rate-3/4 (18 байт -- саме так шле стокова).
	 * Пишемо прямо в s_rxPdu; тип блока задає довжину. Завершення -- за CRC32 усього PDU
	 * (самотермінувальне, не довіряємо лічильнику блоків із заголовка). */
	if (rxDataType == DT_RATE12_DATA || rxDataType == DT_RATE34_DATA)
	{
		if (!s_rxHaveHeader) { SMS_DG(s_dgBlkNoHdr++); return; }
		/* Не чіпаємо s_rxPdu, поки готовий PDU ще не забрав основний цикл (пишемо тепер
		 * прямо в s_rxPdu, тож інакше новий burst затер би те, що ще не прочитано). */
		if (s_rxReady) { SMS_DG(s_dgBlkBusy++); return; }

		/* rate-1/2 (unconfirmed): весь 12-байтний блок -- навантаження.
		 * rate-3/4 від стокової -- CONFIRMED data: 18-байтний блок = [2 байти DBSN+CRC9] +
		 * [16 байтів навантаження]. Беремо лише 16 байтів навантаження: перші 2 службові й НЕ
		 * входять у data-PDU/CRC32. Підтверджено дампом з ефіру (2026-09-05): так блоки
		 * складаються в чистий IPv4/UDP/TMS і CRC32 усього PDU сходиться (0x43bc6082). */
#if defined(ENABLE_SMS_DIAG)
		/* Знімок СИРОГО блока (до відкидання службових байтів) -- еталон для CRC9. */
		if (s_rawBlkCount < SMS_RAWBLK_MAX)
		{
			int raw = (rxDataType == DT_RATE34_DATA) ? 18 : 12;
			for (int i = 0; i < raw; i++) { s_rawBlk[s_rawBlkCount][i] = p[i]; }
			s_rawBlkLen[s_rawBlkCount] = (uint8_t)raw;
			s_rawBlkCount++;
		}
#endif

		const uint8_t *src = p;
		int blkLen = 12;
		if (rxDataType == DT_RATE34_DATA) { src = p + 2; blkLen = 16; }
		if ((int)s_rxLen + blkLen > (int)sizeof s_rxPdu) { SMS_DG(s_dgBlkOvf++); return; }   /* захист від переповнення */
		/* diag6: службові байти, час і HW-CRC блока -- для знімка, якщо PDU не складеться.
		 * DBSN (старші 7 бітів першого службового байта) у CONFIRMED rate-3/4 -- порядковий
		 * номер блока: 0,1,2... Збирач його НЕ перевіряє (кладе блоки в порядку прибуття),
		 * тож тут лише рахуємо розбіжності -- повтор або перестановка блока їх покаже. */
#if defined(ENABLE_SMS_DIAG)
		if (s_rxCount < SMS_SNAP_MAX)
		{
			s_curSvc[s_rxCount][0] = p[0];
			s_curSvc[s_rxCount][1] = p[1];
			s_curMs[s_rxCount] = (uint16_t)SAFE_MIN(ticksGetMillis() - s_curHdrMs, 65535u);
			if (s_lastHwOk) { s_curHwOk |= (uint8_t)(1u << s_rxCount); }
		}
		if ((rxDataType == DT_RATE34_DATA) && s_rxAckReq && ((p[0] >> 1) != (s_rxCount & 0x7F))) { s_dgDbsnBad++; }
#endif
		memcpy(s_rxPdu + s_rxLen, src, blkLen);
		s_rxLen = (uint16_t)(s_rxLen + blkLen);
		s_rxCount++;
		/* Скільки блоків даних обіцяв заголовок: nblocks мінус ENC-заголовок, якщо він був. */
		int expData = (int)s_rxHdrBlocks - (s_rxHaveEnc ? 1 : 0);
		if ((expData > 0) && ((int)s_rxCount > expData)) { SMS_DG(s_dgBlkExtra++); }

		/* Завершуємо, коли накопичене утворює CRC32-валідний data-PDU. Самотермінувально:
		 * змішування/обрив блоків просто не дасть валідний CRC32. Мінімум ~2 rate-1/2 блоки
		 * (24 Б). Гейт на s_rxHaveHeader (не s_rxHaveEnc), щоб і ЧИСТИЙ текст (без ENC-заголовка)
		 * теж збирався; тип шифрування несе s_rxHaveEnc, IPv4/UDP-перевірка в tick відкине не-SMS. */
		if (s_rxHaveHeader && (s_rxLen >= 24) && !s_rxReady)
		{
			int total = s_rxLen;
			uint32_t want = ((uint32_t)s_rxPdu[total - 4] << 24) | ((uint32_t)s_rxPdu[total - 3] << 16) |
					((uint32_t)s_rxPdu[total - 2] << 8) | (uint32_t)s_rxPdu[total - 1];
			uint32_t got = dmrSmsPduCrc32(s_rxPdu, total);
			if (got != want)
			{
				/* Ще не повний PDU -- копимо далі. Але якщо блоків уже рівно стільки, скільки
				 * в заголовку, -- PDU мав скластися: рахуємо як «CRC32 не зійшовся». */
				if ((expData > 0) && ((int)s_rxCount == expData))
				{
					SMS_DG(s_dgCrcFail++);
					if (rxDataType == DT_RATE34_DATA)
					{
						/* fix7: зібрано рівно під заголовок, а CRC32 не зійшовся. Трелліс-декодер
						 * чипа псує 1-2 сусідні трибіти (знімки #8/#12) -- віддаємо головному циклу
						 * на програмну корекцію (dmr_sms_fix.c). Знімок «Діагностики 4» робить він
						 * же, і лише якщо виправити не вдалося. */
						smsRxPublish(total, 1);
						dmrSmsRxReset();
					}
#if defined(ENABLE_SMS_DIAG)
					else
					{
						/* diag6: знімок цього PDU (сирі блоки = службові + навантаження з s_rxPdu). */
						smsSnapStore(s_rxPdu, (int)s_rxCount, 0, s_curSvc, s_curMs, s_curHwOk, s_curHdr,
						             want, got, s_dgCrcFail);
					}
#else
					(void)got;
#endif
				}
				return;
			}
			smsRxPublish(total, 0);
			SMS_DG(s_dgPduOk++);
#if defined(ENABLE_SMS_DIAG)
			s_diagPdu++;
			/* snapshot raw (still-encrypted) PDU for USB inspection (clamped to the
			 * snapshot buffer — the reported length must never exceed the bytes stored) */
			s_diagLastPduLen = (uint16_t)((total > (int)sizeof s_diagLastPdu) ? (int)sizeof s_diagLastPdu : total);
			s_diagLastKeyId = s_rxKeyId;
			s_diagLastExp = s_rxExpBlocks;
			s_diagLastPeer = s_rxSrc;
			for (int i = 0; i < total && i < (int)sizeof s_diagLastPdu; i++) { s_diagLastPdu[i] = s_rxPdu[i]; }
#endif
			dmrSmsRxReset();
		}
	}
}

/* Чи адресоване це повідомлення саме НАМ?
 *
 *   - приватне (group == 0): адресат має точно збігатися з нашим DMR ID;
 *   - групове: адресат = TG активного каналу, будь-який TG зі списку RX-груп цього каналу,
 *     або All Call. Це той самий критерій, за яким пропускається ГОЛОС
 *     (hrc6000CallAcceptFilter + currentRxGroupData), тож SMS і голос поводяться однаково.
 *
 * Адресат лежить у ВІДКРИТОМУ заголовку даних, тому перевірка робиться ДО розшифровки:
 * на чуже повідомлення не витрачається ані AES, ані блокуючий запис у флеш.
 *
 * NOT_IN_CODEPLUG_contactsTG[] уже містить розкриті номери TG (їх заповнює
 * codeplugRxGroupGetDataForIndex), тож звертань до флеша тут немає взагалі. */
static int smsIsForUs(uint32_t dst, int group)
{
	if (dst == 0) { return 0; }

	if (group == 0)
	{
		return (dst == trxDMRID);
	}

	if ((dst >= MIN_ALL_CALL_VALUE) && (dst <= MAX_ALL_CALL_VALUE)) { return 1; }

	/* trxTalkGroupOrPcId у старшому байті тримає тип виклику: 0x03 = приватний. Порівнювати
	 * ГРУПОВИЙ адресат з ним можна лише коли там справді TG, інакше рація, налаштована на
	 * приватний виклик 1234, приймала б групові повідомлення на TG 1234. */
	if ((((trxTalkGroupOrPcId >> 24) & 0xFF) != PC_CALL_FLAG) &&
			(dst == (trxTalkGroupOrPcId & 0x00FFFFFF)))
	{
		return 1;
	}

	for (int i = 0; i < currentRxGroupData.NOT_IN_CODEPLUG_numTGsInGroup; i++)
	{
		if (currentRxGroupData.NOT_IN_CODEPLUG_contactsTG[i] == dst) { return 1; }
	}
	return 0;
}

/* fix7: прийнятність виправленого PDU -- IPv4 header checksum + UDP checksum. Шифрований --
 * спершу розшифрувати копію (ключ із заголовка, потім усі завантажені, як і основний шлях). */
typedef struct
{
	uint8_t enc;
	uint8_t keyId;
} smsFixCtx_t;

static int smsFixVerify(const uint8_t *pdu, int len, void *ctx)
{
	const smsFixCtx_t *c = (const smsFixCtx_t *)ctx;
	if (!c->enc) { return dmrSmsPduIpUdpOk(pdu, len); }
	uint8_t tmp[384];
	char text[DMR_SMS_TEXT_MAX + 1];
	if (len > (int)sizeof tmp) { return 0; }
	for (int attempt = 0; attempt <= DMR_AES_MAX_KEYS; attempt++)
	{
		uint8_t k = (attempt == 0) ? c->keyId : (uint8_t)attempt;
		if ((k == 0) || (k >= DMR_AES_MAX_KEYS)) { continue; }
		memcpy(tmp, pdu, (size_t)len);
		if ((dmr_aes_sms_decrypt(k, tmp, len, text, sizeof text) > 0) && dmrSmsPduIpUdpOk(tmp, len)) { return 1; }
	}
	return 0;
}

void dmrSmsRxTick(void)
{
	dmrSmsTxPersistTick();   /* flush any deferred Sent-folder write once the TX has fully un-keyed */
	dmrSmsAckTick();         /* відключити квитанцію на вхідне CONFIRMED SMS, коли настав час */

#if defined(ENABLE_SMS_DIAG)
	/* Фактична затримка квитанції (fix3): перший burst квитанції пішов у чип -> від тиші в
	 * каналі до цього моменту. Старт старшої передачі (до постановки) не рахуємо; якщо за 3 с
	 * передача так і не почалась -- перестаємо чекати (видно в лічильниках «Дані»). */
	if (s_ackAwaitStart)
	{
		uint32_t st = dmrDataTxLastStartMs();
		if ((int32_t)(st - s_ackLoadMs) >= 0)
		{
			uint32_t d = st - s_ackSilenceMs;
			s_ackRealDelayMs = (uint16_t)((d > 65535u) ? 65535u : d);
			/* Етапи (ui1/fix4). Мітки ключування/старту беремо лише якщо вони з ЦІЄЇ передачі
			 * (не раніші за постановку в чергу), інакше 0. */
			uint32_t kt = dmrDataTxLastKeyMs();
			uint32_t ss = dmrDataTxLastSlotStartMs();
			if ((int32_t)(kt - s_ackLoadMs) < 0) { kt = s_ackLoadMs; }
			if ((int32_t)(ss - kt) < 0)          { ss = kt; }
			if ((int32_t)(st - ss) < 0)          { ss = st; }
			s_ackStgQ = (uint16_t)SAFE_MIN(s_ackLoadMs - s_ackSilenceMs, 65535u);
			s_ackStgK = (uint16_t)SAFE_MIN(kt - s_ackLoadMs, 65535u);
			s_ackStgS = (uint16_t)SAFE_MIN(ss - kt, 65535u);
			s_ackStgB = (uint16_t)SAFE_MIN(st - ss, 65535u);
			s_ackAwaitStart = 0;
		}
		else if ((int32_t)(ticksGetMillis() - s_ackLoadMs) > 3000)
		{
			s_ackAwaitStart = 0;
		}
	}
#endif

	/* TX-ACK: стокова TYT отримала наш CONFIRMED SMS і відповіла «01 40».
	 * Позначаємо найновіше надіслане як DMR_SMS_FLAG_DELIVERED і показуємо банер. */
	if (dmrSmsTxAcked())
	{
		store_ensure();
		int o = off_for(1, 0);   /* 1 = outgoing, 0 = newest */
		if (o >= 0 && !(s_store.data[o] & DMR_SMS_FLAG_DELIVERED))
		{
			s_store.data[o] |= DMR_SMS_FLAG_DELIVERED;
			store_save();
		}
		displayLightTrigger(false);
		/* ui1 (2026-10-04): велика зелена галочка без тексту замість «SMS: доставлено»
		 * (текст обрізався, рамка просвічувала). ~2,5 с, звук -- як і був. */
		uiNotificationShow(NOTIFICATION_TYPE_SMS_ACKED, NOTIFICATION_ID_SMS_ACKED, 2500, NULL, true);
		soundSetMelody(MELODY_ACK_BEEP);
	}

	if (!s_rxReady) { return; }

	/* snapshot the FULL pdu (incl. pad+crc32), then release the ISR buffer */
	uint8_t pdu[384];
	int pduLen = s_rxPduLen;
	uint32_t peer = s_rxPeer;
	uint32_t dst = s_rxPeerDst;
	uint8_t  group = s_rxPeerGroup;
	uint8_t  keyId = s_rxPeerKeyId;
	uint8_t  enc = s_rxPeerEnc;
	uint8_t  ackReq = s_rxPeerAckReq;
	/* fix7: PDU на корекцію -- забрати й службові байти/час/заголовок для знімка, поки ISR
	 * не почав наступний PDU (після s_rxReady = 0 він може). */
	uint8_t  fixReq = s_rxPeerFix;
#if defined(ENABLE_SMS_DIAG)
	uint8_t  fxSvc[SMS_SNAP_MAX][2];
	uint16_t fxMs[SMS_SNAP_MAX];
	uint8_t  fxHdr[12];
	uint8_t  fxHw = 0;
	uint16_t fxSeq = 0;
	if (fixReq)
	{
		memcpy(fxSvc, s_curSvc, sizeof fxSvc);
		memcpy(fxMs, s_curMs, sizeof fxMs);
		memcpy(fxHdr, s_curHdr, sizeof fxHdr);
		fxHw = s_curHwOk;
		fxSeq = s_dgCrcFail;
	}
#endif
	if (pduLen > (int)sizeof pdu) { pduLen = (int)sizeof pdu; }
	memcpy(pdu, s_rxPdu, pduLen);
	s_rxReady = 0;
#if defined(ENABLE_SMS_DIAG)
	{
		uint32_t late = ticksGetMillis() - s_rxReadyMs;   /* diag5: як довго PDU чекав на головний цикл */
		if (late > s_dgPickMaxMs) { s_dgPickMaxMs = (uint16_t)((late > 65535u) ? 65535u : late); }
	}
#endif

	if (pduLen < 32) { SMS_DG(s_dgTickBad++); return; }   /* whole PDU is passed; decrypt derives the enc len */

	/* Адресний фільтр. Раніше його не було зовсім: приймалося ВСЕ, що пролізло крізь
	 * частоту/таймслот/кольоровий код і відкрилося будь-яким нашим ключем -- зокрема приватні
	 * повідомлення між іншими рацями. Наслідки були не лише "етичні": чужий трафік витісняв
	 * власні повідомлення з 1342-байтового сховища, кожне з них тягло блокуючий запис у флеш,
	 * банер і звук, а на екрані видно лише ВІДПРАВНИКА -- тобто чужий наказ виглядав як свій.
	 *
	 * Тепер за замовчуванням приймається лише адресоване нам. Монітор (Повідомлення >
	 * "Монітор: увімк") лишає стару поведінку для навмисного прослуховування -- але тоді
	 * чуже позначається DMR_SMS_FLAG_FOREIGN і показується окремо. */
	int forUs = smsIsForUs(dst, group);
	if ((forUs == 0) && (settingsIsOptionBitSet(BIT_SMS_MONITOR_ALL) == false))
	{
		SMS_DG(s_dgTickNotUs++);
		return;
	}

	/* Validate the data-PDU CRC32 over [ct+pad] before trusting the bytes. This rejects
	 * reassemblies that mixed blocks across retransmits (a missed burst/header) — without it
	 * a corrupted PDU decrypts to garbage and, worse, can store a junk message. */
	{
		uint32_t want = ((uint32_t)pdu[pduLen - 4] << 24) | ((uint32_t)pdu[pduLen - 3] << 16) |
				((uint32_t)pdu[pduLen - 2] << 8) | (uint32_t)pdu[pduLen - 1];
		uint32_t got = dmrSmsPduCrc32(pdu, pduLen);
		if (got != want)
		{
			if (!fixReq) { SMS_DG(s_dgTickBad++); return; }   /* corrupted reassembly -> drop */
			/* fix7: програмна корекція 1-2 сусідніх трибітів (див. dmr_sms_fix.h). Приймаємо,
			 * лише якщо CRC32 + IPv4 + UDP сходяться і кандидат РІВНО один. Далі -- як звичайний
			 * PDU (квитанція, дедуп, збереження). Невдача -- знімок на «Діагностику 4». */
#if defined(ENABLE_SMS_DIAG)
			uint32_t t0 = ticksGetMillis();
#endif
			smsFixCtx_t vc;
			vc.enc = enc;
			vc.keyId = keyId;
			int r = dmrSmsPduFix34(pdu, pduLen, enc ? 0 : 1, smsFixVerify, &vc, NULL);
#if defined(ENABLE_SMS_DIAG)
			uint32_t dt = ticksGetMillis() - t0;
			s_dgFixLastMs = (uint16_t)SAFE_MIN(dt, 65535u);
			if (s_dgFixLastMs > s_dgFixMaxMs) { s_dgFixMaxMs = s_dgFixLastMs; }
#endif
			if (r != DMR_SMS_FIX_OK)
			{
				if (r == DMR_SMS_FIX_AMBIG) { SMS_DG(s_dgFixAmb++); }
				else                        { SMS_DG(s_dgFixNone++); }
#if defined(ENABLE_SMS_DIAG)
				smsSnapStore(pdu, pduLen / 16, 1, (const uint8_t (*)[2])fxSvc, fxMs, fxHw, fxHdr, want, got, fxSeq);
#endif
				return;
			}
			SMS_DG(s_dgFixOk++);
		}
	}

	/* Дедуплікація (Task #34): той самий PDU (відправник + IP-ID + TMS-seq) в межах 30 с -> пропустити.
	 * IP-ID: pdu[4..5] (IPv4 Identification); TMS-seq: pdu[32] (20B IPv4 + 8B UDP + 4B TMS prefix).
	 * Квитанцію шлемо НЕЗАЛЕЖНО від дублікату -- відправник чекає. */
	int isDuplicate = 0;
	if (pduLen >= 33)
	{
		uint16_t ipId   = (uint16_t)((pdu[4] << 8) | pdu[5]);
		uint8_t  tmsSeq = pdu[32];
		uint32_t now32  = (uint32_t)ticksGetMillis();
		if (peer == s_dedupPeer && ipId == s_dedupIpId && tmsSeq == s_dedupTmsSeq &&
		    (now32 - s_dedupTs) < 30000U)
		{
			isDuplicate = 1;
		}
		else
		{
			s_dedupPeer   = peer;
			s_dedupIpId   = ipId;
			s_dedupTmsSeq = tmsSeq;
			s_dedupTs     = now32;
		}
	}

	/* Link-layer квитанція: блоки прийнято цілими (CRC32 зійшовся) і повідомлення адресоване
	 * саме нам приватно, а відправник просив підтвердити (CONFIRMED+A) -> шлемо Response header.
	 * Робимо це ДО розшифровки: квитанція -- про доставку кадрів, а не про те, чи ми прочитали
	 * текст (стокова так само квитує ще до показу). Групові й «моніторні»/чужі не квитуємо. */
	SMS_DG(s_ackLastGroup = group);
	SMS_DG(s_ackLastForUs = (uint8_t)(forUs ? 1 : 0));
	/* Квитанцію ставимо в чергу, а віддає її dmrSmsAckTick() -- щойно канал ЗАМОВКНЕ.
	 * Два ефірні заміри задали це вікно з обох боків:
	 *  - rev 5 (BBD_0006): форма квитанції правильна байт-у-байт, але вийшла через 366 мс
	 *    по кінці передачі проти ~80 мс у стокової -- ПІЗНО, вікно закрите. Левову частку
	 *    тих 366 мс з'їдав store_add() нижче: блокуючий erase+write SPI-флеша тримав
	 *    головний цикл, і відкладена квитанція не могла піти.
	 *  - rev 6: віддавали негайно по CRC32 -- але PDU збирається на ОСТАННЬОМУ блоці даних,
	 *    після якого відправник ще шле термінатор. Тобто ми лізли в ефір, поки він передає
	 *    (отже глухий) -- РАНО.
	 * Тому: чекаємо тиші SMS_ACK_QUIET_MS, ключуємо через SMS_ACK_KEY_DELAY_MS (разом
	 * ~45-60 мс після кінця передачі, як у стокової), а блокуючий запис у флеш відкладено
	 * до моменту, коли квитанція вже пішла -- інакше він знову з'їсть усе вікно. */
	int ackedNow = 0;
	if (ackReq && forUs && !group)
	{
		queueSmsAck(peer);
		ackedNow = 1;   /* квитанція винна -> запис у флеш відкладаємо, щоб не тримав цикл */
	}

	char text[DMR_SMS_TEXT_MAX + 1];
	int got = -1;

	if (enc)
	{
		/* Encrypted: try the signalled key id first, then every loaded key (decrypt is
		 * destructive, so each attempt works on a fresh copy of the ciphertext). */
		uint8_t tmp[384];
		for (int attempt = 0; attempt <= DMR_AES_MAX_KEYS && got < 0; attempt++)
		{
			uint8_t k = (attempt == 0) ? keyId : (uint8_t)attempt;
			if (k == 0 || k >= DMR_AES_MAX_KEYS) { continue; }
			memcpy(tmp, pdu, pduLen);
			int r = dmr_aes_sms_decrypt(k, tmp, pduLen, text, sizeof text);
			if (r > 0) { got = r; }
		}
	}
	else
	{
		/* Cleartext SMS: the reassembled PDU IS the plaintext IPv4/UDP/TMS packet. */
		got = dmr_sms_text_from_plaintext(pdu, pduLen, text, sizeof text);
	}
	if (got <= 0) { return; }   /* wrong/no key, not IPv4/UDP, or not an SMS */

	/* Дублікат (Task #34): той самий PDU вже збережений і показаний -- не турбуємо ще раз. */
	if (isDuplicate) { return; }

	{
		uint8_t flags = (uint8_t)(DMR_SMS_FLAG_UNREAD | (group ? DMR_SMS_FLAG_GROUP : 0) |
				(forUs ? 0 : DMR_SMS_FLAG_FOREIGN));
		if (ackedNow)
		{
			/* Квитанція ЗАРАЗ у польоті. store_add() -- блокуючий erase+write SPI-флеша на
			 * сотні мс; якщо зробити його тут, він з'їсть саме те вікно, заради якого ми
			 * поспішали (і взагалі блокуючий флеш у вікні ключування -- крихко, та сама
			 * причина, що й для відкладеного запису теки «Надіслані»). Відкладаємо до
			 * завершення передачі -- зливає dmrSmsInboxPersistTick() з головного циклу. */
			/* Якщо попереднє відкладене ще не зляглось -- запишемо його ЗАРАЗ, інакше воно
			 * просто загубиться (слот один). Той самий запобіжник, що й для «Надісланих». */
			if (s_pendInbox)
			{
				store_add(s_pendInboxFlags, s_pendInboxPeer, s_pendInboxText, s_pendInboxLen);
				s_pendInbox = 0;
			}
			s_pendInbox = 1;
			s_pendInboxFlags = flags;
			s_pendInboxPeer = peer;
			s_pendInboxLen = got;
			memcpy(s_pendInboxText, text, (size_t)got);
			s_pendInboxText[got] = 0;
		}
		else
		{
			store_add(flags, peer, text, got);
		}
	}
	SMS_DG(s_diagMsg++);

	/* notify the user: visual banner (existing) + audible alert (new — раніше цей шлях був
	 * німим, і вхідне SMS можна було пропустити, якщо не дивитись на екран саме в цю мить).
	 * Перехоплене в моніторі позначається просто в тексті банера: свій наказ і чужий мають
	 * різнитися вже в ту секунду, коли банер вискочив, а не лише в списку. */
	char note[DMR_SMS_TEXT_MAX + 12];
	snprintf(note, sizeof note, forUs ? "SMS: %s" : "SMS>: %s", text);
	/* Будимо екран: без цього банер малювався б у темряву й повідомлення так само лишалось
	 * непоміченим -- рація зазвичай лежить із погашеною підсвіткою. displayLightTrigger
	 * шанує налаштування підсвітки користувача (режим/яскравість), ми лише запускаємо її. */
	displayLightTrigger(false);
	/* На весь екран і до RED: повідомлення могло прийти, коли рація лежала в розвантажці. */
	uiNotificationShow(NOTIFICATION_TYPE_SMS, NOTIFICATION_ID_SMS, 60000, note, true);
	soundSetMelody(MELODY_SMS_RECEIVED_BEEP);
}

/* Clear all CCM runtime state to known values (see the forward decl up top). */
static void runtimeReset(void)
{
	s_cfgLoaded = 0;                 /* force the MSGC config to (re)load */
#if defined(ENABLE_SMS_DIAG)
	s_diagData = s_diagHdrOk = s_diagHdrBad = s_diagBlkOk = s_diagBlkBad = 0;
	s_diagPdu = s_diagMsg = 0;
	for (int i = 0; i < 16; i++) { s_diagType[i] = 0; }
#endif
	s_rxReady = 0;                   /* don't process stray garbage as a PDU */
	s_ackPending = 0;                /* не тягнути квитанцію через зміну каналу */
	s_pendInbox = 0;                 /* і відкладений запис вхідного теж */
	s_txAcked = 0;                   /* скидаємо TX-ACK стан (CCM -- не .bss, не auto-zero) */
	s_txPendingDst = 0;
	s_txNS = 0; s_txNSSent = 0;     /* N(S) лічильник TX (Task #32) */
	s_rxLastNS = 0;                  /* N(S) з останнього вхідного CONFIRMED (Task #33) */
	s_dedupPeer = 0; s_dedupIpId = 0; s_dedupTmsSeq = 0; s_dedupTs = 0;  /* деdup (Task #34) */
	SMS_DG(dmrSmsDiagScreenReset());   /* лічильники екрана «Діагностика» (CCM, не .bss) */
	s_rxPeerFix = 0;
#if defined(ENABLE_SMS_DIAG)
	/* Перемикачі екрана «Діагностика» -- типові значення при старті (fix3), не зберігаються. */
	s_dgFastEnd    = DMR_SMS_DEFAULT_FAST_END;
	s_dgRxBypass   = DMR_SMS_DEFAULT_RX_BYPASS;
	s_dgAckTerm    = DMR_SMS_DEFAULT_ACK_TERM;
	s_ackPreambles = DMR_SMS_DEFAULT_ACK_PREAMBLES;
	s_ackTargetMs  = DMR_SMS_DEFAULT_ACK_PAUSE_MS;   /* перемикач «Квит. пауза» 20/50/80 */
	s_ackAwaitStart = 0;
	s_ackSilenceMs = 0; s_ackLoadMs = 0;
#endif
	dmrSmsRxReset();                 /* clear the burst accumulator */
}

#endif /* ENABLE_DMR_DATA && ENABLE_AES */
