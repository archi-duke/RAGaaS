"""Fuseki 로더"""

from pathlib import Path
from typing import Union, Optional,  Optional, Union
import requests


class FusekiLoader:
    """Fuseki에 TriG 파일 업로드"""
    
    def __init__(
        self,
        endpoint: Optional[str] = None,
        dataset: str = "ds",
    ):
        """
        Args:
            endpoint: Fuseki 엔드포인트 (e.g., http://localhost:3030)
            dataset: 데이터셋 이름
        """
        self.endpoint = endpoint
        self.dataset = dataset
    
    @property
    def gsp_url(self) -> Optional[str]:
        """Graph Store Protocol URL"""
        if self.endpoint:
            return f"{self.endpoint.rstrip('/')}/{self.dataset}/data"
        return None
    
    @property
    def sparql_url(self) -> Optional[str]:
        """SPARQL 엔드포인트 URL"""
        if self.endpoint:
            return f"{self.endpoint.rstrip('/')}/{self.dataset}/sparql"
        return None
    
    def upload(
        self,
        trig_path: Union[str, Path],
        graph_uri: Optional[str] = None,
        dry_run: bool = False,
    ) -> dict:
        """TriG 파일 업로드
        
        Args:
            trig_path: TriG 파일 경로
            graph_uri: 대상 그래프 URI (None이면 파일의 Named Graph 사용)
            dry_run: True면 실제 업로드 없이 파일 유효성만 확인
            
        Returns:
            업로드 결과 {"success": bool, "message": str, ...}
        """
        trig_path = Path(trig_path)
        
        if not trig_path.exists():
            return {
                "success": False,
                "message": f"File not found: {trig_path}",
            }
        
        with open(trig_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        if dry_run or not self.endpoint:
            return {
                "success": True,
                "dry_run": True,
                "message": f"Dry-run: would upload {len(content)} bytes to {self.gsp_url or 'N/A'}",
                "file": str(trig_path),
                "size_bytes": len(content),
            }
        
        # 실제 업로드
        try:
            url = self.gsp_url
            if graph_uri:
                url = f"{url}?graph={graph_uri}"
            
            response = requests.post(
                url,
                data=content.encode("utf-8"),
                headers={"Content-Type": "application/trig"},
                timeout=60,
            )
            response.raise_for_status()
            
            return {
                "success": True,
                "message": f"Uploaded to {url}",
                "status_code": response.status_code,
                "file": str(trig_path),
            }
        except requests.RequestException as e:
            return {
                "success": False,
                "message": f"Upload failed: {e}",
                "file": str(trig_path),
            }
    
    def query(self, sparql: str, dry_run: bool = False) -> dict:
        """SPARQL 쿼리 실행
        
        Args:
            sparql: SPARQL 쿼리 문자열
            dry_run: True면 실제 실행 없이 반환
            
        Returns:
            쿼리 결과
        """
        if dry_run or not self.endpoint:
            return {
                "success": True,
                "dry_run": True,
                "message": "Dry-run: query not executed",
                "query": sparql[:100] + "..." if len(sparql) > 100 else sparql,
            }
        
        try:
            response = requests.post(
                self.sparql_url,
                data={"query": sparql},
                headers={"Accept": "application/sparql-results+json"},
                timeout=60,
            )
            response.raise_for_status()
            
            return {
                "success": True,
                "results": response.json(),
            }
        except requests.RequestException as e:
            return {
                "success": False,
                "message": f"Query failed: {e}",
            }
    
    def clear_graph(self, graph_uri: str, dry_run: bool = False) -> dict:
        """그래프 삭제
        
        Args:
            graph_uri: 삭제할 그래프 URI
            dry_run: True면 실제 삭제 없이 반환
        """
        if dry_run or not self.endpoint:
            return {
                "success": True,
                "dry_run": True,
                "message": f"Dry-run: would drop graph {graph_uri}",
            }
        
        sparql = f"DROP GRAPH <{graph_uri}>"
        return self.query(sparql)
