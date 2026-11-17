/*
 * main.c - CLI, criação das threads e escrita dos logs.
 *
 * Uso: ./build/gnb_sim --policy prio --load 1.5 --duration 10 --seed 1 \
 *                      --out ../results/run.csv [--trace t.csv] [--cpu 2]
 */
#define _GNU_SOURCE
#include <errno.h>
#include <getopt.h>
#include <sched.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include "policy.h"
#include "sim.h"

sim_t G;

static void usage(const char *p) {
    fprintf(stderr,
            "Uso: %s [opções]\n"
            "  --policy fifo|prio|edf|dwrr|prio_floor  política (padrão prio)\n"
            "  --floor-video N           prio_floor: PRB/slot garantidos ao vídeo (padrão 0)\n"
            "  --floor-data N            prio_floor: PRB/slot garantidos aos dados (padrão 0)\n"
            "  --stagger K               divide cada rajada de voz/vídeo em K sub-rajadas (padrão 1)\n"
            "  --load X                  multiplicador de carga (padrão 1.0)\n"
            "  --duration S              duração em segundos (padrão 10)\n"
            "  --seed N                  semente (padrão 1)\n"
            "  --prbs N                  PRBs por slot, canal fixo (padrão 50)\n"
            "  --slot-us N               duração do slot em us (padrão 1000)\n"
            "  --trace FILE              traço de canal CSV slot,prbs\n"
            "  --out FILE                CSV de pacotes (padrão results/run.csv)\n"
            "  --cpu N                   fixa tudo na CPU N (padrão: não fixa)\n"
            "  --no-rt                   não usa SCHED_FIFO\n"
            "  --no-mlock                não trava a memória (padrão: mlockall)\n"
            "  --prio-inherit            mutex com PTHREAD_PRIO_INHERIT\n"
            "  --inversion               liga o experimento de inversão de prioridade\n"
            "                            (exige --cpu e SCHED_FIFO)\n"
            "  --cs-us N                 seção crítica da contabilidade, us (padrão 2000)\n"
            "  --hog-ms X                CPU do hog por ciclo de 100 ms (padrão 20; 0 = sem hog)\n"
            "  --max-packets N           capacidade do log (padrão 2000000)\n"
            "  --quiet                   sem saída do monitor\n",
            p);
}

static void parse_args(config_t *c, int argc, char **argv) {
    *c = (config_t){.duration_s = 10, .load = 1.0, .policy = "prio", .seed = 1,
                    .prbs_per_slot = 50, .slot_us = 1000,
                    .out = "results/run.csv", .cpu = -1, .use_rt = 1, .use_mlock = 1,
                    .max_packets = 2000000, .cs_us = 2000, .hog_ms = 20, .stagger = 1};
    static const struct option opts[] = {
        {"policy", 1, 0, 'p'},   {"load", 1, 0, 'l'},  {"duration", 1, 0, 'd'},
        {"seed", 1, 0, 's'},     {"prbs", 1, 0, 'b'},  {"slot-us", 1, 0, 'u'},
        {"trace", 1, 0, 't'},    {"out", 1, 0, 'o'},   {"cpu", 1, 0, 'c'},
        {"no-rt", 0, 0, 'n'},    {"prio-inherit", 0, 0, 'i'},
        {"max-packets", 1, 0, 'm'}, {"quiet", 0, 0, 'q'}, {"help", 0, 0, 'h'},
        {"inversion", 0, 0, 'v'}, {"cs-us", 1, 0, 'k'}, {"hog-ms", 1, 0, 'g'},
        {"no-mlock", 0, 0, 'L'}, {"floor-video", 1, 0, 'V'}, {"floor-data", 1, 0, 'D'},
        {"stagger", 1, 0, 'S'},
        {0, 0, 0, 0}};
    int o;
    while ((o = getopt_long(argc, argv, "", opts, NULL)) != -1) {
        switch (o) {
        case 'p': c->policy = optarg; break;
        case 'l': c->load = atof(optarg); break;
        case 'd': c->duration_s = atof(optarg); break;
        case 's': c->seed = (unsigned)atoi(optarg); break;
        case 'b': c->prbs_per_slot = atoi(optarg); break;
        case 'u': c->slot_us = atoi(optarg); break;
        case 't': c->trace = optarg; break;
        case 'o': c->out = optarg; break;
        case 'c': c->cpu = atoi(optarg); break;
        case 'n': c->use_rt = 0; break;
        case 'i': c->prio_inherit = 1; break;
        case 'm': c->max_packets = atoi(optarg); break;
        case 'q': c->quiet = 1; break;
        case 'v': c->inversion = 1; break;
        case 'k': c->cs_us = atoi(optarg); break;
        case 'g': c->hog_ms = atof(optarg); break;
        case 'L': c->use_mlock = 0; break;
        case 'V': c->floor_video = atoi(optarg); break;
        case 'D': c->floor_data = atoi(optarg); break;
        case 'S': c->stagger = atoi(optarg) > 0 ? atoi(optarg) : 1; break;
        default: usage(argv[0]); exit(o == 'h' ? 0 : 2);
        }
    }
}

/* mkdir -p do diretório pai de `path` (um nível basta para results/). */
static void ensure_parent_dir(const char *path) {
    char dir[512];
    strncpy(dir, path, sizeof dir - 1);
    dir[sizeof dir - 1] = 0;
    char *slash = strrchr(dir, '/');
    if (slash) {
        *slash = 0;
        mkdir(dir, 0755);
    }
}

/* Cria thread; tenta SCHED_FIFO e, se não puder, avisa e cria normal. */
static void spawn(pthread_t *t, void *(*fn)(void *), void *arg, int prio) {
    if (G.cfg.use_rt) {
        pthread_attr_t a;
        struct sched_param sp = {.sched_priority = prio};
        pthread_attr_init(&a);
        pthread_attr_setinheritsched(&a, PTHREAD_EXPLICIT_SCHED);
        pthread_attr_setschedpolicy(&a, SCHED_FIFO);
        pthread_attr_setschedparam(&a, &sp);
        int r = pthread_create(t, &a, fn, arg);
        pthread_attr_destroy(&a);
        if (r == 0) return;
        fprintf(stderr, "aviso: SCHED_FIFO prio %d falhou (%s); usando padrão\n",
                prio, strerror(r));
        G.cfg.use_rt = 0;
    }
    if (pthread_create(t, NULL, fn, arg) != 0) {
        perror("pthread_create");
        exit(1);
    }
}

static void write_packet_log(const sim_t *s) {
    ensure_parent_dir(s->cfg.out);
    FILE *f = fopen(s->cfg.out, "w");
    if (!f) { perror(s->cfg.out); exit(1); }
    fprintf(f, "id,class,arrival_ns,start_ns,end_ns,deadline_ns,prbs,dropped\n");
    for (int i = 0; i < s->npkts; i++) {
        const packet_t *p = &s->pkts[i];
        fprintf(f, "%d,%s,%lld,%lld,%lld,%lld,%d,%d\n", i, CLASS_NAME[p->cls],
                (long long)p->arrival_ns, (long long)p->start_ns,
                (long long)p->end_ns, (long long)p->deadline_ns, p->prbs,
                p->dropped);
    }
    fclose(f);
}

/* <out>.slots.csv: uma linha por slot (latência de escalonamento). */
static void write_slot_log(const sim_t *s) {
    char path[600];
    snprintf(path, sizeof path, "%s.slots.csv", s->cfg.out);
    FILE *f = fopen(path, "w");
    if (!f) { perror(path); return; }
    fprintf(f, "slot,ideal_ns,actual_ns,lock_wait_ns,budget,used\n");
    for (int i = 0; i < s->nslots; i++)
        fprintf(f, "%d,%lld,%lld,%lld,%d,%d\n", i, (long long)s->slots[i].ideal_ns,
                (long long)s->slots[i].actual_ns, (long long)s->slots[i].lock_wait_ns,
                s->slots[i].budget, s->slots[i].used);
    fclose(f);
}

/* <out>.starvation.csv: starvation por classe.
 *   backlog_slots = slots com fila não vazia
 *   starved_slots = desses, quantos a classe recebeu 0 PRB
 *   max_starve_ms = maior espera seguida sem receber nenhum PRB */
static void write_starvation_log(const sim_t *s) {
    char path[600];
    snprintf(path, sizeof path, "%s.starvation.csv", s->cfg.out);
    FILE *f = fopen(path, "w");
    if (!f) { perror(path); return; }
    fprintf(f, "class,backlog_slots,starved_slots,max_starve_ms\n");
    for (int c = 0; c < NCLASSES; c++)
        fprintf(f, "%s,%ld,%ld,%.3f\n", CLASS_NAME[c], s->backlog_slots[c],
                s->starve_slots[c], s->starve_max[c] * s->cfg.slot_us / 1000.0);
    fclose(f);
}

/* <out>.producers.csv: latência de despertar de cada produtora (acordou - ideal). */
static void write_producer_log(const sim_t *s) {
    char path[600];
    snprintf(path, sizeof path, "%s.producers.csv", s->cfg.out);
    FILE *f = fopen(path, "w");
    if (!f) { perror(path); return; }
    fprintf(f, "class,ideal_ns,latency_ns\n");
    for (int c = 0; c < NCLASSES; c++)
        for (int i = 0; i < s->nwake[c]; i++)
            fprintf(f, "%s,%lld,%lld\n", CLASS_NAME[c], (long long)s->wake[c][i].ideal_ns,
                    (long long)s->wake[c][i].lat_ns);
    fclose(f);
}

int main(int argc, char **argv) {
    parse_args(&G.cfg, argc, argv);
    if (!policy_by_name(G.cfg.policy)) {
        fprintf(stderr, "política desconhecida: %s\n", G.cfg.policy);
        return 2;
    }
    if (G.cfg.trace && channel_load_trace(&G, G.cfg.trace) != 0) {
        fprintf(stderr, "não consegui ler o traço %s\n", G.cfg.trace);
        return 2;
    }

    if (G.cfg.inversion && (G.cfg.cpu < 0 || !G.cfg.use_rt)) {
        fprintf(stderr, "--inversion exige --cpu N e SCHED_FIFO (sem --no-rt)\n");
        return 2;
    }

    if (G.cfg.cpu >= 0) { /* threads herdam a afinidade */
        cpu_set_t set;
        CPU_ZERO(&set);
        CPU_SET(G.cfg.cpu, &set);
        if (sched_setaffinity(0, sizeof set, &set) != 0) perror("sched_setaffinity");
    }

    pthread_mutexattr_t ma;
    pthread_mutexattr_init(&ma);
    if (G.cfg.prio_inherit)
        pthread_mutexattr_setprotocol(&ma, PTHREAD_PRIO_INHERIT);
    pthread_mutex_init(&G.lock, &ma);
    sem_init(&G.sem_report, 0, 0); /* contador começa em 0: monitora espera */

    /* Trava toda a memória (atual e futura) na RAM: sem page fault nem swap durante a
     * medição. Vem ANTES dos calloc para que os buffers já nasçam travados.
     * Exige RLIMIT_MEMLOCK alto (pilhas de thread de 8 MB e logs também são travados). */
    struct rlimit rl;
    if (G.cfg.use_mlock && (getrlimit(RLIMIT_MEMLOCK, &rl) != 0 ||
                            (rl.rlim_cur != RLIM_INFINITY && rl.rlim_cur < (rlim_t)512 << 20))) {
        if (!G.cfg.quiet)
            fprintf(stderr, "AVISO: memlock baixo; rodando sem mlockall "
                            "(adicione '@wheel - memlock unlimited' em /etc/security/limits.d/99-rt.conf)\n");
        G.cfg.use_mlock = 0;
    }
    if (G.cfg.use_mlock && mlockall(MCL_CURRENT | MCL_FUTURE) != 0) {
        perror("AVISO: mlockall");
        G.cfg.use_mlock = 0;
    }

    long max_slots = (long)(G.cfg.duration_s * 1e6 / G.cfg.slot_us) + 16;
    G.pkts = calloc(G.cfg.max_packets, sizeof *G.pkts);
    G.slots = calloc(max_slots, sizeof *G.slots);
    if (!G.pkts || !G.slots) { perror("calloc"); return 1; }
    for (int c = 0; c < NCLASSES; c++) {
        G.wake[c] = calloc(MAX_WAKES, sizeof *G.wake[c]);
        if (!G.wake[c]) { perror("calloc"); return 1; }
    }

    G.t0_ns = now_ns() + 100 * NS_PER_MS; /* folga para criar as threads */
    G.end_ns = G.t0_ns + (int64_t)(G.cfg.duration_s * 1e9);

    pthread_t tp[NCLASSES], ts, tm, tacc, thog;
    spawn(&ts, scheduler_thread, &G, sched_rt_prio());
    for (int c = 0; c < NCLASSES; c++)
        spawn(&tp[c], producer_thread, (void *)(intptr_t)c, class_rt_prio(c));
    spawn(&tm, monitor_thread, &G, monitor_rt_prio());
    int run_hog = G.cfg.inversion && G.cfg.hog_ms > 0;
    if (G.cfg.inversion) spawn(&tacc, accounting_thread, &G, accounting_rt_prio());
    if (run_hog) spawn(&thog, hog_thread, &G, hog_rt_prio());

    pthread_join(ts, NULL);
    for (int c = 0; c < NCLASSES; c++) pthread_join(tp[c], NULL);
    pthread_join(tm, NULL);
    if (G.cfg.inversion) pthread_join(tacc, NULL);
    if (run_hog) pthread_join(thog, NULL);

    write_packet_log(&G);
    write_slot_log(&G);
    write_starvation_log(&G);
    write_producer_log(&G);
    if (!G.cfg.quiet)
        fprintf(stderr, "ok: %d pacotes, %d slots -> %s (rt=%d)\n", G.npkts,
                G.nslots, G.cfg.out, G.cfg.use_rt);
    if (G.npkts >= G.cfg.max_packets)
        fprintf(stderr, "AVISO: log cheio (--max-packets); resultado truncado\n");
    return 0;
}
