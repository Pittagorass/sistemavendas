# Contexto para Desenvolvimento de Software - Sistema ERP/E-commerce

Este documento serve como a "Fonte da Verdade" (Source of Truth) e contexto detalhado para orientação de Inteligências Artificiais no desenvolvimento e geração do código-fonte do sistema. Em caso de conflito com o `Documento_de_Requisitos_ERP.pdf`, **prevalece este documento**.

> **Legenda:** itens marcados com **[NOVO]** foram acrescentados na revisão de requisitos (lacunas identificadas). Itens marcados com **[PADRÃO]** são decisões adotadas por padrão e podem ser revistas pelo responsável do projeto.

## 1. Escopo Geral do Projeto
O sistema consiste em uma solução integrada de **E-commerce (Front-end do Cliente)** e **ERP (Retaguarda Administrativa)** focada em cadastro de usuários, gestão de carrinho de compras, pagamento, controle de estoque por parte do gerente e faturamento automático de pedidos com emissão de NF-e.

## 2. Stack Tecnológica Obrigatória (Requisitos Não Funcionais de Infraestrutura)
| ID | Categoria | Especificação |
| :--- | :--- | :--- |
| **RNF-TEC01** | Back-end | Python 3.10+ com **FastAPI** [PADRÃO], ORM SQLAlchemy 2.x e migrações com Alembic. Executado como Serverless Function Python na Vercel (rotas sob `/api`). |
| **RNF-TEC02** | Banco de Dados | PostgreSQL 14+ (ACID e integridade referencial). Hospedagem gerenciada com **pooler de conexões** obrigatório (ex.: Neon/Vercel Postgres) por causa do modelo serverless. |
| **RNF-TEC03** | Hospedagem & Deploy | Vercel para front-end e funções serverless, com deploy automático via GitHub (CI/CD). Variáveis sensíveis apenas em Environment Variables da Vercel. |
| **RNF-TEC04** | Segurança de Transporte | SSL/TLS (HTTPS) obrigatório em **todas** as conexões: navegador ↔ Vercel, API ↔ PostgreSQL (`sslmode=require`) e API ↔ serviços externos. |
| **RNF-TEC05** | Front-end [PADRÃO] | HTML/CSS/JavaScript com Fetch API, servido como estático pela Vercel no mesmo projeto do back-end (mesma origem, sem CORS). |
| **RNF-TEC06** | Senhas | Hash obrigatório com **`bcrypt`** (custo mínimo 12). PBKDF2 **não** deve ser usado. |
| **RNF-TEC07** | Serviços externos [PADRÃO] | CEP: ViaCEP (fallback BrasilAPI) · Imagens: Vercel Blob · E-mail: Resend · Pagamento: Mercado Pago (Pix e cartão) · NF-e: Focus NFe (API intermediária). |
| **RNF-TEC08** | Restrições do serverless | Nenhum estado pode ficar em memória entre requisições (bloqueios, reservas, sessões ficam no PostgreSQL). Tarefas periódicas usam **Vercel Cron**. Chamadas externas devem respeitar o tempo máximo de execução da função. |

---

## 3. Matriz de Requisitos Funcionais (RF) e Não Funcionais (RNF)

### Módulo 1: Cadastro de Clientes e Usuários
| ID | Tipo | Nome | Descrição |
| :--- | :--- | :--- | :--- |
| **RF-CAD01** | Funcional | Formulário de Cadastro | Permitir a criação de contas informando Nome Completo, E-mail, CPF, Telefone, Senha e Endereço (CEP, logradouro, número, complemento, bairro, cidade, UF, código IBGE do município). |
| **RNF-CAD01** | Não Funcional | Autocompletar por CEP | Buscar o endereço automaticamente via ViaCEP assim que o usuário digitar os 8 dígitos do CEP (fallback BrasilAPI). Se a API falhar, permitir preenchimento manual. O código IBGE retornado deve ser armazenado (necessário para a NF-e). |
| **RF-CAD02** | Funcional | Validação de Dados | Validar o formato do e-mail (presença de "@" e domínio válido) e aplicar o algoritmo oficial de validação de dígito verificador do CPF (rejeitar sequências repetidas como `111.111.111-11`). Validação ocorre no front-end **e** obrigatoriamente no back-end. |
| **RNF-CAD02** | Não Funcional | Unicidade de Registros | Bloquear cadastros duplicados com o mesmo E-mail ou CPF por meio de constraints `UNIQUE` no PostgreSQL (e-mail normalizado em minúsculas; CPF salvo apenas com dígitos). |
| **RF-CAD03** | Funcional | Criptografia de Senha | O back-end deve receber a senha do usuário e salvá-la de forma segura no banco de dados. Senha mínima: 8 caracteres, com letras e números. |
| **RNF-CAD03** | Não Funcional | Criptografia de Hash | Proibido salvar senhas em texto limpo; utilizar obrigatoriamente `bcrypt` (ver RNF-TEC06). Senhas nunca aparecem em logs ou respostas da API. |
| **RF-CAD04** [NOVO] | Funcional | Edição de Perfil | Permitir ao cliente editar nome, telefone, senha (exigindo a senha atual) e endereços. E-mail e CPF não são editáveis pelo cliente. |
| **RNF-CAD04** [NOVO] | Não Funcional | Validação de Telefone | Telefone com DDD válido, 10 ou 11 dígitos, armazenado apenas com dígitos. |
| **RF-CAD05** | Funcional | Privacidade (LGPD) – Exclusão | Disponibilizar no perfil do cliente a exclusão de conta. A exclusão é **lógica com anonimização**: nome, e-mail, telefone e endereço são substituídos por valores anonimizados e `excluido_em` é preenchido. Pedidos e notas fiscais são **preservados** por obrigação legal fiscal (5 anos), vinculados ao registro anonimizado. |
| **RNF-CAD05** | Não Funcional | Conformidade Geral | Todo o fluxo de armazenamento e descarte de dados deve respeitar a LGPD. Dados fiscais retidos usam como base legal o cumprimento de obrigação legal (art. 7º, II). |
| **RF-CAD06** [NOVO] | Funcional | Consentimento e Acesso aos Dados | No cadastro, exigir aceite da Política de Privacidade e dos Termos de Uso (registrando data/hora e versão). No perfil, permitir ao cliente exportar seus dados pessoais em JSON. |

### Módulo 2: Login e Autenticação de Segurança
| ID | Tipo | Nome | Descrição |
| :--- | :--- | :--- | :--- |
| **RF-SEC01** | Funcional | Autenticação | Permitir o acesso à conta informando **e-mail ou CPF** e senha corretos. Mensagem de erro genérica ("credenciais inválidas"), sem revelar qual campo está errado. |
| **RF-SEC02** | Funcional | Encerramento de Sessão | Permitir o "Logout" invalidando a sessão atual: o refresh token é revogado no banco e o `jti` do access token é inserido na tabela `tokens_revogados` até sua expiração. |
| **RF-SEC03** [NOVO] | Funcional | Perfis de Acesso (RBAC) | Existem os perfis `cliente` e `gerente`. Cadastro público cria apenas `cliente`. O primeiro `gerente` é criado por script de seed/CLI; demais gerentes são promovidos por um gerente existente. Rotas do ERP exigem perfil `gerente`. |
| **RNF-SEC01** | Não Funcional | Geração de JWT | O back-end gera JWT **assinados** (HS256, segredo em variável de ambiente) contendo `sub`, `perfil`, `jti` e `exp`. Access token com validade de 15 minutos; refresh token de 7 dias armazenado (hash) no banco e enviado em cookie `HttpOnly`, `Secure`, `SameSite=Strict`. |
| **RNF-SEC02** | Não Funcional | Bloqueio de Brute Force | Bloquear temporariamente a conta por 15 minutos após 5 tentativas consecutivas de senha incorreta. Contadores persistidos no PostgreSQL (`tentativas_login`), nunca em memória. |
| **RNF-SEC03** [NOVO] | Não Funcional | Limite por IP | Limitar tentativas de login por IP (ex.: 20 por 15 minutos) para evitar que um atacante bloqueie contas de terceiros em massa. |

### Módulo 3: Jornada do Carrinho de Compras (Front-end)
| ID | Tipo | Nome | Descrição |
| :--- | :--- | :--- | :--- |
| **RF-C01** | Funcional | Adicionar ao Carrinho | Permitir que o cliente insira itens no carrinho a partir do catálogo ou página do produto. O carrinho é persistido no banco e exige login [PADRÃO]. |
| **RNF-C01** | Não Funcional | Atualização Assíncrona | A inserção de itens ocorre via Fetch API sem recarregar a tela. |
| **RF-C02** | Funcional | Validação de Estoque | Impedir quantidades superiores ao saldo **disponível** (`estoque_fisico - estoque_reservado`). A verificação é feita no back-end de forma atômica. |
| **RNF-C02** | Não Funcional | Reserva de Inventário | Ao **iniciar o checkout**, os itens são reservados por 15 minutos (`reservas_estoque` com `expira_em`). Reservas expiradas são liberadas por um Vercel Cron e ignoradas nas consultas de disponibilidade. Reserva e baixa usam `SELECT ... FOR UPDATE` ou `UPDATE ... WHERE disponivel >= qtd` para evitar condição de corrida. |
| **RF-C03** | Funcional | Alterar Quantidades | Permitir aumentar, diminuir ou remover itens na tela resumo do carrinho. Se um produto for desativado ou ficar sem estoque, o item é sinalizado e não pode seguir para o checkout. |
| **RNF-C03** | Não Funcional | Recálculo em Tempo Real | Subtotal, frete e total são recalculados a cada alteração. O front-end exibe valores, mas o **valor oficial é sempre calculado no back-end** com o preço atual do produto. |
| **RF-C04** [NOVO] | Funcional | Cálculo de Frete [PADRÃO] | Frete calculado por tabela fixa por UF de destino (cadastrada pelo gerente), com frete grátis acima de um valor configurável. Implementado atrás de uma interface `CalculadoraFrete` para futura troca por API de transportadora. |

### Módulo 4: Painel Administrativo de Produtos e Estoque (ERP)
| ID | Tipo | Nome | Descrição |
| :--- | :--- | :--- | :--- |
| **RF-PROD01** | Funcional | Cadastro de Produtos | O gerente cadastra itens com nome, descrição, preço de venda, imagem, quantidade física inicial e **dados fiscais**: NCM, CFOP, CST/CSOSN, unidade comercial e origem da mercadoria. |
| **RF-PROD02** | Funcional | Edição e Desativação | Permitir alterar atributos de produtos e desativar (exclusão lógica, `ativo = false`) itens obsoletos. Produtos com pedidos nunca são excluídos fisicamente. |
| **RF-PROD03** [NOVO] | Funcional | Movimentação de Estoque | Toda entrada, saída, ajuste ou venda gera um registro em `movimentacoes_estoque` (tipo, quantidade, motivo, usuário, data), servindo de auditoria. |
| **RNF-PROD01** | Não Funcional | Armazenamento de Imagens | Imagens armazenadas no Vercel Blob; o PostgreSQL guarda apenas a URL. Aceitar JPG/PNG/WebP até 5 MB. |
| **RNF-PROD02** | Não Funcional | Sincronismo de Baixas | A baixa do estoque físico ocorre **na mesma transação ACID** que confirma o pagamento do pedido, garantindo que estoque e vendas nunca fiquem divergentes. |

### Módulo 5: Pagamento [NOVO]
| ID | Tipo | Nome | Descrição |
| :--- | :--- | :--- | :--- |
| **RF-PAG01** [NOVO] | Funcional | Checkout com Pagamento [PADRÃO] | Ao finalizar o carrinho, criar a cobrança no Mercado Pago (Pix ou cartão via Checkout Pro). Dados de cartão **nunca** trafegam ou são armazenados no sistema. |
| **RF-PAG02** [NOVO] | Funcional | Confirmação por Webhook | O status do pagamento é atualizado exclusivamente via webhook do gateway, com validação de assinatura e consulta de confirmação à API do gateway. O processamento deve ser idempotente. |
| **RNF-PAG01** [NOVO] | Não Funcional | Ambiente de Testes | Desenvolvimento e testes usam apenas credenciais de sandbox do gateway. |

### Módulo 6: Faturamento e Integração Comercial
| ID | Tipo | Nome | Descrição |
| :--- | :--- | :--- | :--- |
| **RF-F01** | Funcional | Geração do Pedido | Converter o carrinho validado em "Pedido de Venda" com `numero_pedido` sequencial imutável (sequence própria; lacunas por rollback são aceitas). Itens guardam o **preço unitário vigente no momento da compra**. |
| **RF-F04** [NOVO] | Funcional | Ciclo de Vida do Pedido | Status: `aguardando_pagamento` → `pago` → `faturado` → `enviado` → `entregue`; ou `cancelado` (pagamento recusado/expirado, liberando a reserva). Toda transição é registrada com data/hora. |
| **RF-F02** | Funcional | Emissão de NF-e | Após o pagamento confirmado, enviar os dados do pedido à API intermediária (Focus NFe) [PADRÃO], que assina o XML (XMLDSig), transmite à SEFAZ e retorna o resultado. Emissão processada de forma **assíncrona** (consulta de status por webhook ou Vercel Cron). Desenvolvimento apenas em ambiente de **homologação**. |
| **RNF-F02** | Não Funcional | Certificação Digital | A comunicação com a SEFAZ usa mTLS com Certificado Digital A1, que fica sob custódia da API intermediária (não é armazenado nas funções serverless). Numeração da NF-e (série/número) é controlada separadamente do número do pedido. |
| **RNF-F03** [NOVO] | Não Funcional | Dados do Emitente | CNPJ, Inscrição Estadual, razão social, endereço e regime tributário da empresa ficam em tabela de configuração `empresa`, editável apenas pelo gerente. |
| **RF-F03** | Funcional | Envio de Documentos | Enviar automaticamente o PDF do DANFE e o XML autorizado para o e-mail do comprador (via Resend). Os arquivos também ficam disponíveis no histórico de pedidos do cliente. |

### Requisitos Não Funcionais Transversais [NOVO]
| ID | Nome | Descrição |
| :--- | :--- | :--- |
| **RNF-GER01** | Desempenho | Endpoints de leitura com p95 < 500 ms (excluindo chamadas a serviços externos). |
| **RNF-GER02** | Testes | Testes automatizados com `pytest` executados no CI do GitHub; regras de negócio (CPF, estoque, reserva, cálculo de total) com cobertura mínima de 80%. |
| **RNF-GER03** | Logs e Auditoria | Logs estruturados (JSON) sem dados pessoais sensíveis (senha, CPF completo, tokens). |
| **RNF-GER04** | Backup | Backups automáticos diários do PostgreSQL providos pela hospedagem gerenciada. |

---

## 4. Modelo de Dados Mínimo
| Tabela | Finalidade |
| :--- | :--- |
| `usuarios` | Dados do cliente/gerente, `perfil`, hash da senha, `excluido_em`, aceite de termos |
| `enderecos` | Endereços do usuário (com código IBGE) |
| `produtos` | Catálogo, preço, dados fiscais, `estoque_fisico`, `ativo`, URL da imagem |
| `movimentacoes_estoque` | Auditoria de entradas/saídas |
| `carrinhos` / `itens_carrinho` | Carrinho persistido do cliente |
| `reservas_estoque` | Reservas de checkout com `expira_em` |
| `pedidos` | Pedido de venda, `numero_pedido`, status, totais, frete, endereço de entrega (cópia) |
| `itens_pedido` | Itens com `preco_unitario` congelado |
| `pagamentos` | Transações do gateway e status |
| `notas_fiscais` | Número/série, chave de acesso, status, URLs do XML e DANFE |
| `tentativas_login` | Controle de brute force por conta e IP |
| `refresh_tokens` / `tokens_revogados` | Controle de sessão e logout |
| `tabela_frete` / `empresa` | Configurações do gerente |

## 5. Tabela de Equivalência com o Documento_de_Requisitos_ERP.pdf
| PDF | contexto.md |
| :--- | :--- |
| RNF-TEC01..04 | RNF-TEC01..04 (+ RNF-TEC06 para bcrypt) |
| RF-CAD01, RNF-CAD01, RF-CAD02, RNF-CAD02 | Mesmos IDs |
| RF-SEC01, RNF-SEC01 | Mesmos IDs (login aceita também CPF; JWT é assinado, não criptografado) |
| RF-CAR01 | RF-C01 + RF-C03 |
| RNF-CAR01 | RNF-C01 + RNF-C03 |
| RF-EST01 | RF-PROD01 + RF-PROD02 + RF-PROD03 |
| RNF-EST01 | RNF-PROD01 |
| RF-FAT01 | RF-F01 + RF-F02 |
| RNF-FAT01 | RNF-F02 |

## 6. Ordem de Implementação e Estado Atual
| Etapa | Escopo | Status |
| :--- | :--- | :--- |
| 1 | Fundação: projeto FastAPI, conexão PostgreSQL, Alembic, CI e deploy na Vercel | **Concluída localmente** (2026-10-26): testes passando e conexão com o Neon (sa-east-1) validada. Pendente: enviar ao GitHub, verificar CI e deploy na Vercel |
| 2 | Módulos 1 e 2: cadastro, login, JWT, RBAC | Pendente |
| 3 | Módulo 4: produtos, estoque e painel do gerente | Pendente |
| 4 | Módulo 3: carrinho, frete e reserva | Pendente |
| 5 | Módulo 5 e RF-F01/RF-F04: checkout, pagamento e pedido | Pendente |
| 6 | Módulo 6: NF-e em homologação e envio de documentos | Pendente |

> Atualize esta tabela ao concluir cada etapa.

## 7. Estrutura do Código (estabelecida na Etapa 1)
```
api/index.py              Entrada da Serverless Function na Vercel (apenas importa app.main)
app/main.py               Cria o FastAPI, registra handlers de erro e inclui os routers
app/core/config.py        Settings (pydantic-settings) lidas de variáveis de ambiente / .env
app/core/database.py      engine, SessionLocal e dependência get_db (commit/rollback automático)
app/core/errors.py        ErroNegocio e formato padrão de erro JSON
app/routes/               Routers FastAPI (um arquivo por módulo: auth.py, produtos.py, ...)
app/services/             Regras de negócio (um serviço por módulo)
app/repositories/         Consultas ao banco (únicos que usam select/insert/update)
app/models/base.py        Base declarativa, convenção de nomes de constraints e ModeloBase
app/models/__init__.py    Importa todos os modelos (necessário para o autogenerate do Alembic)
app/schemas/              Schemas Pydantic de entrada/saída da API (criar a partir da Etapa 2)
app/integrations/         Clientes de serviços externos atrás de interfaces (CEP, pagamento, NF-e, e-mail, frete, storage)
migrations/               Alembic (versions/ contém as migrações)
public/                   Front-end estático HTML/CSS/JS servido pela Vercel
tests/                    pytest
vercel.json               Reescreve /api/* para api/index.py
.github/workflows/ci.yml  CI: PostgreSQL 16 + alembic upgrade head + pytest
```

**Rotas já existentes:** `GET /api/health` (API no ar) e `GET /api/health/db` (conexão com o banco).

**Variáveis de ambiente:** `AMBIENTE`, `DATABASE_URL`, `JWT_SECRET` (ver `.env.example`). Novas variáveis devem ser adicionadas em `app/core/config.py` **e** em `.env.example`.

**Dependências fixadas:** fastapi 0.115.6, pydantic-settings 2.6.1, sqlalchemy 2.0.36, psycopg[binary] 3.2.3, alembic 1.14.0 (produção, em `requirements.txt`); uvicorn, pytest e httpx (desenvolvimento, em `requirements-dev.txt`).

---

## 8. Diretrizes Específicas para a I.A. de Geração de Código
Ao gerar arquivos de código para este projeto, você (I.A.) deve seguir as regras abaixo:
1. **Modelagem de Banco de Dados:** Mantenha chaves estrangeiras (`FOREIGN KEY`) consistentes entre as tabelas da seção 4. Utilize tipos nativos do PostgreSQL: `UUID` para chaves primárias, `NUMERIC(10,2)` para valores monetários, `TIMESTAMPTZ` para datas e `CHECK` constraints para estoque não negativo. Toda alteração de schema via migração Alembic.
2. **Separação de Camadas (Clean Architecture):** A camada de rotas/controladores recebe as requisições e delega as regras de negócio a classes de serviço isoladas; o acesso a dados fica em repositórios; integrações externas (CEP, pagamento, NF-e, e-mail, frete, storage) ficam atrás de interfaces para permitir troca e mocks em testes.
3. **Tratamento de Erros:** Todas as operações com o banco devem usar transações com `try/except` e rollback automático em falhas (ex.: `with session.begin():`). Erros retornam JSON padronizado com código HTTP adequado, sem expor detalhes internos.
4. **Valores Monetários:** Usar `Decimal` em Python; nunca `float`.
5. **Segredos:** Nenhuma credencial no código ou no repositório; usar variáveis de ambiente e manter um `.env.example` sem valores reais.
6. **Idempotência:** Webhooks (pagamento e NF-e) e jobs do Vercel Cron devem poder ser executados mais de uma vez sem efeitos duplicados.
7. **Respeitar a estrutura da seção 7:** rotas só recebem a requisição, validam o schema e chamam o serviço; serviços não importam FastAPI; repositórios não contêm regra de negócio. Erros de regra de negócio são lançados como `ErroNegocio` (nunca `HTTPException` dentro de serviços).
8. **Transações:** usar a sessão recebida via `Depends(get_db)`, que já faz commit/rollback; serviços e repositórios não chamam `commit()` por conta própria.
9. **Modelos:** toda tabela herda de `ModeloBase` (UUID, `criado_em`, `atualizado_em`), é importada em `app/models/__init__.py` e ganha uma migração Alembic gerada e revisada.
10. **Idioma:** nomes de tabelas, colunas, classes e funções em português sem acentos (ex.: `numero_pedido`, `ErroNegocio`); mensagens exibidas ao usuário em português com acentuação correta.
11. **Testes:** cada nova regra de negócio acompanha testes em `tests/`; testes que dependem do banco são marcados para rodar apenas com `DATABASE_URL` definida.
