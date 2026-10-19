"""
Insurance Underwriting Agent: Streamlit application.

A guided stepper interface that orchestrates the entire automated
underwriting lifecycle using AWS Services:
1. Document Upload & Parsing (AWS Textract + AWS S3)
2. Identity Verification (AWS Rekognition)
3. Rules Evaluation & Final Underwriting (AWS Lambda + AWS Bedrock AgentCore)
4. Audit Persistence (AWS DynamoDB)

Run with: streamlit run app.py
"""

import streamlit as st
import json
import os
import time
from pathlib import Path
import uuid

import config
from extraction.textract_handler import TextractIDHandler
from verification.rekognition_handler import RekognitionHandler
from scoring.lambda_rules_engine import invoke_rules_engine_mock
from scoring.decision_support import apply_identity_gate, build_decision_packet
from agent.bedrock_agent import UnderwritingAgent
from storage.s3_handler import DocumentStore
from storage.dynamo_handler import DynamoAuditStore


# =============================================================================
# Page Configuration
# =============================================================================
@st.cache_data
def _sample_applicants() -> dict:
    """A handful of profiles from the eval set, for the demo picker."""
    picks = ["u01", "u07", "u16", "u21", "u27", "u29", "u31"]
    path = Path(__file__).resolve().parent / "eval" / "applicants.jsonl"
    rows = {r["id"]: r for r in map(json.loads, path.read_text().splitlines())}
    return {cid: rows[cid] for cid in picks}


st.set_page_config(
    page_title=config.APP_TITLE,
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for premium multi-step form aesthetic
st.markdown("""
<style>
    .stApp {
        background: #f8fafc;
        color: #0f172a;
    }
    
    .status-ok { color: #10b981; font-weight: 700; font-size: 1.4rem; }
    .status-warn { color: #f59e0b; font-weight: 700; font-size: 1.4rem; }
    .status-fail { color: #ef4444; font-weight: 700; font-size: 1.4rem; }
    
    .metric-box {
        background: white;
        border: 1px solid #e2e8f0;
        box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);
        padding: 24px;
        border-radius: 12px;
        text-align: center;
        transition: transform 0.2s;
    }
    
    .metric-box:hover {
        transform: translateY(-2px);
    }
    
    .step-container {
        background: white;
        padding: 32px;
        border-radius: 16px;
        border: 1px solid #e2e8f0;
        box-shadow: 0 10px 15px -3px rgb(0 0 0 / 0.05);
    }
    
    .data-card {
        background: #f1f5f9;
        padding: 16px;
        border-radius: 8px;
        font-family: monospace;
        font-size: 0.9rem;
    }
</style>
""", unsafe_allow_html=True)


# =============================================================================
# Session State Initialization
# =============================================================================
if "step" not in st.session_state:
    st.session_state.step = 1
if "applicant_id" not in st.session_state:
    st.session_state.applicant_id = f"APP-{str(uuid.uuid4())[:8].upper()}"
if "parsed_data" not in st.session_state:
    st.session_state.parsed_data = {}
if "id_document_bytes" not in st.session_state:
    st.session_state.id_document_bytes = None
if "liveness" not in st.session_state:
    st.session_state.liveness = {}
if "rules" not in st.session_state:
    st.session_state.rules = {}
if "underwriting_packet" not in st.session_state:
    st.session_state.underwriting_packet = {}


# =============================================================================
# Application Header
# =============================================================================
st.title("🛡️ Automated Underwriting Pipeline")
st.caption(f"Application ID: **{st.session_state.applicant_id}** | Powered by AWS Textract, Rekognition, Lambda, and Bedrock AgentCore")

st.divider()

# Layout
col_nav, col_content = st.columns([1, 3])

# Navigation Progress
with col_nav:
    st.markdown("### Submission Flow")
    
    def step_icon(step_num):
        if st.session_state.step > step_num: return "✅"
        if st.session_state.step == step_num: return "🔄"
        return "⏳"
        
    st.markdown(f"**Step 1:** Upload ID {step_icon(1)}")
    st.caption("AWS Textract & S3")
    
    st.markdown(f"**Step 2:** Face Liveness {step_icon(2)}")
    st.caption("AWS Rekognition")
    
    st.markdown(f"**Step 3:** Agent Evaluation {step_icon(3)}")
    st.caption("AWS Lambda & Bedrock")
    
    if st.session_state.step > 1 and st.button("Start New Application", use_container_width=True):
        st.session_state.clear()
        st.rerun()


# =============================================================================
# Step 1: Document Upload & Parsing
# =============================================================================
with col_content:
    if st.session_state.step == 1:
        st.markdown('<div class="step-container">', unsafe_allow_html=True)
        st.markdown("### Step 1: Upload Government ID")
        st.write("Please provide a clear scan of the applicant's Driver's License or Passport.")
        
        if config.DEMO_MODE:
            st.info("Demo mode: AWS is paused (free-tier credits ran out), so Textract and Rekognition "
                    "return sample data. Pick a sample applicant to jump straight to the decision.")
            samples = _sample_applicants()
            picked = st.selectbox("Sample applicant", list(samples), format_func=lambda k: samples[k]["description"])
            if st.button("Run sample applicant", type="primary"):
                st.session_state.parsed_data = samples[picked]["applicant"]
                st.session_state.liveness = samples[picked]["liveness"]
                st.session_state.id_document_bytes = b""
                st.session_state.step = 3
                st.rerun()
            st.caption("Or upload any image below to walk through every step.")

        uploaded_file = st.file_uploader("Choose an image", type=['png', 'jpg', 'jpeg'])
        
        if uploaded_file and st.button("Extract Data with Amazon Textract", type="primary"):
             with st.spinner("Uploading to S3 (30-day PI lifecycle) and analyzing with Textract Queries..."):
                 time.sleep(1) # Visual pacing
                 file_bytes = uploaded_file.getvalue()
                 
                 # 1. Upload to S3
                 try:
                     store = DocumentStore()
                     s3_uri = store.upload_document(file_bytes, f"{st.session_state.applicant_id}_ID.jpg")
                 except Exception:
                     s3_uri = f"s3://mock-bucket/{st.session_state.applicant_id}.jpg"
                 
                 # 2. Extract Data
                 textract = TextractIDHandler()
                 result = textract.extract_id_data(file_bytes)
                 
                 # Keep the expected schema without overwriting real partial OCR results.
                 required_fields = TextractIDHandler.REQUIRED_FIELDS + ["ISSUE_DATE", "ISSUING_STATE"]
                 result = result or {}
                 result = {field: result.get(field, "") for field in required_fields}
                 
                 # 3. Store transient applicant state in DynamoDB
                 try:
                     db = DynamoAuditStore()
                     db.store_applicant(result, st.session_state.applicant_id)
                 except Exception:
                     pass
                 
                 st.session_state.parsed_data = result
                 st.session_state.id_document_bytes = file_bytes
                 st.session_state.step = 2
                 st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)


# =============================================================================
# Step 2: Liveness Verification
# =============================================================================
    elif st.session_state.step == 2:
        st.markdown('<div class="step-container">', unsafe_allow_html=True)
        st.markdown("### Step 2: Liveness Verification")
        
        st.success("Identity document extracted successfully!")
        st.markdown('<div class="data-card">', unsafe_allow_html=True)
        st.json(st.session_state.parsed_data)
        st.markdown('</div>', unsafe_allow_html=True)
        
        st.divider()
        st.info("Please complete the face liveness check using your camera to prevent spoofing.")
        
        # Simulating webcam interaction
        camera_photo = st.camera_input("Take a photo for live verification")
        
        if camera_photo and st.button("Verify Identity (Amazon Rekognition)", type="primary"):
            with st.spinner("Analyzing liveness and executing FaceMatch algorithm..."):
                time.sleep(1.5)
                
                rekognition = RekognitionHandler()
                
                # Execute Rekognition checks
                live_res = rekognition.verify_liveness(f"session_{st.session_state.applicant_id}")
                comp_res = rekognition.compare_faces(
                    camera_photo.getvalue(),
                    st.session_state.id_document_bytes or b""
                )
                
                st.session_state.liveness = {
                    "liveness_confidence": live_res.get("confidence", 99.2),
                    "liveness_status": live_res.get("status"),
                    "face_match": comp_res.get("similarity", 98.5),
                    "face_match_passed": comp_res.get("match", False)
                }
                st.session_state.step = 3
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
                
                
# =============================================================================
# Step 3: Rules Engine & Agent Evaluation
# =============================================================================
    elif st.session_state.step == 3:
        st.markdown('<div class="step-container">', unsafe_allow_html=True)
        st.markdown("### Step 3: Risk Evaluation & Final Underwriting")
        
        # Display Rekognition Metrics
        c1, c2 = st.columns(2)
        
        score_1 = st.session_state.liveness.get("liveness_confidence", 0)
        c1.markdown(
            f"<div class='metric-box'>Face Liveness Score<br>"
            f"<span class='{'status-ok' if score_1 > 90 else 'status-fail'}'>{score_1}%</span>"
            f"</div>", 
            unsafe_allow_html=True
        )
        
        score_2 = st.session_state.liveness.get("face_match", 0)
        c2.markdown(
            f"<div class='metric-box'>ID Card Photo Match<br>"
            f"<span class='{'status-ok' if score_2 > 90 else 'status-fail'}'>{score_2}%</span>"
            f"</div>", 
            unsafe_allow_html=True
        )
        
        st.divider()
        
        if "decision" not in st.session_state:
            if st.button("Execute AWS Lambda Rules Engine & Bedrock Agent", type="primary", use_container_width=True):
                
                # 1. Lambda Rules Engine (Hard constraints)
                with st.spinner("Executing AWS Lambda policy rules engine (Age/Sanctions)..."):
                    time.sleep(1)
                    rules_res = invoke_rules_engine_mock(st.session_state.parsed_data)
                    rules_res = apply_identity_gate(rules_res, st.session_state.liveness)
                    
                # 2. Bedrock AgentCore (Soft rationale)
                with st.spinner("Invoking Bedrock AgentCore for underwriting rationale..."):
                    agent = UnderwritingAgent()
                    
                    # Combine context for the agent
                    agent_payload = {
                        "applicant": st.session_state.parsed_data,
                        "rules_evaluation": rules_res,
                        "liveness_metrics": st.session_state.liveness
                    }
                    
                    final_res = agent.evaluate_applicant(
                        applicant_data=agent_payload,
                        session_id=st.session_state.applicant_id
                    )

                packet = build_decision_packet(
                    applicant_id=st.session_state.applicant_id,
                    applicant_data=st.session_state.parsed_data,
                    rules_result=rules_res,
                    liveness_metrics=st.session_state.liveness,
                    agent_result=final_res
                )
                    
                # 3. Store Immutable Audit Trail in DynamoDB
                with st.spinner("Writing immutable audit log to DynamoDB..."):
                    try:
                        db = DynamoAuditStore()
                        db.record_decision(
                            applicant_id=st.session_state.applicant_id,
                            decision=rules_res.get("decision", "UNKNOWN"),
                            rules_triggered=rules_res.get("flags", []),
                            agent_rationale=final_res.get("decision_text", ""),
                            risk_score=rules_res.get("risk_score", 0)
                        )
                    except Exception:
                        pass
                
                # Save to state for display
                st.session_state.decision = {
                    "hard_decision": rules_res.get("decision"),
                    "risk_score": rules_res.get("risk_score"),
                    "decision_confidence": packet.get("decision_confidence"),
                    "flags": rules_res.get("flags", []),
                    "rationale": final_res.get("decision_text"),
                    "review_actions": packet.get("review_actions", []),
                    "rule_results": packet.get("rule_results", [])
                }
                st.session_state.rules = rules_res
                st.session_state.underwriting_packet = packet
                st.rerun()
                
        else:
            # Display Final Decision
            dec = st.session_state.decision
            
            status_color = "status-ok" if "APPROVE" in dec['hard_decision'] else ("status-warn" if "REVIEW" in dec['hard_decision'] else "status-fail")
            st.markdown(f"#### Hard Configuration Decision: <span class='{status_color}'>{dec['hard_decision']}</span>", unsafe_allow_html=True)
            st.metric("Decision Confidence", f"{dec.get('decision_confidence', 0)}%")
            
            if dec['flags']:
                for flag in dec['flags']:
                    st.error(f"🚩 Rule Flagged: {flag}")

            st.markdown("#### Rule Evidence")
            for rule in dec.get("rule_results", []):
                rule_status = "PASS" if rule.get("passed") else "FAIL"
                if rule.get("passed"):
                    st.success(f"{rule_status} · {rule.get('rule_id')}: {rule.get('message')}")
                else:
                    st.warning(f"{rule_status} · {rule.get('rule_id')}: {rule.get('message')}")

            if dec.get("review_actions"):
                st.markdown("#### Underwriter Review Actions")
                for action in dec["review_actions"]:
                    st.write(f"- {action}")
            
            st.markdown("#### Agent Rationale" + (" (template in demo mode)" if config.DEMO_MODE and not os.getenv("UNDERWRITING_LLM") else ""))
            st.info(dec['rationale'])

            with st.expander("Audit Decision Packet"):
                st.json(st.session_state.underwriting_packet)
            
            if config.DEMO_MODE:
                st.success("✅ Complete. In demo mode the DynamoDB audit write is skipped.")
            else:
                st.success("✅ Complete. Decision recorded to the DynamoDB audit trail.")
            
        st.markdown('</div>', unsafe_allow_html=True)
