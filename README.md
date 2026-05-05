# Sistema de Backup Inteligente

Aplicacao desktop para acompanhar diretorios importantes, identificar alteracoes nos arquivos e centralizar a rotina de backup em uma interface simples. O sistema combina monitoramento continuo, geracao de dataset com metadados dos arquivos e criacao de backups versionados em `.zip`, organizados por data e horario.

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
- **Machine Learning preparado no projeto:** scikit-learn / joblib

## Requisitos
- Python 3.13 ou superior
- pip
- Ambiente Windows recomendado

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
- [x] Classificacao inicial de arquivos importantes com base em palavras-chave e estrutura preparada para modelo de machine learning
- [x] Treinamento de modelo em `ml/` a partir do dataset gerado pelo scanner
- [x] Backup manual e backup agendado com compactacao em `.zip` usando `ZIP_LZMA`
- [x] Deduplicacao opcional no backup por hash do conteudo via `deduplicate_backup`
- [x] Versionamento automatico dos backups por dia e horario, com organizacao em pastas por data
- [x] Definicao de diretorio padrao para armazenamento dos backups
- [x] Barra de loading / janela de progresso para acompanhamento da execucao do backup
- [x] Execucao do backup em segundo plano para manter a interface responsiva
- [x] Cancelamento seguro da operacao de backup pela interface
- [x] Historico das execucoes de backup e exportacao do backup mais recente
- [x] Tratamento de falhas parciais durante a compactacao, ignorando arquivos problematicos sem derrubar toda a execucao
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
- [x] Restauracao de arquivos excluidos e versoes anteriores pela interface
- [x] Busca por nome de arquivo na tela de recuperacao para localizar rapidamente backups relacionados
- [x] Busca com sugestoes de arquivos nas telas de recuperacao e historico de backups
- [x] Refinamento de UI/UX com fontes padronizadas, botoes com profundidade, scrollbars estilizados, campos mais destacados e abertura suave de janelas
- [x] Melhor legibilidade nas tabelas e caixa de pre-pesquisa com destaque visual para sugestoes de arquivos e pastas
- [ ] Visualizacao do tamanho dos backups e status da ultima execucao
- [ ] Configuracao mais avancada de agendamento
- [ ] Integracao completa da predicao do modulo `ml/` ao fluxo principal do backup

## Exemplos de Uso

### Estrutura dos Backups Gerados
```text
backups/
  2026-04-08/
    backup_2026-04-08_19-30-39.zip
    backup_2026-04-08_21-10-15.zip
  2026-04-09/
    backup_2026-04-09_09-00-00.zip
```

### Exemplo de Configuracao
```json
{
  "directories": [
    "C:/Users/super/Documents/Projetos",
    "C:/Users/super/Documents/Contratos"
  ],
  "backup_destination": "C:/Users/super/Backups/SmartBackup",
  "deduplicate_backup": true
}
```

### Exemplo de Historico de Backup
```json
[
  {
    "timestamp": "08/04/2026 19:50:00",
    "backup_file": "backup_2026-04-08_19-50-00.zip",
    "backup_path": "C:/Users/super/Backups/SmartBackup/2026-04-08/backup_2026-04-08_19-50-00.zip",
    "backup_folder": "C:/Users/super/Backups/SmartBackup/2026-04-08",
    "total_files": 128,
    "duplicate_files_skipped": 12,
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
- O usuario pode cancelar a operacao durante o scanner ou durante a compactacao do `.zip`.
- Se o cancelamento ocorrer no meio da execucao, o sistema encerra o processo com seguranca e remove arquivos parciais de backup.

### Fluxo Atual da Aplicacao
1. O usuario seleciona os diretorios na interface.
2. O sistema monitora alteracoes nesses diretorios.
3. Quando um arquivo e criado, alterado, removido ou movido, o scanner atualiza o dataset e registra hash e duplicidade.
4. Quando o backup e iniciado manualmente ou por agendamento, a aplicacao abre uma janela de progresso sem travar a interface principal.
5. O usuario pode acompanhar o andamento e cancelar a operacao de forma segura durante o scanner ou a compactacao.
6. Se `deduplicate_backup` estiver ativado no `config.json`, apenas a primeira ocorrencia de cada hash entra no `.zip`.
7. O sistema registra o historico da execucao e permite exportar o ultimo backup.
8. A interface permite consultar arquivos excluidos ou alterados por backup e recuperar itens a partir de backups anteriores.
9. Ao recuperar, arquivos existentes no destino sao comparados por hash; conflitos podem ser renomeados, usando `_recuperado` como nome padrao.

## Estrutura do Projeto
- `main.py`: ponto de entrada da aplicacao.
- `auth/`: autenticacao local, hash de senhas e regras de permissao por perfil.
- `interface/gui.py`: interface principal e janelas auxiliares.
- `interface/login.py`: login e criacao do primeiro administrador.
- `scanner/scanner.py`: varredura dos diretorios, calculo de hash e geracao do dataset CSV.
- `monitor/monitor.py`: monitoramento de alteracoes com watchdog.
- `backup/backup_manager.py`: criacao, versionamento, deduplicacao opcional, historico e restauracao dos backups.
- `utils/file_hash.py`: calculo de hash SHA-256 para identificacao de duplicados.
- `scheduler/scheduler.py`: execucao automatica de backups agendados.
- `tray/tray_icon.py`: integracao com bandeja do sistema.
- `assets/`: arquivos visuais usados pela interface, como o icone da aplicacao.
- `config/`: arquivos de configuracao, historico e agendamento.
- `dataset/`: CSV gerado pelo scanner.
- `backups/`: destino padrao local dos backups.
- `ml/`: estrutura preparada para inteligencia/classificacao futura.

## Proximos Passos Sugeridos
- [x] Adicionar restauracao de backup e versoes anteriores pela interface
- [ ] Mostrar tamanho, data e origem do ultimo backup na tela principal
- [ ] Permitir exclusao ou limpeza de backups antigos
- [ ] Melhorar o menu da bandeja para disparar backup completo e nao apenas scan
- [ ] Exibir logs mais detalhados na interface
- [ ] Integrar classificacao de relevancia usando o modulo `ml/`
- [ ] Adicionar um controle visual na interface para ativar ou desativar `deduplicate_backup`
- [ ] Adicionar troca de senha pelo proprio usuario

## Comandos Uteis
- `python main.py`: inicia a aplicacao.
- `python -m py_compile main.py auth/users.py auth/permissions.py monitor/monitor.py interface/login.py interface/gui.py backup/backup_manager.py scheduler/scheduler.py scanner/scanner.py utils/file_hash.py`: valida a sintaxe dos modulos principais.
- `python scanner/scanner.py`: executa o scanner manualmente.
- `pip install -r requirements.txt`: instala as dependencias do projeto.
