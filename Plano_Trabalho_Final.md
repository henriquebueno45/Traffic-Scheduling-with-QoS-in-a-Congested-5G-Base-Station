# Plano do Trabalho Final: Escalonamento de tráfego com QoS em uma gNB 5G

Trabalho único, entregue em duas disciplinas:
- **Concorrência e Tempo Real (prof. Montez):** prioridade. Aplicação multithread em C/Linux.
- **Comunicações sem Fio (prof. Richard Demo Souza):** análise de rede sobre o mesmo código, com modelo de canal. Relatório em formato de artigo.

Autor: Henrique Bueno de Morais (equipe individual).

---

## 1. Ideia

Em uma rede 5G, a estação-base (gNB) divide seus recursos de rádio entre voz, vídeo e dados. A voz exige baixo atraso, o vídeo exige taxa razoável e os dados toleram esperar. Sob congestionamento, a política de escalonamento define quem é beneficiado e quem é prejudicado.

O trabalho implementa o escalonador de uma gNB como uma aplicação multithread real, compara políticas (FIFO, prioridade estrita, WRR/DWRR) e, na parte de sem fio, faz a capacidade de cada slot depender de um modelo de canal (path loss, shadowing, desvanecimento, diversidade).

Pergunta central: como cada política distribui o desempenho entre as classes sob congestionamento, e como a qualidade do canal altera esse resultado?

## 2. Resumo para a proposta do Richard

**Título:** Escalonamento de tráfego com QoS em uma estação-base 5G sob congestionamento: comparação de políticas de priorização para voz, vídeo e dados em canais com desvanecimento

**Descrição:** a estação-base divide seus recursos de rádio entre voz, vídeo e dados. A voz exige baixo atraso, o vídeo exige taxa razoável e os dados toleram esperar. Quando a rede congestiona, a escolha de quem atender primeiro faz muita diferença. O trabalho simula/emula esse cenário com um canal cuja qualidade varia com a distância (perda de percurso e sombreamento) e com o desvanecimento de pequena escala; a taxa de cada usuário vem da capacidade do canal. São comparadas FIFO, prioridade estrita e WRR/DWRR. A carga é aumentada até congestionar, medindo atraso, jitter, perda, vazão e starvation por classe, e avaliando como o canal (com e sem diversidade de antenas) muda o resultado. O tema é relacionado aos requisitos de QoS do 5G/6G e a Network Slicing.

**Equipe:** 1 integrante. Justificativa: curso a disciplina de forma totalmente remota e trabalho 8 h por dia, o que torna inviável combinar horários com outros integrantes.

**Entrega:** relatório em formato de artigo científico, enviado pelo Moodle, com gráficos e discussão. Código anexado.

Nota: acrescentar que o escalonador é uma implementação multithread desenvolvida também em outra disciplina, e que neste trabalho o foco é a análise com o modelo de canal. Avisar os dois professores sobre o reaproveitamento.

## 3. Arquitetura (um núcleo, duas camadas)

**Núcleo (Montez), C com Pthreads no Linux:**
- Uma thread periódica por classe: voz (ex.: 20 ms), vídeo (ex.: 33 ms), dados (esporádica). Usar `clock_nanosleep` com `TIMER_ABSTIME`.
- Thread escalonadora (ciclo por slot) e thread monitora.
- Recurso de rádio (orçamento de PRBs por slot) compartilhado, protegido por mutex/semáforo.
- Prioridades de SO com `SCHED_FIFO` (Rate Monotonic), tudo fixado em um núcleo (`taskset`) para forçar a disputa.
- Experimentos: inversão de prioridade (sem e com `PTHREAD_PRIO_INHERIT`), starvation, latência de escalonamento, violação de deadline.

**Camada sem fio (Richard):**
- Módulo de canal que define a capacidade de cada slot: path loss log-distância, shadowing log-normal, Rayleigh (Nakagami opcional), capacidade de Shannon, diversidade (MRC com 1, 2 e 4 antenas) como extensão.
- Análise em Python (NumPy, pandas, Matplotlib) dos logs gerados pelo núcleo.

**Decisões de projeto para não refazer depois:**
1. Capacidade por slot como função substituível: primeiro um valor fixo, depois lê um traço de canal.
2. Políticas como módulos com a mesma interface, escolhidas por linha de comando.
3. Log estruturado em CSV por pacote (classe, tempos de chegada, início e fim do atendimento, descartado ou não).
4. Parâmetros por linha de comando (carga, política, semente, duração) para automatizar as varreduras.
5. Repetições por configuração e percentis (P95, P99).

Observações:
- Wokwi/FreeRTOS não é indicado: simula microcontroladores com pouca memória e mede tempo de forma pouco realista. Linux com Pthreads permite `SCHED_FIFO`, herança de prioridade e relógios de alta resolução.
- `SCHED_FIFO` exige root ou `CAP_SYS_NICE`. Testar cedo.
- Resultados em tempo real variam entre execuções: repetir e reportar percentis.

## 4. Tarefas por fase

### Fase 0: Preparação (1 a 3 dias)
- [ ] Ler o edital do Montez e confirmar requisitos (linguagem, mecanismos obrigatórios, formato, datas).
- [ ] Confirmar as datas de entrega do Richard.
- [ ] Avisar os dois professores sobre o reaproveitamento.
- [ ] Montar ambiente: Linux, `gcc`, `pthread`, Python (NumPy, pandas, Matplotlib), repositório git.
- [ ] Testar `SCHED_FIFO` e `taskset`.

### Parte A: Montez (prioridade)

**Fase 1: Esqueleto concorrente**
- [ ] Estruturas: pacote, fila por classe (buffer circular), recurso de rádio (PRBs por slot).
- [ ] Threads periódicas por classe com `clock_nanosleep` absoluto.
- [ ] Thread escalonadora (ciclo por slot) e thread monitora.
- [ ] Sincronização: mutex, variáveis de condição e/ou semáforos.
- [ ] Prioridades `SCHED_FIFO` (RM) e fixação em um núcleo.
- [ ] Log em CSV por pacote.

**Fase 2: Fenômenos de tempo real**
- [ ] Políticas selecionáveis: FIFO, prioridade estrita, DWRR.
- [ ] Experimento de inversão de prioridade, sem e com `PTHREAD_PRIO_INHERIT`.
- [ ] Medição de latência de escalonamento, violação de deadline e starvation.
- [ ] Teste de carga crescente até saturar.

**Fase 3: Fechamento (entrega do Montez)**
- [ ] Scripts de execução e de análise dos logs.
- [ ] Relatório (arquitetura, decisões, resultados, discussão) e demonstração.
- [ ] **Entrega do Montez.**

### Parte B: Richard

**Fase 4: Módulo de canal**
- [ ] Path loss log-distância e shadowing log-normal (ajustar com medidas próprias, se houver).
- [ ] Desvanecimento Rayleigh com correlação temporal (Nakagami opcional).
- [ ] Capacidade de Shannon e conversão em PRBs por slot.
- [ ] Diversidade com 1, 2 e 4 antenas (MRC), como extensão.
- [ ] Gerar traços de canal (Python ou C) e validar com gráfico de capacidade × distância.
- [ ] Integrar ao núcleo: a função "capacidade do slot" lê o traço.
- Pode ser escrito em Python durante a fase 2, sem bloquear o resto.

**Fase 5: Experimentos e análise**
- [ ] Cenários: canal fixo, Rayleigh, Rayleigh com diversidade.
- [ ] Varreduras de carga com 20 a 30 repetições por ponto e intervalo de confiança.
- [ ] Métricas por classe: atraso (média e P95), jitter, perda, vazão, starvation, entrega dentro do prazo, justiça (Jain).
- [ ] Gráficos comparando políticas e cenários, com resolução maior perto do ponto de saturação.
- [ ] Opcional: variante de prioridade estrita com piso mínimo para vídeo e dados.

**Fase 6: Artigo (entrega do Richard)**
- [ ] Resumo, introdução, trabalhos relacionados, modelo, metodologia, resultados, conclusão e referências.
- [ ] Enviar pelo Moodle.

## 5. Riscos e como tratar
- **Tempo:** o escopo combinado é grande. Cortar primeiro diversidade, Nakagami e o piso mínimo.
- **Reprodutibilidade:** resultados em tempo real variam. Repetir execuções e reportar percentis.
- **Duplicação entre relatórios:** o do Montez foca em concorrência; o artigo do Richard foca em canal e comparação das políticas.
- **Dependências:** a fase 4 só se integra depois da 3, mas o modelo de canal pode ser desenvolvido em paralelo.
- **Prazos:** o plano supõe que a entrega do Richard vem depois da do Montez. Confirmar.

## 6. Métricas e metodologia (lições dos trabalhos lidos)
- Preferir taxa de entrega e descumprimento de prazo à latência média, que sofre viés de sobrevivência sob saturação (contar pacotes descartados).
- Medida sugerida: "QoS satisfaction" = taxa de entrega × (1 − descumprimento de prazo).
- Varrer a carga com mais resolução perto do ponto de saturação, onde as políticas se separam.
- Reportar P95/P99, jitter, starvation e índice de Jain, com intervalo de confiança.
- Opcional: modelar a fragmentação do vídeo (um quadro só conta se todos os pacotes chegam a tempo).

## 7. Trabalhos relacionados
Lidos na íntegra (acesso aberto):
- Subudhi et al., *Performance Evaluation of Scheduling Scheme in O-RAN 5G Network using NS-3*, arXiv 2504.00417. Compara RR, Max-Throughput e PF; as vazões médias são parecidas e a diferença está na justiça entre usuários.
- Zanbouri et al., *Overload-Robust Latency in 5G-TSN: A HoL-Enhanced Hybrid Lyapunov Approach for 3GPP Indoor Factory Environments*, arXiv 2609.26011. Saturação em cerca de 12 usuários, igual para todos os escalonadores; sob 2,5× de carga o isolamento de classes protege o URLLC (82,7% de entrega, contra 44 a 46% do PF), mas o eMBB cai a 0% e a vazão agregada cai até 3×.

Não lidos (acesso fechado; só resumos):
- Afroz, Sandrasegaran e Ghosal, *Performance analysis of PF, M-LWDF and EXP/PF packet scheduling algorithms in 3GPP LTE downlink*, ATNAC 2014, DOI 10.1109/atnac.2014.7020879.
- Lai e Tang, *QoS-aware downlink packet scheduling for LTE networks*, Computer Networks, 2013, DOI 10.1016/j.comnet.2013.02.017.
- Yin, Zhang e Roy, *Multiplexing URLLC Traffic within eMBB Services in 5G NR: Fair Scheduling*, IEEE Trans. Commun., 2020, DOI 10.1109/tcomm.2020.3035582.
- Markova et al., *Priority-based Coexistence of eMBB and URLLC Traffic in Industrial 5G NR Deployments*, ICUMT 2020, DOI 10.1109/icumt51630.2020.9222433.
- Ksentini et al., *Providing Low Latency Guarantees for Slicing-Ready 5G Systems via Two-Level MAC Scheduling*, IEEE Network, 2018, DOI 10.1109/mnet.2018.1800005.
- Wang et al., *Energy-Efficient Priority-Based Scheduling for Wireless Network Slicing*, GLOBECOM 2018, DOI 10.1109/glocom.2018.8647696.

Citar os não lidos apenas com o que o resumo diz, ou obter os PDFs pela VPN/Portal de Periódicos da UFSC.

## 8. Ferramentas
- **Escolhido:** C com Pthreads (núcleo) e Python (canal e gráficos).
- **Alternativas descartadas por ora:** ns-3 + 5G-LENA, Simu5G (OMNeT++), Vienna 5G SLS, LTE-Sim, Sionna. Úteis como referência ou validação opcional; o OMNeT++/Simu5G tem curva de aprendizado alta e dificulta encaixar os modelos de canal vistos em aula.

## 9. Ligação com o conteúdo da disciplina do Richard
- Larga escala: path loss e shadowing.
- Pequena escala: Rayleigh e Nakagami.
- Capacidade: Shannon.
- OFDM: os recursos escalonados são blocos de recursos OFDM.
- Diversidade no tempo e no espaço: MRC com várias antenas, como aprofundamento.

## 10. Pendências
- [ ] Datas de entrega das duas disciplinas (para montar o cronograma semanal).
- [ ] Edital do Montez (formato e requisitos).
- [ ] Aprovação dos dois professores para o reaproveitamento.
- [ ] Decidir se o esqueleto do projeto (pastas, `Makefile`, estruturas em C, scripts de análise) será criado nesta pasta.
