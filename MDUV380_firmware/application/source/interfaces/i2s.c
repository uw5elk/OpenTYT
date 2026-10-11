/*
 * Copyright (C) 2019      Kai Ludwig, DG4KLU
 * Copyright (C) 2019-2025 Roger Clark, VK3KYY / G4KYF
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
#include "main.h"
#include "interfaces/i2s.h"
#include "functions/aprs_rx_cfg.h"
#if defined(APRS_RX)
#include "functions/aprs_rx.h"
#endif
#if defined(ENABLE_APRS_RX_PROBE) && defined(LANGUAGE_BUILD_UKRAINIAN)
#include "functions/aprs_rx_probe.h"
#endif
#if defined(APRS_RX)
#define I2S_START_WS_TIMEOUT_MS 5U   /* R8-fix: скільки максимум чекати фронт WS у I2SStartDMA() */
#endif

volatile bool g_TX_SAI_in_use = false;
volatile bool isSending = false;
volatile bool isReceiving = false;

volatile bool stopOnNextI2SDMAInterrupt = false;

uint16_t i2s_Tx_Buffer[NUM_I2S_BUFFERS][2][WAV_BUFFER_SIZE];
uint16_t i2s_Rx_Buffer[NUM_I2S_BUFFERS][2][WAV_BUFFER_SIZE];

static void clearI2SBuffersAndFlags(void)
{
	memset(i2s_Tx_Buffer, 0x00, (NUM_I2S_BUFFERS * 2 * (WAV_BUFFER_SIZE * sizeof(uint16_t))));
	memset(i2s_Rx_Buffer, 0x00, (NUM_I2S_BUFFERS * 2 * (WAV_BUFFER_SIZE * sizeof(uint16_t))));
	stopOnNextI2SDMAInterrupt = false;
	isSending = false;
	isReceiving = false;
	 HAL_I2S_DMAStop(&hi2s3);
	 __HAL_I2SEXT_FLUSH_RX_DR(&hi2s3);
	g_TX_SAI_in_use = false;
	soundInit();
}

#if defined(APRS_RX)
/* R8-fix: зупинка I2S із ЗАДАЧІ без жодного очікування прапорців.
 *
 * Чому не HAL_I2S_DMAStop(): hi2s3 -- I2S_MODE_SLAVE_RX у дуплексі, тож HAL іде гілкою «RX» і чекає
 * прапорці TXE та BSY веденого I2S3ext у циклах `while (прапорець != потрібний) { if (таймаут) { лише
 * виставити код помилки } }` -- БЕЗ break/return (stm32f4xx_hal_i2s.c, ~рядки 1560-1590). Якщо такту
 * BCLK/WS нема, прапорці не зміняться ніколи: цикл вічний, рація висне (лише зняття акумулятора).
 * Стокова зупинка викликається з переривання DMA, коли такт гарантовано є, тож там це не проявлялося;
 * фоновий приймач APRS (R8) зупиняє I2S з головної задачі в довільний момент (початок передачі, вихід
 * з каналу), коли такту може не бути. Тут: перервати DMA (HAL_DMA_Abort -- з таймаутом і return),
 * вимкнути периферію й прапорці DMA напряму. Нічого не чекаємо. Лічильник збоїв -- aprsRxNoteI2sEvent. */
static void i2sHaltNoWait(void)
{
	if ((hi2s3.hdmarx != NULL) && (hi2s3.hdmarx->State == HAL_DMA_STATE_BUSY))
	{
		if (HAL_DMA_Abort(hi2s3.hdmarx) == HAL_TIMEOUT)
		{
			aprsRxNoteI2sEvent(APRS_RX_I2S_EV_ABORT_TIMEOUT);
		}
	}
	if ((hi2s3.hdmatx != NULL) && (hi2s3.hdmatx->State == HAL_DMA_STATE_BUSY))
	{
		if (HAL_DMA_Abort(hi2s3.hdmatx) == HAL_TIMEOUT)
		{
			aprsRxNoteI2sEvent(APRS_RX_I2S_EV_ABORT_TIMEOUT);
		}
	}
	__HAL_I2SEXT_DISABLE(&hi2s3);
	__HAL_I2S_DISABLE(&hi2s3);
	CLEAR_BIT(SPI3->CR2, SPI_CR2_RXDMAEN | SPI_CR2_TXDMAEN);
	CLEAR_BIT(I2S3ext->CR2, SPI_CR2_RXDMAEN | SPI_CR2_TXDMAEN);
	__HAL_I2S_CLEAR_OVRFLAG(&hi2s3);
	__HAL_I2SEXT_CLEAR_UDRFLAG(&hi2s3);
	__HAL_I2SEXT_CLEAR_OVRFLAG(&hi2s3);
	(void)READ_REG(SPI3->DR);
	(void)READ_REG(I2S3ext->DR);
	hi2s3.State = HAL_I2S_STATE_READY;
	__HAL_UNLOCK(&hi2s3);
}

/* Те саме, що clearI2SBuffersAndFlags(), але зупинка без очікування (i2sHaltNoWait). */
static void clearI2SBuffersAndFlagsNoWait(void)
{
	stopOnNextI2SDMAInterrupt = false;
	isSending = false;
	isReceiving = false;
	i2sHaltNoWait();
	memset(i2s_Tx_Buffer, 0x00, (NUM_I2S_BUFFERS * 2 * (WAV_BUFFER_SIZE * sizeof(uint16_t))));
	memset(i2s_Rx_Buffer, 0x00, (NUM_I2S_BUFFERS * 2 * (WAV_BUFFER_SIZE * sizeof(uint16_t))));
	__HAL_I2SEXT_FLUSH_RX_DR(&hi2s3);
	g_TX_SAI_in_use = false;
	soundInit();
}

/* R8: блок I2S RX -- пробі, якщо її екран відкрито, інакше фоновому приймачу APRS. */
static inline void aprsI2SBlock(uint32_t bufNum)
{
#if defined(ENABLE_APRS_RX_PROBE)
	if (aprsRxProbeIsOn())
	{
		aprsRxProbeI2SBlock(bufNum);
		return;
	}
#endif
	aprsRxI2SBlock(bufNum);
}
#endif

void HAL_I2SEx_TxRxHalfCpltCallback(I2S_HandleTypeDef *hi2s)
{
	if (!stopOnNextI2SDMAInterrupt)
	{
		if (isSending)
		{
			g_TX_SAI_in_use = soundRefillData(0);
		}
		else if(isReceiving)
		{
			soundReceiveRefillData(0);
		}
#if defined(APRS_RX)
		else
		{
			// R2/R8: DMA без isSending/isReceiving запускає лише I2SProbeStart() (екран «APRS проба» і
			// фоновий приймач APRS); звичайний код завжди ставить один із прапорців, тож сюди він не потрапляє.
			aprsI2SBlock(0);
		}
#endif
	}
	else
	{
		clearI2SBuffersAndFlags();
	}
}

void HAL_I2SEx_TxRxCpltCallback(I2S_HandleTypeDef *hi2s)
{
	if (!stopOnNextI2SDMAInterrupt)
	{
		if (isSending)
		{
			g_TX_SAI_in_use = soundRefillData(1);
		}
		else if(isReceiving)
		{
			soundReceiveRefillData(1);
		}
#if defined(APRS_RX)
		else
		{
			// R2/R8: DMA без isSending/isReceiving запускає лише I2SProbeStart() (екран «APRS проба» і
			// фоновий приймач APRS); звичайний код завжди ставить один із прапорців, тож сюди він не потрапляє.
			aprsI2SBlock(1);
		}
#endif
	}
	else
	{
		clearI2SBuffersAndFlags();
	}
}

void I2SStartDMA(uint16_t *txbuff, uint16_t *rxbuff, size_t bufferLen)
{
#if defined(APRS_RX)
	// R8-fix: стокові три цикли очікування WS не мають таймаута -- якщо HR-C6000 не веде такт, рація
	// висла б намертво. Тут увесь пошук фронту обмежено ~5 мс (лічильник DWT, а не HAL_GetTick: той не
	// тікає з вимкненими перериваннями). Після таймаута DMA НЕ стартуємо: прапорці повертаємо в «вільно»
	// (інакше isSending/g_TX_SAI_in_use лишилися б «зайнято» і наступний старт заблокувався б), буфери
	// звуку скидаємо (це ж і притримує повторні спроби, доки не накопичиться новий звук).
	CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
	DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
	uint32_t budget = (HAL_RCC_GetHCLKFreq() / 1000U) * I2S_START_WS_TIMEOUT_MS;
	uint32_t c0 = DWT->CYCCNT;
	bool ok = true;

	// Need to wait for WS line has just toggled from logic low to high
	for (int phase = 0; (phase < 3) && ok; phase++)
	{
		bool wantHigh = (phase != 1);

		while (((GPIOA->IDR & GPIO_PIN_15) != 0U) != wantHigh)
		{
			if ((DWT->CYCCNT - c0) > budget)
			{
				ok = false;
				break;
			}
		}
	}
	if (ok == false)
	{
		aprsRxNoteI2sEvent(APRS_RX_I2S_EV_WS_TIMEOUT);
		isSending = false;
		isReceiving = false;
		g_TX_SAI_in_use = false;
		soundInit();
		return;
	}
#else
	// Need to wait for WS line has just toggled from logic low to high
	while(!HAL_GPIO_ReadPin(GPIOA, GPIO_PIN_15));
	while(HAL_GPIO_ReadPin(GPIOA, GPIO_PIN_15));
	while(!HAL_GPIO_ReadPin(GPIOA, GPIO_PIN_15));
#endif
	stopOnNextI2SDMAInterrupt = false;
	HAL_I2SEx_TransmitReceive_DMA(&hi2s3, txbuff, rxbuff, bufferLen);
}

#if defined(APRS_RX)
uint32_t I2SProbeStatusRegs(void)
{
	return (SPI3->SR & 0xFFFFU) | ((I2S3ext->SR & 0xFFFFU) << 16);
}

void I2SProbeRegs(uint16_t *r)
{
	r[0] = (uint16_t)SPI3->I2SCFGR;
	r[1] = (uint16_t)SPI3->I2SPR;
	r[2] = (uint16_t)SPI3->CR2;
	r[3] = (uint16_t)I2S3ext->I2SCFGR;
	r[4] = (uint16_t)I2S3ext->I2SPR;
	r[5] = (uint16_t)I2S3ext->CR2;
}

// R7: рівень WS (PA15) читаємо прямо з IDR -- швидше за HAL_GPIO_ReadPin (виклик + порівняння).
static inline bool probeWsHigh(void)
{
	return ((GPIOA->IDR & GPIO_PIN_15) != 0U);
}

// Дочекатися рівня WS не довше за timeoutCycles тактів (DWT); переривання вимкнені викликачем.
static bool probeWaitWsCycles(bool high, uint32_t timeoutCycles)
{
	uint32_t c0 = DWT->CYCCNT;
	while (probeWsHigh() != high)
	{
		if ((DWT->CYCCNT - c0) > timeoutCycles)
		{
			return false;
		}
	}
	return true;
}

bool I2SProbeStart(uint32_t tStartCycles, uint32_t periodCycles, uint32_t *halCycles, uint32_t *tActualCycles, uint32_t *startWs)
{
	if (g_TX_SAI_in_use || isSending || isReceiving || (periodCycles == 0U))
	{
		return false;
	}

	// Лічильник тактів DWT (як у spectrum.c).
	CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
	DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;

	// R7: усе, що не залежить від фронту WS, -- ДО нього (раніше memset 1280 Б входив у «112 мкс»).
	memset(i2s_Tx_Buffer, 0x00, sizeof(i2s_Tx_Buffer));   // у ЦАП -- тиша
	isSending = false;
	isReceiving = false;
	stopOnNextI2SDMAInterrupt = false;
	g_TX_SAI_in_use = true;                                 // soundSendData() не стартує поверх

	uint32_t hal = *halCycles;
	uint32_t delay = 0;
	if (hal != 0U)
	{
		// I2SE має припасти на tStartCycles після фронту: HAL починається на (tStart - hal) mod період.
		delay = ((tStartCycles % periodCycles) + periodCycles - (hal % periodCycles)) % periodCycles;
	}

	uint32_t primask = __get_PRIMASK();
	__disable_irq();

	// Фронт WS 0->1: чекаємо низький рівень, потім високий. Тайм-аут -- 2 періоди кожен: за відсутності
	// такту переривання вимкнені не довше ~0,5 мс (WS справжній -- чекання < 1 періоду).
	bool edge = probeWaitWsCycles(false, periodCycles * 2U) && probeWaitWsCycles(true, periodCycles * 2U);
	if (edge == false)
	{
		__set_PRIMASK(primask);
		g_TX_SAI_in_use = false;
		return false;
	}
	uint32_t cEdge = DWT->CYCCNT;
	while ((DWT->CYCCNT - cEdge) < delay)
	{
	}

	uint32_t c0 = DWT->CYCCNT;
	HAL_StatusTypeDef st = HAL_I2SEx_TransmitReceive_DMA(&hi2s3, (uint16_t *)i2s_Tx_Buffer, (uint16_t *)i2s_Rx_Buffer, (NUM_I2S_BUFFERS * 2 * WAV_BUFFER_SIZE));
	// I2SE увімкнено в самому кінці HAL (ES0182 2.12.6: WS у цей момент має бути 1)
	uint32_t c1 = DWT->CYCCNT;
	uint32_t ws = probeWsHigh() ? 1U : 0U;
	__set_PRIMASK(primask);

	if (st != HAL_OK)
	{
		g_TX_SAI_in_use = false;
		return false;
	}
	*halCycles = ((c1 - c0) != 0U) ? (c1 - c0) : 1U;
	*tActualCycles = (c1 - cEdge) % periodCycles;
	*startWs = ws;
	return true;
}

bool I2SProbeIsRunning(void)
{
	return (g_TX_SAI_in_use && (isSending == false) && (isReceiving == false) && (stopOnNextI2SDMAInterrupt == false));
}

void I2SProbeStop(void)
{
	if ((g_TX_SAI_in_use == false) || isSending || isReceiving)
	{
		return;   // нічого не запущено, або це чужа (звичайна) передача
	}

	// Як I2STerminateTransfers(): найближче переривання (<= 20 мс) саме зупинить DMA й
	// скине прапорці через clearI2SBuffersAndFlags().
	stopOnNextI2SDMAInterrupt = true;
	uint32_t t0 = HAL_GetTick();
	while (g_TX_SAI_in_use && ((HAL_GetTick() - t0) < 60U))
	{
	}

	if (g_TX_SAI_in_use)
	{
		// Переривань немає (такт WS зник посеред проби) -- зупиняємо самі. R8-fix: без очікування
		// прапорців (при зниклому такті HAL_I2S_DMAStop() крутився б вічно).
		clearI2SBuffersAndFlagsNoWait();
	}
}

/* R8: НЕГАЙНА зупинка передачі, запущеної I2SProbeStart(), без очікування переривання (на відміну від
 * I2SProbeStop(), що чекає до 60 мс). Для фонового приймача APRS: його викликають із задачі перед
 * голосовою підказкою / відтворенням «Переслухати» / зміною режиму, де 20 мс зупинки головного циклу
 * були б помітні. Чужу (звичайну) передачу не чіпає. Безпечно, якщо нічого не запущено. */
void I2SProbeAbort(void)
{
	if ((g_TX_SAI_in_use == false) || isSending || isReceiving)
	{
		return;
	}
	clearI2SBuffersAndFlagsNoWait();   /* R8-fix: див. i2sHaltNoWait() -- HAL_I2S_DMAStop() тут міг висіти вічно */
}
#endif

void I2SReset(void)
{

}

void I2STerminateTransfers(void)
{
	stopOnNextI2SDMAInterrupt = true;
}

void init_I2S(void)
{

}
