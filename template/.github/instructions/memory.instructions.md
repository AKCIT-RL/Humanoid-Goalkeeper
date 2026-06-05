---
applyTo: "**"
---

# Arquitetura de memória

Este projeto usa o **memory tool** do Copilot com 3 escopos. Use-os com disciplina — memória mal usada vira lixo que polui o contexto.

## Escopos

| Escopo | Pasta | Persiste | Quando usar |
|--------|-------|----------|-------------|
| **Sessão** | `/memories/session/` | Conversa atual | Quadro compartilhado entre subagentes (plano, findings, review) |
| **Repositório** | `/memories/repo/` | Workspace local | Fatos sobre **este** projeto: comandos, convenções, arquitetura, gotchas |
| **Usuário** | `/memories/` | Todas as conversas | Preferências pessoais, padrões cross-projeto. Raramente escrito por subagentes. |

## Estrutura padrão de `/memories/repo/`

Hierarquia inspirada no padrão **MEMORY.md** do Claude Code (índice curto + arquivos de tópico sob demanda):

```
/memories/repo/
├── INDEX.md          # SEMPRE leia primeiro. Lista tópicos → arquivo.
├── architecture.md   # Visão geral do código (módulos, fluxo)
├── conventions.md    # Padrões descobertos (estilo, naming, patterns)
├── commands.md       # Build, test, lint, run (que Copilot não infere lendo)
├── gotchas.md        # Bugs estranhos, workarounds, "nunca faça X"
└── decisions.md      # Decisões arquiteturais ("usamos pydantic v2 porque...")
```

Crie esses arquivos **só quando tiver algo concreto** a registrar. Não crie esqueletos vazios.

## Estrutura padrão de `/memories/session/`

```
/memories/session/
├── plan.md       # Planner escreve. Implementer/Tester/Reviewer leem.
├── findings.md   # Explorer anexa descobertas estruturadas.
└── review.md     # Reviewer escreve veredito final.
```

Sessão é **descartável**. Não promova nada para `repo/` sem critério (ver "Promoção" abaixo).

## Regras de tamanho

- `INDEX.md` (repo): **máximo 50 linhas**. É carregado em toda conversa.
- Arquivos de tópico em `repo/`: alvo <200 linhas. Se cresceu, quebre em sub-arquivos.
- Arquivos em `session/`: sem limite, mas sejam objetivos.
- Bullets curtos > parágrafos longos.

## Quando escrever em `repo/` (promoção)

Promova algo de `session/` ou da conversa para `repo/` **somente se** atender a um destes critérios:

1. **Vai ser útil em outra conversa** (ex: comando de teste não-óbvio).
2. **Evitaria um erro repetido** (ex: "API X exige header Y").
3. **É uma convenção do projeto** que o Copilot não infere lendo um arquivo.

**Não promova:**
- Coisas óbvias do código (Copilot lê o arquivo de novo).
- Decisões temporárias ou específicas da tarefa atual.
- Resumos de implementação (o git diff já é a fonte de verdade).

## Quem pode escrever onde

| Subagente    | session/ | repo/ | Notas |
|--------------|----------|-------|-------|
| Orchestrator | leitura  | leitura | Não escreve memória; só lê para decidir |
| Planner      | **escreve `plan.md`** | leitura | Lê INDEX antes de planejar |
| Explorer     | **escreve `findings.md`** | propõe promoção | Sugere updates ao INDEX se descobrir algo novo |
| Implementer  | leitura  | leitura | Só lê plano e convenções |
| Tester       | leitura  | leitura | — |
| Reviewer     | **escreve `review.md`** | propõe promoção | Sugere registrar gotchas encontrados |
| Docs Writer  | leitura  | leitura | — |

"Propõe promoção" = o subagente sugere ao Orchestrator no retorno; o Orchestrator decide se passa para Implementer/Docs gravar.

## Manutenção

- **No início de cada conversa**: o Orchestrator lê `repo/INDEX.md` se existir.
- **Ao detectar info desatualizada** em `repo/`: atualize ou remova — não acumule entradas conflitantes.
- **Ao fim de uma tarefa relevante**: avalie promoção de `session/` para `repo/`.
- **`session/` é limpa** automaticamente entre conversas — não dependa de nada lá.
