import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
import plotly.graph_objects as go

# ─────────────────────────────────────────────
# CONFIG — fill these in
# ─────────────────────────────────────────────
SENDER_EMAIL = "your_email@gmail.com"       # Gmail address you send FROM
SENDER_PASSWORD = "your_app_password_here"  # Gmail App Password (not your real password)
SUBSCRIBERS_FILE = "subscribers.csv"
ALERTS_LOG_FILE = "alerts_log.csv"

# ─────────────────────────────────────────────
# STORAGE HELPERS
# ─────────────────────────────────────────────
def load_subscribers():
    if os.path.exists(SUBSCRIBERS_FILE):
        return pd.read_csv(SUBSCRIBERS_FILE)
    return pd.DataFrame(columns=["email", "ticker", "subscribed_at"])

def save_subscriber(email, ticker):
    df = load_subscribers()
    email = email.strip().lower()
    ticker = ticker.strip().upper()
    # Avoid duplicates
    exists = ((df["email"] == email) & (df["ticker"] == ticker)).any()
    if not exists:
        new_row = pd.DataFrame([{
            "email": email,
            "ticker": ticker,
            "subscribed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }])
        df = pd.concat([df, new_row], ignore_index=True)
        df.to_csv(SUBSCRIBERS_FILE, index=False)
        return True
    return False  # already subscribed

def load_alerts_log():
    if os.path.exists(ALERTS_LOG_FILE):
        return pd.read_csv(ALERTS_LOG_FILE)
    return pd.DataFrame(columns=["ticker", "cross_type", "cross_date", "emailed_at", "emails_sent_to"])

def log_alert(ticker, cross_type, cross_date, emails):
    df = load_alerts_log()
    new_row = pd.DataFrame([{
        "ticker": ticker,
        "cross_type": cross_type,
        "cross_date": str(cross_date),
        "emailed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "emails_sent_to": ", ".join(emails)
    }])
    df = pd.concat([df, new_row], ignore_index=True)
    df.to_csv(ALERTS_LOG_FILE, index=False)

# ─────────────────────────────────────────────
# DATA & CROSS DETECTION
# ─────────────────────────────────────────────
@st.cache_data(ttl=3600)
def fetch_data(ticker, period="2y"):
    df = yf.download(ticker, period=period, auto_adjust=True, progress=False)
    df = df[["Close"]].copy()
    df.columns = ["Close"]
    df["SMA50"] = df["Close"].rolling(window=50).mean()
    df["SMA200"] = df["Close"].rolling(window=200).mean()
    df.dropna(inplace=True)
    return df

def detect_crosses(df):
    """Returns list of (date, cross_type) for all crosses in the data."""
    crosses = []
    prev_above = df["SMA50"].iloc[0] > df["SMA200"].iloc[0]
    for i in range(1, len(df)):
        curr_above = df["SMA50"].iloc[i] > df["SMA200"].iloc[i]
        if not prev_above and curr_above:
            crosses.append((df.index[i], "Golden Cross 🟡"))
        elif prev_above and not curr_above:
            crosses.append((df.index[i], "Death Cross 💀"))
        prev_above = curr_above
    return crosses

def get_latest_cross(df):
    crosses = detect_crosses(df)
    if crosses:
        return crosses[-1]
    return None

# ─────────────────────────────────────────────
# EMAIL
# ─────────────────────────────────────────────
def send_email(to_email, ticker, cross_type, cross_date, close_price):
    is_golden = "Golden" in cross_type
    color = "#f5a623" if is_golden else "#d0021b"
    signal = "BUY signal" if is_golden else "SELL/caution signal"
    emoji = "🟡" if is_golden else "💀"

    subject = f"{emoji} {cross_type} detected for {ticker}!"
    html_body = f"""
    <html><body style="font-family: Arial, sans-serif; background: #f4f4f4; padding: 20px;">
      <div style="max-width:560px; margin:auto; background:white; border-radius:8px; overflow:hidden; box-shadow:0 2px 8px rgba(0,0,0,0.1);">
        <div style="background:{color}; padding:24px; text-align:center;">
          <h1 style="color:white; margin:0; font-size:28px;">{emoji} {cross_type}</h1>
          <p style="color:white; margin:8px 0 0; opacity:0.9;">Stock Alert Notification</p>
        </div>
        <div style="padding:32px;">
          <p style="font-size:16px; color:#333;">A <strong>{cross_type}</strong> has been detected for <strong>{ticker}</strong>.</p>
          <table style="width:100%; border-collapse:collapse; margin:20px 0;">
            <tr style="background:#f9f9f9;">
              <td style="padding:12px; border:1px solid #eee; color:#666;">Ticker</td>
              <td style="padding:12px; border:1px solid #eee; font-weight:bold;">{ticker}</td>
            </tr>
            <tr>
              <td style="padding:12px; border:1px solid #eee; color:#666;">Cross Date</td>
              <td style="padding:12px; border:1px solid #eee; font-weight:bold;">{cross_date}</td>
            </tr>
            <tr style="background:#f9f9f9;">
              <td style="padding:12px; border:1px solid #eee; color:#666;">Close Price</td>
              <td style="padding:12px; border:1px solid #eee; font-weight:bold;">${close_price:.2f}</td>
            </tr>
            <tr>
              <td style="padding:12px; border:1px solid #eee; color:#666;">Signal</td>
              <td style="padding:12px; border:1px solid #eee; font-weight:bold; color:{color};">{signal}</td>
            </tr>
          </table>
          <p style="font-size:13px; color:#999;">This is an automated alert. Past signals do not guarantee future performance.</p>
        </div>
      </div>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SENDER_EMAIL
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, to_email, msg.as_string())
        return True
    except Exception as e:
        st.error(f"Email error: {e}")
        return False

def check_and_alert(ticker, df):
    """Check for a recent cross and email all subscribers for this ticker."""
    latest = get_latest_cross(df)
    if not latest:
        return

    cross_date, cross_type = latest
    # Only alert if cross is within the last 3 days
    if pd.Timestamp(cross_date) < pd.Timestamp(datetime.now() - timedelta(days=3)):
        return

    close_price = float(df.loc[cross_date, "Close"])
    subscribers = load_subscribers()
    ticker_subs = subscribers[subscribers["ticker"] == ticker]["email"].tolist()

    if not ticker_subs:
        return

    log = load_alerts_log()
    already_sent = (
        (log["ticker"] == ticker) &
        (log["cross_date"] == str(cross_date))
    ).any()

    if already_sent:
        return

    sent_to = []
    for email in ticker_subs:
        if send_email(email, ticker, cross_type, cross_date.date(), close_price):
            sent_to.append(email)

    if sent_to:
        log_alert(ticker, cross_type, cross_date, sent_to)
        st.success(f"📧 Alert emails sent to {len(sent_to)} subscriber(s) for {cross_type} on {ticker}!")

# ─────────────────────────────────────────────
# CHART
# ─────────────────────────────────────────────
def build_chart(df, ticker, crosses):
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df.index, y=df["Close"],
        name="Close Price", line=dict(color="#4a90d9", width=1.5), opacity=0.8
    ))
    fig.add_trace(go.Scatter(
        x=df.index, y=df["SMA50"],
        name="SMA 50", line=dict(color="#f5a623", width=2, dash="dot")
    ))
    fig.add_trace(go.Scatter(
        x=df.index, y=df["SMA200"],
        name="SMA 200", line=dict(color="#d0021b", width=2, dash="dash")
    ))

    for date, ctype in crosses:
        is_golden = "Golden" in ctype
        fig.add_vline(
            x=date, line_width=1.5,
            line_dash="dash",
            line_color="#f5a623" if is_golden else "#d0021b"
        )
        fig.add_annotation(
            x=date,
            y=float(df.loc[date, "Close"]),
            text="🟡 GC" if is_golden else "💀 DC",
            showarrow=True, arrowhead=2,
            bgcolor="#f5a623" if is_golden else "#d0021b",
            font=dict(color="white", size=11),
            arrowcolor="#f5a623" if is_golden else "#d0021b",
        )

    fig.update_layout(
        title=f"{ticker} — Golden & Death Cross Chart",
        xaxis_title="Date",
        yaxis_title="Price (USD)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        template="plotly_dark",
        height=500,
    )
    return fig

# ─────────────────────────────────────────────
# STREAMLIT UI
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Cross Signal Tracker",
    page_icon="📈",
    layout="wide"
)

st.markdown("""
    <style>
        .main { background-color: #0f1117; }
        .block-container { padding-top: 2rem; }
        h1 { color: #f5a623; }
        .stMetric label { color: #aaa; }
    </style>
""", unsafe_allow_html=True)

st.title("📈 Golden & Death Cross Tracker")
st.caption("Detect SMA 50/200 crossovers and subscribe for email alerts.")

# ── Sidebar ──
with st.sidebar:
    st.header("🔍 Analyze a Stock")
    ticker_input = st.text_input("Ticker Symbol", value="AAPL", max_chars=10).upper()
    period = st.selectbox("Lookback Period", ["1y", "2y", "5y"], index=1)
    analyze_btn = st.button("Analyze", use_container_width=True)

    st.divider()
    st.header("📧 Subscribe to Alerts")
    sub_ticker = st.text_input("Ticker to Watch", value="AAPL", max_chars=10).upper()
    sub_email = st.text_input("Your Email Address")
    subscribe_btn = st.button("Subscribe", use_container_width=True)

    if subscribe_btn:
        if sub_email and "@" in sub_email:
            added = save_subscriber(sub_email, sub_ticker)
            if added:
                st.success(f"✅ Subscribed {sub_email} to {sub_ticker} alerts!")
            else:
                st.info("You're already subscribed to this ticker.")
        else:
            st.error("Please enter a valid email.")

    st.divider()
    st.header("📋 Subscribers")
    subs_df = load_subscribers()
    if not subs_df.empty:
        st.dataframe(subs_df[["email", "ticker"]], use_container_width=True, hide_index=True)
    else:
        st.caption("No subscribers yet.")

# ── Main Content ──
if analyze_btn or "df" not in st.session_state:
    with st.spinner(f"Fetching data for {ticker_input}..."):
        try:
            df = fetch_data(ticker_input, period)
            st.session_state["df"] = df
            st.session_state["ticker"] = ticker_input
        except Exception as e:
            st.error(f"Could not fetch data: {e}")
            st.stop()

if "df" in st.session_state:
    df = st.session_state["df"]
    ticker = st.session_state["ticker"]
    crosses = detect_crosses(df)
    latest = get_latest_cross(df)

    # ── Metrics ──
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Current Price", f"${df['Close'].iloc[-1]:.2f}")
    with col2:
        st.metric("SMA 50", f"${df['SMA50'].iloc[-1]:.2f}")
    with col3:
        st.metric("SMA 200", f"${df['SMA200'].iloc[-1]:.2f}")
    with col4:
        if latest:
            date, ctype = latest
            st.metric("Latest Cross", ctype.split()[0] + " Cross", delta=str(date.date()))
        else:
            st.metric("Latest Cross", "None detected")

    # ── Chart ──
    st.plotly_chart(build_chart(df, ticker, crosses), use_container_width=True)

    # ── Cross History Table ──
    st.subheader("📅 Cross History")
    if crosses:
        cross_df = pd.DataFrame(crosses, columns=["Date", "Type"])
        cross_df["Date"] = cross_df["Date"].dt.date
        st.dataframe(cross_df[::-1], use_container_width=True, hide_index=True)
    else:
        st.info("No crosses detected in this time range.")

    # ── Check & Send Alerts ──
    st.divider()
    if st.button("🔔 Check for New Alerts & Send Emails"):
        check_and_alert(ticker, df)

    # ── Alert Log ──
    st.subheader("📬 Alert Log")
    log_df = load_alerts_log()
    if not log_df.empty:
        st.dataframe(log_df[::-1], use_container_width=True, hide_index=True)
    else:
        st.caption("No alerts sent yet.")
