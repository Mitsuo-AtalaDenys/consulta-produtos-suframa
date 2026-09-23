#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
coletar_dou_legado.py
=====================
Coleta atos da SUFRAMA anteriores a 2016, que o portal moderno do DOU nao
indexa, usando o acervo da Imprensa Nacional (pesquisa.in.gov.br).

COMO FUNCIONA
-------------
O acervo antigo e diferente do portal moderno em tres pontos:

1. A busca e por PAGINA de jornal, nao por ato. Um resultado aponta para
   "pagina 136 de 30/03/2012", e nessa pagina pode haver varios atos da
   SUFRAMA — ou nenhum, se o termo aparecer em outro contexto.

2. O conteudo vem em PDF, servido pelo servlet INPDFViewer. Felizmente os
   PDFs tem camada de texto, entao nao ha OCR envolvido e a extracao e
   tao confiavel quanto a da serie moderna.

3. O texto sai diagramado em colunas de jornal, o que quebra palavras com
   hifen no fim da linha ("SIEMENS ELETROE- LETRONICA") e produz
   artefatos como "N o-" no lugar de "nº". Isso e corrigido antes de
   qualquer extracao.

O termo de busca e "Codigo SUFRAMA": em teste, 4 de 4 paginas trazidas por
ele continham ato de projeto, contra 3 de 4 do termo generico "SUFRAMA".

As regras de extracao e classificacao sao as mesmas de coletar_dou.py,
importadas dele — o que ja funciona para 2016-2026 nao e reescrito aqui.

USO
---
  python coletar_dou_legado.py --teste --ano 2012 --mes 3
  python coletar_dou_legado.py --de 2008 --ate 2015
  python coletar_dou_legado.py --de 2012 --ate 2012

Requer: requests, beautifulsoup4, lxml, pandas, pyarrow, pypdf
"""

import argparse
import csv
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Reaproveita as regras ja validadas do coletor moderno
try:
    import coletar_dou as base
except ImportError:
    raise SystemExit("coletar_dou.py precisa estar na mesma pasta.")

BASE_URL = "https://pesquisa.in.gov.br"
START = f"{BASE_URL}/imprensa/core/start.action"
PDF_URL = (BASE_URL + "/imprensa/servlet/INPDFViewer?jornal={j}&pagina={p}"
                      "&data={d}&captchafield=firstAccess")
VISUALIZA = (BASE_URL + "/imprensa/jsp/visualiza/index.jsp"
                        "?jornal={j}&pagina={p}&data={d}")

# Termo padrao. "Codigo SUFRAMA" tem a melhor precisao (4 de 4 paginas
# com ato de projeto no teste), mas menor alcance: o termo amplo
# "SUFRAMA" traz mais paginas. Como as paginas ficam em cache e sao
# deduplicadas por data+pagina, vale rodar as duas passadas e reprocessar
# no fim — a segunda so acrescenta o que a primeira nao viu.
TERMO = '"Código SUFRAMA"'

PASTA = Path("dados")
ARQ_PARCIAL = PASTA / "_parcial_legado.csv"
ARQ_CSV = PASTA / "dou_legado.csv"
ARQ_PARQUET = PASTA / "dou_legado.parquet"
# Texto das paginas guardado em disco: baixar PDF e a parte cara: assim
# uma correcao nas regras nao exige refazer a coleta.
CACHE = PASTA / "paginas_legado"

HD = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/120.0.0.0 Safari/537.36"),
      "Accept-Language": "pt-BR,pt;q=0.9"}

DIAS = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
        7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


def ultimo_dia(ano: int, mes: int) -> int:
    """Fevereiro tem 29 dias so em ano bissexto.

    Pedir 29/02 num ano comum e uma data inexistente, e o acervo responde
    HTTP 500 — foi assim que seis fevereiros inteiros se perderam na
    primeira coleta.
    """
    if mes == 2 and (ano % 4 == 0 and (ano % 100 != 0 or ano % 400 == 0)):
        return 29
    return DIAS[mes]


# ---------------------------------------------------------------------------
# Normalizacao do texto do PDF
# ---------------------------------------------------------------------------
# A extracao do PDF insere espacos dentro de palavras por causa do
# espacamento tipografico ("APROV AR", "GUSTA VO"). Sem reparar, nenhum
# verbo de classificacao e reconhecido.
VERBOS = ("APROVAR", "CANCELAR", "AUTORIZAR", "SUSPENDER", "REVOGAR",
          "ALTERAR", "PRORROGAR", "HOMOLOGAR", "RATIFICAR", "DEFERIR",
          "INDEFERIR", "TORNAR", "PUBLICAR", "ESTABELECER", "DETERMINAR",
          "CONCEDER", "APROVADO", "APROVADA", "CANCELADO")
REPAROS = [(re.compile(r"\b" + r"\s*".join(v) + r"\b"), v) for v in VERBOS]


def normalizar_pdf(t: str) -> str:
    """Desfaz a diagramacao em colunas do jornal impresso.

    O PDF do DOU antigo quebra palavras com hifen no fim da linha. Sem
    juntar essas quebras, nomes de empresa saem partidos ("SIEMENS
    ELETROE- LETRONICA") e nenhuma regra de extracao funciona. O criterio
    e exigir ESPACO depois do hifen: hifens legitimos, como em
    "RESIDUAL-DR", vem colados e ficam preservados.
    """
    t = str(t).replace("\xad", "")
    t = re.sub(r"([A-Za-zÀ-ÿ])-\s+([A-Za-zÀ-ÿ])", r"\1\2", t)
    # "N o-" e "N º-" sao artefatos da extracao de "Nº"
    # Produz sempre "Nº" maiusculo: a versao anterior gerava "nº"
    # minusculo e assim os cabecalhos deixavam de casar com o separador,
    # que e sensivel a caixa para nao confundir cabecalho com citacao.
    t = re.sub(r"\b[Nn]\s*[oº°]\s*-\s*", "Nº ", t)
    t = re.sub(r"\s+", " ", t).strip()
    for padrao, certo in REPAROS:
        t = padrao.sub(certo, t)
    return t


# ---------------------------------------------------------------------------
# Busca
# ---------------------------------------------------------------------------
def montar_payload(form, termo, de, ate, ano):
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

    if "1" in grupos:                      # Secao 1 do DOU
        payload.append(("edicao.jornal", grupos["1"]))

    for i, (n, v) in enumerate(payload):
        ln = n.lower()
        if ln.endswith("txtpesquisa"):
            payload[i] = (n, termo)
        elif ln.endswith("dtinicio"):
            payload[i] = (n, de)
        elif ln.endswith("dtfim"):
            payload[i] = (n, ate)
        elif ln.endswith("ano"):
            payload[i] = (n, str(ano))
    return payload


def buscar_paginas(ses, ano, mes, tentativas=3, termo=None):
    """Devolve [(jornal, pagina, data), ...] do mes informado."""
    de = f"01/{mes:02d}"
    ate = f"{ultimo_dia(ano, mes):02d}/{mes:02d}"

    for t in range(tentativas):
        try:
            r = ses.get(START, headers=HD, timeout=60, verify=False)
            soup = BeautifulSoup(r.text, "lxml")
            form = next(f for f in soup.find_all("form")
                        if "consulta.action" in str(f.get("action", "")))
            acao = urljoin(BASE_URL, form.get("action"))
            payload = montar_payload(form, termo or TERMO, de, ate, ano)

            hd = dict(HD); hd["Referer"] = START
            r2 = ses.post(acao, data=payload, headers=hd, timeout=90,
                          verify=False)
            if r2.status_code != 200:
                print(f"[HTTP {r2.status_code}]", end=" ", flush=True)
                continue

            s2 = BeautifulSoup(r2.text, "lxml")
            achados, vistos = [], set()
            for x in s2.find_all("a", href=True):
                m = re.search(r"jornal=(\d+)&pagina=(\d+)&data=([\d/]+)",
                              str(x.get("href")))
                if m and m.groups() not in vistos:
                    vistos.add(m.groups())
                    achados.append(m.groups())

            # Aviso de paginacao: se houver link de proxima pagina de
            # resultados, parte do mes pode estar ficando de fora.
            tem_mais = bool(s2.find("a", string=re.compile(
                r"pr[óo]xim|seguinte|>>", re.I)))
            return achados, tem_mais
        except (requests.RequestException, StopIteration):
            print(f"[rede {t+1}]", end=" ", flush=True)
            time.sleep(3 * (t + 1))
    return [], False


def caminho_cache(jornal, pagina, data):
    seguro = str(data).replace("/", "-")
    return CACHE / f"{seguro}_j{jornal}_p{pagina}.txt"


def baixar_texto(ses, jornal, pagina, data, tentativas=3):
    CACHE.mkdir(parents=True, exist_ok=True)
    guardado = caminho_cache(jornal, pagina, data)
    if guardado.exists():
        return guardado.read_text(encoding="utf-8", errors="ignore")

    url = PDF_URL.format(j=jornal, p=pagina, d=data)
    hd = dict(HD)
    hd["Referer"] = VISUALIZA.format(j=jornal, p=pagina, d=data)
    for t in range(tentativas):
        try:
            r = ses.get(url, headers=hd, timeout=120, verify=False)
            if r.content[:4] != b"%PDF":
                return ""
            tmp = PASTA / "_tmp_legado.pdf"
            tmp.write_bytes(r.content)
            from pypdf import PdfReader
            leitor = PdfReader(str(tmp))
            bruto = "".join((pg.extract_text() or "") for pg in leitor.pages)
            texto = normalizar_pdf(bruto)
            guardado.write_text(texto, encoding="utf-8")
            return texto
        except requests.RequestException:
            time.sleep(2 * (t + 1))
        except Exception:
            return ""
    return ""


# ---------------------------------------------------------------------------
# Separacao dos atos dentro da pagina
# ---------------------------------------------------------------------------
# Separadores de ato. O erro da primeira versao foi cortar em qualquer
# "Portaria nº X" / "Resolucao nº Y": no DOU antigo, o preambulo de cada
# ato CITA outras normas ("com fundamento na Resolucao nº 202, de 17 de
# maio de 2006"), e o corte caia na citacao, comecando o bloco no meio do
# ato e deixando a empresa no bloco vizinho.
#
# Os dois cortes validos sao:
#   - o item numerado: "Nº 169/08 - Art. 1º APROVAR ..."
#   - o cabecalho de verdade, em CAIXA ALTA e seguido de data:
#     "PORTARIA Nº 535, DE 6 DE NOVEMBRO DE 2008"
# A citacao aparece em caixa mista ("Resolucao nº 202, de ...") e por isso
# nao casa com o segundo padrao, que e sensivel a caixa.

MARCA_ITEM = re.compile(
    r"N[º°o]\s*\.?\s*\d{1,5}(?:\s*/\s*\d{2,4})?\s*[-–—]\s*Art\.?\s*\d",
    re.I)

# O nome do ato permanece sensivel a caixa — e o que separa o cabecalho
# de verdade ("PORTARIA Nº 535, DE 6 DE NOVEMBRO DE 2008") da citacao de
# outra norma no preambulo ("Resolucao nº 202, de 17 de maio de 2006").
# Ja o "Nº" aceita as duas caixas, porque a extracao do PDF varia.
MARCA_CABECALHO = re.compile(
    r"\b(?:PORTARIAS?|RESOLU[ÇC][ÕO]ES|RESOLU[ÇC][ÃA]O|DESPACHOS?)"
    r"(?:\s+SUFRAMA)?\s+(?:"
    r"[Nn][º°Oo]?\s*\.?\s*[\d.]+(?:/\d+)?\s*,?\s+DE\s+\d"
    r"|DE\s+\d{1,2}[º°]?\s+DE\s+[A-Za-zÇÃÉÀ-ÿ]+\s+DE\s+\d{4}"
    r")")


def atos_da_pagina(texto):
    """Fatia o texto da pagina nos atos que ela contem.

    A pagina do jornal traz materias de varios orgaos; so interessam os
    blocos que mencionam a SUFRAMA.
    """
    pontos = sorted({m.start() for m in MARCA_ITEM.finditer(texto)}
                    | {m.start() for m in MARCA_CABECALHO.finditer(texto)})
    if not pontos:
        return []

    blocos = []
    for i, ini_b in enumerate(pontos):
        fim_b = pontos[i + 1] if i + 1 < len(pontos) else len(texto)
        bloco = texto[ini_b:fim_b]
        if len(bloco) < 100:
            continue
        if not re.search(r"suframa", bloco, re.I):
            continue
        blocos.append(bloco)
    return blocos


COLUNAS = ["data_publicacao", "jornal", "pagina", "item", "numero_ato", "titulo",
           "classificacao", "ato_de_projeto", "tipo_projeto", "empresa",
           "cnpj", "inscricao_suframa", "codigo_produto", "produto",
           "processo", "url", "texto_item"]


def processar_pagina(texto, jornal, pagina, data):
    linhas = []
    for bloco in atos_da_pagina(texto):
        cls = base.classificar(bloco)
        # Um mesmo ato pode aprovar varios produtos — a Portaria 252/2015
        # da Flextronics aprova tres codigos de uma vez. extrair_multiplos
        # devolve um registro por produto, como ja acontece na serie
        # moderna.
        registros = base.extrair_multiplos(bloco)
        for pos, campos in enumerate(registros, 1):
            d = {c: "" for c in COLUNAS}
            for k, v in campos.items():
                if k in d and v:
                    d[k] = v
            d["classificacao"] = cls
            d["data_publicacao"] = data
            d["jornal"] = jornal
            d["pagina"] = pagina
            d["url"] = VISUALIZA.format(j=jornal, p=pagina, d=data)
            d["texto_item"] = (campos.get("texto_item") or bloco)[:6000]
            if len(registros) > 1:
                d["item"] = f"{pos}/{len(registros)}"
            m = MARCA_CABECALHO.match(bloco) or MARCA_ITEM.match(bloco)
            if m:
                num = re.search(r"([\d.]+(?:/\d+)?)", m.group(0))
                if num:
                    d["numero_ato"] = num.group(1).strip(".")
                d["titulo"] = re.sub(r"\s+", " ", m.group(0)).strip()
            linhas.append(d)
    return linhas


# ---------------------------------------------------------------------------
def consolidar():
    import pandas as pd
    if not ARQ_PARCIAL.exists():
        print("  Nada a consolidar.")
        return
    df = pd.read_csv(ARQ_PARCIAL, dtype=str).fillna("")
    df = df[df["url"] != "url"]
    df = df.drop_duplicates(subset=["url", "numero_ato", "codigo_produto",
                                    "empresa"])
    df.to_csv(ARQ_CSV, index=False, encoding="utf-8")
    df.to_parquet(ARQ_PARQUET, index=False)
    import shutil
    shutil.copy2(ARQ_PARQUET, Path("dou_legado.parquet"))

    print("\n  --- Consolidacao ---")
    print(f"  Registros:       {len(df)}")
    print(f"  Com empresa:     {(df['empresa'] != '').sum()}")
    print(f"  Com cod.produto: {(df['codigo_produto'] != '').sum()}")
    print("  Por classificacao:")
    for k, v in df["classificacao"].value_counts().items():
        print(f"     {k:26s} {v}")
    print(f"  Parquet: {ARQ_PARQUET}  (copia na raiz)")


def coletar(anos, meses, pausa, teste=False, termo=None):
    PASTA.mkdir(exist_ok=True)
    ja = set()
    if ARQ_PARCIAL.exists():
        with open(ARQ_PARCIAL, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                ja.add((row.get("data_publicacao", ""), row.get("pagina", "")))
        print(f"  Cache: {len(ja)} paginas ja processadas")

    ses = requests.Session()
    novo = not ARQ_PARCIAL.exists() or ARQ_PARCIAL.stat().st_size == 0

    with open(ARQ_PARCIAL, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS, extrasaction="ignore")
        if novo:
            w.writeheader()

        for ano in anos:
            for mes in meses:
                print(f"\n  === {mes:02d}/{ano} ===")
                paginas, tem_mais = buscar_paginas(ses, ano, mes,
                                                   termo=termo)
                print(f"  {len(paginas)} paginas de jornal encontradas"
                      + ("  [ATENCAO: ha mais paginas de resultado]"
                         if tem_mais else ""))
                if teste:
                    paginas = paginas[:3]

                total_atos = 0
                pulados = 0
                for i, (jornal, pagina, data) in enumerate(paginas, 1):
                    if (data, pagina) in ja:
                        pulados += 1
                        continue
                    print(f"    [{i}/{len(paginas)}] pag {pagina} de {data}...",
                          end=" ", flush=True)
                    texto = baixar_texto(ses, jornal, pagina, data)
                    if not texto:
                        print("sem texto")
                        continue
                    linhas = processar_pagina(texto, jornal, pagina, data)
                    for ln in linhas:
                        w.writerow(ln)
                    f.flush()
                    total_atos += len(linhas)
                    print(f"{len(linhas)} ato(s) da SUFRAMA")
                    if teste and linhas:
                        for ln in linhas:
                            print(f"        {ln['classificacao']:22s} | "
                                  f"{ln['codigo_produto'] or '----'} | "
                                  f"{(ln['empresa'] or '-')[:44]}")
                    time.sleep(pausa)
                if pulados:
                    print(f"  ({pulados} pagina(s) puladas por ja estarem "
                          f"na coleta anterior — use --reiniciar para "
                          f"reprocessa-las)")
                print(f"  -> {total_atos} atos no mes")

    consolidar()


def reprocessar():
    """Refaz a extracao a partir do texto das paginas ja guardado.

    Como o texto de cada pagina fica em dados/paginas_legado, corrigir uma
    regra de separacao ou de extracao nao exige baixar nada de novo.
    """
    if not CACHE.exists():
        print("  Sem cache de paginas. Rode a coleta antes.")
        return
    arquivos = sorted(CACHE.glob("*.txt"))
    print(f"  Reprocessando {len(arquivos)} paginas do cache (sem rede)...")

    if ARQ_PARCIAL.exists():
        ARQ_PARCIAL.unlink()

    total = 0
    vazias = []
    with open(ARQ_PARCIAL, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS, extrasaction="ignore")
        w.writeheader()
        for i, arq in enumerate(arquivos, 1):
            m = re.match(r"(\d{2}-\d{2}-\d{4})_j(\d+)_p(\d+)", arq.stem)
            if not m:
                continue
            data = m.group(1).replace("-", "/")
            jornal, pagina = m.group(2), m.group(3)
            texto = arq.read_text(encoding="utf-8", errors="ignore")
            linhas = processar_pagina(texto, jornal, pagina, data)
            for ln in linhas:
                w.writerow(ln)
            total += len(linhas)
            # Pagina veio da busca por "Codigo SUFRAMA", entao contem o
            # termo: se nao rendeu ato, o separador falhou nela.
            if not linhas and re.search(r"c[óo]d\w*\s+suframa", texto, re.I):
                vazias.append((arq.name, len(texto)))
            if i % 100 == 0:
                print(f"    {i}/{len(arquivos)} paginas | {total} atos")
    print(f"  {total} atos extraidos de {len(arquivos)} paginas")
    if vazias:
        print(f"\n  ATENCAO: {len(vazias)} paginas contem 'Codigo SUFRAMA'")
        print("  mas nao renderam ato nenhum — o separador falhou nelas:")
        for nome, tam in vazias[:10]:
            print(f"    {nome}  ({tam} chars)")
        if len(vazias) > 10:
            print(f"    ... e mais {len(vazias) - 10}")
    consolidar()


def main():
    p = argparse.ArgumentParser(description="Coletor do acervo antigo do DOU")
    p.add_argument("--reprocessar", action="store_true",
                   help="refaz a extracao do cache, sem acessar a rede")
    p.add_argument("--reiniciar", action="store_true",
                   help="ignora o que ja foi coletado e recomeca")
    p.add_argument("--de", type=int, default=2008)
    p.add_argument("--ate", type=int, default=2015)
    p.add_argument("--ano", type=int, help="atalho para um ano so")
    p.add_argument("--mes", type=int, help="um mes so")
    p.add_argument("--pausa", type=float, default=1.5)
    p.add_argument("--teste", action="store_true",
                   help="3 paginas do mes, mostrando o que extraiu")
    p.add_argument("--termo", default=None,
                   help='termo de busca; padrao "Código SUFRAMA". '
                        'Use --termo SUFRAMA para ampliar o alcance')
    a = p.parse_args()

    print("=" * 66)
    print("  COLETOR DOU LEGADO - atos da SUFRAMA anteriores a 2016")
    print("=" * 66)

    if a.reprocessar:
        reprocessar()
        return

    if a.reiniciar and ARQ_PARCIAL.exists():
        ARQ_PARCIAL.unlink()
        print("  Coleta anterior descartada — as regras novas valerao")
        print("  para todas as paginas.\n")

    anos = [a.ano] if a.ano else list(range(a.de, a.ate + 1))
    meses = [a.mes] if a.mes else list(range(1, 13))
    print(f"  Anos: {anos[0]} a {anos[-1]} | meses: {len(meses)}")
    print(f"  Termo de busca: {a.termo or TERMO}")

    coletar(anos, meses, a.pausa, a.teste, termo=a.termo)


if __name__ == "__main__":
    main()
