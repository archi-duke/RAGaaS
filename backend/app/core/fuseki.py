import requests
from requests.auth import HTTPBasicAuth
from SPARQLWrapper import SPARQLWrapper, JSON, POST
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

class FusekiClient:
    def __init__(self):
        self.base_url = settings.FUSEKI_URL
        # Default credentials for Fuseki (admin/admin)
        self.auth = HTTPBasicAuth("admin", "admin")
        
    def _get_dataset_url(self, kb_id: str) -> str:
        """Get the dataset URL for a specific knowledge base."""
        # Sanitize kb_id to be URL safe for Fuseki dataset name
        safe_name = f"kb_{kb_id.replace('-', '_')}"
        return f"{self.base_url}/{safe_name}"

    def create_dataset(self, kb_id: str) -> bool:
        """Create a new dataset in Fuseki for the knowledge base."""
        safe_name = f"kb_{kb_id.replace('-', '_')}"
        
        # Check if dataset exists
        try:
            check_url = f"{self.base_url}/$/datasets/{safe_name}"
            response = requests.get(check_url, auth=self.auth, timeout=5)
            if response.status_code == 200:
                logger.info(f"Dataset {safe_name} already exists.")
                return True
        except Exception as e:
            logger.warning(f"Failed to check dataset existence: {e}")

        # Create dataset
        create_url = f"{self.base_url}/$/datasets"
        payload = {
            "dbName": safe_name,
            "dbType": "tdb2"
        }
        
        try:
            response = requests.post(create_url, data=payload, auth=self.auth, timeout=10)
            if response.status_code == 200:
                logger.info(f"Created Fuseki dataset: {safe_name}")
                return True
            else:
                logger.error(f"Failed to create dataset {safe_name}: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error creating Fuseki dataset: {e}")
            return False

    def delete_dataset(self, kb_id: str) -> bool:
        """Delete the dataset for the knowledge base."""
        safe_name = f"kb_{kb_id.replace('-', '_')}"
        delete_url = f"{self.base_url}/$/datasets/{safe_name}"
        
        try:
            response = requests.delete(delete_url, auth=self.auth, timeout=10)
            if response.status_code == 200:
                logger.info(f"Deleted Fuseki dataset: {safe_name}")
                return True
            elif response.status_code == 404:
                return True # Already gone
            else:
                logger.error(f"Failed to delete dataset {safe_name}: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error deleting Fuseki dataset: {e}")
            return False

    def insert_triples(self, kb_id: str, triples: list[str]) -> bool:
        """
        Insert N-Triples formatted strings into the dataset.
        triples: List of strings like '<http://ex/s> <http://ex/p> <http://ex/o> .'
        """
        if not triples:
            return True
            
        dataset_url = self._get_dataset_url(kb_id)
        update_url = f"{dataset_url}/update"
        
        # Construct SPARQL INSERT DATA query
        # Breaking into chunks to avoid massive requests
        chunk_size = 100
        for i in range(0, len(triples), chunk_size):
            chunk = triples[i:i + chunk_size]
            triples_str = "\n".join(chunk)
            
            sparql_query = f"""
            INSERT DATA {{
                {triples_str}
            }}
            """
            
            try:
                # Use SPARQLWrapper for cleaner query execution
                sparql = SPARQLWrapper(update_url)
                sparql.setCredentials("admin", "admin")
                sparql.setMethod(POST)
                sparql.setQuery(sparql_query)
                sparql.query()
            except Exception as e:
                logger.error(f"Error inserting triples into {kb_id}: {e}")
                return False
                
        return True

    def query_sparql(self, kb_id: str, query: str) -> dict:
        """Execute a SPARQL SELECT query."""
        dataset_url = self._get_dataset_url(kb_id)
        query_url = f"{dataset_url}/query"
        
        try:
            sparql = SPARQLWrapper(query_url)
            sparql.setCredentials("admin", "admin")
            sparql.setQuery(query)
            sparql.setReturnFormat(JSON)
            results = sparql.query().convert()
            return results
        except Exception as e:
            logger.error(f"Error executing SPARQL query on {kb_id}: {e}")
            return {}

    def update_sparql(self, kb_id: str, update_query: str) -> bool:
        """Execute a SPARQL UPDATE query (INSERT/DELETE)."""
        dataset_url = self._get_dataset_url(kb_id)
        update_url = f"{dataset_url}/update"
        
        try:
            sparql = SPARQLWrapper(update_url)
            sparql.setCredentials("admin", "admin")
            sparql.setMethod(POST)
            sparql.setQuery(update_query)
            sparql.query()
            return True
        except Exception as e:
            logger.error(f"Error executing SPARQL update on {kb_id}: {e}")
            return False

fuseki_client = FusekiClient()
