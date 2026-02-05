"""Neo4j 로더 - Cypher 실행"""

from pathlib import Path
from typing import Union, Optional,  Optional, Union

# .env 로드
from dotenv import load_dotenv
load_dotenv()


class Neo4jLoader:
    """Neo4j에 그래프 적재"""
    
    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        user: str = "neo4j",
        password: str = "",
        database: str = "neo4j",
    ):
        self.uri = uri
        self.user = user
        self.password = password
        self.database = database
        self._driver = None
    
    def connect(self) -> dict:
        """Neo4j 연결"""
        try:
            from neo4j import GraphDatabase
            self._driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password)
            )
            # 연결 테스트
            with self._driver.session(database=self.database) as session:
                result = session.run("RETURN 1 AS test")
                result.single()
            return {"success": True, "message": f"Connected to {self.uri}"}
        except ImportError:
            return {
                "success": False,
                "message": "neo4j 패키지가 설치되지 않았습니다. pip install neo4j"
            }
        except Exception as e:
            return {"success": False, "message": f"연결 실패: {e}"}
    
    def close(self):
        """연결 종료"""
        if self._driver:
            self._driver.close()
            self._driver = None
    
    def execute_cypher_file(
        self,
        cypher_path: Union[str, Path],
        dry_run: bool = False,
    ) -> dict:
        """Cypher 파일 실행"""
        cypher_path = Path(cypher_path)
        
        if not cypher_path.exists():
            return {"success": False, "message": f"파일 없음: {cypher_path}"}
        
        with open(cypher_path, "r", encoding="utf-8") as f:
            cypher = f.read()
        
        return self.execute_cypher(cypher, dry_run=dry_run)
    
    def execute_cypher(
        self,
        cypher: str,
        dry_run: bool = False,
    ) -> dict:
        """Cypher 실행"""
        # 문장 분리
        statements = []
        for stmt in cypher.split(";"):
            stmt = stmt.strip()
            if stmt and not stmt.startswith("//"):
                statements.append(stmt)
        
        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "message": f"Dry-run: {len(statements)}개 문장",
                "statement_count": len(statements),
            }
        
        if not self._driver:
            conn = self.connect()
            if not conn["success"]:
                return conn
        
        executed = 0
        errors = []
        
        with self._driver.session(database=self.database) as session:
            for stmt in statements:
                try:
                    session.run(stmt)
                    executed += 1
                except Exception as e:
                    # 에러가 발생해도 중단하지 않고 계속 진행
                    # (최대 10개까지만 에러 상세 내용 저장)
                    if len(errors) < 10:
                        errors.append(f"{stmt[:50]}...: {e}")
        
        if errors:
            return {
                "success": False,
                "message": f"실행됨: {executed}, 에러: {len(errors)}",
                "executed": executed,
                "errors": errors[:5],
            }
        
        return {
            "success": True,
            "message": f"{executed}개 문장 실행 완료",
            "executed": executed,
        }
    
    def clear(self, dry_run: bool = False) -> dict:
        """데이터베이스 초기화"""
        if dry_run:
            return {"success": True, "dry_run": True, "message": "Dry-run: 삭제 예정"}
        
        return self.execute_cypher("MATCH (n) DETACH DELETE n")
    
    def get_stats(self) -> dict:
        """통계 조회"""
        if not self._driver:
            conn = self.connect()
            if not conn["success"]:
                return conn
        
        try:
            with self._driver.session(database=self.database) as session:
                nodes = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
                rels = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
            
            return {
                "success": True,
                "nodes": nodes,
                "relationships": rels,
            }
        except Exception as e:
            return {"success": False, "message": str(e)}
