/*
 * channel.c - "capacidade do slot" como função substituível.
 *
 * Sem traço: valor fixo (--prbs). Com traço (--trace): lê um CSV gerado
 * por channel/channel_model.py, formato "slot,prbs" com cabeçalho. O traço
 * é reutilizado em loop se a simulação for mais longa que ele.
 */
#include <stdio.h>
#include <stdlib.h>

#include "sim.h"

int channel_load_trace(sim_t *s, const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) return -1;

    int cap = 1024, n = 0;
    int *v = malloc(cap * sizeof *v);
    char line[128];
    fgets(line, sizeof line, f); /* cabeçalho */
    while (fgets(line, sizeof line, f)) {
        int slot, prbs;
        if (sscanf(line, "%d,%d", &slot, &prbs) != 2) continue;
        if (n == cap) v = realloc(v, (cap *= 2) * sizeof *v);
        v[n++] = prbs;
    }
    fclose(f);
    if (n == 0) {
        free(v);
        return -1;
    }
    s->trace = v;
    s->trace_len = n;
    return 0;
}

int channel_slot_prbs(const sim_t *s, long slot) {
    if (s->trace) return s->trace[slot % s->trace_len];
    return s->cfg.prbs_per_slot;
}
