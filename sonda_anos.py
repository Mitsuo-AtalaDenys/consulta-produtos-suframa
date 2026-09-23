#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sonda_anos.py
=============
Descobre ate onde o portal moderno do DOU (in.gov.br) enxerga atos da
SUFRAMA, e se esses atos trazem texto aproveitavel ou apenas imagem
digitalizada. Isso decide a estrategia para o periodo 2008-2021.

Gera dados/sonda_cobertura_dou.xlsx com uma linha por ano.

ATENCAO: este arquivo deve ser SALVO em disco e executado. Colar o
conteudo dele no PowerShell nao funciona — o PowerShell tentaria executar
cada linha de Python como se fosse um comando dele.

  python sonda_anos.py
  python sonda_anos.py --de 2008 --ate 2021 --mes 3
"""

import argparse
import json
import re
import time
import unicodedata
from datetime import date
from pathlib import Path

import pandas as pd
import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BUSCA = "https://www.in.gov.br/consulta/-/buscar/dou"
ATO = "https://www.in.gov.br/web/dou/-/{slug}"
SCRIPT_ID = "_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params"
HEADERS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36"),
           "Accept-Language": "pt-BR,pt;q=0.9"}

# O tutorial da SUFRAMA sugere "Zona Franca de Manaus"; o coletor atual usa
# "suframa". Em atos antigos a redacao pode favorecer um ou outro, entao a
# sonda mede os dois.
TERMOS = {"suframa": "suframa",
          "zona_franca": '"Zona Franca de Manaus"'}

PASTA = Path("dados")
SAIDA = PASTA / "sonda_cobertura_dou.xlsx"


def sem_acento(t):
    t = unicodedata.normalize("NFKD", str(t))
    return "".join(c for c in t if not unicodedata.combining(c))


def buscar(termo, d1, d2, session):
    params = {"q": termo, "s": "todos", "exactDate": "personalizado",
              "publishFrom": d1.strftime("%d-%m-%Y"),
              "publishTo": d2.strftime("%d-%m-%Y"),
              "sortType": "0", "delta": "20"}
    try:
        r = session.get(BUSCA, params=params, headers=HEADERS,
                        timeout=60, verify=False)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        soup = BeautifulSoup(r.text, "lxml")
        total = ""
        m = re.search(r"([\d.]+)\s+resultados?", soup.get_text(" "))
        if m:
            total = m.group(1)
        tag = soup.find("script", id=SCRIPT_ID)
        if not tag:
            return [], total
        return json.loads(tag.string or tag.text).get("jsonArray", []) or [], total
    except requests.RequestException as e:
        return None, str(e)[:40]


def texto_do_ato(slug, session):
    """Tamanho do texto extraido da pagina do ato.

    0 significa que a pagina existe mas nao tem corpo de texto — indicio de
    que o conteudo daquele periodo esta apenas no jornal digitalizado.
    """
    try:
        r = session.get(ATO.format(slug=slug), headers=HEADERS,
                        timeout=60, verify=False)
        if r.status_code != 200:
            return -1
        soup = BeautifulSoup(r.text, "lxml")
        corpo = soup.select_one(".texto-dou") or soup.find("article")
        if not corpo:
            return 0
        return len(re.sub(r"\s+", " ", corpo.get_text(" ")).strip())
    except requests.RequestException:
        return -1


def ultimo_dia(ano, mes):
    if mes == 2:
        return 29 if (ano % 4 == 0 and (ano % 100 != 0 or ano % 400 == 0)) else 28
    return 31 if mes in (1, 3, 5, 7, 8, 10, 12) else 30


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--de", type=int, default=2008)
    ap.add_argument("--ate", type=int, default=2021)
    ap.add_argument("--mes", type=int, default=3)
    a = ap.parse_args()

    print("=" * 76)
    print("  SONDA DE COBERTURA HISTORICA DO DOU")
    print(f"  Amostra: mes {a.mes:02d} de cada ano, {a.de} a {a.ate}")
    print("=" * 76)
    print()
    print(f"  {'ano':>5s} | {'suframa':>14s} | {'zona franca':>14s} | "
          f"{'situacao':>24s}")
    print("  " + "-" * 70)

    session = requests.Session()
    linhas = []

    for ano in range(a.de, a.ate + 1):
        d1 = date(ano, a.mes, 1)
        d2 = date(ano, a.mes, ultimo_dia(ano, a.mes))

        reg = {"ano": ano}
        slug = None

        for rotulo, termo in TERMOS.items():
            itens, total = buscar(termo, d1, d2, session)
            if itens is None:
                reg[f"{rotulo}_suframa"] = None
                reg[f"{rotulo}_total"] = None
                reg[f"{rotulo}_erro"] = total
                continue
            da_suframa = [it for it in itens
                          if "zona franca de manaus" in
                          sem_acento(it.get("hierarchyStr", "")).lower()]
            reg[f"{rotulo}_suframa"] = len(da_suframa)
            reg[f"{rotulo}_total"] = len(itens)
            reg[f"{rotulo}_erro"] = ""
            if da_suframa and not slug:
                slug = da_suframa[0].get("urlTitle")
            time.sleep(0.6)

        if slug:
            n = texto_do_ato(slug, session)
            reg["texto_caracteres"] = n if n >= 0 else None
            reg["url_exemplo"] = ATO.format(slug=slug)
            if n > 400:
                reg["situacao"] = "texto disponivel"
            elif n == 0:
                reg["situacao"] = "sem texto (digitalizado)"
            elif n < 0:
                reg["situacao"] = "falha ao abrir"
            else:
                reg["situacao"] = "texto muito curto"
        else:
            reg["texto_caracteres"] = None
            reg["url_exemplo"] = ""
            reg["situacao"] = "nenhum ato da SUFRAMA"

        s1, t1 = reg.get("suframa_suframa"), reg.get("suframa_total")
        s2, t2 = reg.get("zona_franca_suframa"), reg.get("zona_franca_total")
        print(f"  {ano:>5d} | "
              f"{(f'{s1} de {t1}' if s1 is not None else 'ERRO'):>14s} | "
              f"{(f'{s2} de {t2}' if s2 is not None else 'ERRO'):>14s} | "
              f"{reg['situacao']:>24s}")
        linhas.append(reg)
        time.sleep(0.4)

    df = pd.DataFrame(linhas)
    colunas = ["ano", "suframa_suframa", "suframa_total",
               "zona_franca_suframa", "zona_franca_total",
               "texto_caracteres", "situacao", "url_exemplo",
               "suframa_erro", "zona_franca_erro"]
    df = df[[c for c in colunas if c in df.columns]]
    df = df.rename(columns={
        "ano": "Ano",
        "suframa_suframa": "Atos SUFRAMA (termo suframa)",
        "suframa_total": "Resultados totais (termo suframa)",
        "zona_franca_suframa": "Atos SUFRAMA (termo zona franca)",
        "zona_franca_total": "Resultados totais (termo zona franca)",
        "texto_caracteres": "Texto do 1o ato (caracteres)",
        "situacao": "Situacao",
        "url_exemplo": "URL de exemplo",
        "suframa_erro": "Erro (suframa)",
        "zona_franca_erro": "Erro (zona franca)",
    })

    PASTA.mkdir(exist_ok=True)
    df.to_excel(SAIDA, index=False, sheet_name="Cobertura DOU")
    print(f"\n  Planilha gerada: {SAIDA}")

    print("\n" + "=" * 76)
    print("  LEITURA DO RESULTADO")
    print("=" * 76)

    com_texto = [r for r in linhas if r["situacao"] == "texto disponivel"]
    sem_texto = [r for r in linhas if r["situacao"] == "sem texto (digitalizado)"]
    vazios = [r for r in linhas if r["situacao"] == "nenhum ato da SUFRAMA"]

    if com_texto:
        anos = [r["ano"] for r in com_texto]
        print(f"  Anos com TEXTO aproveitavel: {min(anos)} a {max(anos)}")
        print("  -> Nesses, basta rodar o coletor com as datas:")
        print(f"     python coletar_dou.py --de {min(anos)}-01-01 "
              f"--ate {max(anos)}-12-31")
    else:
        print("  Nenhum ano trouxe texto aproveitavel.")

    if sem_texto:
        print(f"\n  Anos digitalizados (exigiriam OCR): "
              f"{sorted(r['ano'] for r in sem_texto)}")
    if vazios:
        print(f"\n  Anos sem nenhum ato da SUFRAMA na amostra: "
              f"{sorted(r['ano'] for r in vazios)}")
        print("  Pode ser mes atipico — vale repetir com --mes 6 antes de")
        print("  concluir que o acervo nao cobre o ano.")


if __name__ == "__main__":
    main()
