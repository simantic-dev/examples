/* SOEM EtherCAT MainDevice on the S32K344 EMAC (Zephyr AF_PACKET): ec_init, ec_config_init, map, SAFEOP, OP,
 * CYCLES cyclic LRW at 1 ms with a WKC and echo check, then a summary on the console. The SubDevices'
 * inputs echo their outputs one cycle later (peers/eth/ethercat_sub.py). */
#include <stdio.h>
#include <string.h>
#include <zephyr/kernel.h>
#include "ethercat.h"

#define CYCLES 200

static char iomap[4096];

static int report_states(void)
{
	int bad = 0;

	ec_readstate();
	for (int i = 1; i <= ec_slavecount; i++) {
		printf("ecat: slave %d state 0x%02x alstatuscode 0x%04x\n", i, ec_slave[i].state,
		       ec_slave[i].ALstatuscode);
		bad += ec_slave[i].state != EC_STATE_OPERATIONAL;
	}
	return bad;
}

static uint8_t pattern(int slave, int j, int cycle)
{
	return (uint8_t)(cycle * 7 + slave * 16 + j);
}

int main(void)
{
	int lost = 0, badwkc = 0, echo_err = 0, ok = 0, not_op;

	printf("simantic ecat-main: SOEM on S32K344 EMAC\n");
	if (!ec_init("eth0") || ec_config_init(FALSE) <= 0) {
		printf("ecat: init failed, slaves %d\n", ec_slavecount);
		printf("ecat: RESULT: FAIL\n");
		return 0;
	}
	printf("ecat: slaves %d\n", ec_slavecount);
	ec_config_map(iomap);
	for (int i = 1; i <= ec_slavecount; i++) {
		printf("ecat: slave %d vendor 0x%x product 0x%x out %d in %d\n", i, (unsigned)ec_slave[i].eep_man,
		       (unsigned)ec_slave[i].eep_id, (int)ec_slave[i].Obytes, (int)ec_slave[i].Ibytes);
	}
	int expected = ec_group[0].outputsWKC * 2 + ec_group[0].inputsWKC;

	printf("ecat: map out %d in %d expected wkc %d\n", (int)ec_group[0].Obytes, (int)ec_group[0].Ibytes, expected);
	ec_statecheck(0, EC_STATE_SAFE_OP, EC_TIMEOUTSTATE * 4);
	printf("ecat: lowest state 0x%02x\n", ec_slave[0].state);

	ec_slave[0].state = EC_STATE_OPERATIONAL;
	ec_send_processdata();
	ec_receive_processdata(EC_TIMEOUTRET);
	ec_writestate(0);
	for (int chk = 200; chk > 0 && ec_slave[0].state != EC_STATE_OPERATIONAL; chk--) {
		ec_send_processdata();
		ec_receive_processdata(EC_TIMEOUTRET);
		ec_statecheck(0, EC_STATE_OPERATIONAL, 50000);
	}
	not_op = report_states();
	if (not_op) {
		printf("ecat: %d of %d slaves not in OP\n", not_op, ec_slavecount);
	}

	for (int c = 0; c < CYCLES; c++) {
		for (int i = 1; i <= ec_slavecount; i++) {
			for (int j = 0; j < ec_slave[i].Obytes; j++) {
				ec_slave[i].outputs[j] = pattern(i, j, c);
			}
		}
		ec_send_processdata();
		int wkc = ec_receive_processdata(EC_TIMEOUTRET);

		if (wkc == EC_NOFRAME) {
			lost++;
		} else if (wkc != expected) {
			badwkc++;
		} else {
			ok++;
			for (int i = 1; i <= ec_slavecount && c > 0; i++) {
				for (int j = 0; j < ec_slave[i].Ibytes && j < ec_slave[i].Obytes; j++) {
					echo_err += ec_slave[i].inputs[j] != pattern(i, j, c - 1);
				}
			}
		}
		k_msleep(1);
	}
	printf("ecat: cycles %d ok %d lost %d badwkc %d echo_err %d\n", CYCLES, ok, lost, badwkc, echo_err);
	ec_close();
	printf("ecat: RESULT: %s\n", (!not_op && !lost && !badwkc && !echo_err) ? "PASS" : "FAIL");
	return 0;
}
