#!/usr/bin/env python3
"""Build the subVI call tree of a LabVIEW folder using pylabview (readRSRC -x).

usage: vi_calltree.py <vi folder> <work dir> > calltree.txt
Each VI is extracted into <work dir>/<name>/ and its LIvi link list (subVIs,
typedef controls) is read from the XML.  Diagram logic is NOT available for
LabVIEW 6.1 files (pylabview cannot parse those heaps), only the links.
"""
import os, re, subprocess, sys, shutil
import xml.etree.ElementTree as ET

src, work = sys.argv[1], sys.argv[2]
os.makedirs(work, exist_ok=True)
calls = {}
TEXTS = {}
for name in sorted(os.listdir(src)):
    if not name.lower().endswith((".vi", ".ctl")):
        continue
    d = os.path.join(work, re.sub(r"[^A-Za-z0-9_.-]", "_", name))
    os.makedirs(d, exist_ok=True)
    local = os.path.join(d, "x.vi")
    shutil.copyfile(os.path.join(src, name), local)
    r = subprocess.run(["readRSRC", "-i", "x.vi", "-x"], capture_output=True, text=True, cwd=d)
    xml = os.path.join(d, "x.xml")
    links = []
    title = ""
    if os.path.exists(xml):
        try:
            t = ET.parse(xml).getroot()
            for sec in t.iter("LVIN"):
                q = sec.find("LinkSaveQualName/String")
                if q is not None and q.text and q.text != name:
                    links.append(("vi", q.text))
            for sec in t.iter("LVCC"):
                q = sec.find("LinkSaveQualName/String")
                if q is not None and q.text:
                    links.append(("ctl", q.text))
            ti = t.find("TITL/Section/String")
            if ti is not None and ti.text:
                title = ti.text
        except ET.ParseError as e:
            links.append(("err", str(e)))
    else:
        links.append(("err", (r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout) else "no xml"))
    texts = []
    import glob
    for tf in sorted(glob.glob(os.path.join(d, "x_TRec*.bin")), key=lambda q: int((re.search(r"TRec(\d+)", os.path.basename(q)) or [0, "0"])[1])):
        b = open(tf, "rb").read()
        if len(b) > 0x4c:
            n = b[0x4b]
            txt = b[0x4c:0x4c + n].decode("latin-1", "replace").strip()
            if txt:
                texts.append(txt)
    TEXTS[name] = texts
    seen = []
    for l in links:
        if l not in seen:
            seen.append(l)
    calls[name] = (title, seen)

with open(sys.argv[3] if len(sys.argv) > 3 else os.devnull, "w") as tf:
    for name, texts in TEXTS.items():
        tf.write("==== %s\n" % name)
        for t in texts:
            tf.write("  %s\n" % t.replace("\r", "\n").replace("\n", "\n    "))
for name, (title, links) in calls.items():
    print("%s%s" % (name, ("   [title: %s]" % title) if title and title != name else ""))
    for kind, l in links:
        print("    %s  %s" % (kind, l))
# reverse index: who calls whom
print("\n==== called by ====")
rev = {}
for name, (_, links) in calls.items():
    for kind, l in links:
        if kind == "vi":
            rev.setdefault(l, []).append(name)
for l in sorted(rev):
    print("%s  <-  %s" % (l, ", ".join(sorted(rev[l]))))
