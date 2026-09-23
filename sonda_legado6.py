#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sonda_legado6.py
================
Ultima sonda antes de montar o coletor do acervo antigo. Responde duas
perguntas que decidem o desenho dele:

  1. QUAL TERMO BUSCAR. "Zona Franca de Manaus" traz muito ruido: a pagina
     testada era uma tabela orcamentaria que apenas cita a autarquia.
     Precisamos de um termo que apareca nas portarias de aprovacao e quase
     so nelas.

  2. QUAL A REDACAO DA EPOCA. As regras de extracao que ja temos foram
     escritas para 2016-2026. Em 2012 a formula pode ser outra, e sem ver
     o texto real nao da para escrever as regras certas.

Como funciona: busca cada termo candidato, baixa as primeiras paginas de
jornal encontradas, extrai o texto do PDF e mostra os trechos em que a
SUFRAMA aprova projeto.

Uso:
  python sonda_legado6.py --ano 2012
  python sonda_legado6.py --ano 2010 --paginas 6
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
PDF = (BASE + "/imprensa/servlet/INPDFViewer?jornal={j}&pagina={p}"
              "&data={d}&captchafield=firstAccess")
HD = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/120.0.0.0 Safari/537.36"),
      "Accept-Language": "pt-BR,pt;q=0.9"}
PASTA = Path("dados")
PASTA.mkdir(exist_ok=True)

# Termos candidatos, do mais especifico para o mais amplo
TERMOS = [
    '"Código SUFRAMA"',
    '"projeto técnico-econômico"',
    '"SUFRAMA" "aprovar"',
    'SUFRAMA',
]

ap = argparse.ArgumentParser()
ap.add_argument("--ano", default="2012")
ap.add_argument("--de", default="01/03")
ap.add_argument("--ate", default="31/03")
ap.add_argument("--paginas", type=int, default=4,
                help="quantos PDFs baixar por termo")
a = ap.parse_args()

ses = requests.Session()


def montar_busca(termo):
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
            s = next((o for o in ops if o.has_attr("selected")),
                     ops[0] if ops else None)
            payload.append((nome, s.get("value", "") if s is not None else ""))
        else:
            payload.append((nome, el.get("value", "")))

    if "1" in grupos:
        payload.append(("edicao.jornal", grupos["1"]))

    for i, (n, v) in enumerate(payload):
        ln = n.lower()
        if ln.endswith("txtpesquisa"):
            payload[i] = (n, termo)
        elif ln.endswith("dtinicio"):
            payload[i] = (n, a.de)
        elif ln.endswith("dtfim"):
            payload[i] = (n, a.ate)
        elif ln.endswith("ano"):
            payload[i] = (n, a.ano)

    hd = dict(HD); hd["Referer"] = START
    return ses.post(acao, data=payload, headers=hd, timeout=90, verify=False)


def paginas_do_resultado(html):
    s = BeautifulSoup(html, "lxml")
    achados = []
    for x in s.find_all("a", href=True):
        h = x.get("href")
        m = re.search(r"jornal=(\d+)&pagina=(\d+)&data=([\d/]+)", str(h))
        if m and m.groups() not in [g for g, _ in achados]:
            achados.append((m.groups(), h))
    return [g for g, _ in achados]


def texto_do_pdf(jornal, pagina, data):
    url = PDF.format(j=jornal, p=pagina, d=data)
    hd = dict(HD)
    hd["Referer"] = (f"{BASE}/imprensa/jsp/visualiza/index.jsp"
                     f"?jornal={jornal}&pagina={pagina}&data={data}")
    try:
        r = ses.get(url, headers=hd, timeout=120, verify=False)
        if r.content[:4] != b"%PDF":
            return ""
        dest = PASTA / "_tmp_legado.pdf"
        dest.write_bytes(r.content)
        from pypdf import PdfReader
        leitor = PdfReader(str(dest))
        t = "".join((pg.extract_text() or "") for pg in leitor.pages)
        return re.sub(r"\s+", " ", t)
    except Exception:
        return ""


# Formulas que indicam aprovacao de projeto pela SUFRAMA
MARCAS = re.compile(
    r"(APROVAR\s+o\s+[Pp]rojeto|Fica\s+aprovad|aprova(?:r)?\s+o\s+projeto|"
    r"C[óo]d(?:igo|\.)?\s*SUFRAMA|projeto\s+t[ée]cnico-econ[ôo]mico)", re.I)

print("=" * 78)
print(f"  TESTE DE TERMOS — {a.de} a {a.ate} de {a.ano}")
print("=" * 78)

melhor = None
for termo in TERMOS:
    r = montar_busca(termo)
    pgs = paginas_do_resultado(r.text)
    print(f"\n  termo {termo:32s} -> {len(pgs)} paginas na 1a tela "
          f"(HTTP {r.status_code})")
    if not pgs:
        continue

    acertos = 0
    for jornal, pagina, data in pgs[:a.paginas]:
        t = texto_do_pdf(jornal, pagina, data)
        if not t:
            continue
        if re.search(r"suframa", t, re.I) and MARCAS.search(t):
            acertos += 1
            if melhor is None:
                melhor = (termo, jornal, pagina, data, t)
    print(f"     paginas testadas: {min(a.paginas, len(pgs))} | "
          f"com ato de projeto da SUFRAMA: {acertos}")

print("\n" + "=" * 78)
print("  REDACAO DA EPOCA")
print("=" * 78)

if melhor is None:
    print("  Nenhuma pagina com ato de aprovacao foi encontrada nos termos")
    print("  testados. Tente outro mes ou outro ano:")
    print("     python sonda_legado6.py --ano 2012 --de 01/06 --ate 30/06")
else:
    termo, jornal, pagina, data, t = melhor
    print(f"  Achado com o termo {termo}, pagina {pagina} de {data}\n")
    (PASTA / f"legado_texto_{a.ano}.txt").write_text(t, encoding="utf-8")
    print(f"  Texto completo salvo em dados/legado_texto_{a.ano}.txt\n")

    # Mostra os trechos em volta de cada marca de aprovacao
    vistos = 0
    for m in MARCAS.finditer(t):
        ini = max(0, m.start() - 350)
        trecho = t[ini:m.start() + 700]
        if "suframa" not in trecho.lower():
            continue
        vistos += 1
        print("-" * 78)
        print(f"  TRECHO {vistos}:")
        print(f"  {trecho[:1000]}")
        if vistos >= 3:
            break
    if vistos == 0:
        print("  (marcas encontradas, mas nenhuma perto de 'SUFRAMA')")

print("\n" + "=" * 78)
print("  Me envie os trechos acima — com a redacao real de "
      f"{a.ano} eu escrevo")
print("  as regras de extracao e monto o coletor do acervo antigo.")
