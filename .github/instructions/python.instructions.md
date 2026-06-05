---
applyTo: "**/*.py"
---

# Regras Python

## Estilo

- PEP 8. Linhas até 100 caracteres (não 79).
- Aspas duplas como padrão; aspas simples apenas para evitar escape.
- f-strings em vez de `.format()` ou `%`.

## Type hints

- Se o arquivo **já usa** type hints, mantenha o padrão e adicione nas novas funções.
- Se o arquivo **não usa**, **não introduza** type hints só na sua mudança.

## Imports

- **Não reorganize** imports existentes ao editar um arquivo.
- Para novos imports, adicione no grupo apropriado (stdlib / terceiros / locais) sem mexer no resto.

## Docstrings

- **Não adicione** docstrings em funções/classes que você não está criando.
- Para funções novas, docstring curta no estilo já usado no repo (Google, NumPy, ou simples).

## Erros

- Não use `except:` ou `except Exception:` salvo necessidade real — capture o tipo específico.
- Não adicione `try/except` "defensivo" para cenários que não podem acontecer.

## Testes

- `pytest`. Use fixtures (`@pytest.fixture`) em vez de `setUp`.
- Arquivos em `tests/`, espelhando a estrutura de `src/`.
- Nomes: `test_<funcao>_<cenario>.py` ou agrupados por módulo.
