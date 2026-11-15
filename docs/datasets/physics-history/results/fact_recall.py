import json, re, urllib.parse
from collections import Counter
from app.core.fuseki import fuseki_client as F
KB="921358f2-81ab-4b4c-98f8-19f7678564fd"
rows=F.query_sparql(KB,'''SELECT ?s ?p ?o ?sl ?ol WHERE { GRAPH ?g { ?s ?p ?o
 OPTIONAL { ?s <http://www.w3.org/2000/01/rdf-schema#label> ?sl } OPTIONAL { ?o <http://www.w3.org/2000/01/rdf-schema#label> ?ol } }
 FILTER(STRSTARTS(STR(?g),"urn:doc:")) FILTER(STRSTARTS(STR(?p),"http://rag.local/rel/")) FILTER(!CONTAINS(STR(?p),"/inverse_")) } LIMIT 50000''')["results"]["bindings"]
def loc(u): return urllib.parse.unquote(u.rsplit("/",1)[-1])
def c(x): return re.sub(r"[\s_『』「」()（）·\-.,']","",x or "").lower()
T=[(c((b.get("sl") or {}).get("value") or loc(b["s"]["value"])), loc(b["p"]["value"]), c((b.get("ol") or {}).get("value") or loc(b["o"]["value"]))) for b in rows]
pc=Counter(p for _,p,_ in T)
facts=json.load(open("/tmp/facts.json"))["facts"]
def m(a,b): return a and b and (a==b or (len(a)>=2 and a in b) or (len(b)>=2 and b in a))
exact=loose=0; byrel=Counter(); hit=Counter()
for f in facts:
    s,o,r=c(f["subject"]),c(f["object"]),f["relation"]
    byrel[r]+=1
    if any(p==r and m(s,ts) and m(o,to) for ts,p,to in T): exact+=1; hit[r]+=1
    elif any(m(s,ts) and m(o,to) for ts,p,to in T) or any(m(s,to) and m(o,ts) for ts,p,to in T): loose+=1
print("facts",len(facts),"정확(관계까지 일치)",exact,"쌍만 연결(관계 다름/역방향)",loose)
print({r:f"{hit[r]}/{n}" for r,n in byrel.most_common()})
print("상위 관계",pc.most_common(22))
