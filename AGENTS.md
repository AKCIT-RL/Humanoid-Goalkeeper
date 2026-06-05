# AGENTS.md

Guia de orquestração de subagentes do GitHub Copilot para este projeto.

## Fluxo padrão

```
Orchestrator
   ├─▶ Planner       (decide passos, escreve em /memories/session/plan.md)
   ├─▶ Explorer      (busca/lê código — read-only)
   ├─▶ Implementer   (edita código de produção, diff mínimo)
   ├─▶ Tester        (edita só tests/, roda pytest)
   ├─▶ Docs Writer   (edita só *.md e docstrings quando pedido)
   └─▶ Reviewer      (SEMPRE último; lê git diff e aprova/aponta)
```

O **Orchestrator** não escreve código. Ele decide a sequência, chama subagentes via `runSubagent`, consolida resultados e encerra com o Reviewer.

## Tabela: tarefa → subagente

| Tipo de pedido                          | Cadeia recomendada                                  |
|-----------------------------------------|-----------------------------------------------------|
| Adicionar função/feature pequena        | Planner → Implementer → Tester → Reviewer           |
| Adicionar feature complexa              | Planner → Explorer → Implementer → Tester → Reviewer|
| Corrigir bug                            | Explorer → Implementer → Tester → Reviewer          |
| Entender código existente               | Explorer (sozinho)                                  |
| Escrever só testes                      | Tester → Reviewer                                   |
| Atualizar README / docs                 | Docs Writer → Reviewer                              |
| "O que mudou?" / revisar PR             | Reviewer (sozinho)                                  |
| Refactor explicitamente pedido          | Planner → Explorer → Implementer → Tester → Reviewer|

## Paralelização

Quando subagentes são **independentes** (ex: Explorer lendo módulo A enquanto outro Explorer lê módulo B), o Orchestrator deve chamá-los em paralelo na mesma rodada de tool calls.

Implementer e Tester podem rodar em paralelo **se** mexem em arquivos distintos (código de produção vs. `tests/`).

## Política de modelos

Padrão: **Claude Sonnet** (custo/benefício). Suba para Opus apenas nos casos abaixo:

| Subagente    | Padrão | Opus quando                                    |
|--------------|--------|------------------------------------------------|
| Orchestrator | Sonnet | Tarefa com >5 subagentes encadeados            |
| Planner      | Sonnet | Problema mal definido / arquitetura nova       |
| Explorer     | Sonnet | Nunca                                          |
| Implementer  | Sonnet | Refactor de arquitetura, mudança transversal   |
| Reviewer     | Sonnet | Diffs grandes (>200 linhas) ou áreas críticas  |
| Tester       | Sonnet | Nunca                                          |
| Docs Writer  | Sonnet | Nunca                                          |

Para forçar um modelo específico ao chamar `runSubagent`, use o parâmetro `model` no formato `"Claude Sonnet 4 (copilot)"`.

## Memória

Arquitetura completa em [.github/instructions/memory.instructions.md](.github/instructions/memory.instructions.md). Resumo:

```
/memories/
├── session/      → quadro da conversa atual (plan.md, findings.md, review.md)
├── repo/         → fatos deste projeto (INDEX.md + topic files; consultado sob demanda)
└── (user/)       → preferências globais, cross-projeto
```

**Regra de ouro**: o **INDEX.md** de `repo/` é a porta de entrada — curto (<50 linhas), sempre lido primeiro. Arquivos de tópico (`architecture.md`, `commands.md`, `gotchas.md`, etc.) são carregados sob demanda.

**Quem escreve onde** (resumo):
- Planner → `session/plan.md`
- Explorer → `session/findings.md`
- Reviewer → `session/review.md`
- Implementer/Tester/Docs/Orchestrator → só leem
- Promoção `session/` → `repo/` apenas com critério (ver instrução).

## Regras invioláveis

1. **Implementer nunca toca em `tests/`** — isso é do Tester.
2. **Tester nunca toca em código de produção** — se um teste falha por bug, ele reporta ao Orchestrator.
3. **Reviewer é read-only** — nunca corrige, apenas aponta.
4. **Orchestrator nunca edita** — sempre delega.
5. **Todo subagente que edita** roda `git diff` ao final e inclui o resumo no retorno.
6. **Nenhum passo está completo sem testes passando** — Orchestrator não avança até confirmar.
7. **Subagentes têm acesso total a ferramentas** quando chamados via `runSubagent` — o prompt deve declarar permissões explícitas (o que PODE e NÃO PODE fazer).

## Ciclo de teste obrigatório

Após qualquer edição de código, o fluxo é:

```
Implementer edita → Implementer roda testes existentes
   ├─ passaram → Tester escreve novos testes → Tester roda tudo
   │                ├─ passaram → Reviewer
   │                └─ falharam por bug → volta ao Implementer
   └─ falharam → Implementer corrige e roda novamente
```

O Orchestrator **nunca** chama o Reviewer se testes estão falhando.

## Permissões de subagentes

Quando o Orchestrator chama `runSubagent`, o subagente tem acesso a **todas as ferramentas** (terminal, edição, etc.). O comportamento é controlado pelo **prompt**.

O Orchestrator deve incluir no prompt:

```
# Permissões
- Você TEM permissão para: editar arquivos, rodar comandos no terminal, criar arquivos.
- Você NÃO pode: [restrições do papel — ex: editar tests/]
```

Sem isso, o subagente pode ficar passivo e apenas sugerir ao invés de agir.
