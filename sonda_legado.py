#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sonda_legado.py
===============
Investiga como chegar aos atos anteriores a 2016, que o portal moderno do
DOU nao indexa. Responde tres perguntas:

  1. Qual a data mais antiga que o portal moderno realmente alcanca?
     (busca ordenada do mais antigo para o mais novo)
  2. O acervo antigo (pesquisa.in.gov.br) responde e com que formulario?
  3. Uma busca la devolve resultados? Sao texto ou imagem digitalizada?

Salva o HTML bruto das respostas em dados/legado_*.html, para eu analisar
a estrutura caso a leitura automatica nao baste.

Uso:
  python sonda_legado.py
  python sonda_legado.py --ano 2012
"""

import argparse
import json
import re
from pathlib import Path

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HD = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/120.0.0.0 Safari/537.36"),
      "Accept-Language": "pt-BR,pt;q=0.9"}

PASTA = Path("dados")
PASTA.mkdir(exist_ok=True)

BUSCA_NOVA = "https://www.in.gov.br/consulta/-/buscar/dou"
SID = "_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params"
LEGADO = "https://pesquisa.in.gov.br/imprensa/core/start.action"
LEGADO_CONSULTA = "https://pesquisa.in.gov.br/imprensa/core/consulta.action"


def salvar(nome, texto):
    p = PASTA / nome
    p.write_text(texto, encoding="utf-8", errors="ignore")
    return p


ap = argparse.ArgumentParser()
ap.add_argument("--ano", type=int, default=2012)
a = ap.parse_args()

ses = requests.Session()

# ---------------------------------------------------------------------------
print("=" * 76)
print("  1. ATE ONDE O PORTAL MODERNO ALCANCA")
print("=" * 76)
# sortType=1 costuma inverter a ordem (mais antigo primeiro). Se o acervo
# for maior do que supomos, o ato mais antigo aparece aqui.
for sort_tipo, rotulo in (("1", "mais antigo primeiro"), ("0", "mais novo primeiro")):
    try:
        r = ses.get(BUSCA_NOVA,
                    params={"q": "suframa", "s": "todos", "exactDate": "all",
                            "sortType": sort_tipo, "delta": "20"},
                    headers=HD, timeout=60, verify=False)
        tag = BeautifulSoup(r.text, "lxml").find("script", id=SID)
        itens = (json.loads(tag.string or tag.text).get("jsonArray", [])
                 if tag else [])
        datas = [it.get("pubDate", "") for it in itens]
        print(f"  {rotulo:24s}: {len(itens)} itens | "
              f"primeira data: {datas[0] if datas else '-'}")
        if datas:
            anos = sorted({d[-4:] for d in datas if len(d) >= 4})
            print(f"  {'':24s}  anos nesta pagina: {', '.join(anos)}")
    except requests.RequestException as e:
        print(f"  {rotulo}: ERRO {e}")

# ---------------------------------------------------------------------------
print("\n" + "=" * 76)
print("  2. O ACERVO ANTIGO RESPONDE?")
print("=" * 76)
try:
    r = ses.get(LEGADO, headers=HD, timeout=60, verify=False)
    print(f"  HTTP {r.status_code} | {len(r.text)} bytes")
    p = salvar("legado_start.html", r.text)
    print(f"  HTML salvo em {p}")

    soup = BeautifulSoup(r.text, "lxml")
    forms = soup.find_all("form")
    print(f"\n  Formularios encontrados: {len(forms)}")
    for f in forms[:3]:
        print(f"    action={f.get('action')} method={f.get('method')}")
        campos = []
        for i in f.find_all(["input", "select", "textarea"]):
            nome = i.get("name")
            if nome:
                campos.append(f"{i.name}:{nome}")
        print(f"      campos: {', '.join(campos[:18])}")
except requests.RequestException as e:
    print(f"  ERRO ao acessar: {e}")

# ---------------------------------------------------------------------------
print("\n" + "=" * 76)
print(f"  3. BUSCA NO ACERVO ANTIGO — 'Zona Franca de Manaus' em {a.ano}")
print("=" * 76)

tentativas = [
    ("GET  consulta.action", "get", LEGADO_CONSULTA,
     {"q": '"Zona Franca de Manaus"',
      "dt_inicio": f"01/01/{a.ano}", "dt_fim": f"31/12/{a.ano}"}),
    ("POST consulta.action", "post", LEGADO_CONSULTA,
     {"txtPesquisa": '"Zona Franca de Manaus"',
      "dataPublicacaoInicial": f"01/01/{a.ano}",
      "dataPublicacaoFinal": f"31/12/{a.ano}"}),
]

for rotulo, metodo, url, dados in tentativas:
    try:
        if metodo == "get":
            r = ses.get(url, params=dados, headers=HD, timeout=60, verify=False)
        else:
            r = ses.post(url, data=dados, headers=HD, timeout=60, verify=False)
        soup = BeautifulSoup(r.text, "lxml")
        texto = re.sub(r"\s+", " ", soup.get_text(" "))
        m = re.search(r"([\d.]+)\s*(?:resultado|ocorr|registro)", texto, re.I)
        links_pdf = [x.get("href") for x in soup.find_all("a", href=True)
                     if re.search(r"\.pdf|jornal|visualiza", str(x.get("href")), re.I)]
        print(f"\n  {rotulo}: HTTP {r.status_code} | {len(r.text)} bytes")
        print(f"     contagem detectada : {m.group(0) if m else 'nenhuma'}")
        print(f"     links de jornal/PDF: {len(links_pdf)}")
        for h in links_pdf[:4]:
            print(f"       {str(h)[:100]}")
        p = salvar(f"legado_busca_{metodo}.html", r.text)
        print(f"     HTML salvo em {p}")
        trecho = texto[:300].strip()
        print(f"     inicio do texto: {trecho[:180]}")
    except requests.RequestException as e:
        print(f"\n  {rotulo}: ERRO {e}")

print("\n" + "=" * 76)
print("  PROXIMO PASSO")
print("=" * 76)
print("  Os arquivos dados/legado_*.html guardam as respostas cruas.")
print("  Se a leitura acima nao tiver sido conclusiva, me envie o")
print("  legado_start.html — e nele que esta o formulario real de busca,")
print("  e a partir dele eu monto as requisicoes corretas.")
