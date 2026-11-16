#include <stdio.h>
#include <string.h>
#include "pairing.h"
#include "app_easy_security.h"
#include "app_bond_db.h"
#include "app_easy_gap.h"
#include "app_prf_perm_types.h"
#include "co_math.h"
#include "spi.h"
#include "spi_flash.h"
#include "gpio.h"

static struct { uint32_t magic; struct bd_addr address; } identity;
static uint32_t pin;
char pairing_code[16];

void pairing_flash_open(void) {
    GPIO_set_pad_latch_en(true);
    GPIO_ConfigurePin(GPIO_PORT_0,GPIO_PIN_3,OUTPUT,PID_GPIO,true);
    GPIO_ConfigurePin(GPIO_PORT_0,GPIO_PIN_0,OUTPUT,PID_SPI_CLK,false);
    GPIO_ConfigurePin(GPIO_PORT_0,GPIO_PIN_6,OUTPUT,PID_SPI_DO,false);
    GPIO_ConfigurePin(GPIO_PORT_0,GPIO_PIN_5,INPUT,PID_SPI_DI,false);
    const spi_cfg_t cfg={.spi_ms=SPI_MS_MODE_MASTER,.spi_cp=SPI_CP_MODE_0,
        .spi_speed=SPI_SPEED_MODE_4MHz,.spi_wsz=SPI_MODE_8BIT,.spi_cs=SPI_CS_0,
        .spi_irq=SPI_IRQ_DISABLED,.cs_pad={GPIO_PORT_0,GPIO_PIN_3}};
    const spi_flash_cfg_t flash={0xfe,0xa14013,0x80000};
    SetWord16(SPI_CTRL_REG,0); SetWord16(SPI_CTRL_REG1,0);
    spi_initialize(&cfg); spi_flash_configure_env(&flash);
    spi_flash_release_from_power_down();
}
void pairing_new_code(void) {
    pin=app_sec_gen_tk();
    snprintf(pairing_code,sizeof(pairing_code),"%02X%02X%02X-%06lu",
        identity.address.addr[2],identity.address.addr[1],identity.address.addr[0],(unsigned long)pin);
}
void pairing_init(void) {
    uint32_t count;
    pairing_flash_open();
    spi_flash_read_data((uint8_t *)&identity,0x7e000,sizeof(identity),&count);
    if(identity.magic!=0x43445835) {
        identity.magic=0x43445835;
        for(unsigned i=0;i<6;i++) identity.address.addr[i]=(uint8_t)co_rand_word();
        identity.address.addr[5]|=0xc0;
        spi_flash_block_erase(0x7e000,SPI_FLASH_OP_SE);
        spi_flash_write_data((uint8_t *)&identity,0x7e000,sizeof(identity),&count);
    }
    pairing_new_code();
    app_set_prf_srv_perm(TASK_ID_CUSTS1,SRV_PERM_AUTH);
    app_set_prf_srv_perm(TASK_ID_SUOTAR,SRV_PERM_AUTH);
    app_easy_security_bdb_init();
}
void pairing_address(struct bd_addr *address) { *address=identity.address; }
void pairing_advertise(void) {
    struct gapm_start_advertise_cmd *cmd=app_easy_gap_undirected_advertise_get_active();
    uint8_t data[]={7,0xff,0xff,0xff,identity.address.addr[2],identity.address.addr[1],identity.address.addr[0],5};
    memcpy(cmd->info.host.adv_data+cmd->info.host.adv_data_len,data,sizeof(data));
    cmd->info.host.adv_data_len+=sizeof(data);
}
void pairing_tk(uint8_t conidx,const struct gapc_bond_req_ind *request) {
    app_easy_security_tk_exch(conidx,(uint8_t *)&pin,sizeof(pin),request->data.tk_type==GAP_TK_DISPLAY);
}
void pairing_bdb_init(void) { pairing_flash_open(); default_app_bdb_init(); }
void pairing_bdb_add(struct app_sec_bond_data_env_tag *data) { pairing_flash_open(); default_app_bdb_add_entry(data); }
void pairing_forget(void) {
    pairing_flash_open();
    default_app_bdb_remove_entry(SEARCH_BY_BDA_TYPE,REMOVE_ALL,0,0);
}
