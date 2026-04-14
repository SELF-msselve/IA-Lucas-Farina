# =========================
# LegalMove - Contract Comparator (FINAL STABLE VERSION)
# Uses: PyMuPDF SAFE IMPORT + Modern LangChain + Langfuse Safe Logging
# =========================

import os
import base64
from typing import List, Optional
from dotenv import load_dotenv

import streamlit as st
from pydantic import BaseModel, ValidationError

# ✅ SAFE PyMuPDF import (no fitz conflict)
import pymupdf as fitz

# LangChain (modern)
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate

# Langfuse (safe wrapper)
from langfuse import Langfuse

# =========================
# ENV
# =========================
load_dotenv()

langfuse = Langfuse(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
)

print('paso por las claves')

# =========================
# SAFE LOGGING
# =========================

def log(name, data):
    try:
        trace = langfuse.start_trace(name=name)
        trace.end(output={"result": str(data)[:3000]})
    except:
        pass

# =========================
# SCHEMA
# =========================
class ClauseChange(BaseModel):
    clause_id: Optional[str]
    original_text: str
    amended_text: str
    change_type: str
    legal_impact: str

class ContractDiff(BaseModel):
    modified_clauses: List[ClauseChange]
    affected_topics: List[str]
    summary: str

# =========================
# UTILS
# =========================

def encode_bytes(b: bytes):
    return base64.b64encode(b).decode("utf-8")

# -------- Vision Parsing --------
def parse_image(image_b64):
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    msg = HumanMessage(content=[
        {"type": "text", "text": "Extract all text from this legal document."},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}
    ])

    res = llm.invoke([msg])
    log("vision_parsing", res.content)
    return res.content

# -------- PDF Parsing --------
def parse_pdf(file):
    doc = fitz.open(stream=file.read(), filetype="pdf")
    full_text = ""


    print(doc)

    
    for page in doc:
        pix = page.get_pixmap()
        img_b64 = encode_bytes(pix.tobytes("png"))
        full_text += "\n" + parse_image(img_b64)

    log("pdf_parsing", full_text)
    return full_text

# -------- Dispatcher --------
def extract_text(file):
    if file.type == "application/pdf":
        print('archivos pdf')
        return parse_pdf(file)
    return parse_image(encode_bytes(file.read()))

# =========================
# AGENTS
# =========================

def build_agents():
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    structure_prompt = ChatPromptTemplate.from_template("""
    Structure this contract into clauses.

    Output JSON:
    {{"clauses": [{{"id":"1","title":"...","text":"..."}}]}}

    CONTRACT:
    {text}
    """)

    compare_prompt = ChatPromptTemplate.from_template("""
Compare contracts.

Return JSON:
{{  
    "changes": [
        {{
            "clause_id": "...",
            "change_type": "...",
            "summary": "..."
        }}
    ]
}}

ORIGINAL:
{original}

AMENDED:
{amended}
""")

    structure_chain = structure_prompt | llm
    compare_chain = compare_prompt | llm

    def structure(text):
        res = structure_chain.invoke({"text": text})
        log("structurer", res.content)
        return res.content

    def compare(o, a):
        res = compare_chain.invoke({"original": o, "amended": a})
        log("comparator", res.content)
        return res.content

    return structure, compare

# =========================
# UI
# =========================

def main():
    st.title("📄 LegalMove AI Comparator")

    original = st.file_uploader("Original Contract", type=["pdf","png","jpg","jpeg"])
    amended = st.file_uploader("Amendment", type=["pdf","png","jpg","jpeg"])

    if st.button("Analyze"):
        if not original or not amended:
            st.error("Upload both files")
            return

        with st.spinner("Processing..."):
            o_text = extract_text(original)
            a_text = extract_text(amended)

            structure, compare = build_agents()

            o_struct = structure(o_text)
            a_struct = structure(a_text)

            diff = compare(o_struct, a_struct)

            try:
                result = ContractDiff.model_validate_json(diff)
                st.success("Analysis complete")
                st.json(result.model_dump())
                log("final", result.model_dump())

            except ValidationError as e:
                st.error("Validation error")
                st.text(diff)
                st.text(str(e))


if __name__ == "__main__":
    main()
