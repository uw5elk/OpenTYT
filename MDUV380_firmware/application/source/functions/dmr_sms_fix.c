/*
 * dmr_sms_fix.c -- програмна корекція 1-2 сусідніх трибітів у вхідних rate-3/4 PDU (fix7).
 * Модель, правила прийняття і режим «якір у заголовку IPv4» -- див. dmr_sms_fix.h.
 * Порожній модуль без ENABLE_AES + ENABLE_DMR_DATA (типова збірка не змінюється).
 *
 * ЛІНІЙНІСТЬ CRC32. dmrSmsPduCrc32() -- зсувний регістр з init 0 і без фінального XOR, байти
 * йдуть парами навпаки (pdu[1], pdu[0], pdu[3], ...), наприкінці -- перестановка байтів
 * результату. Отже CRC(d ^ e) = CRC(d) ^ CRC(e). Біт, поданий на кроці j (з nbits), додає до
 * регістра POLY, а далі проходить ще nbits-1-j кроків з нульовим входом:
 *     V(j) = L^(nbits-1-j)(POLY),  L(c) = (c << 1) ^ (старший біт ? POLY : 0).
 * V(j-1) = L(V(j)), а V(j+1) = L^-1(V(j)) -- L оборотний, бо POLY непарний. Байт PDU p
 * (не поле CRC) біт m від старшого -- це крок j = 8*(p ^ 1) + m. Біт поля CRC просто
 * перевертає відповідний біт «очікуваного» значення. Синдром S = CRC(pdu) ^ поле; кандидат
 * e підходить, якщо XOR його внесків == S. На кандидата -- кілька XOR, без перерахунку PDU.
 */
#include "functions/dmr_sms_fix.h"

#if defined(ENABLE_DMR_DATA) && defined(ENABLE_AES)

#include "functions/dmr_sms_pdu.h"
#include <string.h>

#define FIX_POLY      0x04C11DB7u
#define FIX_BLK_PAY   16    /* байтів навантаження rate-3/4 блока в PDU */
#define FIX_TRI_N     48    /* трибітів у сирому 18-байтному блоці */
#define FIX_TRI_FIRST 5     /* трибіти 0..4 -- лише службові біти 0..14 */
#define FIX_IP_HDR    20

static uint32_t fixL(uint32_t c)    { return (c & 0x80000000u) ? ((c << 1) ^ FIX_POLY) : (c << 1); }
static uint32_t fixLinv(uint32_t c) { return (c & 1u) ? (((c ^ FIX_POLY) >> 1) | 0x80000000u) : (c >> 1); }
static uint32_t fixBrev(uint32_t c)
{
	return ((c & 0xFFu) << 24) | ((c & 0xFF00u) << 8) | ((c >> 8) & 0xFF00u) | ((c >> 24) & 0xFFu);
}

static uint32_t fixWant(const uint8_t *pdu, int len)
{
	return ((uint32_t)pdu[len - 4] << 24) | ((uint32_t)pdu[len - 3] << 16) |
			((uint32_t)pdu[len - 2] << 8) | (uint32_t)pdu[len - 1];
}

/* V(j0) для старшого біта кожного з 16 байтів навантаження блока blk (поле CRC -- 0).
 * Прохід від кінця PDU: ~len*8 кроків L(), дешево. */
static void fixBlockV(int len, int blk, uint32_t vm[FIX_BLK_PAY])
{
	int nbits = len * 8 - 32;
	int lo = 128 * blk;
	int hi = lo + 128;
	uint32_t c = FIX_POLY;   /* V(nbits-1) */
	memset(vm, 0, FIX_BLK_PAY * sizeof vm[0]);
	for (int j = nbits - 1; j >= lo; j--)
	{
		if ((j < hi) && ((j & 7) == 0))
		{
			int p = (j >> 3) ^ 1;
			vm[p - FIX_BLK_PAY * blk] = c;
		}
		c = fixL(c);
	}
}

/* Внесок у синдром сирого біта r (0..143) блока blk. Службові біти -- 0. */
static uint32_t fixBitEff(int len, int blk, const uint32_t vm[FIX_BLK_PAY], int r)
{
	int q = r >> 3;
	int m = r & 7;
	if (q < 2) { return 0; }
	int p = FIX_BLK_PAY * blk + q - 2;
	if (p >= len - 4)
	{
		int f = p - (len - 4);
		return 1u << (8 * (3 - f) + (7 - m));
	}
	uint32_t c = vm[q - 2];
	for (int i = 0; i < m; i++) { c = fixLinv(c); }
	return fixBrev(c);
}

/* Таблиця внесків трибіта t для всіх 8 значень (e[0] = 0). Старший біт значення -- біт 3t. */
static void fixTriEff(int len, int blk, const uint32_t vm[FIX_BLK_PAY], int t, uint32_t e[8])
{
	uint32_t b0 = fixBitEff(len, blk, vm, 3 * t);
	uint32_t b1 = fixBitEff(len, blk, vm, 3 * t + 1);
	uint32_t b2 = fixBitEff(len, blk, vm, 3 * t + 2);
	for (int v = 0; v < 8; v++)
	{
		e[v] = ((v & 4) ? b0 : 0) ^ ((v & 2) ? b1 : 0) ^ ((v & 1) ? b2 : 0);
	}
}

/* Трибіт 5 містить службовий біт 15 (старший біт значення): беремо лише значення без нього,
 * інакше та сама зміна PDU рахувалась би двічі. */
static int fixValFirst(int t) { (void)t; return 1; }
static int fixValLast(int t)  { return (t == FIX_TRI_FIRST) ? 3 : 7; }

/* XOR-ом накласти зміну на PDU (повторний виклик -- скасувати). */
static void fixApply(uint8_t *pdu, int len, const dmrSmsFixErr_t *e)
{
	uint16_t bits = e->val;   /* width 2: 6 бітів (v1 << 3 | v2), width 1: 3 біти */
	int nb = 3 * e->width;
	for (int i = 0; i < nb; i++)
	{
		if (((bits >> (nb - 1 - i)) & 1) == 0) { continue; }
		int r = 3 * e->tri + i;
		int q = r >> 3;
		if (q < 2) { continue; }
		int p = FIX_BLK_PAY * e->blk + q - 2;
		if (p < len) { pdu[p] ^= (uint8_t)(0x80u >> (r & 7)); }
	}
}

static uint32_t fixOnesSum(const uint8_t *b, int n, uint32_t s)
{
	for (int i = 0; i < n; i += 2)
	{
		s += ((uint32_t)b[i] << 8) | ((i + 1 < n) ? b[i + 1] : 0u);
	}
	return s;
}

static uint16_t fixFold(uint32_t s)
{
	while (s >> 16) { s = (s & 0xFFFFu) + (s >> 16); }
	return (uint16_t)s;
}

int dmrSmsPduIpUdpOk(const uint8_t *p, int len)
{
	if (len < FIX_IP_HDR + 8) { return 0; }
	if ((p[0] >> 4) != 4) { return 0; }
	int ihl = (p[0] & 0x0F) * 4;
	if ((ihl < FIX_IP_HDR) || (ihl + 8 > len)) { return 0; }
	if (fixFold(fixOnesSum(p, ihl, 0)) != 0xFFFFu) { return 0; }
	if (p[9] != 17) { return 0; }
	int tot = ((int)p[2] << 8) | p[3];
	if ((tot < ihl + 8) || (tot > len)) { return 0; }
	const uint8_t *u = p + ihl;
	int ulen = ((int)u[4] << 8) | u[5];
	if ((ulen < 8) || (ihl + ulen > tot)) { return 0; }
	if ((u[6] == 0) && (u[7] == 0)) { return 1; }   /* UDP checksum не використано */
	uint32_t s = fixOnesSum(p + 12, 8, 0) + 17u + (uint32_t)ulen;   /* псевдозаголовок */
	s = fixOnesSum(u, ulen, s);
	return (fixFold(s) == 0xFFFFu) ? 1 : 0;
}

/* ============================ пошук ===================================== */
typedef struct
{
	dmrSmsFixErr_t e[2];
	uint8_t        n;
} fixCand_t;

typedef struct
{
	uint32_t       tgt[DMR_SMS_FIX_ANCH_MAX + 1];   /* синдром, який має дати кандидат */
	int8_t         anch[DMR_SMS_FIX_ANCH_MAX + 1];  /* -1 -- без якоря, інакше індекс якоря */
	int            ntgt;
	dmrSmsFixErr_t anchErr[DMR_SMS_FIX_ANCH_MAX];
	fixCand_t      match[DMR_SMS_FIX_MATCH_MAX];
	int            nmatch;                          /* може перевищити DMR_SMS_FIX_MATCH_MAX */
	uint32_t       tested;
	uint32_t       bloom[8];                        /* біт (tgt & 0xFF): швидке «точно не ціль» */
} fixCtx_t;

static void fixAddTarget(fixCtx_t *c, uint32_t tgt, int8_t anch)
{
	c->tgt[c->ntgt] = tgt;
	c->anch[c->ntgt] = anch;
	c->ntgt++;
	c->bloom[(tgt >> 5) & 7] |= 1u << (tgt & 31);
}

static void fixNoteMatch(fixCtx_t *c, int k, const dmrSmsFixErr_t *e)
{
	if (c->nmatch < DMR_SMS_FIX_MATCH_MAX)
	{
		fixCand_t *m = &c->match[c->nmatch];
		m->n = 0;
		if (c->anch[k] >= 0) { m->e[m->n++] = c->anchErr[(int)c->anch[k]]; }
		if (e) { m->e[m->n++] = *e; }
	}
	c->nmatch++;
}

/* Звірити внесок кандидата з усіма цілями (крім тих, чий якір -- у цьому ж блоці). */
static inline void fixCheck(fixCtx_t *c, uint32_t eff, const dmrSmsFixErr_t *e)
{
	c->tested++;
	if ((c->bloom[(eff >> 5) & 7] & (1u << (eff & 31))) == 0) { return; }
	for (int k = 0; k < c->ntgt; k++)
	{
		if (eff != c->tgt[k]) { continue; }
		if ((c->anch[k] >= 0) && (c->anchErr[(int)c->anch[k]].blk == e->blk)) { continue; }
		fixNoteMatch(c, k, e);
	}
}

/* Усі кандидати одного блока: одиночний трибіт і пара сусідніх ненульових. */
static void fixSearchBlock(fixCtx_t *c, int len, int blk)
{
	uint32_t vm[FIX_BLK_PAY];
	uint32_t prev[8], cur[8];
	dmrSmsFixErr_t e;
	fixBlockV(len, blk, vm);
	e.blk = (uint8_t)blk;
	for (int t = FIX_TRI_FIRST; t < FIX_TRI_N; t++)
	{
		fixTriEff(len, blk, vm, t, cur);
		e.width = 1;
		e.tri = (uint8_t)t;
		for (int v = fixValFirst(t); v <= fixValLast(t); v++)
		{
			e.val = (uint8_t)v;
			fixCheck(c, cur[v], &e);
		}
		if (t > FIX_TRI_FIRST)
		{
			e.width = 2;
			e.tri = (uint8_t)(t - 1);
			for (int v1 = fixValFirst(t - 1); v1 <= fixValLast(t - 1); v1++)
			{
				for (int v2 = 1; v2 <= 7; v2++)
				{
					e.val = (uint8_t)((v1 << 3) | v2);
					fixCheck(c, prev[v1] ^ cur[v2], &e);
				}
			}
		}
		memcpy(prev, cur, sizeof prev);
	}
}

/* Внесок трибіта t блока blk у суму заголовка IPv4 (за модулем 0xFFFF) для всіх 8 значень.
 * Біт 0->1 додає свою вагу W, 1->0 віднімає; W = 2^(15 - позиція біта в 16-бітному слові).
 * Біти поза першими 20 Б і службові -- 0. */
static void fixTriSum(const uint8_t *pdu, int blk, int t, uint32_t d[8])
{
	uint32_t b[3];
	for (int i = 0; i < 3; i++)
	{
		int r = 3 * t + i;
		int q = r >> 3;
		int m = r & 7;
		int p = FIX_BLK_PAY * blk + q - 2;
		b[i] = 0;
		if ((q < 2) || (p >= FIX_IP_HDR)) { continue; }
		uint32_t w = 1u << (15 - ((p & 1) * 8 + m));
		b[i] = (pdu[p] & (0x80u >> m)) ? (0xFFFFu - w) : w;
	}
	for (int v = 0; v < 8; v++)
	{
		uint32_t x = ((v & 4) ? b[0] : 0) + ((v & 2) ? b[1] : 0) + ((v & 1) ? b[2] : 0);
		d[v] = x % 0xFFFFu;
	}
}

/* Режим «якір»: кандидати в межах заголовка IPv4 (блок 0 і перші 4 Б блока 1), після яких
 * сума заголовка стає валідною (сума слів = 0 за модулем 0xFFFF; рахуємо прирости, без
 * перерахунку). Повертає кількість якорів (може бути більше ANCH_MAX -- тоді не всі записані). */
static int fixFindAnchors(fixCtx_t *c, const uint8_t *pdu, int len, uint32_t S)
{
	int na = 0;
	uint32_t hsum = fixOnesSum(pdu, FIX_IP_HDR, 0) % 0xFFFFu;
	uint32_t need = (0xFFFFu - hsum) % 0xFFFFu;   /* потрібний приріст суми */
	for (int blk = 0; (blk < 2) && (blk < len / FIX_BLK_PAY); blk++)
	{
		uint32_t vm[FIX_BLK_PAY];
		uint32_t prev[8], cur[8], dprev[8], dcur[8];
		dmrSmsFixErr_t e;
		fixBlockV(len, blk, vm);
		e.blk = (uint8_t)blk;
		/* блок 1: трибіти, що зачіпають його байти навантаження 0..3 (сирі біти 16..47) */
		int tmax = (blk == 0) ? (FIX_TRI_N - 1) : 16;
		for (int t = FIX_TRI_FIRST; t <= tmax; t++)
		{
			fixTriSum(pdu, blk, t, dcur);
			int haveCrc = 0;
			for (int w = 1; w <= 2; w++)
			{
				if ((w == 2) && (t == FIX_TRI_FIRST)) { continue; }
				if ((w == 1) && (blk == 1) && (t > 15)) { continue; }   /* трибіт 16 -- поза заголовком */
				int t0 = (w == 1) ? t : t - 1;
				for (int v1 = fixValFirst(t0); v1 <= fixValLast(t0); v1++)
				{
					for (int v2 = (w == 1) ? 0 : 1; v2 <= ((w == 1) ? 0 : 7); v2++)
					{
						c->tested++;
						uint32_t ds = (w == 1) ? dcur[v1] : (dprev[v1] + dcur[v2]);
						if (ds >= 0xFFFFu) { ds -= 0xFFFFu; }
						if (ds != need) { continue; }
						if (!haveCrc) { fixTriEff(len, blk, vm, t, cur); haveCrc = 1; }
						e.width = (uint8_t)w;
						e.tri = (uint8_t)t0;
						e.val = (uint8_t)((w == 1) ? v1 : ((v1 << 3) | v2));
						if (na < DMR_SMS_FIX_ANCH_MAX)
						{
							uint32_t eff = (w == 1) ? cur[v1] : (prev[v1] ^ cur[v2]);
							c->anchErr[na] = e;
							fixAddTarget(c, S ^ eff, (int8_t)na);
						}
						na++;
					}
				}
			}
			/* CRC-внески попереднього трибіта потрібні для пар -- рахуємо завжди (дешево). */
			if (!haveCrc) { fixTriEff(len, blk, vm, t, cur); }
			memcpy(prev, cur, sizeof prev);
			memcpy(dprev, dcur, sizeof dprev);
		}
	}
	return na;
}

int dmrSmsPduFix34(uint8_t *pdu, int len, int plain, dmrSmsFixVerify_t verify, void *ctx,
                   dmrSmsFixInfo_t *info)
{
	fixCtx_t c;
	dmrSmsFixInfo_t dummy;
	if (info == NULL) { info = &dummy; }
	memset(info, 0, sizeof *info);
	memset(&c, 0, sizeof c);
	if ((len < 2 * FIX_BLK_PAY) || ((len % FIX_BLK_PAY) != 0)) { return DMR_SMS_FIX_NONE; }

	uint32_t want = fixWant(pdu, len);
	uint32_t S = dmrSmsPduCrc32(pdu, len) ^ want;
	if (S == 0) { return DMR_SMS_FIX_NONE; }   /* і так валідний -- виправляти нічого */

	int nblk = len / FIX_BLK_PAY;
	int anchored = plain && (fixFold(fixOnesSum(pdu, FIX_IP_HDR, 0)) != 0xFFFFu);
	if (anchored)
	{
		int na = fixFindAnchors(&c, pdu, len, S);
		info->anchored = 1;
		info->anchors = (uint8_t)((na > 255) ? 255 : na);
		/* Якорів більше, ніж уміщаємо, -- справжній міг не потрапити: чесно «нема». */
		if (na > DMR_SMS_FIX_ANCH_MAX) { info->tested = c.tested; return DMR_SMS_FIX_NONE; }
		/* якір сам по собі вже дає валідний CRC32 -- одна помилка в заголовку */
		for (int k = 0; k < c.ntgt; k++)
		{
			if (c.tgt[k] == 0) { fixNoteMatch(&c, k, NULL); }
		}
	}
	else
	{
		fixAddTarget(&c, S, -1);
	}
	if (c.ntgt > 0)
	{
		for (int b = 0; b < nblk; b++) { fixSearchBlock(&c, len, b); }
	}
	info->tested = c.tested;
	info->crcMatches = (uint8_t)((c.nmatch > 255) ? 255 : c.nmatch);

	/* Перевірка кожного збігу: CRC32 повністю і verify() (IPv4/UDP). */
	int good = -1, ngood = 0;
	int nm = (c.nmatch < DMR_SMS_FIX_MATCH_MAX) ? c.nmatch : DMR_SMS_FIX_MATCH_MAX;
	for (int i = 0; i < nm; i++)
	{
		fixCand_t *m = &c.match[i];
		for (int k = 0; k < m->n; k++) { fixApply(pdu, len, &m->e[k]); }
		int ok = (dmrSmsPduCrc32(pdu, len) == fixWant(pdu, len)) && ((verify == NULL) || verify(pdu, len, ctx));
		for (int k = 0; k < m->n; k++) { fixApply(pdu, len, &m->e[k]); }
		if (ok) { ngood++; if (good < 0) { good = i; } }
	}
	info->verified = (uint8_t)ngood;
	/* Збігів більше, ніж перевірено, -- чесно «неоднозначно». */
	if ((ngood > 1) || ((ngood >= 1) && (c.nmatch > DMR_SMS_FIX_MATCH_MAX))) { return DMR_SMS_FIX_AMBIG; }
	if (ngood == 0) { return DMR_SMS_FIX_NONE; }

	fixCand_t *m = &c.match[good];
	for (int k = 0; k < m->n; k++) { fixApply(pdu, len, &m->e[k]); info->err[k] = m->e[k]; }
	info->nerr = m->n;
	return DMR_SMS_FIX_OK;
}

#endif
