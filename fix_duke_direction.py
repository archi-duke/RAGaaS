import requests
import json

FUSEKI_URL = "http://localhost:3030"
AUTH = ("admin", "admin")
KB_ID = "d2980afe_3238_4d34_854d_400bb3937bb9"
DS_NAME = f"/kb_{KB_ID}"

def fix_graph():
    url = f"{FUSEKI_URL}{DS_NAME}/update"
    
    # 1. Delete the inverted triple
    # 2. Insert the correct triple
    # Do this in all graphs (UnionGraph doesn't work for DELETE, must target graphs or use DELETE WHERE)
    
    update_query = """
    PREFIX rel: <http://rag.local/rel/>
    PREFIX inst: <http://rag.local/inst/>
    
    DELETE {
      GRAPH ?g {
        inst:Duke rel:제자 inst:오일남 .
      }
    }
    INSERT {
      GRAPH ?g {
        inst:오일남 rel:제자 inst:Duke .
      }
    }
    WHERE {
      GRAPH ?g {
        inst:Duke rel:제자 inst:오일남 .
      }
    }
    """
    try:
        resp = requests.post(url, data={"update": update_query}, auth=AUTH)
        resp.raise_for_status()
        print("Successfully flipped Duke-Oh relationship in all graphs.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    fix_graph()
