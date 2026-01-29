
from neo4j import GraphDatabase
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

class Neo4jClient:
    def __init__(self):
        self.driver = None
        self.uri = settings.NEO4J_URI
        self.user = settings.NEO4J_USER
        self.password = settings.NEO4J_PASSWORD
        
        if self.uri:
            try:
                self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
                logger.info("Initialized Neo4j driver")
            except Exception as e:
                logger.error(f"Failed to initialize Neo4j driver: {e}")

    def close(self):
        if self.driver:
            self.driver.close()

    def execute_query(self, query: str, parameters: dict = None, db: str = None):
        """Execute a Cypher query."""
        if not self.driver:
            logger.error("Neo4j driver not initialized")
            return []

        try:
            records, summary, keys = self.driver.execute_query(
                query, 
                parameters_=parameters,
                database_=db
            )
            return records
        except Exception as e:
            logger.error(f"Error executing Neo4j query: {e}")
            raise e

    def verify_connectivity(self):
        if not self.driver:
            return False
        try:
            self.driver.verify_connectivity()
            return True
        except Exception as e:
            logger.error(f"Neo4j connectivity check failed: {e}")
            return False

# Global instance
neo4j_client = Neo4jClient()
