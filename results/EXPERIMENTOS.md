# Protocolo experimental (pré-registro)

Escrito **antes** de rodar os experimentos. Hipóteses, métricas e regras de decisão não mudam depois
de ver os dados; qualquer desvio será listado no fim do documento, em "Desvios".

## Cenário comum
Mesmo núcleo C/Pthreads (`core/`), slot de 1 ms, 50 PRB/slot de capacidade média, classes e prazos do
`README.md`. Sementes **pareadas**: a semente `s` gera as mesmas chegadas de dados e o mesmo traço de
canal para todas as políticas, então as comparações são feitas por diferença dentro da semente.
Incerteza: IC 95 % por bootstrap (2000 reamostragens) sobre as sementes. Execuções: 6 s, janela de
medição = chegadas em [1,0 s ; 5,5 s] (warm-up 1 s; tail 0,5 s = maior prazo), exceto onde indicado.
Cada execução grava um `manifest.json` (parâmetros, hash do binário e dos fontes, máquina).

**Métricas.**
- QoS = pacotes entregues no prazo / oferecidos, por classe.
- `max_starve_ms` = maior intervalo seguido sem PRB com fila não vazia.
- **SLA** = QoS(voz) ≥ 0,99 **e** QoS(vídeo) ≥ 0,99.
- **Capacidade sob SLA** (`C_SLA`) = maior carga relativa que ainda cumpre o SLA. Por semente: varre as
  cargas em ordem crescente e interpola linearmente o cruzamento descendente de min(QoS_voz, QoS_vídeo)
  com 0,99. Se nunca cruza, o valor é **censurado** no maior valor da grade (e reportado como tal).

**Canais** (shadowing = 0 dB, velocidade 1,5 m/s, 3,5 GHz, exceto H5):
`fixo` (50 PRB) e Rayleigh com MRC de L ∈ {1, 2, 4} ramos, com a distância ajustada para que **a média
seja 50 PRB em todos** (raiz da expressão teórica de `validate_channel.py`; a média simulada é
conferida no manifesto). Assim L altera só a variância, não a média.

## Hipóteses

**H1 (variância isolada).** Com média fixa de 50 PRB, `C_SLA` cresce com L para toda política.
Regra: para cada política, a diferença pareada `C_SLA(L=4) − C_SLA(L=1)` tem IC 95 % inteiramente > 0.
Nula: diversidade só ajuda por aumentar a média.

**H2 (política × diversidade).** Compara tamanhos de efeito em `C_SLA` com L=1: ganho de política
(`prio` − `fifo`) contra ganho de diversidade (`fifo` com L=4 − `fifo` com L=1). Sem veredito de
direção; reporta ambos com IC e o IC da diferença entre os dois.

**H3 (piso mínimo).** Em sobrecarga (1,6× e 2,0×), um piso de dados de 1 a 2 PRB/slot elimina o
starvation dos dados (`max_starve_ms` ≤ 1 ms em todas as sementes) com custo ≤ 0,01 (absoluto) na QoS
de voz e de vídeo, em relação a `prio`. Regra: IC 95 % da diferença pareada de QoS dentro de [−0,01; 0,01].
Reporta também QoS e vazão dos dados (o piso pode evitar starvation sem entregar no prazo).

**H4 (rajadas escalonadas).** A ordem das políticas por QoS de voz (1,5× e 1,8×, canal fixo) não
depende de K ∈ {1, 2, 5, 10, 20} sub-rajadas por período. Regra: a ordem das médias é a mesma de K=1
para todo K; qualquer troca de ordem com IC da diferença excluindo 0 refuta H4.

**H5 (fading × prazo).** Em Rayleigh L=1, a QoS de voz melhora com a velocidade (tempo de coerência
menor que o prazo de 20 ms permite média temporal). Regra: `QoS(30 m/s) − QoS(0,3 m/s)` com IC 95 % > 0
para `prio` a 1,5×. Velocidades: 0,3; 1,5; 5; 15; 30 m/s (f_D = 3,5 a 350 Hz; T_c ≈ 0,42/f_D).

**H6 (viés de truncamento).** Sem warm-up/tail, com 4 s, a QoS em sobrecarga difere da referência
(20 s com warm-up/tail). Regra: |diferença| > 0,01 com IC excluindo 0 em ao menos uma combinação
(política, carga); reporta também se a ordem das políticas muda.

## Desvios
Nenhum desvio das regras de decisão. Os vereditos abaixo aplicam as regras exatamente como escritas.
Observação de transparência: em L1, `fifo` e `dwrr` já violam o SLA na menor carga testada (1,0×);
essas sementes são censuradas à esquerda (C_SLA = 1,0), logo o ganho da diversidade para elas é um
**limite inferior** (isso só reforça H1).

## Resultados (3400 execuções; `analysis.experiments` + `analysis.exp_report`)
Dados: `results/exp/E*_raw.csv`; manifesto (hashes do binário/fontes): `results/exp/manifest_*.json`;
vereditos: `results/exp/veredito.csv`; figuras `results/exp/E*.png`.

| H | Veredito | Resultado |
|---|----------|-----------|
| H1 | SUPORTADA | Com média de PRB igualada, L=4 amplia C_SLA (IC95% > 0) em todas as políticas: fifo +0,24, prio +0,49, edf +0,05, dwrr +0,53, prio_floor +0,48 |
| H2 | INCONCLUSIVA (descritiva) | Política (prio−fifo, L=1) +0,49 [0,39; 0,60] vs. diversidade (fifo L4−L1) +0,24 [0,22; 0,26]: a escolha da política vale ~2× a diversidade |
| H3 | **REFUTADA** | Canal fixo: piso de 1–2 PRB elimina starvation de dados (≤1 ms) sem custo. Canal Rayleigh: starvation cai de ~525–1387 ms para 3 ms (não ≤1 ms, por fades com capacidade nula) e o vídeo perde 0,8–15 p.p. (>0,01) em 1,6–2,0× |
| H4 | SUPORTADA | A ordem das políticas (voz) não depende de K (rajadas escalonadas) |
| H5 | SUPORTADA | Voz com prio a 1,5×: +0,029 [0,021; 0,038] de 0,3→30 m/s (fading rápido ajuda; coerência lenta > prazo prejudica) |
| H6 | SUPORTADA | Execuções curtas sem trim distorcem o QoS em até +0,66 (fifo/dados) e +0,31 (edf/voz); a ordem prio>edf>fifo se mantém |

Capacidade sob SLA (carga relativa, mediana por cenário; `E1_capacidade_tabela.csv`):

| política | L1 | L2 | L4 | canal fixo |
|---|---|---|---|---|
| fifo | 1,00 | 1,09 | 1,24 | 1,49 |
| dwrr | 1,00 | 1,16 | 1,53 | 1,60 |
| edf | 1,49 | 1,53 | 1,54 | 1,57 |
| prio | 1,50 | 1,77 | 1,98 | 2,20 |
| prio_floor | 1,39 | 1,66 | 1,87 | 2,00 |

Conclusões: (i) diversidade tem ganho real mesmo com média igual (redução de profundidade de fade),
sendo maior com políticas que protegem a voz sob o limite de capacidade (prio, dwrr); com EDF quase
nada, pois o efeito dominó domina; (ii) o piso é um trade-off (Pareto) sob fading: protege dados à custa
do vídeo; (iii) durações curtas sem aparar aquecimento/cauda enviesam fortemente o QoS.
Limitações: SLA fixado em 0,99; um modelo de canal por usuário; sem medição de `mlockall` (memlock 8 MB).
