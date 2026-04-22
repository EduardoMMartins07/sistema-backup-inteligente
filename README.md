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
- [x] Backup manual e backup agendado com compactacao em `.zip`
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
- [ ] Restauracao de backup `.zip` pela interface
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
    "trigger": "manual"
  }
]
```

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

## Estrutura do Projeto
- `main.py`: ponto de entrada da aplicacao.
- `interface/gui.py`: interface principal e janelas auxiliares.
- `scanner/scanner.py`: varredura dos diretorios, calculo de hash e geracao do dataset CSV.
- `monitor/monitor.py`: monitoramento de alteracoes com watchdog.
- `backup/backup_manager.py`: criacao, versionamento, deduplicacao opcional e historico dos backups.
- `utils/file_hash.py`: calculo de hash SHA-256 para identificacao de duplicados.
- `scheduler/scheduler.py`: execucao automatica de backups agendados.
- `tray/tray_icon.py`: integracao com bandeja do sistema.
- `config/`: arquivos de configuracao, historico e agendamento.
- `dataset/`: CSV gerado pelo scanner.
- `backups/`: destino padrao local dos backups.
- `ml/`: estrutura preparada para inteligencia/classificacao futura.

## Proximos Passos Sugeridos
- [ ] Adicionar restauracao de backup pela interface
- [ ] Mostrar tamanho, data e origem do ultimo backup na tela principal
- [ ] Permitir exclusao ou limpeza de backups antigos
- [ ] Melhorar o menu da bandeja para disparar backup completo e nao apenas scan
- [ ] Exibir logs mais detalhados na interface
- [ ] Integrar classificacao de relevancia usando o modulo `ml/`
- [ ] Adicionar um controle visual na interface para ativar ou desativar `deduplicate_backup`

## Comandos Uteis
- `python main.py`: inicia a aplicacao.
- `python -m py_compile main.py monitor/monitor.py interface/gui.py backup/backup_manager.py scheduler/scheduler.py scanner/scanner.py utils/file_hash.py`: valida a sintaxe dos modulos principais.
- `python scanner/scanner.py`: executa o scanner manualmente.
- `pip install -r requirements.txt`: instala as dependencias do projeto.
