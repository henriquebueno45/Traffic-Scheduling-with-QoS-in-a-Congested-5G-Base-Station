/*
 * policy.c - Scheduling policies: fifo, prio, edf, dwrr, and prio_floor.
 * All policies run while the simulation mutex is held.
 */
#include "policy.h"

#include <limits.h>
#include <string.h>

/* ---------- FIFO: serve the oldest packet across all queues ---------- */
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

/* ---------- EDF (Earliest Deadline First): closest deadline first ----------
 * Unlike FIFO, EDF compares the absolute deadline (arrival plus class deadline).
 * Within each class, deadlines grow with arrival, so only the first packet in
 * each queue needs to be considered. Voice (20 ms deadline) tends to remain first,
 * but a very old data packet can outrank a newly arrived voice packet, which helps
 * prevent starvation. */
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

/* ---------- Strict priority: voice > video > data ---------- */
static int prio_pick(sim_t *s, int *limit) {
    *limit = INT_MAX;
    for (int c = 0; c < NCLASSES; c++)
        if (!q_empty(&s->q[c])) return c;
    return -1;
}

/* ---------- DWRR: each class receives a PRB quantum per slot ----------
 * Weights 4:4:2 over 50 PRBs give voice 20, video 20, and data 10 per slot.
 * A class may use only its deficit credit. If budget remains after all credits
 * are exhausted, serve any queued class to conserve work.
 */
static const int DWRR_QUANTUM[NCLASSES] = {20, 20, 10};

static void dwrr_slot_start(sim_t *s) {
    for (int c = 0; c < NCLASSES; c++) {
        if (q_empty(&s->q[c]))
            s->deficit[c] = 0; /* No queue: discard accumulated credit. */
        else
            s->deficit[c] += DWRR_QUANTUM[c];
    }
}

static int dwrr_pick(sim_t *s, int *limit) {
    for (int i = 0; i < NCLASSES; i++) { /* First pass: classes with credit */
        int c = (s->rr_next + i) % NCLASSES;
        if (!q_empty(&s->q[c]) && s->deficit[c] > 0) {
            *limit = s->deficit[c];
            return c;
        }
    }
    for (int i = 0; i < NCLASSES; i++) { /* Second pass: use the remaining budget. */
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

/* ---------- Strict priority with a floor (prio_floor) ----------
 * Similar to prio, but video and data receive a minimum PRB allocation per slot
 * (--floor-video, --floor-data), served before voice. This prevents starvation
 * at the cost of taking those PRBs from voice. `deficit[]` stores the slot floor;
 * all service, including strict-priority service, consumes credit. */
static void floor_slot_start(sim_t *s) {
    s->deficit[CLS_VOICE] = 0;
    s->deficit[CLS_VIDEO] = s->cfg.floor_video;
    s->deficit[CLS_DATA] = s->cfg.floor_data;
}

static int floor_pick(sim_t *s, int *limit) {
    for (int c = CLS_VIDEO; c < NCLASSES; c++) { /* Phase 1: serve the minimum floors. */
        if (!q_empty(&s->q[c]) && s->deficit[c] > 0) {
            *limit = s->deficit[c];
            return c;
        }
    }
    return prio_pick(s, limit); /* Phase 2: strict priority */
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
