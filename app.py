import os
import re
import io
import time
import json
import html
import requests
from urllib.parse import urlparse
from datetime import datetime
from typing import Optional
import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
try:
    import pypdf

    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False
try:
    from bs4 import BeautifulSoup

    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
try:
    from PIL import Image, ImageDraw, ImageFont

    HAS_PIL = True
except ImportError:
    HAS_PIL = False
try:
    import cairosvg

    HAS_CAIROSVG = True
except (ImportError, OSError):
    HAS_CAIROSVG = False
# Key is now fetched dynamically via get_api_key() to ensure reliability on Streamlit Cloud
HISTORY_FILE = "scan_history.json"


def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_history(history):
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(history[:20], f)
    except Exception:
        pass


st.set_page_config(
    page_title="TOS-IC | Savage Legal Scanner",
    layout="wide",
    initial_sidebar_state="expanded",
)
defaults = {
    "archives": load_history(),
    "last_analysis": None,
    "last_compare": None,
    "last_meme": None,
    "input_mode": "Text",
}
for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


def get_api_key():
    return st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")


@st.cache_resource
def get_client():
    api_key = get_api_key()
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


def check_rate_limit():
    if "request_times" not in st.session_state:
        st.session_state.request_times = []
    now = time.time()
    st.session_state.request_times = [
        t for t in st.session_state.request_times if now - t < 600
    ]
    if len(st.session_state.request_times) >= 5:
        return False
    st.session_state.request_times.append(now)
    return True


if os.path.exists("style.css"):
    with open("style.css") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


def esc(value) -> str:
    return html.escape(str(value or ""))


def extract_json(raw: str) -> dict:
    if not raw:
        raise ValueError("Empty model response.")
    cleaned = raw.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(cleaned[start : end + 1])
            except Exception:
                pass
        raise


def normalize_url(url: str) -> str:
    url = url.strip()
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


@st.cache_data(ttl=3600, show_spinner=False)
def extract_from_url(url: str) -> str:
    try:
        url = normalize_url(url)
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "en-US,en;q=0.9",
        }
        r = requests.get(url, headers=headers, timeout=10, stream=True)
        content_length = int(r.headers.get("Content-Length", 0))
        if content_length > 2_000_000:
            raise ValueError("Page too large")
        r.raise_for_status()
        text_content = r.text[:200_000]
        if HAS_BS4:
            soup = BeautifulSoup(text_content, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
        else:
            raw_html = r.text
            raw_html = re.sub(r"<script.*?</script>", "", raw_html, flags=re.DOTALL)
            raw_html = re.sub(r"<style.*?</style>", "", raw_html, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", raw_html)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        result = text.strip()
        if not result or len(result) < 300:
            st.warning(
                "⚠️ Content too thin. The site might be blocking access or requires JavaScript."
            )
            return ""
        return result
    except Exception as e:
        st.error(f"❌ Could not fetch URL: {e}")
        return ""


def extract_from_pdf(uploaded_file) -> str:
    if uploaded_file.size > 5 * 1024 * 1024:
        st.error("❌ PDF too large (max 5MB)")
        return ""
    if not HAS_PYPDF:
        st.error("❌ pypdf is not installed. Run: pip install pypdf")
        return ""
    try:
        reader = pypdf.PdfReader(uploaded_file)
        return "\n".join(
            page.extract_text() or "" for page in reader.pages[:30]
        ).strip()
    except Exception as e:
        st.error(f"❌ Could not read PDF: {e}")
        return ""


@st.cache_data(ttl=3600, show_spinner=False)
def get_company_meta_from_url(url: str) -> dict:
    try:
        domain = urlparse(url).netloc
        if domain.startswith("www."):
            domain = domain[4:]
        parts = domain.split(".")
        if len(parts) >= 3:
            name = parts[-2].capitalize()
        else:
            name = parts[0].capitalize()
        brand_map = {"Openai": "OpenAI", "Github": "GitHub", "Youtube": "YouTube"}
        name = brand_map.get(name, name)
        return {
            "name": name,
            "domain": domain,
            "logo": f"https://logo.clearbit.com/{domain}",
        }
    except Exception:
        return {"name": "Unknown", "domain": "", "logo": ""}


@st.cache_data(show_spinner=False)
def get_company_name_from_text(text: str) -> str:
    c = get_client()
    if not c:
        return "Unknown Company"
    try:
        res = c.models.generate_content(
            model="gemini-2.0-flash",
            contents=f"Extract the company name from this text. Return ONLY the name (max 3 words). If unknown, return 'Unknown Company'.\n\nTEXT:\n{text[:2000]}",
        )
        name = res.text.strip().strip('"').strip("'")
        if not name or len(name) > 40 or "\n" in name:
            return "Unknown Company"
        return name
    except Exception:
        return "Unknown Company"


def logo_img_tag(logo_url: str, css_class: str = "company-logo") -> str:
    if not logo_url:
        return ""
    return (
        f'<img src="{esc(logo_url)}" class="{css_class}" '
        f"onerror=\"this.style.display='none'\">"
    )


def safe_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def rating_from_score(score: int) -> str:
    if score >= 70:
        return "Critical"
    if score >= 35:
        return "Risky"
    return "Safe"


def normalize_analysis(data: dict) -> dict:
    if not isinstance(data, dict):
        data = {}
    score = max(0, min(100, safe_int(data.get("risk_score", 0))))
    rating = data.get("rating") or rating_from_score(score)
    if rating not in ["Safe", "Risky", "Critical"]:
        rating = rating_from_score(score)
    data["risk_score"] = score
    data["rating"] = rating
    data.setdefault("summary", "This agreement needs a closer look.")
    data.setdefault("savage_take", "This agreement deserves a second read.")
    data.setdefault("red_flags", [])
    if not isinstance(data["red_flags"], list):
        data["red_flags"] = []
    normalized_flags = []
    for flag in data["red_flags"][:3]:
        if not isinstance(flag, dict):
            continue
        flag.setdefault("title", "Suspicious clause")
        flag.setdefault("severity", "High Risk")
        flag.setdefault("meaning", "This could affect you in a way worth checking.")
        flag.setdefault(
            "worst_case", "You may lose control, money, access, or privacy."
        )
        flag.setdefault(
            "savage_explanation", "Translation: read this twice before trusting it."
        )
        normalized_flags.append(flag)
    data["red_flags"] = normalized_flags
    return data


def add_archive(entry: dict):
    new_data = entry.get("data", {})
    new_key = (
        entry.get("company"),
        new_data.get("summary"),
        new_data.get("risk_score"),
    )
    for old in st.session_state.archives[:4]:
        old_data = old.get("data", {})
        old_key = (
            old.get("company"),
            old_data.get("summary"),
            old_data.get("risk_score"),
        )
        if old_key == new_key:
            return
    st.session_state.archives.insert(0, entry)
    save_history(st.session_state.archives)


def fun_stats(score: int) -> dict:
    score = safe_int(score)
    return {
        "Chaos Meter": f"{min(100, score + 7)}%",
        "Lawyer Tears": f"{max(1, score // 13)} buckets",
        "Data Vacuum": (
            "Turbo" if score >= 70 else ("Suspicious" if score >= 40 else "Low")
        ),
    }


@st.cache_data(show_spinner=False)
def analyze_legal(text: str, is_compare: bool = False, savage: bool = False) -> dict:
    if not get_api_key():
        raise RuntimeError("API Key missing. Configure it in Streamlit Secrets.")
    c = get_client()
    if not c:
        raise RuntimeError("AI Client failed to initialize.")
    flag_format = '"red_flags": [{"title":"...","severity":"Critical|High Risk|Medium Risk","meaning":"...","worst_case":"...","savage_explanation":"..."}]'
    tone_rules = """
NORMAL MODE:
- Be clear, direct, and consumer-friendly.
- No legal jargon.
- Keep explanations practical.
"""
    if savage:
        tone_rules = """
SAVAGE MODE:
- Be sarcastic, funny, and brutally clear.
- Roast the clause, not the user.
- Keep it safe, accurate, and useful.
- Make "savage_explanation" sound like a witty friend exposing corporate nonsense.
- Example style: "Translation: they can change the rules mid-game and still act shocked when you complain."
- Do NOT invent facts that are not supported by the text.
"""
    prompt = f"""
You are TOS-IC, a ruthless consumer-rights AI that explains Terms of Service and Privacy Policies.
Return ONLY valid JSON.
No markdown.
No commentary outside JSON.
{tone_rules}
RULES:
- ZERO legal jargon.
- Be specific and scary only when the text supports it.
- "meaning" must be one plain sentence a 12-year-old understands.
- "worst_case" must be one concrete nightmare scenario.
- "summary" must be under 15 words.
- "savage_take" must be one punchy sarcastic sentence if Savage Mode is on, otherwise a neutral sentence.
- Max 3 red flags.
- Every red flag must include severity.
- "rating" must be exactly one of: Safe / Risky / Critical
- "risk_score" must be a number from 0 to 100.
- If a specific risk or clause is not clearly stated or supported by the provided text, do NOT invent it. Instead, say "Not explicitly stated in the provided text" in the explanation fields.
JSON format:
{{
  "risk_score": <number 0-100>,
  "rating": "<Safe|Risky|Critical>",
  "summary": "<15 words max>",
  "savage_take": "<one sentence>",
  {flag_format}
}}
LEGAL TEXT:
{text[:12000]}
"""
    res = c.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.55 if savage else 0.25,
            max_output_tokens=2048,
        ),
        timeout=30,
    )
    if not res.text:
        raise ValueError("Empty response from AI")
    data = extract_json(res.text)
    return normalize_analysis(data)


@st.cache_resource
def get_font(size: int, bold: bool = False):
    if not HAS_PIL:
        return None
    candidates = [
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        ),
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "Arial Bold.ttf" if bold else "Arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def wrap_text(text: str, max_chars: int) -> str:
    words = str(text).split()
    lines = []
    current = ""
    for word in words:
        if len(current + " " + word) <= max_chars:
            current = (current + " " + word).strip()
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return "\n".join(lines)


def generate_fallback_meme(
    worst_case: str, company: str, savage: bool = False
) -> Optional[bytes]:
    if not HAS_PIL:
        return None
    W, H = 1280, 720
    img = Image.new("RGB", (W, H), (9, 9, 11))
    draw = ImageDraw.Draw(img)
    for y in range(H):
        r = int(9 + y * 0.01)
        g = int(9 + y * 0.01)
        b = int(11 + y * 0.01)
        draw.line([(0, y), (W, y)], fill=(r, g, b))
    draw.ellipse((-180, -160, 420, 440), fill=(24, 24, 27))
    draw.ellipse((900, -140, 1500, 460), fill=(24, 24, 27))
    title_font = get_font(70, True)
    subtitle_font = get_font(34, True)
    body_font = get_font(42, True)
    small_font = get_font(24, False)
    draw.rounded_rectangle(
        (90, 80, 1190, 640),
        radius=38,
        fill=(24, 24, 27),
        outline=(39, 39, 42),
        width=4,
    )
    triangle = [(180, 190), (300, 420), (60, 420)]
    draw.polygon(triangle, outline=(225, 29, 72), fill=(39, 39, 42))
    draw.line((180, 250, 180, 335), fill=(225, 29, 72), width=12)
    draw.ellipse((170, 365, 190, 385), fill=(225, 29, 72))
    draw.text((340, 145), "TOS-IC WARNING", font=title_font, fill=(225, 29, 72))
    draw.text((345, 230), company.upper(), font=subtitle_font, fill=(250, 250, 250))
    label = "SAVAGE TRANSLATION" if savage else "THREAT SUMMARY"
    draw.text((345, 300), label, font=small_font, fill=(161, 161, 170))
    body = wrap_text(
        worst_case or "This policy may hide serious privacy or account risks.", 36
    )
    draw.text((345, 340), body, font=body_font, fill=(212, 212, 216), spacing=10)
    draw.text(
        (95, 665),
        "AI-generated satirical legal-tech poster · Verify before making decisions",
        font=small_font,
        fill=(113, 113, 122),
    )
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


@st.cache_data(show_spinner=False)
def generate_threat_meme(
    worst_case: str, company: str, savage: bool = False
) -> Optional[bytes]:
    try:
        style_desc = (
            "extra sarcastic, viral meme style"
            if savage
            else "simple, bold warning meme"
        )
        prompt = f"""
Generate ONLY raw SVG code for a 800x800 square meme card.
Style: {style_desc} clean minimalist modern design.
Colors: very dark neutral background (#09090B), crimson red accents (#E11D48), orange warnings (#EA580C).
Requirements:
- Size: width="800" height="800"
- Solid dark background with a 15px bright red border
- Top text: "TOS-IC INTEL" in small red caps
- Center: A large, simple warning symbol (triangle or circle)
- Big bold text: "{company.upper()}"
- Bottom text: A punchy, sarcastic one-line caption about: "{worst_case[:100]}"
- Use only standard SVG shapes and text
- No complex filters, just clean bold lines
- Output ONLY the SVG code. No markdown, no backticks.
SVG starts with <svg and ends with </svg>
"""
        c = get_client()
        if not c:
            raise RuntimeError("API Key missing.")
        res = c.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            timeout=30,
        )
        raw = res.text or ""
        svg_match = re.search(r"<svg[^>]*>.*?</svg>", raw, re.DOTALL | re.IGNORECASE)
        if not svg_match:
            svg_match = re.search(r"<svg.*", raw, re.DOTALL | re.IGNORECASE)
            if not svg_match:
                raise ValueError("No SVG found in Gemini response")
            svg_code = svg_match.group(0)
            if "</svg>" not in svg_code.lower():
                svg_code += "</svg>"
        else:
            svg_code = svg_match.group(0)
        svg_code = (
            svg_code.replace("```xml", "")
            .replace("```svg", "")
            .replace("```", "")
            .strip()
        )
        if HAS_CAIROSVG:
            png_bytes = cairosvg.svg2png(
                bytestring=svg_code.encode("utf-8"),
                output_width=800,
                output_height=800,
            )
            return png_bytes
        else:
            raise RuntimeError("cairosvg not installed. Run: pip install cairosvg")
    except Exception as e:
        st.info(f"ℹ️ Meme generation issue: {e} — Using local fallback.")
        return generate_fallback_meme(worst_case, company, savage=savage)


def render_result(entry: dict, savage_mode: bool):
    data = entry["data"]
    company = entry.get("company", "Unknown")
    logo_url = entry.get("logo", "")
    flags = data.get("red_flags", [])
    st.markdown(
        '<div class="section-title">🔍 Forensic Results</div>', unsafe_allow_html=True
    )
    logo_tag = logo_img_tag(logo_url, "company-logo")
    score = safe_int(data.get("risk_score", 0))
    fun = fun_stats(score)
    st.markdown(
        f"""
<div class="top-result-box">
    <div class="score-orb">
        <span class="num">{score}</span>
        <span class="den">/100</span>
    </div>
    <div class="top-result-text">
        <div class="company-name">{logo_tag} {esc(company)}</div>
        <h2>⚠️ {esc(data.get("rating", "Unknown"))}</h2>
        <p>{esc(data.get("summary", ""))}</p>
    </div>
</div>
""",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
<div class="fun-grid">
    <div class="fun-card">
        <div class="fun-label">🌪️ Chaos Meter</div>
        <div class="fun-value">{esc(fun["Chaos Meter"])}</div>
    </div>
    <div class="fun-card">
        <div class="fun-label">😭 Lawyer Tears</div>
        <div class="fun-value">{esc(fun["Lawyer Tears"])}</div>
    </div>
    <div class="fun-card">
        <div class="fun-label">🧹 Data Vacuum</div>
        <div class="fun-value">{esc(fun["Data Vacuum"])}</div>
    </div>
</div>
""",
        unsafe_allow_html=True,
    )
    if savage_mode and data.get("savage_take"):
        st.markdown(
            f"""
<div class="savage-banner">
    <div class="savage-banner-title">🔥 Savage Translation</div>
    <div class="savage-banner-text">{esc(data.get("savage_take"))}</div>
</div>
""",
            unsafe_allow_html=True,
        )
    if flags:
        st.markdown(
            '<div class="section-title">🚩 Red Flags Detected</div>',
            unsafe_allow_html=True,
        )
        cols = st.columns(min(len(flags), 2))
        for i, flag in enumerate(flags):
            sev = str(flag.get("severity", "High Risk")).lower()
            if "critical" in sev or "extreme" in sev:
                badge_cls = "badge"
            elif "high" in sev:
                badge_cls = "badge high"
            else:
                badge_cls = "badge safe"
            savage_html = ""
            if savage_mode and flag.get("savage_explanation"):
                savage_html = f"""
<div class="savage-translation">
    <div class="savage-translation-label">🔥 Savage Explanation</div>
    <div class="savage-translation-text">{esc(flag.get("savage_explanation"))}</div>
</div>
"""
            card_html = f"""
<div class="flag-card">
    <div class="flag-head">
        <h3 class="flag-title">{esc(flag.get("title", "Unknown Flag"))}</h3>
        <span class="{badge_cls}">{esc(flag.get("severity", "?"))}</span>
    </div>
    <p class="flag-desc">{esc(flag.get("meaning", ""))}</p>
    <div class="worst-case-box">
        <div class="wc-label">💀 Worst Case Scenario</div>
        <p class="wc-text">{esc(flag.get("worst_case", "Unknown impact."))}</p>
    </div>
    {savage_html}
</div>
"""
            with cols[i % len(cols)]:
                st.markdown(card_html, unsafe_allow_html=True)
    st.markdown(
        '<div class="section-title">🎨 Threat Visualizer</div>', unsafe_allow_html=True
    )
    worst_overall = (
        flags[0].get("worst_case", data.get("summary", ""))
        if flags
        else data.get("summary", "")
    )
    gen_col, _ = st.columns([1, 3])
    with gen_col:
        meme_btn = st.button("🎨 VISUALIZE THREAT", use_container_width=True)
    if meme_btn:
        with st.spinner(
            "Generating savage cyberpunk threat poster..."
            if savage_mode
            else "Generating threat visual..."
        ):
            st.session_state.last_meme = generate_threat_meme(
                worst_overall,
                company,
                savage=savage_mode,
            )
    if st.session_state.last_meme:
        company = entry.get("company", "Unknown")
        svg_data = st.session_state.last_meme
        render_fallback = False
        if HAS_CAIROSVG:
            try:
                png_data = cairosvg.svg2png(bytestring=svg_data.encode("utf-8"))
                st.markdown('<div class="meme-box">', unsafe_allow_html=True)
                st.image(png_data, use_container_width=True)
                st.markdown(
                    f'<div class="meme-caption">⚠️ AI-generated satirical threat visualization · {esc(company)} · TOS-IC</div>',
                    unsafe_allow_html=True,
                )
                st.markdown("</div>", unsafe_allow_html=True)
                st.download_button(
                    "💾 DOWNLOAD POSTER (PNG)",
                    png_data,
                    file_name=f"tos_ic_{company.lower().replace(' ', '_')}.png",
                    mime="image/png",
                )
            except Exception as e:
                print(f"DEBUG: SVG conversion failed: {e}")
                render_fallback = True
        else:
            render_fallback = True
        if render_fallback:
            fallback_png = generate_fallback_meme(
                entry["data"].get("summary", ""), company, savage_mode
            )
            if fallback_png:
                st.markdown('<div class="meme-box">', unsafe_allow_html=True)
                st.image(fallback_png, use_container_width=True)
                st.markdown(
                    f'<div class="meme-caption">⚠️ AI-generated summary poster · {esc(company)} · TOS-IC</div>',
                    unsafe_allow_html=True,
                )
                st.markdown("</div>", unsafe_allow_html=True)
                st.download_button(
                    "💾 DOWNLOAD POSTER (PNG)",
                    fallback_png,
                    file_name=f"tos_ic_{company.lower().replace(' ', '_')}.png",
                    mime="image/png",
                )
            else:
                st.warning(
                    "⚠️ High-quality poster generation failed. Displaying raw SVG data."
                )
                st.code(svg_data, language="xml")


def render_compare_results(compare_data: dict, savage_mode: bool):
    metaA = compare_data["metaA"]
    metaB = compare_data["metaB"]
    resA = compare_data["resA"]
    resB = compare_data["resB"]
    scoreA = safe_int(resA.get("risk_score", 0))
    scoreB = safe_int(resB.get("risk_score", 0))
    if scoreA == scoreB:
        winner_text = f"☠️ Tie: both scored {scoreA}/100"
    else:
        riskier_name = metaA["name"] if scoreA > scoreB else metaB["name"]
        winner_text = f"💀 {riskier_name} is Riskier"
    st.markdown(
        f'<div class="compare-winner">{esc(winner_text)}</div>',
        unsafe_allow_html=True,
    )
    col1, col2 = st.columns(2)
    for col, meta, res in [(col1, metaA, resA), (col2, metaB, resB)]:
        with col:
            score = safe_int(res.get("risk_score", 0))
            color_class = "danger" if score >= 60 else "safe"
            badge_label = (
                "Privacy Dumpster Fire"
                if color_class == "danger" and savage_mode
                else (
                    "Critical Risk"
                    if color_class == "danger"
                    else ("Actually Not Horrible" if savage_mode else "Lower Risk")
                )
            )
            logo_tag = logo_img_tag(meta.get("logo", ""), "cc-logo")
            flags_html = ""
            for f in res.get("red_flags", []):
                savage_line = ""
                if savage_mode and f.get("savage_explanation"):
                    savage_line = f'<div class="log-wc">🔥 {esc(f.get("savage_explanation"))}</div>'
                wc_line = (
                    f'<div class="log-wc">💀 {esc(f.get("worst_case", ""))}</div>'
                    if f.get("worst_case")
                    else ""
                )
                flags_html += f"""
<div class='log-item'>
    <span>{"🚫" if color_class == "danger" else "✅"}</span>
    <div>
        <b>{esc(f.get("title", "Flag"))}:</b> {esc(f.get("meaning", ""))}
        {wc_line}
        {savage_line}
    </div>
</div>
"""
            if not flags_html:
                flags_html = """
<div class='log-item'>
    <span>✅</span>
    <div>No major red flags were detected in the analyzed text.</div>
</div>
"""
            savage_verdict = ""
            if savage_mode and res.get("savage_take"):
                savage_verdict = f"""
<div class="savage-translation" style="margin-bottom:14px;">
    <div class="savage-translation-label">🔥 Savage Verdict</div>
    <div class="savage-translation-text">{esc(res.get("savage_take", ""))}</div>
</div>
"""
            st.markdown(
                f"""
<div class="compare-card cc-{color_class}">
    <div class="cc-header">
        <div>
            <div class="cc-title">{logo_tag} {esc(meta["name"])}</div>
            <span class="cc-badge-{color_class}">{esc(badge_label)}</span>
        </div>
        <div>
            <p class="cc-score-label">Threat Score</p>
            <p class="cc-score-num {color_class}">{score}</p>
        </div>
    </div>
    <p style="color:#8b949e;font-size:14px;font-weight:700;margin:0 0 10px 0;">
        {esc(res.get("summary", ""))}
    </p>
    {savage_verdict}
    <div class="log-list">
        <span class="wc-label" style="margin-bottom:0;">📋 Anomaly Log</span>
        {flags_html}
    </div>
</div>
""",
                unsafe_allow_html=True,
            )


with st.sidebar:
    st.markdown(
        """
<div style="padding:12px 4px 22px 4px;">
    <h2 class="sidebar-title">⚖️ TOS-IC</h2>
    <div class="sidebar-tagline">Terms of Service Interrogation Console</div>
</div>
""",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div style="font-size:11px;color:#484f58;font-weight:900;letter-spacing:2px;margin-bottom:12px;">NAVIGATION</div>',
        unsafe_allow_html=True,
    )
    nav = st.radio(
        "nav",
        ["🎯 ANALYZE", "⚔️ COMPARE", "🗂️ ARCHIVES"],
        label_visibility="collapsed",
    )
    st.divider()
    st.markdown(
        """
<div class="savage-panel">
    <div class="savage-panel-title">🔥 Savage Mode</div>
    <div class="savage-panel-text">
        Turns boring legal sludge into spicy, sarcastic, human-readable warnings.
    </div>
</div>
""",
        unsafe_allow_html=True,
    )
    savage_mode = st.toggle("🔥 Enable Savage Mode", value=True)
    st.divider()
    n_archives = len(st.session_state.archives)
    st.markdown(
        f"""
<div style="font-size:11px;color:#484f58;font-weight:900;letter-spacing:2px;margin-bottom:12px;">SESSION</div>
<div style="font-size:14px;color:#8b949e;font-weight:700;">
    📁 {n_archives} scan{"s" if n_archives != 1 else ""} archived
</div>
""",
        unsafe_allow_html=True,
    )
    if st.button("🗑️ CLEAR ARCHIVES", use_container_width=True):
        st.session_state.archives = []
        st.session_state.last_analysis = None
        st.session_state.last_compare = None
        st.session_state.last_meme = None
        save_history([])
        st.rerun()
    if st.session_state.last_analysis:
        data = st.session_state.last_analysis["data"]
        report_lines = [
            f"TOS-IC REPORT — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"Company: {st.session_state.last_analysis.get('company', 'Unknown')}",
            f"Risk Score: {data.get('risk_score', 0)}/100",
            f"Rating: {data.get('rating', 'Unknown')}",
            f"Summary: {data.get('summary', '')}",
            f"Savage Take: {data.get('savage_take', '')}",
            "",
            "RED FLAGS:",
        ]
        for f in data.get("red_flags", []):
            report_lines += [
                f"  • {f.get('title', '')}",
                f"    Severity: {f.get('severity', '')}",
                f"    Meaning: {f.get('meaning', '')}",
                f"    Worst Case: {f.get('worst_case', 'N/A')}",
                f"    Savage Translation: {f.get('savage_explanation', '')}",
                "",
            ]
        report_text = "\n".join(report_lines)
        st.download_button(
            "📥 EXPORT REPORT",
            data=report_text,
            file_name="tos_ic_report.txt",
            mime="text/plain",
            use_container_width=True,
        )
    st.divider()
    st.markdown(
        '<div style="font-size:11px;color:#484f58;font-weight:900;letter-spacing:2px;margin-bottom:12px;">API SETTINGS</div>',
        unsafe_allow_html=True,
    )
    if not get_api_key():
        st.warning("⚠️ API Key not configured.")
    else:
        st.success("✅ API ready.")
    
    # DEBUG: Help identify deployment key-loading issues
    with st.expander("🛠️ Debug Info", expanded=False):
        st.write("DEBUG KEY:", bool(get_api_key()))
        st.write("DEBUG CLIENT:", get_client() is not None)
if nav == "🎯 ANALYZE":
    st.markdown(
        '<div class="page-title">Analysis <span>Engine</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="page-sub">Drop in a Terms of Service, Privacy Policy, URL, or PDF. We translate corporate fog into actual consequences.</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="input-mode-card">', unsafe_allow_html=True)
    st.markdown(
        f'<div class="active-mode-chip">Current Input: {esc(st.session_state.input_mode)}</div>',
        unsafe_allow_html=True,
    )
    mode_cols = st.columns(3)
    mode_buttons = [
        ("📝 TEXT", "Text"),
        ("🔗 URL", "URL"),
        ("📄 PDF", "PDF"),
    ]
    for col, (label, value) in zip(mode_cols, mode_buttons):
        with col:
            active_prefix = "✅ " if st.session_state.input_mode == value else ""
            if st.button(
                f"{active_prefix}{label}",
                key=f"mode_{value}",
                use_container_width=True,
            ):
                st.session_state.input_mode = value
                st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
    raw_text_input = ""
    url_input = ""
    pdf_file = None
    with st.container(border=True):
        st.markdown(
            '<div style="font-size:11px;color:#8b949e;margin-bottom:12px;font-weight:900;letter-spacing:1.5px;">TARGET INPUT</div>',
            unsafe_allow_html=True,
        )
        if st.session_state.input_mode == "Text":
            raw_text_input = st.text_area(
                "Paste TOS",
                height=210,
                label_visibility="collapsed",
                placeholder="Paste Terms of Service, Privacy Policy, or any legal agreement here...",
            )
        elif st.session_state.input_mode == "URL":
            url_input = st.text_input(
                "URL",
                label_visibility="collapsed",
                placeholder="🔗 https://example.com/terms",
            )
        else:
            pdf_file = st.file_uploader(
                "Upload PDF",
                type=["pdf"],
                label_visibility="collapsed",
            )
        run_col, hint_col = st.columns([1, 4])
        with run_col:
            run_btn = st.button("🚀 RUN AUDIT", use_container_width=True)
        with hint_col:
            if savage_mode:
                st.markdown(
                    '<div style="color:#ff6b63;font-weight:800;padding-top:10px;">🔥 Savage Mode armed. Corporate nonsense will be translated with attitude.</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    '<div style="color:#8b949e;font-weight:700;padding-top:10px;">Standard mode enabled. Professional, polite, and slightly less fun.</div>',
                    unsafe_allow_html=True,
                )
    if run_btn:
        if not get_api_key():
            st.error("❌ API key missing. Configure it in Streamlit Secrets.")
            st.stop()
        if not check_rate_limit():
            st.error("⚠️ Slow down! You've reached the scan limit (5 per 10 mins).")
            st.stop()
        raw_text = ""
        company_meta = {"name": "Unknown", "domain": "", "logo": ""}
        if st.session_state.input_mode == "Text":
            raw_text = raw_text_input.strip()
            if raw_text:
                with st.spinner("Identifying target..."):
                    company_meta["name"] = get_company_name_from_text(raw_text)
        elif st.session_state.input_mode == "URL":
            url_val = url_input.strip()
            if url_val:
                company_meta = get_company_meta_from_url(url_val)
                with st.spinner(f"Fetching {company_meta['name']} TOS..."):
                    raw_text = extract_from_url(url_val)
        else:
            if pdf_file:
                company_meta["name"] = (
                    pdf_file.name.replace(".pdf", "").replace("_", " ").title()
                )
                with st.spinner("Extracting PDF text..."):
                    raw_text = extract_from_pdf(pdf_file)
        if not raw_text or len(raw_text.strip()) < 300:
            st.warning("⚠️ Text is too short for a reliable analysis (min 300 chars).")
        else:
            try:
                with st.spinner(
                    "🔥 Roasting suspicious clauses..."
                    if savage_mode
                    else "Decoding compliance architecture..."
                ):
                    data = analyze_legal(
                        raw_text,
                        is_compare=False,
                        savage=savage_mode,
                    )
                entry = {
                    "data": data,
                    "company": company_meta["name"],
                    "logo": company_meta.get("logo", ""),
                    "type": st.session_state.input_mode,
                    "timestamp": datetime.now().strftime("%H:%M · %b %d"),
                }
                st.session_state.last_analysis = entry
                st.session_state.last_meme = None
                add_archive(entry.copy())
            except Exception as e:
                print(f"ERROR: Analysis failed: {e}")
                st.error(f"❌ Analysis failed: {e}")
    if st.session_state.last_analysis:
        render_result(st.session_state.last_analysis, savage_mode)
elif nav == "⚔️ COMPARE":
    st.markdown(
        '<div class="page-title">Comparative <span>Analysis</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="page-sub">Compare two apps and find out which one treats your privacy like a clearance sale.</div>',
        unsafe_allow_html=True,
    )
    if not get_api_key():
        st.warning(
            "⚠️ API key missing. Configure it in Streamlit Secrets before running comparison."
        )
    with st.container(border=True):
        cA, cBtn, cB = st.columns([4, 2, 4])
        with cA:
            st.markdown(
                '<div style="font-size:11px;color:#8b949e;font-weight:900;letter-spacing:1px;margin-bottom:6px;">TARGET ALPHA</div>',
                unsafe_allow_html=True,
            )
            inputA = st.text_area(
                "app_a",
                placeholder="Paste a URL OR full Terms/Privacy text for app A",
                label_visibility="collapsed",
                height=145,
            )
        with cBtn:
            st.markdown("<br><br>", unsafe_allow_html=True)
            compare_btn = st.button("⚔️ COMPARE", use_container_width=True)
        with cB:
            st.markdown(
                '<div style="font-size:11px;color:#8b949e;font-weight:900;letter-spacing:1px;margin-bottom:6px;">TARGET BETA</div>',
                unsafe_allow_html=True,
            )
            inputB = st.text_area(
                "app_b",
                placeholder="Paste a URL OR full Terms/Privacy text for app B",
                label_visibility="collapsed",
                height=145,
            )
    if compare_btn:
        if not get_api_key():
            st.error("❌ API key missing. Configure it in Streamlit Secrets.")
            st.stop()
        if not check_rate_limit():
            st.error("⚠️ Slow down! You've reached the limit (5 per 10 mins).")
            st.stop()
        if not inputA.strip() or not inputB.strip():
            st.warning("⚠️ Please provide both targets before comparing.")
        else:
            try:
                valA = inputA.strip()
                valB = inputB.strip()
                is_url_a = bool(
                    urlparse(valA).scheme
                    or ("." in valA and "/" not in valA.split(".")[0])
                )
                is_url_b = bool(
                    urlparse(valB).scheme
                    or ("." in valB and "/" not in valB.split(".")[0])
                )
                metaA = (
                    get_company_meta_from_url(valA)
                    if is_url_a
                    else {"name": "Target Alpha", "domain": "", "logo": ""}
                )
                metaB = (
                    get_company_meta_from_url(valB)
                    if is_url_b
                    else {"name": "Target Beta", "domain": "", "logo": ""}
                )
                with st.spinner(
                    f"Fetching {metaA['name']}..."
                    if is_url_a
                    else "Reading Target Alpha..."
                ):
                    textA = extract_from_url(valA) if is_url_a else valA
                with st.spinner(
                    f"Fetching {metaB['name']}..."
                    if is_url_b
                    else "Reading Target Beta..."
                ):
                    textB = extract_from_url(valB) if is_url_b else valB
                if not textA or not textB:
                    st.error("❌ Could not fetch or read one of the targets.")
                elif len(textA.strip()) < 100 or len(textB.strip()) < 100:
                    st.warning(
                        "⚠️ One target has too little text. Use a real policy URL or paste more text."
                    )
                else:
                    with st.spinner(
                        "🔥 Calculating who is legally more unhinged..."
                        if savage_mode
                        else "Calculating threat delta..."
                    ):
                        resA = analyze_legal(textA, is_compare=True, savage=savage_mode)
                        resB = analyze_legal(textB, is_compare=True, savage=savage_mode)
                    st.session_state.last_compare = {
                        "metaA": metaA,
                        "metaB": metaB,
                        "resA": resA,
                        "resB": resB,
                    }
                    for meta, res in [(metaA, resA), (metaB, resB)]:
                        add_archive(
                            {
                                "data": res,
                                "company": meta["name"],
                                "logo": meta.get("logo", ""),
                                "type": "Compare",
                                "timestamp": datetime.now().strftime("%H:%M · %b %d"),
                            }
                        )
            except Exception as e:
                print(f"ERROR: Comparison failed: {e}")
                st.error(f"❌ Comparison failed: {e}")
    if st.session_state.last_compare:
        render_compare_results(st.session_state.last_compare, savage_mode)
elif nav == "🗂️ ARCHIVES":
    st.markdown(
        '<div class="page-title">Scan <span>Archives</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="page-sub">Your session history, because some legal disasters deserve receipts.</div>',
        unsafe_allow_html=True,
    )
    if not st.session_state.archives:
        st.markdown(
            """
<div style="text-align:center;padding:80px 20px;color:#484f58;">
    <div style="font-size:64px;margin-bottom:20px;">🗂️</div>
    <div style="font-size:20px;font-weight:900;margin-bottom:10px;color:#30363d;">No archives yet</div>
    <div style="font-size:14px;font-weight:600;">Run an analysis or comparison to populate archives.</div>
</div>
""",
            unsafe_allow_html=True,
        )
    else:
        total = len(st.session_state.archives)
        critical_count = sum(
            1
            for a in st.session_state.archives
            if a["data"].get("rating") == "Critical"
        )
        avg_score = int(
            sum(
                safe_int(a["data"].get("risk_score", 0))
                for a in st.session_state.archives
            )
            / total
        )
        s1, s2, s3 = st.columns(3)
        stat_cards = [
            (s1, "TOTAL SCANS", total, "#FAFAFA"),
            (s2, "CRITICAL", critical_count, "#E11D48"),
            (s3, "AVG RISK SCORE", avg_score, "#EA580C"),
        ]
        for col, label, val, color in stat_cards:
            with col:
                st.markdown(
                    f"""
<div style="background:#18181B;border:1px solid #27272A;border-radius:16px;padding:22px;text-align:center;margin-bottom:20px;box-shadow:0 4px 10px rgba(0,0,0,0.2);">
    <div style="font-size:11px;color:#71717A;font-weight:800;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:8px;">{label}</div>
    <div style="font-size:42px;font-weight:900;color:{color};">{val}</div>
</div>
""",
                    unsafe_allow_html=True,
                )
        st.markdown(
            '<div class="section-title">📋 Scan History</div>',
            unsafe_allow_html=True,
        )
        for archive in st.session_state.archives:
            d = archive["data"]
            rating = d.get("rating", "Unknown")
            score = safe_int(d.get("risk_score", 0))
            company = archive.get("company", "Unknown")
            logo_url = archive.get("logo", "")
            summary = d.get("summary", "")
            timestamp = archive.get("timestamp", "")
            scan_type = archive.get("type", "Text")
            score_class = (
                "critical"
                if rating == "Critical"
                else ("risky" if rating == "Risky" else "safe")
            )
            logo_tag = logo_img_tag(logo_url, "cc-logo")
            if rating == "Critical":
                rating_style = "background:rgba(225,29,72,0.1);color:#E11D48;border:1px solid rgba(225,29,72,0.2);"
            elif rating == "Risky":
                rating_style = "background:rgba(234,88,12,0.1);color:#EA580C;border:1px solid rgba(234,88,12,0.2);"
            else:
                rating_style = "background:rgba(161,161,170,0.1);color:#A1A1AA;border:1px solid rgba(161,161,170,0.2);"
            st.markdown(
                f"""
<div class="archive-card">
    <div class="archive-score {score_class}">{score}</div>
    <div class="archive-meta">
        <div class="archive-company">{logo_tag} {esc(company)}</div>
        <div class="archive-summary">{esc(summary)}</div>
    </div>
    <div style="text-align:right;display:flex;flex-direction:column;align-items:flex-end;gap:8px;">
        <span class="archive-type">{esc(scan_type)}</span>
        <span class="archive-time">{esc(timestamp)}</span>
        <span style="padding:4px 10px;border-radius:5px;font-size:11px;font-weight:900;{rating_style}">
            {esc(str(rating).upper())}
        </span>
    </div>
</div>
""",
                unsafe_allow_html=True,
            )
            with st.expander(f"↳ View red flags for {company}", expanded=False):
                if d.get("savage_take"):
                    st.markdown(
                        f"""
<div class="savage-translation" style="margin-bottom:12px;">
    <div class="savage-translation-label">🔥 Savage Verdict</div>
    <div class="savage-translation-text">{esc(d.get("savage_take"))}</div>
</div>
""",
                        unsafe_allow_html=True,
                    )
                for flag in d.get("red_flags", []):
                    sev = flag.get("severity", "")
                    worst = flag.get("worst_case", "")
                    savage = flag.get("savage_explanation", "")
                    st.markdown(
                        f"""
<div class="log-item" style="margin-bottom:8px;">
    <span>🚩</span>
    <div>
        <b style="color:#FAFAFA;">{esc(flag.get("title", "Flag"))}</b>
        {f'<span style="font-size:11px;color:#E11D48;margin-left:8px;font-weight:800;">{esc(sev)}</span>' if sev else ""}
        <br>{esc(flag.get("meaning", ""))}
        {f'<div class="log-wc">💀 {esc(worst)}</div>' if worst else ""}
        {f'<div class="log-wc">🔥 {esc(savage)}</div>' if savage else ""}
    </div>
</div>
""",
                        unsafe_allow_html=True,
                    )
