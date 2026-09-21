#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diagnostico_dou.py
==================
Mostra o que ficou dentro de cada classificacao do dou_suframa.parquet,
para afinar as regras sem precisar rebaixar nada.

Uso:
  python diagnostico_dou.py
  python diagnostico_dou.py --classe outro --n 40
"""

import argparse
import re
import unicodedata
from collections import Counter
from pathlib import Path

import pandas as pd

pd.set_option("display.width", 200)


def sem_acento(t):
    t = unicodedata.normalize("NFKD", str(t))
    return "".join(c for c in t if not unicodedata.combining(c))


def carregar():
    for p in [Path("dou_suframa.parquet"), Path("dados/dou_suframa.parquet")]:
        if p.exists():
            return pd.read_parquet(p).fillna("")
    raise SystemExit("dou_suframa.parquet nao encontrado")


def ementa_curta(texto, n=9):
    """Primeiras palavras da ementa — revela o verbo que abre o ato."""
    corte = re.split(
        r"\bO[A-Z\s]{0,4}SUPERINTENDENTE|\bA\s+SUPERINTENDENTE|"
        r"no\s+uso\s+d[ae]s?\s+atribui|\bRESOLVE\b|\bCONSIDERANDO\b|\bArt\.\s*1",
        str(texto), maxsplit=1, flags=re.I)[0]
    corte = re.sub(r"^.*?\bDE\s+\d{1,2}[º°o]?\s+DE\s+[A-Za-zÀ-ÿ]+\s+DE\s+\d{4}\s*",
                   "", corte, flags=re.I | re.S)
    corte = re.sub(r"\s+", " ", corte).strip()
    return " ".join(corte.split()[:n])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--classe", default="outro")
    ap.add_argument("--n", type=int, default=30)
    a = ap.parse_args()

    df = carregar()

    print("=" * 74)
    print(f"  TOTAL: {len(df)} atos")
    print("=" * 74)
    print("\n  Por classificacao (e quantos tem empresa / codigo de produto):")
    for cls, grupo in df.groupby("classificacao"):
        com_emp = (grupo["empresa"] != "").sum()
        com_cod = (grupo["codigo_produto"] != "").sum()
        print(f"    {cls:20s} {len(grupo):>4d}  | empresa: {com_emp:>4d}"
              f"  | cod.produto: {com_cod:>4d}")

    alvo = df[df["classificacao"] == a.classe]
    if alvo.empty:
        print(f"\n  Nenhum ato na classe '{a.classe}'.")
        return

    print("\n" + "=" * 74)
    print(f"  DENTRO DE '{a.classe.upper()}' ({len(alvo)} atos)")
    print("=" * 74)

    # Agrupa pelas 4 primeiras palavras da ementa: revela padroes de redacao
    print("\n  Padroes de abertura mais comuns:")
    chaves = alvo["texto"].map(lambda t: " ".join(ementa_curta(t, 4).split()[:4]))
    for padrao, qtd in Counter(chaves).most_common(18):
        print(f"    {qtd:>4d}x  {padrao[:70]}")

    # Quais tem empresa ou codigo — esses provavelmente sao atos de projeto
    suspeitos = alvo[(alvo["empresa"] != "") | (alvo["codigo_produto"] != "")]
    print(f"\n  Com empresa ou codigo de produto: {len(suspeitos)}"
          f"  <- possiveis atos de projeto mal classificados")

    print(f"\n  Amostra de {min(a.n, len(alvo))} ementas:")
    for _, r in alvo.head(a.n).iterrows():
        em = ementa_curta(r["texto"], 16)
        marca = "*" if (r["empresa"] or r["codigo_produto"]) else " "
        print(f"   {marca} [{r['data_publicacao']}] {em[:96]}")

    # Varredura por termos de encerramento que talvez nao estejam nas regras
    print("\n" + "=" * 74)
    print("  VARREDURA: termos de encerramento em TODA a base")
    print("=" * 74)
    termos = {
        "caducidade": r"caducidade",
        "extingue/extincao": r"exting|extin[çc][ãa]o",
        "cassa/cassacao": r"\bcassa|cassa[çc][ãa]o",
        "declara a perda": r"perda\s+d[eo]s?\s+(?:direito|benef|incentiv)",
        "desenquadra": r"desenquadr",
        "exclui": r"\bexclui|exclus[ãa]o\s+d[eo]",
        "encerra": r"\bencerra",
        "cancela": r"\bcancel",
    }
    for rotulo, padrao in termos.items():
        # procura so na ementa, para nao contar clausula padrao
        ements = df["texto"].map(lambda t: sem_acento(ementa_curta(t, 25)).lower())
        n = ements.str.contains(padrao, regex=True, na=False).sum()
        print(f"    {rotulo:22s} aparece na ementa de {n:>4d} atos")


if __name__ == "__main__":
    main()
