/*
 * sim.h - Types and shared state for the gNB emulator.
 *
 * Simplified model:
 *   - Three traffic classes (voice, video, data), each with its own queue.
 *   - At each slot (for example, 1 ms), the scheduler thread receives a PRB
 *     budget (fixed or read from a channel trace) and divides it among queues
 *     according to the selected policy (fifo | prio | edf | dwrr).
 *   - A packet requires `prbs` PRBs and may be served across several slots.
 *   - All shared state is protected by one mutex (sim_t.lock).
 */
#ifndef SIM_H
#define SIM_H

#include <pthread.h>
#include <semaphore.h>
#include <stdint.h>

#define NCLASSES 3
#define QCAP 4096 /* Capacity of each queue; full => packet dropped */
#define NS_PER_S 1000000000LL
#define NS_PER_MS 1000000LL

enum { CLS_VOICE = 0, CLS_VIDEO = 1, CLS_DATA = 2 };
extern const char *const CLASS_NAME[NCLASSES];

/* A packet. All times are ns relative to t0_ns; -1 means never occurred. */
typedef struct {
    int64_t arrival_ns;
    int64_t start_ns;    /* First slot in which the packet received PRBs */
    int64_t end_ns;      /* End of the slot in which service completed */
    int64_t deadline_ns; /* Absolute deadline (arrival + class deadline) */
    int cls;
    int prbs; /* Required PRBs */
    int remaining; /* PRBs not yet served */
    int dropped;   /* 1 = queue full at arrival */
} packet_t;

/* Circular queue of indices in the packet array. */
typedef struct {
    int idx[QCAP];
    int head;
    int count;
} queue_t;

/* Per-slot record used to measure scheduling latency. */
typedef struct {
    int64_t ideal_ns; /* When the slot should start */
    int64_t actual_ns; /* When the thread actually woke up */
    int64_t lock_wait_ns; /* Time waiting for the mutex (priority inversion) */
    int budget; /* Available PRBs */
    int used;          /* PRBs consumed */
} slot_rec_t;

typedef struct {
    int64_t ideal_ns; /* Instant at which a producer should wake */
    int64_t lat_ns;   /* Actual wake delay: actual wake time - ideal */
} wake_rec_t;

#define MAX_WAKES 40000 /* Per producer (data at load 2.4 and 10 s generates ~12,000 records) */

typedef struct {
    double duration_s;
    double load;          /* Load multiplier (1.0 = baseline load) */
    const char *policy;   /* "fifo" | "prio" | "edf" | "dwrr" */
    unsigned seed;
    int prbs_per_slot;    /* Fixed capacity if no trace is loaded */
    int slot_us;
    const char *trace;    /* CSV "slot,prbs" or NULL */
    const char *out;      /* CSV of packets */
    int cpu;              /* -1 = do not pin */
    int use_rt;           /* 1 = SCHED_FIFO */
    int use_mlock;        /* 1 = mlockall (avoids page faults during measurement) */
    int prio_inherit;     /* 1 = mutex with PTHREAD_PRIO_INHERIT */
    int inversion;        /* 1 = enable the priority-inversion experiment */
    int cs_us;            /* Long critical section for the accounting thread (CPU us) */
    double hog_ms;        /* CPU consumed by the hog thread per cycle (0 = no hog) */
    int max_packets;
    int quiet;
    int floor_video;      /* prio_floor: PRBs/slot guaranteed for video */
    int floor_data;       /* prio_floor: PRBs/slot guaranteed for data */
    int stagger;          /* K: each voice/video burst is divided into K sub-bursts (1 = synchronous) */
} config_t;

typedef struct {
    config_t cfg;
    int64_t t0_ns;  /* Start of the simulation (CLOCK_MONOTONIC) */
    int64_t end_ns; /* t0 + duration */

    pthread_mutex_t lock; /* Protects all shared state below */
    packet_t *pkts;
    int npkts;
    queue_t q[NCLASSES];

    int *trace; /* PRBs per slot read from the CSV (or NULL) */
    int trace_len;

    int deficit[NCLASSES]; /* DWRR state */
    int rr_next;           /* DWRR round-robin pointer */

    /* Per-class starvation (updated by the scheduler each slot):
     * "starved" = slot in which the class had a packet waiting and received 0 PRB. */
    int starve_run[NCLASSES];     /* Current run of starved slots */
    int starve_max[NCLASSES];     /* Maximum observed run */
    long starve_slots[NCLASSES];  /* Total starved slots */
    long backlog_slots[NCLASSES]; /* Total slots with non-empty queues */

    /* Scheduler-to-monitor semaphore: "a new report is ready to print." */
    sem_t sem_report;
    int monitor_stop; /* Set by the scheduler before the final sem_post */

    slot_rec_t *slots;
    int nslots;

    /* Wake latency of each producer (each one writes only to its own vector,
     * without a lock; read after the joins). */
    wake_rec_t *wake[NCLASSES];
    int nwake[NCLASSES];
} sim_t;

/* Unique simulation instance (defined in main.c). */
extern sim_t G;

/* ---- clock ---- */
int64_t now_ns(void); /* CLOCK_MONOTONIC absoluto */

/* ---- queue ---- */
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

/* ---- channel (channel.c) ---- */
int channel_load_trace(sim_t *s, const char *path); /* 0 = ok */
int channel_slot_prbs(const sim_t *s, long slot);

/* ---- threads (threads.c) ---- */
void *producer_thread(void *arg);  /* arg = (void *)(intptr_t) class */
void *scheduler_thread(void *arg); /* arg = sim_t * */
void *monitor_thread(void *arg);   /* arg = sim_t * */
void *accounting_thread(void *arg); /* Low priority; holds the mutex */
void *hog_thread(void *arg); /* Medium priority; consumes CPU only */
int class_rt_prio(int cls);
int sched_rt_prio(void);
int monitor_rt_prio(void);
int accounting_rt_prio(void);
int hog_rt_prio(void);

#endif
