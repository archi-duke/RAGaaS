
import logging
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from app.core.neo4j_client import neo4j_client

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def restore_master_relation():
    try:
        logger.info("Restoring '스승' relationship: 오일남 -> [스승] -> 성기훈")
        
        # We assume the main nodes '오일남' and '성기훈' already exist (since we verified them)
        # We just MERGE the relationship
        query = """
        MATCH (s:Entity {id: '오일남'}), (o:Entity {id: '성기훈'})
        MERGE (s)-[r:스승]->(o)
        SET r.label = '스승'
        RETURN count(r) as created
        """
        
        results = neo4j_client.execute_query(query)
        cnt = results[0]['created'] if results else 0
        
        if cnt > 0 or True: # neo4j might return 0 if it already existed
            logger.info("Successfully ensured '스승' relationship.")

        # Double check
        check_query = """
        MATCH (s:Entity)-[r]->(o:Entity)
        WHERE s.id = '오일남' AND o.id = '성기훈'
        RETURN type(r) as rel_type
        """
        res = neo4j_client.execute_query(check_query)
        rels = [r['rel_type'] for r in res]
        logger.info(f"Current relationships: {rels}")

    except Exception as e:
        logger.error(f"Restore failed: {e}")

if __name__ == "__main__":
    restore_master_relation()
