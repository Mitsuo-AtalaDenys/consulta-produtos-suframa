#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
coletar_silt.py
===============
Coleta os Decretos Concessivos publicados no SILT (Sistema Integrado de
Legislacao Tributaria do Amazonas / SEFAZ-AM) e extrai os dados dos
incentivos fiscais concedidos pelo Estado via SEDECTI/CODAM.

COMO FUNCIONA
-------------
O SILT nao tem API, mas a busca e um POST simples para /silt/q/ e devolve
TODOS os registros do periodo num unico HTML, sem paginacao de servidor
(a tabela pagina no navegador). Isso torna a coleta da listagem trivial:
um POST por faixa de anos.

Depois, cada decreto e aberto individualmente para extrair empresa, CNPJ,
CCA, produto, NCMs e percentual de credito estimulo.

USO
---
  python coletar_silt.py                    # 2025 ate o ano corrente
  python coletar_silt.py --de 2023 --ate 2026
  python coletar_silt.py --teste-url <url>  # testa a extracao de um decreto
  python coletar_silt.py --reiniciar        # ignora o cache e recomeca
  python coletar_silt.py --reprocessar      # reclassifica/reextrai sem rede,
                                             # usando o texto ja salvo no
                                             # cache (dados/_parcial_silt.csv)

Requer: requests, beautifulsoup4, lxml, pandas, pyarrow
"""

import argparse
import csv
import re
import time
import unicodedata
from datetime import date
from pathlib import Path
import sys

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
csv.field_size_limit(sys.maxsize)
# ---------------------------------------------------------------------------
# Configuracao
# ---------------------------------------------------------------------------
BASE = "https://sistemas.sefaz.am.gov.br"
BUSCA_URL = f"{BASE}/silt/q/"
TIPO_NORMA = "DECRETO_CONCESSIVO"

PASTA_DADOS = Path("dados")
ARQ_PARCIAL = PASTA_DADOS / "_parcial_silt.csv"
ARQ_CSV = PASTA_DADOS / "silt_decretos.csv"
ARQ_PARQUET = PASTA_DADOS / "silt_decretos.parquet"

COLUNAS = [
    "numero_decreto", "data_decreto", "data_publicacao_doe", "classificacao",
    "empresa", "cnpj", "cca", "endereco", "produto", "ncms",
    "credito_estimulo", "enquadramento", "codam_reuniao", "resolucao_codam",
    "proposicao_sedecti", "parecer", "url", "texto",
]

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36"),
    "Accept-Language": "pt-BR,pt;q=0.9",
}

MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5,
    "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10,
    "novembro": 11, "dezembro": 12,
}

# ---------------------------------------------------------------------------
# Utilitarios
# ---------------------------------------------------------------------------
def sem_acento(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t))
    return "".join(c for c in t if not unicodedata.combining(c))


def limpar(t: str) -> str:
    return re.sub(r"\s+", " ", str(t).replace("\xa0", " ")).strip()


def pedir(url, session, metodo="get", data=None, tentativas=4):
    for t in range(tentativas):
        try:
            if metodo == "post":
                r = session.post(url, data=data, headers=HEADERS,
                                 timeout=90, verify=False)
            else:
                r = session.get(url, headers=HEADERS, timeout=90, verify=False)
            if r.status_code == 200:
                r.encoding = r.apparent_encoding or "utf-8"
                return r.text
            print(f"[HTTP {r.status_code}]", end=" ", flush=True)
        except requests.RequestException:
            print(f"[rede {t+1}/{tentativas}]", end=" ", flush=True)
        if t < tentativas - 1:
            time.sleep(3 * (t + 1))
    return None

def url_norma(url):
    m = re.search(r"/silt/norma/decreto-concessivo/([^/]+)", url)
    if m:
        return f"{BASE}/get/Normas.do?metodo=viewDoc&uuidDoc={m.group(1)}"
    return url

# ---------------------------------------------------------------------------
# Listagem
# ---------------------------------------------------------------------------
def listar_decretos(ano_de: int, ano_ate: int, session: requests.Session):
    """POST na busca do SILT. Devolve [(numero, titulo, url), ...]."""
    dados = {
        "texto": "",
        "tipoNorma": TIPO_NORMA,
        "de": str(ano_de),
        "ate": str(ano_ate),
        "referenda": "",
    }
    html = pedir(BUSCA_URL, session, metodo="post", data=dados)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")

    texto = soup.get_text(" ")
    m = re.search(r"encontrados?\s+([\d.]+)\s+registros", texto, re.I)
    if m:
        print(f"  O SILT informa {m.group(1)} registros no periodo")

    achados, vistos = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/silt/norma/decreto-concessivo/" not in href:
            continue
        rotulo = limpar(a.get_text(" "))
        if not re.search(r"DECRETO", rotulo, re.I):
            continue
        url = href if href.startswith("http") else BASE + href
        if url in vistos:
            continue
        vistos.add(url)
        num = ""
        mm = re.search(r"DECRETO\s+N[º°.\s]*([\d.]+)", rotulo, re.I)
        if mm:
            num = mm.group(1).strip(".")
        achados.append((num, rotulo, url))
    return achados


# ---------------------------------------------------------------------------
# Extracao
# ---------------------------------------------------------------------------
def extrair_ementa(texto: str) -> str:
    """Isola a ementa do decreto.

    Classificar pelo texto inteiro nao funciona: decretos de concessao
    trazem clausulas padrao de cancelamento e suspensao dos incentivos,
    o que jogaria toda concessao no balde errado. A ementa fica entre o
    cabecalho e o preambulo ("O GOVERNADOR DO ESTADO...").
    """
    corte = re.split(r"\bO\s+GOVERNADOR\b|\bCONSIDERANDO\b|\bDECRETA\b|\bArt\.\s*1",
                     texto, maxsplit=1, flags=re.I)[0]
    corte = re.sub(r"^.*?Poder\s+Executivo[^A-Z]*", "", corte, flags=re.I | re.S)
    corte = re.sub(r"^.*?\bDE\s+\d{1,2}[º°o]?\s+DE\s+[A-Za-zÀ-ÿ]+\s+DE\s+\d{4}\s*",
                   "", corte, flags=re.I | re.S)
    return limpar(corte)[:300]


REGRAS = [
    (r"torna(?:r|ndo)?\s+sem\s+efeito", "tornado sem efeito"),
    (r"\bcancel", "cancelamento"),
    (r"\brevog", "revogacao"),
    (r"\bsuspend|\bsuspens", "suspensao"),
    (r"\bprorrog", "prorrogacao"),
    (r"\baltera|\bretific", "alteracao"),
    (r"\bconced", "concessao"),
    (r"\baprov", "aprovacao"),
]


def classificar(texto: str) -> str:
    ementa = sem_acento(extrair_ementa(texto)).lower()
    if len(ementa) > 8:
        for padrao, rotulo in REGRAS:
            if re.search(padrao, ementa):
                return rotulo

    m = re.search(r"Art\.\s*1[º°o]?\s*(.{0,180})", texto, re.I | re.S)
    if m:
        disp = sem_acento(m.group(1)).lower()
        for padrao, rotulo in REGRAS:
            if re.search(padrao, disp):
                return rotulo

    ini = sem_acento(texto[:300]).lower()
    for padrao, rotulo in REGRAS:
        if re.search(padrao, ini):
            return rotulo
    return "outro"


def data_por_extenso(txt: str) -> str:
    """'10 DE SETEMBRO DE 2026' -> '10/09/2026'."""
    m = re.search(r"(\d{1,2})\s+DE\s+([A-ZÇÃÉa-zçãé]+)\s+DE\s+(\d{4})", txt, re.I)
    if not m:
        return ""
    mes = MESES.get(sem_acento(m.group(2)).lower())
    if not mes:
        return ""
    return f"{int(m.group(1)):02d}/{mes:02d}/{m.group(3)}"


# --- Produto / NCM ---------------------------------------------------------
# Padrao de codigo NCM: "1234.56.78" ou, sem pontuacao, 8 digitos seguidos.
NCM_COD_RE = re.compile(r"\d{4}\.\d{2}\.\d{2}|\d{8}")

# Marcador de item em lista numerada: "I -", "II.", "III –", etc.
MARCADOR_RE = re.compile(r"[IVXLCDM]{1,6}\s*[-–.)]\s*")


def extrair_produto_ncm(texto: str):
    """Extrai produto(s) e NCM/SH do texto do decreto.

    Cobre dois formatos que aparecem no SILT:

    1) Produto unico:
       "...fabricacao do produto BISCOITO, NCM/SH: 1905.31.00..."

    2) Lista numerada de produtos, cada um com seu proprio NCM/SH:
       "...fabricacao dos produtos a seguir relacionados: I - CIMENTO
        NCM/SH: 2523.29.10 II - ARGAMASSA NCM/SH: 3214.10.10..."

    Retorna (produto, ncms) ja formatados para as colunas do CSV:
    produtos separados por " | " quando ha mais de um, NCMs unicos
    (sem repeticao) separados por ", ".
    """
    m_ini = re.search(r"fabrica[çc][ăãa]o\s+d[eo]s?\s+produtos?\b", texto, re.I)

    if not m_ini:
        return "", ""

    trecho = texto[m_ini.end():]

    # limite logico do trecho de produtos: para antes do proximo assunto
    # do decreto (enquadramento, resolucao do CODAM, etc.)
    m_fim = re.search(
        r"\bResolu[çc][ãa]o\s+n[.º°\s]*[\d./-]+\s*-?\s*CODAM"
        r"|\bcr[ée]dito\s+est[íi]mulo\b",
        trecho, re.I,
    )
    if m_fim:
        trecho = trecho[:m_fim.start()]

    itens = MARCADOR_RE.split(trecho)
    marcadores = MARCADOR_RE.findall(trecho)

    produtos, ncms_todos = [], []

    if marcadores:
        # itens[0] e o texto antes do primeiro "I -" (normalmente so
        # "a seguir relacionados:"), descartar; os itens seguintes
        # correspondem 1-a-1 com os marcadores encontrados.
        partes = itens[1:]
        for parte in partes:
            mm = re.search(r"NCM/?\s*SH:?\s*(.+)$", parte, re.I)
            if not mm:
                continue
            nome = limpar(parte[:mm.start()]).strip(" ,.:;-")
            codigos = NCM_COD_RE.findall(mm.group(1))
            if nome:
                produtos.append(nome)
            ncms_todos.extend(codigos)
    else:
        # produto unico, sem marcador de lista
        mm = re.search(r"NCM/?\s*SH:?\s*(.+)$", trecho, re.I)
        if mm:
            nome = limpar(trecho[:mm.start()]).strip(" ,.:;-")
            codigos = NCM_COD_RE.findall(mm.group(1))
            if nome:
                produtos.append(nome)
            ncms_todos.extend(codigos)
    ncms_unicos = list(dict.fromkeys(ncms_todos))
    return " | ".join(produtos), ", ".join(ncms_unicos)


def extrair_campos(texto: str) -> dict:
    d = {c: "" for c in COLUNAS}

    m = re.search(r"DECRETO\s+N[º°.\s]*([\d.]+)", texto, re.I)
    if m:
        d["numero_decreto"] = m.group(1).strip(".")

    d["data_decreto"] = data_por_extenso(texto[:200])

    m = re.search(r"Publicado\s+no\s+DOE\s+de\s+(\d{2}/\d{2}/\d{4})", texto, re.I)
    if m:
        d["data_publicacao_doe"] = m.group(1)

    # Empresa
    # Para de capturar tanto em "estabelecida" quanto em "inscrita", pois
    # alguns decretos vao direto para "inscrita no CNPJ" sem o trecho
    # "estabelecida em ...".
    m = re.search(
        r"empres[aá]ria\s+((?:(?!empres[aá]ria|estabelecida|inscrita).)+?)"
        r"\s*,?\s*(?:estabelecida|inscrita)",
        texto, re.I,
    )
    if not m:
        # fallback: "a empresa NOME, estabelecida/inscrita..."
        m = re.search(
            r"\bempresa\s+((?:(?!estabelecida|inscrita).)+?)"
            r"\s*,?\s*(?:estabelecida|inscrita)",
            texto, re.I,
        )
    if not m:
        m = re.search(r"empres[aá]ria\s+([A-ZÀ-Ý][^.]{3,90}?)\.", texto)
    if m:
        d["empresa"] = limpar(m.group(1)).strip(" ,.")

    m = re.search(r"estabelecida\s+n[ao]\s+(.+?),?\s*inscrita\s+no\s+CNPJ",
                  texto, re.I)
    if m:
        d["endereco"] = limpar(m.group(1)).strip(" ,.")

    # CNPJ
    # Tolerante a espacos extras ao redor da pontuacao, que podem surgir
    # quando o numero vem quebrado por tags no HTML original.
    m = re.search(
        r"\d{2}\s*\.\s*\d{3}\s*\.\s*\d{3}\s*/\s*\d{4}\s*-\s*\d{2}", texto
    )
    if m:
        d["cnpj"] = re.sub(r"\s+", "", m.group(0))

    m = re.search(r"CCA\s+sob\s+o\s+n[.º°\s]*([\d.\-]+)", texto, re.I)
    if m:
        d["cca"] = m.group(1).strip(" .")

    # Produto e NCM/SH (produto unico ou lista numerada I, II, III...)
    produto, ncms = extrair_produto_ncm(texto)
    d["produto"] = produto
    d["ncms"] = ncms

    # Credito estimulo do ICMS: sem informacao segura de formato ainda,
    # deixado em branco por enquanto (nao extrair).
    d["credito_estimulo"] = ""

    m = re.search(r"enquadrado\s+como\s+(.+?),?\s*conforme", texto, re.I)
    if m:
        d["enquadramento"] = limpar(m.group(1)).strip(" ,.")

    m = re.search(r"(\d+)[ªa]\s+reuni[ãa]o", texto, re.I)
    if m:
        d["codam_reuniao"] = m.group(1) + "ª"

    m = re.search(r"Resolu[çc][ãa]o\s+n[.º°\s]*([\d./-]+)\s*-?\s*CODAM",
                  texto, re.I)
    if m:
        d["resolucao_codam"] = m.group(1).strip(" .-/")

    m = re.search(r"Proposi[çc][ãa]o\s+n[.º°\s]*([\d./-]+)", texto, re.I)
    if m:
        d["proposicao_sedecti"] = m.group(1).strip(" .-/")

    m = re.search(r"Parecer\s+de\s+An[áa]lise[^n]*n[.º°\s]*([\d./-]+)", texto, re.I)
    if m:
        d["parecer"] = m.group(1).strip(" .-/")
    return d


def processar(num, rotulo, url, session):
    linha = {c: "" for c in COLUNAS}
    linha["numero_decreto"] = num
    linha["url"] = url

    url_documento = url_norma(url)
    html = pedir(url_documento, session)
    if not html:
        linha["classificacao"] = "nao baixado"
        return linha

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    texto = limpar(soup.get_text(" "))

    i = texto.upper().find("DECRETO N")
    if i > 0:
        texto = texto[i:]

    linha["texto"] = texto
    linha["classificacao"] = classificar(texto)
    for k, v in extrair_campos(texto).items():
        if v and not linha.get(k):
            linha[k] = v
    if not linha["data_decreto"]:
        linha["data_decreto"] = data_por_extenso(rotulo)
    return linha


# ---------------------------------------------------------------------------
# Consolidacao
# ---------------------------------------------------------------------------
def consolidar():
    import pandas as pd

    if not ARQ_PARCIAL.exists():
        print("  Nada a consolidar.")
        return

    df = pd.read_csv(ARQ_PARCIAL, dtype=str).fillna("")
    df = df[df["url"] != "url"].drop_duplicates(subset=["url"])

    df["_ord"] = pd.to_datetime(df["data_decreto"], format="%d/%m/%Y",
                                errors="coerce")
    df = df.sort_values("_ord", ascending=False).drop(columns=["_ord"])

    df.to_csv(ARQ_CSV, index=False, encoding="utf-8")
    df.to_parquet(ARQ_PARQUET, index=False)

    import shutil
    shutil.copy2(ARQ_PARQUET, Path("silt_decretos.parquet"))

    print("\n  --- Consolidacao ---")
    print(f"  Decretos:      {len(df)}")
    print(f"  Com empresa:   {(df['empresa'] != '').sum()}")
    print(f"  Com CNPJ:      {(df['cnpj'] != '').sum()}")
    print(f"  Com produto:   {(df['produto'] != '').sum()}")
    print(f"  Com NCM:       {(df['ncms'] != '').sum()}")
    print("  Por classificacao:")
    for k, v in df["classificacao"].value_counts().items():
        print(f"     {k:18s} {v}")
    print(f"  Parquet: {ARQ_PARQUET}  (copia na raiz)")


# ---------------------------------------------------------------------------
# Principal
# ---------------------------------------------------------------------------
def coletar(ano_de, ano_ate, pausa, reiniciar):
    PASTA_DADOS.mkdir(exist_ok=True)
    if reiniciar and ARQ_PARCIAL.exists():
        ARQ_PARCIAL.unlink()

    ja_tem = set()
    if ARQ_PARCIAL.exists():
        with open(ARQ_PARCIAL, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                ja_tem.add(row.get("url", ""))
        print(f"  Cache: {len(ja_tem)} decretos ja coletados")

    session = requests.Session()
    session.get(f"{BASE}/silt/", headers=HEADERS, timeout=60, verify=False)

    print(f"\n  Listando decretos concessivos de {ano_de} a {ano_ate}...")
    lista = listar_decretos(ano_de, ano_ate, session)
    print(f"  {len(lista)} decretos na listagem")

    pendentes = [x for x in lista if x[2] not in ja_tem]
    print(f"  A baixar agora: {len(pendentes)}\n")
    if not pendentes:
        consolidar()
        return

    novo = not ARQ_PARCIAL.exists() or ARQ_PARCIAL.stat().st_size == 0
    with open(ARQ_PARCIAL, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS, extrasaction="ignore")
        if novo:
            w.writeheader()

        for i, (num, rotulo, url) in enumerate(pendentes, 1):
            print(f"  [{i}/{len(pendentes)}]", end=" ", flush=True)
            linha = processar(num, rotulo, url, session)
            w.writerow(linha)
            f.flush()
            emp = (linha["empresa"] or "-")[:40]
            print(f"Dec. {linha['numero_decreto']:>8s} | "
                  f"{linha['classificacao']:12s} | {emp}")
            if i < len(pendentes):
                time.sleep(pausa)

    consolidar()


def reprocessar():
    """Reclassifica a partir dos textos ja salvos, sem acessar a rede."""
    import pandas as pd
    if not ARQ_PARCIAL.exists():
        print("  Nao ha parcial para reprocessar.")
        return
    df = pd.read_csv(ARQ_PARCIAL, dtype=str).fillna("")
    df = df[df["url"] != "url"]
    print(f"  Reprocessando {len(df)} decretos ja baixados (sem rede)...")
    antes = df["classificacao"].value_counts().to_dict()
    for i, row in df.iterrows():
        texto = row.get("texto", "")
        if not texto:
            continue
        df.at[i, "classificacao"] = classificar(texto)
        for k, v in extrair_campos(texto).items():
            if k == "credito_estimulo":
                continue  # mantido em branco de proposito
            if v:
                df.at[i, k] = v
    df.to_csv(ARQ_PARCIAL, index=False, encoding="utf-8")
    depois = df["classificacao"].value_counts().to_dict()
    print("\n  Antes -> depois:")
    for k in sorted(set(antes) | set(depois)):
        print(f"     {k:20s} {antes.get(k,0):>4d} -> {depois.get(k,0):>4d}")
    consolidar()


def testar_url(url):
    session = requests.Session()
    session.get(f"{BASE}/silt/", headers=HEADERS, timeout=60, verify=False)
    url_documento = url_norma(url)
    html = pedir(url_documento, session)
    if not html:
        print("Nao foi possivel baixar.")
        return
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    texto = limpar(soup.get_text(" "))
    i = texto.upper().find("DECRETO N")
    if i > 0:
        texto = texto[i:]
    print(f"\nTAMANHO: {len(texto)}")
    print(f"CLASSIFICACAO: {classificar(texto)}\n")
    for k, v in extrair_campos(texto).items():
        if v:
            print(f"  {k:22s} = {v[:90]}")
    print(f"\n--- inicio do texto ---\n{texto[:700]}")


def main():
    p = argparse.ArgumentParser(description="Coletor SILT - decretos concessivos")
    p.add_argument("--de", type=int, default=2025)
    p.add_argument("--ate", type=int, default=date.today().year)
    p.add_argument("--pausa", type=float, default=1.0)
    p.add_argument("--reiniciar", action="store_true")
    p.add_argument("--teste-url", default=None)
    p.add_argument("--reprocessar", action="store_true",
                   help="reclassifica os decretos ja baixados, sem rede")
    a = p.parse_args()

    print("=" * 64)
    print("  COLETOR SILT - Decretos Concessivos (SEFAZ-AM)")
    print("=" * 64)

    if a.teste_url:
        testar_url(a.teste_url)
        return
    if a.reprocessar:
        reprocessar()
        return
    coletar(a.de, a.ate, a.pausa, a.reiniciar)


if __name__ == "__main__":
    main()