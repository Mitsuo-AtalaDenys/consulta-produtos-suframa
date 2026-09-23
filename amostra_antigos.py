#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
amostra_antigos.py
==================
Mostra o texto cru de alguns atos de 2016-2021 para revelar a redacao da
epoca, que difere da atual e por isso escapa das regras de extracao.

Nao acessa a rede: le o parquet ja coletado.

Uso:
  python amostra_antigos.py
  python amostra_antigos.py --chars 2000
"""

import argparse
from pathlib import Path

import pandas as pd


def carregar():
    for p in [Path("dou_suframa.parquet"), Path("dados/dou_suframa.parquet")]:
        if p.exists():
            return pd.read_parquet(p).fillna("")
    raise SystemExit("dou_suframa.parquet nao encontrado")


ap = argparse.ArgumentParser()
ap.add_argument("--chars", type=int, default=1400)
a = ap.parse_args()

df = carregar()
df["_dt"] = pd.to_datetime(df["data_publicacao"], format="%d/%m/%Y",
                           errors="coerce")
antigos = df[df["_dt"].dt.year.between(2016, 2021)]

print("=" * 78)
print(f"  {len(antigos)} registros de 2016-2021")
print("=" * 78)
print("\n  Situacao dos campos extraidos nesse periodo:")
print(f"    com empresa:        {(antigos['empresa'] != '').sum()}")
print(f"    com cod. produto:   {(antigos['codigo_produto'] != '').sum()}")
print(f"    com CNPJ:           {(antigos['cnpj'] != '').sum()}")
print(f"    com inscricao:      {(antigos['inscricao_suframa'] != '').sum()}")
print(f"    com tipo de projeto:{(antigos['tipo_projeto'] != '').sum()}")

casos = [
    ("APROVACAO COM codigo de produto",
     antigos[(antigos["classificacao"] == "aprovacao")
             & (antigos["codigo_produto"] != "")]),
    ("APROVACAO SEM codigo de produto",
     antigos[(antigos["classificacao"] == "aprovacao")
             & (antigos["codigo_produto"] == "")]),
    ("APROVACAO com nome de empresa truncado",
     antigos[(antigos["classificacao"] == "aprovacao")
             & (antigos["empresa"].str.contains(r"[(,]\s*$|\bcom$|\bc$",
                                                regex=True, na=False))]),
    ("Classificado como OUTRO",
     antigos[antigos["classificacao"] == "outro"]),
    ("CANCELAMENTO",
     antigos[antigos["classificacao"] == "cancelamento"]),
]

for titulo, grupo in casos:
    print("\n" + "=" * 78)
    print(f"  {titulo}  ({len(grupo)} no total)")
    print("=" * 78)
    if grupo.empty:
        print("  (nenhum)")
        continue
    for _, r in grupo.head(2).iterrows():
        print(f"\n  [{r['data_publicacao']}] {r['titulo'][:66]}")
        print(f"  empresa extraida : '{r['empresa']}'")
        print(f"  codigo / produto : '{r['codigo_produto']}' / '{r['produto'][:50]}'")
        print(f"  tipo de projeto  : '{r['tipo_projeto']}'")
        print(f"  url              : {r['url']}")
        print("  --- texto cru ---")
        print("  " + r["texto"][:a.chars].replace("\n", " "))
        print()
