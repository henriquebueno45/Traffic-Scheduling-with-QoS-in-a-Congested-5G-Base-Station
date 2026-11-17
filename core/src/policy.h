/*
 * policy.h - interface única para as políticas de escalonamento.
 *
 * Para criar uma política nova: implemente as 3 funções em policy.c e
 * registre-a na tabela POLICIES.
 */
#ifndef POLICY_H
#define POLICY_H

#include "sim.h"

typedef struct {
    const char *name;
    /* chamada uma vez no início de cada slot (com o mutex travado) */
    void (*on_slot_start)(sim_t *s);
    /* escolhe a classe a atender; devolve -1 se não há ninguém.
     * *limit = máximo de PRBs que essa classe pode receber agora. */
    int (*pick)(sim_t *s, int *limit);
    /* chamada após atender `prbs` PRBs da classe `cls` */
    void (*on_served)(sim_t *s, int cls, int prbs);
} policy_t;

const policy_t *policy_by_name(const char *name); /* NULL se não existe */

#endif
