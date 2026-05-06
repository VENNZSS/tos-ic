```
┌──(Nishant Nahar@github)-[~/tos-ic]
└─$ cat README.md
```

# > TOS-IC

`# Terms of Service - Intelligence / Check)`

### `$ cat about.txt`

```
It is an AI-powered, savage legal scanner that analyzes Terms of Service (ToS) agreements, Privacy Policies, and other complex legal documents.
Built with Streamlit and the Gemini API, it cuts through the legal jargon to highlight the worst-case scenarios, generate satirical legal-tech threat memes, and tell you what you're actually agreeing to.
```

### `$ ls -la features/`

# 🚀 FEATURES

## Deep Legal Analysis

- Upload or paste legal texts, PDFs, or URLs
- Extracts and dissects Terms of Service and policies
- Identifies hidden clauses, liabilities, and rights concessions

## Savage Mode

- Blunt, unfiltered interpretation of agreements
- Highlights worst-case implications without legal sugarcoating
- Focus on what actually matters to the user

## Threat Meme Generation

- Auto-generates sarcastic warning memes/posters
- Formats: SVG / PNG
- Summarizes the most concerning clauses in a viral-ready format

## Document Support

- Raw text input
- URL scraping (via **BeautifulSoup**)
- PDF parsing (via **PyPDF**)

## Comparison Tool

- Compare:
  - Different versions of the same ToS
  - Policies across companies
- Highlights changes, regressions, and risk differences

## 🗺️ Upcoming Features (Roadmap)

- [ ] **Browser Extension:** Scan ToS directly while signing up on a website.
- [ ] **Dark Patterns Detector:** Identify tricky UI elements designed to mislead.
- [ ] **Multi-Language Support:** Scan legal documents in other languages.

---

# ⚙️ PREREQUISITES

Before running **TOS-IC**, ensure you have:

- **Python 3.8+**
- **Google Gemini API Key**

---

### `$ cat tech_stack.json`

<details>
<summary><b>💻 Languages</b> &nbsp;<sub>(1)</sub></summary>
<br/>

![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white)

</details>

<details>
<summary><b>🎨 Styling</b> &nbsp;<sub>(1)</sub></summary>
<br/>

![CSS](https://img.shields.io/badge/CSS-1572B6?style=flat-square&logo=css3&logoColor=white)

</details>

### `$ ./install.sh`

Installation
Clone the repository:

```bash
git clone https://github.com/yourusername/tos-ic.git
cd tos-ic
```

Set up a virtual environment (Recommended):

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

Install the dependencies:

```bash
pip install -r requirements.txt
```

Note: If meme generation image formats fail, ensure you have system-level dependencies for cairosvg installed (like libcairo2 on Linux).

Set up your Environment Variables: Create a .env file in the root directory and add your Gemini API Key:

```bash
GEMINI_API_KEY=your_gemini_api_key_here
```

### `$ ./run.sh`

Usage
Run the Streamlit application from your terminal:

```javascript
streamlit run app.py
```

The app will launch in your default web browser (usually at http://localhost:8501). From there, you can paste text, upload a PDF, or drop a URL to start scanning.

### `$ cat CONTRIBUTING.md`

Pull requests are welcome. For major changes, please open an issue first.

### `$ whoami`

**Nishant Nahar** — DEV_1
[!GitHub](https://github.com/Its-Nishant-10) [!LinkedIn](https://linkedin.com/in/nishantnahar2006) [!Email](mailto:nishantnahar2006@gmail.com) [!Website](https://portfolio-fawn-nine-frfcfpqjim.vercel.app/)

**VENNZSS** — DEV_2
[!GitHub](https://github.com/VENNZSS)

---

<div align="center">
  <a href="https://github.com/Its-Nishant-10" target="_blank">
    <img src="https://img.shields.io/badge/Follow_on_GitHub-181717?style=for-the-badge&logo=github&logoColor=white" alt="Follow on GitHub" />
  </a>
</div>
