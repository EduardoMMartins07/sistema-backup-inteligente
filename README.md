# Sistema de Backup Inteligente

Aplicacao desktop para acompanhar diretorios importantes, identificar alteracoes nos arquivos e centralizar a rotina de backup em uma interface simples. O sistema combina monitoramento continuo, geracao de dataset com metadados dos arquivos e criacao de backups incrementais com deduplicacao por hash SHA-256, snapshots JSON e restauracao por manifesto.

## Objetivo
Oferecer uma base para backup automatizado e inteligente de arquivos relevantes, permitindo que o usuario configure os diretorios de interesse, acompanhe mudancas no sistema, mantenha um historico das execucoes e tenha copias de seguranca organizadas para consulta e recuperacao futura.

## Regra de Documentacao
Toda alteracao relevante no projeto deve ser refletida neste `README.md`, mantendo a documentacao sempre atualizada com funcionalidades, fluxos, requisitos e mudancas importantes do sistema.

## Stack Tecnologica
- **Runtime:** Python 3.13+
- **Interface Desktop:** Tkinter
- **Monitoramento de arquivos:** watchdog
- **Manipulacao de dados:** pandas
- **Bandeja do sistema:** pystray
- **Imagens/icones:** pillow
- **Classificacao inteligente:** arvore de decisao local com integracao opcional via Gemini API
- **LLM externa opcional:** Gemini API via REST, usando apenas metadados dos arquivos

## Requisitos
- Python 3.13 ou superior
- pip
- Ambiente Windows recomendado
- Chave `GEMINI_API_KEY` opcional para ativar classificacao com Gemini API

## Instalacao e Execucao
1. Clone o repositorio
2. Crie e ative um ambiente virtual:
   ```bash
   python -m venv venv
   venv\Scripts\activate
   ```
3. Instale as dependencias:
   ```bash
   pip install -r requirements.txt
   ```
4. Execute a aplicacao:
   ```bash
   python main.py
   ```

## Funcionalidades
- [x] Configuracao inicial e gerenciamento dos diretorios que serao acompanhados pelo sistema
- [x] Monitoramento continuo de criacao, alteracao, remocao e movimentacao de arquivos
- [x] Scanner automatico para varredura dos diretorios monitorados sempre que ha mudancas relevantes
- [x] Geracao de dataset CSV com nome, extensao, tipo, tamanho, tempo desde a ultima modificacao, hash do arquivo e indicador de relevancia
- [x] Marcacao de arquivos duplicados no dataset por hash SHA-256
- [x] Classificacao inicial de arquivos importantes com base em metadados, palavras-chave e contexto do arquivo
- [x] Classificacao por prioridade usando arvore de decisao local e Gemini API com metadados dos arquivos
- [x] Cache local das respostas da LLM para evitar chamadas repetidas para o mesmo arquivo/hash
- [x] Registro observado de modificacoes e acessos entre varreduras para alimentar a arvore de decisao
- [x] Backup manual e backup agendado com armazenamento incremental em `backup_storage/`
- [x] Deduplicacao persistente por hash SHA-256, evitando salvar o mesmo conteudo mais de uma vez
- [x] Snapshots JSON restauraveis para representar o estado logico de cada execucao
- [x] Politica opcional de backup por prioridade: baixa semanal, media a cada 2 dias e alta no inicio do dia + a cada 4 horas quando alterada
- [x] Versionamento automatico dos backups por dia e horario, com organizacao em pastas por data
- [x] Definicao de diretorio padrao para armazenamento dos backups
- [x] Barra de loading / janela de progresso para acompanhamento da execucao do backup
- [x] Execucao do backup em segundo plano para manter a interface responsiva
- [x] Cancelamento seguro da operacao de backup pela interface
- [x] Historico das execucoes de backup e exportacao do artefato mais recente
- [x] Tratamento de falhas parciais durante a copia incremental, ignorando arquivos problematicos sem derrubar toda a execucao
- [x] Protecao contra recursao, ignorando pastas internas do sistema e a propria area de backup
- [x] Interface grafica principal com menu central e suporte por icone na bandeja do sistema
- [x] Icone personalizado aplicado na janela principal, barra de tarefas e bandeja do sistema
- [x] Rodape da interface principal com resumo do ultimo backup e pasta destino
- [x] Bandeja do sistema com informacoes resumidas do ultimo backup e destino atual
- [x] Tooltip da bandeja ajustado para respeitar o limite de caracteres do Windows
- [x] Layout da tela principal ajustado para evitar sobreposicao entre botoes auxiliares e menu
- [x] Login local com criacao automatica do primeiro administrador
- [x] Controle de usuarios por perfil: administrador, operador e visualizador
- [x] Permissoes aplicadas na interface para backup, agendamento, historico, arquivos, configuracoes e usuarios
- [x] Registro do usuario responsavel em cada backup manual
- [x] Logout com retorno para a tela de login
- [x] Historico filtravel por backup com arquivos adicionados, alterados e excluidos
- [x] Visibilidade do historico por perfil: visualizador ve apenas os proprios backups, operador ve os proprios e os de visualizadores, administrador ve todos
- [x] Tela de arquivos analisados com data de inclusao no backup, filtros por coluna e barras de rolagem
- [x] Administrador pode nomear o backup e adicionar descricao antes da execucao manual
- [x] Filtros avancados por janela nas telas de arquivos analisados e historico de backups
- [x] Clique esquerdo no icone da bandeja abre o painel; clique direito mantem o menu de opcoes
- [x] Restauracao de arquivos excluidos, versoes anteriores e snapshots incrementais pela interface
- [x] Busca por nome de arquivo na tela de recuperacao para localizar rapidamente backups relacionados
- [x] Busca com sugestoes de arquivos nas telas de recuperacao e historico de backups
- [x] Tela de arquivos mostra o status de cobertura do backup: em backup, fara backup ou sera excluido no proximo backup
- [x] Refinamento de UI/UX com fontes padronizadas, botoes com profundidade, scrollbars estilizados, campos mais destacados e abertura suave de janelas
- [x] Melhor legibilidade nas tabelas e caixa de pre-pesquisa com destaque visual para sugestoes de arquivos e pastas
- [ ] Visualizacao do tamanho dos backups e status da ultima execucao
- [ ] Configuracao mais avancada de agendamento
- [x] Integracao completa da classificacao do modulo `ml/` ao scanner e ao fluxo opcional de backup por prioridade

## Exemplos de Uso

### Estrutura dos Backups Gerados
```text
backups/
  backup_storage/
    objects/
      <hash_sha256_1>
      <hash_sha256_2>
    snapshots/
      snapshot_2026-05-08_08-00-00.json
      snapshot_2026-05-08_12-00-00.json
    index.json
```

Os ZIPs gerados por versoes anteriores continuam legiveis para restauracao de historico, mas novas execucoes usam snapshots incrementais como artefato principal.

### Exemplo de Configuracao
```json
{
  "directories": [
    "C:/Users/super/Documents/Projetos",
    "C:/Users/super/Documents/Contratos"
  ],
  "backup_destination": "C:/Users/super/Backups/SmartBackup",
  "deduplicate_backup": true,
  "llm_classification_enabled": true,
  "llm_cache_enabled": true,
  "gemini_model": "gemini-2.5-flash",
  "priority_backup_policy_enabled": false
}
```

`deduplicate_backup` e mantido por compatibilidade com configuracoes antigas; no fluxo incremental novo a deduplicacao por hash e sempre aplicada.

### Classificacao LLM com Gemini API
O sistema usa a LLM somente com metadados, sem enviar o conteudo completo dos arquivos. A chamada inclui dados como nome, extensao, tamanho, caminho/contexto, hash, dias desde a ultima modificacao e contadores observados de modificacao/acesso.

Para pegar a chave:
1. Acesse a pagina oficial de chaves do Google AI Studio: https://aistudio.google.com/app/apikey
2. Entre com sua conta Google.
3. Clique em `Create API key` ou `Criar chave de API`.
4. Copie a chave gerada e guarde em local seguro.

Referencia oficial do Google: https://ai.google.dev/gemini-api/docs/api-key

Para colocar a chave no projeto, nao salve a chave dentro do codigo. Use uma das duas opcoes abaixo.

Opcao 1: variavel de ambiente do Windows.

No PowerShell, apenas para a sessao atual:
```powershell
$env:GEMINI_API_KEY="SUA_CHAVE_AQUI"
```

No Windows, de forma persistente para o usuario:
```powershell
[Environment]::SetEnvironmentVariable("GEMINI_API_KEY", "SUA_CHAVE_AQUI", "User")
```

Depois de configurar de forma persistente, feche e abra novamente o terminal ou reinicie a aplicacao.

Opcao 2: arquivo `.env` local na raiz do projeto.

1. Copie `.env.example` para `.env`.
2. Abra o `.env`.
3. Troque `SUA_CHAVE_AQUI` pela sua chave real:
   ```text
   GEMINI_API_KEY=SUA_CHAVE_AQUI
   GEMINI_MODEL=gemini-2.5-flash
   SMARTBACKUP_LLM_ENABLED=true
   BACKUP_DEV_MODE=false
   ```

O arquivo `.env` fica no `.gitignore` e nao deve ser enviado ao Git. O projeto carrega esse arquivo automaticamente em `ml/llm_classifier.py` sem dependencia extra.

Onde a chave e lida na implementacao:
- `ml/llm_classifier.py`: carrega `.env` e depois le `GEMINI_API_KEY` ou `GOOGLE_API_KEY` pelas variaveis de ambiente.
- `config/config.json`: controla se a classificacao LLM fica ativa com `llm_classification_enabled`.
- `gemini_model`: define o modelo usado. O padrao documentado no projeto e `gemini-2.5-flash`.

Se a chave nao existir, se `llm_classification_enabled` estiver `false` ou se a API falhar, o sistema usa automaticamente a arvore de decisao local como fallback.

### Arvore de Decisao Implementada
A classificacao combina regras locais e, quando disponivel, Gemini API. A arvore considera:
- quantidade observada de modificacoes;
- tipo/extensao do arquivo;
- quantidade observada de acessos;
- nome do arquivo;
- diretorio/contexto onde o arquivo esta inserido.

O resultado gravado em `dataset/files_dataset.csv` inclui:
- `priority`: `baixa`, `media` ou `alta`;
- `priority_score`: pontuacao de 0 a 100;
- `priority_reason`: motivos resumidos da decisao;
- `classification_source`: `rules`, `rules_fallback`, `gemini_api` ou `gemini_cache`;
- `llm_confidence`: confianca retornada/normalizada;
- `backup_policy`: politica derivada da prioridade;
- `decision_tree`: decisoes estruturadas da arvore.

### Politica de Backup por Prioridade
A politica por prioridade fica desativada por padrao para evitar backups automaticos inesperados. Para ativar:
```json
{
  "priority_backup_policy_enabled": true
}
```

Quando ativada, o agendador em segundo plano verifica a politica periodicamente:
- **baixa prioridade:** backup a cada 7 dias;
- **media prioridade:** backup a cada 2 dias;
- **alta prioridade:** backup no primeiro inicio do programa no dia e novamente a cada 4 horas se o arquivo tiver mudado.

Em producao, o agendador checa a politica de prioridade a cada 10 minutos. Com `BACKUP_DEV_MODE=true`, essa checagem passa para 1 minuto para respeitar janelas curtas como `alta = 5 minutos`.

O estado persistente dessa politica fica em `<backup_destination>/backup_storage/index.json`. Backups manuais e agendados avaliam todos os arquivos; backups automaticos por prioridade respeitam as janelas de tempo e registram `skipped_not_eligible` no snapshot quando um arquivo ainda nao deve ser reavaliado.

### DEV MODE para Testes Locais
O projeto aceita um modo de desenvolvimento controlado exclusivamente pela variavel de ambiente `BACKUP_DEV_MODE`. Quando desativado, a politica usa os intervalos reais de producao. Quando ativado, apenas os intervalos de tempo sao reduzidos para facilitar testes locais.

Intervalos usados:
- **producao:** baixa = 7 dias, media = 2 dias, alta = primeiro inicio do dia + a cada 4 horas
- **DEV MODE:** baixa = 30 minutos, media = 15 minutos, alta = 5 minutos

Como ativar no PowerShell:
```powershell
$env:BACKUP_DEV_MODE="true"
python main.py
```

Como desativar no PowerShell:
```powershell
$env:BACKUP_DEV_MODE="false"
python main.py
```

Como ativar no Linux/macOS:
```bash
export BACKUP_DEV_MODE=true
python main.py
```

Como usar no `.env`:
```text
BACKUP_DEV_MODE=true
```

Exemplos de logs:
```text
[DEV MODE] Intervalos reduzidos ativos
[DEV MODE] baixa=30min media=15min alta=5min
[DEV MODE] Arquivo elegivel em intervalo reduzido: contrato.pdf
```

O DEV MODE nao altera prioridade, score, LLM, hash, snapshots, armazenamento incremental, deduplicacao ou restauracao. Ele afeta somente a janela temporal da politica por prioridade.

### Backup Incremental e Restauracao por Snapshot
Cada execucao cria um snapshot JSON em `backup_storage/snapshots/` e salva conteudo fisico apenas quando o hash SHA-256 ainda nao existe em `backup_storage/objects/`. Arquivos inalterados ou duplicados ficam apenas referenciados no snapshot, sem novo objeto fisico.

Para validar a deduplicacao, execute dois backups sem alterar os arquivos e compare a quantidade de arquivos em `backup_storage/objects/`: ela deve permanecer igual enquanto novos snapshots aparecem em `backup_storage/snapshots/`.

Para restaurar um snapshot pela interface, acesse **Recuperar arquivos** e use **Restaurar snapshot**. Pelo codigo, use:
```python
from backup.backup_manager import restore_snapshot

restore_snapshot(
    "C:/Backups/SmartBackup/backup_storage/snapshots/snapshot_2026-05-08_12-00-00.json",
    "C:/Restauracao"
)
```

### Exemplo de Historico de Backup
```json
[
  {
    "timestamp": "08/04/2026 19:50:00",
    "backup_file": "snapshot_2026-04-08_19-50-00.json",
    "backup_path": "C:/Users/super/Backups/SmartBackup/backup_storage/snapshots/snapshot_2026-04-08_19-50-00.json",
    "snapshot_path": "C:/Users/super/Backups/SmartBackup/backup_storage/snapshots/snapshot_2026-04-08_19-50-00.json",
    "backup_storage": "C:/Users/super/Backups/SmartBackup/backup_storage",
    "storage_mode": "incremental",
    "total_files": 128,
    "objects_stored": 8,
    "objects_referenced": 12,
    "files_unchanged": 108,
    "trigger": "manual",
    "user": "admin",
    "user_role": "admin",
    "file_changes": [
      {
        "action": "adicionado",
        "name": "contrato.pdf",
        "archive_name": "Documentos/contrato.pdf",
        "source_path": "C:/Users/super/Documents/contrato.pdf",
        "size_bytes": 34520,
        "modified_at": "2026-04-08T19:48:12"
      }
    ]
  }
]
```

### Perfis de Usuario
- **Administrador:** acessa todas as funcionalidades, incluindo gerenciamento de usuarios, diretorios e destino de backup.
- **Operador:** pode realizar backup, agendar backup, visualizar arquivos, consultar historico e baixar o ultimo backup.
- **Visualizador:** possui acesso somente leitura aos arquivos analisados e ao historico de backups.
- **Sem login:** nao acessa o painel nem executa acoes protegidas.

Os usuarios ficam em `config/users.json`. As senhas nao sao salvas em texto puro; o sistema armazena hash PBKDF2 com salt individual.

### Filtro de Historico por Perfil
- **Visualizador:** visualiza somente backups executados pelo proprio usuario e seus arquivos adicionados, alterados ou excluidos.
- **Operador:** visualiza os proprios backups e backups executados por visualizadores.
- **Administrador:** visualiza backups de administradores, operadores, visualizadores e execucoes do sistema.

Cada backup novo registra um snapshot dos arquivos e compara com o snapshot anterior para montar a lista de mudancas. Backups antigos, criados antes dessa funcionalidade, podem aparecer sem detalhes de mudancas.

### Execucao do Backup na Interface
- Ao iniciar um backup manual, a aplicacao abre uma barra de loading para acompanhar o progresso da operacao.
- O processamento acontece em segundo plano para evitar que a interface principal fique travada.
- O usuario pode cancelar a operacao durante o scanner ou durante a copia dos objetos incrementais.
- Se o cancelamento ocorrer no meio da execucao, o sistema encerra o processo com seguranca e remove arquivos parciais de backup.

### Fluxo Atual da Aplicacao
1. O usuario seleciona os diretorios na interface.
2. O sistema monitora alteracoes nesses diretorios.
3. Quando um arquivo e criado, alterado, removido ou movido, o scanner atualiza o dataset, registra hash, duplicidade, contadores observados e classificacao por prioridade.
4. Quando o backup e iniciado manualmente ou por agendamento, a aplicacao abre uma janela de progresso sem travar a interface principal.
5. O usuario pode acompanhar o andamento e cancelar a operacao de forma segura durante o scanner ou a copia de objetos.
6. O sistema calcula o SHA-256 de cada arquivo avaliado e copia para `objects/` somente hashes ainda inexistentes.
7. Cada execucao cria um snapshot em `snapshots/` e atualiza `index.json` com o ultimo hash, prioridade e data de backup de cada arquivo.
8. Se `priority_backup_policy_enabled` estiver ativado, o agendador cria snapshots respeitando as janelas de prioridade.
9. O sistema registra o historico da execucao e permite exportar o ultimo artefato de backup.
10. A interface permite consultar arquivos excluidos ou alterados por backup, recuperar itens a partir de backups anteriores e restaurar snapshots completos.
11. Ao recuperar, arquivos existentes no destino sao comparados por hash; conflitos podem ser renomeados, usando `_recuperado` como nome padrao.

## Estrutura do Projeto
- `main.py`: ponto de entrada da aplicacao.
- `auth/`: autenticacao local, hash de senhas e regras de permissao por perfil.
- `interface/gui.py`: interface principal e janelas auxiliares.
- `interface/login.py`: login e criacao do primeiro administrador.
- `scanner/scanner.py`: varredura dos diretorios, calculo de hash e geracao do dataset CSV.
- `ml/llm_classifier.py`: classificacao por arvore local e Gemini API usando metadados dos arquivos.
- `monitor/monitor.py`: monitoramento de alteracoes com watchdog.
- `backup/backup_manager.py`: criacao incremental, deduplicacao persistente, snapshots, historico e restauracao dos backups.
- `utils/file_hash.py`: calculo de hash SHA-256 para identificacao de duplicados.
- `scheduler/scheduler.py`: execucao automatica de backups agendados.
- `tray/tray_icon.py`: integracao com bandeja do sistema.
- `assets/`: arquivos visuais usados pela interface, como o icone da aplicacao.
- `config/`: arquivos de configuracao, historico, agendamento, cache da LLM e estado da politica por prioridade.
- `dataset/`: CSV gerado pelo scanner.
- `backups/`: destino padrao local dos backups; novas execucoes criam `backup_storage/` dentro dele.
- `ml/`: modulos de classificacao local e integracao opcional com Gemini API.

## Proximos Passos Sugeridos
- [x] Adicionar restauracao de backup e versoes anteriores pela interface
- [ ] Mostrar tamanho, data e origem do ultimo backup na tela principal
- [ ] Permitir exclusao ou limpeza de backups antigos
- [ ] Melhorar o menu da bandeja para disparar backup completo e nao apenas scan
- [ ] Exibir logs mais detalhados na interface
- [x] Integrar classificacao de relevancia usando o modulo `ml/`
- [x] Deduplicacao persistente no fluxo incremental
- [x] Adicionar um controle visual na interface para ativar ou desativar `priority_backup_policy_enabled`
- [ ] Adicionar troca de senha pelo proprio usuario

## Comandos Uteis
- `python main.py`: inicia a aplicacao.
- `python -m py_compile main.py auth/users.py auth/permissions.py monitor/monitor.py interface/login.py interface/gui.py backup/backup_manager.py scheduler/scheduler.py scanner/scanner.py utils/file_hash.py ml/llm_classifier.py`: valida a sintaxe dos modulos principais.
- `python -m unittest discover -s tests`: executa os testes automatizados do backup incremental.
- `python scanner/scanner.py`: executa o scanner manualmente.
- `pip install -r requirements.txt`: instala as dependencias do projeto.

