from fastapi import APIRouter, HTTPException, Query, Depends
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from app.core.neo4j_client import neo4j_client
from app.core.fuseki import fuseki_client
from app.core.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
import urllib.parse

router = APIRouter()

class GraphNode(BaseModel):
    id: str
    label: str
    group: str  # Entity, Chunk, etc.
    properties: Dict[str, Any] = {}

class GraphLink(BaseModel):
    source: str
    target: str
    label: str
    properties: Dict[str, Any] = {}

class GraphData(BaseModel):
    nodes: List[GraphNode]
    links: List[GraphLink]

@router.get("/expand", response_model=GraphData)
async def expand_graph(
    kb_id: str,
    entity: str,
    backend: str = "neo4j",
    hops: int = 1
):
    print(f"Expanding graph for entity: {entity} on backend: {backend} (KB: {kb_id})")
    
    nodes = {}
    links = []
    
    # Normalize entity
    entity = entity.strip()
    
    if backend == "neo4j":
        # ... (Neo4j code remains) ...
        query = """
        MATCH (n)-[r]-(m)
        WHERE n.label_ko = $entity OR n.name = $entity 
        RETURN n, r, m, startNode(r) as startNode, endNode(r) as endNode, type(r) as rel_type
        LIMIT 50
        """
        try:
            records = neo4j_client.execute_query(query, {"entity": entity})
            
            for record in records:
                n = record["n"]
                m = record["m"]
                r = record["r"]
                rel_type = record["rel_type"]
                
                # Process Node N (Center)
                n_props = dict(n)
                n_id = n_props.get("name") or n_props.get("label_ko") or str(n.id)
                # Label Logic: Check specific properties based on type
                if "Chunk" in n.labels:
                     n_label = n_props.get("id") or f"Chunk {n.element_id}"
                else:
                     n_label = n_props.get("label_ko") or n_props.get("name") or "Unknown"
                
                n_group = list(n.labels)[0] if n.labels else "Entity"
                
                if n_id not in nodes:
                    nodes[n_id] = GraphNode(id=n_id, label=n_label, group=n_group, properties=n_props)
                
                # Process Node M (Neighbor)
                m_props = dict(m)
                m_id = m_props.get("name") or m_props.get("label_ko") or str(m.id)
                # Label Logic for neighbor M
                if "Chunk" in m.labels:
                     m_label = m_props.get("id") or f"Chunk {m.element_id}"
                else:
                     m_label = m_props.get("label_ko") or m_props.get("name") or "Unknown"
                m_group = list(m.labels)[0] if m.labels else "Entity"
                
                if m_id not in nodes:
                    nodes[m_id] = GraphNode(id=m_id, label=m_label, group=m_group, properties=m_props)
                
                # Process Link
                # Use Start/End Node IDs from the relationship to ensure correct direction
                start_node_props = dict(record["startNode"])
                end_node_props = dict(record["endNode"])
                
                # Determine IDs for Source/Target based on same logic as Node creation
                # Note: We must match the ID generation logic used above strictly.
                src_id = start_node_props.get("name") or start_node_props.get("label_ko") or str(record["startNode"].id)
                tgt_id = end_node_props.get("name") or end_node_props.get("label_ko") or str(record["endNode"].id)
                
                # Use relationship type or 'label' property
                r_label = dict(r).get("label") or rel_type 

                links.append(GraphLink(
                    source=src_id,
                    target=tgt_id,
                    label=r_label,
                    properties=dict(r)
                ))

        except Exception as e:
            print(f"Neo4j expansion error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    elif backend == "ontology":
        # Fuseki Query
        sparql = f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT DISTINCT ?s ?p ?o ?sLabel ?oLabel
        WHERE {{
            {{ 
                ?s ?p ?o . 
                {{
                    ?s rdfs:label ?label . FILTER(CONTAINS(LCASE(str(?label)), LCASE("{entity}")))
                }} UNION {{
                    FILTER(CONTAINS(LCASE(str(?s)), LCASE("{entity}")))
                }}
            }}
            UNION
            {{ 
                ?s ?p ?o . 
                {{
                    ?o rdfs:label ?label . FILTER(CONTAINS(LCASE(str(?label)), LCASE("{entity}")))
                }} UNION {{
                    FILTER(CONTAINS(LCASE(str(?o)), LCASE("{entity}")))
                }}
            }}
            OPTIONAL {{ ?s rdfs:label ?sLabel }}
            OPTIONAL {{ ?o rdfs:label ?oLabel }}
            FILTER (!isLiteral(?o))
        }}
        LIMIT 50
        """
        try:
            results = fuseki_client.query_sparql(kb_id, sparql)
            bindings = results.get("results", {}).get("bindings", [])
            
            for b in bindings:
                s_uri = b["s"]["value"]
                o_uri = b["o"]["value"]
                p_uri = b["p"]["value"]
                
                s_label = b.get("sLabel", {}).get("value")
                if not s_label:
                    s_label = urllib.parse.unquote(s_uri.split("/")[-1]).replace("_", " ")
                
                o_label = b.get("oLabel", {}).get("value")
                if not o_label:
                    o_label = urllib.parse.unquote(o_uri.split("/")[-1]).replace("_", " ")
                
                p_label = urllib.parse.unquote(p_uri.split("/")[-1]).replace("_", " ")

                
                # Use label as ID for simplicity in visualization if unique enough, or URI
                # URI is safer.
                s_id = s_uri
                o_id = o_uri
                
                if s_id not in nodes:
                    nodes[s_id] = GraphNode(id=s_id, label=s_label, group="Entity")
                if o_id not in nodes:
                    nodes[o_id] = GraphNode(id=o_id, label=o_label, group="Entity")
                    
                links.append(GraphLink(source=s_id, target=o_id, label=p_label))
                
        except Exception as e:
             raise HTTPException(status_code=500, detail=str(e))

    return GraphData(nodes=list(nodes.values()), links=links)
