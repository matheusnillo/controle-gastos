# Controle de Gastos com Open Finance

App para ver **para onde vai o seu dinheiro** e **o que cortar** para parar de perder dinheiro.
Os dados vêm dos seus bancos via **Open Finance Brasil** (pelo Meu Pluggy, gratuito) ou de extratos
OFX/CSV importados. Roda no seu computador e, opcionalmente, na nuvem do GitHub (criptografado)
para o celular funcionar com o PC desligado.

## O que o app faz

- **Painel**: entradas, gastos, saldo do mês, projeção até o fim do mês, gráfico por categoria,
  evolução de 6 meses e comparação com a regra 50/30/20.
- **Onde cortar**: recomendações com economia estimada em R$/mês:
  - tarifas, juros, IOF e rotativo (dinheiro perdido)
  - assinaturas e cobranças recorrentes (inclusive as que aumentaram de preço)
  - delivery comparado com o mercado
  - "gastos formiga" (muitas compras pequenas)
  - categorias que dispararam em relação à sua média dos últimos 3 meses
  - orçamentos estourados, gastos não essenciais acima de 30% da renda, déficit
  - os 5 estabelecimentos onde mais foi dinheiro
- **Transações**: busca, filtro, troca de categoria. Com "aplicar a todas parecidas" o app cria
  uma regra e passa a categorizar aquele estabelecimento sempre do mesmo jeito. Exporta CSV.
- **Orçamentos**: limite mensal por categoria, com sugestão baseada na sua média.
- Pagamento de fatura, transferências entre contas próprias e investimentos **não** contam
  como gasto, para não contar o mesmo dinheiro duas vezes.

## Como rodar

Precisa só do Python 3.10+ (já instalado nesta máquina). Nenhuma biblioteca extra.

1. Dê dois cliques em `iniciar.bat` (ou rode `py app.py`).
2. O navegador abre em http://127.0.0.1:8765.
3. Clique em **Ver com dados de demonstração** para testar sem conectar banco.

## Conectar seus bancos de verdade (grátis)

### Opção 1 — Open Finance com o Meu Pluggy (gratuito para uso pessoal, sem prazo)

Conectar um banco direto pela Pluggy exige plano pago. Para uso pessoal, o caminho gratuito é o
**Meu Pluggy**: você conecta seus bancos lá e o app lê esses dados pelo conector "MeuPluggy".

1. Crie uma conta em https://meu.pluggy.ai e conecte seus bancos (a autorização é feita no app do banco).
2. Crie uma conta em https://dashboard.pluggy.ai, crie uma *Application* e copie `Client ID` e
   `Client Secret` para o arquivo `.env`.
3. Abra o app e clique em **Conectar banco**: o widget já abre no conector Meu Pluggy. Entre com a
   conta do Meu Pluggy e escolha o banco. Repita para cada banco (uma conexão por banco).
4. O Meu Pluggy atualiza os dados uma vez por dia; clique em **Sincronizar** para trazê-los.

Se o login abrir em pop-up, permita pop-ups para `127.0.0.1:8765` no navegador.
Para ver também os bancos de teste, use `PLUGGY_INCLUDE_SANDBOX=true`; para listar todos os
conectores (plano pago), use `PLUGGY_MEU_PLUGGY=false`.

### Opção 2 — Importar extrato OFX/CSV (sem cadastro nenhum)

Exporte o extrato ou a fatura no app/internet banking e clique em **Importar extrato**:

- **OFX**: Itaú, Bradesco, Banco do Brasil, Santander, Caixa, Inter, C6 e a maioria dos bancos.
- **CSV**: Nubank (conta e fatura) e CSVs genéricos com colunas de data, descrição e valor.
- Pode importar o mesmo arquivo de novo: transações repetidas não são duplicadas.

## Alertas no WhatsApp (grátis)

Usa o [CallMeBot](https://www.callmebot.com/blog/free-api-whatsapp-messages/), gratuito para uso pessoal
(só envia para o seu próprio número).

1. No celular, salve o contato **+34 644 95 42 75** e mande no WhatsApp:
   `I allow callmebot to send me messages`. Em até 2 minutos chega a sua **apikey**.
2. No app, aba **Alertas e celular**: preencha seu número e a apikey, salve e clique em
   **Enviar mensagem de teste**.

O que o app avisa (cada aviso só uma vez):
- gasto acima de um valor (padrão R$ 200) e qualquer tarifa, juros ou IOF;
- orçamento de uma categoria em 85% e estourado;
- assinatura que aumentou de preço;
- resumo diário no horário escolhido (padrão 20h).

O app busca lançamentos novos a cada 4 h (`SYNC_HORAS` no `.env`) enquanto estiver aberto no computador.
O Meu Pluggy atualiza os bancos 1x por dia, então um gasto pode levar até 1 dia para ser avisado.
O texto dos alertas passa pelos servidores do CallMeBot.

## Modo nuvem — celular sem o computador ligado (grátis)

O GitHub roda o app por você: a cada 4 h um robô (GitHub Actions) baixa as transações da Pluggy,
manda os alertas no WhatsApp e publica o painel no GitHub Pages. O celular abre esse painel com o PC desligado.

**Segurança:** o repositório é público (exigência do Pages grátis), mas nele só vai o código. Seus dados
vão **criptografados** (AES-256-GCM, chave derivada da sua senha com PBKDF2, 600 mil iterações) e são
decifrados só no seu celular. Sem a senha, ninguém lê nada — por isso a senha precisa ser forte.
Os logs do robô também são públicos e não mostram dados pessoais.

No celular é só para **ver** (painel, onde cortar, transações, orçamentos). Trocar categorias, orçamentos
e alertas continua no computador; as mudanças sobem sozinhas e aparecem no celular na próxima atualização.

### Configuração (uma vez, ~10 min)

1. Crie uma conta em https://github.com e um repositório **público e vazio** em https://github.com/new
   (ex.: `controle-gastos`).
2. Crie um token em https://github.com/settings/personal-access-tokens/new:
   - *Repository access*: **Only select repositories** → o repositório criado;
   - *Permissions → Repository*: **Contents**, **Workflows**, **Secrets** e **Pages** = *Read and write*.
3. No arquivo `.env`, preencha:
   ```
   GITHUB_TOKEN=github_pat_...
   GITHUB_REPO=seu-usuario/controle-gastos
   NUVEM_SENHA=uma-frase-longa-com-numeros-2026
   ```
   A senha precisa de 12+ caracteres, com letras e números. **Não a perca**: sem ela os dados não abrem.
4. Dê dois cliques em `publicar-nuvem.bat`. Ele cadastra os segredos no GitHub, liga o Pages, envia o
   código (com travas que impedem enviar `.env`, `data/` e senhas) e dispara o robô.
5. Depois de ~2 min, abra no celular `https://seu-usuario.github.io/controle-gastos/`, digite a senha e use
   **Adicionar à tela inicial**.
6. Reinicie o app no computador: com a nuvem ligada, quem manda os alertas é o robô (sem duplicar mensagens).

Para forçar uma atualização: aba **Actions** do repositório → *Controle de Gastos (nuvem)* → *Run workflow*.
O GitHub pode atrasar execuções agendadas em alguns minutos.

## App no celular com o computador ligado (opcional)

O painel funciona como app instalável (PWA). Para abrir no celular de qualquer lugar, sem expor seus
dados na internet, use o [Tailscale](https://tailscale.com/download) (grátis), que cria uma rede privada só
entre os seus aparelhos:

1. No app, aba **Alertas e celular**, crie um **PIN** (6 a 12 números).
2. Instale o Tailscale no computador e no celular, com a mesma conta.
3. No computador, rode `tailscale serve --bg 8765`. Ele mostra um endereço `https://seu-pc.xxxx.ts.net`.
4. No celular, abra esse endereço, digite o PIN e use **Adicionar à tela inicial**
   (Android: menu ⋮ do Chrome · iPhone: Compartilhar no Safari).

O celular só mostra dados com o computador ligado e o app aberto. Para o app abrir sozinho (sem janela)
quando você entra no Windows, rode uma vez `instalar-inicio-automatico.bat`
(para desfazer: `schtasks /delete /tn "ControleDeGastos" /f`). Os logs ficam em `data/app.log`.

## Privacidade

- O servidor escuta só em `127.0.0.1`. O acesso pelo celular passa pelo Tailscale (rede privada) e exige PIN;
  a sessão dura 30 dias e trocar o PIN desconecta todos os aparelhos. Dados financeiros nunca ficam guardados no celular.
- Transações ficam em `data/financas.db` (SQLite). Apague a pasta ou use
  **Conexões → Apagar todos os dados locais** para limpar.
- Nunca compartilhe o arquivo `.env`.

## Estrutura

```
app.py                  servidor HTTP + API
financas/categorize.py  categorias, palavras-chave e mapeamento da Pluggy
financas/insights.py    resumo do mês e recomendações de corte
financas/pluggy.py      cliente da API da Pluggy
financas/importer.py    importação de extratos OFX/CSV
financas/alerts.py      alertas e resumo diário
financas/whatsapp.py    envio pelo CallMeBot
financas/auth.py        PIN e sessão do acesso pelo celular
financas/nuvem.py       criptografia e sincronização com a nuvem
nuvem_job.py            robô que roda no GitHub Actions
publicar_nuvem.py       publica/atualiza o app no GitHub
static/nuvem.js         painel do celular no modo nuvem (decifra no aparelho)
financas/store.py       SQLite
financas/demo.py        dados de demonstração
static/                 interface (HTML/CSS/JS, Chart.js)
tests/                  testes: py -m unittest discover -s tests -t .
```

Para ajustar a categorização de estabelecimentos que o app não reconhece, adicione palavras em
`KEYWORD_RULES` em `financas/categorize.py`, ou simplesmente recategorize pela tela.
