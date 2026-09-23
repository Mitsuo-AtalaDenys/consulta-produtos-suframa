#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sonda_legado4.py
================
Teste decisivo do acervo antigo: o que existe atras dos links de resultado?

A busca em pesquisa.in.gov.br devolve links para PAGINAS do jornal, no
formato visualiza/index.jsp?jornal=1&pagina=30&data=31/12/2012 — nao para
o ato individual. Falta saber o que ha nessa pagina:

  - PDF com camada de texto  -> extracao confiavel, sem OCR. O coletor
    seria viavel com a mesma qualidade da serie moderna.
  - PDF so com imagem        -> exigiria OCR, com risco em CNPJ, inscricao
    e codigo de produto, que sao justamente campos numericos.

Tambem conta corretamente quantos resultados a busca devolveu (a sonda
anterior confundiu o ano 1990 da lista com a contagem).

Uso:
  python sonda_legado4.py --ano 2012
  python sonda_legado4.py --ano 2012 --de 01/03 --ate 31/03
"""

import argparse
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE = "https://pesquisa.in.gov.br"
START = f"{BASE}/imprensa/core/start.action"
HD = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/120.0.0.0 Safari/537.36"),
      "Accept-Language": "pt-BR,pt;q=0.9"}

PASTA = Path("dados")
PASTA.mkdir(exist_ok=True)

ap = argparse.ArgumentParser()
ap.add_argument("--termo", default="Zona Franca de Manaus")
ap.add_argument("--ano", default="2012")
ap.add_argument("--de", default="01/03")
ap.add_argument("--ate", default="31/03")
a = ap.parse_args()

ses = requests.Session()
r = ses.get(START, headers=HD, timeout=60, verify=False)
soup = BeautifulSoup(r.text, "lxml")
form = next(f for f in soup.find_all("form")
            if "consulta.action" in str(f.get("action", "")))
acao = urljoin(BASE, form.get("action"))

payload, grupos = [], {}
for el in form.find_all(["input", "select", "textarea"]):
    nome = el.get("name")
    if not nome:
        continue
    tipo = (el.get("type") or el.name).lower()
    if tipo in ("submit", "button", "image"):
        continue
    if tipo == "checkbox":
        v = el.get("value", "")
        if v[:1] in ("1", "2", "3") and "," in v:
            grupos.setdefault(v[:1], v)
        if el.has_attr("checked"):
            payload.append((nome, v))
    elif tipo == "radio":
        if el.has_attr("checked"):
            payload.append((nome, el.get("value", "")))
    elif el.name == "select":
        ops = el.find_all("option")
        s = next((o for o in ops if o.has_attr("selected")), ops[0] if ops else None)
        payload.append((nome, s.get("value", "") if s is not None else ""))
    else:
        payload.append((nome, el.get("value", "")))

if "1" in grupos:
    payload.append(("edicao.jornal", grupos["1"]))

def por(suf, novo):
    for i, (n, v) in enumerate(payload):
        if n.lower().endswith(suf.lower()):
            payload[i] = (n, novo)

por("txtPesquisa", a.termo)
por("dtInicio", a.de)
por("dtFim", a.ate)
por("ano", a.ano)

hd = dict(HD); hd["Referer"] = START
r2 = ses.post(acao, data=payload, headers=hd, timeout=90, verify=False)

print("=" * 76)
print(f"  BUSCA: '{a.termo}' — {a.de} a {a.ate} de {a.ano}")
print("=" * 76)
print(f"  HTTP {r2.status_code} | {len(r2.text)} bytes")

s2 = BeautifulSoup(r2.text, "lxml")

# Contagem real: procura no trecho DEPOIS do formulario, para nao pegar
# os anos da lista de opcoes
corpo = re.sub(r"\s+", " ", s2.get_text(" "))
depois = corpo.split("Selecionar")[-1] if "Selecionar" in corpo else corpo
m = re.search(r"(?:foram\s+encontrad\w+\s+)?([\d.]+)\s+(?:de\s+)?"
              r"(?:resultado|ocorr|registro|mat[ée]ria)", depois, re.I)
print(f"  contagem: {m.group(0).strip() if m else 'nao detectada'}")

links = [x.get("href") for x in s2.find_all("a", href=True)
         if "visualiza" in str(x.get("href"))]
vistos, paginas = set(), []
for h in links:
    if h not in vistos:
        vistos.add(h)
        paginas.append(h)
print(f"  paginas de jornal distintas nesta pagina de resultados: {len(paginas)}")

if not paginas:
    raise SystemExit("\n  Nenhum link de pagina — nada a testar.")

alvo = urljoin(f"{BASE}/imprensa/jsp/", paginas[0].replace("../jsp/", ""))
print(f"\n  Testando: {alvo}")

print("\n" + "=" * 76)
print("  O QUE HA NA PAGINA DO JORNAL")
print("=" * 76)

r3 = ses.get(alvo, headers=hd, timeout=90, verify=False)
print(f"  HTTP {r3.status_code} | {len(r3.text)} bytes | "
      f"tipo: {r3.headers.get('Content-Type', '?')}")
(PASTA / "legado_visualiza.html").write_text(r3.text, encoding="utf-8",
                                             errors="ignore")

s3 = BeautifulSoup(r3.text, "lxml")
todos = [x.get("href") or x.get("src") for x in s3.find_all(["a", "iframe",
                                                             "embed", "img"])]
pdfs = [u for u in todos if u and ".pdf" in str(u).lower()]
print(f"  links/embeds com .pdf: {len(pdfs)}")
for u in pdfs[:5]:
    print(f"    {str(u)[:100]}")

txt3 = re.sub(r"\s+", " ", s3.get_text(" ")).strip()
print(f"  texto na propria pagina: {len(txt3)} caracteres")
if len(txt3) > 80:
    print(f"    {txt3[:220]}")

# --- Se achou PDF, baixa e testa camada de texto ------------------------
if pdfs:
    url_pdf = urljoin(alvo, pdfs[0])
    print(f"\n  Baixando o PDF: {url_pdf[:100]}")
    try:
        rp = ses.get(url_pdf, headers=hd, timeout=120, verify=False)
        dest = PASTA / "legado_pagina.pdf"
        dest.write_bytes(rp.content)
        print(f"  HTTP {rp.status_code} | {len(rp.content)} bytes | salvo em {dest}")

        eh_pdf = rp.content[:4] == b"%PDF"
        print(f"  e PDF valido: {eh_pdf}")

        if eh_pdf:
            try:
                from pypdf import PdfReader
            except ImportError:
                try:
                    from PyPDF2 import PdfReader
                except ImportError:
                    PdfReader = None
            if PdfReader is None:
                print("\n  Para testar a camada de texto, instale:")
                print("     pip install pypdf")
                print("  e rode esta sonda de novo.")
            else:
                leitor = PdfReader(str(dest))
                paginas_pdf = len(leitor.pages)
                texto = (leitor.pages[0].extract_text() or "").strip()
                print(f"  paginas no PDF: {paginas_pdf}")
                print(f"  texto extraido da 1a pagina: {len(texto)} caracteres")
                if len(texto) > 200:
                    print("\n  >>> TEM CAMADA DE TEXTO — nao precisa de OCR <<<")
                    print(f"\n  Amostra:\n    {texto[:400]}")
                    if re.search(r"suframa|zona franca", texto, re.I):
                        print("\n  E contem mencao a SUFRAMA/Zona Franca.")
                else:
                    print("\n  >>> SEM camada de texto — pagina digitalizada,")
                    print("      exigiria OCR <<<")
    except requests.RequestException as e:
        print(f"  ERRO ao baixar: {e}")
else:
    print("\n  Nenhum PDF encontrado. O visualizador pode montar a pagina")
    print("  por JavaScript — nesse caso me envie dados/legado_visualiza.html")
