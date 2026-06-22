import datetime
import pandas as pd
import altair as alt
import streamlit as st
from google.ads.googleads.client import GoogleAdsClient

st.set_page_config(page_title="Koras 광고 대시보드", layout="wide")

START_DATE = st.secrets.get("GOOGLE_START_DATE", "2026-04-01")

@st.cache_data(ttl=3600)   # 1시간마다 새로 불러옴
def load_data():
    cfg = {
        "developer_token": st.secrets["GOOGLE_DEVELOPER_TOKEN"],
        "client_id": st.secrets["GOOGLE_CLIENT_ID"],
        "client_secret": st.secrets["GOOGLE_CLIENT_SECRET"],
        "refresh_token": st.secrets["GOOGLE_REFRESH_TOKEN"],
        "use_proto_plus": True,
    }
    customer_id = str(st.secrets["GOOGLE_CUSTOMER_ID"])
    end_date = datetime.date.today().isoformat()

    client = GoogleAdsClient.load_from_dict(cfg)
    ga = client.get_service("GoogleAdsService")
    data = {}

    camp_q = f"""
        SELECT segments.date, campaign.name, metrics.impressions,
               metrics.clicks, metrics.cost_micros, metrics.conversions
        FROM campaign
        WHERE segments.date BETWEEN '{START_DATE}' AND '{end_date}'
    """
    for batch in ga.search_stream(customer_id=customer_id, query=camp_q):
        for r in batch.results:
            key = (str(r.segments.date), r.campaign.name)
            data[key] = {
                "impressions": int(r.metrics.impressions),
                "clicks": int(r.metrics.clicks),
                "views": 0,
                "cost": r.metrics.cost_micros / 1_000_000,
                "conversions": float(r.metrics.conversions),
            }

    view_q = f"""
        SELECT segments.date, campaign.name, metrics.video_trueview_views
        FROM campaign
        WHERE segments.date BETWEEN '{START_DATE}' AND '{end_date}'
    """
    try:
        for batch in ga.search_stream(customer_id=customer_id, query=view_q):
            for r in batch.results:
                key = (str(r.segments.date), r.campaign.name)
                if key not in data:
                    data[key] = {"impressions": 0, "clicks": 0, "views": 0,
                                 "cost": 0.0, "conversions": 0.0}
                data[key]["views"] += int(r.metrics.video_trueview_views)
    except Exception:
        pass

    rows = [{"date": d, "platform": "google", "campaign": c, **m}
            for (d, c), m in data.items()]
    df = pd.DataFrame(rows)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


df = load_data()
if df.empty:
    st.warning("데이터가 없습니다.")
    st.stop()

# ---- 사이드바 ----
st.sidebar.title("Koras 광고")
page = st.sidebar.radio("페이지", ["📊 대시보드", "📄 원본 데이터"])

platforms = sorted(df["platform"].unique())
sel_plat = st.sidebar.multiselect("플랫폼", platforms, default=platforms)

min_d = df["date"].min().date()
max_d = df["date"].max().date()
date_range = st.sidebar.date_input("기간", value=(min_d, max_d), min_value=min_d, max_value=max_d)

if st.sidebar.button("🔄 데이터 새로고침"):
    st.cache_data.clear()
    st.rerun()

# ---- 필터 ----
f = df[df["platform"].isin(sel_plat)].copy()
if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
    start, end = date_range
else:
    start = end = date_range if not isinstance(date_range, (list, tuple)) else date_range[0]
f = f[(f["date"].dt.date >= start) & (f["date"].dt.date <= end)]

if f.empty:
    st.info("선택한 조건에 데이터가 없습니다.")
    st.stop()

LABELS = {"views": "조회수", "clicks": "클릭수", "conversions": "전환수",
          "impressions": "노출수", "cost": "비용"}
METRIC_ORDER = ["조회수", "클릭수", "전환수", "노출수", "비용"]

if page == "📊 대시보드":
    st.title("📊 Koras 광고 대시보드")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("조회수 (TrueView)", f"{int(f['views'].sum()):,}")
    c2.metric("클릭수", f"{int(f['clicks'].sum()):,}")
    c3.metric("전환수", f"{f['conversions'].sum():,.0f}")
    c4.metric("노출수", f"{int(f['impressions'].sum()):,}")
    impr = int(f["impressions"].sum())
    clk = int(f["clicks"].sum())
    ctr = (clk / impr * 100) if impr else 0
    st.caption(f"비용 {f['cost'].sum():,.0f}원   ·   CTR {ctr:.2f}%   ·   기간 {start} ~ {end}")

    st.divider()
    st.subheader("일별 추이 (통합)")
    chosen = st.multiselect("표시할 지표", METRIC_ORDER,
                            default=["조회수", "클릭수", "전환수", "노출수"])
    if chosen:
        cols = [k for k, v in LABELS.items() if v in chosen]
        daily = f.groupby("date")[cols].sum().reset_index()
        long = daily.melt("date", var_name="m", value_name="값")
        long["지표"] = long["m"].map(LABELS)
        long["상대값"] = long.groupby("m")["값"].transform(
            lambda s: s / s.max() * 100 if s.max() else s * 0
        )
        chart = (
            alt.Chart(long).mark_line(point=True).encode(
                x=alt.X("date:T", title="날짜"),
                y=alt.Y("상대값:Q", title="상대값 (지표별 최대=100)"),
                color=alt.Color("지표:N", sort=METRIC_ORDER, title="지표"),
                tooltip=["date:T", "지표:N", alt.Tooltip("값:Q", title="실제값", format=",.0f")],
            ).properties(height=400)
        )
        st.altair_chart(chart, width="stretch")
        st.caption("※ 지표마다 단위가 달라, 각 지표를 '자기 최대값=100' 기준으로 맞춰 그렸어요. 선 위에 마우스를 올리면 실제 숫자가 나와요.")

    st.divider()
    st.subheader("캠페인별 비교")
    camp_metric = st.selectbox("지표 선택", METRIC_ORDER, index=0)
    col = [k for k, v in LABELS.items() if v == camp_metric][0]
    by_campaign = f.groupby("campaign")[col].sum().sort_values(ascending=True)
    st.bar_chart(by_campaign, horizontal=True)

else:
    st.title("📄 원본 데이터")
    st.caption(f"기간 {start} ~ {end}   ·   총 {len(f)}건")
    show = f.sort_values("date", ascending=False).copy()
    show["date"] = show["date"].dt.date
    st.dataframe(show, width="stretch", hide_index=True)
