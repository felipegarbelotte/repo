import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dateutil import parser
import altair as alt

SHEET_ID = "1Qf2TL2Pj6yHtU2IkehIT2CTgmW4Nj2CRQ85heVzTWgc"
WORKSHEET_NAME = "Form Responses 1"

st.set_page_config(page_title="Dashboard Financeiro", layout="wide")

@st.cache_data(ttl=300)
def load_data(sheet_id: str, worksheet_name: str) -> pd.DataFrame:
    scope = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]   
    # creds = ServiceAccountCredentials.from_json_keyfile_name("credenciais.json", scope) #credenciais local
    creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["google"], scope)
    client = gspread.authorize(creds)
    ws = client.open_by_key(sheet_id).worksheet(worksheet_name)
    records = ws.get_all_records()
    df = pd.DataFrame(records)

    # Padroniza nomes de colunas esperadas (ajuste se diferente na sua planilha)
    colmap = {
        "Timestamp": "timestamp",
        "Tipo de lançamento": "tipo",
        "Categoria": "categoria",
        "Data do lançamento": "data",
        "Valor (R$)": "valor",
        "Forma de pagamento": "forma_pagamento",
        "De quem recebeu / Para quem pagou (lista)": "pessoa_lista",
        "Outro nome (digite manualmente)": "pessoa_texto",
        "Observações": "observacoes",
    }
    df = df.rename(columns={k: v for k, v in colmap.items() if k in df.columns})

    # Pessoa Final
    if "pessoa_lista" in df.columns or "pessoa_texto" in df.columns:
        df["pessoa_final"] = df.get("pessoa_texto", "").fillna("")
        mask_vazio = df["pessoa_final"].astype(str).str.strip() == ""
        if "pessoa_lista" in df.columns:
            df.loc[mask_vazio, "pessoa_final"] = df.loc[mask_vazio, "pessoa_lista"]

    # Valor numérico
    if "valor" in df.columns:
        df["valor"] = (
            df["valor"]
            .astype(str)
            .str.replace(".", "", regex=False)   # remove separador de milhar
            .str.replace(",", ".", regex=False)  # usa ponto como decimal
        )
        df["valor"] = pd.to_numeric(df["valor"], errors="coerce")

    # Datas
    # Tenta usar "Data do lançamento"; se não existir, usa "Timestamp"
    if "data" in df.columns:
        df["data"] = pd.to_datetime(df["data"], errors="coerce")
    elif "timestamp" in df.columns:
        df["data"] = pd.to_datetime(df["timestamp"], errors="coerce")

    # Limpa linhas sem valor ou sem data
    df = df.dropna(subset=["valor", "data"])
    return df

def kpi_cards(df: pd.DataFrame):
    receitas = df.loc[df["tipo"].str.lower() == "receita", "valor"].sum() if "tipo" in df.columns else 0
    despesas = df.loc[df["tipo"].str.lower() == "despesa", "valor"].sum() if "tipo" in df.columns else 0
    saldo = receitas - despesas

    col1, col2, col3 = st.columns(3)
    col1.metric("Receitas (R$)", f"{receitas:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    col2.metric("Despesas (R$)", f"{despesas:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    col3.metric("Saldo (R$)", f"{saldo:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

def monthly_charts(df: pd.DataFrame):
    if "tipo" not in df.columns:
        st.info("Coluna 'Tipo de lançamento' não encontrada.")
        return

    df["ano_mes"] = df["data"].dt.to_period("M").astype(str)
    receitas_m = df[df["tipo"].str.lower() == "receita"].groupby("ano_mes")["valor"].sum().reset_index()
    despesas_m = df[df["tipo"].str.lower() == "despesa"].groupby("ano_mes")["valor"].sum().reset_index()
    saldo_m = receitas_m.merge(despesas_m, on="ano_mes", how="outer", suffixes=("_rec", "_des")).fillna(0)
    saldo_m["saldo"] = saldo_m["valor_rec"] - saldo_m["valor_des"]

    base = pd.melt(
        saldo_m[["ano_mes", "valor_rec", "valor_des", "saldo"]],
        id_vars=["ano_mes"],
        var_name="tipo",
        value_name="valor"
    )
    tipo_map = {"valor_rec": "Receitas", "valor_des": "Despesas", "saldo": "Saldo"}
    base["tipo"] = base["tipo"].map(tipo_map)

    chart = (
        alt.Chart(base)
        .mark_line(point=True)
        .encode(x=alt.X("ano_mes:N", title="Ano-Mês"), y=alt.Y("valor:Q", title="Valor (R$)"), color="tipo:N")
        .properties(height=300)
    )
    st.subheader("Evolução mensal: receitas, despesas e saldo")
    st.altair_chart(chart, use_container_width=True)

def category_chart(df: pd.DataFrame):
    if "categoria" in df.columns:
        despesas_cat = df[df["tipo"].str.lower() == "despesa"].groupby("categoria")["valor"].sum().reset_index()
        chart = alt.Chart(despesas_cat).mark_bar().encode(
            x=alt.X("valor:Q", title="Valor (R$)"),
            y=alt.Y("categoria:N", sort="-x", title="Categoria"),
            tooltip=["categoria", "valor"]
        ).properties(height=350)
        st.subheader("Despesas por categoria")
        st.altair_chart(chart, use_container_width=True)
    else:
        st.info("Coluna 'Categoria' não encontrada.")

def payment_chart(df: pd.DataFrame):
    if "forma_pagamento" in df.columns:
        por_forma = df.groupby("forma_pagamento")["valor"].sum().reset_index()
        chart = alt.Chart(por_forma).mark_bar().encode(
            x=alt.X("valor:Q", title="Valor (R$)"),
            y=alt.Y("forma_pagamento:N", sort="-x", title="Forma de pagamento"),
            tooltip=["forma_pagamento", "valor"]
        ).properties(height=300)
        st.subheader("Totais por forma de pagamento")
        st.altair_chart(chart, use_container_width=True)
    else:
        st.info("Coluna 'Forma de pagamento' não encontrada.")

def top_people_chart(df: pd.DataFrame):
    if "pessoa_final" in df.columns:
        top = (
            df.groupby("pessoa_final")["valor"]
            .sum()
            .reset_index()
            .sort_values("valor", ascending=False)
            .head(15)
        )
        chart = alt.Chart(top).mark_bar().encode(
            x=alt.X("valor:Q", title="Valor (R$)"),
            y=alt.Y("pessoa_final:N", sort="-x", title="Pessoa/Fornecedor"),
            tooltip=["pessoa_final", "valor"]
        ).properties(height=450)
        st.subheader("Top pessoas/fornecedores")
        st.altair_chart(chart, use_container_width=True)
    else:
        st.info("Coluna unificada 'Pessoa Final' não encontrada.")

def main():
    st.title("Dashboard Financeiro")
    st.caption("Fonte: Google Sheets (Form Responses 1)")

    df = load_data(SHEET_ID, WORKSHEET_NAME)

    # Filtros
    colA, colB, colC = st.columns(3)
    tipos = sorted(df["tipo"].dropna().unique()) if "tipo" in df.columns else []
    categorias = sorted(df["categoria"].dropna().unique()) if "categoria" in df.columns else []
    formas = sorted(df["forma_pagamento"].dropna().unique()) if "forma_pagamento" in df.columns else []

    sel_tipos = colA.multiselect("Tipo", tipos, default=tipos)
    sel_categorias = colB.multiselect("Categoria", categorias, default=categorias)
    sel_formas = colC.multiselect("Forma de pagamento", formas, default=formas)

    # Aplica filtros
    if "tipo" in df.columns:
        df = df[df["tipo"].isin(sel_tipos)]
    if "categoria" in df.columns:
        df = df[df["categoria"].isin(sel_categorias)]
    if "forma_pagamento" in df.columns:
        df = df[df["forma_pagamento"].isin(sel_formas)]

    kpi_cards(df)
    monthly_charts(df)

    col1, col2 = st.columns([1, 1])
    with col1:
        category_chart(df)
    with col2:
        payment_chart(df)

    top_people_chart(df)

    st.divider()
    st.caption("Dica: atualize os dados clicando no ícone de 'Rerun' do Streamlit. O cache expira a cada 5 minutos.")

if __name__ == "__main__":
    main()
