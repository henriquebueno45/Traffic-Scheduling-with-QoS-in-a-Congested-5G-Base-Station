/*
 * threads.c - threads produtoras (uma por classe), escalonadora e monitora.
 *
 * Prioridades SCHED_FIFO (Rate Monotonic: período menor => prioridade maior):
 *   escalonador (slot 1 ms) 90 > voz (20 ms) 80 > vídeo (33 ms) 70
 *   > dados (esporádica) 60 > hog 50 > contabilidade 20 > monitor 10
 * (hog e contabilidade só existem com --inversion; ver abaixo)
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

/* Parâmetros do tráfego. Carga 1.0 = valores abaixo.
 * voz/vídeo: a cada `period_ns`, `base_pkts * load` pacotes chegam juntos
 *   (usuários transmitindo no mesmo instante: pior caso, simples).
 * dados: esporádica; intervalo médio exponencial = period_ns / load. */
typedef struct {
    int64_t period_ns;
    int base_pkts;
    int prbs;
    int64_t deadline_ns;
    int rt_prio;
} class_cfg_t;

static const class_cfg_t CLS[NCLASSES] = {
    {20 * NS_PER_MS, 100, 2, 20 * NS_PER_MS, 80},  /* voz   */
    {33 * NS_PER_MS, 40, 10, 50 * NS_PER_MS, 70},  /* vídeo */
    {2 * NS_PER_MS, 1, 20, 500 * NS_PER_MS, 60},   /* dados */
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

/* ===================== produtoras ===================== */

/* Cria `n` pacotes da classe `cls` de uma vez (um único lock). */
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
    int k = 0; /* índice da sub-rajada dentro do período (voz/vídeo) */

    for (;;) {
        sleep_until(next);
        if (next >= s->end_ns) break;
        if (s->nwake[cls] < MAX_WAKES) /* latência de despertar = agora - instante ideal */
            s->wake[cls][s->nwake[cls]++] =
                (wake_rec_t){next - s->t0_ns, now_ns() - next};

        if (cls == CLS_DATA) {
            enqueue_burst(s, cls, 1);
            double u = (rand_r(&seed) + 1.0) / ((double)RAND_MAX + 2.0);
            next += (int64_t)(-log(u) * CLS[cls].period_ns / s->cfg.load);
        } else {
            /* K sub-rajadas por período; n_k distribui o total sem perder pacotes */
            int K = s->cfg.stagger;
            int total = (int)(CLS[cls].base_pkts * s->cfg.load + 0.5);
            enqueue_burst(s, cls, total * (k + 1) / K - total * k / K);
            k = (k + 1) % K;
            next += CLS[cls].period_ns / K;
        }
    }
    return NULL;
}

/* ===================== escalonadora ===================== */

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
        int got[NCLASSES] = {0};     /* PRBs que cada classe recebeu neste slot */
        int backlogged[NCLASSES];    /* a classe tinha pacote esperando? */

        int64_t t_try = now_ns();
        pthread_mutex_lock(&s->lock);
        int64_t t_got = now_ns();
        int64_t slot_start = t_got - s->t0_ns; /* quando o slot é realmente processado */
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
                p->end_ns = slot_start + slot_ns; /* fim do slot */
                q_pop(&s->q[c]);
            }
        }

        /* Starvation: fila não vazia e nenhum PRB recebido => slot "starved".
         * Contamos a sequência atual e guardamos a maior. */
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

        /* A cada 1 s simulado, avisa a monitora pelo semáforo. */
        if ((slot + 1) % slots_per_sec == 0) sem_post(&s->sem_report);
    }
    s->monitor_stop = 1; /* o sem_post garante que a monitora enxergue isto */
    sem_post(&s->sem_report);
    return NULL;
}

/* ===================== monitora ===================== */

/* Dorme em sem_wait até a escalonadora liberar um relatório (sem polling de tempo). */
void *monitor_thread(void *arg) {
    sim_t *s = arg;
    for (;;) {
        sem_wait(&s->sem_report);
        if (s->monitor_stop) break;
        if (s->cfg.quiet) continue;
        pthread_mutex_lock(&s->lock);
        fprintf(stderr, "[monitor] t=%3.0fs filas v/V/d=%4d/%4d/%4d pacotes=%d\n",
                s->nslots * s->cfg.slot_us / 1e6, s->q[0].count, s->q[1].count,
                s->q[2].count, s->npkts);
        pthread_mutex_unlock(&s->lock);
    }
    return NULL;
}

/* ============ experimento de inversão de prioridade (--inversion) ============
 *
 * Cenário clássico, tudo fixado em UMA CPU (--cpu) com SCHED_FIFO:
 *   - contabilidade (prio 20) pega o mutex e fica `cs_us` us de CPU dentro dele
 *     (ex.: atualizar estatísticas globais);
 *   - hog (prio 50) acorda logo depois e consome `hog_ms` ms de CPU;
 *   - a escalonadora (prio 90) precisa do mutex no slot seguinte e bloqueia.
 * Sem herança: o hog preempta a contabilidade, que só termina depois dele =>
 *   a escalonadora espera ~hog_ms (inversão não limitada pela seção crítica).
 * Com PTHREAD_PRIO_INHERIT: a contabilidade herda prio 90, preempta o hog e
 *   libera o mutex em ~cs_us => espera limitada.
 * Fases (relativas a cada ciclo de 100 ms): contabilidade +300 us, hog +800 us,
 * e a escalonadora tenta o mutex em +1000 us.
 */
#define INV_PERIOD_NS (100 * NS_PER_MS)

/* Consome tempo de CPU da própria thread (preempções não contam). */
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
