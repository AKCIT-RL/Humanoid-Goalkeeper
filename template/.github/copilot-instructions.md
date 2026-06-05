# Instruções globais do projeto

Estas regras se aplicam a **todas** as interações do Copilot neste repositório.

## Idioma

- Responda sempre em **português brasileiro**.
- Código, nomes de variáveis e mensagens de commit em inglês (convenção).

## Princípio fundamental: diff mínimo

Faça **a menor mudança possível** para atender ao pedido. Concretamente:

- **Não refatore** código que não foi pedido para mudar.
- **Não adicione** docstrings, comentários ou type hints em código que você não está alterando.
- **Não reorganize** imports nem altere formatação de linhas que não tocou.
- **Não renomeie** variáveis, funções ou arquivos sem pedido explícito.
- **Não adicione** tratamento de erro para cenários que não podem acontecer. Valide apenas nas fronteiras do sistema.
- **Não crie** helpers, abstrações ou camadas para uso único.
- **Não adicione** features além do que foi pedido.

## Testes: validar antes de avançar

Nenhum passo está completo até os testes passarem. Concretamente:

- **Após qualquer edição de código**, rode os testes existentes relacionados antes de considerar o passo feito.
- **Após criar código novo**, escreva testes (ou peça ao Tester) e rode-os.
- **Testes falhando = pare e corrija** antes de avançar ao próximo passo.
- Rode testes com verbose (`pytest -v`, ou equivalente) para dar visibilidade ao resultado.
- Quando possível, rode **antes e depois** da mudança para confirmar que não quebrou nada.
- Prefira rodar os testes do módulo afetado antes do suite inteiro (mais rápido, feedback mais claro).

## Verificação obrigatória ao final

Antes de finalizar qualquer tarefa que envolva edição de arquivos:

1. Rode os **testes** afetados e confirme que passam.
2. Rode `git diff` (ou `git status` + `git diff --stat` para uma visão rápida).
3. Confirme que toda mudança no diff é justificada pelo pedido.
4. Se houver mudança fora de escopo, reverta antes de entregar.

## Segurança

- **Nunca** use `sudo` em nenhum comando. Se algo exigir sudo, pare e pergunte ao usuário.
- **Nunca** rode `rm -rf /`, `rm -rf ~`, ou comandos destrutivos em caminhos amplos.
- **Nunca** exponha credenciais, tokens ou senhas em saída de terminal.

## Comunicação

- Seja conciso. 1–3 frases para respostas simples.
- Não explique o que vai fazer antes de fazer — execute e depois resuma brevemente.
- Não use emojis salvo pedido explícito.

## Permissões para subagentes

Ao chamar `runSubagent`, o subagente roda com **todas as ferramentas disponíveis** — incluindo edição de arquivos e terminal. O prompt do subagente deve:

- **Declarar explicitamente** o que ele pode fazer: "Você tem permissão para editar arquivos, rodar comandos no terminal, criar arquivos."
- **Declarar explicitamente** o que ele NÃO pode: "Não edite arquivos em tests/."
- Incluir o conteúdo do chatmode correspondente no prompt (o subagente não herda chatmode — ele só vê o prompt).

Isso garante que o subagente não fique "tímido" pedindo confirmação ou evitando editar.

## Quando usar subagentes

Veja [AGENTS.md](../AGENTS.md) na raiz do projeto. Regra rápida: se você está no modo **Orchestrator**, **sempre** delegue via `runSubagent` — nunca edite código diretamente.
