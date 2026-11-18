/*
 * threads.c - Producer threads (one per class), scheduler, and monitor.
 *
 * SCHED_FIFO priorities (Rate Monotonic: shorter period => higher priority):
 *   scheduler (1-ms slot) 90 > voice (20 ms) 80 > video (33 ms) 70
 *   > data (sporadic) 60 > hog 50 > accounting 20 > monitor 10
 * The hog and accounting threads exist only with --inversion; see below.
 */
#include <errno.h>
#include <limits.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#include "policy.h"
#include "sim.h"

const char *const CLASS_NAME[NCLASSES] = {"voice", "video", "data"};

/* Traffic parameters. Load 1.0 uses the baseline values below.
 * Voice/video: every `period_ns`, `base_pkts * load` packets arrive together
 *   (all users transmit simultaneously: a simple worst case).
 * Data: sporadic; mean exponential interval = period_ns / load. */
typedef struct {
    int64_t period_ns;
    int base_pkts;
    int prbs;
    int64_t deadline_ns;
    int rt_prio;
} class_cfg_t;

static const class_cfg_t CLS[NCLASSES] = {
    {20 * NS_PER_MS, 100, 2, 20 * NS_PER_MS, 80},  /* voice   */
    {33 * NS_PER_MS, 40, 10, 50 * NS_PER_MS, 70},  /* video */
    {2 * NS_PER_MS, 1, 20, 500 * NS_PER_MS, 60},   /* data */
};

int class_rt_prio(int cls) { return CLS[cls].rt_prio; }
int sched_rt_prio(void) { return 90; }
int monitor_rt_prio(void) { return 10; }
int accounting_rt_prio(void) { return 20; }
int hog_rt_prio(void) { return 50; }

int64_t now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (int64_t)ts.tv_sec * NS_PER_S + ts.tv_nsec;
}

static void sleep_until(int64_t abs_ns) {
    struct timespec ts = {abs_ns / NS_PER_S, abs_ns % NS_PER_S};
    while (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, NULL) == EINTR)
        ;
}

/* ===================== producers ===================== */

/* Create `n` packets of class `cls` at once under the shared lock. */
static void enqueue_burst(sim_t *s, int cls, int n) {
    int64_t t = now_ns() - s->t0_ns;
    pthread_mutex_lock(&s->lock);
    for (int i = 0; i < n && s->npkts < s->cfg.max_packets; i++) {
        packet_t *p = &s->pkts[s->npkts];
        p->cls = cls;
        p->prbs = p->remaining = CLS[cls].prbs;
        p->arrival_ns = t;
        p->start_ns = p->end_ns = -1;
        p->deadline_ns = t + CLS[cls].deadline_ns;
        if (q_full(&s->q[cls])) {
            p->dropped = 1;
        } else {
            q_push(&s->q[cls], s->npkts);
        }
        s->npkts++;
    }
    pthread_mutex_unlock(&s->lock);
}

void *producer_thread(void *arg) {
    int cls = (int)(intptr_t)arg;
    sim_t *s = &G;
    unsigned seed = s->cfg.seed * 7919u + (unsigned)cls;
    int64_t next = s->t0_ns;
    int k = 0; /* Index of the sub-burst within the period (voice/video) */

    for (;;) {
        sleep_until(next);
        if (next >= s->end_ns) break;
        if (s->nwake[cls] < MAX_WAKES) /* wake latency = now - ideal instant */
            s->wake[cls][s->nwake[cls]++] =
                (wake_rec_t){next - s->t0_ns, now_ns() - next};

        if (cls == CLS_DATA) {
            enqueue_burst(s, cls, 1);
            double u = (rand_r(&seed) + 1.0) / ((double)RAND_MAX + 2.0);
            next += (int64_t)(-log(u) * CLS[cls].period_ns / s->cfg.load);
        } else {
            /* K sub-bursts per period; n_k distributes the total without losing packets. */
            int K = s->cfg.stagger;
            int total = (int)(CLS[cls].base_pkts * s->cfg.load + 0.5);
            enqueue_burst(s, cls, total * (k + 1) / K - total * k / K);
            k = (k + 1) % K;
            next += CLS[cls].period_ns / K;
        }
    }
    return NULL;
}

/* ===================== scheduler ===================== */

void *scheduler_thread(void *arg) {
    sim_t *s = arg;
    const policy_t *pol = policy_by_name(s->cfg.policy);
    const int64_t slot_ns = (int64_t)s->cfg.slot_us * 1000;
    const long slots_per_sec = 1000000L / s->cfg.slot_us;
    int64_t ideal = s->t0_ns;

    for (long slot = 0; ideal < s->end_ns; slot++, ideal += slot_ns) {
        sleep_until(ideal);
        int64_t woke = now_ns();
        int budget = channel_slot_prbs(s, slot);
        int total = budget;
        int got[NCLASSES] = {0};     /* PRBs each class received in this slot */
        int backlogged[NCLASSES];    /* Did the class have a packet waiting? */

        int64_t t_try = now_ns();
        pthread_mutex_lock(&s->lock);
        int64_t t_got = now_ns();
        int64_t slot_start = t_got - s->t0_ns; /* When the slot is actually processed */
        pol->on_slot_start(s);
        for (int c = 0; c < NCLASSES; c++) backlogged[c] = !q_empty(&s->q[c]);

        while (budget > 0) {
            int limit;
            int c = pol->pick(s, &limit);
            if (c < 0) break;
            packet_t *p = &s->pkts[q_front(&s->q[c])];
            int chunk = p->remaining;
            if (chunk > budget) chunk = budget;
            if (chunk > limit) chunk = limit;

            if (p->start_ns < 0) p->start_ns = slot_start;
            p->remaining -= chunk;
            budget -= chunk;
            got[c] += chunk;
            pol->on_served(s, c, chunk);
            if (p->remaining == 0) {
                p->end_ns = slot_start + slot_ns; /* End of the slot */
                q_pop(&s->q[c]);
            }
        }

        /* Starvation: queue non-empty and zero PRBs received => "starved" slot.
         * Count the current run and retain the maximum. */
        for (int c = 0; c < NCLASSES; c++) {
            if (!backlogged[c]) { s->starve_run[c] = 0; continue; }
            s->backlog_slots[c]++;
            if (got[c] > 0) { s->starve_run[c] = 0; continue; }
            s->starve_slots[c]++;
            if (++s->starve_run[c] > s->starve_max[c]) s->starve_max[c] = s->starve_run[c];
        }

        s->slots[slot].ideal_ns = ideal - s->t0_ns;
        s->slots[slot].actual_ns = woke - s->t0_ns;
        s->slots[slot].lock_wait_ns = t_got - t_try;
        s->slots[slot].budget = total;
        s->slots[slot].used = total - budget;
        s->nslots = (int)slot + 1;
        pthread_mutex_unlock(&s->lock);

        /* Every 1 simulated second, notify the monitor through the semaphore. */
        if ((slot + 1) % slots_per_sec == 0) sem_post(&s->sem_report);
    }
    s->monitor_stop = 1; /* sem_post ensures the monitor sees this update */
    sem_post(&s->sem_report);
    return NULL;
}

/* ===================== monitor ===================== */

/* Wait on sem_wait until the scheduler releases a report (without time polling). */
void *monitor_thread(void *arg) {
    sim_t *s = arg;
    for (;;) {
        sem_wait(&s->sem_report);
        if (s->monitor_stop) break;
        if (s->cfg.quiet) continue;
        pthread_mutex_lock(&s->lock);
        fprintf(stderr, "[monitor] t=%3.0fs queues v/V/d=%4d/%4d/%4d packets=%d\n",
                s->nslots * s->cfg.slot_us / 1e6, s->q[0].count, s->q[1].count,
                s->q[2].count, s->npkts);
        pthread_mutex_unlock(&s->lock);
    }
    return NULL;
}

/* ============ priority-inversion experiment (--inversion) ============
 *
 * Classic scenario, all pinned to one CPU (--cpu) with SCHED_FIFO:
 *   - accounting (priority 20) takes the mutex and spends `cs_us` CPU microseconds inside it;
 *   - hog (priority 50) wakes immediately afterward and consumes `hog_ms` ms of CPU;
 *   - the scheduler (priority 90) needs the mutex in the next slot and blocks.
 * Without inheritance, the hog preempts accounting, so the scheduler waits about hog_ms
 * and the inversion is not bounded by the accounting critical section.
 * With PTHREAD_PRIO_INHERIT, accounting inherits priority 90, preempts the hog, and
 * releases the mutex in about cs_us, so the wait is bounded.
 * Phases relative to each 100-ms cycle: accounting +300 us, hog +800 us,
 * and the scheduler attempts the mutex at +1000 us.
 */
#define INV_PERIOD_NS (100 * NS_PER_MS)

/* Consume CPU time on this thread (preemptions do not count). */
static void burn_cpu_ns(int64_t ns) {
    struct timespec t;
    clock_gettime(CLOCK_THREAD_CPUTIME_ID, &t);
    int64_t start = (int64_t)t.tv_sec * NS_PER_S + t.tv_nsec, cur;
    do {
        clock_gettime(CLOCK_THREAD_CPUTIME_ID, &t);
        cur = (int64_t)t.tv_sec * NS_PER_S + t.tv_nsec;
    } while (cur - start < ns);
}

void *accounting_thread(void *arg) {
    sim_t *s = arg;
    for (int64_t next = s->t0_ns + 300000; next < s->end_ns; next += INV_PERIOD_NS) {
        sleep_until(next);
        pthread_mutex_lock(&s->lock);
        burn_cpu_ns((int64_t)s->cfg.cs_us * 1000);
        pthread_mutex_unlock(&s->lock);
    }
    return NULL;
}

void *hog_thread(void *arg) {
    sim_t *s = arg;
    for (int64_t next = s->t0_ns + 800000; next < s->end_ns; next += INV_PERIOD_NS) {
        sleep_until(next);
        burn_cpu_ns((int64_t)(s->cfg.hog_ms * 1e6));
    }
    return NULL;
}
