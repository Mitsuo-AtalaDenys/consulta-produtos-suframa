#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dashboard_suframa.py
====================
App de consulta da base completa de Produtos da Suframa
(1.768 produtos x tipos, com NCM e descricao da NCM).

Identidade visual Atala & Denys: burgundy, bege e tons crus.
"""

from pathlib import Path
import base64
import pandas as pd
import streamlit as st

# -------- Configuracao da pagina ------------------------------------------
st.set_page_config(page_title="Consulta de Produtos · Atala & Denys",
                   page_icon="🔎", layout="wide")

ARQUIVO = "suframa_insumos.parquet"
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
@st.cache_data(show_spinner="Carregando a base...")
def carregar():
    df = pd.read_parquet(ARQUIVO)
    for c in COLUNAS:
        if c not in df.columns:
            df[c] = ""
    df = df.fillna("")
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


# -------- Aplicacao -------------------------------------------------------
aplicar_estilo()
checar_senha()
df = carregar()

renderizar_topo()

st.markdown('<div class="ad-title">🔎 Consulta de Produtos · SUFRAMA</div>',
            unsafe_allow_html=True)
st.markdown(
    f'<div class="ad-subtitle">Base completa: '
    f'{df["codigo_produto"].nunique():,} produtos · '
    f'{len(df):,} tipos · '
    f'{(df["ncm"].str.len() > 0).sum():,} com NCM</div>'.replace(",", "."),
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Filtros")
    unidades = st.multiselect("Unidade", sorted(u for u in df["unidade"].unique() if u))
    so_ncm = st.checkbox("Somente itens com NCM", value=False)
    st.divider()
    st.caption("Dica: a busca procura ao mesmo tempo no nome do produto, "
               "no tipo, na NCM e na base legal. Pode digitar várias "
               "palavras (ex.: *parafuso ferro*).")

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

renderizar_rodape()
