/* USER CODE BEGIN Header */
/**
 ******************************************************************************
 * @file           : main.c
 * @brief          : Main program body
 ******************************************************************************
 * @attention
 *
 * Copyright (c) 2026 STMicroelectronics.
 * All rights reserved.
 *
 * This software is licensed under terms that can be found in the LICENSE file
 * in the root directory of this software component.
 * If no LICENSE file comes with this software, it is provided AS-IS.
 *
 ******************************************************************************
 */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include <stdio.h>
#include "ism330dhcx_reg.h"
#include "har_preproc.h"
#include "har_model.h"

/* Самоперевірка на платі: одноразовий прогін тестових векторів із
   har_test_vectors.h і вимір часу інференсу лічильником тактів DWT одразу
   після старту. Вмикати після кожної зміни моделі чи ваг: результат має бути
   50/50 збігів із очікуваними класами. 0 — звичайна робота. */
#define HAR_SELFTEST      0

#if HAR_SELFTEST
#include "har_test_vectors.h"
#endif
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
/* Потік CSV у UART: 1 — для збору даних, 0 — коли працює тільки інференс
   (при 104 Гц рядок займає ~60 % пропускної здатності 115200 бод). */
#define HAR_STREAM_CSV    0

/* Що саме виводити: 1 — відліки після ФНЧ (те, що бачить модель),
   0 — сирі, якщо треба подивитися на сигнал до фільтра. */
#define HAR_LOG_FILTERED  1

/* Як часто друкувати фактичну частоту і лічильник втрат, мс. */
#define HAR_STATUS_PERIOD_MS  5000u

/* Один рядок CSV: мітка часу + 6 значень у форматі -123.456 */
#define CSV_LINE_MAX      96
/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
MDF_HandleTypeDef AdfHandle0;
MDF_FilterConfigTypeDef AdfFilterConfig0;

I2C_HandleTypeDef hi2c1;
I2C_HandleTypeDef hi2c2;

OSPI_HandleTypeDef hospi1;
OSPI_HandleTypeDef hospi2;

SPI_HandleTypeDef hspi2;

UART_HandleTypeDef huart4;
UART_HandleTypeDef huart1;

PCD_HandleTypeDef hpcd_USB_OTG_FS;

/* USER CODE BEGIN PV */
#define IMU_I2C   hi2c2
#define IMU_ADDR  (0x6B << 1)

static stmdev_ctx_t imu_ctx;

/* Sampling is paced by the sensor's own data-ready line (INT1 -> PE11).
   The ISR only bumps imu_drdy_count; imu_drdy_served is what the main loop
   has already consumed, so the gap between them exposes samples we did not
   keep up with. A 32-bit load is atomic on Cortex-M33, no locking needed. */
static volatile uint32_t imu_drdy_count = 0;
static uint32_t imu_drdy_served = 0;
static uint32_t imu_missed = 0;

static int32_t imu_write(void *h, uint8_t reg, uint8_t *buf, uint16_t len) {
	return (HAL_I2C_Mem_Write(&IMU_I2C, IMU_ADDR, reg, I2C_MEMADD_SIZE_8BIT,
			buf, len, 100) == HAL_OK) ? 0 : -1;
}

static int32_t imu_read(void *h, uint8_t reg, uint8_t *buf, uint16_t len) {
	return (HAL_I2C_Mem_Read(&IMU_I2C, IMU_ADDR, reg, I2C_MEMADD_SIZE_8BIT, buf,
			len, 100) == HAL_OK) ? 0 : -1;
}

static void imu_init(void) {
	uint8_t whoami = 0, rst = 1;

	imu_ctx.write_reg = imu_write;
	imu_ctx.read_reg = imu_read;
	imu_ctx.mdelay = HAL_Delay;
	imu_ctx.handle = NULL;

	HAL_Delay(15);
	ism330dhcx_device_id_get(&imu_ctx, &whoami);
	printf("WHO_AM_I = 0x%02X (expected 0x%02X)\r\n", whoami, ISM330DHCX_ID);
	if (whoami != ISM330DHCX_ID) {
		printf("IMU not found\r\n");
		Error_Handler();
	}

	ism330dhcx_reset_set(&imu_ctx, PROPERTY_ENABLE);
	do {
		ism330dhcx_reset_get(&imu_ctx, &rst);
	} while (rst);

	ism330dhcx_block_data_update_set(&imu_ctx, PROPERTY_ENABLE);
	ism330dhcx_xl_full_scale_set(&imu_ctx, ISM330DHCX_4g);
	ism330dhcx_gy_full_scale_set(&imu_ctx, ISM330DHCX_2000dps);
	/* 104 Гц на обох датчиках — рівно та частота, на якій підготовлений
	   датасет (har_model_config.h: HAR_FS_HZ). Міняти тут, не узгодивши з
	   датасетом, не можна: вікно 208 відліків перестане дорівнювати 2 с. */
	ism330dhcx_xl_data_rate_set(&imu_ctx, ISM330DHCX_XL_ODR_104Hz);
	ism330dhcx_gy_data_rate_set(&imu_ctx, ISM330DHCX_GY_ODR_104Hz);

	/* Вбудовані фільтри датчика лишаємо вимкненими: LPF2 акселерометра дає
	   щонайбільше ODR/10 = 10.4 Гц (зрізало б корисний сигнал), а LPF1
	   гіроскопа задається «силою», а не частотою. Потрібні рівно 25 Гц —
	   їх робить har_preproc.c тими самими коефіцієнтами, що й датасет. */

	/* Drive accelerometer data-ready out on INT1 (INT1_CTRL, int1_drdy_xl)
	   as a short pulse, which is what an edge-triggered EXTI line wants. */
	ism330dhcx_pin_int1_route_t int1_route;
	ism330dhcx_pin_int1_route_get(&imu_ctx, &int1_route);
	int1_route.int1_ctrl.int1_drdy_xl = PROPERTY_ENABLE;
	ism330dhcx_pin_int1_route_set(&imu_ctx, &int1_route);
	ism330dhcx_data_ready_mode_set(&imu_ctx, ISM330DHCX_DRDY_PULSED);
}

/* Друк дробових чисел без printf("%f"): значення тримаємо в тисячних
   (мілі-g і мілі-dps) і форматуємо цілими. Знак обробляємо окремо, інакше
   -0.5 надрукувалося б як "0.-500". */
static char *put_milli(char *p, int32_t milli)
{
	if (milli < 0) {
		*p++ = '-';
		milli = -milli;
	}
	p += sprintf(p, "%ld.%03ld", (long) (milli / 1000), (long) (milli % 1000));
	return p;
}

/* Увесь рядок збираємо в буфер і віддаємо в UART одним викликом: при 104 Гц
   побайтовий HAL_UART_Transmit (через printf) з'їдав би більшу частину
   періоду вибірки. */
static void emit_csv(uint32_t t_ms, const float s[HAR_CHANNELS])
{
	char line[CSV_LINE_MAX];
	char *p = line;

	p += sprintf(p, "%lu", (unsigned long) t_ms);
	for (int c = 0; c < HAR_CHANNELS; c++) {
		*p++ = ',';
		p = put_milli(p, (int32_t) (s[c] * 1000.0f));
	}
	*p++ = '\r';
	*p++ = '\n';

	HAL_UART_Transmit(&huart1, (uint8_t *) line, (uint16_t) (p - line),
			HAL_MAX_DELAY);
}

/* Результат класифікації окремим рядком, що починається з '#': tools/log.py
   такі рядки пропускає, тож потік лишається придатним і для збору CSV. */
static void emit_pred(uint32_t t_ms, int cls, float p)
{
	char line[CSV_LINE_MAX];
	char *q = line;

	q += sprintf(q, "# pred t=%lu class=%s p=", (unsigned long) t_ms,
			har_model_class_name(cls));
	q = put_milli(q, (int32_t) (p * 1000.0f));
	*q++ = '\r';
	*q++ = '\n';

	HAL_UART_Transmit(&huart1, (uint8_t *) line, (uint16_t) (q - line),
			HAL_MAX_DELAY);
}
/* USER CODE END PV */

#if HAR_SELFTEST
/* Прогін тестових векторів і вимір часу інференсу. Викликається один раз
   після старту; результати йдуть у UART рядками з '#', тож tools/log.py їх
   пропускає. Лічильник тактів DWT дає точність до одного такту ядра. */
static void har_selftest(void)
{
	CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
	DWT->CYCCNT = 0;
	DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;

	int ok = 0;
	uint32_t cyc_min = 0xFFFFFFFFu, cyc_max = 0, cyc_sum = 0;

	for (int i = 0; i < HAR_TV_COUNT; i++) {
		float probs[HAR_CLASS_COUNT];
		int cls = -1;

		const uint32_t t0 = DWT->CYCCNT;
		const har_model_status_t st = har_model_predict(&har_tv_input[i][0][0], probs, &cls);
		const uint32_t dt = DWT->CYCCNT - t0;

		if (st != HAR_MODEL_OK) {
			printf("# selftest vector %d: %s\r\n", i, har_model_status_str(st));
			continue;
		}
		if (dt < cyc_min) { cyc_min = dt; }
		if (dt > cyc_max) { cyc_max = dt; }
		cyc_sum += dt;
		if (cls == (int) har_tv_expected[i]) {
			ok++;
		} else {
			printf("# selftest mismatch %d: expected=%d got=%d\r\n",
				i, (int) har_tv_expected[i], cls);
		}
	}

	printf("# selftest match=%d/%d\r\n", ok, HAR_TV_COUNT);
	printf("# selftest cycles min=%lu avg=%lu max=%lu clk=%lu\r\n",
			(unsigned long) cyc_min, (unsigned long) (cyc_sum / HAR_TV_COUNT),
			(unsigned long) cyc_max, (unsigned long) SystemCoreClock);
	printf("# selftest us avg=%lu\r\n",
			(unsigned long) ((uint64_t) (cyc_sum / HAR_TV_COUNT) * 1000000u / SystemCoreClock));
}
#endif /* HAR_SELFTEST */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void SystemPower_Config(void);
static void MX_GPIO_Init(void);
static void MX_ADF1_Init(void);
static void MX_I2C1_Init(void);
static void MX_I2C2_Init(void);
static void MX_ICACHE_Init(void);
static void MX_OCTOSPI1_Init(void);
static void MX_OCTOSPI2_Init(void);
static void MX_SPI2_Init(void);
static void MX_UART4_Init(void);
static void MX_USART1_UART_Init(void);
static void MX_UCPD1_Init(void);
static void MX_USB_OTG_FS_PCD_Init(void);
/* USER CODE BEGIN PFP */

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

/* USER CODE END 0 */

/**
 * @brief  The application entry point.
 * @retval int
 */
int main(void) {

	/* USER CODE BEGIN 1 */

	/* USER CODE END 1 */

	/* MCU Configuration--------------------------------------------------------*/

	/* Reset of all peripherals, Initializes the Flash interface and the Systick. */
	HAL_Init();

	/* USER CODE BEGIN Init */

	/* USER CODE END Init */

	/* Configure the System Power */
	SystemPower_Config();

	/* Configure the system clock */
	SystemClock_Config();

	/* USER CODE BEGIN SysInit */

	/* USER CODE END SysInit */

	/* Initialize all configured peripherals */
	MX_GPIO_Init();
	MX_ADF1_Init();
	MX_I2C1_Init();
	MX_I2C2_Init();
	MX_ICACHE_Init();
	MX_OCTOSPI1_Init();
	MX_OCTOSPI2_Init();
	MX_SPI2_Init();
	MX_UART4_Init();
	MX_USART1_UART_Init();
	MX_UCPD1_Init();
	MX_USB_OTG_FS_PCD_Init();
	/* USER CODE BEGIN 2 */
	setvbuf(stdout, NULL, _IONBF, 0);
	printf("Start\r\n");
	imu_init();
	har_preproc_init();
	const har_model_status_t model_st = har_model_init();
	/* Без %f/%g: newlib-nano за замовчуванням не лінкує float-форматування,
	   тому всі дробові значення друкуємо цілими (див. put_milli). */
	printf("# fs=%d Hz window=%d x %d hop=%d lpf=%d Hz units=%s,%s\r\n",
			(int) HAR_FS_HZ, HAR_WINDOW_SAMPLES, HAR_CHANNELS,
			HAR_HOP_SAMPLES, (int) HAR_LPF_HZ, HAR_ACC_UNIT, HAR_GYR_UNIT);
	printf("# model=%s classes=%d\r\n",
			har_model_status_str(model_st), HAR_CLASS_COUNT);

#if HAR_SELFTEST
	har_selftest();
#endif

	/* Unmask the line only once the sensor is configured, so none of the
	   writes above can leave a stale edge pending. */
	__HAL_GPIO_EXTI_CLEAR_RISING_IT(Mems_ISM330DLC_INT1_Pin);
	HAL_NVIC_SetPriority(EXTI11_IRQn, 5, 0);
	HAL_NVIC_EnableIRQ(EXTI11_IRQn);

#if HAR_STREAM_CSV
	printf("timestamp_ms,ax,ay,az,gx,gy,gz\r\n");
#endif

	/* Лічильники для рядка стану: фактична частота, зібрані вікна, втрати. */
	uint32_t sample_count = 0, window_count = 0;
	uint32_t status_at = HAL_GetTick();
	/* USER CODE END 2 */

	/* Infinite loop */
	/* USER CODE BEGIN WHILE */
	while (1) {
		/* USER CODE END WHILE */

		/* USER CODE BEGIN 3 */
	    uint32_t drdy_now = imu_drdy_count;

	    if (drdy_now != imu_drdy_served) {
	      uint32_t pending = drdy_now - imu_drdy_served;
	      imu_drdy_served = drdy_now;

	      /* Only the newest sample is still in the output registers, so every
	         interrupt beyond the one we are about to read is a sample we lost. */
	      const uint32_t lost = (pending > 1) ? (pending - 1) : 0;
	      imu_missed += lost;

	      /* Одиниці рівно як у датасеті: акселерометр у g, гіроскоп у °/с.
	         Драйвер віддає мілі-одиниці, тому ділимо на 1000. */
	      int16_t a_raw[3], g_raw[3];
	      float sample[HAR_CHANNELS];

	      ism330dhcx_acceleration_raw_get(&imu_ctx, a_raw);
	      ism330dhcx_angular_rate_raw_get(&imu_ctx, g_raw);
	      for (int i = 0; i < 3; i++) {
	        sample[i]     = ism330dhcx_from_fs4g_to_mg(a_raw[i]) / 1000.0f;
	        sample[3 + i] = ism330dhcx_from_fs2000dps_to_mdps(g_raw[i]) / 1000.0f;
	      }

	      /* ФНЧ 25 Гц + накопичення вікна 208 x 6 (крок 104) з урахуванням
	         втрачених відліків: малий провал добивається інтерполяцією,
	         великий рве вікно — так само, як у препроцесингу датасету. */
	      const int window_ready = har_preproc_push_missed(sample, lost);
	      sample_count++;

#if HAR_STREAM_CSV
#if HAR_LOG_FILTERED
	      emit_csv(HAL_GetTick(), har_preproc_last());
#else
	      emit_csv(HAL_GetTick(), sample);
#endif
#endif

	      if (window_ready) {
	        window_count++;
	        float *window = har_preproc_window();
	        har_preproc_normalize(window);

	        /* Вікно готове рівно в тому вигляді, в якому навчалася модель.
	           Доки мережі в прошивці немає (HAR_MODEL_DEPLOYED == 0), виклик
	           повертає NOT_DEPLOYED і цикл просто йде далі. */
	        float probs[HAR_CLASS_COUNT];
	        int cls = -1;

	        if (har_model_predict(window, probs, &cls) == HAR_MODEL_OK) {
	          emit_pred(HAL_GetTick(), cls, probs[cls]);
	        }
	      }
	    }

	    /* Фактична частота: ODR у даташиті номінальний, і якщо реально вийде
	       не 104 Гц, вікно у 208 відліків перестане бути двома секундами. */
	    const uint32_t now = HAL_GetTick();
	    if (now - status_at >= HAR_STATUS_PERIOD_MS) {
	      const uint32_t elapsed = now - status_at;
	      const uint32_t milli_hz = (sample_count * 1000000u) / elapsed;
	      char line[CSV_LINE_MAX];
	      char *p = line;

	      p += sprintf(p, "# rate=");
	      p = put_milli(p, (int32_t) milli_hz);
	      p += sprintf(p, " Hz windows=%lu missed=%lu",
	                   (unsigned long) window_count, (unsigned long) imu_missed);
	      *p++ = '\r';
	      *p++ = '\n';
	      HAL_UART_Transmit(&huart1, (uint8_t *) line, (uint16_t) (p - line),
	                        HAL_MAX_DELAY);

	      status_at = now;
	      sample_count = 0;
	    }
	  }
	/* USER CODE END 3 */
}

/**
 * @brief System Clock Configuration
 * @retval None
 */
void SystemClock_Config(void) {
	RCC_OscInitTypeDef RCC_OscInitStruct = { 0 };
	RCC_ClkInitTypeDef RCC_ClkInitStruct = { 0 };

	/** Configure the main internal regulator output voltage
	 */
	if (HAL_PWREx_ControlVoltageScaling(PWR_REGULATOR_VOLTAGE_SCALE1)
			!= HAL_OK) {
		Error_Handler();
	}

	/** Initializes the CPU, AHB and APB buses clocks
	 */
	RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI48
			| RCC_OSCILLATORTYPE_HSI | RCC_OSCILLATORTYPE_MSI;
	RCC_OscInitStruct.HSIState = RCC_HSI_ON;
	RCC_OscInitStruct.HSI48State = RCC_HSI48_ON;
	RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
	RCC_OscInitStruct.MSIState = RCC_MSI_ON;
	RCC_OscInitStruct.MSICalibrationValue = RCC_MSICALIBRATION_DEFAULT;
	RCC_OscInitStruct.MSIClockRange = RCC_MSIRANGE_4;
	RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
	RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_MSI;
	RCC_OscInitStruct.PLL.PLLMBOOST = RCC_PLLMBOOST_DIV1;
	RCC_OscInitStruct.PLL.PLLM = 1;
	RCC_OscInitStruct.PLL.PLLN = 80;
	RCC_OscInitStruct.PLL.PLLP = 2;
	RCC_OscInitStruct.PLL.PLLQ = 2;
	RCC_OscInitStruct.PLL.PLLR = 2;
	RCC_OscInitStruct.PLL.PLLRGE = RCC_PLLVCIRANGE_0;
	RCC_OscInitStruct.PLL.PLLFRACN = 0;
	if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK) {
		Error_Handler();
	}

	/** Initializes the CPU, AHB and APB buses clocks
	 */
	RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK
			| RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2 | RCC_CLOCKTYPE_PCLK3;
	RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
	RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
	RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;
	RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;
	RCC_ClkInitStruct.APB3CLKDivider = RCC_HCLK_DIV1;

	if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_4) != HAL_OK) {
		Error_Handler();
	}
}

/**
 * @brief Power Configuration
 * @retval None
 */
static void SystemPower_Config(void) {
	HAL_PWREx_EnableVddIO2();

	/*
	 * Switch to SMPS regulator instead of LDO
	 */
	if (HAL_PWREx_ConfigSupply(PWR_SMPS_SUPPLY) != HAL_OK) {
		Error_Handler();
	}
	/* USER CODE BEGIN PWR */
	/* USER CODE END PWR */
}

/**
 * @brief ADF1 Initialization Function
 * @param None
 * @retval None
 */
static void MX_ADF1_Init(void) {

	/* USER CODE BEGIN ADF1_Init 0 */

	/* USER CODE END ADF1_Init 0 */

	/* USER CODE BEGIN ADF1_Init 1 */

	/* USER CODE END ADF1_Init 1 */

	/**
	 AdfHandle0 structure initialization and HAL_MDF_Init function call
	 */
	AdfHandle0.Instance = ADF1_Filter0;
	AdfHandle0.Init.CommonParam.ProcClockDivider = 1;
	AdfHandle0.Init.CommonParam.OutputClock.Activation = DISABLE;
	AdfHandle0.Init.SerialInterface.Activation = ENABLE;
	AdfHandle0.Init.SerialInterface.Mode = MDF_SITF_LF_MASTER_SPI_MODE;
	AdfHandle0.Init.SerialInterface.ClockSource = MDF_SITF_CCK0_SOURCE;
	AdfHandle0.Init.SerialInterface.Threshold = 4;
	AdfHandle0.Init.FilterBistream = MDF_BITSTREAM0_FALLING;
	if (HAL_MDF_Init(&AdfHandle0) != HAL_OK) {
		Error_Handler();
	}

	/**
	 AdfFilterConfig0 structure initialization

	 WARNING : only structure is filled, no specific init function call for filter
	 */
	AdfFilterConfig0.DataSource = MDF_DATA_SOURCE_BSMX;
	AdfFilterConfig0.Delay = 0;
	AdfFilterConfig0.CicMode = MDF_ONE_FILTER_SINC4;
	AdfFilterConfig0.DecimationRatio = 2;
	AdfFilterConfig0.Gain = 0;
	AdfFilterConfig0.ReshapeFilter.Activation = DISABLE;
	AdfFilterConfig0.HighPassFilter.Activation = DISABLE;
	AdfFilterConfig0.SoundActivity.Activation = DISABLE;
	AdfFilterConfig0.AcquisitionMode = MDF_MODE_ASYNC_CONT;
	AdfFilterConfig0.FifoThreshold = MDF_FIFO_THRESHOLD_NOT_EMPTY;
	AdfFilterConfig0.DiscardSamples = 0;
	/* USER CODE BEGIN ADF1_Init 2 */

	/* USER CODE END ADF1_Init 2 */

}

/**
 * @brief I2C1 Initialization Function
 * @param None
 * @retval None
 */
static void MX_I2C1_Init(void) {

	/* USER CODE BEGIN I2C1_Init 0 */

	/* USER CODE END I2C1_Init 0 */

	/* USER CODE BEGIN I2C1_Init 1 */

	/* USER CODE END I2C1_Init 1 */
	hi2c1.Instance = I2C1;
	hi2c1.Init.Timing = 0x30909DEC;
	hi2c1.Init.OwnAddress1 = 0;
	hi2c1.Init.AddressingMode = I2C_ADDRESSINGMODE_7BIT;
	hi2c1.Init.DualAddressMode = I2C_DUALADDRESS_DISABLE;
	hi2c1.Init.OwnAddress2 = 0;
	hi2c1.Init.OwnAddress2Masks = I2C_OA2_NOMASK;
	hi2c1.Init.GeneralCallMode = I2C_GENERALCALL_DISABLE;
	hi2c1.Init.NoStretchMode = I2C_NOSTRETCH_DISABLE;
	if (HAL_I2C_Init(&hi2c1) != HAL_OK) {
		Error_Handler();
	}

	/** Configure Analogue filter
	 */
	if (HAL_I2CEx_ConfigAnalogFilter(&hi2c1, I2C_ANALOGFILTER_ENABLE)
			!= HAL_OK) {
		Error_Handler();
	}

	/** Configure Digital filter
	 */
	if (HAL_I2CEx_ConfigDigitalFilter(&hi2c1, 0) != HAL_OK) {
		Error_Handler();
	}
	/* USER CODE BEGIN I2C1_Init 2 */

	/* USER CODE END I2C1_Init 2 */

}

/**
 * @brief I2C2 Initialization Function
 * @param None
 * @retval None
 */
static void MX_I2C2_Init(void) {

	/* USER CODE BEGIN I2C2_Init 0 */

	/* USER CODE END I2C2_Init 0 */

	/* USER CODE BEGIN I2C2_Init 1 */

	/* USER CODE END I2C2_Init 1 */
	hi2c2.Instance = I2C2;
	hi2c2.Init.Timing = 0x30909DEC;
	hi2c2.Init.OwnAddress1 = 0;
	hi2c2.Init.AddressingMode = I2C_ADDRESSINGMODE_7BIT;
	hi2c2.Init.DualAddressMode = I2C_DUALADDRESS_DISABLE;
	hi2c2.Init.OwnAddress2 = 0;
	hi2c2.Init.OwnAddress2Masks = I2C_OA2_NOMASK;
	hi2c2.Init.GeneralCallMode = I2C_GENERALCALL_DISABLE;
	hi2c2.Init.NoStretchMode = I2C_NOSTRETCH_DISABLE;
	if (HAL_I2C_Init(&hi2c2) != HAL_OK) {
		Error_Handler();
	}

	/** Configure Analogue filter
	 */
	if (HAL_I2CEx_ConfigAnalogFilter(&hi2c2, I2C_ANALOGFILTER_ENABLE)
			!= HAL_OK) {
		Error_Handler();
	}

	/** Configure Digital filter
	 */
	if (HAL_I2CEx_ConfigDigitalFilter(&hi2c2, 0) != HAL_OK) {
		Error_Handler();
	}
	/* USER CODE BEGIN I2C2_Init 2 */

	/* USER CODE END I2C2_Init 2 */

}

/**
 * @brief ICACHE Initialization Function
 * @param None
 * @retval None
 */
static void MX_ICACHE_Init(void) {

	/* USER CODE BEGIN ICACHE_Init 0 */

	/* USER CODE END ICACHE_Init 0 */

	/* USER CODE BEGIN ICACHE_Init 1 */

	/* USER CODE END ICACHE_Init 1 */

	/** Enable instruction cache in 1-way (direct mapped cache)
	 */
	if (HAL_ICACHE_ConfigAssociativityMode(ICACHE_1WAY) != HAL_OK) {
		Error_Handler();
	}
	if (HAL_ICACHE_Enable() != HAL_OK) {
		Error_Handler();
	}
	/* USER CODE BEGIN ICACHE_Init 2 */

	/* USER CODE END ICACHE_Init 2 */

}

/**
 * @brief OCTOSPI1 Initialization Function
 * @param None
 * @retval None
 */
static void MX_OCTOSPI1_Init(void) {

	/* USER CODE BEGIN OCTOSPI1_Init 0 */

	/* USER CODE END OCTOSPI1_Init 0 */

	OSPIM_CfgTypeDef sOspiManagerCfg = { 0 };
	HAL_OSPI_DLYB_CfgTypeDef HAL_OSPI_DLYB_Cfg_Struct = { 0 };

	/* USER CODE BEGIN OCTOSPI1_Init 1 */

	/* USER CODE END OCTOSPI1_Init 1 */
	/* OCTOSPI1 parameter configuration*/
	hospi1.Instance = OCTOSPI1;
	hospi1.Init.FifoThreshold = 1;
	hospi1.Init.DualQuad = HAL_OSPI_DUALQUAD_DISABLE;
	hospi1.Init.MemoryType = HAL_OSPI_MEMTYPE_APMEMORY;
	hospi1.Init.DeviceSize = 23;
	hospi1.Init.ChipSelectHighTime = 1;
	hospi1.Init.FreeRunningClock = HAL_OSPI_FREERUNCLK_DISABLE;
	hospi1.Init.ClockMode = HAL_OSPI_CLOCK_MODE_0;
	hospi1.Init.WrapSize = HAL_OSPI_WRAP_NOT_SUPPORTED;
	hospi1.Init.ClockPrescaler = 2;
	hospi1.Init.SampleShifting = HAL_OSPI_SAMPLE_SHIFTING_NONE;
	hospi1.Init.DelayHoldQuarterCycle = HAL_OSPI_DHQC_ENABLE;
	hospi1.Init.ChipSelectBoundary = 10;
	hospi1.Init.DelayBlockBypass = HAL_OSPI_DELAY_BLOCK_USED;
	hospi1.Init.MaxTran = 0;
	hospi1.Init.Refresh = 100;
	if (HAL_OSPI_Init(&hospi1) != HAL_OK) {
		Error_Handler();
	}
	sOspiManagerCfg.ClkPort = 1;
	sOspiManagerCfg.DQSPort = 1;
	sOspiManagerCfg.NCSPort = 1;
	sOspiManagerCfg.IOLowPort = HAL_OSPIM_IOPORT_1_LOW;
	sOspiManagerCfg.IOHighPort = HAL_OSPIM_IOPORT_1_HIGH;
	if (HAL_OSPIM_Config(&hospi1, &sOspiManagerCfg,
	HAL_OSPI_TIMEOUT_DEFAULT_VALUE) != HAL_OK) {
		Error_Handler();
	}
	HAL_OSPI_DLYB_Cfg_Struct.Units = 0;
	HAL_OSPI_DLYB_Cfg_Struct.PhaseSel = 0;
	if (HAL_OSPI_DLYB_SetConfig(&hospi1, &HAL_OSPI_DLYB_Cfg_Struct) != HAL_OK) {
		Error_Handler();
	}
	/* USER CODE BEGIN OCTOSPI1_Init 2 */

	/* USER CODE END OCTOSPI1_Init 2 */

}

/**
 * @brief OCTOSPI2 Initialization Function
 * @param None
 * @retval None
 */
static void MX_OCTOSPI2_Init(void) {

	/* USER CODE BEGIN OCTOSPI2_Init 0 */

	/* USER CODE END OCTOSPI2_Init 0 */

	OSPIM_CfgTypeDef sOspiManagerCfg = { 0 };
	HAL_OSPI_DLYB_CfgTypeDef HAL_OSPI_DLYB_Cfg_Struct = { 0 };

	/* USER CODE BEGIN OCTOSPI2_Init 1 */

	/* USER CODE END OCTOSPI2_Init 1 */
	/* OCTOSPI2 parameter configuration*/
	hospi2.Instance = OCTOSPI2;
	hospi2.Init.FifoThreshold = 4;
	hospi2.Init.DualQuad = HAL_OSPI_DUALQUAD_DISABLE;
	hospi2.Init.MemoryType = HAL_OSPI_MEMTYPE_MACRONIX;
	hospi2.Init.DeviceSize = 26;
	hospi2.Init.ChipSelectHighTime = 2;
	hospi2.Init.FreeRunningClock = HAL_OSPI_FREERUNCLK_DISABLE;
	hospi2.Init.ClockMode = HAL_OSPI_CLOCK_MODE_0;
	hospi2.Init.WrapSize = HAL_OSPI_WRAP_NOT_SUPPORTED;
	hospi2.Init.ClockPrescaler = 4;
	hospi2.Init.SampleShifting = HAL_OSPI_SAMPLE_SHIFTING_NONE;
	hospi2.Init.DelayHoldQuarterCycle = HAL_OSPI_DHQC_ENABLE;
	hospi2.Init.ChipSelectBoundary = 0;
	hospi2.Init.DelayBlockBypass = HAL_OSPI_DELAY_BLOCK_USED;
	hospi2.Init.MaxTran = 0;
	hospi2.Init.Refresh = 0;
	if (HAL_OSPI_Init(&hospi2) != HAL_OK) {
		Error_Handler();
	}
	sOspiManagerCfg.ClkPort = 2;
	sOspiManagerCfg.DQSPort = 2;
	sOspiManagerCfg.NCSPort = 2;
	sOspiManagerCfg.IOLowPort = HAL_OSPIM_IOPORT_2_LOW;
	sOspiManagerCfg.IOHighPort = HAL_OSPIM_IOPORT_2_HIGH;
	if (HAL_OSPIM_Config(&hospi2, &sOspiManagerCfg,
	HAL_OSPI_TIMEOUT_DEFAULT_VALUE) != HAL_OK) {
		Error_Handler();
	}
	HAL_OSPI_DLYB_Cfg_Struct.Units = 0;
	HAL_OSPI_DLYB_Cfg_Struct.PhaseSel = 0;
	if (HAL_OSPI_DLYB_SetConfig(&hospi2, &HAL_OSPI_DLYB_Cfg_Struct) != HAL_OK) {
		Error_Handler();
	}
	/* USER CODE BEGIN OCTOSPI2_Init 2 */

	/* USER CODE END OCTOSPI2_Init 2 */

}

/**
 * @brief SPI2 Initialization Function
 * @param None
 * @retval None
 */
static void MX_SPI2_Init(void) {

	/* USER CODE BEGIN SPI2_Init 0 */

	/* USER CODE END SPI2_Init 0 */

	SPI_AutonomousModeConfTypeDef HAL_SPI_AutonomousMode_Cfg_Struct = { 0 };

	/* USER CODE BEGIN SPI2_Init 1 */

	/* USER CODE END SPI2_Init 1 */
	/* SPI2 parameter configuration*/
	hspi2.Instance = SPI2;
	hspi2.Init.Mode = SPI_MODE_MASTER;
	hspi2.Init.Direction = SPI_DIRECTION_2LINES;
	hspi2.Init.DataSize = SPI_DATASIZE_4BIT;
	hspi2.Init.CLKPolarity = SPI_POLARITY_LOW;
	hspi2.Init.CLKPhase = SPI_PHASE_1EDGE;
	hspi2.Init.NSS = SPI_NSS_HARD_OUTPUT;
	hspi2.Init.BaudRatePrescaler = SPI_BAUDRATEPRESCALER_2;
	hspi2.Init.FirstBit = SPI_FIRSTBIT_MSB;
	hspi2.Init.TIMode = SPI_TIMODE_DISABLE;
	hspi2.Init.CRCCalculation = SPI_CRCCALCULATION_DISABLE;
	hspi2.Init.CRCPolynomial = 0x7;
	hspi2.Init.NSSPMode = SPI_NSS_PULSE_ENABLE;
	hspi2.Init.NSSPolarity = SPI_NSS_POLARITY_LOW;
	hspi2.Init.FifoThreshold = SPI_FIFO_THRESHOLD_01DATA;
	hspi2.Init.MasterSSIdleness = SPI_MASTER_SS_IDLENESS_00CYCLE;
	hspi2.Init.MasterInterDataIdleness = SPI_MASTER_INTERDATA_IDLENESS_00CYCLE;
	hspi2.Init.MasterReceiverAutoSusp = SPI_MASTER_RX_AUTOSUSP_DISABLE;
	hspi2.Init.MasterKeepIOState = SPI_MASTER_KEEP_IO_STATE_DISABLE;
	hspi2.Init.IOSwap = SPI_IO_SWAP_DISABLE;
	hspi2.Init.ReadyMasterManagement = SPI_RDY_MASTER_MANAGEMENT_INTERNALLY;
	hspi2.Init.ReadyPolarity = SPI_RDY_POLARITY_HIGH;
	if (HAL_SPI_Init(&hspi2) != HAL_OK) {
		Error_Handler();
	}
	HAL_SPI_AutonomousMode_Cfg_Struct.TriggerState = SPI_AUTO_MODE_DISABLE;
	HAL_SPI_AutonomousMode_Cfg_Struct.TriggerSelection =
	SPI_GRP1_GPDMA_CH0_TCF_TRG;
	HAL_SPI_AutonomousMode_Cfg_Struct.TriggerPolarity =
	SPI_TRIG_POLARITY_RISING;
	if (HAL_SPIEx_SetConfigAutonomousMode(&hspi2,
			&HAL_SPI_AutonomousMode_Cfg_Struct) != HAL_OK) {
		Error_Handler();
	}
	/* USER CODE BEGIN SPI2_Init 2 */

	/* USER CODE END SPI2_Init 2 */

}

/**
 * @brief UART4 Initialization Function
 * @param None
 * @retval None
 */
static void MX_UART4_Init(void) {

	/* USER CODE BEGIN UART4_Init 0 */

	/* USER CODE END UART4_Init 0 */

	/* USER CODE BEGIN UART4_Init 1 */

	/* USER CODE END UART4_Init 1 */
	huart4.Instance = UART4;
	huart4.Init.BaudRate = 115200;
	huart4.Init.WordLength = UART_WORDLENGTH_8B;
	huart4.Init.StopBits = UART_STOPBITS_1;
	huart4.Init.Parity = UART_PARITY_NONE;
	huart4.Init.Mode = UART_MODE_TX_RX;
	huart4.Init.HwFlowCtl = UART_HWCONTROL_NONE;
	huart4.Init.OverSampling = UART_OVERSAMPLING_16;
	huart4.Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
	huart4.Init.ClockPrescaler = UART_PRESCALER_DIV1;
	huart4.AdvancedInit.AdvFeatureInit = UART_ADVFEATURE_NO_INIT;
	if (HAL_UART_Init(&huart4) != HAL_OK) {
		Error_Handler();
	}
	if (HAL_UARTEx_SetTxFifoThreshold(&huart4, UART_TXFIFO_THRESHOLD_1_8)
			!= HAL_OK) {
		Error_Handler();
	}
	if (HAL_UARTEx_SetRxFifoThreshold(&huart4, UART_RXFIFO_THRESHOLD_1_8)
			!= HAL_OK) {
		Error_Handler();
	}
	if (HAL_UARTEx_DisableFifoMode(&huart4) != HAL_OK) {
		Error_Handler();
	}
	/* USER CODE BEGIN UART4_Init 2 */

	/* USER CODE END UART4_Init 2 */

}

/**
 * @brief USART1 Initialization Function
 * @param None
 * @retval None
 */
static void MX_USART1_UART_Init(void) {

	/* USER CODE BEGIN USART1_Init 0 */

	/* USER CODE END USART1_Init 0 */

	/* USER CODE BEGIN USART1_Init 1 */

	/* USER CODE END USART1_Init 1 */
	huart1.Instance = USART1;
	huart1.Init.BaudRate = 115200;
	huart1.Init.WordLength = UART_WORDLENGTH_8B;
	huart1.Init.StopBits = UART_STOPBITS_1;
	huart1.Init.Parity = UART_PARITY_NONE;
	huart1.Init.Mode = UART_MODE_TX_RX;
	huart1.Init.HwFlowCtl = UART_HWCONTROL_NONE;
	huart1.Init.OverSampling = UART_OVERSAMPLING_16;
	huart1.Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
	huart1.Init.ClockPrescaler = UART_PRESCALER_DIV1;
	huart1.AdvancedInit.AdvFeatureInit = UART_ADVFEATURE_NO_INIT;
	if (HAL_UART_Init(&huart1) != HAL_OK) {
		Error_Handler();
	}
	if (HAL_UARTEx_SetTxFifoThreshold(&huart1, UART_TXFIFO_THRESHOLD_1_8)
			!= HAL_OK) {
		Error_Handler();
	}
	if (HAL_UARTEx_SetRxFifoThreshold(&huart1, UART_RXFIFO_THRESHOLD_1_8)
			!= HAL_OK) {
		Error_Handler();
	}
	if (HAL_UARTEx_DisableFifoMode(&huart1) != HAL_OK) {
		Error_Handler();
	}
	/* USER CODE BEGIN USART1_Init 2 */

	/* USER CODE END USART1_Init 2 */

}

/**
 * @brief UCPD1 Initialization Function
 * @param None
 * @retval None
 */
static void MX_UCPD1_Init(void) {

	/* USER CODE BEGIN UCPD1_Init 0 */

	/* USER CODE END UCPD1_Init 0 */

	LL_GPIO_InitTypeDef GPIO_InitStruct = { 0 };

	/* Peripheral clock enable */
	LL_APB1_GRP2_EnableClock(LL_APB1_GRP2_PERIPH_UCPD1);

	LL_AHB2_GRP1_EnableClock(LL_AHB2_GRP1_PERIPH_GPIOA);
	LL_AHB2_GRP1_EnableClock(LL_AHB2_GRP1_PERIPH_GPIOB);
	/**UCPD1 GPIO Configuration
	 PA15 (JTDI)   ------> UCPD1_CC1
	 PB15   ------> UCPD1_CC2
	 */
	GPIO_InitStruct.Pin = LL_GPIO_PIN_15;
	GPIO_InitStruct.Mode = LL_GPIO_MODE_ANALOG;
	GPIO_InitStruct.Pull = LL_GPIO_PULL_NO;
	LL_GPIO_Init(GPIOA, &GPIO_InitStruct);

	GPIO_InitStruct.Pin = LL_GPIO_PIN_15;
	GPIO_InitStruct.Mode = LL_GPIO_MODE_ANALOG;
	GPIO_InitStruct.Pull = LL_GPIO_PULL_NO;
	LL_GPIO_Init(GPIOB, &GPIO_InitStruct);

	/* USER CODE BEGIN UCPD1_Init 1 */

	/* USER CODE END UCPD1_Init 1 */
	/* USER CODE BEGIN UCPD1_Init 2 */

	/* USER CODE END UCPD1_Init 2 */

}

/**
 * @brief USB_OTG_FS Initialization Function
 * @param None
 * @retval None
 */
static void MX_USB_OTG_FS_PCD_Init(void) {

	/* USER CODE BEGIN USB_OTG_FS_Init 0 */

	/* USER CODE END USB_OTG_FS_Init 0 */

	/* USER CODE BEGIN USB_OTG_FS_Init 1 */

	/* USER CODE END USB_OTG_FS_Init 1 */
	hpcd_USB_OTG_FS.Instance = USB_OTG_FS;
	hpcd_USB_OTG_FS.Init.dev_endpoints = 6;
	hpcd_USB_OTG_FS.Init.speed = PCD_SPEED_FULL;
	hpcd_USB_OTG_FS.Init.phy_itface = PCD_PHY_EMBEDDED;
	hpcd_USB_OTG_FS.Init.Sof_enable = DISABLE;
	hpcd_USB_OTG_FS.Init.low_power_enable = DISABLE;
	hpcd_USB_OTG_FS.Init.lpm_enable = DISABLE;
	hpcd_USB_OTG_FS.Init.battery_charging_enable = DISABLE;
	hpcd_USB_OTG_FS.Init.use_dedicated_ep1 = DISABLE;
	hpcd_USB_OTG_FS.Init.vbus_sensing_enable = DISABLE;
	hpcd_USB_OTG_FS.Init.dma_enable = DISABLE;
	if (HAL_PCD_Init(&hpcd_USB_OTG_FS) != HAL_OK) {
		Error_Handler();
	}
	/* USER CODE BEGIN USB_OTG_FS_Init 2 */

	/* USER CODE END USB_OTG_FS_Init 2 */

}

/**
 * @brief GPIO Initialization Function
 * @param None
 * @retval None
 */
static void MX_GPIO_Init(void) {
	GPIO_InitTypeDef GPIO_InitStruct = { 0 };
	/* USER CODE BEGIN MX_GPIO_Init_1 */

	/* USER CODE END MX_GPIO_Init_1 */

	/* GPIO Ports Clock Enable */
	__HAL_RCC_GPIOG_CLK_ENABLE();
	__HAL_RCC_GPIOC_CLK_ENABLE();
	__HAL_RCC_GPIOA_CLK_ENABLE();
	__HAL_RCC_GPIOI_CLK_ENABLE();
	__HAL_RCC_GPIOH_CLK_ENABLE();
	__HAL_RCC_GPIOB_CLK_ENABLE();
	__HAL_RCC_GPIOD_CLK_ENABLE();
	__HAL_RCC_GPIOE_CLK_ENABLE();
	__HAL_RCC_GPIOF_CLK_ENABLE();

	/*Configure GPIO pin Output Level */
	HAL_GPIO_WritePin(UCPD_PWR_GPIO_Port, UCPD_PWR_Pin, GPIO_PIN_RESET);

	/*Configure GPIO pin Output Level */
	HAL_GPIO_WritePin(GPIOH, LED_RED_Pin | LED_GREEN_Pin | Mems_VL53_xshut_Pin,
			GPIO_PIN_RESET);

	/*Configure GPIO pin Output Level */
	HAL_GPIO_WritePin(WRLS_WKUP_B_GPIO_Port, WRLS_WKUP_B_Pin, GPIO_PIN_RESET);

	/*Configure GPIO pin Output Level */
	HAL_GPIO_WritePin(GPIOF, Mems_STSAFE_RESET_Pin | WRLS_WKUP_W_Pin,
			GPIO_PIN_RESET);

	/*Configure GPIO pins : WRLS_FLOW_Pin Mems_VLX_GPIO_Pin Mems_INT_LPS22HH_Pin */
	GPIO_InitStruct.Pin = WRLS_FLOW_Pin | Mems_VLX_GPIO_Pin
			| Mems_INT_LPS22HH_Pin;
	GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
	GPIO_InitStruct.Pull = GPIO_NOPULL;
	HAL_GPIO_Init(GPIOG, &GPIO_InitStruct);

	/*Configure GPIO pin : PH3_BOOT0_Pin */
	GPIO_InitStruct.Pin = PH3_BOOT0_Pin;
	GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
	GPIO_InitStruct.Pull = GPIO_NOPULL;
	HAL_GPIO_Init(PH3_BOOT0_GPIO_Port, &GPIO_InitStruct);

	/*Configure GPIO pin : UCPD_PWR_Pin */
	GPIO_InitStruct.Pin = UCPD_PWR_Pin;
	GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
	GPIO_InitStruct.Pull = GPIO_NOPULL;
	GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
	HAL_GPIO_Init(UCPD_PWR_GPIO_Port, &GPIO_InitStruct);

	/*Configure GPIO pin : USER_Button_Pin */
	GPIO_InitStruct.Pin = USER_Button_Pin;
	GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
	GPIO_InitStruct.Pull = GPIO_NOPULL;
	HAL_GPIO_Init(USER_Button_GPIO_Port, &GPIO_InitStruct);

	/*Configure GPIO pins : LED_RED_Pin LED_GREEN_Pin Mems_VL53_xshut_Pin */
	GPIO_InitStruct.Pin = LED_RED_Pin | LED_GREEN_Pin | Mems_VL53_xshut_Pin;
	GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
	GPIO_InitStruct.Pull = GPIO_NOPULL;
	GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
	HAL_GPIO_Init(GPIOH, &GPIO_InitStruct);

	/*Configure GPIO pin : MIC_CCK1_Pin */
	GPIO_InitStruct.Pin = MIC_CCK1_Pin;
	GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
	GPIO_InitStruct.Pull = GPIO_NOPULL;
	GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
	GPIO_InitStruct.Alternate = GPIO_AF6_MDF1;
	HAL_GPIO_Init(MIC_CCK1_GPIO_Port, &GPIO_InitStruct);

	/*Configure GPIO pin : WRLS_WKUP_B_Pin */
	GPIO_InitStruct.Pin = WRLS_WKUP_B_Pin;
	GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
	GPIO_InitStruct.Pull = GPIO_NOPULL;
	GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
	HAL_GPIO_Init(WRLS_WKUP_B_GPIO_Port, &GPIO_InitStruct);

	/*Configure GPIO pins : WRLS_NOTIFY_Pin Mems_INT_IIS2MDC_Pin USB_IANA_Pin */
	GPIO_InitStruct.Pin = WRLS_NOTIFY_Pin | Mems_INT_IIS2MDC_Pin | USB_IANA_Pin;
	GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
	GPIO_InitStruct.Pull = GPIO_NOPULL;
	HAL_GPIO_Init(GPIOD, &GPIO_InitStruct);

	/*Configure GPIO pins : USB_UCPD_FLT_Pin Mems_ISM330DLC_INT1_Pin */
	GPIO_InitStruct.Pin = USB_UCPD_FLT_Pin | Mems_ISM330DLC_INT1_Pin;
	GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
	GPIO_InitStruct.Pull = GPIO_NOPULL;
	HAL_GPIO_Init(GPIOE, &GPIO_InitStruct);

	/*Configure GPIO pin : USB_VBUS_SENSE_Pin */
	GPIO_InitStruct.Pin = USB_VBUS_SENSE_Pin;
	GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
	GPIO_InitStruct.Pull = GPIO_NOPULL;
	HAL_GPIO_Init(USB_VBUS_SENSE_GPIO_Port, &GPIO_InitStruct);

	/*Configure GPIO pins : Mems_STSAFE_RESET_Pin WRLS_WKUP_W_Pin */
	GPIO_InitStruct.Pin = Mems_STSAFE_RESET_Pin | WRLS_WKUP_W_Pin;
	GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
	GPIO_InitStruct.Pull = GPIO_NOPULL;
	GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
	HAL_GPIO_Init(GPIOF, &GPIO_InitStruct);

	/*Configure GPIO pin : MIC_SDIN0_Pin */
	GPIO_InitStruct.Pin = MIC_SDIN0_Pin;
	GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
	GPIO_InitStruct.Pull = GPIO_NOPULL;
	GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
	GPIO_InitStruct.Alternate = GPIO_AF6_MDF1;
	HAL_GPIO_Init(MIC_SDIN0_GPIO_Port, &GPIO_InitStruct);

	/* USER CODE BEGIN MX_GPIO_Init_2 */

	/*Re-configure GPIO pin : Mems_ISM330DLC_INT1_Pin (IMU data-ready) */
	GPIO_InitStruct.Pin = Mems_ISM330DLC_INT1_Pin;
	GPIO_InitStruct.Mode = GPIO_MODE_IT_RISING;
	GPIO_InitStruct.Pull = GPIO_NOPULL;
	HAL_GPIO_Init(Mems_ISM330DLC_INT1_GPIO_Port, &GPIO_InitStruct);

	/* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */
void HAL_GPIO_EXTI_Rising_Callback(uint16_t GPIO_Pin) {
	if (GPIO_Pin == Mems_ISM330DLC_INT1_Pin) {
		imu_drdy_count++;
	}
}

int __io_putchar(int ch) {
	HAL_UART_Transmit(&huart1, (uint8_t*) &ch, 1, HAL_MAX_DELAY);
	return ch;
}
/* USER CODE END 4 */

/**
 * @brief  This function is executed in case of error occurrence.
 * @param None
 * @retval None
 */
void Error_Handler(void) {
	/* USER CODE BEGIN Error_Handler_Debug */
	/* User can add his own implementation to report the HAL error return state */
	__disable_irq();
	while (1) {
	}
	/* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
