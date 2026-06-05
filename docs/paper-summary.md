# Humanoid Goalkeeper — Resumo do Paper

**Paper:** [Humanoid Goalkeeper: Learning from Position Conditioned Task-Motion Constraints](https://arxiv.org/abs/2510.18002)

## Objetivo

Framework de RL para goleiro autônomo com robôs humanoides. Aprende uma única política end-to-end que integra task rewards + motion priors via esquema adversarial (AMP), gerando movimentos altamente dinâmicos e humanos.

## Arquitetura do Método

```
Observações (bola + propriocepção)
         │
         ▼
   Ball Estimator ──► prediz posição + região de pouso
         │
         ▼
   Política PPO (end-to-end)
    ├─ Task Reward (position-conditioned)
    └─ AMP Reward (motion constraints por região)
         │
         ▼
   Ações: torques articulares do humanóide
```

### Componentes-chave

1. **Position-Conditioned Task Rewards**: A área do gol é dividida em k regiões. Cada região usa a mão correspondente (esquerda/direita) e encoraja movimentos laterais ou saltos conforme necessário.

2. **Adversarial Motion Priors (AMP)**: Discriminadores por região treinados com demos humanas retargetadas. Variante "soft" que gera amostras gaussianas ao redor do movimento e premia o melhor score, evitando conflito com task rewards.

3. **Post-Task Stability**: Episódio de 3s (voo da bola ~0.4-1s). Após interceptação, recompensa por manter postura estável. Resets de ambiente com poses de outros envs (não volta à pose default).

4. **Ball Estimator**: Prediz posição da bola + classifica região de pouso. Treinado com MSE + Cross-Entropy.

5. **Noise de Treinamento**: Perturbação de posição (±5cm), dropout aleatório de observação da bola após 0.4s (simula oclusão/FOV).

## Motion Priors — Pipeline

```
Vídeos RGB de humanos ──► GVHMR (extrai poses SMPL) ──► Retarget para G1 ──► Buffer de referência por região
```

6 regiões no gol → 6 motion priors (lefthand, righthand, leftjump, rightjump, leftstep, rightstep).

Os arquivos `.pt` estão em `legged_gym/resources/datasets/goalkeeper/`.

## Treinamento

- **Simulador:** IsaacGym
- **Algoritmo:** PPO (implementação customizada em `rsl_rl/`)
- **GPU:** RTX 4090 (24GB)
- **Convergência:** ~20k episódios (goalkeeper), ~40k (escape)
- **Envs paralelos:** não especificado no paper, mas o código suporta milhares

## Observações

| Observação | Actor | Critic |
|---|---|---|
| Posição da bola (frame local) | ✓ | ✓ |
| Velocidade angular base | ✓ | ✓ |
| Vetor de gravidade projetado | ✓ | ✓ |
| Posições articulares | ✓ | ✓ |
| Velocidades articulares | ✓ | ✓ |
| Ação anterior | ✓ | ✓ |
| Velocidade linear base | - | ✓ |
| Região alvo final | - | ✓ |
| Alvo end-effector | - | ✓ |
| Velocidade da bola (frame local) | - | ✓ |
| Posição mão esquerda/direita | - | ✓ |
| Distância de alcance | - | ✓ |

## Resultados

- **Simulação:** maior taxa de sucesso entre todos os baselines, com melhor resemblance de movimento.
- **Hardware (MoCap):** 21/30 saves totais (falhas concentradas em regiões superiores).
- **Hardware (câmera):** 14/30 saves (limitado pelo FOV estreito da câmera).
- **Goleiro contínuo:** capaz de saves consecutivos sem reset para pose default.

## Tarefas de Generalização

- **Ball Escaping:** salto/agachamento para desviar da bola (branch `escape` no repo).
- **Ball Grabbing:** pegar bola com bolsa macia (taxa menor por deformabilidade da bolsa).

## Robô Original

O paper usa o **Unitree G1** (29 DoF). Para adaptar ao **Booster T1**, é necessário:
1. Retargetar os motion priors para o T1 (via ViMoS/GMR)
2. Adaptar a config do env (URDF, limites articulares, observações)
3. Treinar com a task do T1

## Conexão com ViMoS

O ViMoS fornece a pipeline completa:
1. **Stage 1 (GENMO):** Vídeo → SMPL-X poses
2. **Stage 2 (GMR):** SMPL-X → movimentos do robô (CSV/PKL)
3. **Stage 3 (whole_body_tracking):** CSV → NPZ → treino de política (Isaac Lab / PPO)
4. **Stage 4 (deploy):** deploy no T1 via TorchScript JIT

Para o projeto goalkeeper no T1, usaríamos:
- ViMoS Stage 1+2 para converter vídeos de goleiro → movimentos do T1
- O treinamento do Humanoid-Goalkeeper (com AMP) adaptado para o T1, OU
- ViMoS Stage 3 (BeyondMimic) para treinar motion tracking no T1
