#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sonda_legado2.py
================
Busca no acervo antigo do DOU (pesquisa.in.gov.br) montando a requisicao a
partir do proprio formulario da pagina, em vez de adivinhar os campos.

A tentativa anterior deu HTTP 500 porque os nomes reais sao prefixados
("edicao.txtPesquisa", nao "txtPesquisa") e porque a sessao (jsessionid)
precisa ser mantida entre a abertura da pagina e o envio da busca.

O que faz:
  1. Abre start.action e guarda a sessao.
  2. Le o formulario de consulta e copia todos os campos como estao.
  3. Troca apenas o termo e o intervalo de datas.
  4. Envia e relata o que voltou, salvando o HTML cru.

Uso:
  python sonda_legado2.py
  python sonda_legado2.py --termo "Zona Franca de Manaus" --de 01/01/2012 --ate 31/12/2012
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
ap.add_argument("--de", default="01/01/2012")
ap.add_argument("--ate", default="31/12/2012")
a = ap.parse_args()

ses = requests.Session()

print("=" * 76)
print("  1. ABRINDO A PAGINA E LENDO O FORMULARIO")
print("=" * 76)

r = ses.get(START, headers=HD, timeout=60, verify=False)
print(f"  HTTP {r.status_code} | cookies: {list(ses.cookies.keys())}")
soup = BeautifulSoup(r.text, "lxml")

form = None
for f in soup.find_all("form"):
    if "consulta.action" in str(f.get("action", "")):
        form = f
        break
if form is None:
    raise SystemExit("  Formulario de consulta nao encontrado.")

acao = urljoin(BASE, form.get("action"))
print(f"  action: {acao[:110]}")

# Monta o payload copiando o formulario como o navegador faria
payload = []
print("\n  Campos do formulario:")
for el in form.find_all(["input", "select", "textarea"]):
    nome = el.get("name")
    if not nome:
        continue
    tipo = (el.get("type") or el.name).lower()

    if tipo in ("checkbox", "radio"):
        marcado = el.has_attr("checked")
        valor = el.get("value", "on")
        print(f"    [{tipo:8s}] {nome:28s} = {valor:12s} "
              f"{'(marcado)' if marcado else ''}")
        if marcado:
            payload.append((nome, valor))
    elif el.name == "select":
        opcoes = el.find_all("option")
        sel = next((o for o in opcoes if o.has_attr("selected")), None)
        valor = (sel or (opcoes[0] if opcoes else None))
        valor = valor.get("value", "") if valor is not None else ""
        amostra = [o.get("value", "") for o in opcoes[:6]]
        print(f"    [select  ] {nome:28s} = {valor:12s} "
              f"opcoes: {amostra}")
        payload.append((nome, valor))
    elif tipo in ("submit", "button", "image"):
        continue
    else:
        valor = el.get("value", "")
        print(f"    [{tipo:8s}] {nome:28s} = {valor[:40]}")
        payload.append((nome, valor))

# Substitui termo e datas
def por(chave_parcial, novo):
    global payload
    achou = False
    for i, (n, v) in enumerate(payload):
        if n.lower().endswith(chave_parcial.lower()):
            payload[i] = (n, novo)
            achou = True
    return achou

print("\n  Substituindo termo e datas:")
print(f"    txtPesquisa -> {a.termo}   ({'ok' if por('txtPesquisa', a.termo) else 'CAMPO NAO ACHADO'})")
print(f"    dtInicio    -> {a.de}      ({'ok' if por('dtInicio', a.de) else 'CAMPO NAO ACHADO'})")
print(f"    dtFim       -> {a.ate}     ({'ok' if por('dtFim', a.ate) else 'CAMPO NAO ACHADO'})")

print("\n" + "=" * 76)
print("  2. ENVIANDO A BUSCA")
print("=" * 76)

hd = dict(HD)
hd["Referer"] = START
hd["Content-Type"] = "application/x-www-form-urlencoded"

r2 = ses.post(acao, data=payload, headers=hd, timeout=90, verify=False)
print(f"  HTTP {r2.status_code} | {len(r2.text)} bytes")

p = PASTA / "legado_resultado.html"
p.write_text(r2.text, encoding="utf-8", errors="ignore")
print(f"  HTML salvo em {p}")

s2 = BeautifulSoup(r2.text, "lxml")
texto = re.sub(r"\s+", " ", s2.get_text(" "))

m = re.search(r"([\d.]+)\s*(?:resultado|ocorr[eê]ncia|registro|materia)",
              texto, re.I)
print(f"  contagem detectada: {m.group(0) if m else 'nenhuma'}")

links = [x.get("href") for x in s2.find_all("a", href=True)]
interessantes = [h for h in links
                 if re.search(r"jornal|visualiza|pdf|materia|exibe", str(h), re.I)]
print(f"  links de materia/jornal: {len(interessantes)}")
for h in interessantes[:8]:
    print(f"    {str(h)[:104]}")

print(f"\n  Inicio do texto da resposta:")
print(f"    {texto[:400].strip()[:380]}")

# O acervo antigo entrega imagem ou texto?
tem_img = len(s2.find_all("img"))
tem_pdf = sum(1 for h in links if ".pdf" in str(h).lower())
print(f"\n  imagens na pagina: {tem_img} | links .pdf: {tem_pdf}")

print("\n" + "=" * 76)
print("  COMO LER ESTE RESULTADO")
print("=" * 76)
print("  HTTP 200 com contagem e links de materia -> da para coletar.")
print("  HTTP 200 sem nada -> a busca exige algum campo que nao copiei.")
print("  HTTP 500 -> ainda falta um parametro obrigatorio.")
print("  Em qualquer caso, dados/legado_resultado.html tem a resposta crua.")
