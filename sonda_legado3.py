#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sonda_legado3.py
================
Terceira tentativa no acervo antigo do DOU, agora com o formato correto.

O que as tentativas anteriores ensinaram:
  - os campos sao prefixados: "edicao.txtPesquisa", nao "txtPesquisa";
  - a sessao (jsessionid) precisa ser mantida;
  - e o decisivo: dtInicio/dtFim sao DIA/MES apenas ("22/09"), com o ano
    num select separado ("edicao.ano"). Passar "01/01/2012" no campo de
    data provoca NullPointerException no servidor.

Esta sonda tambem lista TODOS os anos oferecidos pelo select — e o menor
deles define, sozinho, ate onde o acervo permite pesquisar.

Uso:
  python sonda_legado3.py
  python sonda_legado3.py --ano 2012 --termo "Zona Franca de Manaus"
  python sonda_legado3.py --ano 2012 --de 01/01 --ate 31/03
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
ap.add_argument("--de", default="01/01", help="dia/mes inicial (sem ano)")
ap.add_argument("--ate", default="31/12", help="dia/mes final (sem ano)")
ap.add_argument("--secao", default="1",
                help="1, 2 ou 3 — secao do DOU (padrao: 1)")
a = ap.parse_args()

ses = requests.Session()
r = ses.get(START, headers=HD, timeout=60, verify=False)
soup = BeautifulSoup(r.text, "lxml")

form = next((f for f in soup.find_all("form")
             if "consulta.action" in str(f.get("action", ""))), None)
if form is None:
    raise SystemExit("Formulario nao encontrado.")
acao = urljoin(BASE, form.get("action"))

# --- Todos os anos oferecidos: o menor define o limite do acervo ---------
print("=" * 76)
print("  ANOS DISPONIVEIS NO ACERVO")
print("=" * 76)
sel_ano = form.find("select", attrs={"name": re.compile(r"ano$")})
anos = []
if sel_ano:
    anos = [o.get("value", "") for o in sel_ano.find_all("option")
            if o.get("value", "").isdigit() and o.get("value") != "0"]
    print(f"  {len(anos)} anos: {', '.join(anos)}")
    if anos:
        print(f"\n  Mais antigo: {min(anos)}   Mais recente: {max(anos)}")
        if a.ano not in anos:
            print(f"\n  ATENCAO: {a.ano} NAO esta na lista — o acervo desta")
            print("  busca nao alcanca esse ano.")
else:
    print("  select de ano nao encontrado")

# --- Monta o payload copiando o formulario -------------------------------
grupos = {}
payload = []
for el in form.find_all(["input", "select", "textarea"]):
    nome = el.get("name")
    if not nome:
        continue
    tipo = (el.get("type") or el.name).lower()
    if tipo in ("submit", "button", "image"):
        continue
    if tipo == "checkbox":
        valor = el.get("value", "")
        # Os grupos de secao comecam pelo numero da secao
        if valor[:1] in ("1", "2", "3") and "," in valor:
            grupos.setdefault(valor[:1], valor)
        if el.has_attr("checked"):
            payload.append((nome, valor))
    elif tipo == "radio":
        if el.has_attr("checked"):
            payload.append((nome, el.get("value", "")))
    elif el.name == "select":
        opcoes = el.find_all("option")
        sel = next((o for o in opcoes if o.has_attr("selected")), None)
        v = (sel or (opcoes[0] if opcoes else None))
        payload.append((nome, v.get("value", "") if v is not None else ""))
    else:
        payload.append((nome, el.get("value", "")))

# Marca a secao escolhida do DOU
if a.secao in grupos:
    payload.append(("edicao.jornal", grupos[a.secao]))
    print(f"\n  Secao {a.secao} marcada "
          f"({grupos[a.secao][:46]}...)")

def por(sufixo, novo):
    achou = False
    for i, (n, v) in enumerate(payload):
        if n.lower().endswith(sufixo.lower()):
            payload[i] = (n, novo)
            achou = True
    return achou

por("txtPesquisa", a.termo)
por("dtInicio", a.de)     # DIA/MES apenas
por("dtFim", a.ate)
por("ano", a.ano)

print("\n" + "=" * 76)
print(f"  BUSCA: '{a.termo}' de {a.de} a {a.ate} de {a.ano}")
print("=" * 76)

hd = dict(HD)
hd["Referer"] = START
r2 = ses.post(acao, data=payload, headers=hd, timeout=90, verify=False)
print(f"  HTTP {r2.status_code} | {len(r2.text)} bytes")

p = PASTA / f"legado_{a.ano}.html"
p.write_text(r2.text, encoding="utf-8", errors="ignore")
print(f"  HTML salvo em {p}")

s2 = BeautifulSoup(r2.text, "lxml")
texto = re.sub(r"\s+", " ", s2.get_text(" "))

if r2.status_code == 500:
    erro = re.search(r"(java\.lang\.\w+(?:Exception)?)", texto)
    print(f"  erro do servidor: {erro.group(1) if erro else 'desconhecido'}")
else:
    m = re.search(r"([\d.]+)\s*(?:resultado|ocorr[eê]ncia|registro|mat[ée]ria)",
                  texto, re.I)
    print(f"  contagem: {m.group(0) if m else 'nao detectada'}")

    links = [x.get("href") for x in s2.find_all("a", href=True)]
    mats = [h for h in links
            if re.search(r"jornal|visualiza|materia|exibe|pdf", str(h), re.I)]
    print(f"  links de materia: {len(mats)}")
    for h in mats[:6]:
        print(f"    {str(h)[:104]}")

    # Suframa aparece no resultado?
    n_suframa = len(re.findall(r"suframa|zona franca", texto, re.I))
    print(f"  mencoes a SUFRAMA / Zona Franca no resultado: {n_suframa}")
    print(f"\n  Trecho: {texto[:340].strip()[:320]}")

print("\n" + "=" * 76)
print("  LEITURA")
print("=" * 76)
if anos:
    print(f"  O acervo desta busca cobre de {min(anos)} a {max(anos)}.")
    print("  Se o ano que voce precisa nao estiver na lista, esta busca nao")
    print("  serve — o caminho passa a ser a Central de Atendimento da")
    print("  Imprensa Nacional ou a solicitacao via SIC a propria SUFRAMA.")
