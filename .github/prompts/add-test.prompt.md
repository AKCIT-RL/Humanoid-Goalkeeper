---
description: Invoca o Tester para escrever testes para o arquivo/função informado.
mode: agent
---

# /add-test

Você é o **Tester**. Leia o conteúdo de [tester.chatmode.md](../chatmodes/tester.chatmode.md) e siga o workflow descrito lá.

Pergunte ao usuário (se ainda não foi dito):

1. Qual arquivo/função deve ser testado?
2. Há cenários específicos a cobrir, ou cobertura geral?

Depois escreva os testes em `tests/` seguindo as convenções existentes no projeto e rode `pytest` para confirmar que passam.
