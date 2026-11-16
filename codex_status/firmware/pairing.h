#ifndef CODEX_PAIRING_H
#define CODEX_PAIRING_H
#include "app.h"
#include "app_security.h"
void pairing_init(void);
void pairing_new_code(void);
void pairing_address(struct bd_addr *);
void pairing_advertise(void);
void pairing_tk(uint8_t, const struct gapc_bond_req_ind *);
void pairing_bdb_init(void);
void pairing_bdb_add(struct app_sec_bond_data_env_tag *);
void pairing_forget(void);
void pairing_flash_open(void);
extern char pairing_code[16];
#endif
