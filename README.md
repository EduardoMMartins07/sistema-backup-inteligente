# Sistema de Backup Inteligente

Aplicação desktop desenvolvida para acompanhar diretórios importantes, identificar alterações nos arquivos e centralizar a rotina de backup em uma interface simples. O sistema combina monitoramento contínuo, geração de dataset com metadados dos arquivos e criação de backups versionados em `.zip`, organizados por data e horário.

## Objetivo
O objetivo deste projeto é oferecer uma base para backup automatizado e inteligente de arquivos relevantes, permitindo que o usuário configure os diretórios de interesse, acompanhe mudanças no sistema, mantenha um histórico das execuções e tenha cópias de segurança organizadas para consulta e recuperação futura.

## Regra de Documentação
Toda alteração relevante no projeto deve ser refletida neste `README.md`, mantendo a documentação sempre atualizada com funcionalidades, fluxos, requisitos e mudanças importantes do sistema.

## Stack Tecnológica
- **Runtime:** Python 3.13+
- **Interface Desktop:** Tkinter
- **Monitoramento de arquivos:** watchdog
- **Manipulação de dados:** pandas
- **Bandeja do sistema:** pystray
- **Imagens/ícones:** pillow
- **Machine Learning preparado no projeto:** scikit-learn / joblib

## Requisitos
- Python 3.13 ou superior
- pip
- Ambiente Windows recomendado

## Instalação e Execução

1. Clone o repositório
2. Crie e ative um ambiente virtual:
   ```bash
   python -m venv venv
   venv\Scripts\activate
   ```
3. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```
4. Execute a aplicação:
   ```bash
   python main.py
   ```

## Funcionalidades
- [x] Configuração inicial e gerenciamento dos diretórios que serão acompanhados pelo sistema
- [x] Monitoramento contínuo de criação, alteração, remoção e movimentação de arquivos
- [x] Scanner automático para varredura dos diretórios monitorados sempre que há mudanças relevantes
- [x] Geração de dataset CSV com nome, extensão, tipo, tamanho, tempo desde a última modificação e indicador de relevância
- [x] Classificação inicial de arquivos importantes com base em palavras-chave e estrutura preparada para modelo de machine learning
- [x] Treinamento de modelo em `ml/` a partir do dataset gerado pelo scanner
- [x] Backup manual e backup agendado com compactação em `.zip`
- [x] Versionamento automático dos backups por dia e horário, com organização em pastas por data
- [x] Definição de diretório padrão para armazenamento dos backups
- [x] Barra de loading / janela de progresso para acompanhamento da execução do backup
- [x] Execução do backup em segundo plano para manter a interface responsiva
- [x] Cancelamento seguro da operação de backup pela interface
- [x] Histórico das execuções de backup e exportação do backup mais recente
- [x] Tratamento de falhas parciais durante a compactação, ignorando arquivos problemáticos sem derrubar toda a execução
- [x] Proteção contra recursão, ignorando pastas internas do sistema e a própria área de backup
- [x] Interface gráfica principal com menu central e suporte por ícone na bandeja do sistema
- [ ] Restauração de backup `.zip` pela interface
- [ ] Visualização do tamanho dos backups e status da última execução
- [ ] Configuração mais avançada de agendamento
- [ ] Integração completa da predição do módulo `ml/` ao fluxo principal do backup

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

### Exemplo de Configuração
```json
{
  "directories": [
    "C:/Users/super/Documents/Projetos",
    "C:/Users/super/Documents/Contratos"
  ],
  "backup_destination": "C:/Users/super/Backups/SmartBackup"
}
```

### Exemplo de Histórico de Backup
```json
[
  {
    "timestamp": "08/04/2026 19:50:00",
    "backup_file": "backup_2026-04-08_19-50-00.zip",
    "backup_path": "C:/Users/super/Backups/SmartBackup/2026-04-08/backup_2026-04-08_19-50-00.zip",
    "backup_folder": "C:/Users/super/Backups/SmartBackup/2026-04-08",
    "total_files": 128,
    "trigger": "manual"
  }
]
```

### Execucao do Backup na Interface
- Ao iniciar um backup manual, a aplicacao abre uma barra de loading para acompanhar o progresso da operacao.
- O processamento acontece em segundo plano para evitar que a interface principal fique travada.
- O usuario pode cancelar a operacao durante o scanner ou durante a compactacao do `.zip`.
- Se o cancelamento ocorrer no meio da execucao, o sistema encerra o processo com seguranca e remove arquivos parciais de backup.

### Fluxo Atual da Aplicação
1. O usuário seleciona os diretórios na interface.
2. O sistema monitora alterações nesses diretórios.
3. Quando um arquivo é criado, alterado, removido ou movido, o scanner atualiza o dataset.
4. Quando o backup é iniciado manualmente ou por agendamento, a aplicação abre uma janela de progresso sem travar a interface principal.
5. O usuário pode acompanhar o andamento e cancelar a operação de forma segura durante o scanner ou a compactação.
6. O backup `.zip` é gerado somente quando solicitado manualmente ou quando o horário agendado é atingido.
7. O sistema registra o histórico da execução e permite exportar o último backup.

## Estrutura do Projeto
- `main.py`: ponto de entrada da aplicação.
- `interface/gui.py`: interface principal e janelas auxiliares.
- `scanner/scanner.py`: varredura dos diretórios e geração do dataset CSV.
- `monitor/monitor.py`: monitoramento de alterações com watchdog.
- `backup/backup_manager.py`: criação, versionamento e histórico dos backups.
- `scheduler/scheduler.py`: execução automática de backups agendados.
- `tray/tray_icon.py`: integração com bandeja do sistema.
- `config/`: arquivos de configuração, histórico e agendamento.
- `dataset/`: CSV gerado pelo scanner.
- `backups/`: destino padrão local dos backups.
- `ml/`: estrutura preparada para inteligência/classificação futura.

## Próximos Passos Sugeridos
- [ ] Adicionar restauração de backup pela interface
- [ ] Mostrar tamanho, data e origem do último backup na tela principal
- [ ] Permitir exclusão ou limpeza de backups antigos
- [ ] Melhorar o menu da bandeja para disparar backup completo e não apenas scan
- [ ] Exibir logs mais detalhados na interface
- [ ] Integrar classificação de relevância usando o módulo `ml/`

## Comandos Úteis
- `python main.py`: inicia a aplicação.
- `python -m py_compile main.py monitor/monitor.py interface/gui.py backup/backup_manager.py scheduler/scheduler.py scanner/scanner.py`: valida a sintaxe dos módulos principais.
- `python scanner/scanner.py`: executa o scanner manualmente.
- `pip install -r requirements.txt`: instala as dependências do projeto.
