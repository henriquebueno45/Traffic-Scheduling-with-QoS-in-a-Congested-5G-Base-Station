/*
 * policy.c - políticas de escalonamento: fifo, prio, dwrr.
 * Todas rodam com o mutex da simulação travado.
 */
#include "policy.h"

#include <limits.h>
#include <string.h>

/* ---------- FIFO: atende o pacote mais antigo entre todas as filas ---------- */
static int fifo_pick(sim_t *s, int *limit) {
    int best = -1;
    int64_t best_arrival = INT64_MAX;
    for (int c = 0; c < NCLASSES; c++) {
        if (q_empty(&s->q[c])) continue;
        int64_t a = s->pkts[q_front(&s->q[c])].arrival_ns;
        if (a < best_arrival) {
            best_arrival = a;
            best = c;
        }
    }
    *limit = INT_MAX;
    return best;
}

/* ---------- EDF (Earliest Deadline First): prazo mais próximo primeiro ----------
 * Igual ao FIFO, mas compara o PRAZO ABSOLUTO (chegada + prazo da classe) em vez
 * da chegada. Dentro de cada classe os prazos crescem com a chegada, então basta
 * olhar o primeiro pacote de cada fila. Voz (prazo 20 ms) tende a ir na frente,
 * mas um pacote de dados muito antigo acaba ganhando de voz recém-chegada
 * (prazo dele fica mais próximo), o que evita starvation. */
static int edf_pick(sim_t *s, int *limit) {
    int best = -1;
    int64_t best_deadline = INT64_MAX;
    for (int c = 0; c < NCLASSES; c++) {
        if (q_empty(&s->q[c])) continue;
        int64_t d = s->pkts[q_front(&s->q[c])].deadline_ns;
        if (d < best_deadline) {
            best_deadline = d;
            best = c;
        }
    }
    *limit = INT_MAX;
    return best;
}

/* ---------- Prioridade estrita: voz > vídeo > dados ---------- */
static int prio_pick(sim_t *s, int *limit) {
    *limit = INT_MAX;
    for (int c = 0; c < NCLASSES; c++)
        if (!q_empty(&s->q[c])) return c;
    return -1;
}

/* ---------- DWRR: cada classe ganha um "quantum" de PRBs por slot ----------
 * Pesos 4:4:2 sobre 50 PRBs => voz 20, vídeo 20, dados 10 (por slot).
 * A classe só pode usar seu crédito (deficit); se sobrar orçamento e todos
 * os créditos acabaram, atende quem tiver fila (conserva trabalho).
 */
static const int DWRR_QUANTUM[NCLASSES] = {20, 20, 10};

static void dwrr_slot_start(sim_t *s) {
    for (int c = 0; c < NCLASSES; c++) {
        if (q_empty(&s->q[c]))
            s->deficit[c] = 0; /* sem fila, sem crédito acumulado */
        else
            s->deficit[c] += DWRR_QUANTUM[c];
    }
}

static int dwrr_pick(sim_t *s, int *limit) {
    for (int i = 0; i < NCLASSES; i++) { /* 1ª passada: quem tem crédito */
        int c = (s->rr_next + i) % NCLASSES;
        if (!q_empty(&s->q[c]) && s->deficit[c] > 0) {
            *limit = s->deficit[c];
            return c;
        }
    }
    for (int i = 0; i < NCLASSES; i++) { /* 2ª passada: conserva trabalho */
        int c = (s->rr_next + i) % NCLASSES;
        if (!q_empty(&s->q[c])) {
            *limit = INT_MAX;
            return c;
        }
    }
    return -1;
}

static void dwrr_served(sim_t *s, int cls, int prbs) {
    s->deficit[cls] -= prbs;
    if (s->deficit[cls] <= 0) s->rr_next = (cls + 1) % NCLASSES;
}

static void noop_slot_start(sim_t *s) { (void)s; }
static void noop_served(sim_t *s, int cls, int prbs) {
    (void)s; (void)cls; (void)prbs;
}

/* ---------- Prioridade estrita com PISO (prio_floor) ----------
 * Igual à prio, mas vídeo e dados têm um mínimo garantido de PRBs POR SLOT
 * (--floor-video, --floor-data), atendido ANTES da voz. Evita starvation ao custo
 * de tirar esses PRBs da voz. Reaproveita `deficit[]` como crédito do piso do slot.
 * Todo serviço recebido (inclusive o da fase de prioridade) consome o crédito. */
static void floor_slot_start(sim_t *s) {
    s->deficit[CLS_VOICE] = 0;
    s->deficit[CLS_VIDEO] = s->cfg.floor_video;
    s->deficit[CLS_DATA] = s->cfg.floor_data;
}

static int floor_pick(sim_t *s, int *limit) {
    for (int c = CLS_VIDEO; c < NCLASSES; c++) { /* fase 1: pisos */
        if (!q_empty(&s->q[c]) && s->deficit[c] > 0) {
            *limit = s->deficit[c];
            return c;
        }
    }
    return prio_pick(s, limit); /* fase 2: prioridade estrita */
}

static void floor_served(sim_t *s, int cls, int prbs) {
    if (cls != CLS_VOICE) s->deficit[cls] -= prbs;
}

static const policy_t POLICIES[] = {
    {"fifo", noop_slot_start, fifo_pick, noop_served},
    {"prio", noop_slot_start, prio_pick, noop_served},
    {"edf", noop_slot_start, edf_pick, noop_served},
    {"dwrr", dwrr_slot_start, dwrr_pick, dwrr_served},
    {"prio_floor", floor_slot_start, floor_pick, floor_served},
};

const policy_t *policy_by_name(const char *name) {
    for (size_t i = 0; i < sizeof POLICIES / sizeof POLICIES[0]; i++)
        if (strcmp(POLICIES[i].name, name) == 0) return &POLICIES[i];
    return NULL;
}
