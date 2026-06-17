#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
coletar_suframa.py  (v2)
========================
Coleta a base COMPLETA de Insumos da Suframa e consolida em arquivos
pesquisaveis (CSV, Parquet e SQLite), com:

  - TODOS os produtos (catalogo completo) vindos da Listagem Padrao de
    Insumos em versao de impressao (1 unica pagina, ~1.768 produtos):
        EST_PoloProdutoGeraltd_imp.asp
    Dela saem: codigo, produto_nome, base_legal, unidade, data_atualizacao.
  - TODOS os tipos de cada produto:
        EST_PoloProdutoGeralTipo.asp?produto=<codigo>
    Dela saem: codigo_tipo, descricao_tipo.
  - O NCM de cada tipo (visita a pagina de detalhe de cada tipo):
        EST_PoloProdutoGeralTipoDetalha.asp?produto=<codigo>&tipo=<codigo_tipo>

Resultado: uma linha por (produto x tipo) com produto + tipo + NCM.

A coleta com NCM e LENTA (uma requisicao por tipo). O script grava o
progresso a cada produto em dados/_parcial.csv e, se voce rodar de novo,
ele CONTINUA de onde parou (pula os produtos ja coletados). Pode fechar e
reabrir sem perder o que ja foi feito.

Uso:
  python3 coletar_suframa.py                  # coleta completa COM NCM (recomendado)
  python3 coletar_suframa.py --sem-ncm        # produto + tipo, sem NCM (bem mais rapido)
  python3 coletar_suframa.py --limite 3       # TESTE: so os 3 primeiros produtos
  python3 coletar_suframa.py --teste-ncm 1873 010   # baixa 1 detalhe e mostra o NCM achado
  python3 coletar_suframa.py --listagem pagina_imp.html  # usa um HTML ja salvo da listagem
  python3 coletar_suframa.py --pausa 0.5      # segundos entre requisicoes (padrao 0.8)
  python3 coletar_suframa.py --reiniciar      # ignora o _parcial.csv e comeca do zero
  python3 coletar_suframa.py --saida dados    # pasta de saida (padrao: dados)

Requisitos:
  pip3 install requests beautifulsoup4 lxml pandas pyarrow
"""

import argparse, re, sys, time, sqlite3
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
import pandas as pd

# ---------------------------------------------------------------------------
ROOT = "https://wwws.suframa.gov.br/"
BASE = ROOT + "servicos/estrangeiro/consultas/listageminsumos/"
URL_IMPRESSAO = BASE + "EST_PoloProdutoGeraltd_imp.asp"          # lista completa
URL_TIPO      = BASE + "EST_PoloProdutoGeralTipo.asp?produto={}"  # tipos do produto
URL_DETALHE   = BASE + "EST_PoloProdutoGeralTipoDetalha.asp?produto={}&tipo={}"  # NCM

HEADERS = {"User-Agent": "Mozilla/5.0 (consulta-publica-insumos)",
           "Accept-Language": "pt-BR,pt;q=0.9"}
ENCODING = "ISO-8859-1"

UNIDADES = ["TONELADA MÉTRICA LÍQUIDA", "QUILOGRAMA LÍQUIDO", "TONELADA MÉTRICA",
            "MIL UNIDADES", "METRO CÚBICO", "METRO QUADRADO", "QUILOGRAMA",
            "TONELADA", "UNIDADE", "LITRO", "METRO", "DÚZIA"]
UN_ALT = "|".join(re.escape(u) for u in sorted(UNIDADES, key=len, reverse=True))
DATA_RE = r"\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}"


# ---------------------------------------------------------------------------
def baixar(session, url, tentativas=3, pausa=1.0):
    for i in range(tentativas):
        try:
            r = session.get(url, headers=HEADERS, timeout=60)
            r.encoding = ENCODING
            r.raise_for_status()
            return r.text
        except Exception as e:
            if i == tentativas - 1:
                print(f"      [erro] {url} -> {e}")
                return None
            time.sleep(pausa * (i + 1))
    return None


# ---------------------------------------------------------------------------
def extrair_produtos_impressao(html):
    """Da Listagem Padrao (impressao) extrai a lista completa de produtos.
    Retorna [{codigo, produto_nome, base_legal, unidade, data_atualizacao}, ...].
    A pagina e texto corrido; cada linha tem o formato:
        CODIGO  NOME  Tipo  BASE_LEGAL  UNIDADE  [DATA]
    Usamos a palavra 'Tipo' como ancora (ela separa nome de base legal)."""
    soup = BeautifulSoup(html, "html.parser")
    texto = soup.get_text(" ", strip=True)
    ini = texto.find("Data última atualização")
    fim = texto.find("Copyright")
    bloco = texto[ini + len("Data última atualização"): fim if fim > 0 else len(texto)].strip()

    boundary = re.compile(r"^(.*?)\s+(" + UN_ALT + r")(?:\s+(" + DATA_RE + r"))?\s+(\d{4})\s+(.*)$", re.DOTALL)
    segs = bloco.split(" Tipo ")
    if len(segs) < 2:
        return []

    regs = []
    m0 = re.match(r"\s*(\d{4})\s+(.*)$", segs[0], re.DOTALL)
    pc, pn = m0.group(1), m0.group(2)
    for k in range(1, len(segs)):
        if k < len(segs) - 1:
            m = boundary.match(segs[k])
            if not m:
                continue
            base, uni, data, nc, nn = m.groups()
            regs.append({"codigo": pc, "produto_nome": " ".join(pn.split()),
                         "base_legal": " ".join(base.split()), "unidade": uni,
                         "data_atualizacao": data or ""})
            pc, pn = nc, nn
        else:
            m = re.match(r"^(.*?)\s+(" + UN_ALT + r")(?:\s+(" + DATA_RE + r"))?\s*$", segs[k], re.DOTALL)
            base, uni, data = (m.group(1), m.group(2), m.group(3)) if m else (segs[k], "", "")
            regs.append({"codigo": pc, "produto_nome": " ".join(pn.split()),
                         "base_legal": " ".join(base.split()), "unidade": uni,
                         "data_atualizacao": data or ""})

    # remove duplicatas de codigo preservando ordem
    vistos, unicos = set(), []
    for r in regs:
        if r["codigo"] not in vistos:
            vistos.add(r["codigo"]); unicos.append(r)
    return unicos


def extrair_tipos(html):
    """Da pagina de um produto extrai [(codigo_tipo, descricao_tipo), ...]."""
    soup = BeautifulSoup(html, "html.parser")
    tipos = []
    for a in soup.find_all("a", href=True):
        m = re.search(r"TipoDetalha\.asp\?produto=\d+&tipo=([^&\"']+)", a["href"])
        if not m:
            continue
        codigo = a.get_text(strip=True) or m.group(1)
        desc = ""
        tr = a.find_parent("tr")
        if tr:
            tds = tr.find_all("td")
            if len(tds) >= 2:
                desc = " ".join(tds[1].get_text(" ", strip=True).split())
        tipos.append((codigo, desc))
    # dedup preservando ordem
    vistos, out = set(), []
    for c, d in tipos:
        if c not in vistos:
            vistos.add(c); out.append((c, d))
    return out


def extrair_ncm(html):
    """Captura NCM(s) e a descricao da NCM da pagina de detalhe do tipo.
    A pagina tem uma tabela 'NCM | Descricao da NCM' com uma ou mais linhas
    no formato: <codigo 8 digitos> | <descricao>. Validado contra
    detalhe_1873_010.html (73181600 - PORCAS DE FERRO FUNDIDO, FERRO OU ACO).
    Retorna (codigos_ncm, descricoes_ncm)."""
    soup = BeautifulSoup(html, "html.parser")
    ncms = []
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        c0 = tds[0].get_text(" ", strip=True).replace(".", "").strip()
        c1 = tds[1].get_text(" ", strip=True)
        if re.fullmatch(r"\d{8}", c0):
            ncms.append((c0, c1))
    if ncms:
        cod = ", ".join(dict.fromkeys(n for n, _ in ncms))
        desc = " | ".join(dict.fromkeys(d for _, d in ncms if d))
        return cod, desc
    # fallback: nenhuma tabela reconhecida -> 8 digitos avulsos, sem descricao
    texto = soup.get_text(" ", strip=True)
    oito = re.findall(r"(?<!\d)\d{8}(?!\d)", texto)
    return ", ".join(dict.fromkeys(oito)), ""


# ---------------------------------------------------------------------------
def carregar_listagem(session, arquivo, pausa):
    if arquivo:
        print(f">> Lendo a listagem de arquivo local: {arquivo}")
        html = Path(arquivo).read_text(encoding=ENCODING, errors="replace")
    else:
        print(">> Baixando a Listagem Padrao de Insumos (impressao)...")
        html = baixar(session, URL_IMPRESSAO, pausa=pausa)
        if not html:
            sys.exit("Falha ao baixar a listagem. Verifique conexao/VPN.")
    produtos = extrair_produtos_impressao(html)
    print(f"   {len(produtos)} produtos encontrados.")
    if not produtos:
        sys.exit("Nenhum produto extraido - o layout pode ter mudado.")
    return produtos


def coletar(args):
    saida = Path(args.saida); saida.mkdir(parents=True, exist_ok=True)
    parcial = saida / "_parcial.csv"
    s = requests.Session()

    # ---- modo teste de NCM: baixa 1 detalhe e mostra o que achou ----
    if args.teste_ncm:
        cod, tipo = args.teste_ncm
        url = URL_DETALHE.format(cod, tipo)
        print(f">> Baixando detalhe produto={cod} tipo={tipo}\n   {url}")
        h = baixar(s, url, pausa=args.pausa)
        if not h:
            sys.exit("Nao consegui baixar a pagina de detalhe.")
        Path(f"detalhe_{cod}_{tipo}.html").write_text(h, encoding=ENCODING)
        print(f"   HTML salvo em detalhe_{cod}_{tipo}.html")
        cod_ncm, desc_ncm = extrair_ncm(h)
        print(f"   NCM detectado : {cod_ncm or '(nada)'}")
        print(f"   Descricao NCM : {desc_ncm or '(nada)'}")
        return

    produtos = carregar_listagem(s, args.listagem, args.pausa)
    if args.limite:
        produtos = produtos[:args.limite]
        print(f"   MODO TESTE: {len(produtos)} produtos.")

    # ---- retomada ----
    feitos = set()
    if parcial.exists() and not args.reiniciar:
        try:
            ant = pd.read_csv(parcial, dtype=str)
            feitos = set(ant["codigo_produto"].unique())
            print(f">> Retomando: {len(feitos)} produtos ja coletados serao pulados.")
        except Exception:
            feitos = set()
    if args.reiniciar and parcial.exists():
        parcial.unlink()

    base_tipo = URL_TIPO
    base_det = URL_DETALHE
    pegar_ncm = not args.sem_ncm

    for n, p in enumerate(produtos, 1):
        cod = p["codigo"]
        if cod in feitos:
            continue
        print(f"   [{n}/{len(produtos)}] {cod} - {p['produto_nome'][:55]}")
        h = baixar(s, base_tipo.format(cod), pausa=args.pausa)
        tipos = extrair_tipos(h) if h else []
        if not tipos:
            tipos = [("", "")]  # produto sem tipo listado: registra mesmo assim

        linhas = []
        for ct, dt in tipos:
            ncm = ncm_desc = ""
            if pegar_ncm and ct:
                hd = baixar(s, base_det.format(cod, ct), pausa=args.pausa)
                if hd:
                    ncm, ncm_desc = extrair_ncm(hd)
                time.sleep(args.pausa)
            linhas.append({
                "codigo_produto": cod,
                "produto_nome": p["produto_nome"],
                "base_legal": p["base_legal"],
                "unidade": p["unidade"],
                "data_atualizacao": p["data_atualizacao"],
                "codigo_tipo": ct,
                "descricao_tipo": dt,
                "ncm": ncm,
                "ncm_descricao": ncm_desc,
            })
        # grava incremental (retomavel)
        df_p = pd.DataFrame(linhas)
        df_p.to_csv(parcial, mode="a", header=not parcial.exists(),
                    index=False, encoding="utf-8-sig")
        time.sleep(args.pausa)

    # ---- consolidacao final ----
    base = pd.read_csv(parcial, dtype=str).fillna("")
    base["_busca"] = base.astype(str).agg(" | ".join, axis=1)

    base.to_csv(saida / "suframa_insumos.csv", index=False, encoding="utf-8-sig")
    (base[["codigo_produto", "produto_nome", "base_legal", "unidade", "data_atualizacao"]]
        .drop_duplicates("codigo_produto").sort_values("codigo_produto")
        .to_csv(saida / "suframa_produtos.csv", index=False, encoding="utf-8-sig"))
    try:
        base.to_parquet(saida / "suframa_insumos.parquet", index=False)
    except Exception as e:
        print(f"   (parquet pulado: {e})")
    con = sqlite3.connect(saida / "suframa_insumos.sqlite")
    base.to_sql("insumos", con, if_exists="replace", index=False); con.close()

    print("\n>> Concluido!")
    print(f"   Produtos        : {base['codigo_produto'].nunique()}")
    print(f"   Linhas (tipos)  : {len(base)}")
    if pegar_ncm:
        com_ncm = (base['ncm'].str.len() > 0).sum()
        print(f"   Linhas com NCM  : {com_ncm}")
    print(f"   Arquivos em     : {saida.resolve()}")


def main():
    p = argparse.ArgumentParser(description="Coletor completo da base de insumos da Suframa (produto + tipo + NCM)")
    p.add_argument("--saida", default="dados")
    p.add_argument("--limite", type=int, default=None)
    p.add_argument("--pausa", type=float, default=0.8)
    p.add_argument("--sem-ncm", dest="sem_ncm", action="store_true")
    p.add_argument("--listagem", default=None, help="HTML local da listagem de impressao")
    p.add_argument("--reiniciar", action="store_true")
    p.add_argument("--teste-ncm", nargs=2, metavar=("CODIGO", "TIPO"),
                   help="baixa 1 pagina de detalhe e mostra o NCM detectado")
    a = p.parse_args()
    coletar(a)


if __name__ == "__main__":
    main()
