#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sonda_legado5.py
================
Encontra o endereco real do PDF por tras do visualizador do acervo antigo.

A pagina visualiza/index.jsp tem apenas ~1 KB: e uma casca que carrega o
arquivo de outro lugar. A sonda anterior nao achou nada porque procurava
por ".pdf", e a Imprensa Nacional serve o documento por um servlet, sem
extensao no endereco.

Esta sonda:
  1. Despeja TUDO que existe dentro da casca (links, iframes, scripts).
  2. Testa os endpoints conhecidos do visualizador.
  3. Em qualquer PDF que responder, verifica se ha camada de texto.

Uso:
  python sonda_legado5.py
  python sonda_legado5.py --data 30/03/2012 --pagina 86
"""

import argparse
import re
from pathlib import Path

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE = "https://pesquisa.in.gov.br"
HD = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/120.0.0.0 Safari/537.36"),
      "Accept-Language": "pt-BR,pt;q=0.9"}
PASTA = Path("dados")
PASTA.mkdir(exist_ok=True)

ap = argparse.ArgumentParser()
ap.add_argument("--data", default="30/03/2012")
ap.add_argument("--pagina", default="86")
ap.add_argument("--jornal", default="1")
a = ap.parse_args()

ses = requests.Session()
ses.get(f"{BASE}/imprensa/core/start.action", headers=HD, timeout=60,
        verify=False)

casca = (f"{BASE}/imprensa/jsp/visualiza/index.jsp"
         f"?jornal={a.jornal}&pagina={a.pagina}&data={a.data}")

print("=" * 76)
print("  1. O QUE HA DENTRO DA CASCA DO VISUALIZADOR")
print("=" * 76)
r = ses.get(casca, headers=HD, timeout=60, verify=False)
print(f"  HTTP {r.status_code} | {len(r.text)} bytes\n")
print("  --- conteudo bruto ---")
print("  " + r.text.replace("\n", "\n  ")[:1600])

s = BeautifulSoup(r.text, "lxml")
achados = []
for tag in s.find_all(True):
    for attr in ("href", "src", "data", "value", "action"):
        v = tag.get(attr)
        if v and not v.startswith("#"):
            achados.append(f"{tag.name}[{attr}] = {v}")
for sc in s.find_all("script"):
    for u in re.findall(r"['\"]([^'\"]*(?:servlet|viewer|pdf|jsp)[^'\"]*)['\"]",
                        sc.string or ""):
        achados.append(f"script -> {u}")

print("\n  --- URLs encontradas ---")
for x in dict.fromkeys(achados):
    print(f"    {x[:120]}")
if not achados:
    print("    (nenhuma)")

# ---------------------------------------------------------------------------
print("\n" + "=" * 76)
print("  2. TESTANDO ENDPOINTS CONHECIDOS DO VISUALIZADOR")
print("=" * 76)

candidatos = [
    f"{BASE}/imprensa/servlet/INPDFViewer?jornal={a.jornal}"
    f"&pagina={a.pagina}&data={a.data}&captchafield=firstAccess",
    f"{BASE}/imprensa/servlet/INPDFViewer?jornal={a.jornal}"
    f"&pagina={a.pagina}&data={a.data}&captchafield=itemslist",
    f"{BASE}/imprensa/servlet/INPDFViewer?jornal={a.jornal}"
    f"&pagina={a.pagina}&data={a.data}",
]

hd = dict(HD)
hd["Referer"] = casca
sucesso = None

for url in candidatos:
    try:
        rp = ses.get(url, headers=hd, timeout=120, verify=False)
        tipo = rp.headers.get("Content-Type", "?")
        eh_pdf = rp.content[:4] == b"%PDF"
        print(f"\n  {url.split('servlet/')[-1][:78]}")
        print(f"    HTTP {rp.status_code} | {len(rp.content)} bytes | {tipo}")
        print(f"    e PDF: {eh_pdf}")
        if eh_pdf and not sucesso:
            sucesso = (url, rp.content)
    except requests.RequestException as e:
        print(f"\n  ERRO: {str(e)[:70]}")

# ---------------------------------------------------------------------------
print("\n" + "=" * 76)
print("  3. CAMADA DE TEXTO")
print("=" * 76)

if not sucesso:
    print("  Nenhum endpoint devolveu PDF.")
    print("  Me envie o conteudo bruto impresso no item 1 — a URL real")
    print("  esta nele, e a partir dela eu monto o coletor.")
else:
    url, conteudo = sucesso
    dest = PASTA / "legado_pagina.pdf"
    dest.write_bytes(conteudo)
    print(f"  PDF salvo em {dest} ({len(conteudo)} bytes)")
    try:
        from pypdf import PdfReader
    except ImportError:
        print("  Instale: pip install pypdf")
        raise SystemExit

    leitor = PdfReader(str(dest))
    texto = ""
    for pg in leitor.pages[:2]:
        texto += (pg.extract_text() or "")
    texto = re.sub(r"\s+", " ", texto).strip()
    print(f"  paginas: {len(leitor.pages)} | texto extraido: {len(texto)} chars")

    if len(texto) > 200:
        print("\n  >>> TEM CAMADA DE TEXTO — NAO precisa de OCR <<<")
        print(f"\n  Amostra:\n    {texto[:500]}")
        alvo = re.search(r"[^.]{0,200}(?:SUFRAMA|Zona Franca)[^.]{0,300}",
                         texto, re.I)
        if alvo:
            print(f"\n  Trecho com SUFRAMA:\n    {alvo.group(0)[:450]}")
        else:
            print("\n  (Sem mencao a SUFRAMA nesta pagina especifica —")
            print("   normal, a busca aponta paginas com o termo em qualquer")
            print("   lugar do texto.)")
    else:
        print("\n  >>> SEM camada de texto — pagina digitalizada, exigiria OCR")
