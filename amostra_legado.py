#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
amostra_legado.py
=================
Diagnostica a coleta do acervo antigo, olhando dois riscos:

  1. TRUNCAMENTO DA BUSCA. O acervo mostra os resultados em telas, e se
     houver paginacao nao tratada perdemos parte de cada mes. O indicio e
     estatistico: meses que param exatamente no mesmo numero de paginas
     (10, por exemplo) provavelmente foram cortados, nao terminaram.

  2. EXTRACAO IMPRECISA. Na pagina de jornal os atos vem misturados e
     diagramados em colunas; o corte pelo cabecalho pode partir um ato ao
     meio. O sintoma e registro sem empresa ou classificado como "outro".

Nao acessa a rede: le o parquet ja coletado.

Uso:
  python amostra_legado.py
  python amostra_legado.py --chars 1800
"""

import argparse
import re
from collections import Counter
from pathlib import Path

import pandas as pd


ap = argparse.ArgumentParser()
ap.add_argument("--chars", type=int, default=1200)
a = ap.parse_args()


def carregar():
    for p in [Path("dou_legado.parquet"), Path("dados/dou_legado.parquet")]:
        if p.exists():
            return pd.read_parquet(p).fillna("")
    raise SystemExit("dou_legado.parquet nao encontrado")


df = carregar()
df["_dt"] = pd.to_datetime(df["data_publicacao"], format="%d/%m/%Y",
                           errors="coerce")

print("=" * 78)
print(f"  ACERVO ANTIGO — {len(df)} registros")
print("=" * 78)
print(f"  com empresa      : {(df['empresa'] != '').sum():>5d}"
      f"  ({(df['empresa'] != '').mean():.0%})")
print(f"  com cod. produto : {(df['codigo_produto'] != '').sum():>5d}"
      f"  ({(df['codigo_produto'] != '').mean():.0%})")
print(f"  com CNPJ         : {(df['cnpj'] != '').sum():>5d}")
print(f"  com inscricao    : {(df['inscricao_suframa'] != '').sum():>5d}")

# ---------------------------------------------------------------------------
print("\n" + "=" * 78)
print("  1. A BUSCA FOI TRUNCADA?")
print("=" * 78)

paginas_mes = (df.dropna(subset=["_dt"])
                 .groupby([df["_dt"].dt.year, df["_dt"].dt.month])["pagina"]
                 .nunique())
print(f"  Meses com dados: {len(paginas_mes)} (de 96 possiveis em 2008-2015)")
print("\n  Distribuicao de paginas por mes:")
cont = Counter(paginas_mes.values)
for qtd in sorted(cont):
    marca = "  <-- suspeito de corte" if cont[qtd] >= 4 and qtd >= 8 else ""
    print(f"    {qtd:>3d} paginas: {cont[qtd]:>3d} meses{marca}")

topo = max(cont) if cont else 0
n_no_topo = cont.get(topo, 0)
print(f"\n  Maximo observado: {topo} paginas num mes, "
      f"em {n_no_topo} mes(es)")
if n_no_topo >= 4:
    print("  >>> Varios meses parando no mesmo teto indica PAGINACAO nao")
    print("      tratada: a busca corta a lista e nao estamos vendo o resto.")
else:
    print("  >>> Sem teto repetido: provavelmente nao ha truncamento.")

print("\n  Aprovacoes por ano:")
apr = df[df["classificacao"] == "aprovacao"].dropna(subset=["_dt"])
for ano, n in apr.groupby(apr["_dt"].dt.year).size().items():
    print(f"    {ano}: {n:>4d}  {'#' * min(int(n / 2), 50)}")

# ---------------------------------------------------------------------------
print("\n" + "=" * 78)
print("  2. QUALIDADE DA EXTRACAO — amostras do texto cru")
print("=" * 78)

casos = [
    ("APROVACAO sem empresa",
     df[(df["classificacao"] == "aprovacao") & (df["empresa"] == "")]),
    ("OUTRO, mas com codigo de produto (provavel ato de projeto)",
     df[(df["classificacao"] == "outro") & (df["codigo_produto"] != "")]),
    ("OUTRO sem codigo",
     df[(df["classificacao"] == "outro") & (df["codigo_produto"] == "")]),
    ("APROVACAO completa (para comparar)",
     df[(df["classificacao"] == "aprovacao") & (df["empresa"] != "")
        & (df["codigo_produto"] != "")]),
]

for titulo, g in casos:
    print("\n" + "-" * 78)
    print(f"  {titulo}  —  {len(g)} registros")
    print("-" * 78)
    if g.empty:
        print("  (nenhum)")
        continue
    for _, r in g.head(2).iterrows():
        print(f"\n  [{r['data_publicacao']}] pag {r['pagina']} | "
              f"{r['titulo'][:40]}")
        print(f"  empresa='{r['empresa'][:50]}' cod='{r['codigo_produto']}' "
              f"tipo='{r['tipo_projeto']}'")
        print(f"  texto ({len(r['texto_item'])} chars):")
        print(f"    {r['texto_item'][:a.chars]}")

# ---------------------------------------------------------------------------
print("\n" + "=" * 78)
print("  3. TAMANHO DOS BLOCOS")
print("=" * 78)
df["_tam"] = df["texto_item"].str.len()
print(f"  mediana: {int(df['_tam'].median())} | "
      f"minimo: {int(df['_tam'].min())} | maximo: {int(df['_tam'].max())}")
curtos = (df["_tam"] < 400).sum()
print(f"  blocos com menos de 400 caracteres: {curtos} "
      f"({curtos / len(df):.0%})")
print("  Bloco muito curto costuma ser ato partido pela diagramacao em")
print("  colunas — o cabecalho ficou num bloco e o corpo em outro.")
