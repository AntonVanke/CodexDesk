#include "user_periph_setup.h"
#include "gpio.h"
#include "syscntl.h"
#include "system_library.h"
void GPIO_reservations(void) {
    RESERVE_GPIO(LED_0, GPIO_PORT_0, GPIO_PIN_2, PID_GPIO);
    RESERVE_GPIO(LED_1, GPIO_PORT_2, GPIO_PIN_5, PID_GPIO);
    RESERVE_GPIO(LED_2, GPIO_PORT_2, GPIO_PIN_9, PID_GPIO);
    RESERVE_GPIO(FLASH_CS, GPIO_PORT_0, GPIO_PIN_3, PID_GPIO);
    RESERVE_GPIO(FLASH_CLK, GPIO_PORT_0, GPIO_PIN_0, PID_SPI_CLK);
    RESERVE_GPIO(FLASH_DO, GPIO_PORT_0, GPIO_PIN_6, PID_SPI_DO);
    RESERVE_GPIO(FLASH_DI, GPIO_PORT_0, GPIO_PIN_5, PID_SPI_DI);
    RESERVE_GPIO(LCD_CS, GPIO_PORT_2, GPIO_PIN_1, PID_GPIO);
    RESERVE_GPIO(LCD_AUX, GPIO_PORT_2, GPIO_PIN_3, PID_GPIO);
}
void set_pad_functions(void) {
    GPIO_ConfigurePin(GPIO_PORT_0, GPIO_PIN_2, OUTPUT, PID_GPIO, true);
    GPIO_ConfigurePin(GPIO_PORT_2, GPIO_PIN_5, OUTPUT, PID_GPIO, true);
    GPIO_ConfigurePin(GPIO_PORT_2, GPIO_PIN_9, OUTPUT, PID_GPIO, true);
    GPIO_ConfigurePin(GPIO_PORT_0, GPIO_PIN_3, OUTPUT, PID_GPIO, true);
    GPIO_ConfigurePin(GPIO_PORT_2, GPIO_PIN_1, OUTPUT, PID_GPIO, true);
    GPIO_ConfigurePin(GPIO_PORT_2, GPIO_PIN_3, OUTPUT, PID_GPIO, true);
}
void periph_init(void) {
    SetBits16(PMU_CTRL_REG, PERIPH_SLEEP, 0);
    while (!(GetWord16(SYS_STAT_REG) & PER_IS_UP)) {}
    SetBits16(CLK_16M_REG, XTAL16_BIAS_SH_ENABLE, 1);
    patch_func();
    set_pad_functions();
    GPIO_set_pad_latch_en(true);
}
