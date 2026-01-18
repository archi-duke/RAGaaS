from fastapi import APIRouter, HTTPException, Query, Depends
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from app.core.neo4j_client import neo4j_client
from app.core.fuseki import fuseki_client
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
        FROM <urn:x-arq:UnionGraph>
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

@router.get("/schema", response_model=GraphData)
async def get_schema(
    kb_id: str,
    backend: str = "ontology"
):
    """
    Retrieve ontology schema (classes and their relationships) for visualization.
    Only supports ontology (Fuseki) backend.
    """
    print(f"Fetching schema for KB: {kb_id} on backend: {backend}")
    
    if backend != "ontology":
        raise HTTPException(status_code=400, detail="Schema view only supported for ontology backend")
    
    nodes = {}
    links = []
    
    # Named Graph URI for promoted ontology schema
    graph_uri = f"urn:ontology:{kb_id}"
    
    # SPARQL query to get classes and their relationships from Named Graph
    sparql = f"""
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    
    SELECT DISTINCT ?class ?classLabel ?relType ?relatedClass ?relatedLabel ?propLabel
    WHERE {{
      GRAPH <{graph_uri}> {{
        # Get all classes
        ?class a owl:Class .
        OPTIONAL {{ ?class rdfs:label ?classLabel }}
        
        # Get relationships between classes
        OPTIONAL {{
          {{
            # Subclass relationships
            ?class rdfs:subClassOf ?relatedClass .
            FILTER (!isBlank(?relatedClass))
            BIND("subClassOf" AS ?relType)
          }}
          UNION
          {{
            # Property domain/range relationships
            ?prop rdfs:domain ?class ;
                  rdfs:range ?relatedClass .
            FILTER (!isBlank(?relatedClass))
            ?relatedClass a owl:Class .
            OPTIONAL {{ ?prop rdfs:label ?propLabel }}
            BIND(COALESCE(?propLabel, STRAFTER(STR(?prop), "#"), STRAFTER(STR(?prop), "/")) AS ?relType)
          }}
        }}
        
        OPTIONAL {{ ?relatedClass rdfs:label ?relatedLabel }}
        
        # Filter out blank nodes and generic top-level classes
        FILTER (!isBlank(?class))
        FILTER (?class != owl:Thing && ?class != owl:Class && ?class != rdfs:Resource)
      }}
    }}
    LIMIT 100
    """
    
    try:
        results = fuseki_client.query_sparql(kb_id, sparql)
        bindings = results.get("results", {}).get("bindings", [])
        
        if not bindings:
            print("No OWL classes found, attempting fallback to raw predicates...")
            # Fallback: Query for distinct predicates and check if object is literal
            fallback_sparql = """
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT DISTINCT ?p ?label (SAMPLE(isLiteral(?o)) as ?isLit) WHERE {
              ?s ?p ?o .
              OPTIONAL { ?p rdfs:label ?label }
            } GROUP BY ?p ?label LIMIT 100
            """
            fb_results = fuseki_client.query_sparql(kb_id, fallback_sparql)
            fb_bindings = fb_results.get("results", {}).get("bindings", [])
            
            if fb_bindings:
                # Create base nodes
                nodes["Entity"] = GraphNode(id="Entity", label="Entity", group="Class")
                nodes["Literal"] = GraphNode(id="Literal", label="Literal (Value)", group="Class")
                
                # We can differentiate colors in frontend if group is different, but for now both Class
                # Let's verify existing frontend logic: if group=='Class' -> Orange.
                
                for b in fb_bindings:
                    p_uri = b["p"]["value"]
                    p_label = b.get("label", {}).get("value")
                    if not p_label:
                        p_label = urllib.parse.unquote(p_uri.split("/")[-1].split("#")[-1]).replace("_", " ")
                    
                    is_lit = b.get("isLit", {}).get("value") == "true"
                    
                    target_id = "Literal" if is_lit else "Entity"
                    
                    # For Entity->Entity, source=Entity, target=Entity (Self loop visual)
                    # For Entity->Literal, source=Entity, target=Literal
                    
                    links.append(GraphLink(
                        source="Entity",
                        target=target_id,
                        label=p_label
                    ))
            
            
        else:
            # First pass: Collect all valid owl:Class URIs
            valid_class_uris = set()
            for b in bindings:
                class_uri = b["class"]["value"]
                valid_class_uris.add(class_uri)
            
            print(f"[Schema] Found {len(valid_class_uris)} valid owl:Class definitions")
            
            # Second pass: Build nodes and links
            for b in bindings:
                # Process class node
                class_uri = b["class"]["value"]
                class_label = b.get("classLabel", {}).get("value")
                if not class_label:
                    class_label = urllib.parse.unquote(class_uri.split("/")[-1].split("#")[-1]).replace("_", " ")
                
                if class_uri not in nodes:
                    nodes[class_uri] = GraphNode(
                        id=class_uri,
                        label=class_label,
                        group="Class",
                        properties={"uri": class_uri}
                    )
                
                # Process relationship if exists - only if related class is also a valid owl:Class
                if "relatedClass" in b and b.get("relatedClass"):
                    related_uri = b["relatedClass"]["value"]
                    
                    # Skip if related class is not a valid owl:Class
                    if related_uri not in valid_class_uris:
                        continue
                    
                    related_label = b.get("relatedLabel", {}).get("value")
                    if not related_label:
                        related_label = urllib.parse.unquote(related_uri.split("/")[-1].split("#")[-1]).replace("_", " ")
                    
                    if related_uri not in nodes:
                        nodes[related_uri] = GraphNode(
                            id=related_uri,
                            label=related_label,
                            group="Class",
                            properties={"uri": related_uri}
                        )
                    
                    # Add link (skip self-referencing links like A subClassOf A)
                    if class_uri == related_uri:
                        continue
                    rel_type = b.get("relType", {}).get("value", "related")
                    links.append(GraphLink(
                        source=class_uri,
                        target=related_uri,
                        label=rel_type
                    ))
        
        print(f"Schema query returned {len(nodes)} classes and {len(links)} relationships")
        
    except Exception as e:
        print(f"Fuseki schema query error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
    return GraphData(nodes=list(nodes.values()), links=links)


@router.get("/schema/instances", response_model=GraphData)
async def get_class_instances(
    kb_id: str,
    class_uri: str,
    limit: int = 20
):
    """Get instances of a class for schema viewer expansion."""
    print(f"[Schema] Fetching instances for class: {class_uri}")
    
    nodes = {}
    links = []
    
    try:
        dataset = f"kb_{kb_id.replace('-', '_')}"
        query_url = f"{fuseki_client.base_url}/{dataset}/query"
        
        # Query for instances of this class (Must query the Named Graph)
        graph_uri = f"urn:ontology:{kb_id}"
        sparql_query = f"""
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?instance ?label WHERE {{
            GRAPH <{graph_uri}> {{
                ?instance rdf:type <{class_uri}> .
                OPTIONAL {{ ?instance rdfs:label ?label }}
                FILTER (!isBlank(?instance))
            }}
        }}
        LIMIT {limit}
        """
        
        import requests
        response = requests.post(
            query_url,
            data={'query': sparql_query},
            headers={'Accept': 'application/sparql-results+json'},
            auth=fuseki_client.auth,
            timeout=30
        )
        
        if response.status_code != 200:
            print(f"[Schema] Instance query failed: {response.status_code}")
            return GraphData(nodes=[], links=[])
        
        bindings = response.json().get("results", {}).get("bindings", [])
        
        # Add class node first
        class_label = urllib.parse.unquote(class_uri.split("/")[-1].split("#")[-1]).replace("_", " ")
        nodes[class_uri] = GraphNode(
            id=class_uri,
            label=class_label,
            group="Class",
            properties={"uri": class_uri}
        )
        
        # Add instance nodes
        for b in bindings:
            inst_uri = b["instance"]["value"]
            inst_label = b.get("label", {}).get("value")
            if not inst_label:
                inst_label = urllib.parse.unquote(inst_uri.split("/")[-1].split("#")[-1]).replace("_", " ")
            
            nodes[inst_uri] = GraphNode(
                id=inst_uri,
                label=inst_label,
                group="Instance",  # Mark as Instance for different coloring
                properties={"uri": inst_uri}
            )
            
            # Link instance to class
            links.append(GraphLink(
                source=inst_uri,
                target=class_uri,
                label="rdf:type"
            ))
        
        print(f"[Schema] Found {len(bindings)} instances for class {class_label}")
        
    except Exception as e:
        print(f"[Schema] Instance query error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
    return GraphData(nodes=list(nodes.values()), links=links)
