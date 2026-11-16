#ifndef CODEX_APP_H
#define CODEX_APP_H
#include "app.h"
#include "app_callback.h"
#include "app_default_handlers.h"
#include "arch_api.h"
void user_app_init(void);
void user_suota_status(uint8_t);
void user_app_paired(uint8_t);
void user_app_encrypted(uint8_t,uint8_t);
void user_app_db_init_complete(void);
void user_app_adv_start(void);
void user_app_connection(uint8_t, struct gapc_connection_req_ind const *);
void user_app_disconnect(struct gapc_disconnect_ind const *);
void user_app_adv_undirect_complete(uint8_t);
void user_catch_rest_hndl(ke_msg_id_t, void const *, ke_task_id_t, ke_task_id_t);
arch_main_loop_callback_ret_t user_app_system_powered(void);
#endif
