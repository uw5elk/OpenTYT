/* R91C (форк): див. functions/lc_distance.h. Увесь файл -- лише під ENABLE_LC_DISTANCE (+ APRS_RX). */
#include "functions/lc_distance.h"

#if defined(LC_DISTANCE)

#include <math.h>
#include <stdio.h>

bool lcDistUsable(double lat, double lon)
{
	if (isnan(lat) || isnan(lon))
	{
		return false;
	}

	if ((lat < -90.0) || (lat > 90.0) || (lon < -180.0) || (lon > 180.0))
	{
		return false;
	}

	return !((lat == 0.0) && (lon == 0.0));
}

bool lcDistCompute(double myLat, double myLon, double lat, double lon, uint32_t *distM, uint16_t *bearingDeg)
{
	if ((isnan(myLat) || isnan(myLon) || (myLat < -90.0) || (myLat > 90.0) || (myLon < -180.0) || (myLon > 180.0)) || (lcDistUsable(lat, lon) == false))
	{
		return false;
	}

	double m = distanceBetweenTwoCoords(myLat, myLon, lat, lon, false);
	double brg = courseTo(myLat, myLon, lat, lon);

	*distM = (m < 0.0) ? 0U : (uint32_t)(m + 0.5);
	*bearingDeg = (uint16_t)(((int)(brg + 0.5)) % 360);

	return true;
}

bool lcDistText(char *buf, size_t size, bool ownPositionValid, double myLat, double myLon, double lat, double lon)
{
	uint32_t distM;
	uint16_t brg;

	if ((ownPositionValid == false) || (lcDistCompute(myLat, myLon, lat, lon, &distM, &brg) == false))
	{
		return false;
	}

	aprsRxFormatGeo(buf, size, distM, brg);

	return true;
}

bool lcDistLabel(char *buf, size_t size, bool ownPositionValid, double myLat, double myLon, double lat, double lon, uint16_t *bearingDeg, bool *bearingKnown)
{
	uint32_t distM;

	if ((ownPositionValid == false) || (lcDistCompute(myLat, myLon, lat, lon, &distM, bearingDeg) == false))
	{
		return false;
	}

	aprsRxFormatDist(buf, size, distM);
	*bearingKnown = aprsBearingKnown(distM);

	return true;
}

lcDistRow_t lcDistLabelRow(size_t textLen, bool singleLineOnly, bool autoSplit)
{
	if (textLen < 5U)
	{
		return LC_ROW_NONE;
	}

	if (singleLineOnly || (autoSplit && (textLen <= 16U)))
	{
		return (textLen <= 16U) ? LC_ROW_FIRST : LC_ROW_NONE;
	}

	return LC_ROW_SECOND;
}

void lcDistArrowGeom(lcDistArrow_t *a, int16_t screenW, int16_t rowY, int16_t rowH, uint16_t bearingDeg)
{
	a->cx = (int16_t)(screenW - LC_ARROW_MARGIN);
	a->cy = (int16_t)(rowY + (rowH / 2));
	aprsArrowGeom(&a->g, a->cx, a->cy, LC_ARROW_LEN, bearingDeg);
	a->bx = (int16_t)((2 * a->cx) - a->g.tx);
	a->by = (int16_t)((2 * a->cy) - a->g.ty);
}

#endif /* LC_DISTANCE */
