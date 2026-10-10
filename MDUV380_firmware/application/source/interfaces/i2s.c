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
#if defined(ENABLE_APRS_RX_PROBE) && defined(LANGUAGE_BUILD_UKRAINIAN)
#include "functions/aprs_rx_probe.h"
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
#if defined(ENABLE_APRS_RX_PROBE) && defined(LANGUAGE_BUILD_UKRAINIAN)
		else
		{
			// R2: DMA без isSending/isReceiving запускає лише I2SProbeStart() («APRS проба»);
			// звичайний код завжди ставить один із прапорців, тож сюди він не потрапляє.
			aprsRxProbeI2SBlock(0);
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
#if defined(ENABLE_APRS_RX_PROBE) && defined(LANGUAGE_BUILD_UKRAINIAN)
		else
		{
			// R2: DMA без isSending/isReceiving запускає лише I2SProbeStart() («APRS проба»);
			// звичайний код завжди ставить один із прапорців, тож сюди він не потрапляє.
			aprsRxProbeI2SBlock(1);
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
	// Need to wait for WS line has just toggled from logic low to high
	while(!HAL_GPIO_ReadPin(GPIOA, GPIO_PIN_15));
	while(HAL_GPIO_ReadPin(GPIOA, GPIO_PIN_15));
	while(!HAL_GPIO_ReadPin(GPIOA, GPIO_PIN_15));
	stopOnNextI2SDMAInterrupt = false;
	HAL_I2SEx_TransmitReceive_DMA(&hi2s3, txbuff, rxbuff, bufferLen);
}

#if defined(ENABLE_APRS_RX_PROBE) && defined(LANGUAGE_BUILD_UKRAINIAN)
// R2: дочекатися рівня WS (PA15) не довше за timeoutMs. Стоковий I2SStartDMA чекає без
// обмеження -- у FM-прийомі такту від HR-C6000 може й не бути, і рація зависла б.
static bool probeWaitWs(GPIO_PinState level, uint32_t t0, uint32_t timeoutMs)
{
	while (HAL_GPIO_ReadPin(GPIOA, GPIO_PIN_15) != level)
	{
		if ((HAL_GetTick() - t0) > timeoutMs)
		{
			return false;
		}
	}
	return true;
}

uint32_t I2SProbeStatusRegs(void)
{
	return (SPI3->SR & 0xFFFFU) | ((I2S3ext->SR & 0xFFFFU) << 16);
}

bool I2SProbeStart(uint32_t *startCycles, uint32_t *startWs)
{
	if (g_TX_SAI_in_use || isSending || isReceiving)
	{
		return false;
	}

	// R6: лічильник тактів DWT (як у spectrum.c) -- щоб виміряти, коли саме ввімкнувся I2S.
	CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
	DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;

	// Той самий момент старту, що в I2SStartDMA(): одразу після фронту WS.
	uint32_t t0 = HAL_GetTick();
	if ((probeWaitWs(GPIO_PIN_SET, t0, 5) && probeWaitWs(GPIO_PIN_RESET, t0, 5) && probeWaitWs(GPIO_PIN_SET, t0, 5)) == false)
	{
		return false;
	}
	uint32_t c0 = DWT->CYCCNT;

	memset(i2s_Tx_Buffer, 0x00, sizeof(i2s_Tx_Buffer));   // у ЦАП -- тиша
	isSending = false;
	isReceiving = false;
	stopOnNextI2SDMAInterrupt = false;
	g_TX_SAI_in_use = true;                                 // soundSendData() не стартує поверх
	if (HAL_I2SEx_TransmitReceive_DMA(&hi2s3, (uint16_t *)i2s_Tx_Buffer, (uint16_t *)i2s_Rx_Buffer, (NUM_I2S_BUFFERS * 2 * WAV_BUFFER_SIZE)) != HAL_OK)
	{
		g_TX_SAI_in_use = false;
		return false;
	}
	// R6: I2SE увімкнено в кінці HAL -- скільки минуло від фронту WS і який рівень WS зараз.
	uint32_t c1 = DWT->CYCCNT;
	*startWs = (HAL_GPIO_ReadPin(GPIOA, GPIO_PIN_15) == GPIO_PIN_SET) ? 1U : 0U;
	*startCycles = ((c1 - c0) != 0U) ? (c1 - c0) : 1U;
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
		// Переривань немає (такт WS зник посеред проби) -- зупиняємо самі.
		clearI2SBuffersAndFlags();
	}
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
