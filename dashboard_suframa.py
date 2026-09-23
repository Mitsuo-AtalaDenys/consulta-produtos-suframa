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
import re
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


COLUNAS_DOU = {
    "data_publicacao": "Publicação",
    "classificacao": "Ato",
    "tipo_projeto": "Tipo de projeto",
    "empresa": "Empresa",
    "codigo_produto": "Cód.",
    "produto": "Produto",
    "cnpj": "CNPJ",
    "numero_ato": "Portaria",
    "item": "Item",
    "fonte": "Origem",
    "processo": "Processo",
    "url": "Link",
}

COLUNAS_SILT = {
    "data_decreto": "Data",
    "classificacao": "Ato",
    "numero_decreto": "Decreto",
    "empresa": "Empresa",
    "produto": "Produto",
    "ncms": "NCM/SH",
    "credito_estimulo": "Crédito ICMS",
    "cnpj": "CNPJ",
    "codam_reuniao": "CODAM",
    "url": "Link",
}


@st.cache_data(show_spinner="Carregando os atos do DOU...")
def _preparar_dou(d, fonte):
    """Normaliza uma base de atos do DOU e marca a origem."""
    for c in list(COLUNAS_DOU) + ["ato_de_projeto", "tem_anexo", "texto",
                                  "texto_item", "item"]:
        if c not in d.columns:
            d[c] = ""
    for c in d.columns:
        d[c] = d[c].fillna("").astype(str)
    d["fonte"] = fonte
    return d


def carregar_dou():
    """Junta as duas series: o portal moderno e o acervo antigo.

    Sao coletas de origens diferentes — o portal entrega cada ato isolado,
    enquanto no acervo antigo o ato e reconstruido do texto da pagina do
    jornal. A coluna "fonte" preserva essa distincao, porque a cobertura
    e a precisao nao sao iguais nas duas pontas.
    """
    partes = []

    for nome in ("dou_suframa.parquet", "dados/dou_suframa.parquet"):
        p = Path(nome)
        if p.is_file():
            partes.append(_preparar_dou(pd.read_parquet(p), "Portal DOU"))
            break

    for nome in ("dou_legado.parquet", "dados/dou_legado.parquet"):
        p = Path(nome)
        if p.is_file():
            partes.append(_preparar_dou(pd.read_parquet(p), "Acervo antigo"))
            break

    if not partes:
        return None

    d = pd.concat(partes, ignore_index=True) if len(partes) > 1 else partes[0]
    d = d.fillna("")
    for c in d.columns:
        d[c] = d[c].astype(str)

    d["_dt"] = pd.to_datetime(d["data_publicacao"], format="%d/%m/%Y",
                              errors="coerce")
    d = d.sort_values("_dt", ascending=False)

    # Busca no texto DO ITEM, nao do ato inteiro. Num ato coletivo todas as
    # linhas compartilham o texto integral, entao buscar nele faria
    # "motocicleta" devolver tambem os colchoes publicados no mesmo dia.
    campo_texto = "texto_item" if (d["texto_item"] != "").any() else "texto"
    d["_busca_low"] = montar_busca(
        d, ["empresa", "cnpj", "produto", "codigo_produto",
            "numero_ato", "processo", "titulo", campo_texto]).str.lower()
    return d


@st.cache_data(show_spinner="Carregando os decretos do SILT...")
def carregar_silt():
    for nome in ("silt_decretos.parquet", "dados/silt_decretos.parquet"):
        p = Path(nome)
        if p.is_file():
            d = pd.read_parquet(p)
            for c in list(COLUNAS_SILT) + ["texto", "cca", "enquadramento"]:
                if c not in d.columns:
                    d[c] = ""
            for c in d.columns:
                d[c] = d[c].fillna("").astype(str)
            d["_dt"] = pd.to_datetime(d["data_decreto"], format="%d/%m/%Y",
                                      errors="coerce")
            d["_busca_low"] = montar_busca(
                d, ["empresa", "cnpj", "produto", "ncms", "numero_decreto",
                    "cca", "enquadramento"]).str.lower()
            return d
    return None


def cruzar_com_produtos(df_atos, df_prod):
    """Traz nome do produto-padrão, tipos e NCMs da base da SUFRAMA.

    O código do produto no ato do DOU é a chave que liga a publicação à
    base de produtos — é o que transforma uma lista de portarias numa
    consulta de quem fabrica o quê, com as NCMs de cada tipo.
    """
    if df_atos is None or df_prod is None:
        return df_atos

    base = df_prod.copy()
    base["_ch"] = base["codigo_produto"].astype(str).str.strip().str.zfill(4)

    nomes = base.drop_duplicates("_ch").set_index("_ch")["produto_nome"].to_dict()
    tipos = base.groupby("_ch").size().to_dict()
    ncms = (base.groupby("_ch")["ncm"]
                .apply(lambda s: ", ".join(sorted({
                    n.strip() for v in s for n in str(v).split(",") if n.strip()
                })))
                .to_dict())
    unid = base.drop_duplicates("_ch").set_index("_ch")["unidade"].to_dict()

    ch = df_atos["codigo_produto"].astype(str).str.strip().str.zfill(4)
    df_atos = df_atos.copy()
    df_atos["produto_padrao"] = ch.map(nomes).fillna("")
    df_atos["qtd_tipos"] = ch.map(tipos).fillna(0).astype(int)
    df_atos["ncms_do_produto"] = ch.map(ncms).fillna("")
    df_atos["unidade_produto"] = ch.map(unid).fillna("")
    return df_atos


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
df_dou = cruzar_com_produtos(carregar_dou(), df)
df_silt = carregar_silt()

renderizar_topo()

st.markdown('<div class="ad-title">🔎 Consulta SUFRAMA</div>',
            unsafe_allow_html=True)
st.markdown(
    f'<div class="ad-subtitle">'
    f'{milhar(df["codigo_produto"].nunique())} produtos-padrão · '
    f'{milhar(len(df))} tipos'
    + (f' · {milhar(len(df_lips))} insumos na LIPS' if df_lips is not None else "")
    + (f' · {milhar((df_dou["classificacao"] == "aprovacao").sum())} projetos '
       f'aprovados no DOU' if df_dou is not None else "")
    + (f' · {milhar(len(df_silt))} decretos no SILT' if df_silt is not None else "")
    + '</div>',
    unsafe_allow_html=True,
)

rotulos = ["📦  Produtos / Tipos"]
if df_lips is not None:
    rotulos.append("🧪  Insumos por Produto")
if df_dou is not None:
    rotulos.append("📜  Projetos aprovados (DOU)")
if df_silt is not None:
    rotulos.append("🏛️  Incentivos estaduais (SILT)")
abas = st.tabs(rotulos)
IDX = {nome: i for i, nome in enumerate(rotulos)}


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


# =========================================================================
# ABA 3 — Projetos aprovados no DOU
# =========================================================================
if df_dou is not None:
    with abas[IDX["📜  Projetos aprovados (DOU)"]]:

        so_projeto = df_dou[df_dou["ato_de_projeto"] == "SIM"]
        n_apr = (so_projeto["classificacao"] == "aprovacao").sum()
        periodo = ""
        if so_projeto["_dt"].notna().any():
            periodo = (f'{so_projeto["_dt"].min():%m/%Y} a '
                       f'{so_projeto["_dt"].max():%m/%Y}')
        st.markdown(
            f'<div class="ad-subtitle" style="margin-bottom:6px;">'
            f'Portarias e Resoluções da SUFRAMA sobre projetos de empresas · '
            f'{milhar(n_apr)} aprovações · {periodo}</div>',
            unsafe_allow_html=True,
        )
        if "Acervo antigo" in set(so_projeto["fonte"]):
            st.caption(
                "Até 2015 os atos vêm do acervo digitalizado da Imprensa "
                "Nacional, reconstruídos do texto da página do jornal: a "
                "cobertura é parcial e convém conferir no DOU antes de citar. "
                "De 2016 em diante vêm do portal, onde cada ato é publicado "
                "isoladamente."
            )

        modo_d = st.radio(
            "Modo de consulta",
            ["Por empresa ou produto", "Quem fabrica esta NCM", "Linha do tempo"],
            horizontal=True,
            key="modo_dou",
        )

        res_d = so_projeto

        if modo_d == "Por empresa ou produto":
            termo_d = st.text_input(
                "Buscar empresa, CNPJ, produto, código ou nº da portaria",
                placeholder="ex.: flextronics, 0674, 2.709, plástico...",
                key="busca_dou",
            )
            if termo_d.strip():
                for palavra in termo_d.lower().split():
                    res_d = res_d[res_d["_busca_low"].str.contains(
                        palavra, regex=False)]

        elif modo_d == "Quem fabrica esta NCM":
            st.caption("Informe uma NCM para descobrir quais empresas tiveram "
                       "projeto aprovado em produtos que a contemplam.")
            ncm_busca = st.text_input(
                "NCM (pode ser parcial — 8 dígitos, capítulo ou posição)",
                placeholder="ex.: 39219019, 3921, 8473",
                key="ncm_dou",
            )
            if ncm_busca.strip():
                alvo = re.sub(r"\D", "", ncm_busca)
                res_d = res_d[res_d["ncms_do_produto"].str.replace(
                    r"\D", "", regex=True).str.contains(alvo, na=False)]
            else:
                res_d = res_d.iloc[0:0]

        else:  # Linha do tempo
            empresas = sorted(e for e in so_projeto["empresa"].unique() if e)
            sel_emp = st.selectbox(
                "Empresa", ["— selecione —"] + empresas, key="emp_dou")
            if sel_emp != "— selecione —":
                res_d = res_d[res_d["empresa"] == sel_emp].sort_values(
                    "_dt", ascending=False)
            else:
                res_d = res_d.iloc[0:0]

        cf1, cf2, cf3 = st.columns(3)
        with cf1:
            classes = ["Todos"] + sorted(
                c for c in so_projeto["classificacao"].unique() if c)
            sel_cls = st.selectbox("Tipo de ato", classes, key="cls_dou")
            if sel_cls != "Todos":
                res_d = res_d[res_d["classificacao"] == sel_cls]
        with cf2:
            tipos_p = ["Todos"] + sorted(
                t for t in so_projeto["tipo_projeto"].unique() if t)
            sel_tp = st.selectbox("Tipo de projeto", tipos_p, key="tp_dou")
            if sel_tp != "Todos":
                res_d = res_d[res_d["tipo_projeto"] == sel_tp]
        with cf3:
            origens = ["Todas"] + sorted(
                f for f in so_projeto["fonte"].unique() if f)
            sel_fo = st.selectbox("Origem", origens, key="fonte_dou")
            if sel_fo != "Todas":
                res_d = res_d[res_d["fonte"] == sel_fo]

        m1, m2, m3 = st.columns(3)
        m1.metric("Atos", milhar(len(res_d)))
        m2.metric("Empresas", milhar(res_d["empresa"].replace("", pd.NA).nunique()))
        m3.metric("Produtos-padrão",
                  milhar(res_d["codigo_produto"].replace("", pd.NA).nunique()))

        if res_d.empty:
            if modo_d == "Quem fabrica esta NCM":
                st.info("Digite uma NCM para ver as empresas aprovadas.")
            elif modo_d == "Linha do tempo":
                st.info("Selecione uma empresa para ver o histórico de atos.")
            else:
                st.warning("Nenhum ato encontrado com esses critérios.")
        else:
            cols_d = list(COLUNAS_DOU) + ["produto_padrao", "ncms_do_produto"]
            cols_d = [c for c in cols_d if c in res_d.columns]
            rotulos_d = dict(COLUNAS_DOU)
            rotulos_d["produto_padrao"] = "Produto-padrão (base SUFRAMA)"
            rotulos_d["ncms_do_produto"] = "NCMs do produto"
            tabela_d = res_d[cols_d].rename(columns=rotulos_d)

            st.dataframe(
                tabela_d, width="stretch", hide_index=True, height=520,
                column_config={
                    "Publicação": st.column_config.TextColumn(width="small"),
                    "Ato": st.column_config.TextColumn(width="small"),
                    "Empresa": st.column_config.TextColumn(width="large"),
                    "Cód.": st.column_config.TextColumn(width="small"),
                    "Origem": st.column_config.TextColumn(width="small"),
                    "Link": st.column_config.LinkColumn(
                        "DOU", display_text="abrir", width="small"),
                },
            )

            d1c, d2c = st.columns(2)
            with d1c:
                st.download_button(
                    "⬇️ Baixar resultado (CSV)",
                    data=tabela_d.to_csv(index=False).encode("utf-8-sig"),
                    file_name="projetos_aprovados_dou.csv", mime="text/csv",
                    key="dl_csv_dou")
            with d2c:
                st.download_button(
                    "⬇️ Baixar resultado (Excel)",
                    data=gerar_excel(tabela_d, "DOU"),
                    file_name="projetos_aprovados_dou.xlsx",
                    mime=("application/vnd.openxmlformats-officedocument"
                          ".spreadsheetml.sheet"),
                    key="dl_xlsx_dou")

            com_anexo = res_d[res_d["tem_anexo"] == "SIM"]
            if not com_anexo.empty:
                st.caption(
                    f"⚠️ {len(com_anexo)} ato(s) do resultado remetem a anexo "
                    "com lista de empresas/produtos que não é capturada "
                    "automaticamente — abra o link para consultar."
                )


# =========================================================================
# ABA 4 — Incentivos estaduais (SILT / SEFAZ-AM)
# =========================================================================
if df_silt is not None:
    with abas[IDX["🏛️  Incentivos estaduais (SILT)"]]:

        n_conc = (df_silt["classificacao"] == "concessao").sum()
        periodo_s = ""
        if df_silt["_dt"].notna().any():
            periodo_s = (f'{df_silt["_dt"].min():%m/%Y} a '
                         f'{df_silt["_dt"].max():%m/%Y}')
        st.markdown(
            f'<div class="ad-subtitle" style="margin-bottom:14px;">'
            f'Decretos Concessivos do Estado do Amazonas (SEDECTI/CODAM) · '
            f'{milhar(n_conc)} concessões · {periodo_s}</div>',
            unsafe_allow_html=True,
        )

        termo_s = st.text_input(
            "Buscar empresa, CNPJ, produto, NCM ou nº do decreto",
            placeholder="ex.: 55.356, panificação, 1905, 09.488.986...",
            key="busca_silt",
        )
        res_s = df_silt
        if termo_s.strip():
            for palavra in termo_s.lower().split():
                res_s = res_s[res_s["_busca_low"].str.contains(
                    palavra, regex=False)]

        sf1, sf2 = st.columns(2)
        with sf1:
            cls_s = ["Todos"] + sorted(
                c for c in df_silt["classificacao"].unique() if c)
            sel_cs = st.selectbox("Tipo de ato", cls_s, key="cls_silt")
            if sel_cs != "Todos":
                res_s = res_s[res_s["classificacao"] == sel_cs]
        with sf2:
            creds = ["Todos"] + sorted(
                c for c in df_silt["credito_estimulo"].unique() if c)
            sel_cr = st.selectbox("Crédito estímulo", creds, key="cred_silt")
            if sel_cr != "Todos":
                res_s = res_s[res_s["credito_estimulo"] == sel_cr]

        sm1, sm2, sm3 = st.columns(3)
        sm1.metric("Decretos", milhar(len(res_s)))
        sm2.metric("Empresas", milhar(res_s["empresa"].replace("", pd.NA).nunique()))
        sm3.metric("Com NCM", milhar((res_s["ncms"] != "").sum()))

        if res_s.empty:
            st.warning("Nenhum decreto encontrado com esses critérios.")
        else:
            tabela_s = res_s[list(COLUNAS_SILT)].rename(columns=COLUNAS_SILT)
            st.dataframe(
                tabela_s, width="stretch", hide_index=True, height=520,
                column_config={
                    "Data": st.column_config.TextColumn(width="small"),
                    "Decreto": st.column_config.TextColumn(width="small"),
                    "Empresa": st.column_config.TextColumn(width="large"),
                    "NCM/SH": st.column_config.TextColumn(width="medium"),
                    "Link": st.column_config.LinkColumn(
                        "SILT", display_text="abrir", width="small"),
                },
            )

            s1c, s2c = st.columns(2)
            with s1c:
                st.download_button(
                    "⬇️ Baixar resultado (CSV)",
                    data=tabela_s.to_csv(index=False).encode("utf-8-sig"),
                    file_name="decretos_concessivos_silt.csv", mime="text/csv",
                    key="dl_csv_silt")
            with s2c:
                st.download_button(
                    "⬇️ Baixar resultado (Excel)",
                    data=gerar_excel(tabela_s, "SILT"),
                    file_name="decretos_concessivos_silt.xlsx",
                    mime=("application/vnd.openxmlformats-officedocument"
                          ".spreadsheetml.sheet"),
                    key="dl_xlsx_silt")

renderizar_rodape()
