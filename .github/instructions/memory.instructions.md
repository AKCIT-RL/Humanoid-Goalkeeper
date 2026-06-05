---
applyTo: "**"
---

# Arquitetura de memória

Este projeto usa o **memory tool** do Copilot com 3 escopos.

## Escopos

| Escopo | Pasta | Persiste | Quando usar |
|--------|-------|----------|-------------|
| **Sessão** | `/memories/session/` | Conversa atual | Quadro compartilhado entre subagentes |
| **Repositório** | `/memories/repo/` | Workspace local | Fatos sobre este projeto |
| **Usuário** | `/memories/` | Todas as conversas | Preferências pessoais |

## Estrutura padrão de `/memories/repo/`

```
/memories/repo/
├── INDEX.md          # SEMPRE leia primeiro
├── architecture.md
├── conventions.md
├── commands.md
├── gotchas.md
└── decisions.md
```

## Estrutura padrão de `/memories/session/`

```
/memories/session/
├── plan.md       # Planner escreve
├── findings.md   # Explorer anexa
└── review.md     # Reviewer escreve
```

## Regras de tamanho

- `INDEX.md` (repo): **máximo 50 linhas**.
- Arquivos de tópico em `repo/`: alvo <200 linhas.
- Bullets curtos > parágrafos longos.

## Quem pode escrever onde

| Subagente    | session/ | repo/ |
|--------------|----------|-------|
| Orchestrator | leitura  | leitura |
| Planner      | **escreve `plan.md`** | leitura |
| Explorer     | **escreve `findings.md`** | propõe promoção |
| Implementer  | leitura  | leitura |
| Tester       | leitura  | leitura |
| Reviewer     | **escreve `review.md`** | propõe promoção |
| Docs Writer  | leitura  | leitura |
