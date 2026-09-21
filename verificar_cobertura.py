#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verificar_cobertura.py
======================
Confere se a coleta do DOU pegou atos da SUFRAMA sob TODOS os ministerios
que ja abrigaram a autarquia, e nao apenas o atual.

Ao longo dos governos a SUFRAMA passou por pastas de nomes diferentes. O
coletor nao filtra por ministerio de proposito — ele peneira pela
hierarquia da autarquia, que e estavel. Este script comprova isso indo ao
DOU, consultando cada ministerio separadamente, e comparando os numeros
com o que ja foi coletado.

Uso:
  python verificar_cobertura.py
  python verificar_cobertura.py --de 2025-01-01 --ate 2026-09-18
"""

import argparse
import json
import re
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BUSCA = "https://www.in.gov.br/consulta/-/buscar/dou"
SCRIPT_ID = "_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params"
HEADERS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36")}

# Pastas que ja abrigaram a SUFRAMA (as tres que o portal oferece hoje)
MINISTERIOS = [
    "Ministério da Economia",
    "Ministério da Indústria, Comércio Exterior e Serviços",
    "Ministério do Desenvolvimento, Indústria, Comércio e Serviços",
]


def sem_acento(t):
    t = unicodedata.normalize("NFKD", str(t))
    return "".join(c for c in t if not unicodedata.combining(c))


def buscar(d1, d2, session):
    """Uma janela de datas, sem filtro de orgao. Devolve os itens."""
    params = {
        "q": "suframa", "s": "todos", "exactDate": "personalizado",
        "publishFrom": d1.strftime("%d-%m-%Y"),
        "publishTo": d2.strftime("%d-%m-%Y"),
        "sortType": "0", "delta": "20",
    }
    try:
        r = session.get(BUSCA, params=params, headers=HEADERS,
                        timeout=60, verify=False)
        if r.status_code != 200:
            return []
        tag = BeautifulSoup(r.text, "lxml").find("script", id=SCRIPT_ID)
        if not tag:
            return []
        return json.loads(tag.string or tag.text).get("jsonArray", []) or []
    except Exception:
        return []


def varrer(d1, d2, session, prof=0):
    itens = buscar(d1, d2, session)
    if len(itens) < 20 or d1 == d2:
        return itens
    meio = d1 + (d2 - d1) / 2
    return (varrer(d1, meio, session, prof + 1)
            + varrer(meio + timedelta(days=1), d2, session, prof + 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--de", default="2025-01-01")
    ap.add_argument("--ate", default=None)
    a = ap.parse_args()

    d1 = datetime.strptime(a.de, "%Y-%m-%d").date()
    d2 = (datetime.strptime(a.ate, "%Y-%m-%d").date() if a.ate else date.today())

    print("=" * 76)
    print("  VERIFICACAO DE COBERTURA POR MINISTERIO")
    print(f"  Periodo: {d1:%d/%m/%Y} a {d2:%d/%m/%Y}")
    print("=" * 76)

    session = requests.Session()
    print("\n  Varrendo o DOU (sem filtro de orgao)...")
    itens = varrer(d1, d2, session)

    vistos, suframa = set(), []
    for it in itens:
        slug = it.get("urlTitle", "")
        if not slug or slug in vistos:
            continue
        vistos.add(slug)
        if "zona franca de manaus" in sem_acento(it.get("hierarchyStr", "")).lower():
            suframa.append(it)

    print(f"  {len(itens)} resultados brutos -> {len(vistos)} unicos "
          f"-> {len(suframa)} da SUFRAMA")

    print("\n" + "=" * 76)
    print("  ATOS DA SUFRAMA ENCONTRADOS, POR MINISTERIO")
    print("=" * 76)
    contagem = {}
    for it in suframa:
        h = it.get("hierarchyStr", "")
        pasta = h.split("/")[0].strip() if "/" in h else h.strip()
        contagem[pasta] = contagem.get(pasta, 0) + 1
    for pasta, qtd in sorted(contagem.items(), key=lambda x: -x[1]):
        print(f"  {qtd:>5d}  {pasta}")

    print("\n  Ministerios conhecidos e se aparecem no periodo:")
    for m in MINISTERIOS:
        achou = any(sem_acento(m).lower() in sem_acento(p).lower()
                    for p in contagem)
        print(f"    [{'x' if achou else ' '}] {m}")
    print("\n  (Ministerios sem marca simplesmente nao abrigavam a SUFRAMA")
    print("   neste periodo — o que e esperado, nao e falha de coleta.)")

    # Compara com o que ja foi coletado
    alvo = None
    for nome in ("dou_suframa.parquet", "dados/dou_suframa.parquet"):
        if Path(nome).is_file():
            alvo = pd.read_parquet(nome).fillna("")
            break

    if alvo is None:
        print("\n  (dou_suframa.parquet nao encontrado — pulando comparacao)")
        return

    print("\n" + "=" * 76)
    print("  COMPARACAO COM A BASE JA COLETADA")
    print("=" * 76)

    tipos_ok = {"portaria", "resolucao"}
    esperados = {
        "https://www.in.gov.br/web/dou/-/" + it["urlTitle"]
        for it in suframa
        if any(t in sem_acento(it.get("artType", "")).lower() for t in tipos_ok)
    }
    tenho = set(alvo["url"])

    faltando = esperados - tenho
    print(f"  Portarias/Resolucoes da SUFRAMA no DOU: {len(esperados)}")
    print(f"  Na base coletada:                       {len(tenho & esperados)}")
    print(f"  Faltando:                               {len(faltando)}")

    if faltando:
        print("\n  Ate 10 que faltam:")
        for u in list(faltando)[:10]:
            print(f"    {u}")
    else:
        print("\n  Cobertura completa: nenhum ato de fora.")

    if "hierarquia" in alvo.columns and (alvo["hierarquia"] != "").any():
        print("\n  Hierarquias gravadas na base:")
        for h, q in alvo["hierarquia"].value_counts().head(8).items():
            print(f"    {q:>5d}  {h[:66]}")
    else:
        print("\n  A base atual nao tem a coluna 'hierarquia' (foi coletada")
        print("  antes desta versao). Ela sera preenchida na proxima coleta.")


if __name__ == "__main__":
    main()
