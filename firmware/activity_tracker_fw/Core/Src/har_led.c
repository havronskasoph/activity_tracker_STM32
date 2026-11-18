/* Реалізація індикації стану. Див. har_led.h. */
#include "har_led.h"

#include "main.h"

#if HAR_LED_ACTIVE_HIGH
#define HAR_LED_ON   GPIO_PIN_SET
#define HAR_LED_OFF  GPIO_PIN_RESET
#else
#define HAR_LED_ON   GPIO_PIN_RESET
#define HAR_LED_OFF  GPIO_PIN_SET
#endif

static void red(GPIO_PinState state)
{
	HAL_GPIO_WritePin(LED_RED_GPIO_Port, LED_RED_Pin, state);
}

static void green(GPIO_PinState state)
{
	HAL_GPIO_WritePin(LED_GREEN_GPIO_Port, LED_GREEN_Pin, state);
}

void har_led_init(void)
{
	red(HAR_LED_OFF);
	green(HAR_LED_OFF);
}

void har_led_fault_code(uint8_t step)
{
	if (step == 0u) {
		return;
	}
	green(HAR_LED_OFF);
	for (uint8_t rep = 0u; rep < 3u; rep++) {
		for (uint8_t i = 0u; i < step; i++) {
			red(HAR_LED_ON);
			HAL_Delay(250u);
			red(HAR_LED_OFF);
			HAL_Delay(250u);
		}
		HAL_Delay(1200u);     /* пауза між серіями, щоб було що рахувати */
	}
}

void har_led_ready(void)
{
	red(HAR_LED_OFF);
	green(HAR_LED_ON);
}

void har_led_beat(void)
{
	HAL_GPIO_TogglePin(LED_GREEN_GPIO_Port, LED_GREEN_Pin);
}

void har_led_stalled(uint8_t on)
{
	red((on != 0u) ? HAR_LED_ON : HAR_LED_OFF);
}
