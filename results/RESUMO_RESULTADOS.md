# Resumo de resultados (insumo para relatório e vídeo)

Reprodução: ver `README.md`. Plataforma: Linux (Fedora), 8 núcleos, `SCHED_FIFO`, governor `performance`,
núcleo fixado com `--cpu 2`. Slot = 1 ms, capacidade fixa = 50 PRB/slot. Voz: 100 pacotes × 2 PRB a cada
20 ms (prazo 20 ms); vídeo: 40 × 10 PRB a cada 33 ms (prazo 50 ms); dados: Poisson, 20 PRB (prazo 500 ms).
QoS = entregues no prazo / oferecidos (descartes e pacotes não atendidos contam contra).

## Figuras (em `results/`)

| Figura | O que mostra | Parte |
|---|---|---|
| `edf_qos.png` | QoS × carga, 4 políticas, canal fixo, 20 sementes | Montez/Richard |
| `edf_starvation.png` | Maior espera sem PRB (ms) × carga, por política | Montez |
| `inversao.png` | Espera no mutex e deadline da voz: baseline × sem herança × `PTHREAD_PRIO_INHERIT` | Montez |
| `produtoras.png` | CCDF da latência de despertar das produtoras (`clock_nanosleep`) | Montez |
| `validacao_canal.png` | PRBs médios × distância: simulação × teoria (1/2/4 antenas MRC) | Richard |
| `fixo_qos.png`, `ray1_qos.png`, `ray4_qos.png` | QoS × carga: canal fixo, Rayleigh 1 antena, Rayleigh MRC 4 (160 m, sem shadowing, 5 sementes) | Richard |
| `sh6n30_ray{1,4}_qos.png` | Idem com shadowing 6 dB, 30 sementes (IC bootstrap) | Richard |
| `sh6_ray{1,4}_qos.png`, `inicial_qos.png` | Execuções preliminares (5 sementes; IC grande); não usar no artigo | — |

Dados: `*_raw.csv` (uma linha por execução/classe), `*_agg.csv` (média e IC 95 % bootstrap),
`escalonabilidade.csv`, `produtoras_*.csv`, `validacao_canal.csv`, `inversao_*.csv`.

## Resultados-chave

**Saturação.** U(carga 1,0) = 0,642 → saturação prevista em **1,56×** (teoria = experimento).

**Políticas, canal fixo (QoS; `edf_agg.csv`, 20 sementes).**
- `prio`: voz = 1,00 até 2,4×; vídeo = 1,00 até 2,0× e colapsa em 2,4× (voz+vídeo passam de U = 1, previsto em 2,26×); dados são sacrificados primeiro (QoS 0,05 em 2,0×; ~4 s sem PRB em 2,4×).
- `fifo`: pior para voz já em 1,6× (QoS 0,105), pois a voz espera atrás de vídeo/dados.
- `edf`: bom até ~1,6×, mas **efeito dominó** na sobrecarga (voz 0,19 em 2,0×).
- `dwrr`: starvation = 0 em todas as cargas (quantum garante serviço), mas voz cai a 0,01 em 2,4×.

**Starvation (maior espera sem PRB, ms, média de 20 sementes).**

| Classe, carga 2,0× | prio | edf | fifo | dwrr |
|---|---|---|---|---|
| voz | 0 | 38,7 | 43,1 | 0 |
| vídeo | 8 | 33,6 | 33,7 | 0 |
| dados | 32 | 32 | 24 | 0 |

**Canal (5 sementes, 160 m, sem shadowing).** Rayleigh 1 antena antecipa a degradação (voz com `fifo` 0,41 em 1,5×).
Com MRC 4 antenas tudo fica em QoS ≈ 1 até 2,4× (voz com `prio` = 1,00). Com shadowing 6 dB e 30 sementes
(carga 1,6×): voz com `prio` = 0,90 (1 antena) e 1,00 (4 antenas). A variância entre sementes vem do sorteio
estático de shadowing (bimodal); por isso IC por bootstrap.

**Validação do canal.** Erro máximo simulação × teoria (Gamma(L,1) com Shannon truncado) ≤ 0,5 PRB (arredondamento).

**Inversão de prioridade (5 sementes × 10 s).**

| Cenário | Espera máx. no mutex | Voz: perdas de deadline |
|---|---|---|
| baseline (sem hog) | 1,35 ms | 0 % |
| sem herança | 21,4 ms | 20 % |
| `PTHREAD_PRIO_INHERIT` | 1,57 ms | 0 % |

**Escalonabilidade analítica** (`analysis/schedulability.py`): Liu-Layland para voz+vídeo = 0,828 (suficiente, conservador);
tempo de resposta de prioridade fixa: voz 4 ms × L, vídeo ≤ 32 ms até 2,0×; EDF viável só até U ≤ 1 (1,56×).

**Latência de despertar das produtoras** (10 sementes × 10 s, carga 1,5, sem `mlockall`):

| Classe | P50 | P99 | P99,9 | máx |
|---|---|---|---|---|
| voz | 9,4 µs | 53 µs | 101 µs | 155 µs |
| vídeo | 10,7 µs | 63 µs | 115 µs | 165 µs |
| dados | 3,0 µs | 36 µs | 63 µs | 226 µs |

Máximo de 0,23 ms ≪ prazo de 20 ms: o jitter do SO é desprezível frente ao jitter de fila. Page faults: ~1400 menores, 0 maiores por execução.

## Experimentos pré-registrados (resultados finais; supersedem os preliminares)
Ver `results/EXPERIMENTOS.md` (protocolo + resultados) e `results/exp/` (dados, manifesto, `veredito.csv`,
figuras `E1_capacidade.png`, `E1_qos_vs_carga.png`, `E2_piso.png`, `E3_rajadas.png`, `E5_velocidade.png`).
- Capacidade sob SLA (QoS≥0,99) com média de PRB igualada: prio 1,50→1,98× (L1→L4), fifo 1,00→1,24×, dwrr 1,00→1,53×, edf ~1,5× (quase sem ganho).
- Política vale ~2× mais que diversidade (prio−fifo +0,49 vs. +0,24).
- Piso de dados: H3 refutada sob Rayleigh (starvation 3 ms, vídeo perde 0,8–15 p.p.); no canal fixo, sem custo.
- Fading mais rápido melhora a voz (+0,029 de 0,3→30 m/s); ordem das políticas independe de K.
- Execuções curtas sem trim enviesam o QoS em até +0,66.

## `mlockall`
Implementado (`--no-mlock` desliga). Exige `RLIMIT_MEMLOCK` alto (pilhas de 8 MB por thread e os logs
são travados). No ambiente atual o limite é 8 MB, então o núcleo avisa e roda sem travar. Para ativar:
`@wheel - memlock unlimited` em `/etc/security/limits.d/99-rt.conf`, novo login, e rodar
`python -m analysis.producers` (compara com × sem `mlockall`). **Pendente: medir o efeito.**

## Roteiro sugerido para o vídeo (demonstração)
1. Arquitetura: produtoras (voz/vídeo/dados) → filas → escalonadora (prio 90) → log; monitora via semáforo.
2. Rodar `prio` em 1,0× e mostrar o monitor; subir para 2,0× e ver os dados starvarem (`starvation.csv`).
3. Comparar `fifo` × `prio` × `edf` × `dwrr` (`edf_qos.png`, `edf_starvation.png`).
4. Inversão de prioridade: `--inversion` sem e com `--prio-inherit` (`inversao.png`).
5. Canal Rayleigh/MRC: `ray1` × `ray4`.

## Limitações a declarar
- Rajadas síncronas (pior caso), sem fragmentação/HARQ/MCS discreto; shadowing estático por execução.
- Sweeps de canal com 5 sementes (exceto `sh6n30`); EDF só no canal fixo.
- Pacotes ainda na fila ao fim da execução contam como não entregues (sem warm-up/trim).
- Modelo analítico fluido; dados tratados por taxa média.
