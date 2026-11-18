/*
 * policy.h - Common interface for the scheduling policies.
 *
 * To create a new policy, implement the three functions in policy.c and
 * register it in the POLICIES table.
 */
#ifndef POLICY_H
#define POLICY_H

#include "sim.h"

typedef struct {
    const char *name;
    /* Called once at the start of each slot while holding the mutex. */
    void (*on_slot_start)(sim_t *s);
    /* Select the class to serve; return -1 if no packet is queued.
     * *limit is the maximum PRBs that this class may receive now. */
    int (*pick)(sim_t *s, int *limit);
    /* Called after serving `prbs` PRBs from class `cls`. */
    void (*on_served)(sim_t *s, int cls, int prbs);
} policy_t;

const policy_t *policy_by_name(const char *name); /* NULL if it does not exist */

#endif
