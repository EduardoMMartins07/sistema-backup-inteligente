# Resumo da Avaliacao Experimental

Resultados gerados por `python -m experiments.benchmark_backup` com dataset sintetico deterministico.

| Cenario | Estrategia | Fase | Runs | Tempo medio (s) | Desvio (s) | Tamanho medio (bytes) | Reducao media (%) |
|---|---|---|---:|---:|---:|---:|---:|
| small | cloud_s3 | upload_failure | 1 | 0.547110 | 0.000000 | 1708168 | -4.26 |
| small | incremental | changed_backup | 1 | 0.127334 | 0.000000 | 1708168 | -4.26 |
| small | incremental | export_zip | 1 | 1.427627 | 0.000000 | 1674925 | -2.23 |
| small | incremental | initial_backup | 1 | 0.193627 | 0.000000 | 1348977 | 17.66 |
| small | incremental | no_changes_backup | 1 | 0.091404 | 0.000000 | 1444512 | 11.83 |
| small | incremental | restore | 1 | 1.442226 | 0.000000 | 1638400 | 0.00 |
| small | incremental_encrypted | initial_backup | 1 | 0.173721 | 0.000000 | 1582378 | 3.42 |
| small | zip_traditional | full_backup | 1 | 2.894523 | 0.000000 | 1674916 | -2.23 |

## Falha de Rede Simulada

As execucoes de upload para S3 falso retornaram status: `falhou`.
Esse cenario valida que o backup local permanece mensuravel mesmo quando a sincronizacao em nuvem falha.
