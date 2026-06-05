# padrao-claude

Template de organização de agentes do **GitHub Copilot** para uso em qualquer projeto novo. Define **1 Orquestrador** + **6 subagentes especializados** (Planner, Explorer, Implementer, Reviewer, Tester, Docs) com foco em **diffs mínimos** e **Python**.

## Filosofia

- Você ativa o chatmode **Orchestrator** e descreve a tarefa.
- O Orchestrator **não escreve código** — ele decompõe e delega a subagentes via `runSubagent`.
- Cada subagente tem ferramentas restritas ao seu papel (Explorer só lê; Tester só mexe em `tests/`; etc.).
- Reviewer **sempre roda ao final**, lendo `git diff` e apontando mudanças fora de escopo.

```
Você ──▶ Orchestrator ──▶ Planner ──▶ Explorer ∥ Implementer ──▶ Tester ──▶ Reviewer
```

## Setup inicial em um projeto novo

### Opção A — script (recomendado)

Do diretório deste template, rode apontando para o projeto destino:

```bash
./install.sh /caminho/para/o/projeto
```

Isso copia `template/.github/` e `template/AGENTS.md` para o projeto, sem sobrescrever arquivos existentes.

### Opção B — manual

```bash
cp -r template/.github /caminho/para/o/projeto/
cp    template/AGENTS.md /caminho/para/o/projeto/
```

### Passos depois de copiar

1. Abra o projeto no VS Code.
2. Recarregue a janela (`Ctrl+Shift+P` → *Developer: Reload Window*) para o Copilot detectar os chatmodes.
3. Abra o painel do Copilot Chat e troque o modo para **Orchestrator** no seletor de modos.
4. (Opcional) Edite [template/AGENTS.md](template/AGENTS.md) com particularidades do projeto antes de copiar.
5. Mande sua primeira tarefa. Exemplo:
   > Adicione a função `parse_invoice` em `src/billing.py` com testes.

   O Orchestrator vai chamar Planner → Implementer → Tester → Reviewer automaticamente.

## Estrutura do template

```
template/
├── AGENTS.md                          # tabela tarefa → subagente + política de modelos
└── .github/
    ├── copilot-instructions.md        # regras globais (PT-BR, diff mínimo)
    ├── chatmodes/
    │   ├── orchestrator.chatmode.md   # ATIVE ESTE
    │   ├── planner.chatmode.md
    │   ├── explorer.chatmode.md
    │   ├── implementer.chatmode.md
    │   ├── reviewer.chatmode.md
    │   ├── tester.chatmode.md
    │   └── docs-writer.chatmode.md
    ├── instructions/
    │   └── python.instructions.md     # aplicado em **/*.py
    └── prompts/
        ├── review-diff.prompt.md      # /review-diff
        └── add-test.prompt.md         # /add-test
```

## Política de modelos

Definida em [template/AGENTS.md](template/AGENTS.md). Resumo:

| Subagente    | Modelo padrão | Quando subir para Opus |
|--------------|---------------|------------------------|
| Orchestrator | Sonnet        | Tarefas com >5 subagentes encadeados |
| Planner      | Sonnet        | Quando o problema é mal definido |
| Explorer     | Sonnet        | Nunca (só lê) |
| Implementer  | Sonnet        | Refactor de arquitetura |
| Reviewer     | Sonnet        | Diffs grandes (>200 linhas) |
| Tester       | Sonnet        | Nunca |
| Docs         | Sonnet        | Nunca |

## Adicionando outras linguagens

Para suportar TypeScript, Go, etc., crie um novo arquivo em `template/.github/instructions/`:

```yaml
---
applyTo: "**/*.ts"
---
# Regras específicas de TypeScript
```

## Atualizando um projeto que já usa este template

Rode `./install.sh` novamente — ele só copia o que **não existe** no destino. Para forçar atualização:

```bash
./install.sh /caminho/para/o/projeto --force
```
