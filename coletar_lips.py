#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
coletar_lips.py
===============
Coleta os insumos da LIPS (Lista de Insumos Padrão Suframa) vinculados
a cada produto-padrão. Complementa o coletor_suframa.py que coleta
produtos e tipos — este coleta os INSUMOS autorizados por produto.

Fonte: EST_PoloProdutoTipo_imp.asp?produto=XXXX  (versão para impressão)
Encoding: windows-1252

Colunas extraídas por insumo:
  produto_id, produto_nome, ncm, destaque, descricao_suframa,
  controlado_ppb, comentario

Uso:
  # Coleta completa (lê os produto_ids do parquet existente)
  python coletar_lips.py

  # Coleta de produto específico (teste)
  python coletar_lips.py --produto 0003

  # Retomar coleta interrompida
  python coletar_lips.py --retomar

  # Coleta com lista manual de códigos (sem depender do parquet)
  python coletar_lips.py --lista-produtos 0001 0003 0005

Requer: requests, beautifulsoup4, lxml, pandas, pyarrow
"""

import argparse
import csv
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests
import urllib3
from bs4 import BeautifulSoup

# Desabilita aviso de SSL (redes corporativas com inspeção SSL)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
BASE_URL = (
    "http://wwws.suframa.gov.br/servicos/estrangeiro/consultas/"
    "listageminsumos/EST_PoloProdutoTipo_imp.asp?produto={cod}"
)
ENCODING = "windows-1252"
PASTA_DADOS = Path("dados")
ARQUIVO_PARCIAL = PASTA_DADOS / "_parcial_lips.csv"
ARQUIVO_STATUS = PASTA_DADOS / "_status_lips.csv"
ARQUIVO_FINAL_CSV = PASTA_DADOS / "suframa_lips.csv"
ARQUIVO_FINAL_PARQUET = PASTA_DADOS / "suframa_lips.parquet"
COLUNAS = [
    "produto_id",
    "produto_nome",
    "ncm",
    "destaque",
    "descricao_suframa",
    "controlado_ppb",
    "comentario",
]
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------
def carregar_codigos_produtos(parquet_path: str = "suframa_insumos.parquet"):
    """Carrega os códigos de produto do parquet existente.

    O nome da coluna varia entre as bases (`codigo_produto`, `produto_id`...),
    então ele é detectado em vez de assumido.
    """
    import pandas as pd

    candidatos_coluna = [
        "codigo_produto",
        "produto_id",
        "cod_produto",
        "codigo",
        "produto",
        "cod",
    ]

    # Tenta vários caminhos possíveis
    candidatos = [
        Path(parquet_path),
        PASTA_DADOS / parquet_path,
        Path("suframa_insumos.parquet"),
    ]
    for p in candidatos:
        if not p.exists():
            continue

        df = pd.read_parquet(p)
        mapa = {str(c).lower().strip(): c for c in df.columns}
        coluna = next((mapa[c] for c in candidatos_coluna if c in mapa), None)

        if coluna is None:
            print(f"ERRO: nenhuma coluna de código de produto encontrada em {p}")
            print(f"  Colunas disponíveis: {list(df.columns)}")
            sys.exit(1)

        # Normaliza para 4 dígitos com zeros à esquerda (formato da URL)
        codigos = (
            df[coluna].dropna().astype(str).str.strip().str.zfill(4).unique().tolist()
        )
        codigos = sorted(c for c in codigos if c and c.lower() != coluna.lower())

        print(f"  Coluna de código detectada: '{coluna}'")
        print(f"  {len(codigos)} códigos de produto encontrados em {p}")
        return codigos

    print("ERRO: Nenhum arquivo parquet de produtos encontrado.")
    print("  Opções:")
    print("    1) Coloque suframa_insumos.parquet na pasta dados/")
    print("    2) Use --lista-produtos 0001 0003 ...")
    sys.exit(1)


def ler_status():
    """Lê o registro de status. Retorna {produto_id: status}.

    Status possíveis:
      ok     — coletado, tem insumos
      vazio  — página existe mas não há insumos cadastrados
      falha  — erro de rede/download; precisa ser refeito
    """
    if not ARQUIVO_STATUS.exists():
        return {}
    status = {}
    with open(ARQUIVO_STATUS, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            status[row["produto_id"]] = row["status"]
    return status


def semear_status_do_parcial():
    """Cria o registro de status a partir de um parcial antigo, sem status.

    Marca como 'ok' tudo que já tem insumos gravados, para não recoletar.
    """
    if ARQUIVO_STATUS.exists() or not ARQUIVO_PARCIAL.exists():
        return

    contagem = {}
    with open(ARQUIVO_PARCIAL, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pid = (row.get("produto_id") or "").strip()
            if pid and pid != "produto_id":
                contagem[pid] = contagem.get(pid, 0) + 1

    if not contagem:
        return

    with open(ARQUIVO_STATUS, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["produto_id", "status", "n_insumos"])
        w.writeheader()
        for pid, n in sorted(contagem.items()):
            w.writerow({"produto_id": pid, "status": "ok", "n_insumos": n})

    print(f"  Registro de status criado a partir do parcial: {len(contagem)} produtos")


def extrair_insumos(html: str, produto_cod: str):
    """Extrai os insumos de uma página de produto."""
    soup = BeautifulSoup(html, "lxml")

    # Extrai nome do produto.
    # O HTML usa <b>Produto</b>: — o get_text insere espaço antes dos ":",
    # por isso o \s* entre "Produto" e ":".
    texto = soup.get_text(" ", strip=True)
    produto_nome = ""
    for padrao in (
        r"Produto\s*:\s*(.+?)\s*Código\s*:",
        r"Produto\s*:\s*(.+?)\s*NCM\b",
        r"Produto\s*:\s*(.+)$",
    ):
        m = re.search(padrao, texto)
        if m and m.group(1).strip():
            produto_nome = " ".join(m.group(1).split())
            break

    # Encontra o cabeçalho "NCM" para localizar a tabela de dados
    insumos = []
    ncm_header = None
    for td in soup.find_all("td"):
        if td.get_text(strip=True) == "NCM":
            ncm_header = td
            break

    if not ncm_header:
        return produto_nome, insumos

    # A tabela que contém o cabeçalho
    tabela = ncm_header.find_parent("table")
    if not tabela:
        return produto_nome, insumos

    rows = tabela.find_all("tr")
    # Encontra o índice da linha do cabeçalho
    header_idx = -1
    for i, tr in enumerate(rows):
        tds = tr.find_all("td")
        if any(td.get_text(strip=True) == "NCM" for td in tds):
            header_idx = i
            break

    if header_idx < 0:
        return produto_nome, insumos

    # Processa as linhas de dados
    for tr in rows[header_idx + 1 :]:
        tds = tr.find_all("td")
        # Filtra linhas vazias/separadoras (menos de 4 células)
        if len(tds) < 4:
            continue

        ncm = tds[0].get_text(strip=True).replace(".", "")
        destaque = tds[1].get_text(strip=True)
        descricao = " ".join(tds[2].get_text(" ", strip=True).split())
        controlado = tds[3].get_text(strip=True) if len(tds) > 3 else ""
        comentario = " ".join(tds[4].get_text(" ", strip=True).split()) if len(tds) > 4 else ""

        # Valida: NCM deve ser 8 dígitos
        if not re.fullmatch(r"\d{8}", ncm):
            continue

        insumos.append(
            {
                "produto_id": produto_cod,
                "produto_nome": produto_nome,
                "ncm": ncm,
                "destaque": destaque,
                "descricao_suframa": descricao,
                "controlado_ppb": controlado,
                "comentario": comentario,
            }
        )

    return produto_nome, insumos


def baixar_pagina(produto_cod: str, session: requests.Session, tentativas: int = 4):
    """Baixa a página de insumos de um produto, com retries e espera crescente."""
    url = BASE_URL.format(cod=produto_cod)
    for t in range(tentativas):
        try:
            r = session.get(url, timeout=60, verify=False, headers=HEADERS)
            r.encoding = ENCODING
            if r.status_code == 200:
                return r.text
            print(f"[HTTP {r.status_code}]", end=" ", flush=True)
        except requests.RequestException:
            print(f"[erro {t + 1}/{tentativas}]", end=" ", flush=True)
        if t < tentativas - 1:
            time.sleep(3 * (t + 1))
    return None


# ---------------------------------------------------------------------------
# Coleta principal
# ---------------------------------------------------------------------------
def coletar(codigos: list[str], pausa: float = 0.8, retomar: bool = False):
    """Coleta os insumos LIPS para cada produto."""
    PASTA_DADOS.mkdir(exist_ok=True)

    # Se há um parcial antigo sem registro de status, cria o registro
    semear_status_do_parcial()

    # Filtra o que já foi resolvido (coletado ou confirmado vazio).
    # Produtos com status 'falha' voltam para a fila.
    ja_feitos = set()
    if retomar:
        status = ler_status()
        ja_feitos = {p for p, s in status.items() if s in ("ok", "vazio")}
        n_falhas = sum(1 for s in status.values() if s == "falha")
        print(f"  Já resolvidos: {len(ja_feitos)} · Falhas a refazer: {n_falhas}")

    pendentes = [c for c in codigos if c not in ja_feitos]
    if not pendentes:
        print("  Todos os produtos já foram coletados!")
        consolidar()
        return

    print(f"\n  Produtos a coletar: {len(pendentes)}")
    print(f"  Pausa entre requisições: {pausa}s\n")

    precisa_cabecalho = (
        not ARQUIVO_PARCIAL.exists() or ARQUIVO_PARCIAL.stat().st_size == 0
    )
    precisa_cab_status = (
        not ARQUIVO_STATUS.exists() or ARQUIVO_STATUS.stat().st_size == 0
    )

    with open(ARQUIVO_PARCIAL, "a", newline="", encoding="utf-8") as f, open(
        ARQUIVO_STATUS, "a", newline="", encoding="utf-8"
    ) as fs:
        writer = csv.DictWriter(f, fieldnames=COLUNAS)
        if precisa_cabecalho:
            writer.writeheader()

        w_status = csv.DictWriter(
            fs, fieldnames=["produto_id", "status", "n_insumos"]
        )
        if precisa_cab_status:
            w_status.writeheader()

        session = requests.Session()
        total_insumos = 0
        n_ok = n_vazio = n_falha = 0
        inicio = time.time()

        for i, cod in enumerate(pendentes, 1):
            print(f"  [{i}/{len(pendentes)}] Produto {cod}...", end=" ", flush=True)

            html = baixar_pagina(cod, session)
            if not html:
                print("FALHOU")
                w_status.writerow(
                    {"produto_id": cod, "status": "falha", "n_insumos": 0}
                )
                fs.flush()
                n_falha += 1
                time.sleep(pausa)
                continue

            nome, insumos = extrair_insumos(html, cod)
            for ins in insumos:
                writer.writerow(ins)
            f.flush()

            situacao = "ok" if insumos else "vazio"
            w_status.writerow(
                {"produto_id": cod, "status": situacao, "n_insumos": len(insumos)}
            )
            fs.flush()

            if insumos:
                n_ok += 1
            else:
                n_vazio += 1

            total_insumos += len(insumos)
            nome_curto = nome[:50] if nome else "(nome não capturado)"
            marca = "—" if not insumos else "→"
            print(f"{nome_curto} {marca} {len(insumos)} insumos")

            if i % 100 == 0 and i < len(pendentes):
                decorrido = time.time() - inicio
                restante = (decorrido / i) * (len(pendentes) - i)
                print(
                    f"\n  ── {i}/{len(pendentes)} · "
                    f"{total_insumos:,} insumos · ".replace(",", ".")
                    + f"{n_falha} falhas · ~{restante / 60:.0f} min restantes ──\n"
                )

            if i < len(pendentes):
                time.sleep(pausa)

    print(f"\n  Com insumos: {n_ok} · Sem insumos: {n_vazio} · Falhas: {n_falha}")
    if n_falha:
        print(f"  Para refazer as {n_falha} falhas: python coletar_lips.py --retomar")
    consolidar()


def consolidar():
    """Converte o CSV parcial em Parquet + CSV final."""
    import pandas as pd

    if not ARQUIVO_PARCIAL.exists():
        print("  Nenhum dado parcial para consolidar.")
        return

    df = pd.read_csv(ARQUIVO_PARCIAL, dtype=str)

    # Remove eventuais linhas de cabeçalho repetidas no meio dos dados
    df = df[df["produto_id"] != "produto_id"]

    # Mantém só linhas com NCM válido (8 dígitos)
    df = df[df["ncm"].notna()]
    df = df[df["ncm"].str.fullmatch(r"\d{8}", na=False)]
    df = df.drop_duplicates()

    # Nulos viram string vazia — evita erro de tipo no dashboard
    df = df.fillna("").astype(str)

    # Salva os arquivos finais
    df.to_csv(ARQUIVO_FINAL_CSV, index=False, encoding="utf-8")
    df.to_parquet(ARQUIVO_FINAL_PARQUET, index=False)

    n_prod = df["produto_id"].nunique()
    n_ins = len(df)
    n_ctrl = (df["controlado_ppb"] == "SIM").sum()

    print(f"\n  ─── Consolidação ───")
    print(f"  Produtos:           {n_prod}")
    print(f"  Insumos:            {n_ins:,}".replace(",", "."))
    print(f"  Controlados (PPB):  {n_ctrl:,}".replace(",", "."))
    print(f"  CSV:     {ARQUIVO_FINAL_CSV}")
    print(f"  Parquet: {ARQUIVO_FINAL_PARQUET}")

    # Copia o parquet para a raiz (para o Streamlit encontrar)
    destino_raiz = Path("suframa_lips.parquet")
    import shutil
    shutil.copy2(ARQUIVO_FINAL_PARQUET, destino_raiz)
    print(f"  Cópia:   {destino_raiz}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Coletor de insumos LIPS da Suframa"
    )
    parser.add_argument(
        "--produto",
        type=str,
        help="Código de UM produto para testar (ex: 0003)",
    )
    parser.add_argument(
        "--lista-produtos",
        nargs="+",
        type=str,
        help="Lista manual de códigos de produto",
    )
    parser.add_argument(
        "--retomar",
        action="store_true",
        help="Retoma coleta interrompida",
    )
    parser.add_argument(
        "--pausa",
        type=float,
        default=0.8,
        help="Segundos entre requisições (padrão: 0.8)",
    )
    parser.add_argument(
        "--parquet",
        type=str,
        default="suframa_insumos.parquet",
        help="Caminho do parquet de produtos (para obter a lista de códigos)",
    )
    parser.add_argument(
        "--reiniciar",
        action="store_true",
        help="Apaga dados parciais e começa do zero",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  COLETOR LIPS — Insumos por Produto (Suframa)")
    print("=" * 60)

    if args.reiniciar:
        for arq in (ARQUIVO_PARCIAL, ARQUIVO_STATUS):
            if arq.exists():
                arq.unlink()
        print("  Dados parciais e registro de status apagados.\n")

    if args.produto:
        # Teste com um produto
        codigos = [args.produto.zfill(4)]
        print(f"\n  Modo teste: produto {codigos[0]}")
    elif args.lista_produtos:
        codigos = [c.zfill(4) for c in args.lista_produtos]
        print(f"\n  Lista manual: {len(codigos)} produtos")
    else:
        # Lê do parquet existente
        print("\n  Carregando lista de produtos do parquet...")
        codigos = carregar_codigos_produtos(args.parquet)

    # Retomar é o padrão: só recomeça do zero com --reiniciar.
    # Assim uma interrupção nunca faz perder o trabalho já feito.
    retomar = not args.reiniciar
    coletar(codigos, pausa=args.pausa, retomar=retomar)


if __name__ == "__main__":
    main()
