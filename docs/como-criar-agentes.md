# Como criar agentes customizados para o GitHub Copilot

Guia prático baseado na criação do sistema de agentes deste projeto.

## Estrutura de arquivos

```
.github/
├── agents/                          # Agentes customizados
│   ├── orchestrator.agent.md        # Aparece no seletor (user-invocable: true)
│   ├── planner.agent.md             # Subagente (user-invocable: false)
│   ├── explorer.agent.md
│   ├── implementer.agent.md
│   ├── tester.agent.md
│   ├── reviewer.agent.md
│   └── docs-writer.agent.md
├── instructions/                    # Regras automáticas por glob
│   ├── python.instructions.md       # applyTo: "**/*.py"
│   └── memory.instructions.md       # applyTo: "**"
├── prompts/                         # Slash commands (/review-diff, /add-test)
│   ├── review-diff.prompt.md
│   └── add-test.prompt.md
└── copilot-instructions.md          # Regras globais (sempre carregado)
```

## Anatomia de um `.agent.md`

```yaml
---
description: "Frase curta que descreve O QUE faz e QUANDO usar. Use when: ..."
tools: [read, search, edit, execute, agent, todo, web]
user-invocable: true          # true = aparece no seletor | false = só subagente
model: "Claude Sonnet 4"     # opcional, usa o default do seletor
---

# Nome do Agente

Corpo em Markdown com instruções detalhadas.
```

### Campos do frontmatter

| Campo | Obrigatório | Descrição |
|---|---|---|
| `description` | **Sim** | Como o Copilot decide quando invocar o agente. Inclua "Use when: ..." com keywords. |
| `tools` | Não | Lista de aliases de ferramentas. Omitir = todas. `[]` = nenhuma. |
| `user-invocable` | Não | Default `true`. Use `false` para subagentes. |
| `model` | Não | Modelo específico. Aceita array para fallback. |
| `agents` | Não | Restringe quais subagentes pode chamar. Omitir = todos. |
| `argument-hint` | Não | Texto de ajuda no input do chat. |

### Aliases de ferramentas

| Alias | Permite |
|---|---|
| `read` | Ler arquivos |
| `search` | Buscar arquivos/texto |
| `edit` | Editar arquivos |
| `execute` | Rodar comandos no terminal |
| `agent` | Chamar subagentes |
| `todo` | Gerenciar lista de tarefas |
| `web` | Buscar na web / fetch URLs |

## Passo a passo: criando um agente

### 1. Defina o papel

Responda:
- O que esse agente faz? (1 frase)
- Quando deve ser escolhido ao invés do default? (keywords)
- Quais ferramentas precisa? (mínimo necessário)
- O que ele NÃO deve fazer? (limites claros)

### 2. Crie o arquivo

Caminho: `.github/agents/<nome>.agent.md`

O nome do arquivo (sem extensão) é o nome do agente no seletor.

### 3. Escreva o frontmatter

A `description` é o campo mais importante — é a superfície de descoberta. Se as keywords certas não estiverem na description, o agente não será encontrado.

```yaml
---
description: "DevOps Engineer. Gerencia Docker, CI/CD e infraestrutura. Use when: criar Dockerfile, configurar pipeline, deploy."
tools: [read, search, edit, execute]
---
```

### 4. Escreva o corpo

Estrutura recomendada:

```markdown
# Nome do Agente

Frase definindo o papel e restrição principal.

## Workflow
1. Passo 1
2. Passo 2
3. Passo 3

## Proibições
- Não faça X
- Não faça Y

## Formato de saída
O que retornar e como estruturar.
```

### 5. Recarregue o VS Code

`Ctrl+Shift+P` → *Developer: Reload Window*

O agente aparece no seletor de agentes do Copilot Chat (se `user-invocable: true`).

## Exemplo completo: Orchestrator deste projeto

```yaml
---
description: "Orquestrador. Decompõe a tarefa e delega a subagentes. Use when: tarefa complexa, multi-step, coordenar subagentes."
tools: [agent, read, search, todo, web]
---
```

**Por que essas tools?**
- `agent` — precisa chamar subagentes
- `read`, `search` — precisa ler contexto para decidir delegação
- `todo` — torna o plano visível ao usuário
- `web` — buscar informações externas quando necessário
- **Sem** `edit` e `execute` — Orchestrator nunca edita código diretamente

## Padrão: Orchestrator + Subagentes

```
Orchestrator (user-invocable: true, tools: [agent, read, search, todo])
   ├── Planner     (user-invocable: false, tools: [read, search, todo])
   ├── Explorer    (user-invocable: false, tools: [read, search])
   ├── Implementer (user-invocable: false, tools: [read, search, edit, execute])
   ├── Tester      (user-invocable: false, tools: [read, search, edit, execute])
   ├── Reviewer    (user-invocable: false, tools: [read, search, execute])
   └── Docs Writer (user-invocable: false, tools: [read, search, edit, execute])
```

**Princípios:**
- Cada agente tem **um papel único** e **ferramentas mínimas**
- Proibições explícitas no corpo (Implementer não toca em tests, Tester não toca em produção)
- Orchestrator coordena e nunca edita
- Reviewer é sempre o último e nunca corrige

## Anti-patterns a evitar

| Anti-pattern | Problema | Solução |
|---|---|---|
| Description vaga ("Um agente útil") | Copilot não sabe quando usar | Inclua keywords específicas e "Use when: ..." |
| Tools demais | Agente perde foco | Só as ferramentas que o papel precisa |
| Sem proibições | Agente faz coisas fora do escopo | Liste explicitamente o que NÃO fazer |
| Corpo muito longo | Dilui as instruções | Foque no workflow e limites, não em contexto geral |
| Subagentes circulares (A→B→A) | Loop infinito | Defina critérios de saída claros |

## Outros tipos de customização

### `.instructions.md` — regras automáticas

Aplicadas automaticamente quando o glob `applyTo` corresponde ao arquivo sendo editado.

```yaml
---
applyTo: "**/*.py"
---
# Regras para Python
- PEP 8, linhas até 100 chars
- f-strings ao invés de .format()
```

### `.prompt.md` — slash commands

Ativados manualmente pelo usuário digitando `/nome` no chat.

```yaml
---
description: "Revisa o git diff atual"
mode: agent
---
# /review-diff
Rode `git --no-pager diff` e analise...
```

### `copilot-instructions.md` — regras globais

Sempre carregado em toda interação. Fica em `.github/copilot-instructions.md`.
