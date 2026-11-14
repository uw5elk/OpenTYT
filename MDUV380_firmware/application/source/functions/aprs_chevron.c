/* R93 (форк): див. functions/aprs_chevron.h. Увесь файл -- лише під APRS_RX. */
#include "functions/aprs_chevron.h"
#include "functions/aprs_rx_cfg.h"

#if defined(APRS_RX)

#include <math.h>

static int16_t iround(double v)
{
	return (int16_t)(v + ((v >= 0.0) ? 0.5 : -0.5));
}

void aprsChevronGeom(aprsChevron_t *c, int16_t cx, int16_t cy, int16_t len, uint16_t bearingDeg)
{
	const double rad = 0.017453292519943295;
	const double b = (double)(bearingDeg % 360U) * rad;
	const double dx = sin(b);
	const double dy = -cos(b);        /* вісь на екрані (y вниз, північ угору) */
	const double px = -dy;            /* перпендикуляр: вісь, повернута на +90° (праворуч від напрямку) */
	const double py = dx;
	const double L = (double)len;
	const double hw = 0.8 * L;        /* півширина основи */
	const double nd = 0.72 * L;       /* виїмка: позаду середини осі */
	/* R98-FIX3 Д: (cx,cy) -- центр ОПИСАНОГО кола фігури, а не середина осі. Вістря (u = +L) і кутові точки (u = -L, ±0.8L) рівновіддалені від точки u = -0.16L
	 * (радіус 1.16L): (L + 0.16L)^2 = (L - 0.16L)^2 + (0.8L)^2. Тож середину осі зсуваємо на 0.16L уперед від (cx,cy) -- у колі (кільце APRS, голка «пеленг») фігура
	 * стоїть рівно при будь-якому азимуті; розмір і форма ті самі. */
	const double sh = 0.16 * L;
	const double ox = (double)cx + (dx * sh);
	const double oy = (double)cy + (dy * sh);

	c->tx = (int16_t)iround(ox + (dx * L));
	c->ty = (int16_t)iround(oy + (dy * L));
	c->lx = (int16_t)iround(ox + (-dx * L) - (px * hw));
	c->ly = (int16_t)iround(oy + (-dy * L) - (py * hw));
	c->rx = (int16_t)iround(ox + (-dx * L) + (px * hw));
	c->ry = (int16_t)iround(oy + (-dy * L) + (py * hw));
	c->nx = (int16_t)iround(ox + (-dx * nd));
	c->ny = (int16_t)iround(oy + (-dy * nd));
}

#endif /* APRS_RX */
