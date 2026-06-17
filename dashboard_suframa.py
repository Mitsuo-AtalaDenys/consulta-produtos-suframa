#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dashboard_suframa.py
====================
App de consulta da base completa de Insumos da Suframa
(1.768 produtos x tipos, com NCM e descricao da NCM).

Le o arquivo suframa_insumos.parquet (na mesma pasta) gerado pelo
coletar_suframa.py. Roda local com:  streamlit run dashboard_suframa.py
e no Streamlit Cloud lendo o parquet do repositorio.

Senha opcional: defina em Settings -> Secrets do app:
    senha = "suaSenha"
Sem esse segredo, o acesso e livre.
"""

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Consulta de Insumos · SUFRAMA",
                   page_icon="🔎", layout="wide")

ARQUIVO = "suframa_insumos.parquet"

COLUNAS = {
    "codigo_produto": "Código",
    "produto_nome": "Produto",
    "codigo_tipo": "Tipo",
    "descricao_tipo": "Descrição do Tipo",
    "ncm": "NCM",
    "ncm_descricao": "Descrição da NCM",
    "base_legal": "Base Legal",
    "unidade": "Unidade",
    "data_atualizacao": "Atualização",
}


# ---------------------------------------------------------------------------
def checar_senha():
    """Bloqueia o app com senha se houver 'senha' nos Secrets. Caso contrario,
    o acesso e livre."""
    try:
        senha = st.secrets.get("senha", None)
    except Exception:
        senha = None
    if not senha:
        return
    if st.session_state.get("_ok"):
        return
    digitada = st.sidebar.text_input("Senha de acesso", type="password")
    if digitada == senha:
        st.session_state["_ok"] = True
    else:
        st.info("Digite a senha de acesso na barra lateral para continuar.")
        st.stop()


@st.cache_data(show_spinner="Carregando a base...")
def carregar():
    df = pd.read_parquet(ARQUIVO)
    # garante que as colunas esperadas existam
    for c in COLUNAS:
        if c not in df.columns:
            df[c] = ""
    df = df.fillna("")
    # coluna de busca: usa a existente ou monta uma na hora
    if "_busca" not in df.columns:
        df["_busca"] = df[list(COLUNAS)].astype(str).agg(" | ".join, axis=1)
    df["_busca_low"] = df["_busca"].str.lower()
    return df


def filtrar(df, termo, unidades, so_ncm):
    out = df
    if termo.strip():
        for palavra in termo.lower().split():
            out = out[out["_busca_low"].str.contains(palavra, regex=False)]
    if unidades:
        out = out[out["unidade"].isin(unidades)]
    if so_ncm:
        out = out[out["ncm"].str.len() > 0]
    return out


# ---------------------------------------------------------------------------
checar_senha()
df = carregar()

st.title("🔎 Consulta de Insumos · SUFRAMA")
st.caption(
    f"Base completa: {df['codigo_produto'].nunique():,} produtos · "
    f"{len(df):,} tipos · {(df['ncm'].str.len() > 0).sum():,} com NCM"
    .replace(",", ".")
)

# ----- barra lateral: filtros -----
with st.sidebar:
    st.header("Filtros")
    unidades = st.multiselect("Unidade", sorted(u for u in df["unidade"].unique() if u))
    so_ncm = st.checkbox("Somente itens com NCM", value=False)
    st.divider()
    st.caption("Dica: a busca procura ao mesmo tempo no nome do produto, "
               "no tipo, na NCM e na base legal. Pode digitar várias "
               "palavras (ex.: *parafuso ferro*).")

# ----- busca principal -----
termo = st.text_input("Buscar produto, tipo, NCM ou base legal",
                      placeholder="ex.: parafuso, porca, 8473, condicionador de ar...")

res = filtrar(df, termo, unidades, so_ncm)

c1, c2, c3 = st.columns(3)
c1.metric("Produtos", f"{res['codigo_produto'].nunique():,}".replace(",", "."))
c2.metric("Linhas (tipos)", f"{len(res):,}".replace(",", "."))
c3.metric("Com NCM", f"{(res['ncm'].str.len() > 0).sum():,}".replace(",", "."))

if res.empty:
    st.warning("Nenhum resultado. Tente outra palavra ou remova filtros.")
else:
    tabela = res[list(COLUNAS)].rename(columns=COLUNAS)
    st.dataframe(
        tabela,
        use_container_width=True,
        hide_index=True,
        height=560,
        column_config={
            "Código": st.column_config.TextColumn(width="small"),
            "Produto": st.column_config.TextColumn(width="large"),
            "Tipo": st.column_config.TextColumn(width="small"),
            "Descrição do Tipo": st.column_config.TextColumn(width="medium"),
            "NCM": st.column_config.TextColumn(width="small"),
            "Descrição da NCM": st.column_config.TextColumn(width="large"),
            "Base Legal": st.column_config.TextColumn(width="medium"),
            "Unidade": st.column_config.TextColumn(width="small"),
            "Atualização": st.column_config.TextColumn(width="small"),
        },
    )

    csv = tabela.to_csv(index=False).encode("utf-8-sig")
    st.download_button("⬇️ Baixar resultado (CSV)", data=csv,
                       file_name="consulta_suframa.csv", mime="text/csv")
