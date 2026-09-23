#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
coletar_dou.py
==============
Coleta Portarias e Resolucoes da SUFRAMA publicadas no Diario Oficial da
Uniao que tratam de projetos de empresas (aprovacao, alteracao,
cancelamento, suspensao) e extrai os dados estruturados de cada ato.

COMO FUNCIONA
-------------
O portal do DOU nao tem API publica, mas a pagina de resultados embute os
dados num <script type="application/json">. Este coletor le esse JSON.

Duas particularidades do portal, descobertas na pratica:

1. O filtro `orgSub` so funciona junto com `orgPrin`, e o nome do
   ministerio mudou varias vezes (caixa alta ate 2017, caixa mista hoje).
   Filtrar por orgao quebraria a serie historica. Por isso buscamos por
   texto e peneiramos pelo campo `hierarchyStr` do proprio resultado.

2. A paginacao por URL esta quebrada: `currentPage` e ignorado e sempre
   devolve a primeira pagina de 20 itens. Contorno: fatiar a busca em
   janelas de data e, quando a janela devolver 20 itens (indicio de que ha
   mais), dividir a janela ao meio recursivamente.

USO
---
  python coletar_dou.py                      # 01/01/2025 ate hoje
  python coletar_dou.py --de 2026-01-01      # a partir de uma data
  python coletar_dou.py --de 2026-08-01 --ate 2026-09-17
  python coletar_dou.py --teste-url <url>    # testa a extracao de um ato
  python coletar_dou.py --reiniciar          # ignora o cache e recomeca

Requer: requests, beautifulsoup4, lxml, pandas, pyarrow
"""

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------------------------
# Configuracao
# ---------------------------------------------------------------------------
BUSCA_URL = "https://www.in.gov.br/consulta/-/buscar/dou"
ATO_URL = "https://www.in.gov.br/web/dou/-/{slug}"
SCRIPT_JSON_ID = "_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params"

# Termo de busca. Todo ato da SUFRAMA traz a palavra no titulo ou na
# assinatura, entao serve de rede ampla; a peneira real e a hierarquia.
TERMO_BUSCA = "suframa"
HIERARQUIA_ALVO = "zona franca de manaus"

# Tipos de ato que interessam (campo artType do JSON)
TIPOS_ATO = {"portaria", "resolucao", "resolução"}

PASTA_DADOS = Path("dados")
ARQ_PARCIAL = PASTA_DADOS / "_parcial_dou.csv"
ARQ_CSV = PASTA_DADOS / "dou_suframa.csv"
ARQ_PARQUET = PASTA_DADOS / "dou_suframa.parquet"

COLUNAS = [
    "data_publicacao", "tipo_ato", "numero_ato", "titulo", "classificacao",
    "ato_de_projeto", "tem_anexo", "tipo_projeto", "empresa", "cnpj",
    "inscricao_suframa", "codigo_produto", "produto", "processo",
    "item", "secao", "pagina", "hierarquia", "url", "texto_item", "texto",
]

# Tipos de projeto previstos na regulamentacao da SUFRAMA. A redacao varia
# ("do tipo diversificacao", "projeto de diversificacao", "diversificacao
# de producao"), entao a busca e por radical.
TIPOS_PROJETO = {
    "implanta": "implantação",
    "diversifica": "diversificação",
    "amplia": "ampliação",
    "atualiza": "atualização",
    "moderniza": "modernização",
    "reformula": "reformulação",
    "adapta": "adaptação",
    "substitui": "substituição",
    "revis": "revisão",
    "transfer": "transferência",
}

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36"),
    "Accept-Language": "pt-BR,pt;q=0.9",
}


# ---------------------------------------------------------------------------
# Utilitarios
# ---------------------------------------------------------------------------
def sem_acento(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in texto if not unicodedata.combining(c))


def limpar(html_ou_texto: str) -> str:
    """Remove tags e normaliza espacos."""
    t = re.sub(r"<[^>]*>", " ", str(html_ou_texto))
    t = t.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", t).strip()


def baixar(url: str, session: requests.Session, params=None, tentativas=4):
    for t in range(tentativas):
        try:
            r = session.get(url, params=params, headers=HEADERS,
                            timeout=60, verify=False)
            if r.status_code == 200:
                return r.text
            print(f"[HTTP {r.status_code}]", end=" ", flush=True)
        except requests.RequestException:
            print(f"[rede {t+1}/{tentativas}]", end=" ", flush=True)
        if t < tentativas - 1:
            time.sleep(3 * (t + 1))
    return None


# ---------------------------------------------------------------------------
# Busca
# ---------------------------------------------------------------------------
def buscar_pagina(d1: date, d2: date, session: requests.Session):
    """Devolve a lista de itens do JSON embutido para a janela informada."""
    params = {
        "q": TERMO_BUSCA,
        "s": "todos",
        "exactDate": "personalizado",
        "publishFrom": d1.strftime("%d-%m-%Y"),
        "publishTo": d2.strftime("%d-%m-%Y"),
        "sortType": "0",
        "delta": "20",
    }
    html = baixar(BUSCA_URL, session, params=params)
    if not html:
        return None

    soup = BeautifulSoup(html, "lxml")
    tag = soup.find("script", id=SCRIPT_JSON_ID)
    if not tag:
        return []
    try:
        dados = json.loads(tag.string or tag.text)
    except json.JSONDecodeError:
        return []
    return dados.get("jsonArray", []) or []


def coletar_janela(d1: date, d2: date, session: requests.Session, prof=0):
    """Busca a janela; se vier cheia (20 itens), divide ao meio.

    A paginacao do portal nao funciona por URL, entao estreitar a janela
    ate caber numa pagina e a unica forma de garantir cobertura total.
    """
    prefixo = "  " + "  " * prof
    itens = buscar_pagina(d1, d2, session)
    if itens is None:
        print(f"{prefixo}{d1:%d/%m/%Y}-{d2:%d/%m/%Y}: FALHOU")
        return []

    if len(itens) < 20 or d1 == d2:
        if itens:
            print(f"{prefixo}{d1:%d/%m/%Y}-{d2:%d/%m/%Y}: {len(itens)} itens")
        return itens

    # Janela cheia: pode haver mais de 20. Divide.
    meio = d1 + (d2 - d1) / 2
    print(f"{prefixo}{d1:%d/%m/%Y}-{d2:%d/%m/%Y}: cheia, dividindo")
    time.sleep(0.5)
    esq = coletar_janela(d1, meio, session, prof + 1)
    time.sleep(0.5)
    dir_ = coletar_janela(meio + timedelta(days=1), d2, session, prof + 1)
    return esq + dir_


def interessa(item: dict) -> bool:
    """Filtra por orgao (SUFRAMA) e por tipo de ato.

    A peneira e pelo trecho "zona franca de manaus" dentro da hierarquia,
    NAO pelo ministerio. Ao longo dos governos a SUFRAMA passou por pastas
    de nomes diferentes — Ministerio da Economia; da Industria, Comercio
    Exterior e Servicos; do Desenvolvimento, Industria, Comercio e
    Servicos — e o proprio nome da autarquia mudou de caixa alta para
    caixa mista no portal. Amarrar a busca a um ministerio deixaria
    periodos inteiros de fora; a hierarquia da autarquia e estavel.
    """
    hier = sem_acento(item.get("hierarchyStr", "")).lower()
    if sem_acento(HIERARQUIA_ALVO) not in hier:
        return False
    tipo = sem_acento(item.get("artType", "")).lower().strip()
    return any(sem_acento(t) in tipo for t in TIPOS_ATO)


# ---------------------------------------------------------------------------
# Extracao dos campos do ato
# ---------------------------------------------------------------------------
def extrair_ementa(texto: str) -> str:
    """Isola a ementa — a linha que diz o que o ato faz.

    Classificar pelo texto inteiro nao funciona: portarias de aprovacao
    trazem clausula padrao como "sob pena de cancelamento dos beneficios",
    o que jogaria toda aprovacao no balde de cancelamento. A ementa fica
    entre o titulo e o preambulo ("O SUPERINTENDENTE ... no uso das
    atribuicoes"), e e a declaracao autoritativa do objeto do ato.
    """
    corte = re.split(
        r"\bO[A-Z\s]{0,4}SUPERINTENDENTE|\bA\s+SUPERINTENDENTE|"
        r"no\s+uso\s+d[ae]s?\s+atribui|\bRESOLVE\b|\bCONSIDERANDO\b|"
        r"\bArt\.\s*1",
        texto, maxsplit=1, flags=re.I)[0]
    # Remove o cabecalho "PORTARIA SUFRAMA Nº X, DE d DE mes DE aaaa"
    corte = re.sub(r"^.*?\bDE\s+\d{1,2}[º°o]?\s+DE\s+[A-Za-zÀ-ÿ]+\s+DE\s+\d{4}\s*",
                   "", corte, flags=re.I | re.S)
    return limpar(corte)[:400]


# Ordem importa: um ato de cancelamento cita a portaria de aprovacao que
# esta cancelando, entao os verbos mais especificos vem primeiro.
REGRAS = [
    # Cota de importacao NAO e aprovacao de projeto: o ato apenas amplia o
    # limite de insumos de um produto ja aprovado antes.
    # "cotas" e "quotas" convivem na serie: c+otas ou qu+otas
    (r"(?:c|qu)otas?\s+de\s+importa[çc]|"
     r"remanejamento\s+de\s+(?:c|qu)otas?|"
     r"adicional\s+de\s+(?:c|qu)otas?", "cota de importacao"),
    (r"torna(?:r|ndo)?\s+sem\s+efeito", "tornado sem efeito"),
    (r"\bcancel", "cancelamento"),
    (r"\brevog", "revogacao"),
    (r"\bsuspend|\bsuspens", "suspensao"),
    (r"\bprorrog", "prorrogacao"),
    (r"\bratific|\bhomolog", "homologacao"),
    (r"\baltera|\bretific", "alteracao"),
    (r"\baprov", "aprovacao"),
    (r"\bconced", "concessao"),
    (r"\bindefer", "indeferimento"),
    (r"\barquiv", "arquivamento"),
]


# Aberturas tipicas de ato administrativo interno da autarquia. Nao tratam
# de projeto de empresa e nao devem poluir as estatisticas.
PADROES_ADMIN = (
    r"^(?:estabelece\s+normas|disp[õo]e\s+sobre|institui\b|delega\b|"
    r"designa\b|realoca|torna\s+p[úu]blic|aprova\s+o\s+(?:regimento|"
    r"regulamento|plano|calend[áa]rio|manual)|constitui\b|cria\b|"
    r"estabelece\s+o\s+rito|estende\s+os\s+efeitos)"
)


def eh_ato_de_projeto(texto: str) -> bool:
    """Distingue ato sobre projeto de empresa de ato administrativo interno."""
    t = sem_acento(texto).lower()
    # Sinais fortes: codigo SUFRAMA do produto, inscricao, ou "da empresa"
    if re.search(r"codigo\s+suframa\s*n?[º°.\s]*\d{3,4}", t):
        return True
    if re.search(r"\bprojeto\s+(?:industrial|agropecuario|t[eé]cnico)", t):
        return True
    if re.search(r"\bd[ao]\s+empresa\b|sociedade\s+empresaria", t):
        return True
    ementa = sem_acento(extrair_ementa(texto)).lower()
    if re.match(PADROES_ADMIN, ementa):
        return False
    return bool(re.search(r"incentivos?\s+fiscais|beneficios?\s+fiscais", t))


def classificar(texto: str) -> str:
    """Classifica o ato pelo que ele faz com o projeto."""
    inicio = sem_acento(texto[:120]).lower()
    if "portaria de pessoal" in inicio:
        return "normativo/administrativo"

    ementa_bruta = sem_acento(extrair_ementa(texto)).lower()
    # Ato normativo que apenas regula procedimentos nao e cancelamento,
    # ainda que a palavra apareca na ementa.
    if re.match(PADROES_ADMIN, ementa_bruta):
        return "normativo/administrativo"
    # 1) Pela ementa, que e a fonte mais confiavel
    ementa = sem_acento(extrair_ementa(texto)).lower()
    if len(ementa) > 8:
        for padrao, rotulo in REGRAS:
            if re.search(padrao, ementa):
                return rotulo

    # 2) Sem ementa util, olhar o dispositivo do Art. 1º
    # O "(?!\d)" impede casar com "Art. 12" do preambulo ("considerando
    # o que lhe autoriza o Art. 12, Inciso I"): sem ele, a regra lia o
    # trecho errado e o ato caia em "outro".
    m = re.search(r"Art\.?\s*1\s*[º°o]?(?!\d)\s*[-.]?\s*(.{0,180})",
                  texto, re.I | re.S)
    if m:
        disp = sem_acento(m.group(1)).lower()
        for padrao, rotulo in REGRAS:
            if re.search(padrao, disp):
                return rotulo

    # 3) Ultimo recurso: so o verbo que abre o ato, sem o preambulo. Usar
    # 300 caracteres pegava "aprovada pelo Conselho de Administracao" e
    # classificava como aprovacao atos que nada aprovam.
    ini = sem_acento(texto[:160]).lower()
    ini = re.split(r"\bo\s+superintendente\b", ini)[0]
    for padrao, rotulo in REGRAS:
        if re.search(padrao, ini):
            return rotulo
    return "outro"


def extrair_campos(texto: str) -> dict:
    """Extrai os dados estruturados do corpo do ato."""
    d = {c: "" for c in COLUNAS}

    # Tipo de projeto: procura o radical na ementa e no dispositivo, pois a
    # redacao varia muito entre "do tipo X", "projeto de X" e "X de producao".
    escopo = sem_acento(extrair_ementa(texto) + " " + texto[:1200]).lower()
    m = re.search(r"do\s+tipo\s+([a-z\s/-]{4,30}?)\s*[,.]", escopo)
    if m:
        bruto = m.group(1).strip()
        for radical, rotulo in TIPOS_PROJETO.items():
            if radical in bruto:
                d["tipo_projeto"] = rotulo
                break
        else:
            d["tipo_projeto"] = bruto
    if not d["tipo_projeto"]:
        for radical, rotulo in TIPOS_PROJETO.items():
            if re.search(r"projeto[^.]{0,40}\b" + radical, escopo) or \
               re.search(radical + r"\w*\s+d[ao]\s+produ", escopo):
                d["tipo_projeto"] = rotulo
                break

    # Empresa. Duas redacoes convivem na serie:
    #   2016-2021: "da empresa X (CNPJ: ... e Inscricao SUFRAMA: ...)"
    #   2025-2026: "da empresa X, inscrita no CNPJ sob o no ..."
    # O "(?!empresa)" impede que a captura comece na ementa do inicio do
    # ato e engula o preambulo inteiro.
    SEM_EMPRESA = r"(?:(?!\bempres(?:[aá]ri[ao]|a)\b).)+?"
    for padrao in (
        # formato antigo: nome termina no parentese do CNPJ
        r"d[ao]\s+empresa\s+(" + SEM_EMPRESA + r")\s*\(\s*(?:CNPJ|Inscri)",
        # "da empresa X, CNPJ Nº 11.425.472/0001-02"
        r"d[ao]\s+empresa\s+(" + SEM_EMPRESA + r"),\s*CNPJ",
        # "da empresa, AUTCOM ENGENHARIA LTDA, na Zona Franca"
        r"d[ao]\s+empresa,?\s+(" + SEM_EMPRESA +
        r"),?\s*n[ao]\s+Zona\s+Franca",
        r"em\s+nome\s+d[ao]\s+empresa\s+(" + SEM_EMPRESA +
        r"),?\s*com\s+Inscri[çc][ãa]o",
        # formato atual
        r"empres(?:[aá]ri[ao]|a)\s+(" + SEM_EMPRESA +
        r"),?\s*inscrita\s+no\s+CNPJ",
        r"empres(?:[aá]ri[ao]|a)\s+(" + SEM_EMPRESA +
        r"),?\s*(?:estabelecida|inscrit)",
        # projeto agropecuario: pessoa fisica, nao empresa
        r"de\s+interesse\s+d[eo]\s+(.{4,80}?)\s*\(\s*CPF",
        r"d[ao]\s+empresa\s+([A-ZÀ-Ý][^.;]{3,90}?)(?:,\s*inscrit|\.\s|;)",
    ):
        m = re.search(padrao, texto, re.I)
        if m:
            cand = re.sub(r"\s+", " ", m.group(1)).strip(" ,.(")
            if 3 < len(cand) < 120:
                d["empresa"] = cand
                break

    m = re.search(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", texto)
    if m:
        d["cnpj"] = m.group(0)

    # Inscricao SUFRAMA: "sob o no X" (atual) ou "Inscricao SUFRAMA: X"
    for padrao in (
        r"Inscri[çc][ãa]o\s+SUFRAMA:?\s*n?[º°.\s]*([\d.\-]{6,20})",
        r"SUFRAMA\s+sob\s+o\s+n[º°.\s]*([\d.\-/]{6,20})",
    ):
        m = re.search(padrao, texto, re.I)
        if m:
            d["inscricao_suframa"] = m.group(1).strip(" .")
            break

    # Codigo do produto: "codigo SUFRAMA 1306" ou "Cod. Suframa 0399"
    m = re.search(r"\(?\s*c[óo]d(?:igo|\.)?\s*SUFRAMA\s*n?[º°.:\s]*(\d{3,4})",
                  texto, re.I)
    if m:
        d["codigo_produto"] = m.group(1).zfill(4)

    # Tipo de projeto. Na redacao antiga vem como "projeto industrial de
    # IMPLANTACAO"; na atual, "do tipo diversificacao".
    escopo = sem_acento(extrair_ementa(texto) + " " + texto[:1500]).lower()
    m = re.search(r"projeto\s+(?:industrial|agropecuario|t[eé]cnico)"
                  r"[\w\s-]{0,20}?\s+de\s+([a-z]{5,18})(?:\s*/\s*[a-z]+)?",
                  escopo)
    if not m:
        m = re.search(r"do\s+tipo\s+([a-z\s/-]{4,30}?)\s*[,.]", escopo)
    if m:
        bruto = m.group(1).strip()
        for radical, rotulo in TIPOS_PROJETO.items():
            if radical in bruto:
                d["tipo_projeto"] = rotulo
                break
    if not d["tipo_projeto"]:
        for radical, rotulo in TIPOS_PROJETO.items():
            if re.search(r"projeto[^.]{0,40}\b" + radical, escopo):
                d["tipo_projeto"] = rotulo
                break

    # Produto: varias redacoes, todas fechando em ", codigo SUFRAMA"
    LIXO = re.compile(r"Art\.\s*\d|Fica(?:m)?\s+aprovad|Parecer|"
                      r"Resolu[çc][ãa]o|N[º°o]\s*\d+\s*[-–]", re.I)
    for padrao in (
        # 2018: "para producao de X (Codigo SUFRAMA: 0665)"
        r"produ[çc][ãa]o\s+d[eo]\s+(.+?)\s*\(\s*c[óo]d\w*\s+SUFRAMA",
        r"Zona\s+Franca\s+de\s+Manaus,?\s*d[eo]\s+(.+?),\s*c[óo]d\w*\s+SUFRAMA",
        r"produ[çc][ãa]o\s+d[eo]\s+(.+?),\s*c[óo]d\w*\s+SUFRAMA",
        r"fabrica[çc][ãa]o\s+d[eo]\s+(.+?)[,(]\s*c[óo]d\w*\s+SUFRAMA",
        r"produto\s+(.+?)\s*[-–]\s*C[óo]d\.?\s*Suframa",
        r"[,;]\s*d[eo]\s+([^,;]{4,160}?),\s*c[óo]d\w*\s+SUFRAMA",
    ):
        m = re.search(padrao, texto, re.I)
        if not m:
            continue
        cand = re.sub(r"\s+", " ", m.group(1)).strip(" ,.")
        if LIXO.search(cand) or len(cand) > 170:
            continue
        d["produto"] = cand
        break

    m = re.search(r"processo\s+administrativo\s+n[º°.\s]*([\d./\-]+)", texto, re.I)
    if m:
        d["processo"] = m.group(1).strip(" .")

    # Cancelamentos costumam citar a empresa sem a formula "inscrita no CNPJ"
    if not d["empresa"]:
        m = re.search(r"d[ao]\s+empresa\s+([A-ZÀ-Ý][A-ZÀ-Ý0-9\s.,&\-/]{4,70}?)"
                      r"(?:,\s*em\s+virtude|,\s*inscrit|\.|;|\s+e\s+d[ao]\s)",
                      texto)
        if m:
            d["empresa"] = re.sub(r"\s+", " ", m.group(1)).strip(" ,.")

    # Atos com anexo trazem a lista de empresas/produtos fora do corpo —
    # o cancelamento em lote e o caso tipico.
    if re.search(r"listad[ao]s?\s+n[oa]\s+anexo|\bconstantes?\s+d[oa]\s+anexo|"
                 r"\bANEXO\b", texto, re.I):
        d["tem_anexo"] = "SIM"

    d["ato_de_projeto"] = "SIM" if eh_ato_de_projeto(texto) else "NAO"
    return d


# Separadores de item dentro de um ato coletivo, em ordem de confianca.
# Os atos "RESOLUCOES CAS-SUFRAMA" numeram cada resolucao como
# "Nº 488 - Art. 1º Fica aprovado, com base no Parecer...", e esse rotulo
# e o corte natural entre um projeto e o seguinte.
SEPARADORES = [
    r"\bN[º°o]\s*\.?\s*\d{1,5}\s*[-–—]\s*Art\.\s*1",
    r"\bRESOLU[ÇC][ÃA]O\s+N[º°o]?\s*\.?\s*[\d.]+",
    r"\bPORTARIA\s+SUFRAMA\s+N[º°o]?\s*\.?\s*[\d.]+",
    r"\bArt\.\s*1[º°o]\s+Fica(?:m)?\s+aprovad",
]


def dividir_blocos(texto: str) -> list:
    """Divide um ato coletivo em blocos, um por projeto.

    Usa o rotulo que numera cada item; so recorre a ancora do codigo do
    produto se nenhum separador aparecer, porque cortar pelo codigo deixa
    a descricao do produto no bloco errado.
    """
    for sep in SEPARADORES:
        marcas = list(re.finditer(sep, texto, re.I))
        if len(marcas) >= 2:
            blocos = []
            for i, m in enumerate(marcas):
                fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
                blocos.append(texto[m.start():fim])
            return blocos

    # Sem rotulo de item: corta na ancora do codigo, incluindo o texto
    # anterior, onde fica a descricao do produto.
    marcas = list(re.finditer(r"c[óo]digo\s+SUFRAMA\s*n?[º°.\s]*\d{3,4}",
                              texto, re.I))
    if len(marcas) <= 1:
        return [texto]
    blocos, ini = [], 0
    for m in marcas:
        blocos.append(texto[ini:min(len(texto), m.end() + 250)])
        ini = m.end()
    return blocos


def extrair_anexo_cancelamento(texto: str) -> list:
    """Extrai empresa e produtos dos anexos de cancelamento automatico.

    As portarias de cancelamento em lote (arts. 46 e 47 da Resolucao
    204/2019) nao citam empresas no corpo: publicam a relacao em anexo,
    que vem embutido no texto no formato

        ANEXO I - ... Inscricao SUFRAMA: 200104080
        Razao Social: ARRIS INDUSTRIA ELETRONICA DO BRASIL LTDA.
        Codigo Produto Nro.Doc. Tipo Doc. Data Doc. Tipo Projeto
        1311 MODULADOR/DEMODULADOR PARA COMUNICACAO DE DADOS ...

    Sem isso, um unico ato que cancela dezenas de produtos vira um
    registro vazio.
    """
    cabecalhos = list(re.finditer(
        r"Inscri[çc][ãa]o\s+SUFRAMA:?\s*([\d.\-]{6,20})\s*"
        r"Raz[ãa]o\s+Social:?\s*(.+?)\s*C[óo]digo\s+Produto",
        texto, re.I))
    if not cabecalhos:
        return []

    # Motivo do cancelamento, quando o anexo o identifica
    def motivo(trecho):
        if re.search(r"Art\.?\s*n?[º°]?\s*46", trecho, re.I):
            return "art. 46 - LP nao emitido em 36 meses"
        if re.search(r"Art\.?\s*n?[º°]?\s*47", trecho, re.I):
            return "art. 47 - producao paralisada 36 meses"
        return ""

    registros = []
    for i, cab in enumerate(cabecalhos):
        inscricao = cab.group(1).strip(" .")
        empresa = re.sub(r"\s+", " ", cab.group(2)).strip(" ,.")
        ini = cab.end()
        fim = (cabecalhos[i + 1].start() if i + 1 < len(cabecalhos)
               else len(texto))
        bloco = texto[ini:fim]

        # Contexto anterior indica em qual anexo (art. 46 ou 47) o bloco esta
        contexto = texto[max(0, cab.start() - 400):cab.start()]
        mot = motivo(contexto) or motivo(bloco[:200])

        # Linhas do anexo, no formato:
        #   codigo | descricao | Nro.Doc | Tipo Doc | Data | Tipo Projeto
        # A ancora e a DATA, nao o primeiro digito: nomes de produto contem
        # numeros ("MOTONETA ACIMA DE 100 CM3 ATE 450 CM3") e cortar no
        # primeiro digito truncaria a descricao.
        linhas = list(re.finditer(
            r"(?<![/\d])\b(\d{4})\s+(.+?)\s+(\d{1,7})\s+([A-Z]{2,5})\s+"
            r"(\d{2}/\d{2}/\d{4})", bloco))

        if not linhas:
            # Anexo sem a coluna de data: volta ao corte conservador
            linhas = list(re.finditer(
                r"(?<![/\d])\b(\d{4})\s+([A-ZÀ-Ý][^\d]{4,120}?)\s+(?=\d)",
                bloco))

        TIPOS = ("DIVERSIFICACAO", "IMPLANTACAO", "AMPLIACAO", "ATUALIZACAO",
                 "MODERNIZACAO", "ADAPTACAO", "SUBSTITUICAO")
        for lin in linhas:
            desc = re.sub(r"\s+", " ", lin.group(2)).strip(" ,.-")
            primeira = sem_acento(desc).upper().split(" ")[0]
            if primeira in TIPOS or desc.upper().startswith("ANEXO"):
                continue
            reg = {
                "empresa": empresa,
                "inscricao_suframa": inscricao,
                "codigo_produto": lin.group(1).zfill(4),
                "produto": desc,
                "tipo_projeto": "",
                "processo": "",
                "motivo": mot,
            }
            if lin.lastindex and lin.lastindex >= 5:
                reg["data_documento"] = lin.group(5)
                reg["tipo_documento"] = lin.group(4)
            registros.append(reg)

    return registros


def extrair_multiplos(texto: str) -> list:
    """Um registro por projeto, com o texto do proprio bloco em cada um."""
    # Cancelamento em lote: a informacao esta no anexo, nao no corpo
    anexo = extrair_anexo_cancelamento(texto)
    if anexo:
        base = extrair_campos(texto)
        saida = []
        for reg in anexo:
            d = dict(base)
            d.update({k: v for k, v in reg.items() if k != "motivo"})
            d["texto_item"] = (f"{reg['empresa']} | {reg['codigo_produto']} | "
                               f"{reg['produto']} | {reg.get('motivo', '')}")
            d["tem_anexo"] = "SIM"
            saida.append(d)
        return saida

    blocos = dividir_blocos(texto)
    if len(blocos) <= 1:
        d = extrair_campos(texto)
        d["texto_item"] = texto
        return [d]

    registros, vistos = [], set()
    for bloco in blocos:
        d = extrair_campos(bloco)
        if not d.get("codigo_produto"):
            continue
        chave = (d.get("empresa", ""), d.get("codigo_produto", ""))
        if chave in vistos:
            continue
        vistos.add(chave)
        d["texto_item"] = bloco
        registros.append(d)

    if not registros:
        d = extrair_campos(texto)
        d["texto_item"] = texto
        return [d]
    return registros


def processar_item(item: dict, session: requests.Session) -> dict:
    """Baixa o ato completo e monta a linha de saida."""
    slug = item.get("urlTitle", "")
    url = ATO_URL.format(slug=slug)
    titulo = limpar(item.get("title", ""))

    linha = {c: "" for c in COLUNAS}
    linha.update({
        "data_publicacao": item.get("pubDate", ""),
        "tipo_ato": item.get("artType", ""),
        "titulo": titulo,
        "secao": item.get("pubName", ""),
        "pagina": item.get("numberPage", ""),
        "hierarquia": limpar(item.get("hierarchyStr", "")),
        "url": url,
    })

    m = re.search(r"n[º°.\s]*([\d.]+)", titulo)
    if m:
        linha["numero_ato"] = m.group(1).strip(".")

    html = baixar(url, session)
    if not html:
        linha["classificacao"] = "nao baixado"
        linha["item"] = "1/1"
        return [linha]

    soup = BeautifulSoup(html, "lxml")
    corpo = soup.select_one(".texto-dou") or soup.find("article") or soup.body
    texto = limpar(corpo.get_text(" ") if corpo else "")

    linha["texto"] = texto
    linha["classificacao"] = classificar(texto)

    registros = extrair_multiplos(texto)
    linhas = []
    for k, campos in enumerate(registros, 1):
        nova = dict(linha)
        for campo, valor in campos.items():
            if valor:
                nova[campo] = valor
        nova["item"] = f"{k}/{len(registros)}"
        linhas.append(nova)
    return linhas


# ---------------------------------------------------------------------------
# Consolidacao
# ---------------------------------------------------------------------------
def consolidar():
    import pandas as pd

    if not ARQ_PARCIAL.exists():
        print("  Nada a consolidar.")
        return

    df = pd.read_csv(ARQ_PARCIAL, dtype=str).fillna("")
    df = df[df["url"] != "url"]
    df = df.drop_duplicates(subset=["url", "codigo_produto", "empresa"])

    # Ordena da publicacao mais recente para a mais antiga
    df["_ord"] = pd.to_datetime(df["data_publicacao"], format="%d/%m/%Y",
                                errors="coerce")
    df = df.sort_values("_ord", ascending=False).drop(columns=["_ord"])

    df.to_csv(ARQ_CSV, index=False, encoding="utf-8")
    df.to_parquet(ARQ_PARQUET, index=False)

    import shutil
    shutil.copy2(ARQ_PARQUET, Path("dou_suframa.parquet"))

    print("\n  --- Consolidacao ---")
    print(f"  Registros:       {len(df)}  (atos distintos: {df['url'].nunique()})")
    print(f"  Com empresa:     {(df['empresa'] != '').sum()}")
    print(f"  Com cod.produto: {(df['codigo_produto'] != '').sum()}")
    print("  Por classificacao:")
    for k, v in df["classificacao"].value_counts().items():
        print(f"     {k:22s} {v}")
    print(f"  Parquet: {ARQ_PARQUET}  (copia na raiz)")


# ---------------------------------------------------------------------------
# Principal
# ---------------------------------------------------------------------------
def coletar(d1: date, d2: date, pausa: float, reiniciar: bool):
    PASTA_DADOS.mkdir(exist_ok=True)
    if reiniciar and ARQ_PARCIAL.exists():
        ARQ_PARCIAL.unlink()

    ja_tem = set()
    if ARQ_PARCIAL.exists():
        with open(ARQ_PARCIAL, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                ja_tem.add(row.get("url", ""))
        print(f"  Cache: {len(ja_tem)} atos ja coletados")

    session = requests.Session()

    print(f"\n  Buscando atos de {d1:%d/%m/%Y} a {d2:%d/%m/%Y}...\n")
    brutos = coletar_janela(d1, d2, session)

    vistos, fila = set(), []
    for it in brutos:
        slug = it.get("urlTitle", "")
        if not slug or slug in vistos:
            continue
        vistos.add(slug)
        if interessa(it):
            fila.append(it)

    print(f"\n  {len(brutos)} resultados brutos -> {len(vistos)} unicos "
          f"-> {len(fila)} da SUFRAMA (portarias/resolucoes)")

    pendentes = [i for i in fila
                 if ATO_URL.format(slug=i["urlTitle"]) not in ja_tem]
    print(f"  A baixar agora: {len(pendentes)}\n")

    if not pendentes:
        consolidar()
        return

    novo = not ARQ_PARCIAL.exists() or ARQ_PARCIAL.stat().st_size == 0
    with open(ARQ_PARCIAL, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS, extrasaction="ignore")
        if novo:
            w.writeheader()

        for i, item in enumerate(pendentes, 1):
            print(f"  [{i}/{len(pendentes)}]", end=" ", flush=True)
            linhas = processar_item(item, session)
            for linha in linhas:
                w.writerow(linha)
            f.flush()
            p0 = linhas[0]
            emp = (p0["empresa"] or "-")[:38]
            cod = p0["codigo_produto"] or "----"
            extra = f" (+{len(linhas)-1} projetos)" if len(linhas) > 1 else ""
            print(f"{p0['data_publicacao']} | {p0['classificacao']:18s} "
                  f"| {cod} | {emp}{extra}")
            if i < len(pendentes):
                time.sleep(pausa)

    consolidar()


def reprocessar():
    """Reclassifica e reextrai a partir dos textos ja salvos no parcial.

    Como o texto integral de cada ato fica gravado, corrigir uma regra nao
    exige baixar nada de novo. Atos coletivos sao reexpandidos aqui: as
    linhas sao reconstruidas a partir do texto, e nao das linhas antigas.
    """
    import pandas as pd

    if not ARQ_PARCIAL.exists():
        print("  Nao ha parcial para reprocessar.")
        return

    df = pd.read_csv(ARQ_PARCIAL, dtype=str).fillna("")
    df = df[df["url"] != "url"]
    for c in COLUNAS:
        if c not in df.columns:
            df[c] = ""

    antes_linhas = len(df)
    antes = df["classificacao"].value_counts().to_dict()
    print(f"  Reprocessando {df['url'].nunique()} atos ja baixados (sem rede)...")

    # Campos que descrevem o ato (nao o projeto dentro dele)
    do_ato = ["data_publicacao", "tipo_ato", "numero_ato", "titulo",
              "secao", "pagina", "hierarquia", "url", "texto"]

    novas = []
    coletivos = 0
    for url, grupo in df.groupby("url", sort=False):
        r0 = grupo.iloc[0]
        texto = r0.get("texto", "")
        base = {c: r0.get(c, "") for c in do_ato}

        if not texto:
            linha = {c: r0.get(c, "") for c in COLUNAS}
            novas.append(linha)
            continue

        cls = classificar(texto)
        registros = extrair_multiplos(texto)
        if len(registros) > 1:
            coletivos += 1
        for k, campos in enumerate(registros, 1):
            linha = {c: "" for c in COLUNAS}
            linha.update(base)
            linha["classificacao"] = cls
            for campo, valor in campos.items():
                if valor:
                    linha[campo] = valor
            linha["item"] = f"{k}/{len(registros)}"
            novas.append(linha)

    novo_df = pd.DataFrame(novas, columns=COLUNAS).fillna("")
    novo_df.to_csv(ARQ_PARCIAL, index=False, encoding="utf-8")

    print(f"\n  Atos coletivos desmembrados: {coletivos}")
    print(f"  Linhas: {antes_linhas} -> {len(novo_df)}")
    print("\n  Classificacao, antes -> depois:")
    depois = novo_df["classificacao"].value_counts().to_dict()
    for k in sorted(set(antes) | set(depois)):
        print(f"     {k:26s} {antes.get(k, 0):>4d} -> {depois.get(k, 0):>4d}")
    consolidar()


def testar_url(url: str):
    """Mostra o que a extracao consegue tirar de um ato especifico."""
    session = requests.Session()
    html = baixar(url, session)
    if not html:
        print("Nao foi possivel baixar.")
        return
    soup = BeautifulSoup(html, "lxml")
    corpo = soup.select_one(".texto-dou") or soup.body
    texto = limpar(corpo.get_text(" "))
    print(f"\nTAMANHO DO TEXTO: {len(texto)}")
    print(f"CLASSIFICACAO: {classificar(texto)}\n")
    for k, v in extrair_campos(texto).items():
        if v:
            print(f"  {k:20s} = {v}")
    print(f"\n--- inicio do texto ---\n{texto[:600]}")


def main():
    p = argparse.ArgumentParser(description="Coletor DOU - atos da SUFRAMA")
    p.add_argument("--de", default="2025-01-01", help="data inicial AAAA-MM-DD")
    p.add_argument("--ate", default=None, help="data final AAAA-MM-DD (padrao: hoje)")
    p.add_argument("--pausa", type=float, default=1.0)
    p.add_argument("--reiniciar", action="store_true")
    p.add_argument("--teste-url", default=None, help="testa a extracao de um ato")
    p.add_argument("--reprocessar", action="store_true",
                   help="reclassifica os atos ja baixados, sem acessar a rede")
    a = p.parse_args()

    print("=" * 64)
    print("  COLETOR DOU - Portarias e Resolucoes da SUFRAMA")
    print("=" * 64)

    if a.teste_url:
        testar_url(a.teste_url)
        return

    if a.reprocessar:
        reprocessar()
        return

    try:
        d1 = datetime.strptime(a.de, "%Y-%m-%d").date()
        d2 = (datetime.strptime(a.ate, "%Y-%m-%d").date() if a.ate
              else date.today())
    except ValueError:
        print("ERRO: datas devem estar no formato AAAA-MM-DD")
        sys.exit(1)

    coletar(d1, d2, a.pausa, a.reiniciar)


if __name__ == "__main__":
    main()
