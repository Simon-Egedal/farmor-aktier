import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import yfinance as yf
from pymongo import MongoClient
import plotly.graph_objects as go
import plotly.express as px
import numpy as np

# Page configuration
st.set_page_config(page_title="Aktieportfolio Manager", layout="wide", initial_sidebar_state="expanded")

# Initialize session state for caching
if "stock_cache" not in st.session_state:
    st.session_state.stock_cache = {}
    st.session_state.stock_cache_time = {}
if "dividend_cache" not in st.session_state:
    st.session_state.dividend_cache = {}
    st.session_state.dividend_cache_time = {}

# Custom CSS
st.markdown("""
    <style>
    .metric-card {
        background-color: #f0f2f6;
        padding: 20px;
        border-radius: 10px;
        text-align: center;
        margin: 10px;
    }
    .metric-value {
        font-size: 32px;
        font-weight: bold;
        color: #0066cc;
    }
    .metric-label {
        font-size: 14px;
        color: #666;
    }
    </style>
""", unsafe_allow_html=True)

# MongoDB Connection
CONNECTION_STRING = st.secrets["MONGODB_CONNECTION_STRING"]

@st.cache_resource
def init_mongodb():
    try:
        client = MongoClient(CONNECTION_STRING, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
        client.admin.command('ping')
        return client
    except Exception as e:
        print(f"MongoDB connection error: {e}")  # Log to console instead of showing to user
        return None

client = init_mongodb()
db = None
portfolio_collection = None
transactions_collection = None
cash_collection = None
dividends_collection = None

if client:
    try:
        db = client["stock_portfolio"]
        portfolio_collection = db["portfolio"]
        transactions_collection = db["transactions"]
        cash_collection = db["cash"]
        dividends_collection = db["dividends"]
        
        # Initialize cash if not exists
        if cash_collection.count_documents({}) == 0:
            cash_collection.insert_one({"amount": 0.0, "currency": "DKK"})
    except Exception as e:
        print(f"Database initialization error: {e}")
        client = None

# Cache for stock data and currency rates
@st.cache_data(ttl=600)
def get_exchange_rate(from_currency, to_currency="DKK"):
    if from_currency == to_currency:
        return 1.0
    
    try:
        ticker = yf.Ticker(f"{from_currency}{to_currency}=X")
        rate = ticker.history(period="1d")['Close'].iloc[-1]
        return rate
    except Exception:
        fallback_rates = {
            "USD_DKK": 6.85,
            "EUR_DKK": 7.45,
            "GBP_DKK": 8.65,
            "SEK_DKK": 0.64,
            "NOK_DKK": 0.63,
            "CHF_DKK": 7.85
        }
        return fallback_rates.get(f"{from_currency}_{to_currency}", 1.0)

@st.cache_data(ttl=600)
def get_stock_data(ticker_symbol):
    try:
        ticker = yf.Ticker(ticker_symbol)
        history = ticker.history(period="1d")
        
        if not history.empty:
            current_price = history['Close'].iloc[-1]
            info = ticker.fast_info
            currency = getattr(info, 'currency', 'DKK')
            
            full_info = ticker.info
            stock_name = full_info.get('longName', full_info.get('shortName', ticker_symbol))
            
            return {
                'price': current_price,
                'currency': currency,
                'name': stock_name
            }
    except Exception as e:
        pass  # Silent fail - yfinance may have network issues on deployment
    return None

@st.cache_data(ttl=600)
def get_all_stocks_data_batch(tickers_tuple):
    """Hent data for flere aktier med caching"""
    result = {}
    for ticker in tickers_tuple:
        try:
            data = get_stock_data(ticker)
            if data:
                result[ticker] = data
        except Exception as e:
            pass  # Silent fail for better performance
    return result

def make_datetime_naive(dt):
    if dt is None:
        return None
    if isinstance(dt, pd.Timestamp):
        dt = dt.to_pydatetime()
    if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt

def get_cash_balance():
    try:
        cash_doc = cash_collection.find_one({})
        return cash_doc.get("amount", 0.0) if cash_doc else 0.0
    except Exception as e:
        st.error(f"Fejl ved hentning af saldo: {e}")
        return 0.0

def get_portfolio_value():
    total = 0.0
    try:
        stocks = list(portfolio_collection.find({}))
        tickers = tuple([stock['ticker'] for stock in stocks])
        
        stocks_data = get_all_stocks_data_batch(tickers)
        
        for stock in stocks:
            ticker_symbol = stock['ticker']
            if ticker_symbol in stocks_data:
                data = stocks_data[ticker_symbol]
                current_price = data['price']
                currency = data['currency']
                rate = get_exchange_rate(currency, "DKK")
                total += current_price * stock['shares'] * rate
    except Exception as e:
        st.error(f"Fejl ved beregning af portfolio værdi: {e}")
    return total

def calculate_regular_dividend(ticker_symbol, div_data):
    """
    FORBEDRET UDBYTTE LOGIK - Beregner KUN regelmæssige udbytter
    """
    try:
        if not div_data:
            return 0.0
            
        # METODE 1: Forward Dividend Rate (mest pålidelig)
        info = div_data.get('info', {})
        if not info:
            return 0.0
            
        forward_dividend = info.get('dividendRate', None)

        if forward_dividend and forward_dividend > 0:
            return forward_dividend

        # METODE 2: Trailing Dividend Yield omregnet
        trailing_yield = info.get('trailingAnnualDividendYield', None)
        current_price = info.get('currentPrice', None)

        if trailing_yield and current_price and current_price > 0:
            trailing_dividend = trailing_yield * current_price
            if trailing_dividend > 0:
                return trailing_dividend

        # METODE 3: Beregn fra historik MED OUTLIER DETECTION
        dividends = div_data.get('dividends', None)
        if dividends is None or len(dividends) == 0:
            return 0.0

        if len(dividends) >= 4:  # Mindst 4 udbytter for god estimation
            one_year_ago = datetime.now() - timedelta(days=365)
            div_dates_naive = [make_datetime_naive(d) for d in dividends.index]

            # Find udbytter fra sidste år
            last_year_divs = []
            for i, div_date in enumerate(div_dates_naive):
                if div_date and div_date > one_year_ago:
                    last_year_divs.append(dividends.iloc[i])

            if len(last_year_divs) >= 2:
                # STATISTISK OUTLIER DETECTION
                divs_array = np.array(last_year_divs)

                # Beregn Q1, Q3 og IQR (Interquartile Range)
                q1 = np.percentile(divs_array, 25)
                q3 = np.percentile(divs_array, 75)
                iqr = q3 - q1

                # Outlier grænser: Q1 - 1.5*IQR og Q3 + 1.5*IQR
                lower_bound = q1 - 1.5 * iqr
                upper_bound = q3 + 1.5 * iqr

                # Filtrer outliers (ekstraordinære udbytter)
                regular_divs = [d for d in last_year_divs if lower_bound <= d <= upper_bound]

                if len(regular_divs) > 0:
                    annual_dividend = sum(regular_divs)
                    return annual_dividend

        # METODE 4: Sidste 4 kvartaler hvis data findes
        if len(dividends) >= 4:
            last_4 = dividends.iloc[-4:].values

            # Tjek om de 4 seneste er relativt ensartede (ikke outliers)
            median_val = np.median(last_4)
            regular_vals = [d for d in last_4 if d < median_val * 2.5]

            if len(regular_vals) >= 3:
                annual_dividend = sum(regular_vals) * (4 / len(regular_vals))
                return annual_dividend

        return 0.0

    except Exception as e:
        st.warning(f"Fejl ved dividend beregning for {ticker_symbol}: {e}")
        return 0.0

def get_dividend_data(ticker_symbol):
    """Hent og cache dividend data"""
    try:
        ticker = yf.Ticker(ticker_symbol)
        dividends = ticker.dividends
        info = ticker.info
        
        return {
            'dividends': dividends,
            'info': info
        }
    except Exception:
        return None

def calculate_estimated_annual_dividend():
    total = 0.0
    try:
        stocks = list(portfolio_collection.find({}))
        
        for stock in stocks:
            try:
                ticker_symbol = stock['ticker']
                div_data = get_dividend_data(ticker_symbol)
                if not div_data:
                    continue
                
                annual_dividend = calculate_regular_dividend(ticker_symbol, div_data)
                
                if annual_dividend > 0:
                    info = div_data['info']
                    currency = info.get('currency', 'DKK')
                    rate = get_exchange_rate(currency, "DKK")
                    total += annual_dividend * stock['shares'] * rate
            except Exception as e:
                st.warning(f"Fejl ved udbytte for {stock['ticker']}: {e}")
    except Exception as e:
        st.error(f"Fejl ved samlet udbytte: {e}")
    return total

def show_dashboard():
    st.title("📊 Dashboard")
    
    # Use session state for caching calculations
    cache_key = "dashboard_data"
    if cache_key not in st.session_state:
        st.session_state[cache_key] = {
            "cash_balance": get_cash_balance(),
            "portfolio_value": get_portfolio_value(),
            "annual_dividend": calculate_estimated_annual_dividend()
        }
    
    data = st.session_state[cache_key]
    cash_balance = data["cash_balance"]
    portfolio_value = data["portfolio_value"]
    annual_dividend = data["annual_dividend"]
    total_value = cash_balance + portfolio_value
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Kontant Saldo", f"{cash_balance:,.2f} DKK")
    
    with col2:
        st.metric("Portfolio Værdi", f"{portfolio_value:,.2f} DKK")
    
    with col3:
        st.metric("Total Værdi", f"{total_value:,.2f} DKK")
    
    with col4:
        st.metric("Årligt Udbytte (Est.)", f"{annual_dividend:,.2f} DKK")
    
    st.divider()
    
    # Allocation chart
    try:
        stocks = list(portfolio_collection.find({}))
        if stocks:
            tickers = tuple([stock['ticker'] for stock in stocks])
            stocks_data = get_all_stocks_data_batch(tickers)
            
            labels = []
            values = []
            
            for stock in stocks:
                ticker_symbol = stock['ticker']
                if ticker_symbol in stocks_data:
                    data = stocks_data[ticker_symbol]
                    current_price = data['price']
                    currency = data['currency']
                    rate = get_exchange_rate(currency, "DKK")
                    value = current_price * stock['shares'] * rate
                    labels.append(ticker_symbol)
                    values.append(value)
            
            if values:
                fig = go.Figure(data=[go.Pie(labels=labels, values=values, textinfo="label+percent")])
                fig.update_layout(title="Aktiefordeling", height=500)
                st.plotly_chart(fig, width='stretch')
    except Exception:
        pass

def show_stocks():
    st.title("📈 Mine Aktier")
    
    try:
        stocks = list(portfolio_collection.find({}))
        if not stocks:
            st.info("Ingen aktier i portfolio")
            return
        
        tickers = tuple([stock['ticker'] for stock in stocks])
        stocks_data = get_all_stocks_data_batch(tickers)
        
        stock_list = []
        total_profit_loss = 0.0
        total_buy_value = 0.0
        total_current_value = 0.0
        
        for stock in stocks:
            ticker_symbol = stock['ticker']
            if ticker_symbol not in stocks_data:
                continue
            
            data = stocks_data[ticker_symbol]
            current_price = data['price']
            currency = data['currency']
            stock_name = data.get('name', ticker_symbol)
            rate = get_exchange_rate(currency, "DKK")
            
            current_price_dkk = current_price * rate
            buy_price_dkk = stock['buy_price'] * rate
            shares = stock['shares']
            
            current_value = current_price_dkk * shares
            buy_value = buy_price_dkk * shares
            profit_loss = current_value - buy_value
            profit_loss_pct = (profit_loss / buy_value) * 100 if buy_value > 0 else 0
            
            total_profit_loss += profit_loss
            total_buy_value += buy_value
            total_current_value += current_value
            
            stock_list.append({
                "Navn": stock_name[:25],
                "Ticker": ticker_symbol,
                "Antal": shares,
                "Købskurs": f"{buy_price_dkk:.2f}",
                "Nuværende": f"{current_price_dkk:.2f}",
                "Værdi": f"{current_value:,.2f}",
                "Gevinst/Tab": f"{profit_loss:,.2f}",
                "Gevinst %": f"{profit_loss_pct:.2f}%"
            })
        
        # Display summary
        total_profit_pct = (total_profit_loss / total_buy_value) * 100 if total_buy_value > 0 else 0
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Samlet Investering", f"{total_buy_value:,.2f} DKK")
        with col2:
            st.metric("Aktuel Værdi", f"{total_current_value:,.2f} DKK")
        with col3:
            profit_color = "green" if total_profit_loss >= 0 else "red"
            st.metric(
                "Total Fortjeneste", 
                f"{total_profit_loss:,.2f} DKK",
                f"{total_profit_pct:.2f}%",
                delta_color="normal"
            )
        
        st.divider()
        
        if stock_list:
            df = pd.DataFrame(stock_list)
            st.dataframe(df, width='stretch', hide_index=True)
        else:
            st.info("Ingen aktier data tilgængelig")
    except Exception as e:
        st.error(f"Fejl ved hentning af aktier: {e}")

def show_buy_stocks():
    st.title("🛒 Køb Aktier")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Køb Nye Aktier (Automatisk Pris)")
        
        ticker = st.text_input("Ticker (f.eks. AAPL)", key="buy_ticker")
        shares = st.number_input("Antal aktier", min_value=1, value=1, key="buy_shares")
        
        if st.button("Køb"):
            ticker = ticker.upper()
            if not ticker:
                st.error("Indtast ticker")
            else:
                data = get_stock_data(ticker)
                if not data:
                    st.error(f"Kunne ikke hente data for {ticker}")
                else:
                    current_price = data['price']
                    currency = data['currency']
                    rate = get_exchange_rate(currency, "DKK")
                    total_cost = current_price * shares * rate
                    
                    cash_balance = get_cash_balance()
                    if total_cost > cash_balance:
                        st.error(f"Ikke nok kontanter! Du har {cash_balance:,.2f} DKK")
                    else:
                        existing = portfolio_collection.find_one({"ticker": ticker})
                        if existing:
                            new_total_shares = existing['shares'] + shares
                            new_avg_price = ((existing['buy_price'] * existing['shares']) +
                                            (current_price * shares)) / new_total_shares
                            portfolio_collection.update_one(
                                {"ticker": ticker},
                                {"$set": {"shares": new_total_shares, "buy_price": new_avg_price}}
                            )
                        else:
                            portfolio_collection.insert_one({
                                "ticker": ticker,
                                "shares": shares,
                                "buy_price": current_price,
                                "currency": currency,
                                "buy_date": datetime.now()
                            })
                        
                        cash_collection.update_one({}, {"$inc": {"amount": -total_cost}})
                        
                        transactions_collection.insert_one({
                            "type": "buy",
                            "ticker": ticker,
                            "shares": shares,
                            "price": current_price,
                            "currency": currency,
                            "total": total_cost,
                            "date": datetime.now()
                        })
                        
                        st.success(f"✅ Købte {shares} {ticker} for {total_cost:,.2f} DKK")
                        st.rerun()
    
    with col2:
        st.subheader("Tilføj Gamle Aktier (Manuel Pris)")
        
        old_ticker = st.text_input("Ticker", key="old_ticker")
        old_price = st.number_input("Købskurs", min_value=0.0, value=0.0, key="old_price")
        old_shares = st.number_input("Antal aktier", min_value=1, value=1, key="old_shares")
        
        if st.button("Tilføj"):
            old_ticker = old_ticker.upper()
            if not old_ticker:
                st.error("Indtast ticker")
            else:
                data = get_stock_data(old_ticker)
                if not data:
                    st.error(f"Kunne ikke hente data for {old_ticker}")
                else:
                    currency = data['currency']
                    rate = get_exchange_rate(currency, "DKK")
                    total_cost = old_price * old_shares * rate
                    
                    cash_balance = get_cash_balance()
                    if total_cost > cash_balance:
                        st.error(f"Ikke nok kontanter! Du har {cash_balance:,.2f} DKK")
                    else:
                        existing = portfolio_collection.find_one({"ticker": old_ticker})
                        if existing:
                            new_total_shares = existing['shares'] + old_shares
                            new_avg_price = ((existing['buy_price'] * existing['shares']) +
                                            (old_price * old_shares)) / new_total_shares
                            portfolio_collection.update_one(
                                {"ticker": old_ticker},
                                {"$set": {"shares": new_total_shares, "buy_price": new_avg_price}}
                            )
                        else:
                            portfolio_collection.insert_one({
                                "ticker": old_ticker,
                                "shares": old_shares,
                                "buy_price": old_price,
                                "currency": currency,
                                "buy_date": datetime.now()
                            })
                        
                        cash_collection.update_one({}, {"$inc": {"amount": -total_cost}})
                        
                        transactions_collection.insert_one({
                            "type": "buy",
                            "ticker": old_ticker,
                            "shares": old_shares,
                            "price": old_price,
                            "currency": currency,
                            "total": total_cost,
                            "date": datetime.now()
                        })
                        
                        st.success(f"✅ Tilføjede {old_shares} {old_ticker}")
                        st.rerun()

def show_dividends():
    st.title("💰 Udbytter")
    
    # Use session state to cache dividend calculations
    cache_key = "dividends_data"
    
    if cache_key not in st.session_state:
        # Calculate once and store
        st.session_state[cache_key] = {
            "annual": calculate_estimated_annual_dividend(),
            "upcoming": None  # Will calculate on demand
        }
    
    annual_dividend = st.session_state[cache_key]["annual"]
    monthly_avg = annual_dividend / 12 if annual_dividend > 0 else 0
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Estimeret Årligt Udbytte", f"{annual_dividend:,.2f} DKK")
    with col2:
        st.metric("Månedligt Gennemsnit", f"{monthly_avg:,.2f} DKK")
    
    st.divider()
    st.subheader("📅 Kommende Udbytter (næste 12 måneder)")
    
    try:
        stocks = list(portfolio_collection.find({}))
        if not stocks:
            st.info("Ingen aktier i portfolio")
            return
        
        tickers = tuple([stock['ticker'] for stock in stocks])
        stocks_data = get_all_stocks_data_batch(tickers)
        
        dividends_list = []
        
        for stock in stocks:
            ticker_symbol = stock['ticker']
            stock_name = stocks_data.get(ticker_symbol, {}).get('name', ticker_symbol)
            
            div_data = get_dividend_data(ticker_symbol)
            if not div_data:
                continue
            
            dividends = div_data.get('dividends')
            if dividends is None or len(dividends) == 0:
                continue
            
            if len(dividends) >= 3:
                div_dates_naive = [make_datetime_naive(d) for d in dividends.index]
                
                last_div_date = div_dates_naive[-1]
                two_years_ago = datetime.now() - timedelta(days=730)
                
                if last_div_date < two_years_ago:
                    continue
                
                recent_dates = div_dates_naive[-min(5, len(div_dates_naive)):]
                
                intervals = []
                for i in range(1, len(recent_dates)):
                    interval = (recent_dates[i] - recent_dates[i-1]).days
                    if interval > 0:
                        intervals.append(interval)
                
                if not intervals:
                    continue
                
                intervals.sort()
                median_interval = intervals[len(intervals)//2]
                
                if median_interval > 300:
                    expected_payments = 1
                elif median_interval > 150:
                    expected_payments = 2
                elif median_interval > 60:
                    expected_payments = 4
                else:
                    expected_payments = 12
                
                if median_interval < 400:
                    annual_dividend_stock = calculate_regular_dividend(ticker_symbol, div_data)
                    
                    if annual_dividend_stock > 0:
                        info = div_data.get('info', {})
                        currency = info.get('currency', 'DKK')
                        rate = get_exchange_rate(currency, "DKK")
                        current_price = info.get('currentPrice', 0)
                        
                        dividend_per_payment = annual_dividend_stock / expected_payments
                        
                        current_date = last_div_date
                        one_year_from_now = datetime.now() + timedelta(days=365)
                        payment_count = 0
                        payment_delay = 25
                        
                        while current_date < one_year_from_now and payment_count < expected_payments:
                            current_date = current_date + timedelta(days=median_interval)
                            
                            if current_date > datetime.now() and current_date <= one_year_from_now:
                                amount = dividend_per_payment * stock['shares'] * rate
                                payment_date = current_date + timedelta(days=payment_delay)
                                
                                price_dkk = current_price * rate if current_price else 0
                                dividends_list.append({
                                    "Selskab": f"{stock_name} ({ticker_symbol})",
                                    "Pris": f"{price_dkk:.2f} DKK",
                                    "Udbetalingsdato": payment_date.strftime('%d/%m/%Y'),
                                    "Beløb": f"{amount:,.2f} DKK"
                                })
                                payment_count += 1
        
        if dividends_list:
            df = pd.DataFrame(dividends_list)
            df['Sort_Date'] = pd.to_datetime(df['Udbetalingsdato'], format='%d/%m/%Y')
            df = df.sort_values('Sort_Date').drop('Sort_Date', axis=1)
            
            st.dataframe(df, width='stretch', hide_index=True)
        else:
            st.info("❌ Ingen kommende udbytter fundet")
    
    except Exception:
        pass

def show_cash_management():
    st.title("🏦 Kontanthåndtering")
    
    cash_balance = get_cash_balance()
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.metric("Nuværende Saldo", f"{cash_balance:,.2f} DKK")
        
        st.subheader("Indsæt Penge")
        deposit_amount = st.number_input("Beløb i DKK", min_value=0.0, value=0.0, key="deposit")
        
        if st.button("Indsæt"):
            if deposit_amount > 0:
                cash_collection.update_one({}, {"$inc": {"amount": deposit_amount}})
                transactions_collection.insert_one({
                    "type": "deposit",
                    "amount": deposit_amount,
                    "date": datetime.now()
                })
                st.success(f"✅ Indsat {deposit_amount:,.2f} DKK")
                st.rerun()
            else:
                st.error("Beløb skal være større end 0")
    
    with col2:
        st.subheader("Hæv Penge")
        withdraw_amount = st.number_input("Beløb i DKK", min_value=0.0, value=0.0, key="withdraw")
        
        if st.button("Hæv"):
            if withdraw_amount > 0:
                if withdraw_amount <= cash_balance:
                    cash_collection.update_one({}, {"$inc": {"amount": -withdraw_amount}})
                    transactions_collection.insert_one({
                        "type": "withdrawal",
                        "amount": withdraw_amount,
                        "date": datetime.now()
                    })
                    st.success(f"✅ Hævet {withdraw_amount:,.2f} DKK")
                    st.rerun()
                else:
                    st.error("Ikke nok penge!")
            else:
                st.error("Beløb skal være større end 0")

# Main app navigation
def show_login():
    """Login page"""
    st.markdown("""
        <style>
        .login-container {
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
        }
        .login-box {
            text-align: center;
            padding: 40px;
            border-radius: 10px;
            background-color: #1e1e1e;
        }
        </style>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("## 🔐 Aktieportfolio Login")
        st.markdown("---")
        
        username = st.text_input("Brugernavn", placeholder="Indtast brugernavn")
        password = st.text_input("Adgangskode", type="password", placeholder="Indtast adgangskode")
        
        col_btn1, col_btn2 = st.columns(2)
        
        with col_btn1:
            if st.button("Login", use_container_width=True):
                if username and password:
                    st.session_state.logged_in = True
                    st.session_state.username = username
                    st.rerun()
                else:
                    st.error("❌ Venligst udfyld brugernavn og adgangskode")
        
        with col_btn2:
            st.button("Annuller", use_container_width=True)

def main():
    # Initialize session state
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    
    # Show login or main app
    if not st.session_state.logged_in:
        show_login()
    else:
        # Sidebar with logout
        st.sidebar.title("🏠 Aktieportfolio Manager")
        
        if st.sidebar.button("🚪 Log ud", use_container_width=True):
            st.session_state.logged_in = False
            st.rerun()
        
        st.sidebar.markdown("---")
        
        page = st.sidebar.radio("Navigation", ["Dashboard", "Mine Aktier", "Køb Aktier", "Udbytter", "Kontanter"])
        
        if page == "Dashboard":
            show_dashboard()
        elif page == "Mine Aktier":
            show_stocks()
        elif page == "Køb Aktier":
            show_buy_stocks()
        elif page == "Udbytter":
            show_dividends()
        elif page == "Kontanter":
            show_cash_management()

if __name__ == "__main__":
    main()
