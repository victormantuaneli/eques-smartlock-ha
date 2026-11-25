# Eques Smart Lock & Video Doorbell - Home Assistant Integration

Integração oficial customizada (HACS / Custom Component) para fechaduras inteligentes e campainhas com vídeo **Eques** no **Home Assistant**.

Suporta comunicação direta e autenticada via **Cloud WebSocket (Push em tempo real)**, sem depender de scripts externos e sem derrubar a fechadura da nuvem.

---

## ✨ Recursos

- 🔐 **Entidade Fechadura (`lock`)**:
  - Destrava a fechadura física remotamente utilizando seu PIN seguro.
  - Suporte inteligente a wake-up de fechaduras a bateria (se a fechadura estiver dormindo, arma a espera automática para o momento em que a campainha for tocada).
- 🛎️ **Entidade Binária da Campainha (`binary_sensor`)**:
  - Ativa instantaneamente (`on`) quando alguém toca a campainha física ou inicia uma chamada de vídeo.
- 👤 **Sensores de Registro e Auditoria (`sensor`)**:
  - **Último Método de Abertura**: Identifica se foi aberta por *Biometria (Digital)*, *Senha no Teclado*, *Cartão RFID* ou *App Remoto*.
  - **Último Usuário a Abrir**: Nome e ID de quem destravou.
  - **Horário da Última Abertura**: Data e hora exatas da abertura.
  - **Horário da Última Campainha**: Data e hora do último toque.
  - **Status da Fechadura**: Indica se está em repouso (*standby*) ou ativa (*awake*).
- 🚪 **Interruptor de Abertura na Campainha (`switch`)**:
  - **"Abrir ao Tocar Campainha"**: Quando ativado, a fechadura destrava automaticamente na próxima vez que alguém tocar a campainha (com desarme automático após 5 minutos).

---

## 📦 Como Instalar no Home Assistant

### Método 1: Manualmente via Samba / SSH / File Editor

1. Copie a pasta inteira `custom_components/eques` para dentro da pasta `config/custom_components/` do seu Home Assistant:
   ```text
   homeassistant/
   └── config/
       └── custom_components/
           └── eques/
               ├── __init__.py
               ├── manifest.json
               ├── const.py
               ├── client.py
               ├── config_flow.py
               ├── lock.py
               ├── binary_sensor.py
               ├── sensor.py
               ├── switch.py
               ├── strings.json
               └── translations/
   ```
2. Reinicie o Home Assistant.

### Método 2: Via HACS (Repositório Customizado)
1. No HACS, clique nos 3 pontinhos -> **Repositórios personalizados**.
2. Adicione o repositório como categoria **Integração**.
3. Clique em **Download** e reinicie o Home Assistant.

---

## ⚙️ Como Configurar

1. No Home Assistant, acesse **Configurações** -> **Dispositivos e Serviços** -> **Adicionar Integração**.
2. Pesquise por **Eques Smart Lock & Doorbell**.
3. Preencha os campos:
   - **Usuário / E-mail / Telefone**: Seu login da conta Eques.
   - **Senha**: Sua senha da conta Eques.
   - **PIN de Destrave Remoto**: O PIN numérico de abertura configurado no aplicativo (ex: `812760`).
4. Clique em **Enviar**. A integração validará o acesso, descobrirá a fechadura e criará todas as entidades automaticamente!

---

## 👤 Cadastro de Nomes de Usuários (Modal de Opções)

Após adicionar a integração, você pode cadastrar nomes amigáveis para cada usuário:

1. Vá em **Configurações** -> **Dispositivos e Serviços**.
2. No card da integração **Eques**, clique no botão **CONFIGURAR** (Options Flow).
3. Um modal abrirá com os campos:
   - **Usuário / ID 1**: Nome da pessoa cadastrada na fechadura como ID 1 (ex: *Felipe*)
   - **Usuário / ID 2**: Nome da pessoa cadastrada como ID 2 (ex: *Esposa*)
   - **Usuário / ID 3, 4, 5...**
   - **IDs Customizados / Apps**: Campo de texto para IDs adicionais ou contas remotas (formato `ID: Nome`, uma por linha).
   - **Tempo de Auto-Trancamento**: Segundos após abertura para a entidade retornar ao estado trancado (padrão: 10s).
   - **Tempo limite da fila de abertura**: Tempo máximo que a solicitação de abertura aguardará pelo toque da campainha se a fechadura estiver dormindo (padrão: 300s).
4. Ao salvar, as alterações entram em vigor instantaneamente em todas as entidades e no sensor de último usuário, sem precisar reiniciar o Home Assistant!
