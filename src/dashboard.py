"""Streamlit operations dashboard for the Olist AI Operator."""

from __future__ import annotations

import os
import json
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

SRC_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SRC_DIR.parent
sys.path.insert(0, str(SRC_DIR))

from ai_cli import is_fast_question  # noqa: E402
from ai_operator import ask  # noqa: E402
from automation_runner import run_automation_once  # noqa: E402
from create_database import build_database  # noqa: E402
from email_adapter import EmailActionConfig  # noqa: E402
from operator_cli import answer as local_answer  # noqa: E402
from queries import DEFAULT_DATABASE, get_order  # noqa: E402
from delivery_delay_workflow import approve_case, reject_case  # noqa: E402
from operations_case_store import (  # noqa: E402
    all_audit_entries,
    audit_entries,
    list_cases,
    update_customer_message,
)


st.set_page_config(
    page_title="Olist Ops Control Room",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)


def inject_style() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=Space+Grotesk:wght@500;600&display=swap');

        :root { --ink:#f6f7fb; --muted:#93a1b5; --line:rgba(147,161,181,.18); --panel:#121a2a; --panel-2:#172238; --violet:#8b7cf6; --mint:#42d6b3; --amber:#f4b45f; --rose:#f47791; }
        .stApp { background: radial-gradient(circle at 92% 0%, rgba(139,124,246,.13), transparent 28rem), #0a1020; color:var(--ink); font-family:'DM Sans',sans-serif; }
        [data-testid='stHeader'] { background:transparent; }
        [data-testid='stSidebar'] { background:linear-gradient(180deg,#0f1728 0%,#0c1322 100%); border-right:1px solid var(--line); }
        [data-testid='stSidebar'] .block-container { padding:2rem 1.35rem; }
        .block-container { max-width: 1480px; padding-top:2.25rem; padding-bottom:3rem; }
        h1,h2,h3 { font-family:'Space Grotesk',sans-serif !important; letter-spacing:-.035em; color:var(--ink) !important; }
        h1 { font-size:2.65rem !important; line-height:1.05 !important; margin-bottom:.35rem !important; }
        h2 { font-size:1.3rem !important; margin-top:1.6rem !important; }
        p, label, [data-testid='stMarkdownContainer'] { color:var(--muted); }
        .brand { display:flex; align-items:center; gap:.72rem; margin-bottom:2.4rem; }
        .brand-mark { width:2.35rem; height:2.35rem; display:grid; place-items:center; border-radius:.75rem; background:linear-gradient(135deg,#9b8dfd,#5e55d8); color:white; font-family:'Space Grotesk'; font-size:1.2rem; box-shadow:0 10px 28px rgba(106,91,231,.28); }
        .brand-title { font-family:'Space Grotesk'; font-size:1.04rem; color:var(--ink); font-weight:600; line-height:1.1; }
        .brand-sub { color:var(--muted); font-size:.72rem; margin-top:.2rem; letter-spacing:.08em; text-transform:uppercase; }
        .eyebrow { color:var(--mint); font-size:.71rem; letter-spacing:.16em; text-transform:uppercase; font-weight:600; margin-bottom:.75rem; }
        .hero-copy { max-width:700px; color:var(--muted); font-size:1rem; line-height:1.6; }
        .live-pill { display:inline-flex; align-items:center; gap:.45rem; color:#b8c5d8; border:1px solid var(--line); border-radius:999px; padding:.42rem .72rem; font-size:.72rem; letter-spacing:.08em; text-transform:uppercase; background:rgba(18,26,42,.7); }
        .live-dot { width:.42rem; height:.42rem; border-radius:50%; background:var(--mint); box-shadow:0 0 0 .23rem rgba(66,214,179,.12); }
        .kpi-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:1rem; margin:2rem 0 1rem; }
        .kpi { background:linear-gradient(145deg,rgba(24,35,56,.95),rgba(16,25,43,.95)); border:1px solid var(--line); border-radius:1rem; padding:1.15rem 1.2rem 1.25rem; min-height:8.5rem; position:relative; overflow:hidden; }
        .kpi:after { content:''; position:absolute; width:7rem; height:7rem; border-radius:50%; right:-3.8rem; top:-3.8rem; background:var(--kpi-accent); opacity:.16; }
        .kpi-label { color:var(--muted); font-size:.76rem; text-transform:uppercase; letter-spacing:.08em; }
        .kpi-value { color:var(--ink); font-family:'Space Grotesk'; font-size:1.8rem; font-weight:600; margin-top:.7rem; letter-spacing:-.035em; }
        .kpi-note { color:#a9b5c8; font-size:.78rem; margin-top:.35rem; }
        .section-label { color:var(--muted); font-size:.72rem; font-weight:600; letter-spacing:.12em; text-transform:uppercase; margin:1.7rem 0 .7rem; }
        .panel-head { display:flex; align-items:flex-end; justify-content:space-between; gap:1rem; margin-bottom:.8rem; }
        .panel-title { color:var(--ink); font-family:'Space Grotesk'; font-size:1.08rem; font-weight:600; }
        .panel-caption { color:var(--muted); font-size:.8rem; }
        .insight { border-left:3px solid var(--mint); padding:.75rem 1rem; background:rgba(66,214,179,.06); border-radius:0 .7rem .7rem 0; color:#c5d0df; font-size:.88rem; line-height:1.5; margin-top:1rem; }
        .warning { border-left-color:var(--amber); background:rgba(244,180,95,.07); }
        .stTabs [data-baseweb='tab-list'] { gap:.35rem; border-bottom:1px solid var(--line); }
        .stTabs [data-baseweb='tab'] { color:var(--muted); padding:.7rem 1rem; }
        .stTabs [aria-selected='true'] { color:var(--ink) !important; }
        .stButton > button, .stDownloadButton > button { border-radius:.7rem; border:1px solid var(--line); background:#172238; color:var(--ink); }
        .stButton > button:hover, .stDownloadButton > button:hover { border-color:var(--violet); color:white; }
        div[data-testid='stDataFrame'] { border:1px solid var(--line); border-radius:.8rem; overflow:hidden; }
        [data-testid='stMetric'] { background:transparent; }
        .chat-note { color:var(--muted); font-size:.82rem; padding:.6rem 0 1rem; }
        @media (max-width: 900px) { .kpi-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } h1 {font-size:2rem !important;} }
        @media (max-width: 560px) { .kpi-grid { grid-template-columns:1fr; } .kpi-value {font-size:1.55rem;} }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(show_spinner=False)
def load_order_data() -> pd.DataFrame:
    import sqlite3

    connection = sqlite3.connect(DEFAULT_DATABASE)
    try:
        query = """
        SELECT
            o.order_id, o.customer_id, o.order_status,
            o.order_purchase_timestamp, o.order_delivered_customer_date,
            o.order_estimated_delivery_date,
            COALESCE(pay.payment_value, 0) AS revenue,
            c.customer_unique_id, c.customer_city, c.customer_state
        FROM orders AS o
        LEFT JOIN (
            SELECT order_id, SUM(payment_value) AS payment_value
            FROM order_payments GROUP BY order_id
        ) AS pay ON pay.order_id = o.order_id
        LEFT JOIN customers AS c ON c.customer_id = o.customer_id
        """
        frame = pd.read_sql_query(query, connection)
    finally:
        connection.close()

    for column in (
        "order_purchase_timestamp",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ):
        frame[column] = pd.to_datetime(frame[column], errors="coerce")
    frame["days_late"] = (
        frame["order_delivered_customer_date"] - frame["order_estimated_delivery_date"]
    ).dt.total_seconds() / 86400
    frame["is_late"] = frame["days_late"] > 0
    frame["has_delivery_dates"] = frame["order_delivered_customer_date"].notna() & frame[
        "order_estimated_delivery_date"
    ].notna()
    return frame


def ensure_app_database() -> None:
    """Build the generated SQLite database on first deploy if it is absent."""

    if not DEFAULT_DATABASE.exists():
        build_database()


def money(value: float) -> str:
    return f"R${value:,.2f}"


def money_short(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"R${value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"R${value / 1_000:.1f}K"
    return money(value)


def pct(value: float) -> str:
    return f"{value:.1f}%"


def kpi_card(label: str, value: str, note: str, accent: str) -> str:
    return f"<div class='kpi' style='--kpi-accent:{accent}'><div class='kpi-label'>{label}</div><div class='kpi-value'>{value}</div><div class='kpi-note'>{note}</div></div>"


def filtered_frame(frame: pd.DataFrame) -> pd.DataFrame:
    st.sidebar.markdown("<div class='section-label'>View controls</div>", unsafe_allow_html=True)
    min_date = frame["order_purchase_timestamp"].min().date()
    max_date = frame["order_purchase_timestamp"].max().date()
    selected_dates = st.sidebar.date_input("Purchase period", value=(min_date, max_date))
    if isinstance(selected_dates, tuple) and len(selected_dates) == 2:
        start_date, end_date = selected_dates
    else:
        start_date = end_date = selected_dates
    statuses = sorted(frame["order_status"].dropna().unique().tolist())
    selected_statuses = st.sidebar.multiselect("Order status", statuses, default=statuses)
    result = frame[
        (frame["order_purchase_timestamp"].dt.date >= start_date)
        & (frame["order_purchase_timestamp"].dt.date <= end_date)
        & frame["order_status"].isin(selected_statuses)
    ].copy()
    st.sidebar.markdown(
        f"<div class='chat-note'>{len(result):,} orders in current view</div>",
        unsafe_allow_html=True,
    )
    return result


def overview_tab(frame: pd.DataFrame) -> None:
    delivered = frame[(frame["order_status"] == "delivered") & frame["has_delivery_dates"]]
    late = delivered[delivered["is_late"]]
    on_time_rate = 100 - (len(late) / len(delivered) * 100) if len(delivered) else 0
    avg_order = frame["revenue"].sum() / len(frame) if len(frame) else 0
    st.markdown(
        "<div class='kpi-grid'>"
        + kpi_card("Gross payments", money_short(frame["revenue"].sum()), f"{money(frame['revenue'].sum())} total", "#8b7cf6")
        + kpi_card("Orders", f"{len(frame):,}", "Purchase records", "#42d6b3")
        + kpi_card("On-time rate", pct(on_time_rate), "Among dated deliveries", "#f4b45f")
        + kpi_card("Average order", money(avg_order), "Payments ÷ orders", "#f47791")
        + "</div>",
        unsafe_allow_html=True,
    )

    left, right = st.columns([1.45, 1])
    with left:
        st.markdown("<div class='panel-head'><div><div class='panel-title'>Payments over time</div><div class='panel-caption'>Monthly payment value in the selected period</div></div></div>", unsafe_allow_html=True)
        monthly = frame.set_index("order_purchase_timestamp").resample("MS").agg(revenue=("revenue", "sum")).reset_index()
        monthly["month_label"] = monthly["order_purchase_timestamp"].dt.strftime("%b %Y")
        chart = (
            alt.Chart(monthly)
            .mark_bar(color="#8b7cf6", cornerRadiusTopLeft=5, cornerRadiusTopRight=5)
            .encode(
                x=alt.X("order_purchase_timestamp:T", title=None, axis=alt.Axis(format="%b %Y", labelColor="#93a1b5", titleColor="#93a1b5", tickCount=6, grid=False)),
                y=alt.Y("revenue:Q", title="R$", axis=alt.Axis(labelColor="#93a1b5", titleColor="#93a1b5", format="~s", gridColor="#243149")),
                tooltip=[alt.Tooltip("month_label:N", title="Month"), alt.Tooltip("revenue:Q", title="Payments", format=",.2f")],
            )
            .properties(height=290)
        )
        st.altair_chart(chart, use_container_width=True)
    with right:
        st.markdown("<div class='panel-head'><div><div class='panel-title'>Order status</div><div class='panel-caption'>Distribution in current view</div></div></div>", unsafe_allow_html=True)
        status = frame["order_status"].value_counts().rename_axis("status").reset_index(name="orders")
        chart = (
            alt.Chart(status)
            .mark_bar(cornerRadiusEnd=5)
            .encode(
                x=alt.X("orders:Q", title="Orders", axis=alt.Axis(labelColor="#93a1b5", titleColor="#93a1b5", gridColor="#243149")),
                y=alt.Y("status:N", sort="-x", title=None, axis=alt.Axis(labelColor="#c8d2e2", titleColor="#93a1b5")),
                color=alt.Color("status:N", scale=alt.Scale(range=["#42d6b3", "#8b7cf6", "#f4b45f", "#f47791", "#6e86a8"]), legend=None),
                tooltip=["status:N", "orders:Q"],
            )
            .properties(height=290)
        )
        st.altair_chart(chart, use_container_width=True)
    if len(late):
        st.markdown(
            f"<div class='insight warning'><strong>Operational signal.</strong> {len(late):,} delivered orders in the current view were late, with an average delay of {late['days_late'].mean():.1f} days.</div>",
            unsafe_allow_html=True,
        )


def delivery_tab(frame: pd.DataFrame) -> None:
    delivered = frame[(frame["order_status"] == "delivered") & frame["has_delivery_dates"]]
    late = delivered[delivered["is_late"]].sort_values("days_late", ascending=False)
    late_rate = len(late) / len(delivered) * 100 if len(delivered) else 0
    st.markdown(
        "<div class='kpi-grid'>"
        + kpi_card("Delivered", f"{len(delivered):,}", "With both delivery dates", "#42d6b3")
        + kpi_card("Late orders", f"{len(late):,}", f"{late_rate:.1f}% of delivered", "#f47791")
        + kpi_card("Average delay", f"{late['days_late'].mean():.1f} d" if len(late) else "—", "Late orders only", "#f4b45f")
        + kpi_card("Worst case", f"{late['days_late'].max():.1f} d" if len(late) else "—", "Maximum delay", "#8b7cf6")
        + "</div>",
        unsafe_allow_html=True,
    )
    st.markdown("<div class='panel-head'><div><div class='panel-title'>Critical delivery queue</div><div class='panel-caption'>Sorted by days late, most critical first</div></div></div>", unsafe_allow_html=True)
    display = late[["order_id", "order_status", "order_estimated_delivery_date", "order_delivered_customer_date", "days_late", "customer_city", "customer_state"]].head(100).copy()
    display.columns = ["Order ID", "Status", "Estimated", "Delivered", "Days late", "City", "State"]
    for column in ("Estimated", "Delivered"):
        display[column] = display[column].dt.strftime("%d %b %Y")
    st.dataframe(display, use_container_width=True, hide_index=True, height=430)
    csv_data = display.to_csv(index=False).encode("utf-8")
    st.download_button("Download current delay queue", csv_data, "delivery_delays_current_view.csv", "text/csv")


def order_tab() -> None:
    st.markdown("<div class='panel-head'><div><div class='panel-title'>Order investigation</div><div class='panel-caption'>Look up the full operational context of one order</div></div></div>", unsafe_allow_html=True)
    order_id = st.text_input("Order ID", placeholder="32-character order ID")
    if not order_id:
        st.markdown("<div class='insight'>Paste an order ID to see status, delivery dates, items, payments and reviews.</div>", unsafe_allow_html=True)
        return
    result = get_order(order_id.strip())
    if not result:
        st.error("Order not found. Check the ID and try again.")
        return
    order = result["order"]
    st.markdown(
        f"<div class='kpi-grid'>"
        + kpi_card("Status", str(order["order_status"]).title(), "Current order state", "#42d6b3")
        + kpi_card("Items", str(len(result["items"])), "Line items", "#8b7cf6")
        + kpi_card("Payments", str(len(result["payments"])), "Payment records", "#f4b45f")
        + kpi_card("Reviews", str(len(result["reviews"])), "Review records", "#f47791")
        + "</div>",
        unsafe_allow_html=True,
    )
    details = pd.DataFrame([{
        "Purchase": order["order_purchase_timestamp"],
        "Estimated delivery": order["order_estimated_delivery_date"],
        "Actual delivery": order["order_delivered_customer_date"] or "Not available",
        "Customer city": order["customer_city"],
        "Customer state": order["customer_state"],
    }])
    st.dataframe(details, use_container_width=True, hide_index=True)
    with st.expander("Items and payments"):
        st.dataframe(pd.DataFrame(result["items"]), use_container_width=True, hide_index=True)
        st.dataframe(pd.DataFrame(result["payments"]), use_container_width=True, hide_index=True)
    with st.expander("Reviews"):
        st.dataframe(pd.DataFrame(result["reviews"]), use_container_width=True, hide_index=True)


def _safe_json(value: str | None) -> object:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


def _case_queue_frame(cases: list[dict]) -> pd.DataFrame:
    rows = [
        {
            "Case ID": case["case_id"],
            "Order": case["order_id"],
            "Issue type": case["case_type"],
            "Severity": (case.get("severity") or "—").upper(),
            "Confidence": f"{case['confidence']:.0%}" if case.get("confidence") is not None else "—",
            "Recommended action": case.get("recommended_action") or "—",
            "Status": case["status"],
            "Updated": case.get("updated_at", ""),
        }
        for case in cases
    ]
    return pd.DataFrame(rows)


def _policy_for_case(case_id: str) -> dict | None:
    for entry in audit_entries(case_id):
        if entry["event_type"] == "automation_policy_decision":
            value = _safe_json(entry.get("output_json"))
            return value if isinstance(value, dict) else None
    return None


def _demo_email_config() -> EmailActionConfig:
    """The public UI is always safe even if a developer has live env vars."""

    return EmailActionConfig(
        mode="simulation",
        external_actions_enabled=False,
        # RFC 2606 .invalid address: visible in the audit, never deliverable,
        # and used only so the public demo can close a simulated contact case.
        recipient=os.getenv("AI_OPERATOR_EMAIL_RECIPIENT") or "demo-recipient@example.invalid",
    )


def _render_case_detail(case: dict) -> None:
    case_id = case["case_id"]
    st.markdown(
        f"<div class='panel-head'><div><div class='panel-title'>{case_id}</div>"
        f"<div class='panel-caption'>{case['case_type']} · order {case['order_id']}</div></div>"
        f"<span class='live-pill'>{case['status']}</span></div>",
        unsafe_allow_html=True,
    )
    left, right = st.columns([1.05, 1.3])
    with left:
        order_result = get_order(case["order_id"])
        if order_result:
            order = order_result["order"]
            st.markdown("**Order information**")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Order ID": order["order_id"],
                            "Status": order["order_status"],
                            "Purchased": order["order_purchase_timestamp"],
                            "Estimated delivery": order["order_estimated_delivery_date"],
                            "Delivered": order["order_delivered_customer_date"] or "—",
                            "Customer city": order["customer_city"],
                            "Customer state": order["customer_state"],
                        }
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
        st.markdown("**Decision**")
        decision = pd.DataFrame(
            [
                {
                    "Severity": (case.get("severity") or "—").upper(),
                    "Confidence": f"{case['confidence']:.0%}" if case.get("confidence") is not None else "—",
                    "Recommended action": case.get("recommended_action") or "—",
                    "Current status": case["status"],
                }
            ]
        )
        st.dataframe(decision, use_container_width=True, hide_index=True)
    with right:
        evidence = case.get("evidence") or {}
        facts = evidence.get("facts") if isinstance(evidence, dict) else evidence
        selected = evidence.get("selected_evidence", []) if isinstance(evidence, dict) else []
        st.markdown("**Verified facts**")
        st.json(facts or {})
        st.markdown("**Evidence used by AI**")
        if selected:
            for item in selected:
                st.markdown(f"- {item}")
        else:
            st.caption("No evidence recorded.")

    st.markdown("**Rationale**")
    st.info(case.get("rationale") or "No rationale recorded.")
    if case.get("customer_message"):
        st.markdown("**Customer message**")
        st.markdown(f"> {case['customer_message']}")
    policy = _policy_for_case(case_id)
    if policy:
        st.markdown("**Automation policy decision**")
        st.json(policy)

    if case["status"] == "PENDING_HUMAN_APPROVAL":
        st.markdown("**Human approval**")
        if case.get("customer_message") is not None:
            message = st.text_area(
                "Edit customer message before approval",
                value=case.get("customer_message") or "",
                key=f"message_{case_id}",
                height=120,
            )
            edit_col, approve_col, reject_col = st.columns([1.2, 1, 1])
            with edit_col:
                if st.button("Save message", key=f"save_message_{case_id}"):
                    try:
                        update_customer_message(case_id, message)
                        st.success("Message updated.")
                        st.rerun()
                    except Exception as error:
                        st.error(str(error))
            with approve_col:
                if st.button("Approve", key=f"approve_detail_{case_id}", type="primary"):
                    try:
                        approve_case(case_id, email_config=_demo_email_config())
                        st.success("Approved action simulated and case closed.")
                        st.rerun()
                    except Exception as error:
                        st.error(str(error))
            with reject_col:
                if st.button("Reject", key=f"reject_detail_{case_id}"):
                    try:
                        reject_case(case_id)
                        st.success("Case rejected and closed without external action.")
                        st.rerun()
                    except Exception as error:
                        st.error(str(error))

    st.markdown("**Audit trail**")
    audit = audit_entries(case_id)
    audit_frame = pd.DataFrame(
        [
            {
                "Timestamp": entry["timestamp"],
                "Actor": entry["actor"],
                "Event": entry["event_type"],
                "From": entry["from_status"] or "",
                "To": entry["to_status"] or "",
                "Success": bool(entry["success"]),
                "Error": entry["error"] or "",
            }
            for entry in audit
        ]
    )
    st.dataframe(audit_frame, use_container_width=True, hide_index=True)


def control_center_tab(data: pd.DataFrame) -> None:
    cases = [case for case in list_cases() if case]
    statuses = pd.Series([case["status"] for case in cases]) if cases else pd.Series(dtype=str)
    delayed = data[(data["order_status"] == "delivered") & data["has_delivery_dates"] & data["is_late"]]
    auto_resolved = sum(
        any(entry["event_type"] == "automation_policy_auto_approved" for entry in audit_entries(case["case_id"]))
        for case in cases
        if case["status"] == "CLOSED"
    )
    ai_processed = sum(case["status"] != "OPEN" for case in cases)
    kpis = [
        ("Orders scanned", f"{len(data):,}", "Current Olist snapshot", "#8b7cf6"),
        ("Issues detected", f"{len(delayed):,}", "Deterministic delivery rule", "#f47791"),
        ("Cases OPEN", str(int((statuses == "OPEN").sum())), "Awaiting AI processing", "#f4b45f"),
        ("AI processed", str(ai_processed), "Investigated or failed", "#42d6b3"),
        ("Auto-resolved", str(auto_resolved), "Policy-approved simulated actions", "#8b7cf6"),
        ("Human approval", str(int((statuses == "PENDING_HUMAN_APPROVAL").sum())), "Waiting for reviewer", "#f4b45f"),
        ("FAILED", str(int((statuses == "FAILED").sum())), "Requires attention", "#f47791"),
    ]
    st.markdown("<div class='kpi-grid'>" + "".join(kpi_card(*item) for item in kpis) + "</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='insight warning'><strong>DEMO SAFE MODE.</strong> External actions are simulated and the UI never enables live SMTP. Gemini processing is opt-in per run; a missing key, quota error or invalid output is shown as FAILED and recorded in the audit.</div>",
        unsafe_allow_html=True,
    )

    if st.session_state.get("last_runner_result") is not None:
        st.markdown("**Last runner result**")
        st.json(st.session_state["last_runner_result"])

    with st.expander("Run bounded Operator cycle", expanded=False):
        st.caption("Detection is deterministic. Gemini is disabled unless you explicitly enable it for this run.")
        run_col1, run_col2, run_col3, run_col4 = st.columns(4)
        with run_col1:
            max_orders = st.number_input("Orders", min_value=1, max_value=100, value=5)
        with run_col2:
            max_created = st.number_input("Cases created", min_value=1, max_value=100, value=5)
        with run_col3:
            max_processed = st.number_input("Cases processed", min_value=1, max_value=100, value=2)
        with run_col4:
            max_calls = st.number_input("Gemini calls", min_value=1, max_value=100, value=4)
        allow_gemini = st.checkbox("Allow Gemini calls for this run", value=False)
        if st.button("Run Operator once", type="primary"):
            if allow_gemini and not os.getenv("GEMINI_API_KEY"):
                st.error("GEMINI_API_KEY is not configured. No Gemini call was made.")
            else:
                try:
                    with st.spinner("Running bounded Operator cycle…"):
                        result = run_automation_once(
                            max_orders_scanned=int(max_orders),
                            max_cases_created=int(max_created),
                            max_cases_processed=int(max_processed),
                            max_gemini_calls=int(max_calls),
                            enable_gemini=allow_gemini,
                        )
                    st.session_state["last_runner_result"] = result
                    st.rerun()
                except Exception as error:
                    st.session_state["last_runner_result"] = {
                        "mode": "runner_error",
                        "error_type": type(error).__name__,
                        "error": str(error),
                    }
                    st.rerun()

    st.markdown("<div class='panel-head'><div><div class='panel-title'>Operations Queue</div><div class='panel-caption'>One queue for detection, investigation, policy and human review</div></div></div>", unsafe_allow_html=True)
    if not cases:
        st.info("No Operations Cases yet. Run the safe scan above to create new DELIVERY_DELAY cases.")
    else:
        st.dataframe(_case_queue_frame(cases), use_container_width=True, hide_index=True, height=360)
        case_labels = {case["case_id"]: f"{case['case_id']} · {case['status']}" for case in cases}
        selected_case_id = st.selectbox(
            "Open case",
            [case["case_id"] for case in cases],
            format_func=lambda value: case_labels[value],
        )
        selected_case = next(case for case in cases if case["case_id"] == selected_case_id)
        _render_case_detail(selected_case)

    st.markdown("<div class='panel-head'><div><div class='panel-title'>Activity Feed</div><div class='panel-caption'>Append-only Operator activity across cases</div></div></div>", unsafe_allow_html=True)
    feed = all_audit_entries(limit=80)
    if feed:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Timestamp": entry["timestamp"],
                        "Case": entry["case_id"],
                        "Actor": entry["actor"],
                        "Activity": entry["event_type"],
                        "Status": f"{entry['from_status'] or ''} → {entry['to_status'] or ''}".strip(" →"),
                        "Result": "OK" if entry["success"] else (entry["error"] or "FAILED"),
                    }
                    for entry in feed
                ]
            ),
            use_container_width=True,
            hide_index=True,
            height=360,
        )
    else:
        st.info("No activity recorded yet.")


def copilot_tab() -> None:
    copilot_status = "Gemini connected" if os.environ.get("GEMINI_API_KEY") else "Local tools ready"
    st.markdown(f"<div class='panel-head'><div><div class='panel-title'>Ask the operations copilot</div><div class='panel-caption'>Gemini can reason over the approved Olist tools</div></div><span class='live-pill'><span class='live-dot'></span>{copilot_status}</span></div>", unsafe_allow_html=True)
    st.markdown("<div class='chat-note'>Try: <em>Quali sono le cause operative più urgenti?</em> or <em>Analizza l'ordine 1b3190b2dfa9d789e1f14c05b647a14a</em></div>", unsafe_allow_html=True)
    if "dashboard_messages" not in st.session_state:
        st.session_state.dashboard_messages = []
    for message in st.session_state.dashboard_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    question = st.chat_input("Ask about orders, payments or delivery risk…")
    if question:
        st.session_state.dashboard_messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            with st.spinner("Analysing the operation…"):
                try:
                    response = local_answer(question) if is_fast_question(question) else ask(question)
                except Exception as error:
                    response = f"Non riesco a completare l'analisi: {error}"
            st.markdown(response)
        st.session_state.dashboard_messages.append({"role": "assistant", "content": response})

def main() -> None:
    inject_style()
    ensure_app_database()
    data = load_order_data()
    st.sidebar.markdown("<div class='brand'><div class='brand-mark'>◈</div><div><div class='brand-title'>Olist Ops</div><div class='brand-sub'>Control room</div></div></div>", unsafe_allow_html=True)
    st.sidebar.caption("Local SQLite intelligence layer")
    filtered = filtered_frame(data)

    st.markdown("<div class='eyebrow'>AI Operations Automation · Olist Brazil</div>", unsafe_allow_html=True)
    st.markdown("# AI Operations Control Center")
    st.markdown("<div class='hero-copy'>The Operator detects delivery issues, investigates approved facts, applies deterministic guardrails and policy, then routes every action to simulation or human approval.</div>", unsafe_allow_html=True)
    st.markdown("<br><span class='live-pill'><span class='live-dot'></span>Demo safe mode · local SQLite · refreshed on reload</span>", unsafe_allow_html=True)

    control, overview, delivery, order, copilot = st.tabs(["Control Center", "BI overview", "Delivery risk", "Order lookup", "AI copilot"])
    with control:
        control_center_tab(data)
    with overview:
        overview_tab(filtered)
    with delivery:
        delivery_tab(filtered)
    with order:
        order_tab()
    with copilot:
        copilot_tab()


if __name__ == "__main__":
    main()
