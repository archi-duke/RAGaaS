import requests
from requests.auth import HTTPBasicAuth

KB_ID = "fe5ef020-a2f7-425d-883d-5f8982c6320c"
DATASET_NAME = f"kb_{KB_ID.replace('-', '_')}"
FUSEKI_BASE_URL = "http://localhost:3030"
GRAPH_URI = f"urn:ontology:{KB_ID}"
OWL_FILE = "/Users/dukekimm/Works/RAGaaS/backend/doc2onto_out/fe5ef020-a2f7-425d-883d-5f8982c6320c/promotion/ontology_v1.0.owl"

def upload_to_fuseki():
    url = f"{FUSEKI_BASE_URL}/{DATASET_NAME}/data?graph={GRAPH_URI}"
    
    with open(OWL_FILE, "rb") as f:
        data = f.read()
    
    response = requests.post(
        url,
        data=data,
        headers={"Content-Type": "application/rdf+xml"},
        auth=HTTPBasicAuth("admin", "admin"),
        timeout=60
    )
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text[:500]}")
    
    if response.status_code in [200, 201, 204]:
        print("SUCCESS: OWL file uploaded to Fuseki!")
    else:
        print("FAILED: Could not upload OWL file.")

if __name__ == "__main__":
    print(f"Uploading {OWL_FILE}")
    print(f"To Named Graph: {GRAPH_URI}")
    upload_to_fuseki()
