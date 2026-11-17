# gNB QoS Scheduler – emulador multithread (C/Pthreads) + canal e análise (Python)

Plano completo: `Plano_Trabalho_Final.md`.

## Estrutura

```
core/                 Núcleo em tempo real (C, Pthreads, Linux)
  Makefile            make | make debug | make clean
  src/sim.h           Tipos e estado compartilhado (leia primeiro)
  src/threads.c       Produtoras (voz/vídeo/dados), escalonadora, monitora
  src/policy.c        Políticas: fifo, prio, edf, dwrr (mesma interface)
  src/channel.c       Capacidade do slot: fixa ou lida de um traço CSV
  src/main.c          CLI, SCHED_FIFO/afinidade, escrita dos logs
channel/channel_model.py   Path loss + shadowing + Rayleigh (Jakes) + MRC -> traço de PRBs
analysis/analyze.py        Métricas por classe de uma execução
analysis/sweep.py          Varredura política x carga x sementes, IC 95% (bootstrap), gráfico
analysis/inversion.py      Experimento de inversão de prioridade (sem/com herança)
tests/test_python.py       Testes numéricos (pytest)
results/                   Saídas (CSV, PNG)
```

## Como funciona (resumo)

- A cada **slot** (1 ms) a thread escalonadora recebe um orçamento de PRBs e o reparte
  entre 3 filas (voz, vídeo, dados) conforme a política. Pacote = N PRBs, pode levar vários slots.
- Produtoras: voz 20 ms, vídeo 33 ms (rajadas periódicas, `clock_nanosleep` absoluto),
  dados esporádica (intervalos exponenciais). `--load` escala a carga (1.0 = base, ~64 % da capacidade de 50 PRB/slot).
- Prioridades `SCHED_FIFO` (RM): escalonador 90 > voz 80 > vídeo 70 > dados 60 > monitor 10.
- Um único mutex protege filas, pacotes e estado da política.
- Log em memória, gravado só no fim (sem I/O dentro das threads de tempo real).

## Uso rápido

```bash
# 1) compilar
make -C core

# 2) uma execução (10 s, canal fixo de 50 PRB), fixada na CPU 2
core/build/gnb_sim --policy prio --load 1.5 --duration 10 --seed 1 --cpu 2 --out results/run.csv

# 3) métricas
./venv/bin/python -m analysis.analyze results/run.csv --duration 10

# 4) com canal Rayleigh e 2 antenas (MRC) a 200 m
./venv/bin/python -m channel.channel_model --distance 200 --antennas 2 --slots 10000 --out results/trace.csv
core/build/gnb_sim --policy dwrr --load 1.5 --trace results/trace.csv --out results/run.csv

# 5) varredura completa (gera results/sweep_*.csv e sweep_qos.png)
./venv/bin/python -m analysis.sweep --loads 0.5 1 1.5 2 2.5 --seeds 5 --duration 5 --cpu 2

# testes
./venv/bin/python -m pytest -q tests
```

Antes de medir: governor `performance`, laptop na tomada, `ulimit -r` = 95
(sem isso o núcleo avisa e roda sem `SCHED_FIFO`; `rt=0` na última linha).

## Logs

`results/run.csv` – um pacote por linha: `id,class,arrival_ns,start_ns,end_ns,deadline_ns,prbs,dropped`
(`-1` = nunca atendido; `dropped=1` = fila cheia). `results/run.csv.slots.csv` – por slot:
`slot,ideal_ns,actual_ns,lock_wait_ns,budget,used` (latência de escalonamento = actual − ideal;
`lock_wait_ns` = tempo que a escalonadora esperou o mutex).

## Como estender

- **Nova política:** escreva `on_slot_start/pick/on_served` em `core/src/policy.c` e adicione à tabela `POLICIES`.
- **Novo canal:** gere um CSV `slot,prbs` (qualquer ferramenta) e passe com `--trace`.
- **Depurar:** `make -C core debug` (ThreadSanitizer) e `gdb core/build/gnb_sim`; use `--no-rt` se não tiver permissão.
- **Próximos passos do plano:** variante de prioridade estrita com piso mínimo, teste de
  escalonabilidade (Liu-Layland), validação capacidade × distância.

## Políticas, semáforo e starvation (o que cada parte faz)

- **Políticas** (`policy.c`, mesma interface `on_slot_start/pick/on_served`): `fifo` (pacote mais antigo),
  `prio` (voz > vídeo > dados), `edf` (menor deadline absoluto entre as cabeças das filas),
  `dwrr` (quanta proporcionais).
- **Semáforo** (`sem_report`): a escalonadora faz `sem_post` a cada 1 s simulado; a monitora dorme em
  `sem_wait` e então imprime as filas. No fim, `monitor_stop = 1` + `sem_post` a encerram.
  O mutex protege o estado; o semáforo apenas sinaliza eventos (sem polling de tempo).
- **Starvation** (explícita, por classe): um slot é *starved* se a classe tinha fila e recebeu 0 PRB.
  `<out>.starvation.csv`: `class,backlog_slots,starved_slots,max_starve_ms`
  (`max_starve_ms` = maior sequência de slots starved × duração do slot).
  `analyze.py` imprime `starved_frac` e `max_starve_ms`; `sweep.py` agrega `max_starve_ms`.
- Exemplo (carga 2.0, canal fixo): `prio` deixa dados sem PRB em ~89 % dos slots com fila; `edf`
  reparte a perda, mas a voz chega a ficar 47 ms sem PRB (> deadline de 20 ms).

## Experimento de inversão de prioridade

Três threads em uma única CPU com `SCHED_FIFO`: a **escalonadora (prio 90)** precisa do mutex; a
**contabilidade (prio 20)** o segura por `--cs-us` (2 ms de CPU) a cada 100 ms; o **hog (prio 50)**
consome `--hog-ms` (20 ms) logo depois. Sem herança, o hog preempta a contabilidade e a escalonadora
espera ~20 ms (a voz, prazo de 20 ms, estoura). Com `PTHREAD_PRIO_INHERIT`, a contabilidade herda a
prio 90 e libera o mutex em ~2 ms.

```bash
# automatizado: baseline x sem herança x com herança (gera results/inversao.png)
./venv/bin/python -m analysis.inversion --seeds 5 --duration 10 --cpu 2

# manual
core/build/gnb_sim --inversion --cpu 2 --policy prio                  # sem herança
core/build/gnb_sim --inversion --cpu 2 --policy prio --prio-inherit   # com herança
core/build/gnb_sim --inversion --cpu 2 --hog-ms 0                     # baseline
```
`--inversion` exige `--cpu` e `SCHED_FIFO` (sem isso o hog roda em outro núcleo e não há inversão).

## Teste de escalonabilidade (analítico) e resultados com EDF

`analysis/schedulability.py` calcula, por carga: utilização U, limite de Liu-Layland (voz+vídeo),
tempo de resposta de prioridade fixa e teste de demanda do EDF. Prevê saturação em 1,56x e que
`prio` protege voz/vídeo até U(voz+vídeo) = 1 (carga ~2,26x). Validado pelo sweep (20 sementes,
canal fixo, 4 s): `prio` mantém QoS de voz = 1,0 até 2,4x e o vídeo só colapsa em 2,4x.

```bash
./venv/bin/python -m analysis.schedulability --loads 1.5 1.6 2.0 2.4
./venv/bin/python -m analysis.sweep --loads 1.2 1.6 2.0 2.4 --seeds 20 --duration 4 --cpu 2 --tag edf
```
Saídas: `results/edf_{raw,agg}.csv`, `edf_qos.png`, `edf_starvation.png`, `escalonabilidade.csv`.
Achados: (i) sob sobrecarga o EDF sofre efeito dominó (QoS da voz cai a 0,19 em 2,0x) e `prio` não;
(ii) `prio` starva dados (~4 s sem PRB em 2,4x); (iii) `dwrr` tem starvation 0 (quantum garante
serviço) mas perde voz em 2,4x; (iv) `fifo` é o pior para voz já em 1,6x.

## Latência das produtoras, mlockall e validação do canal

- Cada produtora registra `acordou - ideal` a cada `clock_nanosleep` em `<out>.producers.csv`
  (`class,ideal_ns,latency_ns`). `python -m analysis.producers` gera `results/produtoras_*.csv/png`.
- `mlockall(MCL_CURRENT|MCL_FUTURE)` roda por padrão (`--no-mlock` desliga). Precisa de
  `@wheel - memlock unlimited` em `/etc/security/limits.d/99-rt.conf`; sem isso o núcleo avisa e segue sem travar.
- `python -m analysis.validate_channel` compara PRBs médios × distância com a teoria (Gamma/MRC).
- Resumo dos resultados e roteiro do vídeo: `results/RESUMO_RESULTADOS.md`.

## Experimentos pré-registrados (contribuição científica)
Protocolo (hipóteses H1–H6 e regras de decisão escritas antes de rodar): `results/EXPERIMENTOS.md`.
- Nova política `prio_floor` (prioridade estrita + piso de PRB/slot): `--floor-video N --floor-data N`.
- Rajadas escalonadas: `--stagger K` (K sub-rajadas por período).
- Rodar (≈2 h, retomável): `./venv/bin/python -m analysis.experiments run E1 E2 E3 E4 E5 --cpus 1 2 3`
- Relatório/vereditos/figuras: `./venv/bin/python -m analysis.exp_report` → `results/exp/`.
- Resultados: seção "Resultados" de `results/EXPERIMENTOS.md` (H3 refutada, as demais suportadas ou inconclusivas).

## Simplificações assumidas

Rajadas simultâneas (pior caso), sem fragmentação de vídeo, sem HARQ/MCS discreto, shadowing
estático por traço, um usuário representativo no canal. Capacidade: PRBs = 50 · SE/4, com
SE = min(log2(1+SNR), 7,4) bit/s/Hz.
