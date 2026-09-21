#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diagnostico_texto.py
====================
Investiga por que 173 atos ficaram com ementa vazia e ajuda a validar se a
coleta pegou de fato todos os projetos aprovados publicados no DOU.

Uso:
  python diagnostico_texto.py
"""

from pathlib import Path

import pandas as pd


def carregar():
    for p in [Path("dou_suframa.parquet"), Path("dados/dou_suframa.parquet")]:
        if p.exists():
            return pd.read_parquet(p).fillna("")
    raise SystemExit("dou_suframa.parquet nao encontrado")


df = carregar()
df["tam"] = df["texto"].str.len()

print("=" * 76)
print("  1. TAMANHO DO TEXTO EXTRAIDO, POR CLASSIFICACAO")
print("=" * 76)
print(f"  {'classificacao':22s} {'atos':>5s} {'vazio':>7s} {'curto':>7s} "
      f"{'mediana':>9s}")
print("  " + "-" * 60)
for cls, g in df.groupby("classificacao"):
    vazio = (g["tam"] == 0).sum()
    curto = ((g["tam"] > 0) & (g["tam"] < 300)).sum()
    print(f"  {cls:22s} {len(g):>5d} {vazio:>7d} {curto:>7d} "
          f"{int(g['tam'].median()):>9d}")

print(f"\n  TOTAL com texto vazio: {(df['tam'] == 0).sum()}")
print(f"  TOTAL com texto < 300 caracteres: {((df['tam'] > 0) & (df['tam'] < 300)).sum()}")

print("\n" + "=" * 76)
print("  2. AMOSTRA DOS ATOS PROBLEMATICOS (classe 'outro', texto curto/vazio)")
print("=" * 76)
prob = df[(df["classificacao"] == "outro") & (df["tam"] < 300)]
print(f"  {len(prob)} atos nessa situacao\n")
for _, r in prob.head(8).iterrows():
    print(f"  [{r['data_publicacao']}] {r['tipo_ato']} | {r['tam']} chars")
    print(f"     titulo: {r['titulo'][:88]}")
    print(f"     texto : {repr(r['texto'][:150])}")
    print(f"     url   : {r['url']}")
    print()

print("=" * 76)
print("  3. OS 3 CANCELAMENTOS ENCONTRADOS")
print("=" * 76)
for _, r in df[df["classificacao"] == "cancelamento"].iterrows():
    print(f"  [{r['data_publicacao']}] {r['titulo'][:70]}")
    print(f"     empresa: {r['empresa'][:60] or '-'} | produto: {r['codigo_produto'] or '-'}")
    print(f"     {r['texto'][:230]}")
    print()

print("=" * 76)
print("  4. APROVACOES POR MES (para conferir se ha buraco na serie)")
print("=" * 76)
ap = df[df["classificacao"] == "aprovacao"].copy()
ap["dt"] = pd.to_datetime(ap["data_publicacao"], format="%d/%m/%Y", errors="coerce")
serie = ap.dropna(subset=["dt"]).groupby(ap["dt"].dt.to_period("M")).size()
for mes, qtd in serie.items():
    barra = "#" * min(int(qtd), 55)
    print(f"  {mes}  {qtd:>3d}  {barra}")
print(f"\n  Periodo coberto: {serie.index.min()} a {serie.index.max()}")
print(f"  Media por mes: {serie.mean():.1f}")

print("\n" + "=" * 76)
print("  5. AMOSTRA DE APROVACOES PARA CONFERENCIA MANUAL NO DOU")
print("=" * 76)
amostra = ap[(ap["empresa"] != "") & (ap["codigo_produto"] != "")].head(6)
for _, r in amostra.iterrows():
    print(f"  [{r['data_publicacao']}] {r['empresa'][:52]}")
    print(f"     produto {r['codigo_produto']} | {r['tipo_projeto'] or '-'} "
          f"| CNPJ {r['cnpj'] or '-'}")
    print(f"     {r['url']}")
    print()

print("=" * 76)
print("  6. TIPOS DE PROJETO APROVADOS")
print("=" * 76)
for k, v in ap["tipo_projeto"].replace("", "(nao identificado)").value_counts().items():
    print(f"  {v:>4d}x  {k}")
