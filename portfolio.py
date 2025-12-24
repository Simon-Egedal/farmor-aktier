import streamlit as st
import yfinance as yf
import pandas as pd
import time
import plotly.express as px
from datetime import datetime, timedelta
from supabase import create_client, Client

# --- SUPABASE KONFIGURATION ---
SUPABASE_URL = "https://spypxxbqfhnhuwvgixce.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNweXB4eGJxZmhuaHV3dmdpeGNlIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjYzNTMyMjksImV4cCI6MjA4MTkyOTIyOX0.pLpcT1UxXFh2Ua1xkF4Qx6sGxHIoqGebDZuGkQ2bWlw"

# FÆLLES PORTEFØLJE ID (samme for alle brugere)
SHARED_PORTFOLIO_ID = "shared_portfolio_2025"

# Forbind til Supabase
@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

try:
    supabase = init_supabase()
except Exception as e:
    st.error(f"Forbindelsesfejl: {e}")
    st.stop()

# --- SIDE KONFIGURATION ---
st.set_page_config(page_title="Portefølje Tracker", layout="wide")

# --- LOGIN SYSTEM ---
if 'user' not in st.session_state:
    st.session_state.user = None

def login_user(email, password):
    try:
        response = supabase.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state.user = response.user
        st.success("Logget ind!")
        time.sleep(0.5)
        st.rerun()
    except Exception as e:
        st.error(f"Login fejlede: {e}")

def logout_user():
    supabase.auth.sign_out()
    st.session_state.user = None

# --- LOGIN SKÆRM ---
if not st.session_state.user:
    st.title("Portefølje Adgang")
    with st.form("login_form"):
        email = st.text_input("Email")
        password = st.text_input("Adgangskode", type="password")
        submit = st.form_submit_button("Log Ind")
        if submit:
            login_user(email, password)
    st.stop()

# --- HOVED APP (KUN HVIS LOGGET IND) ---

st.sidebar.button("Log Ud", on_click=logout_user)
st.title("Portefølje & Udbytte Tracker")

# Vis hvem der er logget ind
st.sidebar.info(f"ogget ind som: {st.session_state.user.email}")

# --- INITIAL DATA (Standard aktier) - OPDATERET TIL 900K ---
planned_portfolio = [
    {"Navn": "Danske Bank", "Ticker": "DANSKE.CO", "Kategori": "Høj", "Mål_Investering": 90000},
    {"Navn": "Atea", "Ticker": "ATEA.OL", "Kategori": "Høj", "Mål_Investering": 90000},
    {"Navn": "NCC", "Ticker": "NCC-B.ST", "Kategori": "Høj", "Mål_Investering": 90000},
    {"Navn": "AT&T", "Ticker": "T", "Kategori": "Høj", "Mål_Investering": 90000},
    {"Navn": "Gjensidige", "Ticker": "GJF.OL", "Kategori": "Mellem", "Mål_Investering": 54000},
    {"Navn": "H&M", "Ticker": "HM-B.ST", "Kategori": "Mellem", "Mål_Investering": 54000},
    {"Navn": "Cloetta", "Ticker": "CLA-B.ST", "Kategori": "Mellem", "Mål_Investering": 54000},
    {"Navn": "Orkla", "Ticker": "ORK.OL", "Kategori": "Mellem", "Mål_Investering": 54000},
    {"Navn": "Coca Cola", "Ticker": "KO", "Kategori": "Mellem", "Mål_Investering": 54000},
    {"Navn": "Unilever", "Ticker": "UL", "Kategori": "Mellem", "Mål_Investering": 54000},
    {"Navn": "Royal Unibrew", "Ticker": "RBREW.CO", "Kategori": "Lav/Vækst", "Mål_Investering": 36000},
    {"Navn": "Rockwool", "Ticker": "ROCK-B.CO", "Kategori": "Lav/Vækst", "Mål_Investering": 36000},
    {"Navn": "Procter & Gamble", "Ticker": "PG", "Kategori": "Lav/Vækst", "Mål_Investering": 36000},
    {"Navn": "McDonald's", "Ticker": "MCD", "Kategori": "Lav/Vækst", "Mål_Investering": 36000},
    {"Navn": "Nestlé", "Ticker": "NESN.SW", "Kategori": "Lav/Vækst", "Mål_Investering": 36000},
    {"Navn": "S&P 500 ETF", "Ticker": "IVV", "Kategori": "Lav/Vækst", "Mål_Investering": 36000},
]

# --- DATABASE FUNKTIONER (FÆLLES PORTEFØLJE) ---

def get_db_data():
    """Henter data fra Supabase - FÆLLES for alle brugere."""
    try:
        response = supabase.table("portfolio_data").select("*").eq("user_id", SHARED_PORTFOLIO_ID).execute()
        if response.data:
            return response.data[0]
        # Opret fælles portefølje hvis den ikke findes
        supabase.table("portfolio_data").insert({"user_id": SHARED_PORTFOLIO_ID, "holdings": [], "cash_balance": 0}).execute()
        return {"holdings": [], "cash_balance": 0, "total_dividends_received": 0, "last_div_check": datetime.now().isoformat()}
    except Exception as e:
        st.error(f"Database fejl: {e}")
        return {"holdings": [], "cash_balance": 0}

def save_db_data(holdings, cash_balance, total_div=None, last_check=None):
    """Gemmer data til Supabase - FÆLLES for alle brugere."""
    try:
        data = {"holdings": holdings, "cash_balance": cash_balance}
        if total_div is not None:
            data["total_dividends_received"] = total_div
        if last_check:
            data["last_div_check"] = last_check
        supabase.table("portfolio_data").update(data).eq("user_id", SHARED_PORTFOLIO_ID).execute()
    except Exception as e:
        st.error(f"Kunne ikke gemme: {e}")

def reset_database():
    """Nulstiller alle data for den fælles portefølje."""
    try:
        supabase.table("portfolio_data").update({
            "holdings": [],
            "cash_balance": 0,
            "total_dividends_received": 0,
            "last_div_check": datetime.now().isoformat()
        }).eq("user_id", SHARED_PORTFOLIO_ID).execute()
        return True
    except Exception as e:
        st.error(f"Kunne ikke nulstille: {e}")
        return False

def auto_setup_portfolio():
    """Automatisk opsætning: køb aktier iht. planned_portfolio, resten som kontant."""
    try:
        with st.spinner("Køber aktier automatisk..."):
            # Start med 900k
            remaining_cash = 900000
            new_holdings = []
            success_count = 0
            failed_stocks = []

            for stock in planned_portfolio:
                try:
                    ticker = yf.Ticker(stock["Ticker"])
                    current_price = ticker.history(period="1d")["Close"].iloc[-1]

                    # Beregn antal aktier baseret på mål investering
                    target_investment = stock["Mål_Investering"]
                    quantity = int(target_investment / current_price)

                    if quantity > 0:
                        actual_cost = quantity * current_price

                        # Tjek om vi har nok kontanter
                        if actual_cost <= remaining_cash:
                            new_holdings.append({
                                "Navn": stock["Navn"],
                                "Ticker": stock["Ticker"],
                                "Antal": quantity,
                                "Nuværende_Pris": current_price,
                                "Købspris": current_price,
                                "Kategori": stock["Kategori"]
                            })

                            remaining_cash -= actual_cost
                            success_count += 1
                        else:
                            failed_stocks.append(f"{stock['Navn']} (ikke nok kontanter)")

                except Exception as e:
                    failed_stocks.append(f"{stock['Navn']} (fejl: {str(e)[:30]})")
                    continue

            # Gem den nye portefølje
            save_db_data(new_holdings, remaining_cash, 0, datetime.now().isoformat())
            return True, success_count, remaining_cash, failed_stocks

    except Exception as e:
        st.error(f"Auto-setup fejlede: {e}")
        return False, 0, 0, []

def ensure_price_exists(holdings):
    """Sikrer at alle beholdninger har Nuværende_Pris og Købspris"""
    for h in holdings:
        if "Nuværende_Pris" not in h or h["Nuværende_Pris"] is None:
            try:
                ticker = yf.Ticker(h["Ticker"])
                current_price = ticker.history(period="1d")["Close"].iloc[-1]
                h["Nuværende_Pris"] = current_price
            except:
                h["Nuværende_Pris"] = 0
                st.warning(f"Kunne ikke hente pris for {h['Navn']}")

        # Sikr at købspris findes (fallback til nuværende pris)
        if "Købspris" not in h or h["Købspris"] is None:
            h["Købspris"] = h.get("Nuværende_Pris", 0)

    return holdings

# --- HENT DATA ---
db_data = get_db_data()
holdings = db_data.get("holdings", [])
cash_balance = db_data.get("cash_balance", 0)
total_dividends = db_data.get("total_dividends_received", 0)
last_div_check = db_data.get("last_div_check", datetime.now().isoformat())

# Sikr at alle holdings har priser
holdings = ensure_price_exists(holdings)

# --- SIDEBAR KONTROLPANEL ---
st.sidebar.title("Kontrolpanel")

# OPDATER KURSER
if st.sidebar.button("Opdater Kurser"):
    with st.spinner("Henter aktuelle kurser..."):
        for h in holdings:
            try:
                ticker = yf.Ticker(h["Ticker"])
                current_price = ticker.history(period="1d")["Close"].iloc[-1]
                h["Nuværende_Pris"] = current_price
            except:
                st.warning(f"Kunne ikke opdatere {h['Navn']}")
        save_db_data(holdings, cash_balance, total_dividends, last_div_check)
        st.success("Kurser opdateret!")
        st.rerun()

# --- AUTO-SETUP PORTEFØLJE ---
st.sidebar.markdown("---")
with st.sidebar.expander("Opsæt Portefølje", expanded=False):
    st.info("Dette vil automatisk købe alle 16 aktier baseret på 900k fordeling.")

    st.markdown("**Hvad sker der:**")
    st.markdown("- Nulstiller eksisterende data")
    st.markdown("- Køber aktier iht. planned_portfolio")
    st.markdown("- Resterende beløb gemmes som kontant")
    st.markdown("")
    st.markdown("**Fordeling:**")
    st.markdown("- 4 aktier × 90.000 kr (Høj)")
    st.markdown("- 6 aktier × 54.000 kr (Mellem)")
    st.markdown("- 6 aktier × 36.000 kr (Lav/Vækst)")

    if st.button("KØB ALLE AKTIER", type="primary"):
        success, num_stocks, remaining, failed = auto_setup_portfolio()
        if success:
            st.success(f"✅ Købte {num_stocks} aktier! Kontant: {remaining:,.0f} kr")
            if failed:
                st.warning(f"Kunne ikke købe: {', '.join(failed)}")
            time.sleep(2)
            st.rerun()

# --- NULSTIL DATABASE (FARLIG ZONE) ---
with st.sidebar.expander("Nulstil Database", expanded=False):
    st.warning("ADVARSEL: Dette vil slette alle beholdninger i den FÆLLES portefølje!")

    confirm = st.checkbox("Jeg forstår at dette påvirker alle brugere")

    if st.button("🗑️ NULSTIL ALT", disabled=not confirm, type="secondary"):
        if reset_database():
            st.success("Fælles portefølje nulstillet!")
            time.sleep(1)
            st.rerun()

st.sidebar.markdown("---")

# --- WITHDRAW KONTANTER ---
st.sidebar.subheader("Hæv Kontanter")
if cash_balance > 0:
    with st.sidebar.form("withdraw_form"):
        withdraw_amount = st.number_input(
            f"Beløb (Max: {cash_balance:,.0f} kr)", 
            min_value=0.0, 
            max_value=float(cash_balance),
            step=100.0
        )
        withdraw_btn = st.form_submit_button("Hæv")

        if withdraw_btn and withdraw_amount > 0:
            cash_balance -= withdraw_amount
            save_db_data(holdings, cash_balance, total_dividends, last_div_check)
            st.success(f"Hævede {withdraw_amount:,.0f} kr")
            st.rerun()
else:
    st.sidebar.info("Ingen kontanter at hæve")

# --- INDSÆT PENGE ---
with st.sidebar.expander("Indsæt Penge"):
    with st.form("add_money"):
        add_amount = st.number_input("Beløb at indsætte (kr)", min_value=0, step=1000)
        add_btn = st.form_submit_button("Indsæt")
        if add_btn and add_amount > 0:
            cash_balance += add_amount
            save_db_data(holdings, cash_balance, total_dividends, last_div_check)
            st.success(f"Indsat {add_amount} kr")
            st.rerun()

# --- KØB AKTIER (FRA PLANNED PORTFOLIO) ---
with st.sidebar.expander("Køb genkøb Aktier"):
    stock_to_buy = st.selectbox("Vælg aktie", [s["Navn"] for s in planned_portfolio], key="planned_select")
    buy_qty = st.number_input("Antal aktier", min_value=1, step=1, key="planned_qty")

    if st.button("Køb", key="planned_buy"):
        stock_info = next((s for s in planned_portfolio if s["Navn"] == stock_to_buy), None)
        if stock_info:
            ticker = yf.Ticker(stock_info["Ticker"])
            try:
                current_price = ticker.history(period="1d")["Close"].iloc[-1]
                total_cost = current_price * buy_qty

                if total_cost <= cash_balance:
                    existing = next((h for h in holdings if h["Navn"] == stock_to_buy), None)
                    if existing:
                        # Genberegn gennemsnitlig købspris
                        total_shares = existing["Antal"] + buy_qty
                        total_cost_basis = (existing["Antal"] * existing["Købspris"]) + (buy_qty * current_price)
                        existing["Købspris"] = total_cost_basis / total_shares
                        existing["Antal"] = total_shares
                        existing["Nuværende_Pris"] = current_price
                    else:
                        holdings.append({
                            "Navn": stock_to_buy,
                            "Ticker": stock_info["Ticker"],
                            "Antal": buy_qty,
                            "Nuværende_Pris": current_price,
                            "Købspris": current_price,
                            "Kategori": stock_info["Kategori"]
                        })
                    cash_balance -= total_cost
                    save_db_data(holdings, cash_balance, total_dividends, last_div_check)
                    st.success(f"Købte {buy_qty} {stock_to_buy} for {total_cost:,.0f} kr")
                    st.rerun()
                else:
                    st.error("Ikke nok kontanter!")
            except Exception as e:
                st.error(f"Fejl: {e}")

# --- KØB CUSTOM AKTIER (VIA TICKER) ---
with st.sidebar.expander("Køb Nye Aktier"):
    st.markdown("**Køb aktier via ticker symbol**")
    st.markdown("Eksempler: AAPL, MSFT, TSLA, NVDA")

    custom_ticker = st.text_input("Ticker symbol (fx AAPL)", key="custom_ticker").upper().strip()
    custom_qty = st.number_input("Antal aktier", min_value=1, step=1, key="custom_qty")
    custom_category = st.selectbox("Vælg kategori", ["Høj", "Mellem", "Lav/Vækst", "Custom"], key="custom_cat")

    if st.button("Køb ny Aktie", key="custom_buy"):
        if custom_ticker:
            try:
                ticker = yf.Ticker(custom_ticker)
                info = ticker.info
                current_price = ticker.history(period="1d")["Close"].iloc[-1]
                stock_name = info.get("shortName", custom_ticker)

                total_cost = current_price * custom_qty

                if total_cost <= cash_balance:
                    existing = next((h for h in holdings if h["Ticker"] == custom_ticker), None)
                    if existing:
                        # Genberegn gennemsnitlig købspris
                        total_shares = existing["Antal"] + custom_qty
                        total_cost_basis = (existing["Antal"] * existing["Købspris"]) + (custom_qty * current_price)
                        existing["Købspris"] = total_cost_basis / total_shares
                        existing["Antal"] = total_shares
                        existing["Nuværende_Pris"] = current_price
                    else:
                        holdings.append({
                            "Navn": stock_name,
                            "Ticker": custom_ticker,
                            "Antal": custom_qty,
                            "Nuværende_Pris": current_price,
                            "Købspris": current_price,
                            "Kategori": custom_category
                        })
                    cash_balance -= total_cost
                    save_db_data(holdings, cash_balance, total_dividends, last_div_check)
                    st.success(f"✅ Købte {custom_qty} {stock_name} ({custom_ticker}) for {total_cost:,.0f} kr")
                    st.rerun()
                else:
                    st.error(f"Ikke nok kontanter! Mangler {total_cost - cash_balance:,.0f} kr")
            except Exception as e:
                st.error(f"Kunne ikke finde ticker '{custom_ticker}': {e}")
        else:
            st.warning("Indtast et ticker symbol")

# --- SÆLG AKTIER ---
with st.sidebar.expander("Sælg Aktier"):
    if holdings:
        stock_to_sell = st.selectbox("Vælg aktie", [h["Navn"] for h in holdings], key="sell_select")
        sell_qty = st.number_input("Antal at sælge", min_value=1, step=1, key="sell_qty")

        if st.button("Sælg"):
            holding = next((h for h in holdings if h["Navn"] == stock_to_sell), None)
            if holding and sell_qty <= holding["Antal"]:
                if "Nuværende_Pris" not in holding:
                    holding["Nuværende_Pris"] = 0

                sale_value = holding["Nuværende_Pris"] * sell_qty
                holding["Antal"] -= sell_qty
                if holding["Antal"] == 0:
                    holdings.remove(holding)
                cash_balance += sale_value
                save_db_data(holdings, cash_balance, total_dividends, last_div_check)
                st.success(f"Solgte {sell_qty} {stock_to_sell} for {sale_value:,.0f} kr")
                st.rerun()
            else:
                st.error("Ugyldigt antal!")
    else:
        st.info("Ingen aktier at sælge")

# --- HOVEDVISNING ---
st.sidebar.markdown("---")
st.sidebar.metric("Fælles Saldo", f"{cash_balance:,.0f} kr")

# Beregn porteføljeværdi og profit/loss
total_value = sum(h["Antal"] * h.get("Nuværende_Pris", 0) for h in holdings)
total_cost_basis = sum(h["Antal"] * h.get("Købspris", 0) for h in holdings)
profit_loss = total_value - total_cost_basis

col1, col2 = st.columns(2)
col1.metric(
    "Portefølje Værdi", 
    f"{total_value:,.0f} kr", 
    delta=f"{profit_loss:+,.0f} kr"
)
col2.metric("Kontant Saldo", f"{cash_balance:,.0f} kr")

# --- TABS ---
t1, t2, t3 = st.tabs(["Fordeling", "Beholdning", "Udbytte Kalender"])

with t1:
    st.subheader("Aktiv Fordeling")
    if holdings:
        df = pd.DataFrame([{
            "Aktiv": h["Navn"],
            "Værdi": h["Antal"] * h.get("Nuværende_Pris", 0),
            "Kategori": h.get("Kategori", "Ukendt")
        } for h in holdings])

        fig = px.pie(df, values="Værdi", names="Aktiv", title="Værdi Fordeling", hole=0.4)
        fig.update_traces(textposition='inside', textinfo='percent+label')
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Kategori Fordeling")
        cat_df = df.groupby("Kategori")["Værdi"].sum().reset_index()
        fig2 = px.bar(cat_df, x="Kategori", y="Værdi", title="Investering pr. Kategori", color="Kategori")
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("Ingen beholdninger endnu")

with t2:
    st.subheader("Mine Beholdninger")
    if holdings:
        beholdning_df = pd.DataFrame([{
            "Aktiv": h["Navn"],
            "Ticker": h["Ticker"],
            "Antal": h["Antal"],
            "Købspris": f"{h.get('Købspris', 0):.2f}",
            "Nuværende Kurs": f"{h.get('Nuværende_Pris', 0):.2f}",
            "Værdi": f"{h['Antal'] * h.get('Nuværende_Pris', 0):,.0f} kr",
            "Profit/Loss": f"{h['Antal'] * (h.get('Nuværende_Pris', 0) - h.get('Købspris', 0)):+,.0f} kr",
            "Kategori": h.get("Kategori", "Ukendt")
        } for h in holdings])
        st.dataframe(beholdning_df, use_container_width=True, hide_index=True)
    else:
        st.info("Ingen beholdninger")

with t3:
    st.subheader("Udbyttekalender - Næste 12 Måneder")

    if holdings:
        try:
            # Beregn datograenser (næste 12 måneder fra i dag)
            today = datetime.now().replace(tzinfo=None)
            one_year_from_now = today + timedelta(days=365)

            dividend_schedule = []
            annual_dividend_estimates = []

            for aktiv in holdings:
                ticker_symbol = aktiv["Ticker"]

                try:
                    ticker = yf.Ticker(ticker_symbol)
                    dividends = ticker.dividends

                    if dividends.empty:
                        continue

                    recent_divs = dividends.tail(4)

                    if len(recent_divs) >= 2:
                        dates = recent_divs.index
                        avg_days = (dates[-1] - dates[0]).days / (len(dates) - 1)
                        last_div_date = dates[-1].replace(tzinfo=None)

                        # Beregn estimeret årligt udbytte
                        avg_dividend_amount = recent_divs.mean()
                        dividends_per_year = 365 / avg_days if avg_days > 0 else 0
                        annual_dividend_per_share = avg_dividend_amount * dividends_per_year
                        total_annual_dividend = annual_dividend_per_share * aktiv["Antal"]

                        annual_dividend_estimates.append({
                            "Aktiv": aktiv["Navn"],
                            "Årligt Udbytte/Aktie": annual_dividend_per_share,
                            "Antal Aktier": aktiv["Antal"],
                            "Total Årligt": total_annual_dividend,
                            "Udbetalinger/År": dividends_per_year
                        })

                        # Generer datoer indtil vi har nok til næste år
                        i = 1
                        while i <= 20:
                            next_date = last_div_date + timedelta(days=int(avg_days * i))

                            if next_date > one_year_from_now:
                                break

                            if next_date > today:
                                dividend_schedule.append({
                                    "Aktiv": aktiv["Navn"],
                                    "Ticker": ticker_symbol,
                                    "Estimeret Dato": next_date,
                                    "Måned": next_date.strftime("%B %Y"),
                                    "Estimeret Beløb": f"{avg_dividend_amount:.2f}",
                                    "Dine Aktier": aktiv["Antal"],
                                    "Total Udbetaling": f"{avg_dividend_amount * aktiv['Antal']:.2f}"
                                })

                            i += 1

                except Exception as e:
                    continue

            # VIS ÅRLIGT ESTIMAT
            if annual_dividend_estimates:
                st.subheader("Estimeret Årligt Udbytte")

                df_annual = pd.DataFrame(annual_dividend_estimates)
                total_annual = df_annual["Total Årligt"].sum()

                # Metrics øverst
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Årligt Udbytte", f"{total_annual:,.0f} kr")
                col2.metric("Månedligt Gennemsnit", f"{total_annual/12:,.0f} kr")
                col3.metric("Portefølje Yield", f"{(total_annual/total_value*100):.2f}%" if total_value > 0 else "0%")

                # Detaljeret tabel
                st.dataframe(
                    df_annual[[
                        "Aktiv", 
                        "Antal Aktier", 
                        "Årligt Udbytte/Aktie", 
                        "Udbetalinger/År",
                        "Total Årligt"
                    ]].style.format({
                        "Årligt Udbytte/Aktie": "{:.2f} kr",
                        "Udbetalinger/År": "{:.1f}",
                        "Total Årligt": "{:,.0f} kr"
                    }),
                    use_container_width=True,
                    hide_index=True
                )

                st.markdown("---")

            # VIS KALENDER
            if dividend_schedule:
                st.subheader("Kommende Udbetalinger")

                df_div = pd.DataFrame(dividend_schedule)
                df_div = df_div.sort_values("Estimeret Dato")

                # Format dato til visning
                df_div["Dato"] = df_div["Estimeret Dato"].dt.strftime("%d-%m-%Y")

                st.dataframe(
                    df_div[["Dato", "Aktiv", "Ticker", "Estimeret Beløb", "Dine Aktier", "Total Udbetaling"]],
                    use_container_width=True,
                    hide_index=True
                )

                st.subheader("Månedlig Oversigt")
                monthly = df_div.groupby("Måned").size().reset_index(name="Antal Udbetalinger")

                col1, col2 = st.columns([2, 1])
                with col1:
                    fig_timeline = px.bar(
                        monthly, 
                        x="Måned", 
                        y="Antal Udbetalinger",
                        title="Forventet Udbytte pr. Måned (Næste 12 mdr)",
                        color="Antal Udbetalinger",
                        color_continuous_scale="Greens"
                    )
                    st.plotly_chart(fig_timeline, use_container_width=True)

                with col2:
                    st.metric("Total Udbetalinger", len(df_div))
                    if len(monthly) > 0:
                        most_active = monthly.loc[monthly["Antal Udbetalinger"].idxmax(), "Måned"]
                        st.metric("Mest aktiv måned", most_active)
            else:
                st.info("Ingen kommende udbytter fundet i de næste 12 måneder.")

        except Exception as e:
            st.error(f"Fejl ved beregning af udbyttekalender: {e}")
            st.exception(e)
    else:
        st.info("Køb aktier for at se udbyttekalender")