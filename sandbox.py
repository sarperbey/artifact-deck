"""Turns a saved artifact into a locked-down HTML document. No GTK needed."""
import json
import os
import re

CSP = (
    "default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval'; "
    "style-src 'unsafe-inline'; img-src data: blob:; font-src data:; "
    "media-src data: blob:; connect-src 'none'; worker-src blob:; "
    "form-action 'none'; base-uri 'none'; frame-src 'none'"
)
CSP_META = '<meta http-equiv="Content-Security-Policy" content="%s">' % CSP

BRIDGE_JS = r"""
(function(){
  function ser(v){try{if(typeof v==="string")return v;if(v instanceof Error)return v.message;return JSON.stringify(v)}catch(e){return String(v)}}
  function send(l,m){try{window.webkit.messageHandlers.deck.postMessage(JSON.stringify({l:l,m:m}))}catch(e){}}
  ["log","info","warn","error"].forEach(function(k){
    var o=console[k].bind(console);
    console[k]=function(){send(k,[].slice.call(arguments).map(ser).join(" "));o.apply(null,arguments)};
  });
  addEventListener("error",function(e){send("error",(e.message||"Error")+(e.lineno?" @line "+e.lineno:""))});
  addEventListener("unhandledrejection",function(e){send("error","Unhandled rejection: "+ser(e.reason))});
  var ls=null,mem={},P="deck:";
  try{ls=window.localStorage;ls.getItem("x")}catch(e){ls=null}
  function G(k){return ls?ls.getItem(P+k):(k in mem?mem[k]:null)}
  function S(k,v){if(ls)ls.setItem(P+k,v);else mem[k]=v}
  function D(k){if(ls)ls.removeItem(P+k);else delete mem[k]}
  function K(){var r=[];if(ls){for(var i=0;i<ls.length;i++){var k=ls.key(i);if(k&&k.indexOf(P)===0)r.push(k.slice(P.length))}}else r=Object.keys(mem);return r}
  window.storage={
    get:function(k,s){return new Promise(function(res,rej){var v=G(k);if(v===null)rej(new Error("Key not found: "+k));else res({key:k,value:v,shared:!!s})})},
    set:function(k,v,s){return new Promise(function(res,rej){try{S(k,String(v));res({key:k,value:String(v),shared:!!s})}catch(e){rej(e)}})},
    delete:function(k,s){return new Promise(function(res){D(k);res({key:k,deleted:true,shared:!!s})})},
    list:function(p,s){return new Promise(function(res){var keys=K().filter(function(k){return !p||k.indexOf(p)===0});res({keys:keys,prefix:p,shared:!!s})})}
  };
  function needApi(){send("api","needs-api")}
  var of=window.fetch;
  window.fetch=function(u){
    var url=typeof u==="string"?u:(u&&u.url)||"";
    if(/anthropic\.com/i.test(url)){needApi();return Promise.reject(new Error("Claude API calls are not available in Artifact Deck"))}
    return of.apply(this,arguments);
  };
  window.claude={complete:function(){needApi();return Promise.reject(new Error("Claude API calls are not available in Artifact Deck"))}};
})();
"""

STUB_JS = (
    "window.__stub=function(mod){console.warn('Not available offline: '+mod);"
    "var C=function(p){return (p&&p.children)||null};"
    "return new Proxy({},{get:function(_,k){return k==='__esModule'?false:C}})};"
)

BASE_FILES = ["react.production.min.js", "react-dom.production.min.js", "babel.min.js"]

MODULES = {
    "react": ("React", []),
    "react-dom": ("ReactDOM", []),
    "lucide-react": ("LucideReact", ["lucide-react.min.js"]),
    "recharts": ("Recharts", ["prop-types.min.js", "Recharts.js"]),
    "lodash": ("_", ["lodash.min.js"]),
    "d3": ("d3", ["d3.min.js"]),
    "mathjs": ("math", ["math.js"]),
    "papaparse": ("Papa", ["papaparse.min.js"]),
}

IMPORT_RE = re.compile(
    r"^[ \t]*import\s+(?:([\w*{}\s,$]+?)\s+from\s+)?['\"]([^'\"]+)['\"][ \t]*;?[ \t]*\n?", re.M)

def esc_script(s):
    return re.sub(r"</(script)", r"<\/\1", s, flags=re.I)

def read_vendor(vendor_dir, name):
    try:
        with open(os.path.join(vendor_dir, name), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None

def inject_head(doc):
    # Always prepend CSP as safety net against comment/textarea/SVG bypass
    result = CSP_META + doc
    m = re.search(r"<head(?:\s[^>]*)?>", result, re.I)
    if m and m.start() > len(CSP_META):
        result = result[:m.end()] + CSP_META + result[m.end():]
    return result

def convert_import(clause, expr, skip_name):
    out = []
    clause = clause.strip()
    m = re.search(r"\{([^}]*)\}", clause)
    if m:
        names = []
        for part in m.group(1).split(","):
            part = part.strip()
            if not part: continue
            if re.search(r"\sas\s", part):
                a, b = [s.strip() for s in re.split(r"\sas\s", part, maxsplit=1)]
                names.append(a if a == b else "%s: %s" % (a, b))
            else:
                names.append(part)
        if names:
            out.append("const {%s} = %s;" % (", ".join(names), expr))
        clause = clause.replace(m.group(0), "")
    ns = re.search(r"\*\s+as\s+([\w$]+)", clause)
    if ns:
        if ns.group(1) != skip_name:
            out.append("const %s = %s;" % (ns.group(1), expr))
        clause = clause.replace(ns.group(0), "")
    default = clause.replace(",", "").strip()
    if default and default != skip_name:
        out.append("const %s = %s;" % (default, expr))
    return " ".join(out)

def prepare_react(code):
    extra, missing = [], []
    def repl(m):
        clause, mod = m.group(1), m.group(2)
        if not clause: return ""
        base = "react-dom" if mod.startswith("react-dom") else mod
        if base in MODULES:
            glob, files = MODULES[base]
            for f in files:
                if f not in extra: extra.append(f)
            return convert_import(clause, "window." + glob, glob) + "\n"
        missing.append(mod)
        return convert_import(clause, "window.__stub(%s)" % json.dumps(mod), None) + "\n"
    code = IMPORT_RE.sub(repl, code)
    name = "App"
    m = re.search(r"export\s+default\s+function\s+([A-Za-z_$][\w$]*)", code)
    if m:
        name = m.group(1); code = code.replace(m.group(0), "function " + name, 1)
    else:
        m = re.search(r"export\s+default\s+([A-Za-z_$][\w$]*)\s*;?\s*$", code, re.M)
        if m:
            name = m.group(1); code = code.replace(m.group(0), "", 1)
        else:
            code, n = re.subn(r"export\s+default\s+", "const __Default = ", code, count=1)
            if n: name = "__Default"
    code = re.sub(r"^\s*export\s+(?=(?:const|let|var|function|class)\b)", "", code, flags=re.M)
    code += ("\nReactDOM.createRoot(document.getElementById('root'))"
             ".render(React.createElement(%s));\n" % name)
    return code, extra, missing

def needed_files(type_, code):
    if type_ != "react": return []
    _code, extra, _missing = prepare_react(code)
    return BASE_FILES + extra

def detect_type(code, filename=""):
    ext = os.path.splitext(filename)[1].lower()
    full_html = re.search(r"<!doctype\s+html|<html[\s>]", code, re.I)
    if ext in (".jsx", ".tsx"): return "react"
    if not full_html and re.search(
            r"from\s+['\"]react['\"]|export\s+default|useState|<[A-Z][A-Za-z]*[\s/>]", code):
        return "react"
    if ext in (".html", ".htm") or re.search(
            r"<!doctype\s+html|<html[\s>]|<body[\s>]|<div[\s>]|<style[\s>]|<canvas[\s>]|<svg[\s>]",
            code, re.I):
        return "html"
    return "js"

def notice_page(text):
    safe = text.replace("&", "&amp;").replace("<", "&lt;")
    return ("<!DOCTYPE html><html><head><meta charset='utf-8'>" + CSP_META +
            "</head><body style='font-family:system-ui;padding:2rem;max-width:40rem'>"
            "<h3>Cannot run this artifact</h3><p>%s</p></body></html>" % safe)

def build_srcdoc(type_, code, vendor_dir):
    if type_ == "html":
        if re.search(r"<!doctype\s+html|<html[\s>]", code, re.I):
            return inject_head(code)
        return ("<!DOCTYPE html><html><head><meta charset='utf-8'>" + CSP_META +
                "</head><body>" + code + "</body></html>")
    head = "<!DOCTYPE html><html><head><meta charset='utf-8'>" + CSP_META + "</head>"
    if type_ == "js":
        return head + '<body><div id="app"></div><script>' + esc_script(code) + "</script></body></html>"
    code, extra, missing = prepare_react(code)
    libs = []
    for fname in BASE_FILES[:2] + extra + BASE_FILES[2:]:
        text = read_vendor(vendor_dir, fname)
        if text is None:
            return notice_page("Missing library file: " + fname)
        libs.append(text)
    warn = ""
    if missing:
        msg = json.dumps("Not available offline, these parts may be blank: " + ", ".join(missing))
        warn = "<script>console.warn(" + msg.replace("</", "</") + ")</script>"
    first = "<script>" + esc_script(libs[0]) + "</script><script>" + esc_script(libs[1]) + "</script>"
    alias = "<script>window.react=window.React;</script>"
    rest = "".join("<script>" + esc_script(t) + "</script>" for t in libs[2:])
    return (head + '<body><div id="root"></div>' + "<script>" + STUB_JS + "</script>" + warn +
            first + alias + rest +
            '<script type="text/babel" data-presets="react">' + esc_script(code) +
            "</script></body></html>")
