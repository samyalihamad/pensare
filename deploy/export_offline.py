#!/usr/bin/env python3
"""Export a pensare study project to a self-contained OFFLINE bundle.

Renders every markdown doc (concepts/, explanations/, kb/) to static HTML, rewrites
internal doc links to local files, bundles highlight.js locally, and builds an index.html
organized by the DSA roadmap. Open <out>/index.html from file:// — no network needed.

Usage:  python3 export_offline.py --project interview-prep --out ~/interview-prep-offline
"""
import argparse, os, re, subprocess, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(os.path.dirname(HERE), "lib")
sys.path.insert(0, LIB)
import lambda_handler as LH  # noqa: E402  (_md_to_html lives here)

STORAGE = os.path.join(LIB, "storage.py")
HLJS_JS = "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"
HLJS_CSS = "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css"

# DSA roadmap order (topic, short) for grouping the index.
ROADMAP = [
 "Arrays & Hashing","Two Pointers","Stack","Math & Geometry","Bit Manipulation",
 "Binary Search","Sliding Window","Linked List","Trees","Tries","Heap / Priority Queue",
 "Backtracking","Graphs","1-D Dynamic Programming","Advanced Graphs","2-D Dynamic Programming",
 "Greedy","Intervals",
]

def sh(project, *args):
    return subprocess.run(["python3", STORAGE, "--project", project, *args],
                          capture_output=True, text=True)

def dump(project, prefix):
    """Return {key: content} for all *.md under prefix (recursive)."""
    out = sh(project, "dump", "--prefix", prefix, "--glob", "*.md").stdout
    docs, cur, buf = {}, None, []
    for line in out.split("\n"):
        m = re.match(r"^===== PENSARE-FILE: (.+?) =====$", line)
        if m:
            if cur is not None:
                docs[cur] = "\n".join(buf)
            cur, buf = m.group(1), []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        docs[cur] = "\n".join(buf)
    return docs

def flat(key):  # concepts/dsa/x.md -> concepts__dsa__x.html
    return key.replace("/", "__")[:-3] + ".html"

def parse_fm(md):
    if not md.startswith("---"):
        return {}
    end = md.find("\n---", 3)
    fm = {}
    for ln in md[3:end].split("\n"):
        if ":" in ln:
            k, _, v = ln.partition(":")
            fm[k.strip()] = v.strip().strip('"')
    return fm

def doc_key_from_url(url):
    m = re.search(r"key=([^&\"]+\.md)", url or "")
    return m.group(1) if m else None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = os.path.expanduser(a.out)
    os.makedirs(os.path.join(out, "assets"), exist_ok=True)

    # 1) download highlight.js assets locally (needs internet NOW)
    for url, name in [(HLJS_JS, "highlight.min.js"), (HLJS_CSS, "hljs.css")]:
        try:
            urllib.request.urlretrieve(url, os.path.join(out, "assets", name))
        except Exception as e:
            print(f"  warn: could not fetch {name}: {e}")

    # 2) gather all docs. The storage dump is not recursive across sub-prefixes,
    # so enumerate each directory explicitly.
    docs = {}
    for pre in ("concepts", "concepts/dsa", "concepts/build", "concepts/python",
                "explanations", "kb", "coding-prep/programming-concepts",
                "coding-prep/problems/anthropic", "inference-eval"):
        docs.update(dump(a.project, pre))
    print(f"docs: {len(docs)}")

    # 3) render each to static HTML (rewrite links + hljs to local)
    def localize(html):
        # internal doc links -> local flat html
        html = re.sub(r'href="https?://[^"]*?/doc\?[^"]*?key=([^"&]+\.md)[^"]*"',
                      lambda m: f'href="{flat(m.group(1))}"', html)
        # hljs CDN -> local assets
        html = html.replace(HLJS_CSS, "assets/hljs.css").replace(HLJS_JS, "assets/highlight.min.js")
        # drop the light-theme CDN link entirely (we only bundle dark)
        html = re.sub(r'<link rel="stylesheet" media="\(prefers-color-scheme: light\)"[^>]*>', "", html)
        return html

    for key, md in docs.items():
        title = key.rsplit("/", 1)[-1][:-3].replace("-", " ").title()
        html = LH._md_to_html(md, title=title, back_href="index.html")
        html = localize(html)
        open(os.path.join(out, flat(key)), "w").write(html)

    # 4) read board items -> group lessons/problems by topic
    items = {}
    for key, md in dump(a.project, "kanban/items").items():
        fm = parse_fm(md)
        if fm.get("id"):
            items[fm["id"]] = fm
    concepts_by_topic, probs_by_topic = {}, {}
    for it in items.values():
        t = it.get("topic")
        if not t:
            continue
        cat = it.get("category", "")
        if cat == "Concept":
            concepts_by_topic.setdefault(t, []).append(it)
        elif cat != "Build":
            probs_by_topic.setdefault(t, []).append(it)

    # 5) build index.html
    def esc(s): return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    def lesson_link(it):
        k = doc_key_from_url(it.get("doc"))
        href = flat(k) if k and k in docs else None
        return f'<a href="{href}">{esc(it.get("title"))}</a>' if href else esc(it.get("title"))
    def prob_link(it):
        bits = [esc(it.get("title"))]
        k = doc_key_from_url(it.get("doc"))
        if k and k in docs:
            bits.append(f'<a href="{flat(k)}">doc</a>')
        if it.get("leetcode"):
            bits.append(f'<a href="{esc(it["leetcode"])}">LeetCode↗</a>')
        tech = it.get("techniques", "")
        chips = "".join(f'<span class="t">{esc(x.strip())}</span>'
                        for x in tech.strip("[]").split(",") if x.strip())
        return f'<li>{bits[0]} <span class="lnk">{" · ".join(bits[1:])}</span> {chips}</li>'

    sections = []
    # study method first
    for special in ("concepts/learning-path.md",):
        if special in docs:
            sections.append(f'<p class="lead"><a href="{flat(special)}">▶ Start here: Learning Path (how to study)</a></p>')
    for t in ROADMAP:
        cs = concepts_by_topic.get(t, []); ps = sorted(probs_by_topic.get(t, []), key=lambda x: x.get("id", ""))
        lessons = " · ".join(lesson_link(c) for c in cs) or "<i>no lesson</i>"
        plis = "".join(prob_link(p) for p in ps) or "<li><i>no problems</i></li>"
        sections.append(f'<section><h2>{esc(t)}</h2><p class="les">Lessons: {lessons}</p><ul>{plis}</ul></section>')
    # python + other concept docs not tied to a roadmap topic
    pyc = [it for it in items.values() if it.get("category") == "Concept" and str(it.get("topic","")).startswith("Python")]
    if pyc:
        links = " · ".join(lesson_link(c) for c in sorted(pyc, key=lambda x: x.get("id","")))
        sections.append(f'<section><h2>Python</h2><p class="les">{links}</p></section>')

    css = """body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:900px;margin:0 auto;padding:2rem 1.2rem;background:#0d1117;color:#c9d1d9;line-height:1.5}
h1{color:#e6edf3}h2{color:#58a6ff;border-bottom:1px solid #21262d;padding-bottom:.2rem;margin-top:1.8rem}
a{color:#58a6ff;text-decoration:none}a:hover{text-decoration:underline}
.lead a{font-size:1.05rem;font-weight:600;color:#bc8cff}
.les{color:#8b949e;font-size:.95rem}ul{list-style:none;padding-left:0}
li{padding:5px 0;border-top:1px solid #161b22}.lnk{font-size:.85rem;color:#7d8590}
.t{display:inline-block;font-size:.7rem;color:#3fb98a;background:#10231c;border:1px solid #1c3d31;border-radius:9px;padding:1px 7px;margin-left:4px}"""
    index = (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
             f'<meta name="viewport" content="width=device-width, initial-scale=1">'
             f'<title>Interview Prep — Offline</title><style>{css}</style></head><body>'
             f'<h1>Interview Prep — offline study</h1>'
             f'<p class="les">{len(docs)} lessons/docs · self-contained · works without internet '
             f'(LeetCode links need a connection).</p>'
             + "".join(sections) + '</body></html>')
    open(os.path.join(out, "index.html"), "w").write(index)
    print(f"wrote {len(docs)} doc pages + index.html to {out}")

if __name__ == "__main__":
    main()
