/*
 * sim.h - tipos e estado compartilhado do emulador de gNB.
 *
 * Modelo (simplificado de propósito):
 *   - 3 classes de tráfego (voz, vídeo, dados), cada uma com sua fila.
 *   - A cada slot (ex.: 1 ms) a thread escalonadora recebe um orçamento de
 *     PRBs (fixo ou lido de um traço de canal) e o distribui entre as filas
 *     de acordo com a política escolhida (fifo | prio | dwrr).
 *   - Um pacote precisa de `prbs` PRBs; pode ser atendido em vários slots.
 *   - Todo o estado compartilhado é protegido por UM mutex (sim_t.lock).
 */
#ifndef SIM_H
#define SIM_H

#include <pthread.h>
#include <semaphore.h>
#include <stdint.h>

#define NCLASSES 3
#define QCAP 4096 /* capacidade de cada fila; cheia => pacote descartado */
#define NS_PER_S 1000000000LL
#define NS_PER_MS 1000000LL

enum { CLS_VOICE = 0, CLS_VIDEO = 1, CLS_DATA = 2 };
extern const char *const CLASS_NAME[NCLASSES];

/* Um pacote. Todos os tempos são ns relativos a t0_ns; -1 = nunca ocorreu. */
typedef struct {
    int64_t arrival_ns;
    int64_t start_ns;    /* primeiro slot em que recebeu PRBs */
    int64_t end_ns;      /* fim do slot em que terminou de ser atendido */
    int64_t deadline_ns; /* prazo absoluto (chegada + prazo da classe) */
    int cls;
    int prbs;      /* PRBs necessários */
    int remaining; /* PRBs ainda não atendidos */
    int dropped;   /* 1 = fila cheia na chegada */
} packet_t;

/* Fila circular de índices no vetor de pacotes. */
typedef struct {
    int idx[QCAP];
    int head;
    int count;
} queue_t;

/* Um registro por slot (para medir latência de escalonamento). */
typedef struct {
    int64_t ideal_ns;  /* quando o slot deveria começar */
    int64_t actual_ns; /* quando a thread realmente acordou */
    int64_t lock_wait_ns; /* tempo esperando o mutex (inversão de prioridade) */
    int budget;        /* PRBs disponíveis */
    int used;          /* PRBs usados */
} slot_rec_t;

typedef struct {
    int64_t ideal_ns; /* instante em que a produtora deveria acordar */
    int64_t lat_ns;   /* quanto atrasou: acordou_de_fato - ideal */
} wake_rec_t;

#define MAX_WAKES 40000 /* por produtora (dados com carga 2.4 e 10 s gera ~12 mil) */

typedef struct {
    double duration_s;
    double load;          /* multiplicador de carga (1.0 = carga base) */
    const char *policy;   /* "fifo" | "prio" | "edf" | "dwrr" */
    unsigned seed;
    int prbs_per_slot;    /* capacidade fixa (se não houver traço) */
    int slot_us;
    const char *trace;    /* CSV "slot,prbs" ou NULL */
    const char *out;      /* CSV de pacotes */
    int cpu;              /* -1 = não fixar */
    int use_rt;           /* 1 = SCHED_FIFO */
    int use_mlock;        /* 1 = mlockall (evita page fault durante a medição) */
    int prio_inherit;     /* 1 = mutex com PTHREAD_PRIO_INHERIT */
    int inversion;        /* 1 = liga o experimento de inversão de prioridade */
    int cs_us;            /* seção crítica longa da thread de contabilidade (us de CPU) */
    double hog_ms;        /* CPU consumida pela thread hog por ciclo (0 = sem hog) */
    int max_packets;
    int quiet;
    int floor_video;      /* prio_floor: PRB/slot garantidos ao vídeo */
    int floor_data;       /* prio_floor: PRB/slot garantidos aos dados */
    int stagger;          /* K: cada rajada de voz/vídeo é dividida em K sub-rajadas (1 = síncrona) */
} config_t;

typedef struct {
    config_t cfg;
    int64_t t0_ns;  /* início da simulação (CLOCK_MONOTONIC) */
    int64_t end_ns; /* t0 + duração */

    pthread_mutex_t lock; /* protege TUDO abaixo */
    packet_t *pkts;
    int npkts;
    queue_t q[NCLASSES];

    int *trace; /* PRBs por slot lidos do CSV (ou NULL) */
    int trace_len;

    int deficit[NCLASSES]; /* estado do DWRR */
    int rr_next;           /* ponteiro round-robin do DWRR */

    /* Starvation por classe (atualizado pela escalonadora a cada slot):
     * "starved" = slot em que a classe TINHA pacote esperando e recebeu 0 PRB. */
    int starve_run[NCLASSES];     /* sequência atual de slots starved */
    int starve_max[NCLASSES];     /* maior sequência observada */
    long starve_slots[NCLASSES];  /* total de slots starved */
    long backlog_slots[NCLASSES]; /* total de slots com fila não vazia */

    /* Semáforo escalonadora -> monitora: "há um relatório novo para imprimir". */
    sem_t sem_report;
    int monitor_stop; /* a escalonadora liga antes do último sem_post */

    slot_rec_t *slots;
    int nslots;

    /* Latência de despertar de cada produtora (cada uma escreve só o seu vetor,
     * sem lock; lido depois dos joins). */
    wake_rec_t *wake[NCLASSES];
    int nwake[NCLASSES];
} sim_t;

/* instância única da simulação (definida em main.c) */
extern sim_t G;

/* ---- relógio ---- */
int64_t now_ns(void); /* CLOCK_MONOTONIC absoluto */

/* ---- fila ---- */
static inline int q_full(const queue_t *q) { return q->count >= QCAP; }
static inline int q_empty(const queue_t *q) { return q->count == 0; }
static inline void q_push(queue_t *q, int idx) {
    q->idx[(q->head + q->count++) % QCAP] = idx;
}
static inline int q_front(const queue_t *q) { return q->idx[q->head]; }
static inline void q_pop(queue_t *q) {
    q->head = (q->head + 1) % QCAP;
    q->count--;
}

/* ---- canal (channel.c) ---- */
int channel_load_trace(sim_t *s, const char *path); /* 0 = ok */
int channel_slot_prbs(const sim_t *s, long slot);

/* ---- threads (threads.c) ---- */
void *producer_thread(void *arg);  /* arg = (void *)(intptr_t) classe */
void *scheduler_thread(void *arg); /* arg = sim_t * */
void *monitor_thread(void *arg);   /* arg = sim_t * */
void *accounting_thread(void *arg); /* baixa prioridade, segura o mutex */
void *hog_thread(void *arg);        /* prioridade média, só consome CPU */
int class_rt_prio(int cls);
int sched_rt_prio(void);
int monitor_rt_prio(void);
int accounting_rt_prio(void);
int hog_rt_prio(void);

#endif
