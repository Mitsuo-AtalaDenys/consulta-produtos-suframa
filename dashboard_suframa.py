#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dashboard_suframa.py
====================
App de consulta das bases da Suframa, com duas camadas:

  1. Produtos / Tipos  — base de produtos-padrão (suframa_insumos.parquet)
  2. Insumos por Produto — Listagem Padrão de Insumos (suframa_lips.parquet)

Identidade visual Atala & Denys: burgundy, bege e tons crus.
"""

from pathlib import Path
import base64
import unicodedata
from io import BytesIO

import pandas as pd
import streamlit as st

# -------- Configuracao da pagina ------------------------------------------
st.set_page_config(page_title="Consulta de Produtos · Atala & Denys",
                   page_icon="🔎", layout="wide")

ARQUIVO = "suframa_insumos.parquet"
ARQUIVO_LIPS = "suframa_lips.parquet"
LOGO_CANDIDATOS = [
    "logo_atala_denys.png",
    "logo_atala_denys.jpeg",
    "logo_atala_denys.jpg",
    "logo_atala_denys.PNG",
    "logo_atala_denys.JPEG",
    "logo_atala_denys.JPG",
]

# -------- Paleta da casa --------------------------------------------------
BURGUNDY_DARK = "#25171A"
BURGUNDY = "#3D1E24"
BURGUNDY_LIGHT = "#6A343E"
SAND = "#DFD4C4"
CREAM = "#F3F0EA"
TEXT_LIGHT = "#F5EFE7"
GOLD = "#C5A78A"

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

COLUNAS_LIPS = {
    "produto_id": "Código",
    "produto_nome": "Produto",
    "ncm": "NCM",
    "destaque": "Destaque",
    "descricao_suframa": "Descrição Suframa",
    "controlado_ppb": "Controlado (PPB)",
    "comentario": "Comentário",
}


# -------- Estilo (CSS) ----------------------------------------------------
def aplicar_estilo():
    st.markdown(f"""
    <style>
      .stApp {{
        background: linear-gradient(180deg, {BURGUNDY_DARK} 0%, {BURGUNDY} 100%);
        color: {TEXT_LIGHT};
      }}
      [data-testid="stSidebar"] {{
        background-color: {BURGUNDY_DARK};
        border-right: 1px solid {BURGUNDY_LIGHT};
      }}
      [data-testid="stSidebar"] * {{ color: {TEXT_LIGHT} !important; }}

      /* Campo de senha (sidebar) - fundo claro, texto escuro, sempre legivel */
      [data-testid="stSidebar"] .stTextInput input {{
        background-color: {CREAM} !important;
        color: {BURGUNDY_DARK} !important;
        border: 1px solid {SAND} !important;
        -webkit-text-fill-color: {BURGUNDY_DARK} !important;
        caret-color: {BURGUNDY_DARK} !important;
      }}
      [data-testid="stSidebar"] .stTextInput input::placeholder {{
        color: {BURGUNDY_LIGHT} !important;
        opacity: 0.7;
      }}
      /* Botao de olho (mostrar/ocultar senha) */
      [data-testid="stSidebar"] .stTextInput button svg {{
        fill: {BURGUNDY_DARK} !important;
      }}

      /* Multiselect "Unidade" (sidebar) - caixa e texto digitado */
      [data-testid="stSidebar"] [data-baseweb="select"] > div {{
        background-color: {CREAM} !important;
        border: 1px solid {SAND} !important;
      }}
      [data-testid="stSidebar"] [data-baseweb="select"] * {{
        color: {BURGUNDY_DARK} !important;
        -webkit-text-fill-color: {BURGUNDY_DARK} !important;
      }}
      [data-testid="stSidebar"] [data-baseweb="select"] input {{
        caret-color: {BURGUNDY_DARK} !important;
      }}
      /* Lista de opcoes do multiselect (popover, fora da sidebar) */
      [data-baseweb="popover"] [data-baseweb="menu"] {{
        background-color: {CREAM} !important;
      }}
      [data-baseweb="popover"] [data-baseweb="menu"] * {{
        color: {BURGUNDY_DARK} !important;
      }}
      /* Checkbox "Somente itens com NCM" */
      [data-testid="stSidebar"] [data-testid="stCheckbox"] label span {{
        color: {TEXT_LIGHT} !important;
      }}

      /* --- Abas (mesma linguagem visual do resto) --- */
      .stTabs [data-baseweb="tab-list"] {{
        gap: 28px;
        border-bottom: 1px solid {BURGUNDY_LIGHT};
        margin-bottom: 18px;
      }}
      .stTabs [data-baseweb="tab"] {{
        font-family: Georgia, 'Times New Roman', serif;
        font-size: 1.02rem;
        letter-spacing: 0.4px;
        color: {SAND} !important;
        padding: 10px 2px;
      }}
      .stTabs [data-baseweb="tab"] p {{
        font-family: Georgia, 'Times New Roman', serif;
        font-size: 1.02rem;
      }}
      .stTabs [aria-selected="true"] {{
        color: {TEXT_LIGHT} !important;
      }}
      .stTabs [data-baseweb="tab-highlight"] {{
        background-color: {GOLD} !important;
      }}

      /* Selectbox e radio na area principal */
      [data-testid="stMain"] [data-baseweb="select"] > div {{
        background-color: {CREAM} !important;
        border: 1px solid {SAND} !important;
      }}
      [data-testid="stMain"] [data-baseweb="select"] * {{
        color: {BURGUNDY_DARK} !important;
        -webkit-text-fill-color: {BURGUNDY_DARK} !important;
      }}
      [data-testid="stMain"] [data-testid="stRadio"] label p,
      [data-testid="stMain"] [data-testid="stCheckbox"] label p {{
        color: {TEXT_LIGHT} !important;
      }}
      [data-testid="stMain"] label p {{ color: {SAND} !important; }}

      .ad-header {{
        background-color: {CREAM};
        padding: 22px 32px;
        border-radius: 6px;
        margin-bottom: 24px;
        display: flex;
        align-items: center;
        justify-content: flex-start;
        box-shadow: 0 2px 6px rgba(0,0,0,0.25);
      }}
      .ad-header img {{
        max-height: 56px;
        width: auto;
        display: block;
      }}
      .ad-title {{
        font-family: Georgia, 'Times New Roman', serif;
        font-size: 2.2rem;
        color: {TEXT_LIGHT};
        margin: 8px 0 4px 0;
        font-weight: 600;
        letter-spacing: 0.5px;
      }}
      .ad-subtitle {{
        color: {SAND};
        font-size: 0.95rem;
        margin-bottom: 24px;
      }}
      .ad-footer {{
        margin-top: 48px;
        padding: 18px 0;
        border-top: 1px solid {BURGUNDY_LIGHT};
        color: {SAND};
        font-size: 0.85rem;
        text-align: center;
        letter-spacing: 0.5px;
      }}
      .ad-footer strong {{ color: {TEXT_LIGHT}; }}
      [data-testid="stMetricValue"] {{
        color: {TEXT_LIGHT} !important;
        font-family: Georgia, serif;
      }}
      [data-testid="stMetricLabel"] {{ color: {SAND} !important; }}
      .stTextInput > div > div > input {{
        background-color: {CREAM};
        color: {BURGUNDY_DARK};
        border: 1px solid {SAND};
        -webkit-text-fill-color: {BURGUNDY_DARK};
        caret-color: {BURGUNDY_DARK};
      }}
      .stTextInput > div > div > input::placeholder {{
        color: {BURGUNDY_LIGHT};
        opacity: 0.65;
      }}
      .stDownloadButton button {{
        background-color: {SAND};
        color: {BURGUNDY_DARK};
        border: none;
        font-weight: 600;
      }}
      .stDownloadButton button:hover {{
        background-color: {CREAM};
        color: {BURGUNDY_DARK};
      }}
      [data-testid="stDataFrame"] {{
        background-color: {CREAM};
        border-radius: 4px;
      }}
    </style>
    """, unsafe_allow_html=True)


def _localizar_logo():
    """Procura o arquivo da logo entre extensoes comuns (.png, .jpg, .jpeg,
    maiusculas ou minusculas), pois o nome exato pode variar dependendo de
    como o arquivo foi salvo/exportado."""
    for nome in LOGO_CANDIDATOS:
        caminho = Path(nome)
        if caminho.is_file():
            ext = caminho.suffix.lower().lstrip(".")
            mime = "jpeg" if ext in ("jpg", "jpeg") else "png"
            return caminho, mime
    return None, None


def renderizar_topo():
    """Header com a logo da Atala & Denys."""
    caminho, mime = _localizar_logo()
    if caminho is not None:
        with open(caminho, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        st.markdown(
            f'<div class="ad-header">'
            f'<img src="data:image/{mime};base64,{b64}" alt="Atala & Denys">'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        # Sem a logo no disco, segue sem quebrar
        st.markdown(
            f'<div class="ad-header" style="justify-content:center;">'
            f'<span style="font-family:Georgia,serif;font-size:1.4rem;'
            f'color:{BURGUNDY};letter-spacing:3px;">ATALA &amp; DENYS</span>'
            f'</div>',
            unsafe_allow_html=True,
        )


def renderizar_rodape():
    st.markdown(
        '<div class="ad-footer">'
        'Elaborado por <strong>Mitsuo Matsui</strong> · '
        'Atala &amp; Denys Consultoria e Projetos Econômicos'
        '</div>',
        unsafe_allow_html=True,
    )


def milhar(n) -> str:
    return f"{n:,}".replace(",", ".")


# -------- Senha -----------------------------------------------------------
def checar_senha():
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


# -------- Dados -----------------------------------------------------------
def montar_busca(df: pd.DataFrame, colunas: list) -> pd.Series:
    """Concatena colunas em uma string única, de forma vetorizada.

    Evita `df.agg(' | '.join, axis=1)`, que quebra em versões recentes do
    pandas quando há valores nulos ou numéricos.
    """
    colunas = [c for c in colunas if c in df.columns]
    if not colunas:
        return pd.Series([""] * len(df), index=df.index)
    busca = df[colunas[0]].fillna("").astype(str)
    for c in colunas[1:]:
        busca = busca + " | " + df[c].fillna("").astype(str)
    return busca


@st.cache_data(show_spinner="Carregando a base de produtos...")
def carregar():
    df = pd.read_parquet(ARQUIVO)
    for c in COLUNAS:
        if c not in df.columns:
            df[c] = ""
    df = df.fillna("")
    if "_busca" not in df.columns:
        df["_busca"] = montar_busca(df, list(COLUNAS))
    df["_busca_low"] = df["_busca"].astype(str).str.lower()
    return df


@st.cache_data(show_spinner="Carregando a listagem de insumos...")
def carregar_lips():
    caminho = Path(ARQUIVO_LIPS)
    if not caminho.is_file():
        caminho = Path("dados") / ARQUIVO_LIPS
    if not caminho.is_file():
        return None

    df = pd.read_parquet(caminho)
    for c in COLUNAS_LIPS:
        if c not in df.columns:
            df[c] = ""
    # Tudo como texto, sem nulos — evita erro de tipo na busca
    for c in df.columns:
        df[c] = df[c].fillna("").astype(str)
    # Remove eventual linha de cabecalho gravada no meio dos dados
    df = df[df["produto_id"] != "produto_id"]
    return df


def enriquecer_lips(df_lips, df_prod):
    """Preenche o nome do produto na base de insumos cruzando com a base de
    produtos, que é a fonte de verdade para essa informação."""
    if df_lips is None or df_prod is None:
        return df_lips
    if "codigo_produto" not in df_prod.columns:
        return df_lips

    mapa = (
        df_prod[["codigo_produto", "produto_nome"]]
        .drop_duplicates(subset=["codigo_produto"])
        .assign(_ch=lambda d: d["codigo_produto"].astype(str).str.strip().str.zfill(4))
        .set_index("_ch")["produto_nome"]
        .to_dict()
    )
    chave = df_lips["produto_id"].astype(str).str.strip().str.zfill(4)
    cruzado = chave.map(mapa).fillna("")

    atual = df_lips["produto_nome"].fillna("").astype(str)
    df_lips["produto_nome"] = atual.where(atual.str.strip() != "", cruzado)

    vazio = df_lips["produto_nome"].str.strip() == ""
    df_lips.loc[vazio, "produto_nome"] = "(sem nome) " + df_lips.loc[vazio, "produto_id"]

    df_lips["_busca_low"] = montar_busca(df_lips, list(COLUNAS_LIPS)).str.lower()
    return df_lips


def normalizar(texto: str) -> str:
    texto = str(texto).lower()
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in texto if not unicodedata.combining(c))


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


def gerar_excel(tabela: pd.DataFrame, nome_aba: str) -> bytes:
    buffer = BytesIO()
    tabela.to_excel(buffer, index=False, sheet_name=nome_aba)
    return buffer.getvalue()


# -------- Aplicacao -------------------------------------------------------
aplicar_estilo()
checar_senha()

df = carregar()
df_lips = enriquecer_lips(carregar_lips(), df)

renderizar_topo()

st.markdown('<div class="ad-title">🔎 Consulta SUFRAMA</div>',
            unsafe_allow_html=True)
st.markdown(
    f'<div class="ad-subtitle">'
    f'{milhar(df["codigo_produto"].nunique())} produtos-padrão · '
    f'{milhar(len(df))} tipos'
    + (f' · {milhar(len(df_lips))} insumos na LIPS' if df_lips is not None else "")
    + '</div>',
    unsafe_allow_html=True,
)

if df_lips is None:
    abas = st.tabs(["📦  Produtos / Tipos"])
else:
    abas = st.tabs(["📦  Produtos / Tipos", "🧪  Insumos por Produto"])


# =========================================================================
# ABA 1 — Produtos / Tipos (consulta original, preservada)
# =========================================================================
with abas[0]:
    with st.sidebar:
        st.header("Filtros")
        unidades = st.multiselect(
            "Unidade", sorted(u for u in df["unidade"].unique() if u)
        )
        so_ncm = st.checkbox("Somente itens com NCM", value=False)
        st.divider()
        st.caption("Dica: a busca procura ao mesmo tempo no nome do produto, "
                   "no tipo, na NCM e na base legal. Pode digitar várias "
                   "palavras (ex.: *parafuso ferro*).")

    termo = st.text_input(
        "Buscar produto, tipo, NCM ou base legal",
        placeholder="ex.: parafuso, porca, 8473, condicionador de ar...",
    )

    res = filtrar(df, termo, unidades, so_ncm)

    c1, c2, c3 = st.columns(3)
    c1.metric("Produtos", milhar(res["codigo_produto"].nunique()))
    c2.metric("Linhas (tipos)", milhar(len(res)))
    c3.metric("Com NCM", milhar((res["ncm"].str.len() > 0).sum()))

    if res.empty:
        st.warning("Nenhum resultado. Tente outra palavra ou remova filtros.")
    else:
        tabela = res[list(COLUNAS)].rename(columns=COLUNAS)
        st.dataframe(
            tabela,
            width="stretch",
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


# =========================================================================
# ABA 2 — Insumos por Produto (LIPS)
# =========================================================================
if df_lips is not None:
    with abas[1]:
        st.markdown(
            f'<div class="ad-subtitle" style="margin-bottom:14px;">'
            f'Matérias-primas, secundárias e embalagens habilitadas à '
            f'importação · {milhar(df_lips["produto_id"].nunique())} produtos '
            f'com listagem</div>',
            unsafe_allow_html=True,
        )

        modo = st.radio(
            "Modo de consulta",
            ["Busca livre", "Por produto"],
            horizontal=True,
            key="modo_lips",
        )

        res_l = df_lips

        if modo == "Busca livre":
            termo_l = st.text_input(
                "Buscar insumo, NCM, produto ou destaque",
                placeholder="ex.: parafuso aco, 73181500, borracha, cabo...",
                key="busca_lips",
            )
            if termo_l.strip():
                for palavra in termo_l.lower().split():
                    res_l = res_l[
                        res_l["_busca_low"].str.contains(palavra, regex=False)
                    ]
        else:
            produtos = (
                df_lips[["produto_id", "produto_nome"]]
                .drop_duplicates()
                .sort_values("produto_id")
            )
            opcoes = ["— selecione —"] + [
                f"{r.produto_id} · {r.produto_nome}"
                for r in produtos.itertuples()
            ]
            sel = st.selectbox("Produto-padrão", opcoes, key="sel_prod_lips")

            if sel != "— selecione —":
                cod = sel.split(" · ")[0].strip()
                res_l = res_l[res_l["produto_id"] == cod]

                termo_dentro = st.text_input(
                    "Filtrar dentro deste produto",
                    placeholder="ex.: parafuso, 4016, plastico...",
                    key="busca_dentro_lips",
                )
                if termo_dentro.strip():
                    for palavra in termo_dentro.lower().split():
                        res_l = res_l[
                            res_l["_busca_low"].str.contains(palavra, regex=False)
                        ]
            else:
                res_l = res_l.iloc[0:0]

        cf1, cf2 = st.columns([1, 2])
        with cf1:
            ppb = st.selectbox(
                "Item controlado (PPB)", ["Todos", "SIM", "NÃO"], key="ppb_lips"
            )
        with cf2:
            so_coment = st.checkbox(
                "Somente com comentário", key="coment_lips"
            )

        if ppb != "Todos":
            res_l = res_l[res_l["controlado_ppb"].str.strip().str.upper() == ppb]
        if so_coment:
            res_l = res_l[res_l["comentario"].str.strip() != ""]

        m1, m2, m3 = st.columns(3)
        m1.metric("Insumos", milhar(len(res_l)))
        m2.metric("Produtos", milhar(res_l["produto_id"].nunique()))
        m3.metric(
            "Controlados (PPB)",
            milhar((res_l["controlado_ppb"].str.strip().str.upper() == "SIM").sum()),
        )

        if res_l.empty:
            if modo == "Por produto" and st.session_state.get("sel_prod_lips") == "— selecione —":
                st.info("Selecione um produto-padrão para ver os insumos habilitados.")
            else:
                st.warning("Nenhum insumo encontrado com esses critérios.")
        else:
            tabela_l = res_l[list(COLUNAS_LIPS)].rename(columns=COLUNAS_LIPS)
            st.dataframe(
                tabela_l,
                width="stretch",
                hide_index=True,
                height=560,
                column_config={
                    "Código": st.column_config.TextColumn(width="small"),
                    "Produto": st.column_config.TextColumn(width="medium"),
                    "NCM": st.column_config.TextColumn(width="small"),
                    "Destaque": st.column_config.TextColumn(width="small"),
                    "Descrição Suframa": st.column_config.TextColumn(width="large"),
                    "Controlado (PPB)": st.column_config.TextColumn(width="small"),
                    "Comentário": st.column_config.TextColumn(width="medium"),
                },
            )

            d1, d2 = st.columns(2)
            with d1:
                st.download_button(
                    "⬇️ Baixar resultado (CSV)",
                    data=tabela_l.to_csv(index=False).encode("utf-8-sig"),
                    file_name="consulta_insumos_lips.csv",
                    mime="text/csv",
                    key="dl_csv_lips",
                )
            with d2:
                st.download_button(
                    "⬇️ Baixar resultado (Excel)",
                    data=gerar_excel(tabela_l, "Insumos LIPS"),
                    file_name="consulta_insumos_lips.xlsx",
                    mime=("application/vnd.openxmlformats-officedocument"
                          ".spreadsheetml.sheet"),
                    key="dl_xlsx_lips",
                )

renderizar_rodape()
