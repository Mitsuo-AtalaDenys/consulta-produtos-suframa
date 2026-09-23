#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auditoria_dou.py
================
Verifica se TODOS os projetos aprovados foram capturados, procurando os
tres tipos de falha possiveis:

  1. SUB-EXTRACAO — o ato foi baixado, mas dele saiu menos projeto do que
     o texto contem. E a falha mais perigosa, porque nao aparece em
     nenhuma contagem: o ato esta la, so que incompleto. A checagem conta
     quantas vezes o texto diz "APROVAR o projeto" e compara com quantos
     registros aquele ato gerou.

  2. EXTRACAO INCOMPLETA — o projeto existe como registro, mas sem
     empresa ou sem codigo de produto, o que o torna inutil na consulta.

  3. CLASSIFICACAO ERRADA — o ato aprova projeto mas caiu em outra
     classe (tipicamente "outro"), ficando escondido no dashboard.

Com --online, tambem confere contra o proprio DOU se algum ato do periodo
nao chegou a ser baixado.

Gera dados/auditoria_dou.xlsx com uma aba por tipo de falha.

Uso:
  python auditoria_dou.py
  python auditoria_dou.py --online
"""

import argparse
import json
import re
import time
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

PASTA = Path("dados")
SAIDA = PASTA / "auditoria_dou.xlsx"

# Formulas que indicam aprovacao de projeto, em todas as redacoes vistas
# na serie 2016-2026.
PADRAO_APROVA = re.compile(
    r"APROVAR\s+o\s+[Pp]rojeto|Fica(?:m)?\s+aprovad[oa]s?\s+o?s?\s*[Pp]rojeto|"
    r"Aprova\s+o\s+projeto|APROVAR,\s+com\s+base",
    re.I)

PADRAO_CODIGO = re.compile(
    r"\(?\s*c[óo]d(?:igo|\.)?\s*SUFRAMA\s*n?[º°.:\s]*\d{3,4}", re.I)


def sem_acento(t):
    t = unicodedata.normalize("NFKD", str(t))
    return "".join(c for c in t if not unicodedata.combining(c))


def carregar():
    for p in [Path("dou_suframa.parquet"), PASTA / "dou_suframa.parquet"]:
        if p.exists():
            return pd.read_parquet(p).fillna("")
    raise SystemExit("dou_suframa.parquet nao encontrado")


# ---------------------------------------------------------------------------
# Conferencia online (opcional)
# ---------------------------------------------------------------------------
def varrer_dou(d1, d2):
    """Repete a busca no DOU para descobrir atos que nao foram baixados."""
    import requests
    import urllib3
    from bs4 import BeautifulSoup
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    BUSCA = "https://www.in.gov.br/consulta/-/buscar/dou"
    SID = "_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params"
    HD = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"}
    ses = requests.Session()

    def uma(a, b):
        par = {"q": "suframa", "s": "todos", "exactDate": "personalizado",
               "publishFrom": a.strftime("%d-%m-%Y"),
               "publishTo": b.strftime("%d-%m-%Y"),
               "sortType": "0", "delta": "20"}
        try:
            r = ses.get(BUSCA, params=par, headers=HD, timeout=60, verify=False)
            if r.status_code != 200:
                return []
            tag = BeautifulSoup(r.text, "lxml").find("script", id=SID)
            if not tag:
                return []
            return json.loads(tag.string or tag.text).get("jsonArray", []) or []
        except Exception:
            return []

    def varrer(a, b, prof=0):
        itens = uma(a, b)
        if len(itens) < 20 or a == b:
            return itens
        meio = a + (b - a) / 2
        time.sleep(0.4)
        return (varrer(a, meio, prof + 1)
                + varrer(meio + timedelta(days=1), b, prof + 1))

    print(f"  Varrendo o DOU de {d1:%d/%m/%Y} a {d2:%d/%m/%Y}...")
    brutos = varrer(d1, d2)

    vistos, saida = set(), []
    for it in brutos:
        slug = it.get("urlTitle", "")
        if not slug or slug in vistos:
            continue
        vistos.add(slug)
        hier = sem_acento(it.get("hierarchyStr", "")).lower()
        tipo = sem_acento(it.get("artType", "")).lower()
        if "zona franca de manaus" not in hier:
            continue
        if not any(t in tipo for t in ("portaria", "resolucao")):
            continue
        saida.append({
            "data": it.get("pubDate", ""),
            "titulo": re.sub(r"<[^>]*>", "", str(it.get("title", ""))),
            "url": "https://www.in.gov.br/web/dou/-/" + slug,
        })
    return saida


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--online", action="store_true",
                    help="confere tambem contra o DOU (demora)")
    a = ap.parse_args()

    df = carregar()
    df["_dt"] = pd.to_datetime(df["data_publicacao"], format="%d/%m/%Y",
                               errors="coerce")

    print("=" * 76)
    print(f"  AUDITORIA — {len(df)} registros / {df['url'].nunique()} atos")
    print("=" * 76)

    abas = {}

    # --- 1. Sub-extracao: ato com mais aprovacoes no texto que registros ---
    print("\n  [1] Sub-extracao (ato incompleto)")
    linhas = []
    for url, g in df.groupby("url"):
        texto = g.iloc[0].get("texto", "")
        if not texto:
            continue
        no_texto = len(PADRAO_APROVA.findall(texto))
        codigos = len(PADRAO_CODIGO.findall(texto))
        esperado = max(no_texto, codigos)
        extraidos = len(g[g["codigo_produto"] != ""])
        if esperado > extraidos:
            linhas.append({
                "data": g.iloc[0]["data_publicacao"],
                "titulo": g.iloc[0]["titulo"][:90],
                "aprovacoes_no_texto": no_texto,
                "codigos_no_texto": codigos,
                "registros_extraidos": extraidos,
                "faltando": esperado - extraidos,
                "url": url,
            })
    linhas.sort(key=lambda x: -x["faltando"])
    abas["1-subextracao"] = pd.DataFrame(linhas)
    total_perdido = sum(x["faltando"] for x in linhas)
    print(f"      {len(linhas)} atos com projeto faltando "
          f"({total_perdido} projetos no total)")
    for x in linhas[:8]:
        print(f"        [{x['data']}] faltam {x['faltando']:>3d} | "
              f"{x['titulo'][:56]}")

    # --- 2. Extracao incompleta ---
    print("\n  [2] Registros de aprovacao incompletos")
    apr = df[df["classificacao"] == "aprovacao"]
    inc = apr[(apr["empresa"] == "") | (apr["codigo_produto"] == "")]
    abas["2-incompletos"] = inc[["data_publicacao", "item", "empresa",
                                 "codigo_produto", "produto", "titulo",
                                 "url"]].copy()
    print(f"      {len(inc)} de {len(apr)} aprovacoes sem empresa ou sem codigo")
    print(f"        sem empresa: {(apr['empresa'] == '').sum()}")
    print(f"        sem codigo : {(apr['codigo_produto'] == '').sum()}")

    # --- 3. Classificacao errada ---
    print("\n  [3] Atos que aprovam projeto mas nao estao como aprovacao")
    outros = df[df["classificacao"] != "aprovacao"]
    susp = outros[outros["texto"].map(
        lambda t: bool(PADRAO_APROVA.search(str(t)))
        and bool(PADRAO_CODIGO.search(str(t))))]
    susp = susp.drop_duplicates(subset=["url"])
    abas["3-classificacao"] = susp[["data_publicacao", "classificacao",
                                    "empresa", "codigo_produto", "titulo",
                                    "url"]].copy()
    print(f"      {len(susp)} atos suspeitos")
    for _, r in susp.head(8).iterrows():
        print(f"        [{r['data_publicacao']}] {r['classificacao']:14s} | "
              f"{r['titulo'][:50]}")

    # --- 4. Conferencia online ---
    if a.online and df["_dt"].notna().any():
        print("\n  [4] Atos do DOU que nao estao na base")
        d1, d2 = df["_dt"].min().date(), df["_dt"].max().date()
        no_dou = varrer_dou(d1, d2)
        tenho = set(df["url"])
        faltam = [x for x in no_dou if x["url"] not in tenho]
        abas["4-nao-baixados"] = pd.DataFrame(faltam)
        print(f"      DOU: {len(no_dou)} atos | na base: "
              f"{len(no_dou) - len(faltam)} | faltando: {len(faltam)}")
        for x in faltam[:10]:
            print(f"        [{x['data']}] {x['titulo'][:60]}")
    else:
        abas["4-nao-baixados"] = pd.DataFrame(
            [{"aviso": "rode com --online para esta conferencia"}])

    PASTA.mkdir(exist_ok=True)
    with pd.ExcelWriter(SAIDA) as w:
        for nome, tabela in abas.items():
            if tabela.empty:
                tabela = pd.DataFrame([{"resultado": "nenhuma ocorrencia"}])
            tabela.to_excel(w, sheet_name=nome[:31], index=False)
    print(f"\n  Planilha: {SAIDA}")

    print("\n" + "=" * 76)
    print("  VEREDITO")
    print("=" * 76)
    if not linhas and inc.empty and susp.empty:
        print("  Nenhuma falha encontrada nas tres verificacoes offline.")
    else:
        print(f"  Projetos possivelmente perdidos por sub-extracao: {total_perdido}")
        print(f"  Aprovacoes incompletas:                           {len(inc)}")
        print(f"  Atos possivelmente mal classificados:             {len(susp)}")
        print("\n  Abra a planilha e confira alguns casos no DOU pelo link.")
        print("  Se confirmarem falha, me envie a aba correspondente.")


if __name__ == "__main__":
    main()
