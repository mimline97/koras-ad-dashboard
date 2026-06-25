import datetime
from datetime import timedelta
import pandas as pd
import altair as alt
import streamlit as st

st.set_page_config(page_title="Koras 광고 대시보드", layout="wide")

# ---- 여백 줄이기 + 통합 숫자 볼드 ----
st.markdown("""
<style>
.block-container {padding-top: 2.2rem; padding-bottom: 2rem;}
[data-testid="stMetricValue"] {font-weight: 700;}
hr {margin: 0.7rem 0;}
</style>
""", unsafe_allow_html=True)

START_DATE = st.secrets.get("GOOGLE_START_DATE", "2026-04-01")
TODAY = datetime.date.today().isoformat()


# ========================================================
#  데이터 불러오기
# ========================================================
@st.cache_data(ttl=3600)
def load_google():
    from google.ads.googleads.client import GoogleAdsClient
    cfg = {
        "developer_token": st.secrets["GOOGLE_DEVELOPER_TOKEN"],
        "client_id": st.secrets["GOOGLE_CLIENT_ID"],
        "client_secret": st.secrets["GOOGLE_CLIENT_SECRET"],
        "refresh_token": st.secrets["GOOGLE_REFRESH_TOKEN"],
        "use_proto_plus": True,
    }
    customer_id = str(st.secrets["GOOGLE_CUSTOMER_ID"])
    client = GoogleAdsClient.load_from_dict(cfg)
    ga = client.get_service("GoogleAdsService")
    data = {}

    camp_q = f"""
        SELECT segments.date, campaign.name, metrics.impressions,
               metrics.clicks, metrics.cost_micros, metrics.conversions
        FROM campaign
        WHERE segments.date BETWEEN '{START_DATE}' AND '{TODAY}'
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
        WHERE segments.date BETWEEN '{START_DATE}' AND '{TODAY}'
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
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600)
def load_meta():
    token = st.secrets.get("META_ACCESS_TOKEN")
    acct = st.secrets.get("META_AD_ACCOUNT_ID")
    if not token or not acct:
        return pd.DataFrame()
    try:
        from facebook_business.api import FacebookAdsApi
        from facebook_business.adobjects.adaccount import AdAccount
        FacebookAdsApi.init(access_token=token)
        account = AdAccount(f"act_{acct}")
        params = {
            "level": "adset",      # 광고세트 단위
            "time_range": {"since": START_DATE, "until": TODAY},
            "time_increment": 1,
        }
        fields = ["campaign_name", "adset_name", "impressions", "clicks",
                  "spend", "reach", "actions", "date_start"]
        rows = []
        for row in account.get_insights(fields=fields, params=params):
            link_click = 0
            for a in (row.get("actions") or []):
                if a.get("action_type") == "link_click":
                    link_click = int(float(a.get("value", 0)))
                    break
            rows.append({
                "date": str(row.get("date_start")),
                "platform": "meta",
                # campaign 칸에 '광고세트명' (구글=캠페인 / 메타=광고세트)
                "campaign": row.get("adset_name") or row.get("campaign_name"),
                "impressions": int(row.get("impressions", 0) or 0),
                "clicks": int(row.get("clicks", 0) or 0),
                "views": int(row.get("reach", 0) or 0),
                "cost": float(row.get("spend", 0) or 0),
                "conversions": float(link_click),
            })
        return pd.DataFrame(rows)
    except Exception as e:
        st.warning(f"메타 데이터를 불러오지 못했어요: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def load_data():
    g = load_google()
    m = load_meta()
    df = pd.concat([g, m], ignore_index=True)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


df = load_data()
if df.empty:
    st.warning("데이터가 없습니다.")
    st.stop()

min_d = df["date"].min().date()
max_d = df["date"].max().date()

# ========================================================
#  사이드바
# ========================================================
st.sidebar.title("Koras 광고")
default_start = max_d.replace(day=1)
if default_start < min_d:
    default_start = min_d
date_range = st.sidebar.date_input("기간", value=(default_start, max_d),
                                   min_value=min_d, max_value=max_d)
if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
    start, end = date_range
else:
    start = end = date_range if not isinstance(date_range, (list, tuple)) else date_range[0]

if st.sidebar.button("🔄 데이터 새로고침"):
    st.cache_data.clear()
    st.rerun()
st.sidebar.caption("전월 대비 = 선택 기간 vs 직전 같은 길이 기간")

period_len = (end - start).days + 1
prev_end = start - timedelta(days=1)
prev_start = prev_end - timedelta(days=period_len - 1)

f = df[(df["date"].dt.date >= start) & (df["date"].dt.date <= end)].copy()
f_prev = df[(df["date"].dt.date >= prev_start) & (df["date"].dt.date <= prev_end)].copy()


def agg(d):
    return {
        "views": int(d["views"].sum()),
        "clicks": int(d["clicks"].sum()),
        "conversions": int(round(d["conversions"].sum())),
        "impressions": int(d["impressions"].sum()),
        "cost": float(d["cost"].sum()),
    }


def delta_str(cur, prev):
    if prev and prev != 0:
        return f"{(cur - prev) / prev * 100:+.1f}%"
    return None


cur = agg(f)
prev = agg(f_prev)

# ========================================================
#  통합 (크게)
# ========================================================
st.markdown("### 📊 통합 (구글 + 메타)")
st.caption(f"기간 {start} ~ {end}")

c1, c2, c3, c4 = st.columns(4)
c1.metric("조회·도달", f"{cur['views']:,}", delta_str(cur["views"], prev["views"]))
c2.metric("클릭수", f"{cur['clicks']:,}", delta_str(cur["clicks"], prev["clicks"]))
c3.metric("전환수", f"{cur['conversions']:,}", delta_str(cur["conversions"], prev["conversions"]))
c4.metric("노출수", f"{cur['impressions']:,}", delta_str(cur["impressions"], prev["impressions"]))

t_ctr = (cur["clicks"] / cur["impressions"] * 100) if cur["impressions"] else 0
t_cpc = (cur["cost"] / cur["clicks"]) if cur["clicks"] else 0
st.caption(f"비용 {cur['cost']:,.0f}원   ·   CTR {t_ctr:.2f}%   ·   CPC {t_cpc:,.0f}원")
st.caption("※ '조회·도달'은 구글 조회수 + 메타 도달의 합이에요(성격이 다른 값이라 참고용).")

st.divider()

# ========================================================
#  플랫폼별 상세 표 (구글 / 메타 / 총계)  — 총계 볼드
# ========================================================
st.markdown("#### 플랫폼별 상세")


def cells(d):
    a = agg(d)
    ctr = (a["clicks"] / a["impressions"] * 100) if a["impressions"] else 0
    cpc = (a["cost"] / a["clicks"]) if a["clicks"] else 0
    return [f"{a['views']:,}", f"{a['clicks']:,}", f"{a['conversions']:,}",
            f"{a['impressions']:,}", f"{a['cost']:,.0f}원", f"{ctr:.2f}%", f"{cpc:,.0f}원"]


headers = ["구분", "조회·도달", "클릭", "전환", "노출", "비용", "CTR", "CPC"]
body = [
    ("구글", cells(f[f["platform"] == "google"]), False),
    ("메타", cells(f[f["platform"] == "meta"]), False),
    ("총계", cells(f), True),
]

bd = "border-bottom:0.5px solid rgba(128,128,128,0.25);"
html = "<table style='width:100%; border-collapse:collapse; font-size:14px; color:inherit;'>"
html += "<thead><tr style='color:rgba(128,128,128,0.95); text-align:right;'>"
for i, h in enumerate(headers):
    align = "left" if i == 0 else "right"
    html += f"<th style='padding:8px 10px; text-align:{align}; font-weight:500; {bd}'>{h}</th>"
html += "</tr></thead><tbody>"
for name, vals, is_total in body:
    weight = "700" if is_total else "400"
    top = "border-top:1.5px solid rgba(128,128,128,0.45);" if is_total else ""
    html += f"<tr style='{top}'>"
    html += f"<td style='padding:9px 10px; text-align:left; font-weight:{weight}; {bd}'>{name}</td>"
    for v in vals:
        html += f"<td style='padding:9px 10px; text-align:right; font-weight:{weight}; {bd}'>{v}</td>"
    html += "</tr>"
html += "</tbody></table>"
st.markdown(html, unsafe_allow_html=True)

st.divider()

# ========================================================
#  그래프 (일별 추이 / 세로 막대)
# ========================================================
st.markdown("#### 그래프")

LABELS = {"views": "조회·도달", "clicks": "클릭수", "conversions": "전환수",
          "impressions": "노출수"}

plat_pick = st.radio("플랫폼", ["전체", "구글", "메타"], horizontal=True)
if plat_pick == "구글":
    g = f[f["platform"] == "google"]
    unit_label = "캠페인별"
elif plat_pick == "메타":
    g = f[f["platform"] == "meta"]
    unit_label = "광고세트별"
else:
    g = f
    unit_label = "캠페인/광고세트별"

if g.empty:
    st.info("선택한 조건에 데이터가 없어요.")
else:
    st.markdown("**일별 추이**")
    metric_keys = ["views", "clicks", "conversions", "impressions"]
    metric_labels = [LABELS[k] for k in metric_keys]
    chosen = st.multiselect("표시할 지표", metric_labels, default=metric_labels)
    if chosen:
        cols = [k for k in metric_keys if LABELS[k] in chosen]
        daily = g.groupby("date")[cols].sum().reset_index()
        long = daily.melt("date", var_name="m", value_name="값")
        long["지표"] = long["m"].map(LABELS)
        long["상대값"] = long.groupby("m")["값"].transform(
            lambda s: s / s.max() * 100 if s.max() else s * 0)
        line = (
            alt.Chart(long).mark_line(point=True).encode(
                x=alt.X("date:T", title="날짜"),
                y=alt.Y("상대값:Q", title="상대값 (지표별 최대=100)"),
                color=alt.Color("지표:N", title="지표"),
                tooltip=["date:T", "지표:N", alt.Tooltip("값:Q", title="실제값", format=",.0f")],
            ).properties(height=380)
        )
        st.altair_chart(line, width="stretch")
        st.caption("※ 지표마다 단위가 달라, 각 지표를 '자기 최대값=100' 기준으로 맞춰 그렸어요. 선에 마우스를 올리면 실제 숫자가 나와요.")

    st.markdown(f"**{unit_label} 비교**")
    bar_label = st.selectbox("지표 선택", metric_labels, index=0)
    bcol = [k for k in metric_keys if LABELS[k] == bar_label][0]
    bar_df = g.groupby("campaign")[bcol].sum().reset_index().sort_values(bcol, ascending=False)
    bars = (
        alt.Chart(bar_df).mark_bar().encode(
            x=alt.X("campaign:N", sort="-y", title=None, axis=alt.Axis(labelAngle=-40)),
            y=alt.Y(f"{bcol}:Q", title=bar_label),
            tooltip=[alt.Tooltip("campaign:N", title="이름"),
                     alt.Tooltip(f"{bcol}:Q", title=bar_label, format=",.0f")],
        ).properties(height=400)
    )
    st.altair_chart(bars, width="stretch")
